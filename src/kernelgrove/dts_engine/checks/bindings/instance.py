"""Codificación de un nodo como la instancia que espera un schema.

Los schemas de binding describen el device tree **ya compilado**: `dtc`
convierte cada propiedad en bytes y dt-schema los decodifica según el tipo de
la propiedad (`uint32` suelto es un entero, `uint32-array` una lista,
`uint32-matrix` una lista de listas...). Para validar lo que se está
editando hay que hacer ese mismo trabajo desde el texto.

**La regla es no adivinar.** Una propiedad solo entra en la instancia si su
valor se puede codificar con certeza; si no, se apunta en `skipped` y ninguna
comprobación habla de ella. Se quedan fuera:

- Los valores con macros de `dt-bindings/*.h` que no se han podido resolver:
  la capa 3 (`checks/macros.py`) las expande cuando puede (`cpp`, en
  ingesta) y aquí se sustituyen por su número si `ctx.local_macro_values` las
  trae; si no, siguen sin poder codificarse, igual que las expresiones sin
  reducir (`<(1 << 3)>`), que ninguna capa resuelve.
- Las referencias `&label`: un phandle en el binario es un número, y aquí es
  un nombre. Además, cuántas celdas ocupa cada referencia lo dice el nodo
  apuntado (`#gpio-cells`, `#clock-cells`), que habría que resolver.
- Las matrices cuyo *stride* no se conoce: `interrupts` depende del
  `#interrupt-cells` de su controlador. La excepción es `reg`, cuyo tamaño de
  fila sale de `#address-cells`/`#size-cells` del nodo padre.
- Las propiedades cuyo tipo no consta.

Lo que sí entra permite comprobar tipos (un número donde se espera una
cadena), longitudes (`maxItems`), rangos y enumerados, que es la mayor parte
de lo que un binding dice de un valor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Set

from kernelgrove.dt_model.model import DeviceTreeNode
from kernelgrove.dts_engine.checks import values
from kernelgrove.dts_engine.checks.context import SpecContext

# Valores por omisión de la especificación (§2.3.5) cuando el padre no los
# declara: son los que usa dtc para calcular el tamaño de una fila de `reg`.
_DEFAULT_ADDRESS_CELLS = 2
_DEFAULT_SIZE_CELLS = 1

# `compatible` **sí** entra en la instancia, aunque de sus problemas no se
# informe (los cubren la capa 1, que valida su forma, y la 5, que comprueba
# que exista un binding). La razón es que media docena de bindings del kernel
# eligen qué exigir con un `if: properties: compatible: contains: …`, y en
# JSON Schema un `properties` sobre algo que no está en la instancia se cumple
# solo: sin `compatible`, esas condiciones se daban todas por buenas y un
# `qcom,geni-i2c` con un `clock-names` acababa exigiendo los dos de otra
# variante.


@dataclass
class EncodedNode:
    """Nodo listo para validar, y lo que se ha quedado fuera."""

    instance: Dict[str, Any] = field(default_factory=dict)
    skipped: Set[str] = field(default_factory=set)

    def covers(self, property_name: Optional[str]) -> bool:
        """Indica si se puede hablar de esa propiedad a partir de la instancia."""
        if property_name is None:
            return True
        return property_name not in self.skipped


def encode_node(
    node: DeviceTreeNode,
    properties: Dict[str, Any],
    shape_of,
    parent_cells: Optional[tuple] = None,
    macro_values: Optional[Mapping[str, int]] = None,
) -> EncodedNode:
    """Construye la instancia de un nodo a partir de sus propiedades.

    `properties` son las propiedades efectivas (contando includes).
    `shape_of(nombre)` dice qué forma tiene el valor de una propiedad
    ('scalar', 'array', 'matrix', 'string', 'flag', 'phandle',
    'scalar-or-array') o None si no se sabe.
    `parent_cells` es `(#address-cells, #size-cells)` del padre, para `reg`.
    `macro_values` es lo que la capa 3 ha resuelto para este documento
    (nombre de macro -> entero): una celda que no es un literal se busca ahí
    antes de darla por no codificable.
    """
    encoded = EncodedNode()
    # El nombre del nodo es una propiedad más para los schemas: es lo que
    # miran los bindings genéricos para decidir si les toca (`select`).
    encoded.instance["$nodename"] = [node.name]

    for name, raw_value in properties.items():
        value = _encode_value(name, raw_value, shape_of, parent_cells, macro_values)
        if value is _UNKNOWN:
            encoded.skipped.add(name)
            continue
        encoded.instance[name] = value

    return encoded


class _Unknown:
    """Marca de «esto no se puede codificar»."""


_UNKNOWN = _Unknown()


def _encode_value(
    name: str,
    raw_value: Any,
    shape_of,
    parent_cells,
    macro_values: Optional[Mapping[str, int]] = None,
):
    """Codifica una propiedad, o devuelve `_UNKNOWN` si no se puede."""
    if values.is_empty_value(raw_value):
        return True

    raw = values.raw_text(raw_value)
    if not raw:
        return True

    components = values.split_components(raw)
    if not components:
        return _UNKNOWN

    if all(values.is_string(component) for component in components):
        return [values.unquote(component) for component in components]

    if not all(values.is_cell_array(component) for component in components):
        # Bytestrings, mezclas de cadena y celdas, referencias sueltas: no hay
        # una única forma en la que codificarlo.
        return _UNKNOWN

    numbers: List[int] = []
    for component in components:
        for token in values.cell_tokens(component):
            number = values.number(token)
            if number is None and macro_values:
                # La capa 3 ya la resolvió con `cpp` en la ingesta: se usa su
                # valor en vez de rendirse. Una referencia (`&label`) o una
                # expresión que no se pudo evaluar siguen sin estar aquí.
                number = macro_values.get(token)
            if number is None:
                return _UNKNOWN
            numbers.append(number)

    if not numbers:
        return _UNKNOWN

    return _shape(name, numbers, shape_of(name), parent_cells)


def _shape(name: str, numbers: List[int], shape: Optional[str], parent_cells):
    """Da forma a los números según la forma declarada de la propiedad."""
    if shape in (None, "flag", "phandle"):
        # Sin forma conocida no se codifica; `flag` con valor y `phandle` con
        # celdas necesitan, uno la capa 1 y otro resolver referencias.
        return _UNKNOWN

    if shape.endswith("-64"):
        # Un valor de 64 bits se escribe como dos celdas de 32
        # (`redistributor-stride = <0x0 0x20000>`), pero el schema espera un
        # solo número.
        if len(numbers) % 2:
            return _UNKNOWN
        numbers = [
            (numbers[i] << 32) | numbers[i + 1] for i in range(0, len(numbers), 2)
        ]
        shape = shape[: -len("-64")]

    if shape in ("scalar", "scalar-or-array"):
        # Un escalar con varias celdas se deja como lista a propósito: el
        # schema dirá que ahí esperaba un entero, que es el aviso útil. Es
        # también como decide dt-schema cuando el tipo admite las dos formas.
        return numbers[0] if len(numbers) == 1 else numbers

    if shape in ("array", "string"):
        # Una propiedad declarada de cadenas escrita con celdas es una
        # discrepancia de tipo, y el schema la señala mejor que nosotros.
        return numbers

    if shape == "matrix":
        stride = _reg_stride(name, parent_cells)
        if stride is None or stride <= 0 or len(numbers) % stride:
            return _UNKNOWN
        return [numbers[i : i + stride] for i in range(0, len(numbers), stride)]

    return _UNKNOWN


def _reg_stride(name: str, parent_cells) -> Optional[int]:
    """Celdas que ocupa cada fila de `reg`, según el nodo padre."""
    if name != "reg" or parent_cells is None:
        return None
    address_cells, size_cells = parent_cells
    return address_cells + size_cells


def parent_cells_of(properties: Dict[str, Any]) -> tuple:
    """Lee `(#address-cells, #size-cells)` de las propiedades de un nodo.

    Si no las declara se usan los valores por omisión de la especificación,
    que es lo que hace `dtc`.
    """
    return (
        _cell_count(properties.get("#address-cells"), _DEFAULT_ADDRESS_CELLS),
        _cell_count(properties.get("#size-cells"), _DEFAULT_SIZE_CELLS),
    )


def _cell_count(raw_value: Any, default: int) -> int:
    """Interpreta un `#*-cells` como número, con respaldo al valor por omisión."""
    if raw_value is None:
        return default
    cells = values.cells(values.raw_text(raw_value))
    if not cells:
        return default
    number = values.number(cells[0])
    return number if number is not None else default


def encode_instance(ctx: SpecContext, node: DeviceTreeNode) -> EncodedNode:
    """Codifica un nodo del árbol que se está comprobando.

    Toma las propiedades efectivas (contando lo que aportan los includes) y
    las celdas de direccionamiento del padre, y saca el tipo de cada
    propiedad del `SchemaLookup` que el contexto lleva. Lo usan por igual la
    capa 5 y la capa 2, que validan la misma instancia contra schemas
    distintos.
    """
    # El padre que cuenta es el del árbol fusionado: una reapertura
    # `&usb_dwc3_0 { … }` está escrita colgando de la raíz, pero su sitio real
    # está dentro del `soc`, y de ahí salen las celdas de `reg`. Tomar las de
    # la raíz partía `reg = <0x32f10108 0x8>, <0x381f0000 0x20>` en una sola
    # fila de cuatro celdas en vez de en dos de dos.
    merged = ctx.merged_node(node) or node
    parent = merged.parent or node.parent
    parent_cells = _parent_cells(ctx, parent)
    lookup = ctx.schema_lookup

    def shape_of(name: str) -> Optional[str]:
        return lookup.property_shape(name) if lookup is not None else None

    return encode_node(
        node,
        dict(ctx.effective_properties(node)),
        shape_of,
        parent_cells,
        macro_values=ctx.local_macro_values,
    )


def _parent_cells(ctx: SpecContext, parent) -> Optional[tuple]:
    """Celdas de direccionamiento del padre, o None si no se pueden saber.

    Si el padre es una reapertura que no se ha podido resolver, sus celdas
    están en otro fichero: los valores por omisión de la especificación no
    valen ahí, y usarlos partía `reg` en filas del tamaño equivocado. Sin
    saberlo, `reg` no se codifica y nadie habla de él.
    """
    if parent is None:
        return None
    if parent.name.startswith("&") and ctx.merged_node(parent) is None:
        return None
    return parent_cells_of(dict(ctx.effective_properties(parent)))
