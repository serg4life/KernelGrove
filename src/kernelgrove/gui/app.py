"""Arranque de la aplicación gráfica.

Aísla la creación del `QApplication` y la aplicación del tema para que
`kernelgrove.main` solo tenga que invocar `run_app`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMessageBox,
    QProgressDialog,
)

from kernelgrove.gui import brand, theme
from kernelgrove.gui.main_window import (
    SETTING_LANGUAGE,
    SETTING_SKIN,
    SETTING_THEME,
    SETTINGS_APP,
    SETTINGS_ORG,
    MainWindow,
    apply_theme,
)
from kernelgrove.gui.translations import install_translations
from kernelgrove import db_download
from kernelgrove.main import USER_DB_PATH, remember_db_path


def run_app(
    db_path: Path, dtsi_folder: Path, argv: Optional[Sequence[str]] = None
) -> int:
    """Crea la aplicación Qt, muestra la ventana principal y entra en el bucle.

    Devuelve el código de salida de Qt para que el llamante lo propague.
    """
    app = QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName("KernelGrove")
    app.setApplicationDisplayName("Device Tree Studio")
    # Con qué entrada del menú de aplicaciones se corresponde esta ventana
    # (`packaging/linux/kernelgrove.desktop`). Es lo que mira el escritorio —
    # X11 y Wayland— para ponerle a la ventana su icono en la barra de tareas
    # en vez del genérico; sin esto, instalada desde el `.deb`, el lanzador
    # tiene icono y la ventana abierta no.
    app.setDesktopFileName("kernelgrove")
    app.setStyle("Fusion")

    # La tipografía va antes que el tema: el QSS la nombra por familia
    # («Inter»), y si no está registrada cuando se aplica la hoja, Qt
    # resuelve a la de respaldo y no vuelve a mirar.
    theme.load_fonts()

    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    # Claro, oscuro o el del sistema — que es como viene de fábrica y es el
    # equivalente del `prefers-color-scheme` de la web.
    apply_theme(
        app,
        settings.value(SETTING_THEME) or theme.MODE_DARK,
        settings.value(SETTING_SKIN) or theme.SKIN_CLASSIC,
    )

    # Antes de construir ningún widget: `tr()` resuelve al crearse cada
    # texto, así que un traductor instalado después dejaría en inglés todo lo
    # que ya estuviera montado. El idioma fuente es el inglés (ver
    # `gui/translations.py`).
    #
    # Es también el motivo de que elegir otro idioma en el menú pida
    # reiniciar: retraducir en caliente obligaría a que cada widget de la
    # aplicación volviera a fijar sus textos al recibir `LanguageChange`.
    install_translations(app, settings.value(SETTING_LANGUAGE))

    # Después del tema: el símbolo se rasteriza con la tinta activa (el
    # fuente lleva el negro de marca, invisible sobre el fondo oscuro).
    app.setWindowIcon(brand.app_icon())

    # La base no viaja con el programa: si no está, se trae. Y si no se
    # puede traer —hoy, por ejemplo, porque todavía no hay nada publicado—
    # se pide una local, que es como ha funcionado hasta ahora.
    db_path = ensure_database(db_path)
    if db_path is None:
        return 1

    window = MainWindow(db_path=db_path, dtsi_folder=dtsi_folder)
    window.show()

    # `closeEvent` solo se dispara al cerrar la ventana. Si la aplicación
    # termina por otra vía (menú Salir, señal del sistema), los hilos de fondo
    # seguirían vivos y Qt aborta el proceso al destruirlos en marcha.
    app.aboutToQuit.connect(window.stop_background_work)

    return app.exec()


# ----------------------------------------------------------------------
# Conseguir una base de datos
# ----------------------------------------------------------------------
def ensure_database(db_path: Path) -> Optional[Path]:
    """Devuelve una base utilizable, trayéndola o pidiéndola. `None` = salir.

    **Se descarga sola**, sin un botón que haya que encontrar: quien acaba
    de instalar el programa no tiene por qué saber que hace falta un fichero
    aparte ni de dónde sale. Solo se pregunta cuando no se ha podido, y
    entonces se pregunta lo útil: «dame una tú».
    """
    if db_path.is_file():
        return db_path

    descargada = download_database(USER_DB_PATH)
    if descargada is not None:
        remember_db_path(descargada)
        return descargada

    return choose_database()


def download_database(destination: Path) -> Optional[Path]:
    """Trae la base publicada, con su barra. `None` si no se ha podido.

    El error no se enseña aquí: quien llama decide si es «no he podido,
    dame una tú» (primer arranque) o un aviso suelto (actualizar a mano).
    """
    dialogo = QProgressDialog(
        QApplication.translate("app", "Downloading the bindings database…"),
        QApplication.translate("app", "Cancel"),
        0,
        0,
    )
    dialogo.setWindowTitle(QApplication.translate("app", "Database"))
    dialogo.setWindowModality(Qt.ApplicationModal)
    dialogo.setMinimumDuration(0)
    dialogo.setAutoClose(False)
    dialogo.setValue(0)

    def avanzar(leidos: int, total: int) -> bool:
        # Con `total` a 0 el servidor no dijo cuánto ocupa: barra
        # indeterminada en vez de un porcentaje inventado.
        dialogo.setMaximum(total)
        dialogo.setValue(leidos)
        QApplication.processEvents()
        return not dialogo.wasCanceled()

    try:
        manifest = db_download.fetch_manifest()
        return db_download.download(manifest, destination, progress=avanzar)
    except db_download.DatabaseDownloadError as error:
        _ultimo_error[0] = str(error)
        return None
    finally:
        dialogo.close()


def choose_database() -> Optional[Path]:
    """Pide una base local cuando no se ha podido traer. `None` = salir.

    Es la salida de siempre, y hoy es el camino normal: mientras no haya
    nada publicado, la descarga falla y esto es lo que queda.
    """
    while True:
        cuadro = QMessageBox()
        cuadro.setWindowTitle(QApplication.translate("app", "Database"))
        cuadro.setIcon(QMessageBox.Warning)
        cuadro.setText(
            QApplication.translate(
                "app", "KernelGrove could not download the bindings database."
            )
        )
        cuadro.setInformativeText(
            "{reason}\n\n{hint}".format(
                reason=_ultimo_error[0],
                hint=QApplication.translate(
                    "app",
                    "The database is distributed separately from the program. "
                    "You can point KernelGrove at one you already have.",
                ),
            )
        )
        elegir = cuadro.addButton(
            QApplication.translate("app", "Use a local database…"),
            QMessageBox.AcceptRole,
        )
        reintentar = cuadro.addButton(
            QApplication.translate("app", "Try again"), QMessageBox.ActionRole
        )
        cuadro.addButton(QApplication.translate("app", "Quit"), QMessageBox.RejectRole)
        cuadro.exec()

        pulsado = cuadro.clickedButton()
        if pulsado is reintentar:
            descargada = download_database(USER_DB_PATH)
            if descargada is not None:
                remember_db_path(descargada)
                return descargada
            continue
        if pulsado is not elegir:
            return None

        elegida = ask_for_database(None)
        if elegida is not None:
            return elegida


def ask_for_database(parent) -> Optional[Path]:
    """Diálogo de fichero para señalar una base local, y la recuerda."""
    nombre, _ = QFileDialog.getOpenFileName(
        parent,
        QApplication.translate("app", "Choose a bindings database"),
        str(Path.home()),
        QApplication.translate("app", "Bindings database (*.db);;All files (*)"),
    )
    if not nombre:
        return None
    ruta = Path(nombre)
    remember_db_path(ruta)
    return ruta


# El motivo del último intento fallido, para poder enseñarlo en el cuadro
# que viene después. En una lista y no en un `global`: es un dato de paso
# entre dos funciones del mismo módulo, no estado de la aplicación.
_ultimo_error = [""]
