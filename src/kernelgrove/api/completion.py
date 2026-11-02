"""Contexto del cursor para el autocompletado del editor.

Averigua, mirando el texto y sin volver a analizarlo, en qué nodo está el
cursor y qué `compatible` tiene ese nodo. Se hace sobre el texto y no sobre el
árbol por dos razones: mientras se escribe, el árbol es el del último análisis
—que va con retraso— y volver a analizar en cada tecla no es viable.

El recorrido es local: hacia atrás hasta la llave que abre el nodo y hacia
delante hasta la que lo cierra, así que cuesta lo que ocupe el nodo, no el
fichero.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# `compatible = "vendor,modelo"`, con el primer valor, que es el que manda.
_COMPATIBLE_RE = re.compile(r'compatible\s*=\s*"([^"]+)"')

# Cabecera de nodo: `nombre@dir {`, `label: nombre {`, `&label {`.
_HEADER_RE = re.compile(
    r"(?:(?P<label>[A-Za-z_][\w-]*)\s*:\s*)?(?P<name>[^\s{};]+)\s*$"
)

# Nombre de la propiedad que se está escribiendo, cuando el cursor está en su
# valor: `clock-frequency = <`.
_PROPERTY_RE = re.compile(r"([#A-Za-z0-9_,.+-]+)\s*=")

# Cadena completa entre comillas, para enmascararla.
_STRING_RE = re.compile(r'"[^"]*"')


@dataclass(frozen=True)
class CompletionContext:
    """Dónde está el cursor, a efectos de sugerir algo."""

    # Nombre del nodo que lo contiene, tal y como está escrito.
    node_name: str = ""
    # Compatible declarado dentro de ese nodo, si lo declara.
    compatible: Optional[str] = None
    # Etiqueta a la que apunta, si el nodo es una reapertura `&label { … }`:
    # entonces el compatible está en el fichero donde se definió.
    reference: Optional[str] = None
    # Propiedad cuyo valor se está escribiendo, si el cursor está en un valor.
    property_name: Optional[str] = None

    @property
    def inside_node(self) -> bool:
        """Indica si el cursor está dentro de algún nodo."""
        return bool(self.node_name)


def context_at(text: str, position: int) -> CompletionContext:
    """Devuelve el contexto del cursor en `position` dentro de `text`."""
    masked = _mask(text)
    start = _enclosing_node_start(masked, position)
    if start is None:
        return CompletionContext(property_name=_property_at(text, position))

    header = _header_before(masked, start)
    name, reference = _split_header(header)
    return CompletionContext(
        node_name=name,
        compatible=_compatible_of(text, masked, start),
        reference=reference,
        property_name=_property_at(text, position),
    )


def _mask(text: str) -> str:
    """Devuelve el texto con cadenas y comentarios en blanco, misma longitud.

    Enmascarar en vez de quitar deja intactas las posiciones, que es lo que
    permite contar llaves con seguridad y volver luego al texto original a
    leer el `compatible`. Se hace por líneas porque mientras se escribe hay
    cadenas sin cerrar (`status = "ok`), y una comilla suelta descuadraría el
    emparejado del resto del fichero.
    """
    return "\n".join(_mask_line(line) for line in text.split("\n"))


def _mask_line(line: str) -> str:
    """Enmascara cadenas y comentarios de una línea, conservando su longitud."""
    masked = _STRING_RE.sub(lambda match: " " * len(match.group()), line)
    for marker in ("//", "/*"):
        comment = masked.find(marker)
        if comment != -1:
            masked = masked[:comment] + " " * (len(masked) - comment)
    quote = masked.find('"')
    if quote != -1:
        # Cadena sin cerrar: lo que queda de línea es su contenido.
        masked = masked[:quote] + " " * (len(masked) - quote)
    return masked


def _enclosing_node_start(masked: str, position: int) -> Optional[int]:
    """Posición de la llave que abre el nodo donde está el cursor.

    Recibe el texto ya enmascarado y recorre hacia atrás contando llaves: la
    primera sin cerrar es la del nodo. Solo llega tan atrás como haga falta,
    así que cuesta lo que ocupe el nodo y no el fichero.
    """
    depth = 0
    index = min(position, len(masked)) - 1
    while index >= 0:
        char = masked[index]
        if char == "}":
            depth += 1
        elif char == "{":
            if depth == 0:
                return index
            depth -= 1
        index -= 1
    return None


def _header_before(text: str, brace: int) -> str:
    """Texto de la cabecera del nodo que abre esa llave."""
    start = brace
    while start > 0 and text[start - 1] not in "{};\n":
        start -= 1
    return text[start:brace].strip()


def _split_header(header: str) -> tuple:
    """Separa la cabecera en (nombre del nodo, referencia)."""
    if not header:
        return ("", None)
    if header.startswith("&"):
        body = header[1:].strip()
        if body.startswith("{") and body.endswith("}"):
            return (header, None)
        return (header, body)

    match = _HEADER_RE.search(header)
    name = match.group("name") if match else header
    return (name, None)


def _compatible_of(text: str, masked: str, brace: int) -> Optional[str]:
    """Primer `compatible` declarado en el cuerpo del nodo que abre esa llave.

    Se busca en el texto original —hay que leer el valor— pero los límites del
    cuerpo se calculan sobre el enmascarado. Solo cuenta el cuerpo del propio
    nodo: en cuanto empieza un hijo, lo que hay dentro ya no es suyo.
    """
    depth = 0
    index = brace
    length = len(masked)
    body_start = brace + 1
    while index < length:
        char = masked[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                break
        index += 1

    body_end = index
    child = masked.find("{", body_start, body_end)
    if child != -1:
        body_end = child

    match = _COMPATIBLE_RE.search(text[body_start:body_end])
    return match.group(1) if match else None


def _property_at(text: str, position: int) -> Optional[str]:
    """Propiedad cuyo valor se está escribiendo, si el cursor está en uno."""
    line_start = text.rfind("\n", 0, position) + 1
    line = text[line_start:position]
    if "=" not in line:
        return None
    match = _PROPERTY_RE.search(line)
    return match.group(1) if match else None
