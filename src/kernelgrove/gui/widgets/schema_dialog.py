"""Lo que un binding dice de un dispositivo, en una ficha legible.

Nace de lo que **no** hay que hacer: el botón «Open schema» que hubo aquí
volcaba el binding procesado como JSON en una pestaña del editor. Eso es la
base de datos hablando de sí misma —llaves, `allOf`, `$ref`— y no responde a
lo que se viene a preguntar, que es qué propiedades lleva este dispositivo,
cuáles son obligatorias y de qué tipo va cada una.

Así que la ficha enseña lo mismo que el Inspector enseña de un nodo, pero de
un compatible que no está escrito en ninguna parte todavía: la prosa del
binding, desde qué kernel existe, y la lista completa de lo que admite —con
la herencia ya resuelta, que es de donde sale la mayoría—, obligatorias
primero.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from kernelgrove.api import KernelGroveService, PropertySuggestion
from kernelgrove.gui import style
from kernelgrove.gui.translations import Retranslates

# Cuánto de la prosa de una propiedad entra en su fila. El resto va al
# aviso: la ficha es una lista, no un documento.
_MAX_DETAIL = 120


class SchemaDialog(Retranslates, QDialog):
    """Ficha de un compatible: qué es, desde cuándo, y qué admite."""

    def __init__(self, service: KernelGroveService, compatible: str, parent=None):
        """Consulta el binding y lo pinta; sin binding, lo dice y ya."""
        super().__init__(parent)
        self._service = service
        self._compatible = compatible

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self._title = QLabel(compatible)
        self._title.setObjectName("inspectorTitle")
        self._title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._title)

        fila = QHBoxLayout()
        fila.setSpacing(8)
        self._subtitle = QLabel()
        self._subtitle.setObjectName("inspectorDescription")
        self._since = QLabel()
        self._since.setObjectName("cardBadge")
        fila.addWidget(self._subtitle, 1)
        fila.addWidget(self._since)
        layout.addLayout(fila)

        self._description = QLabel()
        self._description.setWordWrap(True)
        self._description.setObjectName("inspectorDescription")
        self._description.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._description)

        self._properties = QTreeWidget()
        self._properties.setObjectName("inspectorProperties")
        self._properties.setRootIsDecorated(False)
        self._properties.setColumnCount(4)
        self._properties.setAlternatingRowColors(False)
        header = self._properties.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        layout.addWidget(self._properties, 1)

        self._empty = QLabel()
        self._empty.setWordWrap(True)
        self._empty.setStyleSheet(f"color: {style.EDITOR_WARNING_ACCENT};")
        self._empty.setVisible(False)
        layout.addWidget(self._empty)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self.resize(*style.SCHEMA_DIALOG_SIZE)
        self._fill()
        self.retranslate()

    def retranslate(self) -> None:
        """Rehace los textos fijos y vuelve a pintar la ficha."""
        self.setWindowTitle(
            self.tr("Binding · {compatible}").format(compatible=self._compatible)
        )
        self._properties.setHeaderLabels(
            [
                self.tr("Property"),
                self.tr("Binding"),
                self.tr("Type"),
                self.tr("What it is"),
            ]
        )
        self._fill()

    def _fill(self) -> None:
        """Rellena la ficha con lo que la base sepa de este compatible."""
        info = self._service.get_binding_info(self._compatible)
        vendor = self._compatible.split(",", 1)[0] if "," in self._compatible else ""
        partes = [texto for texto in (info.title, vendor, info.subsystem) if texto]
        self._subtitle.setText(" · ".join(partes))

        since = self._service.binding_since(self._compatible)
        self._since.setText(
            self.tr("{version}+").format(version=since) if since else ""
        )
        self._since.setVisible(bool(since))

        prosa = " ".join((info.description or "").split())
        self._description.setText(prosa)
        self._description.setVisible(bool(prosa))

        suggestions = self._service.suggest_properties(self._compatible)
        self._properties.clear()
        for suggestion in suggestions:
            self._properties.addTopLevelItem(self._row(suggestion))
        self._properties.setVisible(bool(suggestions))
        self._empty.setVisible(not suggestions)
        self._empty.setText(
            ""
            if suggestions
            else self.tr(
                "No binding in the database documents this compatible, so "
                "there is nothing to list. About a thousand kernel bindings "
                "are still in the old .txt format and never became a schema."
            )
        )

    def _row(self, suggestion: PropertySuggestion) -> QTreeWidgetItem:
        """La fila de una propiedad: nombre, si la exige, tipo y qué dice."""
        if suggestion.required:
            estado, color = self.tr("REQUIRED"), style.CARD_OK_COLOR
        else:
            estado, color = self.tr("OPTIONAL"), style.FAINT_TEXT_COLOR
        tipo = self._service.property_type_label(suggestion.name, suggestion.dt_type)
        if suggestion.is_node:
            tipo = self.tr("node")

        item = QTreeWidgetItem(
            [suggestion.name, estado, tipo or "—", _detail(suggestion)]
        )
        item.setForeground(1, QColor(color))
        item.setForeground(2, QColor(style.FAINT_TEXT_COLOR))
        aviso = " ".join((suggestion.description or "").split())
        if suggestion.allowed_values:
            aviso = "{values}\n\n{prose}".format(
                values=", ".join(suggestion.allowed_values), prose=aviso
            ).strip()
        item.setToolTip(0, aviso or suggestion.name)
        item.setToolTip(3, aviso)
        return item


def _detail(suggestion: PropertySuggestion) -> str:
    """Lo que se lee de un vistazo de una propiedad: sus valores o su prosa.

    Los valores primero cuando el binding los enumera: es lo accionable —lo
    que hay que teclear— mientras que la prosa suele repetir el nombre.
    """
    if suggestion.allowed_values:
        return ", ".join(suggestion.allowed_values[:6]) + (
            "…" if len(suggestion.allowed_values) > 6 else ""
        )
    prosa = " ".join((suggestion.description or "").split())
    if len(prosa) > _MAX_DETAIL:
        prosa = prosa[:_MAX_DETAIL].rsplit(" ", 1)[0] + "…"
    return prosa


def show_schema(
    service: KernelGroveService, compatible: str, parent=None
) -> SchemaDialog:
    """Abre la ficha de un compatible, sin bloquear lo que hubiera detrás."""
    dialog = SchemaDialog(service, compatible, parent)
    dialog.setWindowFlag(Qt.Tool, True)
    dialog.show()
    return dialog
