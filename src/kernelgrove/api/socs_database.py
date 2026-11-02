"""Lado de lectura de las tablas `socs` y `boards`.

Complementa a `BindingsDatabase` (tabla `bindings`). Ambas tablas comparten
esquema —las distingue `db_manager.records.classify_devicetree` al
ingestarlas, no una clase distinta aquí— y son un **catálogo**: identidad
(compatible, vendor, nombre) más `file_path`, la clave del fuente en la tabla
`sources`. El contenido no se guarda aquí; quien quiera el árbol abre el
fuente y lo parsea, que es lo que hace el editor de todas formas.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from kernelgrove.api.dto import SoCSummary
from kernelgrove.api.sqlite_reader import SqliteReader

_VALID_TABLES = {"socs", "boards"}


class SocsDatabase(SqliteReader):
    """Consultas de solo lectura sobre la tabla `socs` o `boards`."""

    def __init__(self, db_path: Path, table_name: str = "socs"):
        """Guarda la ruta al fichero SQLite y la tabla sobre la que consultar.

        `table_name` debe ser `socs` o `boards` — las dos tablas que
        `db_manager` rellena con el mismo esquema. Se valida contra una lista
        cerrada porque de aquí en adelante se interpola directamente en el
        SQL (sqlite no permite parametrizar nombres de tabla).
        """
        if table_name not in _VALID_TABLES:
            raise ValueError(f"table_name must be one of {_VALID_TABLES}")
        super().__init__(db_path)
        self.table_name = table_name

    def table_exists(self) -> bool:
        """Indica si la tabla está creada (la ingesta puede no haberse hecho)."""
        return self._table_exists(self.table_name)

    def list_socs(self, limit: Optional[int] = None) -> List[SoCSummary]:
        """Lista todas las entradas registradas, ordenadas por nombre."""
        if not self.table_exists():
            return []

        # Las columnas de hardware (`arch`, `cores`…) las añade `ensure_column`
        # en la ingesta, así que una base construida antes no las tiene: se
        # piden solo si están y las entradas salen con esos campos vacíos, que
        # es lo que la ficha enseña como «—». Fallar aquí dejaría la
        # aplicación sin catálogo por un dato accesorio.
        extra = [
            name
            for name in ("arch", "cores", "ram", "clock", "model")
            if name in self._columns(self.table_name)
        ]
        columnas = ", ".join(
            ["id", "name", "compatible", "vendor", "file_path", *extra]
        )
        query = (
            f"SELECT {columnas} FROM {self.table_name} ORDER BY name, compatible"
        )
        params: tuple = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (limit,)

        cursor = self._connect().execute(query, params)
        return [
            SoCSummary(
                name=row[1] or "",
                compatible=row[2] or "",
                vendor=row[3],
                file_path=row[4],
                **dict(zip(extra, row[5:])),
            )
            for row in cursor.fetchall()
        ]

    def _columns(self, table: str) -> set:
        """Nombres de columna de una tabla, preguntados una vez por sesión."""
        if not hasattr(self, "_column_cache"):
            self._column_cache = {}
        if table not in self._column_cache:
            cursor = self._connect().execute(f"PRAGMA table_info({table})")
            self._column_cache[table] = {row[1] for row in cursor.fetchall()}
        return self._column_cache[table]
