"""Agrupado "bonito" de la paleta de dispositivos del grafo, por tipo en vez
del subsistema crudo del kernel (`db_manager/storage.py::get_subsystem`, que
es literalmente el nombre del directorio de `bindings/` del que salió el
YAML — treinta y tantos subsistemas, la mayoría con dos o tres dispositivos).

`_SUBSYSTEM_TO_GROUP` es un mapeo curado a mano, no derivado: un subsistema
del kernel que no aparece aquí cae en `"other"` en vez de desaparecer, así
que un directorio nuevo de `bindings/` en un kernel futuro no rompe nada,
solo se ve menos específico hasta que se le añada su propia entrada.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QIcon

from kernelgrove.gui.widgets import icons

# Orden fijo curado en el que se enseñan los grupos: buses y controladores
# primero (lo que estructura el árbol), luego los periféricos por tipo, y
# "Otros" al final como cajón de sastre.
GROUP_ORDER: List[str] = [
    "buses",
    "usb",
    "network",
    "storage",
    "sensors",
    "audio",
    "display",
    "input",
    "leds",
    "power",
    "timing",
    "security",
    "other",
]

_SUBSYSTEM_TO_GROUP: Dict[str, str] = {
    # Buses y expansores: controladores que a su vez ofrecen un bus.
    "i2c": "buses",
    "spi": "buses",
    "mmc": "buses",
    "gpio": "buses",
    "pinctrl": "buses",
    "usb": "usb",
    "net": "network",
    "phy": "network",
    "mtd": "storage",
    "eeprom": "storage",
    "nvmem": "storage",
    "iio": "sensors",
    "hwmon": "sensors",
    "sound": "audio",
    "display": "display",
    "media": "display",
    "auxdisplay": "display",
    "input": "input",
    "leds": "leds",
    "regulator": "power",
    "power": "power",
    "mfd": "power",
    "rtc": "timing",
    "clock": "timing",
    "pwm": "timing",
    "ptp": "timing",
    "dpll": "timing",
    "tpm": "security",
}

_GROUP_ICONS = {
    "buses": icons.chip_icon,
    "usb": icons.usb_icon,
    "network": icons.network_icon,
    "storage": icons.database_icon,
    "sensors": icons.sensor_icon,
    "audio": icons.speaker_icon,
    "display": icons.display_icon,
    "input": icons.keyboard_icon,
    "leds": icons.led_icon,
    "power": icons.bolt_icon,
    "timing": icons.pulse_icon,
    "security": icons.shield_icon,
    "other": icons.dots_icon,
}


def group_for_subsystem(subsystem: Optional[str]) -> str:
    """Grupo curado al que pertenece un subsistema crudo del kernel."""
    return _SUBSYSTEM_TO_GROUP.get(subsystem or "", "other")


def group_label(key: str) -> str:
    """Nombre visible del grupo, traducido en el momento en que se pide.

    Función y no un diccionario de módulo: al importarse esto todavía no hay
    `QApplication` ni idioma cargado (misma razón que `gui/messages.py`). El
    contexto ("binding_groups") va escrito a mano en cada llamada, no en una
    variable: `lupdate` extrae leyendo el código, y tras esa indirección deja
    de ver las cadenas — probado, se quedaban fuera de los `.ts`.
    """
    if key == "buses":
        return QCoreApplication.translate("binding_groups", "Buses & expanders")
    if key == "usb":
        return QCoreApplication.translate("binding_groups", "USB")
    if key == "network":
        return QCoreApplication.translate("binding_groups", "Network")
    if key == "storage":
        return QCoreApplication.translate("binding_groups", "Storage")
    if key == "sensors":
        return QCoreApplication.translate("binding_groups", "Sensors")
    if key == "audio":
        return QCoreApplication.translate("binding_groups", "Audio")
    if key == "display":
        return QCoreApplication.translate("binding_groups", "Display & video")
    if key == "input":
        return QCoreApplication.translate("binding_groups", "Input")
    if key == "leds":
        return QCoreApplication.translate("binding_groups", "LEDs")
    if key == "power":
        return QCoreApplication.translate("binding_groups", "Power")
    if key == "timing":
        return QCoreApplication.translate("binding_groups", "Clocks & timing")
    if key == "security":
        return QCoreApplication.translate("binding_groups", "Security")
    return QCoreApplication.translate("binding_groups", "Other")


def group_icon(key: str, size: int, color: str) -> QIcon:
    """Icono del grupo, dibujado a mano igual que el resto de `icons.py`."""
    draw = _GROUP_ICONS.get(key, icons.dots_icon)
    return draw(size, color)
