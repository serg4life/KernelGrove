"""Delegado de edición para la columna «Conectar dispositivo».

Ofrece, para cada controlador, la lista de dispositivos que pueden colgarse de
su bus. Como esas listas llegan a tener cientos de entradas, el desplegable es
editable y filtra según se escribe.
"""

from __future__ import annotations

from typing import Callable, List

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QCompleter,
    QStyledItemDelegate,
)

from kernelgrove.api import BindingOption
from kernelgrove.gui import style
from kernelgrove.gui.models.tree_model import COLUMN_CONNECT

def no_options_text() -> str:
    """Lo que enseña el desplegable de un bus sin dispositivos conocidos.

    Función y no constante de módulo: al importarse todavía no hay
    `QApplication`, así que una constante se quedaría con el idioma del
    arranque (ver CLAUDE.md).
    """
    return QCoreApplication.translate(
        "BindingDelegate", "(no known devices for this bus)"
    )

# El compatible real se guarda aparte del texto visible, que además lleva el
# título del binding y no serviría como valor.
COMPATIBLE_ROLE = Qt.UserRole + 1

# Margen para barra de desplazamiento y bordes al medir el ancho del desplegable.
POPUP_PADDING = 60


class BindingDelegate(QStyledItemDelegate):
    """Desplegable con autocompletado para elegir el dispositivo a conectar.

    Las opciones se piden mediante `options_provider`, que recibe el slot y
    devuelve los `BindingOption` admisibles; así el delegado no necesita
    conocer la base de datos.
    """

    def __init__(
        self,
        options_provider: Callable[[object], List[BindingOption]],
        parent=None,
    ):
        """Guarda el proveedor de opciones que se consultará al abrir el editor."""
        super().__init__(parent)
        self._options_provider = options_provider

    def createEditor(self, parent, option, index):
        """Construye el combo editable con completado por subcadena."""
        if index.column() != COLUMN_CONNECT:
            return super().createEditor(parent, option, index)

        options = self._options_provider(index.internalPointer())

        combo = QComboBox(parent)
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        # La altura del combo la da la propia fila del árbol (ver
        # `QTreeView::item` en `theme.py`, con relleno vertical pensado para
        # esta columna) — forzarla aquí por encima de la celda hacía que el
        # editor se viera desbordado y desentonara con el resto de filas.
        # Solo se estiliza el desplegable de opciones que abre, que es un
        # popup aparte y sí puede tener sus propias filas más cómodas.
        popup_item_style = (
            f"QListView::item {{ min-height: "
            f"{style.GENERATOR_CONNECT_POPUP_ITEM_HEIGHT}px; padding: 2px 6px; }}"
        )
        combo.view().setStyleSheet(popup_item_style)

        if options:
            for item in options:
                combo.addItem(item.label)
                combo.setItemData(combo.count() - 1, item.compatible, COMPATIBLE_ROLE)
                if item.is_controller:
                    combo.setItemData(
                        combo.count() - 1,
                        "Este dispositivo ofrece un bus: podrás colgarle más nodos.",
                        Qt.ToolTipRole,
                    )
            combo.setCurrentIndex(-1)
        else:
            combo.addItem(no_options_text())

        combo.lineEdit().setPlaceholderText(self.tr("Type to filter…"))
        self._widen_popup(combo, [item.label for item in options])

        completer = QCompleter([item.label for item in options], combo)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        # El popup del completado (el que de verdad se usa al escribir para
        # filtrar, que es el flujo habitual de este combo) es una ventana
        # propia del `QCompleter`, no la misma que `combo.view()` -que solo
        # se ve al pulsar la flechita-. Sin esto se quedaba con el tamaño de
        # fila por defecto de Qt, apretado al alto del propio texto.
        completer.popup().setStyleSheet(popup_item_style)
        combo.setCompleter(completer)

        return combo

    @staticmethod
    def _widen_popup(combo: QComboBox, labels: List[str]) -> None:
        """Ensancha la lista desplegable para que quepan los nombres completos.

        Por defecto el desplegable adopta el ancho de la columna, que es
        demasiado estrecha para un compatible con su título y recorta el texto.
        Se mide el contenido y se limita al ancho de la pantalla disponible.
        """
        if not labels:
            return

        metrics = QFontMetrics(combo.view().font())
        content_width = max(metrics.horizontalAdvance(label) for label in labels)

        screen = combo.screen() or QApplication.primaryScreen()
        max_width = int(screen.availableGeometry().width() * 0.6) if screen else 900

        combo.view().setMinimumWidth(min(content_width + POPUP_PADDING, max_width))
        combo.view().setTextElideMode(Qt.ElideMiddle)

    def setEditorData(self, editor, index) -> None:
        """Deja el combo vacío: cada edición conecta un dispositivo nuevo."""
        if not isinstance(editor, QComboBox):
            super().setEditorData(editor, index)
            return
        editor.setCurrentText("")

    def setModelData(self, editor, model, index) -> None:
        """Vuelca al modelo el compatible elegido, ignorando el texto vacío.

        El texto visible incluye el título del binding, así que el compatible
        se recupera de `COMPATIBLE_ROLE`; si el usuario escribió a mano, se
        busca la entrada cuyo texto coincide.
        """
        if not isinstance(editor, QComboBox):
            super().setModelData(editor, model, index)
            return

        text = editor.currentText().strip()
        if not text or text == no_options_text():
            return

        position = editor.findText(text)
        compatible = (
            editor.itemData(position, COMPATIBLE_ROLE) if position >= 0 else None
        )
        model.setData(index, compatible or text, Qt.EditRole)
