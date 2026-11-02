"""Pie de un panel lateral: el salto a la otra vista del mismo documento.

Un único botón, y a propósito. Antes el pie del explorador llevaba además
dos datos —a qué apunta el documento y qué `dtc` hay instalado— apilados
como rótulo/valor: con `MainWindow._allow_narrow` dejando en cero el mínimo
de todo lo que lleva texto en ese dock, al estrechar el panel esas filas se
descolocaban y el pie se leía torcido. Lo que sí se usa desde ahí es el
salto, así que el pie es el botón.

Lo comparten el explorador de carpetas y el árbol de nodos, y en los dos
dice **lo mismo**: el salto a la vista que no se está mirando. El destino
lo pone `MainWindow._refresh_panel_footers` a partir de la vista central —
no del panel—, porque ofrecer «ver en el grafo» desde el grafo era ofrecer
llegar a donde ya estabas.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from kernelgrove.gui import style


class PanelFooter(QWidget):
    """Botón a ancho completo al pie de un panel lateral."""

    clicked = Signal()

    def __init__(self, draw=None, parent=None):
        """`draw` es la función de `widgets/icons.py` que pinta su icono."""
        super().__init__(parent)
        self.setObjectName("explorerSummary")
        # Una subclase de QWidget no pinta el fondo ni el borde que le
        # da la hoja de estilos si no se le pide: sin esto la franja
        # salía del color de su padre y se fundía con el panel de al
        # lado, que es justo lo que la línea de zona tiene que separar.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._draw = draw
        self._text = ""

        self.button = QPushButton()
        self.button.setObjectName("explorerGraphButton")
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setIconSize(
            QSize(style.ACTION_ICON_SIZE, style.ACTION_ICON_SIZE)
        )
        self.button.clicked.connect(self.clicked)

        box = QVBoxLayout(self)
        box.setContentsMargins(12, 9, 12, 10)
        box.setSpacing(0)
        box.addWidget(self.button)
        self.refresh_icons()

    def refresh_icons(self) -> None:
        """Redibuja el icono en el color activo (ver `MainWindow._repaint_theme`)."""
        if self._draw is not None:
            self.button.setIcon(
                self._draw(style.ACTION_ICON_SIZE, style.ACCENT_TEXT_COLOR)
            )

    def set_target(self, draw, text: str, tooltip: str = "") -> None:
        """Icono, rótulo y ayuda del salto que ofrece este pie."""
        self._draw = draw
        self._text = text
        self.button.setToolTip(tooltip)
        self.refresh_icons()
        self._fit_text()

    def resizeEvent(self, event):
        """Al estrechar el panel el rótulo se cae y queda el icono solo."""
        super().resizeEvent(event)
        self._fit_text()

    def _fit_text(self) -> None:
        """Quita el rótulo cuando no cabe, en vez de dejarlo con puntos.

        `MainWindow._allow_narrow` deja en cero el mínimo de todo lo que
        lleva texto en este dock, así que al estrechar el panel Qt recorta
        el rótulo con puntos suspensivos y acaba enseñando «Visu…» al lado
        del icono: peor que el icono solo, que ya dice lo mismo y tiene su
        tooltip. Se mide contra el ancho del **pie**, no del botón, porque
        el del botón depende de lo que se acaba de decidir aquí.
        """
        margenes = self.layout().contentsMargins()
        disponible = self.width() - margenes.left() - margenes.right()
        # Icono, su separación y el relleno del propio botón (`BUTTON_PADDING`
        # son 12 px a cada lado, y Qt añade lo suyo entre icono y texto).
        necesario = (
            self.button.fontMetrics().horizontalAdvance(self._text)
            + style.ACTION_ICON_SIZE
            + 34
        )
        deseado = self._text if necesario <= disponible else ""
        if self.button.text() != deseado:
            self.button.setText(deseado)
