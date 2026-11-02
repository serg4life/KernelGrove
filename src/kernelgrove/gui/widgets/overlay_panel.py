"""Panel de overlays: el botón por el que empieza todo y el preview del texto.

Es la sección «OVERLAYS» de la `ActivityBar`, y tiene tres estados que se
turnan en el mismo hueco:

1. **en reposo** — los overlays que hay en la carpeta con su comprobación
   (`OverlayList`), cada uno con un interruptor que dice si entra en lo que
   se va a construir, plegables como bloque, y debajo el botón «Create new
   overlay». Escribir un overlay y revisar los que ya hay es la misma
   tarea; **compilarlos no**, y por eso vive en su propia sección
   (`widgets/build_panel.BuildPanel`), que es la que sabe qué árbol se
   construye;
2. **eligiendo** — el aviso de que hay que señalar el nodo objetivo en el
   editor, con su salida;
3. **editando** — el fuente del overlay tal como va quedando, y los botones
   de crearlo o descartarlo.

El panel **no tiene el modelo**: no sabe qué es un fragmento ni qué
propiedades hay marcadas. Solo enseña el texto que le pasan y avisa de en
qué línea se ha hecho clic; quien traduce eso a un nodo es `OverlayTab`, que
es quien lleva el borrador. Así el preview no es una segunda representación
del overlay que haya que mantener sincronizada, sino la única —el texto— ya
generada.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from kernelgrove.api import DeviceTreeNode, KernelGroveService
from kernelgrove.gui import style
from kernelgrove.gui.translations import Retranslates
from kernelgrove.gui.widgets.dts_editor import DtsEditor
from kernelgrove.gui.widgets.overlay_list import OverlayList

# Lo que se espera tras la última tecla antes de releer el texto editado a
# mano. Releerlo por pulsación significaría reconstruir las dos listas —y
# consultar el binding— con cada letra.
REPARSE_DELAY_MS = 400

# Flechas del plegado, las mismas que usan las cabeceras de los docks.
ARROW_OPEN = "⌄"
ARROW_CLOSED = "›"

PAGE_IDLE = 0
PAGE_PICKING = 1
PAGE_PREVIEW = 2


class OverlayPanel(Retranslates, QWidget):
    """Arranque, aviso de selección y preview del overlay en construcción."""

    createRequested = Signal()
    cancelRequested = Signal()
    generateRequested = Signal()
    # Línea (1-based) pulsada en el preview: `OverlayTab` la traduce al nodo
    # del borrador al que apuntan las listas de propiedades.
    lineSelected = Signal(int)
    # El texto del preview lo ha cambiado **una persona**, no el borrador: a
    # partir de ahí manda lo escrito, y `OverlayTab` vuelve a leer de ahí su
    # modelo. Es la salida para corregir a mano un valor de relleno.
    previewEdited = Signal(str)

    def __init__(self, service: KernelGroveService, parent=None):
        """Monta las tres páginas, en reposo."""
        super().__init__(parent)
        self._service = service
        # Levantada mientras el texto lo escribe el borrador: sin esto, cada
        # regeneración se leería como una edición a mano y volvería en bucle.
        self._writing = False

        self._reparse = QTimer(self)
        self._reparse.setSingleShot(True)
        self._reparse.setInterval(REPARSE_DELAY_MS)
        self._reparse.timeout.connect(
            lambda: self.previewEdited.emit(self.preview.toPlainText())
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_idle())
        self._pages.addWidget(self._build_picking())
        self._pages.addWidget(self._build_preview())
        layout.addWidget(self._pages, 1)

        self.retranslate()

    # ------------------------------------------------------------------
    # Construcción
    # ------------------------------------------------------------------
    def _build_idle(self) -> QWidget:
        """En reposo: los overlays de la carpeta y el botón de crear otro."""
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        # Los overlays van **arriba del todo**: son el contenido de esta
        # sección, y el botón de crear uno es lo que se hace con ellos, no
        # al revés.
        self.overlay_list = OverlayList(self._service)
        self._overlays_header = self._collapsible_header(self.overlay_list)

        actions = QWidget()
        action_column = QVBoxLayout(actions)
        action_column.setContentsMargins(12, 8, 12, 8)
        action_column.setSpacing(6)
        self.create_button = QPushButton()
        self.create_button.setObjectName("primaryButton")
        self.create_button.clicked.connect(self.createRequested)
        self._idle_hint = QLabel()
        self._idle_hint.setWordWrap(True)
        self._idle_hint.setStyleSheet(f"color: {style.MUTED_TEXT_COLOR};")
        action_column.addWidget(self.create_button)
        action_column.addWidget(self._idle_hint)

        column.addWidget(self._overlays_header)
        column.addWidget(self.overlay_list, 1)
        column.addWidget(actions)
        return page

    def _collapsible_header(self, target: QWidget) -> QWidget:
        """Cabecera con flecha que pliega `target`.

        Plegar y no cerrar: en una carpeta con veinte overlays la lista se
        come el panel entero y deja sin sitio a los árboles de abajo, que es
        donde se elige qué se construye.
        """
        header = QWidget()
        header.setObjectName("viewToolbar")
        row = QVBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)
        button = QToolButton()
        button.setObjectName("panelSectionHeader")
        button.setCheckable(True)
        button.setChecked(True)
        button.setCursor(Qt.PointingHandCursor)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.toggled.connect(target.setVisible)
        button.toggled.connect(self._refresh_overlays_header)
        row.addWidget(button)
        self._overlays_toggle = button
        return header

    def _refresh_overlays_header(self, *_args) -> None:
        """Escribe la cabecera de la lista con la flecha del estado."""
        abierto = self._overlays_toggle.isChecked()
        self._overlays_toggle.setText(
            "{arrow}  {title}".format(
                arrow=ARROW_OPEN if abierto else ARROW_CLOSED,
                title=self.tr("OVERLAYS IN THIS FOLDER"),
            )
        )

    def _build_picking(self) -> QWidget:
        """Eligiendo: qué se espera del usuario y cómo salirse."""
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(12, 12, 12, 12)
        column.setSpacing(8)

        self._picking_caption = QLabel()
        self._picking_caption.setObjectName("panelCaption")
        self._picking_hint = QLabel()
        self._picking_hint.setWordWrap(True)
        self._picking_hint.setStyleSheet(f"color: {style.MUTED_TEXT_COLOR};")
        self.cancel_button = QPushButton()
        self.cancel_button.clicked.connect(self.cancelRequested)

        column.addWidget(self._picking_caption)
        column.addWidget(self._picking_hint)
        column.addWidget(self.cancel_button)
        column.addStretch(1)
        return page

    def _build_preview(self) -> QWidget:
        """Editando: el fuente que va saliendo, y qué hacer con él."""
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        self._preview_caption = QLabel()
        self._preview_caption.setObjectName("explorerHeader")

        # El mismo editor del resto de la aplicación, y **escribible**: lo
        # normal es construir el overlay marcando propiedades, pero un valor
        # de relleno (`<0>`, `""`) hay que poder corregirlo donde se ve, sin
        # tener que generar el fichero antes. Lo que se escriba aquí vuelve
        # al modelo (`previewEdited`), así que las listas siguen al día.
        self.preview = DtsEditor()
        self.preview.lineClicked.connect(self._on_preview_click)
        self.preview.textChanged.connect(self._on_preview_typed)

        actions = QWidget()
        actions.setObjectName("viewToolbar")
        action_column = QVBoxLayout(actions)
        action_column.setContentsMargins(12, 8, 12, 8)
        action_column.setSpacing(6)
        self.generate_button = QPushButton()
        self.generate_button.setObjectName("primaryButton")
        self.generate_button.clicked.connect(self.generateRequested)
        self.discard_button = QPushButton()
        self.discard_button.clicked.connect(self.cancelRequested)
        action_column.addWidget(self.generate_button)
        action_column.addWidget(self.discard_button)

        column.addWidget(self._preview_caption)
        column.addWidget(self.preview, 1)
        column.addWidget(actions)
        return page

    def _on_preview_typed(self) -> None:
        """Arranca la relectura del texto, si el cambio no es del borrador."""
        if not self._writing:
            self._reparse.start()

    def _on_preview_click(self, line: int) -> None:
        """Traduce el clic a la línea donde empieza el nodo que lo contiene.

        Se apoya en el mismo emparejado de llaves que ya mantiene el plegado
        del editor (`innermost_fold_region`), así que pulsar en una
        propiedad, en el nombre del nodo o en su `};` de cierre señala al
        mismo nodo. Fuera de todo bloque (la cabecera del fichero) no se
        avisa: no hay nodo que apuntar y cambiar la selección sería peor que
        dejarla donde estaba.
        """
        region = self.preview.innermost_fold_region(line)
        if region is not None:
            self.lineSelected.emit(region[0])

    def retranslate(self) -> None:
        """Rehace los textos fijos (ver `Retranslates`)."""
        self.create_button.setText(self.tr("Create new overlay"))
        self._refresh_overlays_header()
        self._idle_hint.setText(
            self.tr(
                "An overlay changes a node of a device tree without "
                "touching its file. You will be asked which node first."
            )
        )
        self._picking_caption.setText(self.tr("SELECT THE TARGET NODE"))
        self._picking_hint.setText(
            self.tr(
                "Click inside the node you want to change, in the editor. "
                "Its label is what the overlay will point at."
            )
        )
        self.cancel_button.setText(self.tr("Cancel"))
        self._preview_caption.setText(self.tr("OVERLAY PREVIEW"))
        self.preview.setToolTip(
            self.tr("Click a node here to edit that node's properties.")
        )
        self.generate_button.setText(self.tr("Create overlay file"))
        self.discard_button.setText(self.tr("Discard"))

    # ------------------------------------------------------------------
    # Listado
    # ------------------------------------------------------------------
    def set_library(
        self, folder: Optional[Path], base: Optional[DeviceTreeNode]
    ) -> None:
        """Dice al listado qué carpeta enseñar y cuál es la base cargada."""
        self.overlay_list.set_context(folder, base)

    # ------------------------------------------------------------------
    # Estados
    # ------------------------------------------------------------------
    def show_idle(self) -> None:
        """Vuelve al principio: solo el botón de crear."""
        self._reparse.stop()
        self._writing = True
        self.preview.setPlainText("")
        self._writing = False
        self._pages.setCurrentIndex(PAGE_IDLE)

    def show_picking(self) -> None:
        """Pide que se señale el nodo objetivo en el editor."""
        self._pages.setCurrentIndex(PAGE_PICKING)

    def show_preview(self, text: str) -> None:
        """Enseña el fuente del overlay tal como va, conservando el punto de vista.

        Se reescribe entero en cada cambio (marcar una propiedad, añadir un
        nodo), así que sin guardar el desplazamiento y la línea del cursor el
        panel saltaría al principio cada vez que se toca algo — y ahora que
        se puede escribir aquí, eso además movería el punto de escritura.

        No hace nada si el texto ya es ese: reescribirlo sin necesidad
        rompería una selección o un deshacer por gusto.
        """
        if text == self.preview.toPlainText():
            self._pages.setCurrentIndex(PAGE_PREVIEW)
            return

        scroll = self.preview.verticalScrollBar().value()
        linea = self.preview.textCursor().blockNumber()
        self._writing = True
        self.preview.setPlainText(text)
        self._writing = False
        self._place_cursor(linea + 1)
        self.preview.verticalScrollBar().setValue(scroll)
        self._pages.setCurrentIndex(PAGE_PREVIEW)

    def highlight_line(self, line: Optional[int]) -> None:
        """Lleva el cursor del preview a la línea del nodo apuntado, y la enseña.

        Es la vuelta del clic: si el nodo se cambia desde la otra vista (al
        añadir uno nuevo, que pasa a ser el apuntado), el preview tiene que
        enseñar cuál es sin que haya que buscarlo.
        """
        if line is not None and self._place_cursor(line):
            self.preview.centerCursor()

    def _place_cursor(self, line: int) -> bool:
        """Pone el cursor al principio de `line`, sin mover el desplazamiento."""
        block = self.preview.document().findBlockByNumber(max(0, line - 1))
        if not block.isValid():
            return False
        cursor = self.preview.textCursor()
        cursor.setPosition(block.position())
        self.preview.setTextCursor(cursor)
        return True
