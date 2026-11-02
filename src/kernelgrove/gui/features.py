"""Qué funciones están todavía en desarrollo.

Una release solo lleva lo que ya está pulido. Lo demás —hoy, **generar**
desde el grafo: la sección «Connections», la paleta de dispositivos, tocar el
árbol desde el grafo, el panel del SoC y «Desconectar dispositivo»— se monta
en un checkout de desarrollo y no en un ejecutable distribuido. La
*visualización* del grafo sí es estable y va siempre.

La costura es `sys.frozen`, la misma que usa `main._app_root()`: la ponen
PyInstaller y compañía, y es exactamente «esto es un build distribuido».
`KERNELGROVE_EXPERIMENTAL` manda sobre ella en los dos sentidos —`1` las
enciende en una release para probarlas, `0` las apaga en un checkout para
ver lo que verá el usuario—.

La pregunta se hace **una vez, al construir la ventana**: encender o apagar
en caliente querría decir rehacer la franja de iconos y los menús.

Para que algo nuevo nazca como experimental basta con preguntar
`experimental()` donde se monte y apuntarlo arriba; cuando esté pulido, se
quita la pregunta.
"""

from __future__ import annotations

import os
import sys


def experimental() -> bool:
    """Si se montan las funciones que todavía no van en una release."""
    forzado = os.environ.get("KERNELGROVE_EXPERIMENTAL", "")
    if forzado in ("0", "1"):
        return forzado == "1"
    return not getattr(sys, "frozen", False)
