"""Índice de macros de las cabeceras `dt-bindings/*.h` (capa 3).

La capa 3 del motor semántico (`dts_engine/checks/macros.py`) tiene dos
niveles, y esta ingesta llena los dos:

- **Existencia**, siempre: un `#\\s*define NOMBRE` por cabecera —sin
  preprocesador— leído de la tabla `sources`, que ya guarda el texto de las
  7,5k cabeceras. Cada cabecera se indexa con el cierre transitivo de lo que
  declara ella misma más lo que declaran las cabeceras que a su vez incluye
  (el grafo es minúsculo, 24 aristas en todo `dt-bindings/`).
- **Valor**, solo si hay checkout del kernel y `cpp` en el sistema
  (`resolve_macro_values`): expandir de verdad una macro exige el
  preprocesador —parámetros de macros de función, referencias anidadas a
  otras macros, aritmética de bits— y reimplementarlo a mano sería repetir mal
  lo que `cpp` ya hace bien. Se le pide que expanda cada nombre en el
  contexto de su cabecera (`#include "…"` seguido de una línea por nombre,
  todo en una sola invocación) y lo que queda, si es una expresión de solo
  números y operadores, se evalúa aquí con un intérprete mínimo y restringido
  —nunca sobre texto que no haya pasado antes por `cpp`, y `cpp` solo corre
  aquí, en ingesta, contra el checkout del kernel: nunca en tiempo de
  análisis ni sobre texto del usuario.

Una macro de función sin argumentos (`GIC_CPU_MASK_RAW`) se queda sin
resolver: cpp la devuelve tal cual, sin expandir, y eso es la señal de que no
hay un valor constante que guardar. Se mantiene en el índice de existencia
igualmente.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import subprocess
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

_DEFINE_RE = re.compile(r"^\s*#\s*define\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*[<"]([^">]+)[>"]', re.MULTILINE)

# Marca cada consulta en la entrada de `cpp` y localiza su respuesta en la
# salida sin depender de que las líneas se conserven una a una.
_MARKER_PREFIX = "__KERNELGROVE__"
_MARKER_SUFFIX = "__"
_ANSWER_RE = re.compile(
    rf"^{_MARKER_PREFIX}(?P<name>[A-Za-z_][A-Za-z0-9_]*){_MARKER_SUFFIX}\s+(?P<expr>.*)$",
    re.MULTILINE,
)

# Solo dígitos (con prefijo hex/octal), espacio y los operadores enteros de C
# que `cpp` puede dejar sin reducir (no evalúa aritmética fuera de `#if`).
# Cualquier otro carácter —una `,` de una lista, una letra que no sea de un
# literal hex— hace que se descarte en vez de forzar una lectura.
_SAFE_EXPR_RE = re.compile(r"^[\s0-9a-fA-Fx()+\-*/%<>|&~^]+$")
_INT_SUFFIX_RE = re.compile(r"\b(0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*\b")


def extract_macro_names(text: str) -> Set[str]:
    """Nombres declarados con `#define` en `text` (de objeto o de función).

    Para una macro de función (`#define GIC_CPU_MASK_RAW(x) ((x) << 8)`) se
    registra el nombre igualmente: existencia no distingue las dos formas,
    solo el paso de resolución de valor las trata distinto.
    """
    return set(_DEFINE_RE.findall(text))


def extract_local_includes(text: str) -> List[str]:
    """Objetivos de los `#include` propios de una cabecera."""
    return _INCLUDE_RE.findall(text)


def _resolve_target(target: str, paths: List[str]) -> Optional[str]:
    """Empareja un `#include` con la cabecera de `sources` a la que apunta.

    Mismo criterio que `SourcesDatabase.find_by_suffix`: la ruta del
    `#include` es parcial (`dt-bindings/interrupt-controller/irq.h`), así que
    se busca la almacenada que termina en ella, y la más corta si hay varias.
    """
    normalized = target.replace("\\", "/").lstrip("./")
    candidates = [
        path
        for path in paths
        if path == normalized or path.endswith(f"/{normalized}")
    ]
    if not candidates:
        return None
    return min(candidates, key=len)


def cpp_binary() -> Optional[str]:
    """Localiza un preprocesador de C utilizable, o None si no hay ninguno."""
    for candidate in ("cpp", "gcc", "cc"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _strip_int_suffixes(text: str) -> str:
    """Quita los sufijos de tipo (`5U`, `0x10UL`) que `int(...)` no acepta."""
    return _INT_SUFFIX_RE.sub(lambda match: match.group(1), text)


def evaluate_c_int_expr(text: str) -> Optional[int]:
    """Evalúa una expresión entera de C ya expandida por `cpp`.

    Después de la expansión solo deberían quedar números y operadores: si
    queda cualquier otra cosa (un identificador que no se pudo resolver, una
    coma) se descarta en vez de intentar leerlo. `eval` corre sobre una
    cadena ya filtrada por `_SAFE_EXPR_RE` y sin builtins, nunca sobre texto
    que no haya pasado antes por `cpp` contra el checkout del kernel.
    """
    candidate = _strip_int_suffixes(text.strip())
    if not candidate or not _SAFE_EXPR_RE.match(candidate):
        return None
    try:
        result = eval(candidate, {"__builtins__": {}}, {})  # noqa: S307
    except Exception:
        return None
    return result if isinstance(result, int) else None


def _include_target(header_path: str, include_root: str) -> Optional[str]:
    """Ruta que hay que escribir en `#include "…"` para `header_path`.

    `include_root` es la única raíz `-I` que hace falta: los 24 `#include`
    internos de `dt-bindings/` son o relativos al propio directorio o
    `<dt-bindings/…>`, así que basta un `-I` apuntando a `include/`.
    """
    prefix = include_root.rstrip("/") + "/"
    if not header_path.startswith(prefix):
        return None
    return header_path[len(prefix) :]


def resolve_macro_values(
    header_path: str,
    names: Sequence[str],
    include_root: str,
    binary: str,
) -> Dict[str, int]:
    """Pide a `cpp` el valor de cada nombre de `names`, visto desde `header_path`.

    Una sola invocación por cabecera: se incluye una vez y se listan todos
    los nombres detrás, cada uno envuelto en una marca que sobrevive a que
    `cpp` reordene o junte líneas en blanco. Los que no se puedan evaluar
    como un entero (macros de función sin argumentos, expresiones con algo
    que no sea número) simplemente no aparecen en el resultado.
    """
    target = _include_target(header_path, include_root)
    if target is None or not names:
        return {}

    lines = [f'#include "{target}"']
    lines.extend(f"{_MARKER_PREFIX}{name}{_MARKER_SUFFIX} {name}" for name in names)

    args = [binary, "-nostdinc", "-P", "-I", include_root, "-"]
    if Path(binary).name in ("gcc", "cc"):
        args.insert(1, "-E")

    try:
        completed = subprocess.run(
            args,
            input="\n".join(lines) + "\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}

    values: Dict[str, int] = {}
    for match in _ANSWER_RE.finditer(completed.stdout):
        name = match.group("name")
        expr = match.group("expr").strip()
        if expr == name:
            # Sin expandir: macro de función referenciada sin paréntesis, o
            # (más raro) un `#define` que el regex vio pero un `#ifdef`
            # descartó de verdad. Ninguno de los dos tiene valor que guardar.
            continue
        value = evaluate_c_int_expr(expr)
        if value is not None:
            values[name] = value
    return values


def build_header_macro_records(
    sqlite_path: Path, include_root: Optional[str] = None
) -> List[Dict[str, object]]:
    """Lee las cabeceras ya guardadas en `sources` y construye el índice.

    Requiere que la tabla `sources` ya esté poblada (`--table sources`). Con
    `include_root` (una ruta relativa a la raíz del repo, típicamente
    `kernel/linux/include`) y `cpp` disponible, además resuelve el valor de
    cada macro; sin alguno de los dos, el índice se queda solo con
    existencia — degradado, no roto, igual que el resto de la ingesta ante
    dependencias opcionales.
    """
    conn = sqlite3.connect(str(sqlite_path))
    try:
        rows = conn.execute(
            "SELECT path, source FROM sources WHERE kind = 'header'"
        ).fetchall()
    finally:
        conn.close()

    texts: Dict[str, str] = {
        path: zlib.decompress(blob).decode("utf-8", errors="replace")
        for path, blob in rows
    }
    paths = list(texts)

    own_names: Dict[str, Set[str]] = {
        path: extract_macro_names(text) for path, text in texts.items()
    }
    own_includes: Dict[str, List[str]] = {
        path: extract_local_includes(text) for path, text in texts.items()
    }

    def closure(path: str, visited: Set[str]) -> Set[str]:
        """Nombres visibles al incluir `path`: los suyos y los de su cascada."""
        if path in visited:
            return set()
        visited.add(path)
        names = set(own_names.get(path, ()))
        for target in own_includes.get(path, ()):
            nested = _resolve_target(target, paths)
            if nested is not None:
                names |= closure(nested, visited)
        return names

    closures: Dict[str, Set[str]] = {path: closure(path, set()) for path in paths}

    binary = cpp_binary() if include_root is not None else None
    values_by_header: Dict[str, Dict[str, int]] = {}
    if binary is not None:
        for path, names in closures.items():
            if names:
                values_by_header[path] = resolve_macro_values(
                    path, sorted(names), include_root, binary
                )

    records: List[Dict[str, object]] = []
    for path, names in closures.items():
        header_values = values_by_header.get(path, {})
        for name in names:
            records.append(
                {
                    "name": name,
                    "header_path": path,
                    "value": header_values.get(name),
                }
            )
    return records
