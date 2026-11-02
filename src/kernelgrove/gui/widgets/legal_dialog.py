"""Las licencias: la del propio proyecto y las de lo que trae consigo.

Se abre desde «Ayuda → Licencias». El texto vive en `gui/LICENSES.md` y no
en el catálogo `.ts`: es un documento legal, y traducirlo a trozos dejaría
párrafos sueltos en otro idioma. Se enseña el original en inglés.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

from kernelgrove.gui.style import LEGAL_DIALOG_SIZE

_LICENSES_PATH = Path(__file__).resolve().parents[1] / "LICENSES.md"


def licenses_text() -> str:
    """El texto de las licencias, o el aviso de que el empaquetado lo perdió.

    Falta solo si el empaquetado se dejó el dato fuera (`package-data` en
    `pyproject.toml`, `datas` en el `.spec`), y entonces se dice en vez de
    enseñar un cuadro vacío.
    """
    try:
        return _LICENSES_PATH.read_text(encoding="utf-8")
    except OSError:
        return (
            "# Licenses\n\nThis text could not be read from this installation. "
            "KernelGrove is licensed under the Apache License 2.0: "
            "<https://www.apache.org/licenses/LICENSE-2.0>"
        )


def _document_style() -> str:
    """Tipografía con serifa y un punto más pequeña que la de la interfaz.

    Va como hoja **del propio widget**: la de la aplicación fija
    `font-family` para todo `QWidget` y se llevaría por delante una fuente
    puesta con `QTextDocument.setDefaultFont`.
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    base = app.font().pointSizeF() if app is not None else 9.0
    tamano = max(round(base * 0.9, 1), 7.0)
    return (
        'QTextBrowser#legalText {{ font-family: Georgia, "Times New Roman", '
        '"Liberation Serif", serif; font-size: {size}pt; }}'
    ).format(size=tamano)


class LegalDialog(QDialog):
    """Un documento legal, de solo lectura, con los enlaces abiertos fuera."""

    def __init__(self, parent=None, text: str = "", title: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(*LEGAL_DIALOG_SIZE)

        layout = QVBoxLayout(self)
        self._view = QTextBrowser()
        self._view.setObjectName("legalText")
        self._view.setOpenExternalLinks(True)
        self._view.setStyleSheet(_document_style())
        self._view.setMarkdown(text)
        layout.addWidget(self._view)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
