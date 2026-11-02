"""Escritura de overrides `&label { … }` sobre el texto fuente.

Es la contrapartida de `dt_model.model.resolve_label_overrides`: donde eso
lee un `&label`/`&{path}` como una modificación del nodo real en vez de un
nodo suelto, esto escribe uno -o actualiza el que ya hubiera- para que la
próxima lectura vuelva a fundirlo en su sitio. Nada en el proyecto escribía
hasta ahora sobre el `.dts` fusionado; el panel de propiedades del SoC es el
primer caso, así que el alcance se limita a lo que pide: cambiar el `status`
de un controlador integrado, no una edición de propiedades genérica.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from kernelgrove.dts_engine import find_matching_brace, parse_dts_source


@dataclass(frozen=True)
class PropertyOverride:
    """Un cambio a aplicar sobre el nodo referenciado por `label` (o, si no
    tiene, por su `path` completo): la propiedad `name` debe pasar a valer
    `value`, ya como literal DTS (p. ej. `'"okay"'`, comillas incluidas)."""

    label: Optional[str]
    path: str
    name: str
    value: str

    @property
    def reference(self) -> str:
        """Forma `&label` o `&{/path}` con la que se reabre el nodo."""
        return f"&{self.label}" if self.label else f"&{{{self.path}}}"


def apply_overrides(text: str, overrides: List[PropertyOverride]) -> str:
    """Aplica cada cambio como un bloque `&label { … }` / `&{/path} { … }`.

    Si el documento ya reabre ese nodo en un bloque de ese tipo, la
    propiedad se inserta o sustituye ahí dentro; si no, se añade un bloque
    nuevo al final del fichero. Es exactamente la forma que
    `resolve_label_overrides` sabe leer, así que el ciclo edición ->
    reanálisis -> grafo se cierra sin necesitar nada más.
    """
    for override in overrides:
        text = _apply_one(text, override)
    return text


def _apply_one(text: str, override: PropertyOverride) -> str:
    """Localiza (si existe) el bloque de este documento que reabre el nodo."""
    result = parse_dts_source(text)
    block = next(
        (child for child in result.root.children if child.name == override.reference),
        None,
    )

    if block is not None and block.line is not None:
        patched = _patch_block(text, block.line, override)
        if patched is not None:
            return patched

    return _append_block(text, override)


def _patch_block(
    text: str, open_line: int, override: PropertyOverride
) -> Optional[str]:
    """Inserta o sustituye la propiedad dentro de un bloque ya existente.

    Devuelve `None` si la llave de apertura resulta huérfana: mejor añadir
    un bloque nuevo (`_append_block`) que arriesgarse a cortar el fichero
    por un sitio equivocado.
    """
    lines = text.splitlines(keepends=True)
    line_start = sum(len(line) for line in lines[: open_line - 1])
    open_index = text.index("{", line_start)

    close_index = find_matching_brace(text, open_index)
    if close_index is None:
        return None

    block_text = text[open_index + 1 : close_index]
    pattern = re.compile(
        rf"^[ \t]*{re.escape(override.name)}\s*=.*?;[ \t]*$", re.MULTILINE
    )
    match = pattern.search(block_text)
    new_line = f"\t{override.name} = {override.value};"
    if match:
        new_block = block_text[: match.start()] + new_line + block_text[match.end() :]
    else:
        new_block = block_text.rstrip(" \t\n") + f"\n{new_line}\n"

    return text[: open_index + 1] + new_block + text[close_index:]


def node_span(text: str, line: int) -> Optional[tuple]:
    """Trozo de `text` que ocupa el nodo que abre en `line`, o None.

    Devuelve `(inicio, fin)` en posiciones de carácter, contando desde el
    principio de la línea de apertura hasta el `}` que la cierra, su `;` y
    el salto de línea si no queda nada más escrito ahí. Es lo que hace falta
    para borrar un nodo del fuente sin arrastrar lo que tenga al lado.

    Se devuelve el tramo y no el texto ya recortado a propósito: quien
    borra lo hace sobre el `QTextDocument` del editor, y así el borrado
    entra en su pila de deshacer como una edición más.

    None si la línea no abre ningún nodo o si su llave está huérfana: mejor
    no tocar nada que cortar el fichero por un sitio equivocado.
    """
    lines = text.splitlines(keepends=True)
    if line < 1 or line > len(lines):
        return None

    start = sum(len(item) for item in lines[: line - 1])
    # La llave tiene que estar en esa misma línea: la cabecera de un nodo
    # (`nombre@dirección {`) acaba en ella. Buscándola por todo el texto, una
    # línea sin llave se llevaría por delante el nodo siguiente.
    open_index = text.find("{", start, start + len(lines[line - 1]))
    if open_index < 0:
        return None

    close_index = find_matching_brace(text, open_index)
    if close_index is None:
        return None

    end = close_index + 1
    if text[end : end + 1] == ";":
        end += 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    if not text[end:line_end].strip():
        end = min(line_end + 1, len(text))
    return start, end


def _append_block(text: str, override: PropertyOverride) -> str:
    """Añade al final del fichero un bloque nuevo para el nodo referenciado."""
    separator = "" if text.endswith("\n") else "\n"
    return (
        f"{text}{separator}\n{override.reference} {{\n"
        f"\t{override.name} = {override.value};\n}};\n"
    )
