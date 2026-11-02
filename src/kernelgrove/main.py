from __future__ import annotations

import ctypes.util
import os
import platform
import sys
from pathlib import Path
from typing import Optional

from kernelgrove import legacy


def _missing_xcb_runtime_deps() -> Optional[str]:
    """Detecta si falta una librería nativa que el plugin Qt `xcb` necesita.

    Sin ella, Qt aborta el proceso con SIGABRT (`IOT instruction (core
    dumped)`) al construir `QApplication`, algo que no se puede capturar como
    excepción de Python porque ocurre en código nativo. Por eso se comprueba
    antes de intentar arrancar la GUI. Solo aplica quien vaya a usar el
    plugin `xcb` (X11 en Linux); si ya se ha pedido otro backend por
    `QT_QPA_PLATFORM`, o no hay sesión X11, no hace falta comprobar nada.
    """
    if platform.system() != "Linux":
        return None

    requested_platform = os.environ.get("QT_QPA_PLATFORM")
    if requested_platform and requested_platform != "xcb":
        return None
    if not requested_platform and os.environ.get("WAYLAND_DISPLAY"):
        return None
    if not os.environ.get("DISPLAY"):
        return None

    if ctypes.util.find_library("xcb-cursor") is not None:
        return None

    return (
        "Falta la librería de sistema libxcb-cursor0, necesaria desde Qt 6.5 "
        "para el plugin gráfico xcb.\nInstálala con:\n"
        "  sudo apt install libxcb-cursor0"
    )


# Dónde busca la base de datos un usuario que no puede escribir junto al
# ejecutable (la instalación del `.deb` en `/opt/kernelgrove`).
USER_DB_PATH = Path.home() / ".kernelgrove" / "bindings.db"

# Dónde se recuerda la base que el usuario ha elegido a mano («usar una base
# local»). En los mismos ajustes que el resto —misma organización y misma
# aplicación que `gui/main_window`— para no inventar un segundo sitio donde
# la aplicación guarda cosas.
SETTINGS_ORG = "KernelGrove"
SETTINGS_APP = "KernelGrove"
SETTING_DB_PATH = "db/path"


def chosen_db_path() -> Optional[Path]:
    """Base elegida a mano en una sesión anterior, si sigue existiendo.

    Se lee con Qt porque es donde vive el resto de los ajustes, y con un
    `try` porque este módulo tiene que poder ejecutarse sin PySide6 (es lo
    que hace que «no tienes PySide6» sea un mensaje y no una traza).
    """
    try:
        from PySide6.QtCore import QSettings
    except ImportError:
        return None
    guardada = QSettings(SETTINGS_ORG, SETTINGS_APP).value(SETTING_DB_PATH)
    if not guardada:
        return None
    ruta = Path(str(guardada)).expanduser()
    return ruta if ruta.is_file() else None


def remember_db_path(path: Path) -> None:
    """Recuerda la base elegida a mano, para no volver a preguntar."""
    from PySide6.QtCore import QSettings

    ajustes = QSettings(SETTINGS_ORG, SETTINGS_APP)
    ajustes.setValue(SETTING_DB_PATH, str(path))
    ajustes.sync()


def _app_root() -> Path:
    """Directorio base de la app: junto al ejecutable si está empaquetada.

    En un checkout normal, `Path(__file__).parents[2]` es la raíz del repo.
    Empaquetado con PyInstaller no hay repo: `__file__` apunta al directorio
    temporal donde se descomprime el bundle, así que en modo `frozen` la base
    pasa a ser el directorio del propio ejecutable — ver
    `packaging/linux/kernelgrove.spec`.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _default_db_path() -> Path:
    """Ubicación por defecto de `bindings.db`, salvo que se indique otra.

    La base de datos no es parte del software (es un artefacto aparte que el
    usuario aporta — la propia KernelGrove, la de un tercero, o una construida con
    `db_manager`), así que la ruta es configurable con `KERNELGROVE_DB_PATH` en vez
    de estar fija al repo. Sin esa variable, se busca junto al ejecutable
    (o al repo, en desarrollo) por comodidad, no porque tenga que estar ahí.

    Y, si ahí no está, en `~/.kernelgrove/bindings.db`: instalada desde el `.deb`
    la aplicación vive en `/opt/kernelgrove`, que es de root, así que dejarla al
    lado del ejecutable exigiría `sudo` para algo que es un fichero del
    usuario.
    """
    override = os.environ.get("KERNELGROVE_DB_PATH")
    if override:
        return Path(override).expanduser()
    # Lo que el usuario haya elegido a mano manda sobre lo que se encuentre
    # por ahí: si dijo «usa esta», es esta.
    elegida = chosen_db_path()
    if elegida is not None:
        return elegida
    junto_al_binario = _app_root() / "database" / "bindings.db"
    if junto_al_binario.is_file():
        return junto_al_binario
    del_usuario = USER_DB_PATH
    return del_usuario if del_usuario.is_file() else junto_al_binario


def _has_display() -> bool:
    """Si hay sesión gráfica: sin ella no hay a quién enseñarle un diálogo.

    La pregunta solo tiene sentido en Linux. `DISPLAY` y `WAYLAND_DISPLAY`
    son de X11 y de Wayland: en Windows y en macOS no existen, y tomar su
    ausencia por «no hay pantalla» es contestar que no siempre. Que es lo que
    pasaba: recién instalado en Windows no hay base de datos todavía, así que
    `main` daba por hecho que no había a quién preguntar, lo escribía por una
    consola que `console=False` no crea, y salía. Pulsar el icono no hacía
    nada, sin un mensaje en ninguna parte.
    """
    if platform.system() != "Linux":
        return True
    return bool(
        os.environ.get("DISPLAY")
        or os.environ.get("WAYLAND_DISPLAY")
        or os.environ.get("QT_QPA_PLATFORM")
    )


def _report_missing_database(db_path: Path) -> None:
    """Dice que falta la base, y lo dice donde se pueda leer.

    Lanzada desde el menú de aplicaciones no hay terminal donde mirar: sin
    esto, pulsar el icono no hacía nada visible. Se intenta un cuadro de
    diálogo y solo si no hay Qt se cae a la consola de siempre — es el mismo
    mensaje, en el único sitio donde el usuario lo va a ver.
    """
    grafico = _has_display()
    texto = (
        f"No se encuentra la base de datos en {db_path}.\n\n"
        "Se distribuye aparte del programa: descárgala y déjala en "
        f"{USER_DB_PATH}, indícala con la variable KERNELGROVE_DB_PATH, o "
        "genérala con `python -m kernelgrove.db_manager.main` (ver CLAUDE.md)."
    )
    if not grafico:
        # Sin sesión gráfica (una terminal, CI) el cuadro de diálogo no lo
        # vería nadie y además se quedaría esperando un clic que no llega.
        print(texto)
        return
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, "KernelGrove", texto)
        del app
    except ImportError:
        print(texto)


def main() -> int:
    """Punto de entrada de la app (`python -m kernelgrove`): lanza la GUI PySide6.

    Si PySide6 no está instalado, o falta una dependencia nativa de Qt,
    muestra instrucciones de instalación en lugar de fallar con una traza de
    importación o un core dump.
    """
    # Lo primero: la beta anterior se llamaba DTstudio y dejó ahí su estado
    # y los ajustes (ver `legacy`).
    legacy.migrate_state()

    db_path = _default_db_path()
    dtsi_folder = _app_root()

    missing_deps_message = _missing_xcb_runtime_deps()
    if missing_deps_message:
        print(missing_deps_message)
        return 1

    # Que falte no es motivo para no arrancar: la aplicación se ofrece a
    # traerla, y si no puede pide una local (`gui/app.ensure_database`). Eso
    # necesita ventanas, así que se hace ya dentro de la GUI; aquí solo se
    # atiende el caso sin pantalla, donde no hay a quién preguntar.
    if not db_path.is_file() and not _has_display():
        _report_missing_database(db_path)
        return 1

    try:
        from kernelgrove.gui.app import run_app
    except ImportError as exc:
        if "PySide6" in str(exc):
            print("PySide6 no está disponible en este entorno.")
            print("Instálalo con:\n  pip install PySide6")
        else:
            print("Error al importar la interfaz gráfica:", exc)
            print("Revisa dependencias internas como kernelgrove.gui.")
        return 1

    return run_app(db_path=db_path, dtsi_folder=dtsi_folder)


if __name__ == "__main__":
    raise SystemExit(main())
