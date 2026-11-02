"""Pestaña de visualización: el device tree dibujado como grafo de nodos.

Comparte el motor de conexión del Generador (`PeripheralTreeModel`/
`PeripheralSlot`, inyectado desde `MainWindow`): misma lógica, interfaz
distinta — aquí se conecta arrastrando un compatible de la paleta sobre un
nodo del grafo en vez de eligiéndolo en un desplegable.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Set

from PySide6.QtCore import QEvent, QSize, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from kernelgrove.api import (
    BindingOption,
    DeviceTreeNode,
    KernelGroveService,
    PeripheralSlot,
    ResolvedInclude,
)
from kernelgrove.gui import style
from kernelgrove.gui.widgets import icons
from kernelgrove.gui.translations import Retranslates
from kernelgrove.gui.models.tree_model import PeripheralTreeModel
from kernelgrove.gui.widgets.binding_palette import BindingPalette
from kernelgrove.gui.widgets.tree_graph import TreeGraphView, build_graph
from kernelgrove.gui.workers import BindingOptionsWorker

def legend_colors():
    """Mismos colores que dibuja el grafo, para que la leyenda no mienta.

    Se consultan al montar la barra y no al importar el módulo: con dos
    modos, una tupla de módulo se queda con los colores del arranque —igual
    que los textos, que tampoco se pueden traducir aquí porque todavía no
    hay `QApplication` ni idioma.
    """
    return (
        style.GRAPH_COLOR_ROOT,
        style.GRAPH_COLOR_CONTROLLER,
        style.GRAPH_COLOR_NODE,
        style.COLOR_GENERATED_BRIGHT,
    )


# Separación de la botonera flotante respecto a la esquina del lienzo.
_CONTROLS_MARGIN = 12


class _CanvasControls(Retranslates, QFrame):
    """Botonera flotante sobre el lienzo: acercar, alejar y encuadrar.

    Va **encima** del grafo y no en la barra de arriba porque es del lienzo:
    el zoom se usa mirando lo que se está ampliando, y tener que subir a una
    franja al otro extremo de la vista para dar un paso de zoom es el
    recorrido que hace que nadie use el botón y todo el mundo use la rueda.
    Es hija de la vista, así que `VisualizerTab` la recoloca cuando esta
    cambia de tamaño (ver `eventFilter`).
    """

    def __init__(self, view: TreeGraphView, parent: QWidget):
        """Monta los tres botones sobre `view`."""
        super().__init__(parent)
        self.setObjectName("canvasControls")
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(2)

        # Los tres del proyecto de referencia: `add`, `remove` y
        # `fit_screen`, dibujados a mano como el resto (`widgets/icons.py`).
        self._buttons = []
        tamano = style.CANVAS_ICON_SIZE
        for draw, slot in (
            (icons.plus_icon, lambda: view.zoom_by(1.2)),
            (icons.minus_icon, lambda: view.zoom_by(1 / 1.2)),
            (icons.fit_icon, view.fit),
            # Reordenar es del lienzo igual que el zoom: se pulsa mirando el
            # desorden. El glifo es el mismo `account_tree` que marca la
            # sección del grafo, que es exactamente lo que devuelve.
            (icons.tree_icon, view.auto_arrange),
        ):
            button = QToolButton()
            button.setObjectName("canvasControlButton")
            button.setIcon(draw(tamano, style.MUTED_TEXT_COLOR))
            button.setIconSize(QSize(tamano, tamano))
            button.clicked.connect(slot)
            row.addWidget(button)
            self._buttons.append(button)

        # El porcentaje al lado de los botones: sin él, tras unas cuantas
        # vueltas de rueda no se sabe si se está al 40 % o al 300 %, y la
        # única forma de volver a un tamaño conocido es encuadrar.
        self.zoom_label = QLabel()
        self.zoom_label.setObjectName("canvasZoomLabel")
        row.addWidget(self.zoom_label)
        view.zoomChanged.connect(self._on_zoom_changed)
        self._on_zoom_changed(view.transform().m11())
        self.retranslate()

    def _on_zoom_changed(self, zoom: float) -> None:
        """Escribe el zoom en tanto por ciento, redondeado."""
        self.zoom_label.setText(f"{round(zoom * 100)}%")

    def refresh_icons(self) -> None:
        """Redibuja los tres iconos en el color activo (ver `MainWindow`)."""
        tamano = style.CANVAS_ICON_SIZE
        for button, draw in zip(
            self._buttons,
            (icons.plus_icon, icons.minus_icon, icons.fit_icon, icons.tree_icon),
        ):
            button.setIcon(draw(tamano, style.MUTED_TEXT_COLOR))

    def retranslate(self) -> None:
        """Los tooltips: es todo el texto que tiene (los símbolos no se traducen)."""
        for button, tip in zip(
            self._buttons,
            (
                self.tr("Zoom in"),
                self.tr("Zoom out"),
                self.tr("Fit to view"),
                self.tr(
                    "Auto-arrange the nodes (undoes what you moved by hand). "
                    "Drag a node to move it, drag on the canvas to select "
                    "several, middle button to pan."
                ),
            ),
        ):
            button.setToolTip(tip)


class VisualizerTab(Retranslates, QWidget):
    """Grafo del árbol cargado, con las inclusiones como nodos abribles."""

    includeActivated = Signal(object)
    socActivated = Signal()
    nodeInspectRequested = Signal(str)
    nodeSourceRequested = Signal(str, str)
    # Nodos a borrar del fuente del documento abierto, como `(línea, nombre)`
    # — ver `TreeGraphView.nodesDeleteRequested`.
    nodesDeleteRequested = Signal(list)

    def __init__(
        self, service: KernelGroveService, tree_model: PeripheralTreeModel, parent=None
    ):
        """Monta la barra de opciones, el grafo y la paleta de conexión."""
        super().__init__(parent)
        self._service = service
        self._tree_model = tree_model

        self._root: Optional[DeviceTreeNode] = None
        self._includes: List[ResolvedInclude] = []
        self._controllers: set = set()
        self._soc_name: Optional[str] = None
        self._board_name: Optional[str] = None
        self._session_slots: Optional[List[PeripheralSlot]] = None
        self._hardware: Optional[dict] = None
        self._compatibles_by_bus: Dict[str, Set[str]] = {}
        self._options_by_compatible: Dict[str, BindingOption] = {}
        self._options_worker: Optional[BindingOptionsWorker] = None
        # Ancho de la paleta antes de plegarla (`_toggle_palette`), para
        # devolvérselo al desplegar en vez de dejar que el splitter reparta a
        # partes iguales.
        self._palette_width = style.PALETTE_DEFAULT_WIDTH
        # Si esta ventana deja tocar el árbol o es solo para verlo
        # (`set_editable`).
        self._editable = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.splitter = QSplitter()
        self.graph = TreeGraphView()
        self.graph.includeActivated.connect(self.includeActivated)
        self.graph.socActivated.connect(self.socActivated)
        self.graph.nodeInspectRequested.connect(self.nodeInspectRequested)
        self.graph.nodeSourceRequested.connect(self.nodeSourceRequested)
        self.graph.drop_validator = self._is_valid_drop
        self.graph.deviceDropped.connect(self._on_device_dropped)
        self.graph.deviceRemoved.connect(self._on_device_removed)
        self.graph.nodesDeleteRequested.connect(self.nodesDeleteRequested)

        # La barra (encuadrar + leyenda) va **dentro** de la columna del
        # grafo, no encima de toda la pestaña: es del grafo, no de la
        # pestaña. Puesta arriba del todo, al plegar la paleta la leyenda
        # quedaba flotando sobre la franja plegada, con la barra terminando
        # en un borde que ya no se correspondía con nada.
        graph_column = QWidget()
        column = QVBoxLayout(graph_column)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        # La leyenda no va dentro de una barra: con el encuadre ya flotando
        # sobre el lienzo, lo único que quedaba en la franja era la leyenda,
        # y un recuadro relleno de punta a punta para cuatro puntos de color
        # es marco por nada. Sin fondo ni línea, la leyenda se lee sobre el
        # propio lienzo, igual que la botonera de zoom de la otra esquina.
        toolbar = QWidget()
        toolbar.setObjectName("graphLegendBar")
        toolbar.setLayout(self._build_toolbar())
        column.addWidget(toolbar)
        column.addWidget(self.graph, 1)
        self.splitter.addWidget(graph_column)

        # Flota sobre el lienzo, en su esquina inferior izquierda. Es hija de
        # la vista (no del layout), así que hay que recolocarla a mano cada
        # vez que la vista cambia de tamaño.
        self.canvas_controls = _CanvasControls(self.graph, self.graph)
        self.graph.installEventFilter(self)
        self._place_canvas_controls()

        self.palette = BindingPalette()
        # En cuanto se coge un compatible de la paleta, iluminar de inmediato
        # los nodos del grafo donde sería válido soltarlo -no solo el que
        # esté bajo el cursor en cada instante, que ya se marca aparte al
        # entrar el arrastre en la vista (`_NodeItem.dragEnterEvent`)-.
        self.palette.dragStarted.connect(self.graph.highlight_drop_targets)
        self.palette.dragFinished.connect(self.graph.clear_drop_highlights)
        self.palette.collapseToggled.connect(self._on_palette_collapse_toggled)
        self.splitter.addWidget(self.palette)
        # Mínimo explícito y casi nulo: la cuadrícula de la paleta es de
        # ancho fijo, y ese mínimo subía por el splitter y la pila central
        # hasta la ventana, que dejaba sin sitio al Inspector **aunque se
        # estuviera en el editor**. Si no cabe, se recorta y el splitter
        # la puede plegar.
        self.palette.setMinimumWidth(1)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        # Ancho inicial explícito: con solo el factor de estiramiento, el
        # reparto de partida sale del `sizeHint` de cada lado (más estrecho
        # de lo que hace falta para que la cuadrícula de 2 columnas de la
        # paleta se vea cómoda), y solo se ensanchaba arrastrando el splitter
        # a mano.
        self.splitter.setSizes([1000, self._palette_width])
        layout.addWidget(self.splitter, 1)

        self._tree_model.modelReset.connect(self._prefetch_palette)
        self._tree_model.slotStateChanged.connect(self._redraw)

        # Al final del todo: `retranslate` redibuja el grafo, que hasta esta
        # línea no existe.
        self.retranslate()

    def _build_toolbar(self) -> QHBoxLayout:
        """Controles de encuadre y leyenda de colores."""
        bar = QHBoxLayout()
        bar.setContentsMargins(12, 7, 12, 7)
        bar.setSpacing(8)

        # El encuadre ya no está aquí sino flotando sobre el lienzo
        # (`_CanvasControls`); esta franja se queda solo con la leyenda, que
        # es lo que sí es de la pestaña y no del gesto de mirar el grafo.
        bar.addStretch(1)

        # Cuántos nodos se han quedado fuera por estar apagados. Va a la
        # izquierda de la leyenda y solo cuando hay alguno: sin esta línea,
        # abrir un `.dtsi` de SoC —que trae apagado casi todo— enseña una
        # ficha sola y parece que el grafo no funciona.
        self._disabled_label = QLabel()
        self._disabled_label.setObjectName("viewToolbarStatus")
        self._disabled_label.setVisible(False)
        bar.addWidget(self._disabled_label)
        bar.addSpacing(16)

        self._legend = QLabel()
        # Que la leyenda no fije el ancho mínimo: con sus cuatro entradas
        # pedía ~350 px, que subían por la pila central hasta la ventana y
        # le quitaban sitio al Inspector aunque se estuviera en el editor.
        # Es informativa; si no cabe, se recorta.
        self._legend.setMinimumWidth(1)
        bar.addWidget(self._legend)
        return bar

    def retranslate(self) -> None:
        """Rehace botón y leyenda, y redibuja el grafo (ver `Retranslates`).

        El grafo se reconstruye entero porque sus etiquetas —«(+12 nodos)»,
        «includes no encontrados»— y los tooltips de cada círculo se fijan al
        crear los items, que son `QGraphicsItem` y no reciben el evento de
        cambio de idioma.
        """
        legend_entries = list(
            zip(
                legend_colors(),
                (
                    self.tr("SoC"),
                    self.tr("controller"),
                    self.tr("node"),
                    self.tr("connected from the editor"),
                ),
            )
        )
        # Sin paleta no se puede conectar nada, así que ese color no aparece
        # nunca: explicarlo en la leyenda sería contar algo que no pasa.
        if not self._editable:
            legend_entries = legend_entries[:-1]
        self._legend.setText(
            "&nbsp;&nbsp;&nbsp;&nbsp;".join(
                f'<span style="color:{color};">●</span> '
                f'<span style="color:{style.GRAPH_COLOR_TEXT};">{text}</span>'
                for color, text in legend_entries
            )
        )
        self._redraw()

    def eventFilter(self, obj, event):
        """Recoloca la botonera flotante cuando el lienzo cambia de tamaño."""
        if obj is self.graph and event.type() == QEvent.Resize:
            self._place_canvas_controls()
        return super().eventFilter(obj, event)

    def _place_canvas_controls(self) -> None:
        """Pega la botonera a la esquina inferior izquierda del lienzo."""
        controls = self.canvas_controls
        controls.adjustSize()
        controls.move(
            _CONTROLS_MARGIN,
            self.graph.height() - controls.height() - _CONTROLS_MARGIN,
        )
        controls.raise_()

    def set_editable(self, editable: bool) -> None:
        """Deja la ventana en solo-visualización, o completa.

        En solo-visualización —una release, mientras generar desde el grafo
        sea experimental (ver `gui/features`)— no hay paleta de dispositivos
        ni se puede tocar el árbol. El grafo se sigue recorriendo entero
        —plegar, mover, abrir el Inspector, saltar al fuente—, que es lo que
        se viene a hacer.
        """
        self._editable = editable
        self.palette.setVisible(editable)
        self.graph.set_editable(editable)
        self.retranslate()

    def _on_palette_collapse_toggled(self, collapsed: bool) -> None:
        """Encoge o devuelve el hueco del splitter al plegar la paleta.

        La flecha vive en una esquina de la propia paleta
        (`BindingPalette.set_collapsed`), que ya no se oculta entera -sigue
        visible para poder volver a pulsarla-, así que aquí solo hace falta
        ajustar el ancho que le da el splitter, no su visibilidad.
        """
        sizes = self.splitter.sizes()
        total = sum(sizes) or (1000 + self._palette_width)
        if collapsed:
            self._palette_width = sizes[1] or self._palette_width
            target = style.DOCK_COLLAPSED_WIDTH
        else:
            target = self._palette_width
        self.splitter.setSizes([max(1, total - target), target])

    def show_tree(
        self,
        root: Optional[DeviceTreeNode],
        includes: Sequence[ResolvedInclude] = (),
        controller_names: Optional[set] = None,
        soc_name: Optional[str] = None,
        board_name: Optional[str] = None,
        session_slots: Optional[List[PeripheralSlot]] = None,
        hardware: Optional[dict] = None,
    ) -> None:
        """Dibuja el árbol recibido del editor.

        Solo se representan las inclusiones de device tree (`.dts`/`.dtsi`):
        una cabecera `dt-bindings/*.h` no aporta nodos al árbol, así que como
        nodo del grafo solo sería ruido. El nodo central se etiqueta con
        `soc_name` al desplegarse -lo que se empaqueta es el SoC, no la raíz
        DTS en abstracto- y con `board_name` mientras está plegado, que es
        cuando lo que se ve desde fuera es la placa.

        `session_slots` es la sesión de conexión del documento mostrado (o
        `None` si no le pertenece: `MainWindow` decide, comparando contra el
        documento que la creó) y se solapa sobre el grafo — ver `build_graph`.
        """
        self._root = root
        self._includes = [item for item in includes if item.is_device_tree]
        self._controllers = controller_names or set()
        self._soc_name = soc_name
        self._board_name = board_name
        self._session_slots = session_slots
        # Qué hardware describe el árbol; lo enseña la ficha central, igual
        # que la entrada del catálogo. Lo calcula `MainWindow` sobre el árbol
        # ya fusionado, que es el único que tiene los cpus de una board.
        self._hardware = hardware
        self._redraw()

    def _redraw(self) -> None:
        """Reconstruye el grafo con las opciones actuales."""
        if self._root is None:
            self.graph.show_graph(None)
            self._disabled_label.setVisible(False)
            return

        grafo = build_graph(
            self._root,
            includes=self._includes,
            controller_names=self._controllers,
            soc_name=self._soc_name,
            board_name=self._board_name,
            root_slots=self._session_slots,
            hardware=self._hardware,
        )
        self.graph.show_graph(grafo)
        self._disabled_label.setText(
            self.tr("{count} disabled nodes not shown").format(
                count=grafo.hidden_disabled
            )
        )
        # La segunda frase manda al panel del SoC, que en modo lectura no se
        # abre (`TreeGraphView.request_soc_properties`): decir cómo encenderlo
        # a quien no puede es peor que no decir nada.
        self._disabled_label.setToolTip(
            self.tr(
                "A node with status = \"disabled\" is not in the machine. "
                "Turn it on from the SoC properties dialog -double click the "
                "central card- and it comes back."
            )
            if self._editable
            else self.tr(
                "A node with status = \"disabled\" is not in the machine."
            )
        )
        self._disabled_label.setVisible(bool(grafo.hidden_disabled))

    def clear(self) -> None:
        """Vacía la vista."""
        self._root = None
        self._includes = []
        self._soc_name = None
        self._board_name = None
        self._session_slots = None
        self.graph.show_graph(None)

    # ------------------------------------------------------------------
    # Conexión de dispositivos (paleta + arrastrar y soltar)
    # ------------------------------------------------------------------
    def _prefetch_palette(self) -> None:
        """Recarga la paleta con los dispositivos conectables a los buses del SoC.

        Se dispara con `modelReset` del `PeripheralTreeModel` compartido, que
        `PeripheralTreeModel.set_root_slots` ya emite al cargar una sesión
        nueva desde `GeneratorTab.load_profile` — sin señal propia que
        inventar.
        """
        self._compatibles_by_bus = {}
        self._options_by_compatible = {}
        self.palette.set_options([])

        buses = sorted(
            {
                slot.child_bus
                for slot in self._tree_model.root_slots()
                if slot.child_bus
            }
        )
        if not buses:
            return

        if self._options_worker is not None and self._options_worker.isRunning():
            self._options_worker.requestInterruption()

        self._options_worker = BindingOptionsWorker(self._service, buses, self)
        self._options_worker.options_ready.connect(self._on_options_ready)
        self._options_worker.start()

    def _on_options_ready(self, bus: str, options: List[BindingOption]) -> None:
        """Añade los dispositivos de un bus a la paleta según van llegando.

        Un mismo compatible puede ofrecerse en más de un bus; se deduplica
        por compatible (`_options_by_compatible`) para no repetirlo en la
        lista mostrada, y por bus (`_compatibles_by_bus`) para validar un
        drop sin volver a consultar la base de datos.
        """
        self._compatibles_by_bus[bus] = {option.compatible for option in options}
        for option in options:
            self._options_by_compatible.setdefault(option.compatible, option)
        self.palette.set_options(list(self._options_by_compatible.values()))

    def _is_valid_drop(self, slot: PeripheralSlot, compatible: str) -> bool:
        """Indica si `compatible` puede conectarse a `slot` (mismo bus)."""
        return compatible in self._compatibles_by_bus.get(slot.child_bus or "", ())

    def _on_device_dropped(self, slot: PeripheralSlot, compatible: str) -> None:
        """Conecta lo soltado; el redibujado llega por `slotStateChanged`."""
        self._tree_model.connect_to_slot(slot, compatible)

    def _on_device_removed(self, slot: PeripheralSlot) -> None:
        """Desconecta el dispositivo señalado desde el menú contextual del grafo."""
        self._tree_model.disconnect_by_slot(slot)

    def stop_workers(self) -> None:
        """Detiene los hilos en curso (al cerrar la ventana)."""
        if self._options_worker is not None and self._options_worker.isRunning():
            self._options_worker.requestInterruption()
            self._options_worker.quit()
            self._options_worker.wait(2000)
