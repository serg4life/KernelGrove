"""Lectura de valores de propiedades DTS tal y como los deja el parser.

El parser guarda cada propiedad como `True` (propiedad sin `=`, el valor
vacío del §2.3 de la especificación) o como el texto crudo que hay a la
derecha del `=`. Aquí se interpreta ese texto según la sintaxis del capítulo
6: componentes separados por comas, cadenas entre comillas, arrays de celdas
`<...>`, bytestrings `[...]` y referencias `&label`.

Nada de esto consulta bindings: son las formas que define el propio lenguaje.
Cuando un valor viene de una macro de `dt-bindings/*.h` no se puede resolver
en esta capa, y las comprobaciones que dependan del número concreto deben
abstenerse (`has_macro`).
"""

from __future__ import annotations

import re
import string
from typing import List, Optional

# Caracteres válidos en un identificador de macro de C.
_MACRO_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Invocación de macro con argumentos: `DIE_NODE(pmgr)`, `EFUSE(10, 27)`.
_MACRO_CALL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*\(.*\)$", re.DOTALL)

# `/bits/ 8 <...>` fija el ancho de las celdas (dtc); el prefijo no forma
# parte del valor.
_BITS_RE = re.compile(r"^/bits/\s*\d+\s*", re.IGNORECASE)

_HEX_DIGITS = set(string.hexdigits)


def is_empty_value(value: object) -> bool:
    """Indica si la propiedad se escribió sin `=` (valor vacío)."""
    return value is True


def raw_text(value: object) -> str:
    """Devuelve el texto crudo del valor, sin espacios sobrantes."""
    if value is True:
        return ""
    return str(value).strip()


def split_components(raw: str) -> List[str]:
    """Separa los componentes de un valor por las comas de primer nivel.

    Un valor puede concatenar varios componentes (`compatible = "a", "b";`,
    `example = <0xf00f0000 19>, "texto";`). Las comas dentro de `<>`, `[]`,
    `()` o de una cadena no separan nada.
    """
    components: List[str] = []
    current: List[str] = []
    depth = 0
    in_string = False
    index = 0
    length = len(raw)

    while index < length:
        char = raw[index]

        if in_string:
            current.append(char)
            if char == "\\" and index + 1 < length:
                current.append(raw[index + 1])
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            current.append(char)
        elif char == "\\":
            # Continuación de línea del preprocesador: el parser convierte el
            # salto en un espacio y deja la barra suelta dentro del valor.
            pass
        elif char in "<[(":
            depth += 1
            current.append(char)
        elif char in ">])":
            depth = max(0, depth - 1)
            current.append(char)
        elif char == "," and depth == 0:
            components.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1

    tail = "".join(current).strip()
    if tail:
        components.append(tail)
    return [component for component in components if component]


def strip_bits_prefix(component: str) -> str:
    """Quita el `/bits/ N` que puede preceder a un array de celdas."""
    return _BITS_RE.sub("", component.strip()).strip()


def is_string(component: str) -> bool:
    """Indica si el componente es una cadena entre comillas."""
    component = component.strip()
    return (
        len(component) >= 2 and component.startswith('"') and component.endswith('"')
    )


def unquote(component: str) -> str:
    """Devuelve el contenido de una cadena, sin las comillas."""
    return component.strip()[1:-1]


def is_cell_array(component: str) -> bool:
    """Indica si el componente es un array de celdas `<...>`."""
    component = strip_bits_prefix(component)
    return component.startswith("<") and component.endswith(">")


def cell_tokens(component: str) -> List[str]:
    """Devuelve las celdas de un array `<...>`, respetando los paréntesis.

    Una celda puede ser un número, una referencia `&label`, una macro o una
    expresión entre paréntesis (`<(1 << 3)>`), que cuenta como una sola.
    """
    component = strip_bits_prefix(component)
    if not is_cell_array(component):
        return []

    inner = component[1:-1]
    tokens: List[str] = []
    current: List[str] = []
    depth = 0
    index = 0
    length = len(inner)

    while index < length:
        char = inner[index]
        if char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth = max(0, depth - 1)
            current.append(char)
        elif char == "{" and depth == 0 and current and current[-1] == "&":
            # Referencia por ruta: `&{/soc/i2c@0}` es una sola celda.
            depth += 1
            current.append(char)
        elif char == "}":
            depth = max(0, depth - 1)
            current.append(char)
        elif char.isspace() and depth == 0:
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(char)
        index += 1

    if current:
        tokens.append("".join(current))
    return tokens


def string_list(raw: str) -> Optional[List[str]]:
    """Devuelve la lista de cadenas del valor, o None si no todas lo son."""
    components = split_components(raw)
    if not components:
        return None
    if not all(is_string(component) for component in components):
        return None
    return [unquote(component) for component in components]


def cells(raw: str) -> Optional[List[str]]:
    """Devuelve todas las celdas del valor, o None si no es un array de celdas."""
    components = split_components(raw)
    if not components:
        return None
    if not all(is_cell_array(component) for component in components):
        return None
    tokens: List[str] = []
    for component in components:
        tokens.extend(cell_tokens(component))
    return tokens


def number(token: str) -> Optional[int]:
    """Convierte una celda en número, o None si no es un literal.

    Devuelve None tanto para las macros (`GIC_SPI`) como para las
    referencias (`&uart0`) y las expresiones: no son valores que esta capa
    pueda resolver.
    """
    token = token.strip().rstrip("uUlL")
    if not token:
        return None
    try:
        return int(token, 0)
    except ValueError:
        return None


def is_number(token: str) -> bool:
    """Indica si la celda es un literal numérico."""
    return number(token) is not None


def is_reference(token: str) -> bool:
    """Indica si la celda es una referencia (`&label` o `&{/ruta}`)."""
    return token.strip().startswith("&")


def is_macro(token: str) -> bool:
    """Indica si la celda parece una macro sin expandir de una cabecera C."""
    token = token.strip()
    if is_number(token) or is_reference(token):
        return False
    return bool(_MACRO_RE.match(token))


def looks_like_macro_call(text: str) -> bool:
    """Indica si el texto es la invocación de una macro de C.

    Los device trees de Apple, Aspeed y algún otro generan nombres y
    etiquetas con macros (`DIE_NODE(pmgr)`, `EFUSE(10, 27)`). Lo que llega al
    árbol es la macro sin expandir, no lo que el fichero declara de verdad,
    así que no se puede juzgar como nombre: resolverlas es cosa de la capa 3.
    """
    return bool(_MACRO_CALL_RE.match(text.strip()))


def is_hex_literal(text: str) -> bool:
    """Indica si el texto son solo dígitos hexadecimales (una unit-address)."""
    return bool(text) and set(text) <= _HEX_DIGITS
