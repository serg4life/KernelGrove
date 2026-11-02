"""Lado de lectura de la tabla `sources`.

Guarda el texto de todos los `.dts`/`.dtsi` y de las cabeceras `dt-bindings`
que la ingesta encontró. La aplicación instalada no tiene el kernel clonado,
así que esta tabla es la única forma de abrir un fichero incluido: el checkout
del kernel solo interviene al construir la base.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from kernelgrove.api.sqlite_reader import SqliteReader


@dataclass(frozen=True)
class StoredSource:
    """Un fuente recuperado de la base de datos."""

    path: str
    name: str
    kind: str
    text: str


class SourcesDatabase(SqliteReader):
    """Consultas de solo lectura sobre la tabla `sources`."""

    def table_exists(self) -> bool:
        """Indica si la tabla `sources` está creada."""
        return self._table_exists("sources")

    def count(self) -> int:
        """Número de fuentes almacenados."""
        if not self.table_exists():
            return 0
        return self._connect().execute("SELECT COUNT(*) FROM sources").fetchone()[0]

    def get(self, path: str) -> Optional[StoredSource]:
        """Recupera un fuente por su ruta exacta."""
        return self._fetch_one(
            "SELECT path, name, kind, source FROM sources WHERE path = ?", (path,)
        )

    def find_by_suffix(self, target: str) -> Optional[StoredSource]:
        """Busca el fuente cuya ruta termina en `target`.

        Los `#include <dt-bindings/gpio/gpio.h>` indican una ruta parcial, no
        completa, así que hay que buscar por el final de la ruta almacenada.

        **El filtro es el nombre de fichero, no un `LIKE '%/…'`.** Un comodín
        al principio impide usar ningún índice, así que la consulta anterior
        recorría las 7 512 filas de `sources` —cada una con su BLOB al lado—
        en cada include a resolver: 3,58 ms por llamada, unas catorce por
        análisis del editor. Filtrando por `name` se usa `idx_sources_name` y
        la misma búsqueda baja a 0,02 ms; el sufijo completo se comprueba
        después en Python sobre el puñado de rutas que comparten nombre.

        Se queda la ruta más corta de las que casan, igual que hacía el
        `ORDER BY length(path)` de antes.
        """
        normalized = target.replace("\\", "/").lstrip("./")
        if not self.table_exists():
            return None

        basename = normalized.rsplit("/", 1)[-1]
        cursor = self._connect().execute(
            "SELECT path FROM sources WHERE name = ?", (basename,)
        )
        candidates = [
            path
            for (path,) in cursor.fetchall()
            if path == normalized or path.endswith(f"/{normalized}")
        ]
        if not candidates:
            return None
        return self.get(min(candidates, key=len))

    def find_by_name(self, name: str) -> List[StoredSource]:
        """Lista los fuentes cuyo nombre de fichero coincide."""
        if not self.table_exists():
            return []
        cursor = self._connect().execute(
            "SELECT path, name, kind, source FROM sources "
            "WHERE name = ? ORDER BY length(path)",
            (name,),
        )
        return [_row_to_source(row) for row in cursor.fetchall()]

    def write_headers(self, directory: Path) -> int:
        """Vuelca las cabeceras `dt-bindings` de la base a un directorio.

        `cpp` solo sabe leer un sistema de ficheros, pero aquí los fuentes
        viven dentro de `bindings.db` — que es justo lo que permite que la
        aplicación funcione sin un checkout del kernel. Compilar obliga a
        deshacer eso en un directorio temporal.

        Se respeta la ruta relativa de cada cabecera (`dt-bindings/gpio/
        gpio.h`), porque es la que aparece en los `#include` y la que
        `cpp -I` tiene que poder recorrer. Devuelve cuántas escribió.
        """
        if not self.table_exists():
            return 0

        escritas = 0
        cursor = self._connect().execute(
            "SELECT path, source FROM sources WHERE kind = 'header'"
        )
        for path, blob in cursor.fetchall():
            relativa = _include_relative_path(path)
            if relativa is None:
                continue
            destino = directory / relativa
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(zlib.decompress(blob))
            escritas += 1
        return escritas

    def _fetch_one(self, query: str, params: tuple) -> Optional[StoredSource]:
        """Ejecuta una consulta y convierte la primera fila, si la hay."""
        if not self.table_exists():
            return None
        row = self._connect().execute(query, params).fetchone()
        return _row_to_source(row) if row else None


def _include_relative_path(path: str) -> Optional[str]:
    """Ruta con la que un `#include` nombra a esta cabecera.

    En la base cada cabecera se guarda con su ruta dentro del checkout
    (`kernel/linux/include/dt-bindings/gpio/gpio.h`), pero un fuente la
    incluye por lo que va de `dt-bindings/` en adelante. Lo que hay antes es
    la raíz que se le pasa a `cpp` con `-I`.
    """
    marca = "dt-bindings/"
    posicion = path.find(marca)
    return path[posicion:] if posicion != -1 else None


def _row_to_source(row: tuple) -> StoredSource:
    """Convierte una fila de `sources`, descomprimiendo el texto."""
    return StoredSource(
        path=row[0],
        name=row[1],
        kind=row[2],
        text=zlib.decompress(row[3]).decode("utf-8", errors="replace"),
    )
