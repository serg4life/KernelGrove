"""Vocabulario de la capa 5: qué necesita el motor saber de un binding.

El motor no conoce SQLite ni dt-schema: define aquí la forma de la respuesta
y el protocolo `SchemaLookup` que alguien —hoy `api/binding_schemas.py`—
tiene que implementar. Trabaja sobre los schemas ya procesados por
dt-schema en vez de sobre el YAML crudo, y de ahí dos rasgos propios:

- La herencia está resuelta. `properties` y `required` incluyen lo que el
  binding hereda por `allOf`/`$ref`, que es donde vive la mitad de la
  información: 1988 entradas `required` del kernel (entre ellas `reg` en 221
  bindings) solo aparecen tras seguir las referencias.
- Se sabe si el schema está **cerrado**. Un binding con
  `additionalProperties: false` enumera todas las propiedades admisibles, y
  solo entonces se puede decir que una propiedad sobra.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Protocol, Tuple


# Palabras clave del schema que hablan del **valor** de una propiedad. Son las
# únicas que las capas 2 y 5 cuentan del resultado de una validación:
# `required`, `additionalProperties` y compañía las cubren sus propias reglas,
# que saben mirar el árbol fusionado y rebajar el aviso cuando no es
# concluyente.
VALUE_KEYWORDS = frozenset(
    {
        "const",
        "contains",
        "enum",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "maxItems",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "multipleOf",
        "pattern",
        "type",
        "uniqueItems",
    }
)

def schema_file(schema_id: str) -> str:
    """Nombre del fichero del binding, que es adonde hay que ir a mirar.

    El identificador de un schema es una URL
    (`http://devicetree.org/schemas/i2c/cdns,i2c-r1p10.yaml#`); de ella lo
    único que sirve para buscar es el fichero.
    """
    return schema_id.rstrip("#").rsplit("/", 1)[-1]


def property_hint(prop: Optional["SchemaProperty"]) -> Optional[str]:
    """Qué hay que saber para escribir una propiedad: su tipo y qué es.

    Es lo que va en la columna de sugerencias de un aviso. Antes iba ahí el
    **título del binding** («ARM Performance Monitor Units»), que ya se
    deduce del compatible que el propio mensaje nombra y no dice nada de la
    propiedad: la sugerencia repetía la pregunta en vez de responderla.

    De la descripción se toma solo la primera línea: los bindings las
    escriben en párrafos de varias frases y la columna tiene el ancho que
    tiene.
    """
    if prop is None:
        return None
    partes = []
    if prop.dt_type:
        partes.append(prop.dt_type)
    items = prop.schema.get("items")
    valores = prop.schema.get("enum")
    if valores is None and isinstance(items, dict):
        # Los bindings declaran el `enum` de un array dentro de `items`.
        valores = items.get("enum")
    if isinstance(valores, list) and valores:
        muestra = ", ".join(str(valor) for valor in valores[:4])
        if len(valores) > 4:
            muestra += "…"
        partes.append(muestra)
    elif prop.description:
        primera = prop.description.strip().splitlines()[0].strip()
        if len(primera) > 90:
            primera = primera[:89].rstrip() + "…"
        if primera:
            partes.append(primera)
    return " · ".join(partes) or None


@dataclass(frozen=True)
class SchemaProperty:
    """Una propiedad admitida por un binding."""

    name: str
    # Subschema JSON tal y como lo dejó dt-schema (enum, const, maxItems...).
    schema: Dict[str, Any] = field(default_factory=dict)
    required: bool = False
    # Schema del que procede: el propio binding o alguno de sus `$ref`.
    origin: str = ""
    # Texto de ayuda, tomado del YAML original (los fixups lo eliminan).
    description: Optional[str] = None
    # Tipo de device tree ('uint32', 'string-array', 'phandle-array'...).
    dt_type: Optional[str] = None
    # La entrada describe un nodo hijo, no una propiedad escalar.
    is_node: bool = False


@dataclass(frozen=True)
class SchemaIssue:
    """Un problema que un schema encuentra en el valor de una propiedad.

    Lo produce quien valide de verdad (hoy `api/schema_validator.py`, con
    `jsonschema`); el motor solo decide qué contar y con qué gravedad, y para
    eso le basta saber **qué palabra clave** del schema falló.
    """

    # 'enum', 'const', 'type', 'maxItems', 'minimum', 'required'...
    keyword: str
    message: str
    property_name: Optional[str] = None
    schema_id: str = ""


@dataclass(frozen=True)
class NodeSchema:
    """Lo que un binding dice de un nodo concreto.

    `properties` está indexado por nombre; `pattern_properties` recoge las
    familias de nombres (`^pinctrl-[0-9]+$`), que hay que probar una a una.
    """

    compatible: str
    schema_id: str = ""
    # Ruta del nodo dentro del schema: vacía para el nodo del propio binding,
    # `"pwm"` para un subnodo suyo. Hace falta para validar contra el trozo
    # correcto del documento.
    node_path: str = ""
    title: Optional[str] = None
    properties: Mapping[str, SchemaProperty] = field(default_factory=dict)
    pattern_properties: Tuple[Tuple[str, SchemaProperty], ...] = ()
    required: Tuple[str, ...] = ()
    # El schema enumera todas las propiedades admisibles
    # (`additionalProperties`/`unevaluatedProperties` a false).
    closed: bool = False

    def property_for(self, name: str) -> Optional[SchemaProperty]:
        """Devuelve la definición de una propiedad, por nombre o por patrón."""
        direct = self.properties.get(name)
        if direct is not None:
            return direct
        for pattern, prop in self.pattern_properties:
            try:
                if re.search(pattern, name):
                    return prop
            except re.error:
                continue
        return None

    def allows(self, name: str) -> bool:
        """Indica si el binding admite una propiedad con ese nombre."""
        return self.property_for(name) is not None


class SchemaLookup(Protocol):
    """Acceso a los schemas de binding que el motor consulta."""

    def schema_for(self, compatible: str) -> Optional[NodeSchema]:
        """Devuelve lo que el binding dice del nodo, o None si no hay binding."""
        ...

    def is_documented(self, compatible: str) -> bool:
        """Indica si algún binding declara ese compatible."""
        ...

    def since(self, schema_id: str) -> Optional[str]:
        """Versión del kernel en la que apareció ese binding ('6.3').

        `None` cuando no consta: una base construida sin la columna, o un
        schema que no viene del kernel (los que trae dt-schema). Sin dato no
        se dice nada, que es la regla de siempre.
        """
        ...

    def child_schema_for(
        self, compatible: str, node_name: str
    ) -> Optional[NodeSchema]:
        """Devuelve lo que el binding de un nodo dice de un hijo suyo.

        Un bus describe en su propio binding las propiedades que pueden
        llevar los dispositivos que cuelgan de él (`mc-peripheral-props.yaml`
        para el bus de memoria externa, por ejemplo). Sin mirar ahí, esas
        propiedades parecen no admitidas por el binding del dispositivo, que
        efectivamente no las conoce.
        """
        ...

    def property_type(self, name: str) -> Optional[str]:
        """Tipo de device tree de una propiedad ('uint32', 'string-array'...).

        None cuando no consta o cuando aparece con tipos incompatibles en
        bindings distintos, y entonces su valor no se codifica.
        """
        ...

    def validate_node(
        self, schema: NodeSchema, instance: Dict[str, Any]
    ) -> List[SchemaIssue]:
        """Valida la instancia de un nodo contra el schema de su binding."""
        ...

    def property_shape(self, name: str) -> Optional[str]:
        """Forma que tiene el valor de una propiedad en el schema.

        'scalar' (un entero), 'array' (lista de enteros), 'matrix' (lista de
        listas), 'string', 'flag', 'phandle' o 'scalar-or-array' cuando el
        tipo declarado admite las dos. None si no consta o si las formas
        posibles no se pueden reducir a una, y entonces el valor no se
        codifica.
        """
        ...

    def is_known_property_name(self, name: str) -> bool:
        """Indica si el nombre usa un prefijo de fabricante registrado.

        El registro es `vendor-prefixes.yaml`, que el kernel mantiene. Un
        `acme,foo` con un prefijo que no existe suele ser una errata.
        """
        ...

    def validate_generic(self, instance: Dict[str, Any]) -> List[SchemaIssue]:
        """Valida la instancia contra los bindings genéricos que le apliquen.

        Son los schemas con `select`, que dt-schema prueba contra todos los
        nodos: clases de dispositivo, buses y propiedades comunes. Es la
        capa 2 del motor.
        """
        ...
