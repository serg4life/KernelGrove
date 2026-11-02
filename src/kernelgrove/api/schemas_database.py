"""Lado de lectura de las tablas `schemas`, `schema_compatibles` y `schema_meta`.

Guardan los bindings del kernel ya procesados por dt-schema durante la
ingesta (ver `db_manager/schemas.py`). Son la fuente de la capa 5 del motor
semántico y del autocompletado: qué propiedades admite un compatible, cuáles
exige y de qué tipo es cada una.

La tabla es opcional: una base construida antes de esta integración —o sin
`dtschema` instalado— simplemente no la tiene, y todo lo que dependa de ella
tiene que quedarse callado en lugar de fallar.
"""

from __future__ import annotations

import json
import re
import sqlite3
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from kernelgrove.api.sqlite_reader import SqliteReader
from kernelgrove.db_schema import DB_SCHEMA_VERSION_KEY


@dataclass(frozen=True)
class StoredSchema:
    """Un schema de binding recuperado de la base de datos."""

    schema_id: str
    path: str
    title: Optional[str]
    # Schema procesado por dt-schema: notación expandida, tipos normalizados
    # y propiedades implícitas añadidas.
    schema: Dict[str, Any]
    # YAML original. Es lo único que conserva `description` y `examples`: los
    # fixups de dt-schema los eliminan por ser irrelevantes para validar.
    raw: Optional[Dict[str, Any]]


def _version_key(version: str) -> tuple:
    """Ordena una versión ('6.10') por sus números y no como texto."""
    return tuple(int(numero) for numero in re.findall(r"\d+", version))


@dataclass(frozen=True)
class SchemaMatch:
    """Dónde está descrito un compatible: schema y nodo dentro de él."""

    schema_id: str
    # Ruta de subnodos dentro del schema; vacía si es el nodo del binding.
    node_path: str


class SchemasDatabase(SqliteReader):
    """Consultas de solo lectura sobre los schemas procesados."""

    def __init__(self, db_path: Path):
        """Guarda la ruta al fichero SQLite y prepara los cachés de la clase."""
        super().__init__(db_path)
        self._available: Optional[bool] = None
        self._patterns: Optional[List[Tuple[re.Pattern, SchemaMatch]]] = None
        self._since_column: Optional[bool] = None

    def since(self, schema_id: str) -> Optional[str]:
        """Versión del kernel desde la que existe ese binding, si consta.

        La calcula la ingesta a partir de la historia del repositorio
        (`db_manager/kernel_versions.py`) y la guarda en `schemas.since`.
        `None` en tres casos que no se distinguen aquí porque no hacen
        falta: una base construida antes de que existiera la columna, un
        schema que no viene del kernel (los que trae dt-schema) y un
        checkout sin historia de git.
        """
        if not self.is_available() or not self._has_since():
            return None
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT since FROM schemas WHERE id = ?", (schema_id.rstrip("#"),)
            )
            row = cursor.fetchone()
        return row[0] if row and row[0] else None

    def kernel_releases(self) -> List[str]:
        """Releases del kernel presentes en `schemas.since`, la más nueva primero.

        Es la lista que se le ofrece al usuario para elegir contra qué kernel
        trabaja: sale de la base, así que dice exactamente hasta dónde puede
        comprobar.
        """
        if not self.is_available() or not self._has_since():
            return []
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT since FROM schemas"
                " WHERE since IS NOT NULL AND since != ''"
            )
            versiones = [row[0] for row in cursor.fetchall()]
        return sorted(versiones, key=_version_key, reverse=True)

    def _has_since(self) -> bool:
        """Si la base es lo bastante nueva para traer la columna.

        Se mira una vez: las bases ya construidas no la tienen y hay que
        seguir sirviéndolas, igual que con `subsystem` o con las columnas de
        hardware de `socs`.
        """
        if self._since_column is None:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(schemas)")
                self._since_column = any(row[1] == "since" for row in cursor.fetchall())
        return self._since_column

    def is_available(self) -> bool:
        """Indica si la base incluye los schemas procesados.

        Se consulta una vez y se recuerda: lo llaman todas las comprobaciones
        de la capa 5, en cada análisis del editor.
        """
        if self._available is None:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name IN ('schemas', 'schema_compatibles')"
                )
                self._available = len(cursor.fetchall()) == 2
        return self._available

    def count(self) -> int:
        """Número de schemas almacenados."""
        if not self.is_available():
            return 0
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM schemas").fetchone()[0]

    def app_schema_version(self) -> Optional[int]:
        """Versión del esquema con la que se construyó la base, si la declara.

        `None` en una base anterior a que existiera la marca (ver
        `kernelgrove.db_schema`), que es indistinguible de "muy antigua": quien
        pregunte decide qué hacer con esa ambigüedad.

        No pasa por `_meta` porque ese exige que la base traiga los schemas
        procesados, y la versión del fichero hay que poder leerla también en
        una base construida sin ellos.
        """
        if not self._table_exists("schema_meta"):
            return None
        row = self._connect().execute(
            "SELECT value FROM schema_meta WHERE key = ?", (DB_SCHEMA_VERSION_KEY,)
        ).fetchone()
        value = _decompress(row[0]) if row else None
        return value if isinstance(value, int) else None

    def dtschema_version(self) -> Optional[str]:
        """Versión de dtschema con la que se generaron los schemas.

        Los schemas procesados no son intercambiables entre versiones, así que
        conviene poder mostrar con cuál se construyó la base.
        """
        value = self._meta("version")
        return str(value) if value else None

    def property_types(self) -> Dict[str, Any]:
        """Tipo de cada propiedad conocida, por nombre exacto."""
        return self._meta("types") or {}

    def pattern_property_types(self) -> Dict[str, Any]:
        """Tipo de las propiedades que solo se conocen por patrón."""
        return self._meta("pattern-types") or {}

    def get_schema(self, schema_id: str) -> Optional[StoredSchema]:
        """Recupera un schema por su `$id`."""
        if not self.is_available():
            return None
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, path, title, schema, raw FROM schemas WHERE id = ?",
                (schema_id.rstrip("#"),),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return StoredSchema(
            schema_id=row[0],
            path=row[1] or "",
            title=row[2],
            schema=_decompress(row[3]) or {},
            raw=_decompress(row[4]),
        )

    def match_compatible(self, compatible: str) -> Optional[SchemaMatch]:
        """Localiza el schema que describe un compatible.

        La resolución es exacta. Los empates —el kernel tiene compatibles
        duplicados, y dt-schema los avisa— se ordenan por tres criterios:

        1. El binding que **se llama como el compatible**: `panel-lvds` lo
           declaran seis paneles concretos además de `panel-lvds.yaml`, y es
           este último el que lo describe. Sin este desempate, una pantalla
           genérica se validaba contra el binding de un panel Advantech y
           heredaba sus medidas exactas como valores obligatorios.
        2. La posición en la lista de compatibles del nodo: el primero
           identifica al dispositivo, los siguientes son familias.
        3. El que lo describe como nodo propio y no como subnodo.

        Como último recurso se prueban los compatibles declarados con
        expresión regular, que son los de familias enteras.
        """
        if not self.is_available():
            return None
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT schema_id, node_path FROM schema_compatibles "
                "WHERE compatible = ? AND is_pattern = 0 "
                "ORDER BY CASE WHEN schema_id LIKE ? THEN 0 ELSE 1 END, "
                "position, length(node_path), schema_id LIMIT 1",
                (compatible, f"%/{compatible}.yaml"),
            )
            row = cursor.fetchone()
        if row is not None:
            return SchemaMatch(schema_id=row[0], node_path=row[1] or "")
        return self._match_pattern(compatible)

    def is_documented(self, compatible: str) -> bool:
        """Indica si algún binding declara ese compatible."""
        return self.match_compatible(compatible) is not None

    def list_subdevices(self, compatible: str) -> List[Tuple[str, str]]:
        """Compatibles que el binding de `compatible` declara para sus subnodos.

        Un MFD como `ti,twl4030` describe en su propio binding las funciones
        que lleva dentro (`ti,twl4030-pwm`, `ti,twl4030-gpio`...). No cuelgan
        de un bus, así que no aparecen por `parent_bus`: se llega a ellas
        desde el dispositivo que las contiene.

        Devuelve `(compatible, node_path)` ordenados por nombre.
        """
        match = self.match_compatible(compatible)
        if match is None or match.node_path:
            # Un subnodo no tiene subnodos propios registrados por esta vía.
            return []

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT compatible, node_path FROM schema_compatibles "
                "WHERE schema_id = ? AND node_path <> '' AND is_pattern = 0 "
                "ORDER BY compatible",
                (match.schema_id,),
            )
            return [(row[0], row[1]) for row in cursor.fetchall()]

    def select_schema_ids(self) -> List[str]:
        """`$id` de los schemas que se aplican por la forma del nodo.

        Son los bindings genéricos —clases de dispositivo, buses, propiedades
        comunes— que dt-schema evalúa contra todos los nodos en vez de
        buscarlos por compatible. En el kernel son 228 de 5663.
        """
        if not self.is_available():
            return []
        with self._connect() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT id FROM schemas WHERE has_select = 1 ORDER BY id"
                )
            except sqlite3.OperationalError:
                # Base construida antes de que existiera la columna.
                return []
            return [row[0] for row in cursor.fetchall()]

    def list_compatibles(self, prefix: str, limit: int = 50) -> List[str]:
        """Lista compatibles documentados que empiezan por `prefix`."""
        if not self.is_available():
            return []
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT compatible FROM schema_compatibles "
                "WHERE is_pattern = 0 AND compatible LIKE ? "
                "ORDER BY compatible LIMIT ?",
                (f"{prefix}%", limit),
            )
            return [row[0] for row in cursor.fetchall()]

    def _match_pattern(self, compatible: str) -> Optional[SchemaMatch]:
        """Prueba los compatibles declarados como expresión regular."""
        if self._patterns is None:
            self._patterns = []
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT compatible, schema_id, node_path FROM schema_compatibles "
                    "WHERE is_pattern = 1"
                )
                for pattern, schema_id, node_path in cursor.fetchall():
                    try:
                        compiled = re.compile(pattern)
                    except re.error:
                        continue
                    self._patterns.append(
                        (compiled, SchemaMatch(schema_id, node_path or ""))
                    )

        for compiled, match in self._patterns:
            if compiled.search(compatible):
                return match
        return None

    def _meta(self, key: str) -> Any:
        """Lee una entrada de `schema_meta`, descomprimida."""
        if not self.is_available():
            return None
        with self._connect() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT value FROM schema_meta WHERE key = ?", (key,))
            except sqlite3.OperationalError:
                return None
            row = cursor.fetchone()
        return _decompress(row[0]) if row else None


def _decompress(blob: Optional[bytes]) -> Any:
    """Descomprime y deserializa un documento guardado con zlib+JSON."""
    if blob is None:
        return None
    return json.loads(zlib.decompress(blob).decode("utf-8"))
