"""Estado que quedó guardado con el nombre anterior de la aplicación.

Hasta la 1.0b2 esto se llamaba DTstudio, y con ese nombre guardaba tres
cosas del usuario: el directorio de estado `~/.dtstudio`, los ajustes de Qt
bajo la organización «DTstudio», y las variables de entorno `DTSTUDIO_*`.
Cambiarle el nombre al programa no puede costarle al usuario lo que ya tenía
configurado, así que lo anterior se recoge una vez y en silencio.

Nada de esto es permanente: cuando no queden instalaciones de la beta
anterior, este módulo se borra entero y con él sus dos llamadas.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_PREFIJO_VIEJO = "DTSTUDIO_"
_PREFIJO_NUEVO = "KERNELGROVE_"

_DIR_VIEJO = Path.home() / ".dtstudio"
_DIR_NUEVO = Path.home() / ".kernelgrove"

_QT_VIEJO = ("DTstudio", "DeviceTreeStudio")


def alias_env() -> None:
    """Hace que cada `DTSTUDIO_*` valga como su `KERNELGROVE_*`.

    Un bucle sobre el entorno y no un alias por variable: las variables
    están repartidas entre `main`, `db_download` y `translations`, y varias
    se leen al importar el módulo — por eso esto se llama desde
    `kernelgrove/__init__`, que es lo primero que corre. La nueva gana
    siempre: quien haya puesto las dos está diciendo cuál quiere.
    """
    for nombre, valor in list(os.environ.items()):
        if nombre.startswith(_PREFIJO_VIEJO):
            os.environ.setdefault(_PREFIJO_NUEVO + nombre[len(_PREFIJO_VIEJO):], valor)


def migrate_state() -> None:
    """Trae el directorio de estado y los ajustes de Qt del nombre anterior.

    Solo si no hay nada nuevo todavía: con las dos versiones presentes manda
    la nueva, que es la que el usuario está usando. El directorio se mueve
    en vez de copiarse para que esto ocurra una sola vez y no quede el
    estado duplicado en dos sitios.
    """
    if _DIR_VIEJO.is_dir() and not _DIR_NUEVO.exists():
        shutil.move(str(_DIR_VIEJO), str(_DIR_NUEVO))

    try:
        from PySide6.QtCore import QSettings
    except ImportError:
        # Este módulo tiene que poder correr sin Qt, igual que `main`: es lo
        # que hace que «no tienes PySide6» sea un mensaje y no una traza.
        return

    from kernelgrove.main import SETTINGS_APP, SETTINGS_ORG

    nuevos = QSettings(SETTINGS_ORG, SETTINGS_APP)
    if nuevos.allKeys():
        return
    viejos = QSettings(*_QT_VIEJO)
    claves = viejos.allKeys()
    if not claves:
        return
    for clave in claves:
        nuevos.setValue(clave, viejos.value(clave))
    nuevos.sync()
