"""Panel de propiedades del SoC: lo que queda empaquetado dentro del círculo central.

Se abre al hacer doble clic en el nodo raíz del grafo, igual que el doble
clic en el bloque PS de Vivado abre su asistente de configuración: aquí no
hay nodos que colgar, solo el estado de los controladores que el SoC integra
de fábrica (`SocPackage`, ver `api/service.build_soc_package`), editable y
aplicado solo al pulsar «Aplicar».

Cada controlador es un bloque, no una fila de tabla -mismo lenguaje visual
que el grafo (`gui/widgets/tree_graph._BlockChip`): verde si está encendido,
sin relleno si no, y solo su compatible como texto- porque aquí hay muchos
más de los que el grafo llega a dibujar (cualquier nodo con `status`, esté o
no conectado) y una tabla con columnas de ruta/estado por fila no se lee de
un vistazo con esa cantidad. Un doble clic alterna el estado del bloque en
el sitio; «Aplicar» junta lo que haya cambiado y lo emite de una vez.
"""

from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStyledItemDelegate,
    QVBoxLayout,
)

from kernelgrove.api import IntegratedController, PropertyOverride, SocPackage
from kernelgrove.gui import style
from kernelgrove.gui.translations import Retranslates

# Estado del bloque, leído por el delegate. No se usa `setBackground`: la
# hoja de estilos define `QListView::item`, y en cuanto una regla QSS toca
# el item Qt deja de hacer caso al brush que se le ponga -el mismo caso ya
# medido con `QTreeWidget::item` en el inspector-. Así que el bloque se
# pinta entero a mano.
_ROLE_ENABLED = Qt.UserRole + 1


class _BlockDelegate(QStyledItemDelegate):
    """Pinta cada controlador como el bloque que el grafo dibuja dentro del SoC.

    Mismo lenguaje que `tree_graph._BlockChip`, para que lo que se ve aquí y
    lo que se ve en el grafo digan lo mismo: relleno verde = encendido,
    **sin relleno** = apagado. El texto sigue al relleno (blanco sobre el
    verde, atenuado cuando no hay relleno), porque el color del texto es la
    segunda señal de que ese bloque no está activo.
    """

    def paint(self, painter: QPainter, option, index) -> None:
        """Dibuja el rectángulo redondeado y el compatible centrado dentro."""
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        enabled = bool(index.data(_ROLE_ENABLED))
        rect = option.rect.adjusted(1, 1, -1, -1)
        # El mismo redondeo que el bloque del grafo, no uno propio: es la
        # misma pieza dibujada en dos sitios.
        radius = style.GRAPH_NODE_CORNER_RADIUS

        if enabled:
            painter.setBrush(QBrush(QColor(style.GRAPH_BLOCK_ENABLED_BG)))
            painter.setPen(QPen(QColor(style.GRAPH_BLOCK_ENABLED_BG), 1))
            text_color = QColor(style.GRAPH_BLOCK_ENABLED_TEXT)
        else:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(style.GRAPH_NODE_DEFAULT_BORDER), 1))
            text_color = QColor(style.MUTED_TEXT_COLOR)
        painter.drawRoundedRect(rect, radius, radius)

        painter.setPen(QPen(text_color))
        text_rect = rect.adjusted(6, 0, -6, 0)
        metrics = QFontMetrics(option.font)
        painter.drawText(
            text_rect,
            Qt.AlignCenter,
            metrics.elidedText(
                str(index.data(Qt.DisplayRole)), Qt.ElideMiddle, text_rect.width()
            ),
        )
        painter.restore()


class SocPropertiesDialog(Retranslates, QDialog):
    """Ficha editable de identidad y controladores integrados del SoC.

    Se retraduce en caliente porque **la ventana sobrevive**: no es modal y
    la misma se reutiliza en cada apertura (`MainWindow._open_soc_properties`),
    así que si estuviera abierta al cambiar de idioma se quedaría en el
    anterior para siempre.
    """

    applyRequested = Signal(list)

    def __init__(self, package: SocPackage, parent=None):
        """Monta la ficha de identidad y la rejilla de bloques del paquete."""
        super().__init__(parent)
        self.resize(*style.SOC_PROPERTIES_DIALOG_SIZE)

        self._controllers: List[IntegratedController] = []
        # Estado pendiente por fila: arranca igual que `controller.enabled` y
        # solo cambia al doble clic. `_on_apply` lo compara contra el
        # original para saber qué de verdad ha cambiado.
        self._states: Dict[int, bool] = {}

        layout = QVBoxLayout(self)

        # Los rótulos se guardan porque `retranslate` tiene que volver a
        # ponerles el texto; construir con `""` y rellenar allí es el patrón
        # del resto de la interfaz (ver `translations.Retranslates`).
        self._identity_form = QFormLayout()
        self._name_caption = QLabel("")
        self._vendor_caption = QLabel("")
        self._name_label = QLabel("—")
        self._name_label.setWordWrap(True)
        self._vendor_label = QLabel("—")
        self._identity_form.addRow(self._name_caption, self._name_label)
        self._identity_form.addRow(self._vendor_caption, self._vendor_label)
        layout.addLayout(self._identity_form)

        self._list_caption = QLabel("")
        layout.addWidget(self._list_caption)

        self._list = QListWidget()
        self._list.setViewMode(QListWidget.IconMode)
        self._list.setResizeMode(QListWidget.Adjust)
        self._list.setMovement(QListWidget.Static)
        self._list.setSelectionMode(QListWidget.NoSelection)
        self._list.setSpacing(style.SOC_BLOCK_SPACING)
        self._list.setItemDelegate(_BlockDelegate(self._list))
        self._list.itemDoubleClicked.connect(self._on_block_double_clicked)
        layout.addWidget(self._list, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self._apply_button = buttons.addButton("", QDialogButtonBox.ApplyRole)
        self._apply_button.clicked.connect(self._on_apply)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

        self._status_line = QLabel("")
        layout.addWidget(self._status_line)

        self.retranslate()
        self.show_package(package)

    def retranslate(self) -> None:
        """Rehace los textos fijos de la ficha (ver `Retranslates`).

        La línea de estado no: dice el resultado de la última pulsación de
        «Aplicar», y volver a redactarla en otro idioma sería inventarse un
        mensaje que nadie ha provocado. Se limpia, que es lo que ya hace
        cualquier cambio en la ficha.
        """
        self.setWindowTitle(self.tr("SoC properties"))
        self._name_caption.setText(self.tr("Name:"))
        self._vendor_caption.setText(self.tr("Vendor:"))
        self._list_caption.setText(self.tr("Controllers integrated in the SoC:"))
        self._apply_button.setText(self.tr("Apply"))
        self._status_line.setText("")

    def show_package(self, package: SocPackage) -> None:
        """Rellena (o refresca) la ficha con un `SocPackage` recién construido."""
        self._controllers = list(package.controllers)
        self._name_label.setText(package.name or "—")
        self._vendor_label.setText(package.vendor or "—")
        self._status_line.setText("")

        self._list.clear()
        self._states = {}
        for row, controller in enumerate(self._controllers):
            item = QListWidgetItem(controller.compatible)
            item.setSizeHint(QSize(*style.SOC_BLOCK_SIZE))
            # La ruta identifica *cuál* de los varios `i2c@…` es este bloque:
            # el compatible se repite entre los controladores del mismo tipo.
            item.setToolTip(controller.path)
            item.setData(_ROLE_ENABLED, controller.enabled)
            self._list.addItem(item)
            self._states[row] = controller.enabled

    def _on_block_double_clicked(self, item: QListWidgetItem) -> None:
        """Alterna el estado pendiente del bloque, sin tocar el fuente todavía."""
        row = self._list.row(item)
        enabled = not self._states[row]
        self._states[row] = enabled
        item.setData(_ROLE_ENABLED, enabled)
        self._status_line.setText("")

    def _on_apply(self) -> None:
        """Reúne los estados que han cambiado y los emite como overrides."""
        changes: List[PropertyOverride] = []
        for row, controller in enumerate(self._controllers):
            enabled = self._states.get(row, controller.enabled)
            if enabled == controller.enabled:
                continue
            changes.append(
                PropertyOverride(
                    label=controller.label,
                    path=controller.path,
                    name="status",
                    value=f'"{"okay" if enabled else "disabled"}"',
                )
            )

        if not changes:
            self._status_line.setText(self.tr("Nothing to apply."))
            return

        self.applyRequested.emit(changes)
