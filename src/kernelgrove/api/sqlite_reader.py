"""Base común de las clases de lectura sobre `bindings.db`.

Todas abren el mismo fichero SQLite y hacen lo mismo con él: consultas de
solo lectura, desde el hilo de la interfaz y desde los hilos de fondo. Lo
único que compartían hasta ahora era el patrón —y solo `BindingsDatabase`
tenía la versión buena—, así que aquí queda una sola vez.

**Una conexión por hilo, reutilizada entre consultas.** Abrir una por
consulta costaba 215 conexiones en cada análisis del editor y 1 369 en cada
pasada diferida, y con cada una se tiraba también el caché de páginas de
SQLite. `threading.local` evita compartir la conexión entre hilos —sqlite3
lo prohíbe por defecto— sin tener que serializar el acceso con un lock.

Ojo con el `with self._connect() as conn:` que queda en algunos llamantes: el
gestor de contexto de sqlite3 delimita la **transacción**, no la conexión —
nunca la ha cerrado. Sobre lecturas es inofensivo, y ahora además es lo
correcto: la conexión sobrevive al bloque a propósito.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


class SqliteReader:
    """Acceso de solo lectura a un fichero SQLite, con conexión por hilo."""

    def __init__(self, db_path: Path):
        """Guarda la ruta; la conexión se abre de forma perezosa por hilo."""
        self.db_path = db_path
        self._local = threading.local()

    def _connect(self) -> sqlite3.Connection:
        """Devuelve la conexión de este hilo, abriéndola la primera vez."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.db_path))
            self._on_connect(conn)
            self._local.conn = conn
        return conn

    def _on_connect(self, conn: sqlite3.Connection) -> None:
        """Gancho para lo que haya que hacer una vez por conexión nueva.

        Solo `BindingsDatabase` lo usa, para migrar la columna `subsystem` de
        bases antiguas; el resto no necesita nada.
        """

    def _table_exists(self, name: str) -> bool:
        """Indica si existe la tabla indicada (la ingesta puede no haberse hecho)."""
        cursor = self._connect().execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        )
        return cursor.fetchone() is not None
