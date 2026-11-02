"""Lado de lectura del índice de macros (capa 3: existencia y valor).

Implementa el protocolo `MacroLookup` de `dts_engine.checks.macros`
directamente sobre la tabla `header_macros` — a diferencia de los bindings
(`api/binding_schemas.py`), aquí no hace falta una capa de resolución
aparte: cada fila ya es la respuesta final (`header_path` incluye el cierre
transitivo de lo que esa cabecera incluye, calculado en la ingesta, y
`value` ya viene expandido por `cpp` si la ingesta pudo hacerlo).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, FrozenSet, List, Optional

from kernelgrove.api.sqlite_reader import SqliteReader


class MacrosDatabase(SqliteReader):
    """Consultas de solo lectura sobre la tabla `header_macros`."""

    def __init__(self, db_path: Path):
        """Guarda la ruta al fichero SQLite y prepara el caché de nombres."""
        super().__init__(db_path)
        self._all_names: Optional[FrozenSet[str]] = None

    def table_exists(self) -> bool:
        """Indica si la tabla `header_macros` está creada."""
        return self._table_exists("header_macros")

    def is_available(self) -> bool:
        """Indica si hay macros indexadas (tabla creada y no vacía)."""
        return self.count() > 0

    def count(self) -> int:
        """Número de filas `(nombre, cabecera)` indexadas."""
        if not self.table_exists():
            return 0
        return self._connect().execute(
            "SELECT COUNT(*) FROM header_macros"
        ).fetchone()[0]

    def names_for(self, header_path: str) -> FrozenSet[str]:
        """Macros visibles al incluir la cabecera `header_path`.

        Ya es el cierre transitivo calculado en la ingesta: no hace falta
        resolver aquí los `#include` de la propia cabecera.
        """
        if not self.table_exists():
            return frozenset()
        rows = self._connect().execute(
            "SELECT name FROM header_macros WHERE header_path = ?",
            (header_path,),
        ).fetchall()
        return frozenset(row[0] for row in rows)

    def values_for(self, header_path: str) -> Dict[str, int]:
        """Valor ya resuelto de cada macro visible al incluir `header_path`.

        Solo las que la ingesta pudo evaluar con `cpp` (columna `value` no
        nula): una macro de función sin argumentos, o una base sin `cpp`
        disponible al construirla, simplemente no aparece aquí — la capa 3
        se calla sobre su valor en vez de inventarlo, igual que con el resto
        de macros sin resolver.
        """
        if not self.table_exists():
            return {}
        rows = self._connect().execute(
            "SELECT name, value FROM header_macros "
            "WHERE header_path = ? AND value IS NOT NULL",
            (header_path,),
        ).fetchall()
        return {row[0]: row[1] for row in rows}

    # ------------------------------------------------------------------
    # Protocolo `MacroLookup` (dts_engine.checks.macros)
    # ------------------------------------------------------------------
    def is_known(self, name: str) -> bool:
        """Indica si `name` está definida en alguna cabecera conocida.

        El conjunto completo de nombres (unos 78k) se carga una vez y se
        cachea en memoria: es más barato que una consulta SQL por cada macro
        que aparece en cada valor, en cada pulsación de tecla.
        """
        return name in self._names()

    def headers_defining(self, name: str) -> List[str]:
        """Cabeceras que declaran `name` (para el hint de qué `#include` falta)."""
        if not self.table_exists():
            return []
        rows = self._connect().execute(
            "SELECT DISTINCT header_path FROM header_macros WHERE name = ? "
            "ORDER BY length(header_path) LIMIT 5",
            (name,),
        ).fetchall()
        return [row[0] for row in rows]

    def _names(self) -> FrozenSet[str]:
        """Carga (una vez) y devuelve el conjunto completo de nombres conocidos."""
        if self._all_names is None:
            if not self.table_exists():
                self._all_names = frozenset()
            else:
                rows = self._connect().execute(
                    "SELECT DISTINCT name FROM header_macros"
                ).fetchall()
                self._all_names = frozenset(row[0] for row in rows)
        return self._all_names
