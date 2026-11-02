"""Resolución de los schemas de binding para el motor y el autocompletado.

Implementa el protocolo `SchemaLookup` de la capa 5 (`dts_engine.checks.
bindings.lookup`) sobre los schemas que dt-schema dejó en la base de datos.

El trabajo real es **seguir la herencia**. Un binding no enumera todas sus
propiedades: referencia con `allOf`/`$ref` los schemas de su clase de
dispositivo y del bus donde vive, y de ahí saca la mayor parte. Sin resolver
esas referencias, un controlador I2C de Cadence declara 14 propiedades; con
ellas resueltas son 50, y `#address-cells`/`#size-cells` pasan de invisibles
a estar fijadas a 1 y 0.

Los bloques condicionales (`allOf` con `if`, `oneOf`, `anyOf`) se recorren
**solo en sentido permisivo**: sus propiedades cuentan como admitidas pero
nunca como obligatorias. La asimetría es deliberada y es lo que hace que esta
capa no pueda ser más estricta que el binding: «esta propiedad sobra» exige
haber mirado todas las ramas —si aparece en alguna, puede ser válida—,
mientras que «esta propiedad falta» exige que la exija la rama que de verdad
aplica, y cuál aplica depende del compatible concreto, que aquí no se evalúa.
Un binding de dominios de tensión que declara los `*-supply` de cada SoC en
un `if` por compatible es el caso típico: sin esto, todos sus `*-supply`
parecerían propiedades no admitidas.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from kernelgrove.api.schema_validator import SchemaValidator
from kernelgrove.api.schemas_database import SchemaMatch, SchemasDatabase, StoredSchema
from kernelgrove.dts_engine.checks.bindings.lookup import (
    NodeSchema,
    SchemaIssue,
    SchemaProperty,
)

# Tope de referencias encadenadas que se siguen. Los bindings del kernel no
# pasan de cuatro o cinco niveles; el límite solo protege de un ciclo raro.
_MAX_DEPTH = 12

# Prefijo con el que dt-schema construye los `$id`.
_SCHEMA_HOST = "http://devicetree.org"

# Forma del valor según el tipo que declara dt-schema. Es lo que decide cómo
# se codifica: un `uint32` es un entero suelto, un `uint32-array` una lista y
# un `uint32-matrix` una lista de listas (ver `types.yaml` de dt-schema).
_SHAPES = {
    "flag": "flag",
    "string": "string",
    "string-array": "string",
    "non-unique-string-array": "string",
    "phandle": "phandle",
    "phandle-array": "phandle",
    "address": "matrix",
    "node": None,
}
for _name in ("int8", "int16", "int32", "uint8", "uint16", "uint32"):
    _SHAPES[_name] = "scalar"
    _SHAPES[f"{_name}-array"] = "array"
    _SHAPES[f"{_name}-matrix"] = "matrix"

# Los de 64 bits se marcan aparte: en el fuente son dos celdas de 32 que el
# schema espera como un único número.
for _name in ("int64", "uint64"):
    _SHAPES[_name] = "scalar-64"
    _SHAPES[f"{_name}-array"] = "array-64"
    _SHAPES[f"{_name}-matrix"] = "matrix"


# Propiedades que dt-schema añade a todos los nodos y que no son del binding
# ni se escriben en un `.dts`: `$nodename` es la comprobación del nombre del
# nodo y `phandle` lo genera dtc.
_INTERNAL_PROPERTIES = {"$nodename", "phandle"}


class BindingSchemaLookup:
    """Resuelve compatibles contra los schemas procesados de la base."""

    def __init__(self, db_path: Path):
        """Prepara el acceso a la base; todo se carga bajo demanda."""
        self._db = SchemasDatabase(db_path)
        self._validator = SchemaValidator(self._db)
        self._schemas: Dict[str, Optional[StoredSchema]] = {}
        self._descriptions: Dict[str, Dict[str, str]] = {}
        self._resolved: Dict[str, Optional[NodeSchema]] = {}
        self._children: Dict[str, Optional[NodeSchema]] = {}
        self._matches: Dict[str, Optional[SchemaMatch]] = {}
        self._types: Optional[Dict[str, Any]] = None
        self._pattern_types: List[Tuple[Any, Any]] = []

    # ------------------------------------------------------------------
    # Protocolo SchemaLookup
    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        """Indica si la base incluye los schemas procesados."""
        return self._db.is_available()

    def is_documented(self, compatible: str) -> bool:
        """Indica si algún binding declara ese compatible."""
        return self._match(compatible) is not None

    def _match(self, compatible: str) -> Optional[SchemaMatch]:
        """Localiza el schema de un compatible, recordando también los fallos.

        El motor pregunta por los mismos compatibles en cada análisis —y hay
        análisis en cada pulsación de tecla—, y un compatible desconocido
        cuesta además recorrer todos los declarados como expresión regular.
        """
        if compatible not in self._matches:
            self._matches[compatible] = self._db.match_compatible(compatible)
        return self._matches[compatible]

    def schema_for(self, compatible: str) -> Optional[NodeSchema]:
        """Devuelve el schema resuelto del nodo que declara ese compatible."""
        if compatible in self._resolved:
            return self._resolved[compatible]

        resolved = self._build(compatible)
        self._resolved[compatible] = resolved
        return resolved

    def child_schema_for(
        self, compatible: str, node_name: str
    ) -> Optional[NodeSchema]:
        """Devuelve lo que el binding de un nodo dice de un hijo suyo.

        Es el trozo de la capa 2 que se puede responder desde aquí: las
        propiedades que un bus declara para lo que cuelga de él viven en su
        binding, no en el del dispositivo.
        """
        key = f"{compatible}\u0000{node_name}"
        if key in self._children:
            return self._children[key]

        resolved = self._build_child(compatible, node_name)
        self._children[key] = resolved
        return resolved

    def _build_child(
        self, compatible: str, node_name: str
    ) -> Optional[NodeSchema]:
        """Resuelve el subschema que el binding padre dedica a un hijo."""
        match = self._match(compatible)
        if match is None:
            return None
        stored = self._stored(match.schema_id)
        if stored is None:
            return None

        parent = _navigate(stored.schema, match.node_path)
        if parent is None:
            return None

        child = _child_subschema(parent, node_name)
        if child is None:
            return None

        accumulator = _Accumulator()
        self._collect(child, match.schema_id, accumulator, set(), 0)
        self._collect_conditional(child, match.schema_id, accumulator, set(), 0)

        return NodeSchema(
            compatible=compatible,
            schema_id=match.schema_id,
            title=stored.title,
            properties={
                name: self._property(name, entry, accumulator)
                for name, entry in accumulator.properties.items()
            },
            pattern_properties=tuple(
                (pattern, self._property(pattern, entry, accumulator))
                for pattern, entry in accumulator.pattern_properties.items()
            ),
            required=(),
            closed=False,
        )

    # ------------------------------------------------------------------
    # Validación (capas 5 y 2)
    # ------------------------------------------------------------------
    def validate_node(
        self, schema: NodeSchema, instance: Dict[str, Any]
    ) -> List[SchemaIssue]:
        """Valida la instancia de un nodo contra el schema de su binding."""
        stored = self._stored(schema.schema_id)
        if stored is None:
            return []

        if not schema.node_path:
            return self._validator.issues(
                schema.schema_id, stored.schema, instance
            )

        # Para un subnodo no vale con sacar su trozo y validarlo suelto: sus
        # `$ref` locales (`#/$defs/clock-props`) apuntan al documento entero.
        # Se apunta a él con un `$ref`, que `referencing` resuelve contra el
        # `$id` del fichero y deja el `$defs` en su sitio.
        pointer = _pointer_for(stored.schema, schema.node_path)
        if pointer is None:
            return []
        return self._validator.issues(
            schema.schema_id,
            {"$ref": f"{schema.schema_id}#{pointer}"},
            instance,
            schema.node_path,
        )

    def validate_generic(self, instance: Dict[str, Any]) -> List[SchemaIssue]:
        """Valida la instancia contra los bindings genéricos aplicables."""
        return self._validator.generic_issues(instance)

    def generic_schema_count(self) -> int:
        """Número de bindings genéricos que se evalúan en la capa 2."""
        return self._validator.select_schema_count()

    # ------------------------------------------------------------------
    # Datos auxiliares
    # ------------------------------------------------------------------
    def dtschema_version(self) -> Optional[str]:
        """Versión de dtschema con la que se generó la base."""
        return self._db.dtschema_version()

    def app_schema_version(self) -> Optional[int]:
        """Versión del esquema de la base, o None si no la declara."""
        return self._db.app_schema_version()

    def subdevices_of(self, compatible: str) -> List[str]:
        """Compatibles de los subnodos que declara el binding de un dispositivo."""
        return [item[0] for item in self._db.list_subdevices(compatible)]

    def documented_compatibles(self, prefix: str, limit: int = 50) -> List[str]:
        """Compatibles documentados que empiezan por `prefix`."""
        return self._db.list_compatibles(prefix, limit)

    def property_shape(self, name: str) -> Optional[str]:
        """Forma del valor de una propiedad, para poder codificarlo.

        Interesa la forma y no el tipo exacto: `clock-frequency` aparece como
        `uint32` en unos bindings y como `uint64` en otros, pero en los dos es
        un entero suelto, así que se puede codificar. Lo que no se puede es
        decidir entre formas distintas (un entero o una lista de enteros), y
        ahí se devuelve None salvo el caso corriente escalar/lista, que se
        resuelve por el número de celdas como hace dt-schema.
        """
        types = self._property_types(name)
        if not types:
            return None

        shapes = {_SHAPES.get(item) for item in types}
        shapes.discard(None)
        if not shapes:
            return None
        if len(shapes) == 1:
            return shapes.pop()
        if shapes == {"scalar", "array"}:
            return "scalar-or-array"
        if shapes == {"scalar", "scalar-64"}:
            # `clock-frequency` es uint32 en unos bindings y uint64 en otros;
            # con una sola celda escrita es un entero de 32 en cualquier caso.
            return "scalar"
        return None

    def is_known_property_name(self, name: str) -> bool:
        """Indica si el nombre usa un prefijo de fabricante registrado."""
        return self._validator.is_known_property_name(name)

    def _property_types(self, name: str) -> set:
        """Tipos con los que aparece una propiedad en los bindings."""
        self._load_types()
        entries = self._types.get(name)
        if entries is None:
            for pattern, value in self._pattern_types:
                if pattern.search(name):
                    entries = value
                    break
        if not isinstance(entries, list):
            return set()
        return {
            entry.get("type")
            for entry in entries
            if isinstance(entry, dict) and entry.get("type")
        }

    def _load_types(self) -> None:
        """Carga los mapas de tipos de la base la primera vez que se usan."""
        if self._types is not None:
            return
        self._types = dict(self._db.property_types())
        self._pattern_types = [
            (re.compile(key), value)
            for key, value in self._db.pattern_property_types().items()
            if _is_valid_regex(key)
        ]

    def property_type(self, name: str) -> Optional[str]:
        """Tipo de device tree de una propiedad, según dt-schema.

        Es el tipo que el propio dtschema deduce del conjunto de los bindings
        ('uint32', 'string-array', 'phandle-array'...). Cuando una propiedad
        aparece con varios tipos incompatibles se devuelve None: no se puede
        afirmar ninguno.
        """
        types = self._property_types(name)
        return types.pop() if len(types) == 1 else None

    def since(self, schema_id: str) -> Optional[str]:
        """Versión del kernel desde la que existe ese schema."""
        return self._db.since(schema_id)

    def kernel_releases(self) -> List[str]:
        """Releases que la base conoce, de la más nueva a la más vieja."""
        return self._db.kernel_releases()

    def binding_since(self, compatible: str) -> Optional[str]:
        """Versión del kernel desde la que existe el binding de un compatible."""
        match = self._match(compatible)
        return self._db.since(match.schema_id) if match else None

    # ------------------------------------------------------------------
    # Construcción
    # ------------------------------------------------------------------
    def _build(self, compatible: str) -> Optional[NodeSchema]:
        """Resuelve el schema de un compatible siguiendo toda su herencia."""
        match = self._match(compatible)
        if match is None:
            return None

        stored = self._stored(match.schema_id)
        if stored is None:
            return None

        subschema = _navigate(stored.schema, match.node_path)
        if subschema is None:
            return None

        accumulator = _Accumulator()
        self._collect(subschema, match.schema_id, accumulator, set(), 0)
        self._collect_conditional(subschema, match.schema_id, accumulator, set(), 0)

        properties = {
            name: self._property(name, entry, accumulator)
            for name, entry in accumulator.properties.items()
            if name not in _INTERNAL_PROPERTIES
        }
        pattern_properties = tuple(
            (pattern, self._property(pattern, entry, accumulator))
            for pattern, entry in accumulator.pattern_properties.items()
        )
        return NodeSchema(
            compatible=compatible,
            schema_id=match.schema_id,
            node_path=match.node_path,
            title=stored.title,
            properties=properties,
            pattern_properties=pattern_properties,
            required=tuple(sorted(accumulator.required)),
            closed=accumulator.closed,
        )

    def _property(
        self, name: str, entry: Tuple[Any, str], accumulator: "_Accumulator"
    ) -> SchemaProperty:
        """Construye la propiedad expuesta al motor a partir de lo acumulado."""
        schema, origin = entry
        subschema = schema if isinstance(schema, dict) else {}
        return SchemaProperty(
            name=name,
            schema=subschema,
            required=name in accumulator.required,
            origin=origin,
            description=self._description(origin, name),
            dt_type=self.property_type(name),
            is_node=_looks_like_node(subschema),
        )

    def _collect(
        self,
        schema: Dict[str, Any],
        origin: str,
        accumulator: "_Accumulator",
        seen: set,
        depth: int,
    ) -> None:
        """Acumula propiedades y requisitos de un schema y de sus referencias."""
        if depth > _MAX_DEPTH or not isinstance(schema, dict):
            return

        for container, target in (
            ("properties", accumulator.properties),
            ("patternProperties", accumulator.pattern_properties),
        ):
            entries = schema.get(container)
            if not isinstance(entries, dict):
                continue
            for name, subschema in entries.items():
                # `false` prohíbe la propiedad; `true` la admite sin decir más.
                if subschema is False:
                    continue
                target.setdefault(name, (subschema, origin))

        required = schema.get("required")
        if isinstance(required, list):
            accumulator.required.update(
                item for item in required if isinstance(item, str)
            )

        if schema.get("additionalProperties") is False:
            accumulator.closed = True
        if schema.get("unevaluatedProperties") is False:
            accumulator.closed = True

        for entry in schema.get("allOf") or []:
            if not isinstance(entry, dict) or "if" in entry:
                # Los bloques condicionales dependen de qué compatible
                # concreto se use; darlos por aplicados inventa requisitos.
                # `_collect_conditional` los recorre aparte, solo para saber
                # qué propiedades pueden llegar a ser válidas.
                continue
            self._follow(entry, origin, accumulator, seen, depth)

        if isinstance(schema.get("$ref"), str):
            self._follow({"$ref": schema["$ref"]}, origin, accumulator, seen, depth)

    def _collect_conditional(
        self,
        schema: Dict[str, Any],
        origin: str,
        accumulator: "_Accumulator",
        seen: set,
        depth: int,
    ) -> None:
        """Recoge, solo como admitidas, las propiedades de las ramas condicionales.

        Recorre `then`/`else` de cada `if`, y las alternativas de `oneOf` y
        `anyOf`, sin tocar `required` ni el carácter cerrado del schema: de
        una rama que puede no aplicar solo se puede concluir que lo que
        declara *podría* ser válido.
        """
        if depth > _MAX_DEPTH or not isinstance(schema, dict):
            return

        branches: List[Any] = []
        for entry in schema.get("allOf") or []:
            if isinstance(entry, dict) and "if" in entry:
                branches.extend(
                    entry.get(key) for key in ("then", "else") if key in entry
                )
        for key in ("then", "else", "oneOf", "anyOf"):
            value = schema.get(key)
            if isinstance(value, list):
                branches.extend(value)
            elif isinstance(value, dict):
                branches.append(value)

        for branch in branches:
            if not isinstance(branch, dict):
                continue
            accumulator.absorb_conditional(branch, origin)
            self._collect_conditional(branch, origin, accumulator, seen, depth + 1)

        # Las ramas condicionales de los schemas referenciados cuentan igual:
        # un `$ref` a la clase de dispositivo puede traerlas.
        for entry in list(schema.get("allOf") or []) + [schema]:
            if not isinstance(entry, dict):
                continue
            reference = entry.get("$ref")
            if not isinstance(reference, str):
                continue
            target_id, fragment = _split_ref(reference, origin)
            key = ("conditional", target_id, fragment)
            if key in seen:
                continue
            seen.add(key)
            stored = self._stored(target_id)
            if stored is None:
                continue
            referenced = _navigate_fragment(stored.schema, fragment)
            if isinstance(referenced, dict):
                self._collect_conditional(
                    referenced, target_id, accumulator, seen, depth + 1
                )

    def _follow(
        self,
        entry: Dict[str, Any],
        origin: str,
        accumulator: "_Accumulator",
        seen: set,
        depth: int,
    ) -> None:
        """Sigue una entrada de `allOf`: su `$ref` y lo que declare en línea."""
        reference = entry.get("$ref")
        if isinstance(reference, str):
            target_id, fragment = _split_ref(reference, origin)
            key = (target_id, fragment)
            if key not in seen:
                seen.add(key)
                stored = self._stored(target_id)
                if stored is not None:
                    referenced = _navigate_fragment(stored.schema, fragment)
                    if isinstance(referenced, dict):
                        self._collect(
                            referenced, target_id, accumulator, seen, depth + 1
                        )

        inline = {key: value for key, value in entry.items() if key != "$ref"}
        if inline:
            self._collect(inline, origin, accumulator, seen, depth + 1)

    def _stored(self, schema_id: str) -> Optional[StoredSchema]:
        """Carga un schema de la base, recordándolo para las siguientes."""
        if schema_id not in self._schemas:
            self._schemas[schema_id] = self._db.get_schema(schema_id)
        return self._schemas[schema_id]

    def _description(self, schema_id: str, name: str) -> Optional[str]:
        """Texto de ayuda de una propiedad, sacado del YAML original.

        Los fixups de dt-schema eliminan las descripciones, así que se leen
        del documento crudo que la ingesta guardó junto al procesado. Se
        indexa el fichero entero por nombre de propiedad: dentro de un mismo
        binding, una propiedad describe siempre lo mismo.
        """
        if schema_id not in self._descriptions:
            stored = self._stored(schema_id)
            index: Dict[str, str] = {}
            if stored is not None and isinstance(stored.raw, dict):
                _index_descriptions(stored.raw, index)
            self._descriptions[schema_id] = index
        return self._descriptions[schema_id].get(name)


class _Accumulator:
    """Estado mutable mientras se recorre la herencia de un schema."""

    def __init__(self) -> None:
        """Arranca vacío y con el schema considerado abierto."""
        self.properties: Dict[str, Tuple[Any, str]] = {}
        self.pattern_properties: Dict[str, Tuple[Any, str]] = {}
        self.required: set = set()
        self.closed = False

    def absorb_conditional(self, schema: Dict[str, Any], origin: str) -> None:
        """Registra las propiedades de una rama condicional como admitidas."""
        for container, target in (
            ("properties", self.properties),
            ("patternProperties", self.pattern_properties),
        ):
            entries = schema.get(container)
            if not isinstance(entries, dict):
                continue
            for name, subschema in entries.items():
                if subschema is False:
                    # La rama la prohíbe, pero solo si la condición se
                    # cumple: no se registra, y tampoco se descarta lo que
                    # otra rama haya admitido.
                    continue
                target.setdefault(name, (subschema, origin))


def _navigate(schema: Dict[str, Any], node_path: str) -> Optional[Dict[str, Any]]:
    """Baja hasta el subnodo indicado por `node_path` dentro del schema."""
    current: Any = schema
    for segment in [part for part in node_path.split("/") if part]:
        if not isinstance(current, dict):
            return None
        properties = current.get("properties")
        pattern_properties = current.get("patternProperties")
        if isinstance(properties, dict) and segment in properties:
            current = properties[segment]
        elif isinstance(pattern_properties, dict) and segment in pattern_properties:
            current = pattern_properties[segment]
        else:
            return None
    return current if isinstance(current, dict) else None


def _pointer_for(schema: Dict[str, Any], node_path: str) -> Optional[str]:
    """Puntero JSON hasta el subnodo indicado dentro del schema.

    Mismo recorrido que `_navigate`, pero devolviendo la ruta en la notación
    de RFC 6901 (`/properties/pwm`) para poder referenciarla con un `$ref`.
    """
    current: Any = schema
    parts: List[str] = []
    for segment in [part for part in node_path.split("/") if part]:
        if not isinstance(current, dict):
            return None
        properties = current.get("properties")
        pattern_properties = current.get("patternProperties")
        if isinstance(properties, dict) and segment in properties:
            container, current = "properties", properties[segment]
        elif isinstance(pattern_properties, dict) and segment in pattern_properties:
            container, current = "patternProperties", pattern_properties[segment]
        else:
            return None
        parts.extend([container, _escape_pointer(segment)])
    return "/" + "/".join(parts) if parts else ""


def _escape_pointer(segment: str) -> str:
    """Escapa un segmento de puntero JSON (RFC 6901)."""
    return segment.replace("~", "~0").replace("/", "~1")


def _split_ref(reference: str, base_id: str) -> Tuple[str, str]:
    """Convierte un `$ref` en (id del schema destino, fragmento interno).

    Las tres formas que usan los bindings, según `writing-schema.rst`: URL
    completa, ruta absoluta (se le antepone el host) y ruta relativa (se
    resuelve contra el `$id` del schema que la escribe).
    """
    target, _, fragment = reference.partition("#")
    if not target:
        target_id = base_id
    elif target.startswith("http"):
        target_id = target
    elif target.startswith("/"):
        target_id = f"{_SCHEMA_HOST}{target}"
    else:
        base = base_id.rsplit("/", 1)[0] if "/" in base_id else _SCHEMA_HOST
        target_id = f"{base}/{target}"
    return (target_id.rstrip("#"), fragment)


def _navigate_fragment(schema: Dict[str, Any], fragment: str) -> Optional[Any]:
    """Baja por el fragmento de un `$ref` (`#/$defs/algo`)."""
    current: Any = schema
    for segment in [part for part in fragment.split("/") if part]:
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def _index_descriptions(schema: Any, index: Dict[str, str], depth: int = 0) -> None:
    """Recoge `properties.<nombre>.description` de todo el documento."""
    if depth > 12 or not isinstance(schema, (dict, list)):
        return
    if isinstance(schema, list):
        for item in schema:
            _index_descriptions(item, index, depth + 1)
        return

    for container in ("properties", "patternProperties"):
        entries = schema.get(container)
        if not isinstance(entries, dict):
            continue
        for name, subschema in entries.items():
            if isinstance(subschema, dict):
                description = subschema.get("description")
                if isinstance(description, str) and name not in index:
                    index[name] = description.strip()

    for value in schema.values():
        _index_descriptions(value, index, depth + 1)


def _child_subschema(
    parent: Dict[str, Any], node_name: str
) -> Optional[Dict[str, Any]]:
    """Busca en un schema el subschema que describe a un hijo por su nombre."""
    properties = parent.get("properties")
    if isinstance(properties, dict):
        direct = properties.get(node_name)
        if isinstance(direct, dict):
            return direct

    pattern_properties = parent.get("patternProperties")
    if isinstance(pattern_properties, dict):
        for pattern, subschema in pattern_properties.items():
            if not isinstance(subschema, dict) or not _is_valid_regex(pattern):
                continue
            if re.search(pattern, node_name):
                return subschema
    return None


def _is_valid_regex(pattern: str) -> bool:
    """Indica si el patrón compila; dt-schema trae alguno con sintaxis rara."""
    try:
        re.compile(pattern)
    except re.error:
        return False
    return True


def _looks_like_node(subschema: Dict[str, Any]) -> bool:
    """Indica si la entrada describe un nodo hijo y no una propiedad."""
    if not isinstance(subschema, dict):
        return False
    if subschema.get("type") == "object":
        return True
    return any(key in subschema for key in ("properties", "patternProperties"))
