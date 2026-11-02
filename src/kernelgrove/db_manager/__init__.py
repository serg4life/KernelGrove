"""Ingesta offline: del checkout del kernel a `database/bindings.db`.

Se usa desde la CLI (`python -m kernelgrove.db_manager.main`, ver
`scripts/build_database.sh`); la aplicación no importa nada de aquí en
tiempo de ejecución —lee la base ya construida a través de `kernelgrove.api`—,
así que este paquete no reexporta nada.
"""
