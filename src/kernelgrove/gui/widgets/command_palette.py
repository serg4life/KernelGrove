"""Paleta de comandos: un solo sitio donde escribir a dónde se quiere ir.

Es el control central del IDE de referencia y el gesto que cualquiera trae
aprendido de VS Code: `Ctrl+P`, se escribe, se pulsa Enter. Aquí busca a la
vez sobre **los ficheros abiertos**, **el catálogo de la base** y **las
acciones** de la ventana, que son las tres cosas por las que uno interrumpe
lo que está haciendo.

No conoce ninguna de las tres: `MainWindow` le pasa una lista de entradas ya
resuelta (`PaletteEntry`), cada una con lo que hay que ejecutar. Así la
paleta no depende del servicio ni del editor, y añadir una acción nueva es
añadir una fila a esa lista, no tocar este fichero.

El filtro es por subcadena sobre título y categoría, no difuso: con un
catálogo de miles de entradas un emparejado difuso devuelve cualquier cosa
para dos letras, y lo que se busca aquí se sabe cómo se llama.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPen
from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyledItemDelegate,
    QVBoxLayout,
)

from kernelgrove.gui import style
from kernelgrove.gui.translations import Retranslates
from kernelgrove.gui.widgets import icons

# Cuántas entradas se enseñan a la vez. El catálogo de la base son miles y
# una lista de miles de filas no se recorre: lo que hace falta es escribir
# dos letras más, no desplazarse.
MAX_RESULTS = 40


@dataclass(frozen=True)
class PaletteEntry:
    """Una fila de la paleta: lo que se lee, dónde encaja y qué hace."""

    title: str
    category: str
    run: Callable[[], None]

    @property
    def haystack(self) -> str:
        """Texto sobre el que busca el filtro, ya en minúsculas."""
        return f"{self.title} {self.category}".lower()


class _EntryDelegate(QStyledItemDelegate):
    """Título a la izquierda y su categoría a la derecha, apagada.

    La categoría es lo que distingue un fichero abierto de un SoC del
    catálogo que se llama igual, así que tiene que verse en la fila y no
    solo en el tooltip; y va a la derecha para no competir con el nombre,
    que es lo que se está leyendo.
    """

    def paint(self, painter, option, index) -> None:
        """Pinta la fila entera: el fondo lo deja al estilo, el texto no."""
        entry: Optional[PaletteEntry] = index.data(Qt.UserRole)
        opcion = option.__class__(option)
        self.initStyleOption(opcion, index)
        opcion.text = ""
        opcion.widget.style().drawControl(
            opcion.widget.style().ControlElement.CE_ItemViewItem,
            opcion,
            painter,
            opcion.widget,
        )
        if entry is None:
            return

        rect = option.rect.adjusted(8, 0, -8, 0)
        categoria_font = QFont(option.font)
        categoria_font.setPointSizeF(max(categoria_font.pointSizeF() - 1, 6.0))
        cm = QFontMetrics(categoria_font)
        ancho = cm.horizontalAdvance(entry.category) + 10

        painter.setFont(option.font)
        painter.setPen(QPen(QColor(style.MUTED_TEXT_COLOR)))
        titulo = QFontMetrics(option.font).elidedText(
            entry.title, Qt.ElideMiddle, rect.width() - ancho
        )
        painter.drawText(
            rect.adjusted(0, 0, -ancho, 0), Qt.AlignVCenter | Qt.AlignLeft, titulo
        )

        painter.setFont(categoria_font)
        painter.setPen(QPen(QColor(style.FAINT_TEXT_COLOR)))
        painter.drawText(rect, Qt.AlignVCenter | Qt.AlignRight, entry.category)


class CommandPalette(Retranslates, QDialog):
    """Diálogo sin marco con un campo de texto y la lista de resultados."""

    def __init__(self, entries: List[PaletteEntry], parent=None):
        """Monta el campo y la lista, y enseña ya las primeras entradas."""
        super().__init__(parent)
        self.setObjectName("commandPalette")
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        # Las dos hacen falta para la esquina redondeada, y por motivos
        # distintos: sin `WA_StyledBackground` Qt no le pinta a una subclase
        # propia el fondo ni el borde que dice la hoja de estilos -y el
        # `border-radius` se queda sin dibujar-, y sin
        # `WA_TranslucentBackground` ese fondo redondeado se pinta encima de
        # un rectángulo opaco, así que la esquina no llega a recortarse.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        self._entries = entries
        # Desde dónde se cogió la ventana para arrastrarla; None mientras no
        # se esté arrastrando. Ver `mousePressEvent`.
        self._drag_origin = None

        layout = QVBoxLayout(self)
        margin = style.COMMAND_PALETTE_MARGIN
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(0)

        self.query = QLineEdit()
        self.query.setObjectName("commandPaletteQuery")
        self.query.addAction(
            icons.search_icon(style.ACTION_ICON_SIZE, style.ACCENT_TEXT_COLOR),
            QLineEdit.LeadingPosition,
        )
        self.query.textChanged.connect(self._refill)
        # Las flechas y Enter tienen que llegar a la lista sin sacar el foco
        # del campo: se escribe y se elige en el mismo gesto, que es el
        # único motivo por el que una paleta es más rápida que un menú.
        self.query.installEventFilter(self)
        layout.addWidget(self.query)

        self.results = QListWidget()
        self.results.setObjectName("commandPaletteResults")
        self.results.setItemDelegate(_EntryDelegate(self.results))
        self.results.itemActivated.connect(self._run)
        self.results.itemClicked.connect(self._run)
        layout.addWidget(self.results, 1)

        self.resize(*style.COMMAND_PALETTE_SIZE)
        self.retranslate()
        self._refill("")

    def mousePressEvent(self, event) -> None:
        """Empieza a arrastrar la ventana desde su banda exterior.

        Va sin marco, así que no tiene barra de título de la que tirar y hay
        que moverla a mano; lo que queda para agarrarla es el margen que
        `COMMAND_PALETTE_MARGIN` deja alrededor del campo y de la lista, que
        son los que reciben el clic en el resto de la superficie -escribir y
        seleccionar texto siguen siendo suyos-.
        """
        if event.button() == Qt.LeftButton:
            self._drag_origin = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """Lleva la ventana con el ratón mientras se mantenga pulsado."""
        if self._drag_origin is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        """Suelta la ventana."""
        self._drag_origin = None
        super().mouseReleaseEvent(event)

    def retranslate(self) -> None:
        """Rehace el texto de ayuda del campo (ver `Retranslates`)."""
        self.query.setPlaceholderText(
            self.tr("Search files, views, SoCs and boards…")
        )

    def _refill(self, text: str) -> None:
        """Vuelve a llenar la lista con lo que casa con `text`."""
        needle = text.strip().lower()
        self.results.clear()
        for entry in self._entries:
            if needle and needle not in entry.haystack:
                continue
            item = QListWidgetItem(entry.title)
            item.setData(Qt.UserRole, entry)
            # La categoría a la derecha, en el tooltip además: en una fila
            # estrecha el título es lo que se lee y lo que se busca.
            item.setToolTip(f"{entry.category} · {entry.title}")
            self.results.addItem(item)
            if self.results.count() >= MAX_RESULTS:
                break
        if self.results.count():
            self.results.setCurrentRow(0)

    def eventFilter(self, obj, event) -> bool:
        """Manda flechas y Enter a la lista aunque el foco esté en el campo."""
        from PySide6.QtCore import QEvent

        if obj is self.query and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Up, Qt.Key_Down):
                self.results.keyPressEvent(event)
                return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                item = self.results.currentItem()
                if item is not None:
                    self._run(item)
                return True
        return super().eventFilter(obj, event)

    def _run(self, item: QListWidgetItem) -> None:
        """Cierra la paleta y ejecuta lo elegido, en ese orden.

        Primero cerrar: la acción puede abrir otro diálogo o cambiar de
        vista, y hacerlo con la paleta todavía encima deja la ventana
        modal por delante de lo que acaba de pedirse.
        """
        entry: Optional[PaletteEntry] = item.data(Qt.UserRole)
        self.accept()
        if entry is not None:
            entry.run()
