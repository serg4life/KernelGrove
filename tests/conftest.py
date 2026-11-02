"""Utilidades compartidas por las pruebas."""

from __future__ import annotations

import os
import tempfile
from typing import Any, List

import pytest

# **Los ajustes de la suite no son los del usuario.** `MainWindow` guarda
# piel, modo e idioma en `QSettings`, y varias pruebas los cambian: sin esto
# `pytest` reescribía el `~/.config/KernelGrove/…conf` de quien lo lanza, y el
# tema de su aplicación quedaba en el que dejara la última prueba. También
# es lo que las hace repetibles: leen lo que ellas mismas han escrito y no
# lo que hubiera en la máquina.
_AJUSTES_TMP = tempfile.mkdtemp(prefix="kernelgrove-settings-")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["XDG_CONFIG_HOME"] = _AJUSTES_TMP


@pytest.fixture
def qt_signal():
    """Recoge lo que emita una señal de Qt, sin montar un bucle de eventos.

    Devuelve una función: se le pasa la señal y devuelve la lista donde se
    van acumulando sus emisiones. Evita repetir el mismo `connect` a una
    lista en cada prueba que comprueba qué emitió un widget.
    """

    def collect(signal) -> List[Any]:
        recibido: List[Any] = []
        signal.connect(
            lambda *args: recibido.append(args[0] if len(args) == 1 else args)
        )
        return recibido

    return collect
