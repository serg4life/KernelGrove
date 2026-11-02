"""Contrato de versión entre la aplicación y el fichero `bindings.db`.

La base de datos **no viaja con el software**: el usuario apunta a la suya,
a la de KernelGrove o a la de un tercero (`KERNELGROVE_DB_PATH`). Sin un número de
versión escrito dentro, lo único que se comprobaba al arrancar era que el
fichero existiera, y una base vieja o ajena degradaba en silencio —"la capa 5
no dice nada" es indistinguible, mirando la pantalla, de "tu device tree está
perfecto"—.

Aquí vive el número y aquí se sube cuando un cambio de esquema deje de ser
compatible hacia atrás. Lo escribe la ingesta (`db_manager.storage.
init_sqlite_db`) y lo lee la aplicación (`api.service.database_warning`).
Este módulo no importa nada a propósito: es el único punto que comparten los
dos lados, que por lo demás no se conocen.
"""

from __future__ import annotations

# Versión que esta aplicación sabe leer. Súbela cuando un cambio en las
# tablas no sea compatible con bases ya distribuidas.
DB_SCHEMA_VERSION = 1

# Clave bajo la que se guarda en la tabla `schema_meta`.
DB_SCHEMA_VERSION_KEY = "app_schema_version"
