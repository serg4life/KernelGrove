"""Que la aplicación arranque donde hay pantalla.

`main` solo se salta la GUI cuando no hay a quién enseñarle un diálogo, y esa
pregunta es de X11/Wayland: contestarla por variables de entorno en Windows
daba «no hay pantalla» siempre, y con `console=False` la explicación se
escribía en una consola que no existe. Resultado: el icono no hacía nada.
"""

from __future__ import annotations

import importlib

# `kernelgrove.main` como módulo: el paquete reexporta la función con ese
# mismo nombre y `from kernelgrove import main` devuelve la función, no esto.
entrada = importlib.import_module("kernelgrove.main")


def test_en_windows_siempre_hay_pantalla(monkeypatch):
    monkeypatch.setattr(entrada.platform, "system", lambda: "Windows")
    for variable in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM"):
        monkeypatch.delenv(variable, raising=False)

    assert entrada._has_display() is True


def test_en_linux_sin_sesion_grafica_no_la_hay(monkeypatch):
    monkeypatch.setattr(entrada.platform, "system", lambda: "Linux")
    for variable in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM"):
        monkeypatch.delenv(variable, raising=False)

    assert entrada._has_display() is False


def test_sin_base_de_datos_windows_no_se_rinde_antes_de_la_gui(monkeypatch, tmp_path):
    """El caso exacto del fallo: recién instalado, sin base todavía."""
    monkeypatch.setattr(entrada.platform, "system", lambda: "Windows")
    for variable in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("KERNELGROVE_DB_PATH", str(tmp_path / "no-existe.db"))

    llamadas = []
    monkeypatch.setattr(
        "kernelgrove.gui.app.run_app", lambda **kwargs: llamadas.append(kwargs) or 0
    )

    assert entrada.main() == 0
    assert llamadas, "main salió sin llegar a la GUI"
