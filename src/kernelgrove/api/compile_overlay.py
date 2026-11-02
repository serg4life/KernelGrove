"""Compilar un overlay a `.dtbo`, cuando el sistema tiene con qué.

Es la **única** parte de la herramienta de overlays que necesita programas
externos, y por eso vive aparte: todo lo demás —generar el fuente, resolver
los símbolos contra la base, previsualizar los cambios, validar— es Python
sobre la base de datos y funciona en una máquina recién instalada.

La tubería es la de siempre en device tree, y son dos pasos porque `dtc` no
preprocesa:

    cpp -nostdinc -undef -x assembler-with-cpp -I… overlay.dtso
      | dtc -@ -I dts -O dtb -o overlay.dtbo

Si algo falla, lo que interesa no es el código de salida sino **lo que dijo
la herramienta**: los avisos de `dtc` son buenos y aquí se devuelven enteros
para poder enseñarlos junto al resto de diagnósticos, en vez de reducirlo
todo a «error al compilar».
"""

from __future__ import annotations

import shlex
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

from kernelgrove.api.toolchain import (
    NO_WINDOW,
    Toolchain,
    detect_toolchain,
    install_hint,
)

# Un overlay no tarda nada en compilar; si pasa de aquí es que algo se ha
# quedado colgado esperando entrada.
COMPILE_TIMEOUT_S = 60


@dataclass
class CompileResult:
    """Cómo fue la compilación, con lo que dijeron las herramientas."""

    ok: bool
    output: Optional[Path] = None
    # Mensaje ya redactado para enseñar cuando no se pudo ni intentar
    # (falta `dtc` o `cpp`); incluye cómo instalarlos.
    unavailable: Optional[str] = None
    # Salida de error de cada paso, tal cual. Los avisos de `dtc` valen
    # aunque la compilación termine bien.
    messages: List[str] = field(default_factory=list)

    @property
    def has_messages(self) -> bool:
        """Si las herramientas dijeron algo que merezca enseñarse."""
        return any(message.strip() for message in self.messages)


def compile_source_file(
    source: Path,
    output: Path,
    include_dirs: Sequence[Path] = (),
    toolchain: Optional[Toolchain] = None,
) -> CompileResult:
    """Compila un `.dts`/`.dtso` **del disco**, con sus inclusiones.

    Distinto de `compile_overlay`, que escribe el texto en un temporal:
    ahí un `#include "sibling.dtsi"` no se resuelve, porque `cpp` lo busca
    junto al fichero que incluye y el fichero está en otro sitio. Un árbol
    completo vive de sus inclusiones, así que se compila donde está y la
    carpeta del propio fuente entra como `-I`.
    """
    tools = toolchain or detect_toolchain()
    if not tools.can_compile:
        return _sin_herramientas(tools.missing)

    with tempfile.TemporaryDirectory(prefix="kernelgrove-build-") as tmp:
        preprocesado = Path(tmp) / f"{source.stem}.pp.dts"
        mensajes: List[str] = []
        directorios = [source.parent, *include_dirs]
        orden = _cpp_command(tools, source, preprocesado, directorios)
        if _run(orden, mensajes) is not True:
            return CompileResult(ok=False, messages=mensajes)
        if _run(_dtc_command(tools, preprocesado, output), mensajes) is not True:
            return CompileResult(ok=False, messages=mensajes)
    return CompileResult(ok=True, output=output, messages=mensajes)


def decompile_blob(
    blob: Path, toolchain: Optional[Toolchain] = None
) -> CompileResult:
    """Devuelve el `.dts` legible de un `.dtb`/`.dtbo` ya compilado.

    El camino de vuelta de `compile_overlay`, y el único que no necesita
    `cpp`: un binario ya no tiene macros ni `#include` que preprocesar, así
    que basta `dtc -I dtb -O dts`. Por eso comprueba `tools.dtc` y no
    `can_compile`, que además pediría un preprocesador para nada.

    El texto vuelve en `messages[0]` en vez de escribirse a un fichero: lo
    que se hace con un árbol descompilado es leerlo, y quien llama ya sabe
    dónde enseñarlo.
    """
    tools = toolchain or detect_toolchain()
    if tools.dtc is None:
        return _sin_herramientas(["dtc"], "Decompiling")
    try:
        completed = subprocess.run(
            [tools.dtc, "-I", "dtb", "-O", "dts", "-@", str(blob)],
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT_S,
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return CompileResult(ok=False, messages=[str(exc)])

    if completed.returncode != 0:
        return CompileResult(ok=False, messages=[completed.stderr.strip()])
    # El aviso de `dtc` se conserva aparte del árbol: sale por stderr y
    # pegarlo dentro del `.dts` lo haría inválido.
    mensajes = [completed.stdout]
    if completed.stderr.strip():
        mensajes.append(completed.stderr.strip())
    return CompileResult(ok=True, output=blob, messages=mensajes)


def _sin_herramientas(
    missing: Sequence[str], verbo: str = "Compiling"
) -> CompileResult:
    """La respuesta cuando la máquina no tiene con qué, con cómo arreglarlo.

    Una sola: las tres entradas de este módulo daban el mismo mensaje con su
    propia copia, y una de ellas unía los nombres con un « y » castellano
    dentro de una frase en inglés —el texto que llega al registro es inglés,
    como el resto de lo que ve el usuario—.
    """
    faltan = " and ".join(f"«{name}»" for name in missing)
    return CompileResult(
        ok=False,
        unavailable=(
            f"{verbo} needs {faltan}, which is not on this system."
            f"\n\n{install_hint()}"
        ),
    )


def _cpp_command(
    tools: Toolchain,
    source: Path,
    target: Path,
    include_dirs: Sequence[Path],
) -> List[str]:
    """Orden de preprocesado, con la forma que espera un fuente de device tree.

    `assembler-with-cpp` es lo que usa el propio kernel para los `.dts`: le
    dice al preprocesador que no intente entender C, solo resolver
    `#include` y macros. Sin `-nostdinc`/`-undef` se colarían las cabeceras
    y las macros del sistema, que aquí no pintan nada.
    """
    command = [
        tools.cpp,
        "-nostdinc",
        "-undef",
        "-D__DTS__",
        "-x",
        "assembler-with-cpp",
    ]
    # `gcc`/`clang` necesitan `-E` para quedarse en el preprocesado; `cpp`
    # ya lo hace por definición y lo acepta igualmente.
    if Path(tools.cpp).name != "cpp":
        command.append("-E")
    for directory in include_dirs:
        command.extend(["-I", str(directory)])
    command.extend(["-o", str(target), str(source)])
    return command


def _dtc_command(tools: Toolchain, source: Path, target: Path) -> List[str]:
    """Orden de compilación. `-@` solo si este `dtc` lo admite."""
    command = [tools.dtc, "-I", "dts", "-O", "dtb"]
    if tools.dtc_supports_symbols:
        command.append("-@")
    command.extend(["-o", str(target), str(source)])
    return command


def _run(command: List[str], messages: List[str]) -> bool:
    """Ejecuta un paso y recoge lo que diga, salga bien o mal.

    La orden entera se apunta siempre, no solo cuando falla: compilar un
    device tree es `cpp` y luego `dtc` con sus `-I`, y cuando el resultado
    no es el esperado lo primero que hay que ver es con qué se ha llamado.
    Es lo que hace un `make V=1`, y es lo que se lee en el registro.

    Con `shlex.join` y no con un `" ".join`: así la línea se puede copiar al
    terminal y volver a lanzarla tal cual, aunque la carpeta del proyecto
    lleve espacios. Y se recogen **las dos salidas**, no solo el error: lo
    que se enseña en el registro es lo que se habría visto ejecutándolo a
    mano, y ahí no hay dos canales separados.
    """
    messages.append("$ " + shlex.join(command))
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT_S,
            check=False,
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        messages.append(f"{Path(command[0]).name}: {exc}")
        return False

    for salida in (completed.stdout, completed.stderr):
        if salida.strip():
            messages.append(salida.rstrip("\n"))
    return completed.returncode == 0
