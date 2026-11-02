"""Botón «×» para cerrar una pestaña de la barra de ficheros abiertos."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget

from kernelgrove.gui import style
from kernelgrove.gui.translations import Retranslates


class TabCloseButton(Retranslates, QAbstractButton):
    """Botón de cierre dibujado a mano, en vez del icono nativo del estilo.

    `QTabBar.setTabsClosable` usa el icono de cierre del `QStyle` activo, que
    en Fusion es un bitmap de baja resolución con aspecto anticuado. Dibujar
    el aspa a mano en cada `paintEvent` la deja nítida a cualquier escala de
    pantalla, y permite el resalte redondeado al pasar el ratón que el icono
    nativo no ofrece.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self.setCursor(Qt.PointingHandCursor)
        self.retranslate()
        # Estilo VS Code: un documento con cambios sin guardar muestra un
        # punto en vez del aspa -el aspa reaparece igualmente al pasar el
        # ratón por encima, que es cuando de verdad hace falta poder
        # cerrarlo-. Lo fija `MainWindow._sync_document_bar` con
        # `set_modified` a partir de `document().isModified()` de cada editor.
        self._modified = False

    def retranslate(self) -> None:
        """Rehace el tooltip al cambiar de idioma (ver `Retranslates`)."""
        self.setToolTip(self.tr("Close"))

    def set_modified(self, modified: bool) -> None:
        """Cambia entre el aspa de cerrar y el punto de "cambios sin guardar"."""
        if modified == self._modified:
            return
        self._modified = modified
        self.update()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()
        hovered = self.underMouse()
        if hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(style.TAB_CLOSE_HOVER_BG))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 4, 4)
            stroke = QColor(style.TAB_CLOSE_HOVER_STROKE)
        else:
            stroke = QColor(style.TAB_CLOSE_STROKE)

        if self._modified and not hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(style.COLOR_GENERATED_BRIGHT))
            center = rect.center()
            radius = 3.5
            painter.drawEllipse(center, radius, radius)
            return

        pen = QPen(stroke)
        pen.setWidthF(1.4)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)

        margin = 5
        painter.drawLine(
            rect.left() + margin, rect.top() + margin,
            rect.right() - margin, rect.bottom() - margin,
        )
        painter.drawLine(
            rect.left() + margin, rect.bottom() - margin,
            rect.right() - margin, rect.top() + margin,
        )
