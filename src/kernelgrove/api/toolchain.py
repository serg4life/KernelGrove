"""Herramientas externas para compilar un overlay: `cpp` y `dtc`.

**No se empaquetan.** La aplicación funciona entera sin ellas —generar,
validar y previsualizar un overlay es Python puro sobre la base de datos— y
solo «Compilar y exportar» las necesita. Si faltan, esa acción explica cómo
instalarlas en vez de fallar.

Es el mismo trato que ya recibe `cpp` en la ingesta de macros
(`db_manager.macros.cpp_binary`) y que la librería `libxcb-cursor0` en el
arranque (`main._missing_xcb_runtime_deps`): se busca, y si no está, el
mensaje dice qué instalar. La diferencia es que aquello corre en la máquina
de quien construye la base y esto en la del usuario, así que el mensaje
importa más.

Dos detalles que no son evidentes:

- **Son dos programas, no uno.** `dtc` no preprocesa: un overlay con
  `#include <dt-bindings/gpio/gpio.h>` necesita pasar antes por `cpp`.
- **Se comprueba la capacidad, no la versión.** El `-@` que exporta los
  símbolos no existe en las versiones antiguas de `dtc`, y las
  distribuciones de soporte largo arrastran versiones viejas. Comparar
  números de versión es frágil y envejece; preguntarle a la propia
  herramienta si acepta el flag es directo.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

# Candidatos por orden de preferencia. `cpp` es el preprocesador suelto;
# `gcc`/`cc`/`clang` hacen lo mismo con `-E`.
CPP_CANDIDATES = ("cpp", "gcc", "cc", "clang")
DTC_CANDIDATES = ("dtc",)

# Cuánto se espera a que una herramienta conteste a `--help`. Es una sonda,
# no una compilación: si tarda más, algo va mal y no conviene bloquear la
# interfaz por ello.
PROBE_TIMEOUT_S = 5

# Windows abre una consola por cada `subprocess.run` cuando la aplicación se
# empaqueta sin ella (`console=False` en `packaging/windows/kernelgrove.spec`), y
# estas sondas corren al arrancar y cada vez que se abre «Acerca de»: sin esto
# parpadea una ventana negra. En el resto de sistemas la bandera no existe y
# vale 0. Mismo apaño que `git_repo._NO_WINDOW`.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class Toolchain:
    """Qué herramientas de compilación hay disponibles, y cuáles no."""

    cpp: Optional[str] = None
    dtc: Optional[str] = None
    # Si el `dtc` encontrado acepta `-@`, el flag que hace que el binario
    # exporte `__symbols__`. Sin él, un overlay que apunte por etiqueta no
    # podrá resolverse al aplicarse sobre este árbol.
    dtc_supports_symbols: bool = False

    @property
    def can_compile(self) -> bool:
        """Si se puede compilar un overlay de principio a fin."""
        return self.cpp is not None and self.dtc is not None

    @property
    def missing(self) -> List[str]:
        """Nombres de lo que falta, para construir el mensaje de ayuda."""
        return [
            name
            for name, found in (("cpp", self.cpp), ("dtc", self.dtc))
            if found is None
        ]


def detect_toolchain() -> Toolchain:
    """Busca `cpp` y `dtc` en el sistema y sondea qué sabe hacer `dtc`."""
    cpp = _first_on_path(CPP_CANDIDATES)
    dtc = _first_on_path(DTC_CANDIDATES)
    return Toolchain(
        cpp=cpp,
        dtc=dtc,
        dtc_supports_symbols=_supports_symbols(dtc) if dtc else False,
    )


def _first_on_path(candidates: Sequence[str]) -> Optional[str]:
    """Ruta del primer candidato que esté instalado, o `None`.

    Se mira el `PATH` y, si ahí no está, el `tools/` que el instalador de
    Windows deja junto al ejecutable. En Windows no hay gestor de paquetes
    que ponga `dtc` en el `PATH` —el instalador las descarga al lado del
    programa, ver `packaging/windows/README.md`—, y buscarlas también ahí es
    lo que evita tener que tocar el `PATH` del usuario: es un cambio global
    por un programa concreto, y encima no alcanza a un proceso ya lanzado.
    """
    junto_al_binario = _bundled_tools_dir()
    for candidate in candidates:
        found = shutil.which(candidate)
        if found is None and junto_al_binario:
            found = shutil.which(candidate, path=junto_al_binario)
        if found:
            return found
    return None


def _bundled_tools_dir() -> Optional[str]:
    """El `tools/` junto al ejecutable empaquetado, si existe.

    Solo en modo `frozen`: en un checkout ese directorio no existe y mirarlo
    sería inventarse una ruta. Mismo criterio que `main._app_root`.
    """
    if not getattr(sys, "frozen", False):
        return None
    carpeta = Path(sys.executable).resolve().parent / "tools"
    return str(carpeta) if carpeta.is_dir() else None


def _supports_symbols(dtc: str) -> bool:
    """Si este `dtc` acepta `-@` (exportar `__symbols__`).

    Se mira su propia ayuda en vez de comparar números de versión: es lo que
    la herramienta dice de sí misma, y no hay que mantener una tabla de qué
    versión introdujo qué.
    """
    try:
        completed = subprocess.run(
            [dtc, "--help"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_S,
            check=False,
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    ayuda = f"{completed.stdout}\n{completed.stderr}"
    return "-@" in ayuda


def _probe_version(binary: Optional[str]) -> Optional[str]:
    """Número de versión que dice una herramienta, o `None`.

    `dtc --version` imprime «Version: DTC 1.7.0» y `cpp --version` algo como
    «cpp (Ubuntu 13.2.0-…) 13.2.0»: de los dos se saca el primer número con
    forma de versión, que es lo que cabe en una línea de una ficha. Si no
    está instalada, o contesta algo que no se reconoce, `None` — es mejor
    decir que no se sabe que inventar un número que luego no cuadra con lo
    que de verdad compila.
    """
    if binary is None:
        return None
    try:
        completed = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_S,
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    salida = f"{completed.stdout} {completed.stderr}"
    match = re.search(r"(\d+\.\d+[\w.\-]*)", salida)
    return match.group(1) if match else None


def dtc_version(tools: Toolchain) -> Optional[str]:
    """Versión del `dtc` encontrado, o `None` si no hay o no se reconoce."""
    return _probe_version(tools.dtc)


def cpp_version(tools: Toolchain) -> Optional[str]:
    """Versión del preprocesador encontrado, o `None`."""
    return _probe_version(tools.cpp)


def install_hint() -> str:
    """Cómo instalar lo que falta, en el sistema donde se está ejecutando.

    Se devuelve el texto entero, ya redactado, para que quien lo enseñe no
    tenga que componer nada — mismo criterio que
    `main._missing_xcb_runtime_deps`.
    """
    sistema = platform.system()
    if sistema == "Linux":
        return (
            "Debian/Ubuntu:  sudo apt install device-tree-compiler cpp\n"
            "Fedora/RHEL:    sudo dnf install dtc gcc\n"
            "Arch:           sudo pacman -S dtc gcc"
        )
    if sistema == "Darwin":
        return (
            "macOS (Homebrew):  brew install dtc\n"
            "(the preprocessor already ships with Xcode's Command Line Tools)"
        )
    if sistema == "Windows":
        return (
            "Run the KernelGrove installer again and tick «Compilation tools»:\n"
            "  it downloads dtc and a preprocessor next to the program.\n"
            "Or install them by hand and put them on the PATH:\n"
            "  «dtc» from MSYS2:  pacman -S mingw-w64-x86_64-dtc\n"
            "  «clang» from LLVM: https://releases.llvm.org"
        )
    return (
        "Install «dtc» (device-tree-compiler) and a C preprocessor "
        "(«cpp» or «clang»)."
    )
