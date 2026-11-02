"""Ingesta de los schemas de bindings procesados por dt-schema.

`dtschema` es la implementación de referencia con la que el propio kernel
valida sus bindings (`make dt_binding_check`). Aquí se usa **solo en tiempo
de ingesta**, por dos cosas que el YAML crudo no da:

- **Extracción de compatibles fiable.** El extractor propio de `records.py`
  recorría el documento buscando cualquier `enum`/`const` cuando no
  encontraba `properties.compatible`, y eso registraba como compatibles
  nombres de grupos de pinmux, extensiones RISC-V o valores de formatos de
  audio. `dtschema.extract_node_compatibles` lee la forma real del schema.
- **Schemas procesados** (`fixup`): los mismos que produce `dt-mk-schema`,
  con la notación abreviada expandida, los tipos normalizados y las
  propiedades implícitas (`status`, `phandle`, `pinctrl-*`...) añadidas. Es
  lo que permite responder «qué propiedades admite este compatible» sin
  reimplementar las reglas de composición de los bindings.

Lo que dt-schema **no** aporta y sigue siendo nuestro: la inferencia de
`parent_bus`/`child_bus` (ver `storage.infer_parent_child_bus`): no existe
ningún `i2c-peripheral-props.yaml`, así que el bus de un dispositivo I2C solo
se deduce de sus ejemplos.

La dependencia es opcional: si `dtschema` no está instalado la ingesta de
bindings sigue funcionando con el extractor antiguo (`records.parse_compatible`)
y la tabla `schemas` simplemente no se genera. Instalarlo:

    pip install -e '.[ingest]'
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

# Un compatible declarado como `pattern` es una expresión regular, no una
# cadena: se guarda aparte para no ofrecerlo como valor literal. Los
# metacaracteres que se buscan son los mismos que usa dtschema en
# `make_compatible_schema`, y deliberadamente **no** incluyen `.` ni `+`:
# ambos aparecen en compatibles reales ("adi,axi-adc-10.0.a",
# "arm,cortex-m0+", "nvidia,p3509-0000+p3636-0001"), así que tomarlos por
# expresiones regulares descarta dispositivos que existen.
_PATTERN_MARKERS = re.compile(r"[\^\$\[\]\{\}\(\)\|\\]")


def load_dtschema():
    """Devuelve el módulo `dtschema`, o None si no está instalado."""
    try:
        import dtschema  # noqa: PLC0415  (import opcional, a propósito)
    except ImportError:
        return None
    return dtschema


def dtschema_version() -> Optional[str]:
    """Versión de dtschema instalada, o None si no lo está."""
    module = load_dtschema()
    return getattr(module, "__version__", None) if module else None


def is_pattern(compatible: str) -> bool:
    """Indica si el «compatible» es en realidad una expresión regular.

    Los bindings de familias enteras declaran el compatible con `pattern`
    (`^qcom,(sa8775p|sc7280)-.*$`). No es un valor que se pueda escribir en
    un `.dts`, así que se registra aparte de los literales.
    """
    return bool(_PATTERN_MARKERS.search(compatible))


def node_compatible_schema(schema: Dict[str, Any]) -> Optional[Any]:
    """Devuelve el subschema que declara los compatibles de un nodo.

    Normalmente es `properties.compatible`, pero un binding que deja esa
    propiedad abierta —porque el compatible real lo pone cada fabricante—
    declara a qué nodos se aplica en `select`, que es el mecanismo con el que
    dt-schema decide qué schema valida qué nodo. Es el caso de
    `snps,dw-pcie-ep.yaml` o `marvell,aquantia.yaml`: mirar solo
    `properties.compatible` los deja sin ningún compatible registrado.
    """
    if not isinstance(schema, dict):
        return None

    properties = schema.get("properties")
    if isinstance(properties, dict) and properties.get("compatible") is not None:
        return properties["compatible"]

    select = schema.get("select")
    if isinstance(select, dict):
        select_properties = select.get("properties")
        if isinstance(select_properties, dict):
            return select_properties.get("compatible")

    return None


# Patrón que dt-core.yaml usa para decir «cualquier compatible con forma
# válida»: casa con todo, así que como criterio de «este binding describe
# este dispositivo» no vale para nada.
_GENERIC_COMPATIBLE_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9,+\-._/]+$"


def is_useful_pattern(value: str) -> bool:
    """Indica si un compatible-expresión-regular sirve para identificar algo.

    Mismo criterio que dtschema aplica en `make_compatible_schema`: tiene que
    estar anclado por los dos extremos y no puede ser comodín. Sin este filtro
    entran patrones como el genérico de `dt-core.yaml` o el
    `^(?!renesas,.+-.+).+$` de `renesas-soc.yaml`, que hacen que **cualquier**
    cadena parezca un compatible documentado.
    """
    if not (value.startswith("^") and value.endswith("$")):
        return False
    if value == _GENERIC_COMPATIBLE_PATTERN:
        return False
    return not re.search(r"\.[+*]", value)


def top_level_compatibles(doc: Dict[str, Any]) -> List[str]:
    """Compatibles que el binding declara para **su propio nodo**.

    Es lo que identifica al binding: los compatibles de sus subnodos
    (`ti,twl4030-pwm` dentro de `ti,twl.yaml`) describen otros dispositivos y
    se registran en `schema_compatibles`, no aquí.

    Devuelve lista vacía si el documento no declara `properties.compatible`.
    Eso no es un fallo: los schemas de propiedades comunes (`rtc.yaml`,
    `dai-params.yaml`, `riscv/extensions.yaml`) no describen ningún
    dispositivo concreto y no deben acabar en la tabla `bindings`.
    """
    subschema = node_compatible_schema(doc)
    if subschema is None:
        return []

    # El orden importa: `bindings.compatible` guarda el primero declarado, que
    # es el modelo que da nombre al binding. `extract_node_compatibles`
    # devuelve un conjunto, así que el orden se toma del extractor propio, que
    # recorre el documento, y de dtschema solo se toma qué pertenece al
    # conjunto (y lo que el otro no supo ver).
    from kernelgrove.db_manager.records import parse_compatible

    ordered = [str(value) for value in parse_compatible(subschema)]

    module = load_dtschema()
    if module is None:
        values = set(ordered)
    else:
        values = {str(value) for value in module.extract_node_compatibles(subschema)}

    seen: List[str] = []
    for value in ordered:
        if value in values and value not in seen:
            seen.append(value)
    seen.extend(sorted(values - set(seen)))

    return [value for value in seen if not is_pattern(value)]


@dataclass
class ProcessedSchemas:
    """Resultado de procesar todos los bindings con dt-schema."""

    version: str
    # $id (sin '#') -> schema ya procesado (fixups aplicados).
    schemas: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Tipo de cada propiedad conocida, por nombre exacto y por patrón.
    types: Dict[str, Any] = field(default_factory=dict)
    pattern_types: Dict[str, Any] = field(default_factory=dict)


def build_processed_schemas(root: Path) -> ProcessedSchemas:
    """Procesa todos los YAML bajo `root` con dt-schema.

    Equivale a `dt-mk-schema -j <root>`: unos 90 segundos y 27 MB de JSON
    para los ~5600 bindings del kernel. Incluye además los schemas del núcleo
    que trae el propio dtschema (`dt-core.yaml`, `i2c-controller.yaml`...),
    imprescindibles porque son el destino de la mitad de los `$ref`.

    Lanza RuntimeError si dtschema no está instalado.
    """
    module = load_dtschema()
    if module is None:
        raise RuntimeError(
            "dtschema no está instalado: no se pueden generar los schemas "
            "procesados. Instálalo con «pip install -e '.[ingest]'»."
        )

    validator = module.DTValidator([str(root)])
    raw_schemas = dict(validator.schemas)

    version = str(raw_schemas.pop("version", getattr(module, "__version__", "")))
    types = _generated(raw_schemas.pop("generated-types", None))
    pattern_types = _generated(raw_schemas.pop("generated-pattern-types", None))
    # `generated-compatibles` no se guarda: la tabla `schema_compatibles`
    # registra los mismos compatibles y además dice a qué schema pertenecen.
    raw_schemas.pop("generated-compatibles", None)

    schemas = {
        key.rstrip("#"): value
        for key, value in raw_schemas.items()
        if isinstance(value, dict)
    }
    return ProcessedSchemas(
        version=version,
        schemas=schemas,
        types=types,
        pattern_types=pattern_types,
    )


def _generated(entry: Any) -> Dict[str, Any]:
    """Extrae el mapa de tipos de una entrada `generated-*` de dt-schema."""
    if not isinstance(entry, dict):
        return {}
    properties = entry.get("properties")
    return properties if isinstance(properties, dict) else {}


def schema_key(filename: Optional[str], root: Path) -> str:
    """Clave legible del fichero de origen de un schema.

    Relativa a la raíz de ingesta cuando el schema viene del kernel; con
    prefijo `dtschema/` cuando es uno de los del núcleo que trae el paquete.
    """
    if not filename:
        return ""
    path = Path(filename)
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        pass
    parts = path.parts
    if "dtschema" in parts:
        index = len(parts) - 1 - parts[::-1].index("dtschema")
        return Path(*parts[index:]).as_posix()
    return path.name


# Compatibles que casi cualquier nodo puede llevar como segundo valor y que
# por tanto no identifican a ningún dispositivo. Mismo criterio que dtschema
# aplica al construir su mapa de compatibles: solo cuentan cuando el schema
# no declara ningún otro, que es el caso de `simple-bus.yaml` o `syscon.yaml`.
#
# `arm,primecell` no está en la lista de dtschema pero se comporta igual: lo
# declaran 32 bindings distintos (el resto de compatibles repetidos no pasan
# de seis), así que resolver por él lleva a un binding cualquiera. Un
# `"arm,pl011", "arm,primecell"` cuyo primer compatible no esté documentado
# acababa validándose contra un schema de CoreSight y exigiendo `in-ports`.
_GENERIC_COMPATIBLES = {"simple-bus", "simple-mfd", "syscon", "arm,primecell"}


def compatible_positions(subschema: Any) -> Dict[str, int]:
    """Posición que ocupa cada compatible dentro de la lista que declara el nodo.

    Un binding de dispositivo concreto declara a menudo dos compatibles: el
    suyo y, detrás, el genérico de la familia.

        compatible:
          items:
            - const: advantech,idk-1110wr
            - const: panel-lvds

    Los dos quedan registrados, pero solo el primero *identifica* a este
    binding: el genérico lo declaran igual media docena de paneles distintos.
    Guardar la posición permite que al resolver `panel-lvds` gane
    `panel-lvds.yaml`, donde es el compatible principal, en vez del primer
    panel que aparezca. Sin esto, una pantalla cualquiera se validaba contra
    el binding de un panel Advantech y heredaba sus medidas como valores
    obligatorios.
    """
    positions: Dict[str, int] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            items = node.get("items")
            if isinstance(items, list):
                for index, entry in enumerate(items):
                    for value in _node_compatibles(entry):
                        positions[value] = min(index, positions.get(value, index))
                for key, value in node.items():
                    if key != "items":
                        walk(value)
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(subschema)
    for value in _node_compatibles(subschema):
        positions.setdefault(value, 0)
    return positions


def compatible_nodes(schema: Dict[str, Any]) -> List[Tuple[str, str, bool, int]]:
    """Lista los compatibles que un schema declara y **dónde** los declara.

    Devuelve `(compatible, node_path, es_patrón, posición)`. `node_path` es la
    ruta de subnodos dentro del schema, vacía para el nodo del propio binding:

        ti,twl4030        -> ""            (el nodo raíz del binding)
        ti,twl4030-pwm    -> "pwm"         (un subnodo suyo)

    Sin esa ruta, resolver `ti,twl4030-pwm` devolvería el schema del MFD
    entero y se le exigirían al PWM las propiedades del padre, que es
    justo el tipo de error inventado que la resolución exacta evita.
    """
    found: List[Tuple[str, str, bool, int]] = []
    for node_path, subschema in _iter_node_schemas(schema, ""):
        compatible = node_compatible_schema(subschema)
        if compatible is None:
            continue
        declared = _node_compatibles(compatible)
        if len(declared) > 1:
            declared = [
                value for value in declared if value not in _GENERIC_COMPATIBLES
            ]

        positions = compatible_positions(compatible)
        for value in declared:
            pattern = is_pattern(value)
            if pattern and not is_useful_pattern(value):
                continue
            found.append((value, node_path, pattern, positions.get(value, 0)))
    return found


def _node_compatibles(subschema: Any) -> List[str]:
    """Valores de un subschema `compatible`, literales y patrones."""
    module = load_dtschema()
    if module is None:
        from kernelgrove.db_manager.records import parse_compatible

        values = parse_compatible(subschema)
    else:
        values = module.extract_node_compatibles(subschema)
    return sorted({str(value) for value in values})


def _iter_node_schemas(
    schema: Dict[str, Any], path: str, depth: int = 0
) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Recorre el schema y sus subnodos, devolviendo (ruta, subschema).

    Un subnodo se reconoce por tener `properties`/`patternProperties`
    propios; `$ref` no vale como marca, porque en los bindings del kernel se
    usa sobre todo para tipar propiedades escalares.
    """
    if not isinstance(schema, dict) or depth > 8:
        return
    yield (path, schema)

    for container in ("properties", "patternProperties"):
        entries = schema.get(container)
        if not isinstance(entries, dict):
            continue
        for name, subschema in entries.items():
            if name == "compatible" or not isinstance(subschema, dict):
                continue
            if not _looks_like_node(subschema):
                continue
            child_path = f"{path}/{name}" if path else name
            yield from _iter_node_schemas(subschema, child_path, depth + 1)


def _looks_like_node(subschema: Dict[str, Any]) -> bool:
    """Indica si el subschema describe un nodo hijo y no una propiedad."""
    if subschema.get("type") == "object":
        return True
    return any(key in subschema for key in ("properties", "patternProperties"))


def schema_records(processed: ProcessedSchemas, root: Path) -> Iterator[Dict[str, Any]]:
    """Convierte los schemas procesados en registros para la tabla `schemas`.

    Junto al schema procesado se recupera el YAML original desde disco: los
    fixups de dt-schema eliminan `description` y `examples`, que son
    justamente lo que hace falta para las ayudas del editor. El `$filename`
    que dt-schema deja en cada schema es la ruta absoluta de la que salió.
    """
    for schema_id, schema in processed.schemas.items():
        filename = schema.get("$filename")
        yield {
            "id": schema_id,
            "path": schema_key(filename, root),
            "title": schema.get("title"),
            # `select` marca los schemas que se aplican por la forma del nodo
            # (los bindings genéricos), no por su compatible. dt-schema los
            # evalúa contra todos los nodos; nosotros también, en la capa 2.
            # `select: false` es un «no me apliques nunca» y no cuenta.
            "has_select": bool(schema.get("select")),
            "schema": schema,
            "raw": _load_raw(filename),
            "compatibles": compatible_nodes(schema),
        }


def _load_raw(filename: Optional[str]) -> Optional[Dict[str, Any]]:
    """Lee el YAML original de un schema, o None si ya no está en disco."""
    if not filename:
        return None
    from kernelgrove.db_manager.loader import load_yaml_document

    path = Path(filename)
    if not path.is_file():
        return None
    try:
        return load_yaml_document(path)
    except RuntimeError:
        return None
