"""Validación de un nodo contra los schemas de binding, con `jsonschema`.

Los schemas que la ingesta guardó son JSON Schema de verdad (dt-schema los
deja listos), así que validar un nodo es dárselos a `jsonschema` con el nodo
codificado como instancia. Es lo mismo que hace `dt-validate`, con dos
diferencias:

- La instancia no viene de un DTB sino del texto que se está editando, y solo
  incluye las propiedades que se pueden codificar sin adivinar (ver
  `dts_engine/checks/bindings/instance.py`). Lo que no entra, no se juzga.
- Los `$ref` se resuelven contra la base de datos, no contra ficheros: la
  aplicación instalada no tiene el kernel.

Qué hacer con cada problema encontrado lo decide el motor: aquí solo se
devuelve la palabra clave del schema que falló y un mensaje.

**`typeSize` se ignora a propósito.** Es la palabra clave con la que dt-schema
comprueba el ancho de los enteros (32 frente a 64 bits), y necesita valores
codificados con su tamaño real desde el binario. Desde el texto DTS cada celda
son 32 bits y no se sabe cuántas forma un valor de 64, así que se deja pasar:
`jsonschema` ignora las palabras clave que no conoce, que es justo el
comportamiento que hace falta.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Pattern

import jsonschema
import referencing.exceptions
from referencing import Registry
from referencing.jsonschema import DRAFT201909

from kernelgrove.api.schemas_database import SchemasDatabase
from kernelgrove.dts_engine.checks.bindings.lookup import SchemaIssue

# Tope de problemas que se devuelven por nodo. Un nodo con el tipo equivocado
# en una propiedad de matriz puede generar decenas de errores anidados que
# dicen lo mismo.
_MAX_ISSUES = 12

# El registro de prefijos de fabricante se saca del bucle por nodo y se
# comprueba aparte (`is_known_property_name`). Su `select` es `true`, así que
# aplica a todos los nodos, y sus 966 `patternProperties` costaban 68 de los
# 79 ms que tardaba la capa 2 en un nodo: el 86 % del tiempo para una
# comprobación que solo depende del **nombre** de la propiedad y que por tanto
# se puede resolver con una expresión regular y una memoria.
_VENDOR_PREFIXES_ID = "http://devicetree.org/schemas/vendor-prefixes.yaml"


class SchemaValidator:
    """Valida instancias de nodo contra los schemas guardados en la base."""

    def __init__(self, schemas: SchemasDatabase):
        """Recibe el acceso de lectura a la tabla `schemas`."""
        self._schemas = schemas
        self._registry = Registry(retrieve=self._retrieve)
        self._validators: Dict[str, Any] = {}
        self._select_ids: Optional[List[str]] = None
        self._select_validators: Dict[str, Any] = {}
        self._known_names: Dict[str, bool] = {}
        self._vendor_regex: Any = _UNSET

    # ------------------------------------------------------------------
    # Validación por binding (capa 5)
    # ------------------------------------------------------------------
    def issues(
        self,
        schema_id: str,
        schema: Dict[str, Any],
        instance: Dict[str, Any],
        node_path: str = "",
    ) -> List[SchemaIssue]:
        """Problemas que un schema encuentra en la instancia de un nodo.

        `schema` es el documento a aplicar, que para un subnodo es solo su
        trozo; `schema_id` es el `$id` del fichero del que salió y sirve de
        base para resolver sus `$ref` relativos.
        """
        validator = self._validator(schema_id, schema, node_path)
        if validator is None:
            return []
        return self._collect(validator, instance, schema_id)

    # ------------------------------------------------------------------
    # Validación por clase de dispositivo (capa 2)
    # ------------------------------------------------------------------
    def generic_issues(self, instance: Dict[str, Any]) -> List[SchemaIssue]:
        """Problemas que encuentran los bindings genéricos aplicables.

        Los schemas con `select` no se buscan por compatible: se prueban
        todos, y cada uno decide si le toca. Se evalúan como
        `{"if": select, "then": schema}`, que es la forma en que dt-schema los
        aplica.
        """
        issues: List[SchemaIssue] = []
        for schema_id in self._select_schema_ids():
            validator = self._select_validator(schema_id)
            if validator is None:
                continue
            issues.extend(self._collect(validator, instance, schema_id))
            if len(issues) >= _MAX_ISSUES:
                break
        return issues[:_MAX_ISSUES]

    def select_schema_count(self) -> int:
        """Número de bindings genéricos que se evalúan en la capa 2."""
        return len(self._select_schema_ids())

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------
    def _select_schema_ids(self) -> List[str]:
        """`$id` de los schemas con `select`, cargados una sola vez."""
        if self._select_ids is None:
            self._select_ids = [
                schema_id
                for schema_id in self._schemas.select_schema_ids()
                if schema_id.rstrip("#") != _VENDOR_PREFIXES_ID
            ]
        return self._select_ids

    # ------------------------------------------------------------------
    # Registro de prefijos de fabricante
    # ------------------------------------------------------------------
    def is_known_property_name(self, name: str) -> bool:
        """Indica si el nombre de propiedad usa un prefijo de fabricante registrado.

        `vendor-prefixes.yaml` es el registro de prefijos del kernel: enumera
        con `patternProperties` los que existen y rechaza el resto con
        `additionalProperties: false`. Aquí se reduce a una única expresión
        regular —los 966 patrones unidos— porque la respuesta solo depende del
        nombre y así se puede recordar de un nodo al siguiente.

        Devuelve True si no hay registro con el que comparar: no tenerlo no
        puede convertirse en un aviso sobre el fichero del usuario.
        """
        if name in self._known_names:
            return self._known_names[name]

        pattern = self._vendor_pattern()
        known = True if pattern is None else bool(pattern.search(name))
        self._known_names[name] = known
        return known

    def _vendor_pattern(self) -> Optional[Pattern]:
        """Une los patrones del registro de fabricantes en una sola regex."""
        if self._vendor_regex is _UNSET:
            stored = self._schemas.get_schema(_VENDOR_PREFIXES_ID)
            self._vendor_regex = None
            if stored is not None:
                patterns = [
                    key
                    for key in (stored.schema.get("patternProperties") or {})
                    if _is_regex(key)
                ]
                literals = [
                    re.escape(key)
                    for key in (stored.schema.get("properties") or {})
                ]
                joined = "|".join(
                    [f"(?:{item})" for item in patterns]
                    + [f"(?:^{item}$)" for item in literals]
                )
                if joined:
                    self._vendor_regex = re.compile(joined)
        return self._vendor_regex

    def _validator(
        self, schema_id: str, schema: Dict[str, Any], node_path: str
    ) -> Optional[Any]:
        """Validador de un schema (o de uno de sus subnodos), cacheado.

        Al validar un subnodo se le pone el `$id` del fichero de origen: es la
        base con la que `referencing` resuelve los `$ref` relativos, y sin
        ella un `$ref: rtc.yaml#` dentro del subnodo no se podría localizar.
        """
        key = f"{schema_id}#{node_path}"
        if key not in self._validators:
            if not isinstance(schema, dict) or not schema:
                self._validators[key] = None
            else:
                document = schema if not node_path else {"$id": schema_id, **schema}
                self._validators[key] = jsonschema.Draft201909Validator(
                    document, registry=self._registry
                )
        return self._validators[key]

    def _select_validator(self, schema_id: str) -> Optional[Any]:
        """Validador condicional de un binding genérico (`if select then …`)."""
        if schema_id not in self._select_validators:
            stored = self._schemas.get_schema(schema_id)
            if stored is None or not stored.schema.get("select"):
                self._select_validators[schema_id] = None
            else:
                self._select_validators[schema_id] = jsonschema.Draft201909Validator(
                    {"if": stored.schema["select"], "then": stored.schema},
                    registry=self._registry,
                )
        return self._select_validators[schema_id]

    def _collect(
        self, validator: Any, instance: Dict[str, Any], schema_id: str
    ) -> List[SchemaIssue]:
        """Convierte los errores de jsonschema en `SchemaIssue`."""
        try:
            errors = list(validator.iter_errors(instance))
        except (
            jsonschema.SchemaError,
            referencing.exceptions.Unresolvable,
            RecursionError,
            TypeError,
        ):
            # Un schema mal formado, una referencia que no se puede resolver o
            # un ciclo no son culpa del device tree que se está editando: ni se
            # inventa un diagnóstico ni se tira el análisis por ello.
            return []

        if not errors:
            # El título se lee de la base, así que solo se pide cuando hay algo
            # que contar: en la capa 2 se evalúan 227 schemas por nodo y casi
            # ninguno tiene nada que decir.
            return []

        issues: List[SchemaIssue] = []
        for error in errors:
            for leaf in _leaves(error):
                issues.append(
                    SchemaIssue(
                        keyword=str(leaf.validator),
                        message=leaf.message,
                        property_name=_property_of(leaf),
                        schema_id=schema_id,
                    )
                )
                if len(issues) >= _MAX_ISSUES:
                    return issues
        return issues

    def _retrieve(self, uri: str):
        """Resuelve un `$ref` con los schemas de la base de datos.

        Un `$ref` que no está en la base devuelve un schema vacío, que admite
        cualquier cosa. Es deliberado: no tener el schema no puede convertirse
        en un error inventado sobre el fichero del usuario.
        """
        stored = self._schemas.get_schema(uri)
        return DRAFT201909.create_resource(stored.schema if stored else {})


def _leaves(error: Any, depth: int = 0):
    """Devuelve los errores hoja, deshaciendo los `anyOf`/`oneOf` anidados.

    Un fallo dentro de un `anyOf` llega envuelto en un error genérico («no es
    válido bajo ninguno de los schemas dados») que no dice nada útil; sus
    `context` sí. Solo se bajan los que tienen una única alternativa: si hay
    varias, no se sabe cuál pretendía el usuario y se queda el error de
    arriba.
    """
    if depth > 4:
        return [error]
    context = getattr(error, "context", None)
    if context and len(context) == 1:
        return _leaves(context[0], depth + 1)
    return [error]


def _property_of(error: Any) -> Optional[str]:
    """Nombre de la propiedad a la que apunta el error, si apunta a una."""
    for part in list(getattr(error, "absolute_path", []) or []):
        if isinstance(part, str):
            return part
    # `required` y `dependentRequired` no llevan ruta: el nombre de la
    # propiedad va entre comillas dentro del mensaje («'#gpio-cells' is a
    # dependency of 'gpio-controller'»).
    if error.validator in ("required", "dependentRequired", "dependencies"):
        message = error.message
        if "'" in message:
            return message.split("'")[1]
    return None


class _Unset:
    """Marca de «todavía no calculado», distinta de «no hay»."""


_UNSET = _Unset()


def _is_regex(pattern: str) -> bool:
    """Indica si el patrón compila."""
    try:
        re.compile(pattern)
    except re.error:
        return False
    return True
