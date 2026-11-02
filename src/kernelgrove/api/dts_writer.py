"""Generación de un fragmento DTS a partir de lo conectado en el generador.

Traduce el árbol de `PeripheralSlot` (controladores del SoC más los
dispositivos que el usuario ha conectado y habilitado) a texto DTS pegable:
un bloque `&label { … }` (o `&{/path} { … }` si el controlador no tiene
label) por cada controlador con algo conectado — exactamente la misma forma
que `api/overrides.py` ya escribe para los overrides de `status`, y que
`dt_model.model.resolve_label_overrides` sabe leer, así que el fragmento
generado aquí se funde igual que un `.dts` de placa real sobre el `.dtsi`
del SoC.

No toda la información de un dispositivo está en el modelo: la dirección de
un bus, un GPIO o un clock concretos dependen del cableado real, que nadie
puede deducir de un binding. Donde el schema fija el valor sin ambigüedad
(`const`, un `enum` de una sola opción) se usa tal cual, porque es
información cierta y no una suposición; donde no, se deja un valor
sintácticamente correcto con un comentario `/* TODO */` — pegable y
analizable de inmediato, ya que el motor semántico del editor señalará ahí
mismo lo que siga sin encajar en cuanto se abra.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from kernelgrove.api.selection import PeripheralSlot
from kernelgrove.dts_engine.checks.bindings.lookup import NodeSchema, SchemaLookup

INDENT = "\t"

# Forma del valor (`SchemaLookup.property_shape`) -> literal DTS de relleno
# cuando no hay nada cierto que deducir del schema. Cada línea debe quedar
# completa y aparcable, así que llevan un valor real (no un hueco vacío como
# las plantillas de autocompletado de `editor_tab.py`, pensadas para seguir
# escribiendo).
_PLACEHOLDER_BY_SHAPE = {
    "string": '"TODO"',
    "phandle": "<&TODO>",
    "scalar": "<0>",
    "scalar-64": "<0>",
    "scalar-or-array": "<0>",
    "array": "<0>",
    "array-64": "<0>",
    "matrix": "<0 0>",
}


def generate_fragment(
    root_slots: List[PeripheralSlot], schema_lookup: Optional[SchemaLookup] = None
) -> str:
    """Genera el texto DTS de todo lo conectado y habilitado en `root_slots`.

    Un bloque por controlador raíz con algo activo; los que no tienen nada
    conectado no generan bloque, igual que `PeripheralSlot.is_active`
    decide qué controlador se emite en el modelo interno. Sin
    `schema_lookup` (base sin schemas procesados) el fragmento se limita a
    los `compatible` de lo conectado, sin expandir propiedades obligatorias.
    """
    blocks = [
        _controller_block(slot, schema_lookup)
        for slot in root_slots
        if slot.is_active()
    ]
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _controller_block(
    slot: PeripheralSlot, schema_lookup: Optional[SchemaLookup]
) -> str:
    """Bloque `&label { … }` de un controlador con lo que cuelga de él."""
    descriptor = slot.descriptor
    reference = (
        f"&{descriptor.label}" if descriptor.label else f"&{{{descriptor.path}}}"
    )

    lines = [f"{reference} {{", f'{INDENT}status = "okay";']
    used_names: Dict[str, int] = {}
    for child in slot.children:
        if not child.enabled:
            continue
        lines.append("")
        lines.extend(
            _device_lines(child, schema_lookup, depth=1, used_names=used_names)
        )
    lines.append("};")
    return "\n".join(lines)


def _device_lines(
    slot: PeripheralSlot,
    schema_lookup: Optional[SchemaLookup],
    depth: int,
    used_names: Dict[str, int],
) -> List[str]:
    """Nodo de un dispositivo conectado: cabecera, propiedades y sus propios hijos."""
    indent = INDENT * depth
    descriptor = slot.descriptor
    compatible = descriptor.compatibles[0] if descriptor.compatibles else None
    schema = (
        schema_lookup.schema_for(compatible)
        if schema_lookup is not None and compatible
        else None
    )

    needs_address = schema is not None and "reg" in schema.required
    node_name, address = _node_name(descriptor.name, needs_address, used_names)

    lines = [f"{indent}{node_name} {{"]
    if compatible:
        lines.append(f'{indent}{INDENT}compatible = "{compatible}";')
    if needs_address:
        lines.append(
            f"{indent}{INDENT}reg = <{address:#x}>; /* TODO: dirección real */"
        )

    if schema is not None and schema_lookup is not None:
        for name in schema.required:
            if name in ("reg", "compatible"):
                continue
            lines.append(_property_line(name, schema, schema_lookup, indent + INDENT))

    for child in slot.children:
        if not child.enabled:
            continue
        lines.append("")
        lines.extend(
            _device_lines(child, schema_lookup, depth + 1, used_names={})
        )

    lines.append(f"{indent}}};")
    return lines


def _node_name(
    raw_name: str, needs_address: bool, used_names: Dict[str, int]
) -> Tuple[str, int]:
    """Nombre de nodo a escribir y, si necesita dirección de unidad, cuál.

    El binding exige `reg` en casi todo lo que cuelga de un bus direccionado
    (i2c, spi...): sin distinguir los hermanos por dirección, dos
    dispositivos con el mismo nombre base colisionarían, y el parser fusiona
    en uno los nodos que reabren el mismo nombre (`dts_engine/parser.py`,
    `_open_node`) — el segundo desaparecería en vez de generarse. Se usa un
    índice incremental por nombre base como dirección de relleno; el
    comentario en la línea `reg` dice que hay que revisarla.
    """
    base = raw_name.split("@", 1)[0]
    index = used_names.get(base, 0)
    used_names[base] = index + 1
    if needs_address:
        return (f"{base}@{index:x}", index)
    return (base if index == 0 else f"{base}-{index + 1}", -1)


def _property_line(
    name: str, schema: NodeSchema, schema_lookup: SchemaLookup, indent: str
) -> str:
    """Línea DTS para una propiedad obligatoria, con el mejor valor disponible."""
    prop = schema.property_for(name)
    subschema = prop.schema if prop is not None else {}

    certain = _certain_value(subschema)
    if certain is not None:
        literal, is_flag = certain
        return f"{indent}{name};" if is_flag else f"{indent}{name} = {literal};"

    shape = schema_lookup.property_shape(name)
    if shape == "flag":
        return f"{indent}{name}; /* TODO: revisar si aplica */"
    placeholder = _PLACEHOLDER_BY_SHAPE.get(shape)
    if placeholder is None:
        return f'{indent}/* TODO: missing "{name}" (required, unknown type) */'
    return f"{indent}{name} = {placeholder}; /* TODO: revisar */"


def _certain_value(subschema: Dict[str, Any]) -> Optional[Tuple[str, bool]]:
    """Valor que el propio schema fija sin ambigüedad, ya como literal DTS.

    `const` o un `enum` de una única opción son información cierta sobre el
    binding, no una suposición: se usan tal cual. Cualquier otro caso (varias
    opciones, sin pista) devuelve None y el llamante recurre a un valor de
    relleno según la forma. El segundo elemento indica si es una propiedad
    "flag" (sin valor, solo presencia).
    """
    if not isinstance(subschema, dict):
        return None
    if "const" in subschema:
        return (_dts_literal(subschema["const"]), False)
    enum = subschema.get("enum")
    if isinstance(enum, list) and len(enum) == 1:
        return (_dts_literal(enum[0]), False)
    return None


def _dts_literal(value: Any) -> str:
    """Traduce un valor de schema (`const`/`enum`) a literal DTS."""
    if isinstance(value, bool):
        return "<1>" if value else "<0>"
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, int):
        return f"<{value:#x}>"
    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            return ", ".join(f'"{item}"' for item in value)
        if all(isinstance(item, (int, float)) for item in value):
            return "<" + " ".join(str(int(item)) for item in value) + ">"
    return f'"{value}"'
