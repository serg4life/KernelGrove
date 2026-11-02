"""Paleta de compatibles arrastrables para conectar dispositivos en el grafo.

Mismo motor que el desplegable del Generador (`BindingDelegate`): solo cambia
la interacción, de elegir en un combo a arrastrar y soltar sobre un nodo del
grafo. La validez del destino (que el compatible declare el bus que el nodo
ofrece) se comprueba al soltar, no aquí — ver `TreeGraphView.drop_validator`.

Un desplegable por grupo (`_CollapsibleSection`), cada uno con su propia
cuadrícula de `style.PALETTE_COLUMNS` columnas — no una lista plana ordenada
por subsistema, que dejaba el agrupado como algo que solo se notaba mirando
con atención. Cada ítem se pinta como un nodo del grafo (rectángulo de
esquinas redondeadas): solo el compatible, centrado; el título y el grupo
—si lo tiene— quedan en el tooltip, para no llenar la cuadrícula de texto.

**El grupo no es el subsistema crudo del kernel.** `option.subsystem` es el
nombre del directorio de `bindings/` del que salió el YAML (`iio`, `hwmon`,
`mfd`...) — treinta y tantos posibles, la mayoría con dos o tres
dispositivos, y ninguno dice nada a quien no conoce el kernel por dentro.
`widgets/binding_groups.py` los reduce a un puñado de grupos por tipo (buses,
sensores, audio...), cada uno con su propio icono dibujado a mano, en el
orden fijo de `GROUP_ORDER` en vez de alfabético por subsistema.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from PySide6.QtCore import QMimeData, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from kernelgrove.api import BindingOption
from kernelgrove.gui import style, theme
from kernelgrove.gui.translations import Retranslates
from kernelgrove.gui.widgets import binding_groups

# El compatible real se guarda aparte de la etiqueta visible, igual que
# `BindingDelegate`.
COMPATIBLE_ROLE = Qt.UserRole + 1

_ITEM_SIZE = QSize(*style.PALETTE_ITEM_SIZE)

# Flechas del botón de plegado, en la esquina de la paleta: apunta hacia
# donde se va a esconder el contenido, igual que en los docks laterales
# (`MainWindow._build_collapsible_header`).
_ARROW_COLLAPSE = "›"
_ARROW_EXPAND = "‹"

# Mismo aspecto que los nodos del grafo (rectángulo, esquinas redondeadas),
# para que arrastrar un ítem de aquí a un nodo se sienta como mover la misma
# pieza. El borde se ilumina en el morado de "conectado" al pasar el ratón,
# como pista de que es lo arrastrable.
def _list_style() -> str:
    """Hoja de la cuadrícula, con los colores del modo activo.

    Función y no constante de módulo: con dos modos, una hoja compuesta al
    importar se queda con los colores que hubiera al arrancar y no cambia
    nunca más.
    """
    return f"""
QListWidget {{
    background: transparent;
    border: none;
}}
QListWidget::item {{
    background: {style.PALETTE_ITEM_BG};
    border: 1px solid {style.PALETTE_ITEM_BORDER};
    border-radius: {theme.RADIUS_ITEM}px;
    padding: 8px 6px;
    margin: 3px;
    color: {style.PALETTE_ITEM_TEXT};
}}
QListWidget::item:hover {{
    border-color: {style.COLOR_GENERATED_BRIGHT};
}}
QListWidget::item:selected {{
    background: {style.PALETTE_ITEM_SELECTED_BG};
}}
"""

# Cabecera de subsistema: una fila de lista, no un botón. Sin fondo propio
# ni esquina redondeada —la sección no es una tarjeta— y con el texto
# pegado a la izquierda, que es donde el ojo busca la primera letra al
# recorrer una columna de veinte nombres.
def _header_style() -> str:
    """Hoja de la cabecera de subsistema, con los colores del modo activo."""
    return f"""
QPushButton {{
    background: {style.PALETTE_SECTION_HEADER_BG};
    border: none;
    border-radius: 3px;
    padding: 5px 8px;
    text-align: left;
    font-weight: 600;
    color: {style.PALETTE_SECTION_HEADER_TEXT};
}}
QPushButton:hover {{
    background: {style.PALETTE_SECTION_HEADER_HOVER_BG};
    color: {style.PALETTE_ITEM_TEXT};
}}
"""


class _DraggableList(QListWidget):
    """Cuadrícula de exactamente `style.PALETTE_COLUMNS` columnas fijas.

    Tanto el tamaño de cada ítem (`_ITEM_SIZE`) como el ancho del propio
    widget (`style.PALETTE_GRID_WIDTH`) son fijos. No basta con fijar solo el
    tamaño del ítem: dejando el widget en `Expanding` se estira al ancho que
    le dé el `QSplitter` del visualizador -normalmente bastante menos de dos
    columnas de 190px-, así que en vez de dos columnas aparecía solo una, y
    además más baja de lo que hacía falta (`sync_height` sí asume
    `PALETTE_COLUMNS` columnas, así que con una sola columna real la mitad de
    los ítems quedaban recortados fuera del área visible — nada que arrastrar
    ahí, aunque el código de arrastre en sí funcione). Fijar el ancho del
    todo es lo que garantiza siempre dos columnas, sea cual sea el ancho que
    le dé el splitter — la cabecera (`_CollapsibleSection.header`) sigue
    ocupando el ancho completo de la paleta por su cuenta, vía el layout.
    """

    # Se emiten alrededor de `startDrag`, no de `mousePressEvent`: solo ahí
    # se sabe que Qt realmente va a arrancar un arrastre (y no un simple
    # clic o una selección). `dragStarted` lleva el compatible para que
    # quien la escuche pueda iluminar de inmediato los nodos válidos del
    # grafo, antes incluso de que el cursor entre en esa vista.
    dragStarted = Signal(str)
    dragFinished = Signal()

    def __init__(self, parent=None):
        """Configura la cuadrícula, arrastrable y sin scroll propio."""
        super().__init__(parent)
        self.setStyleSheet(_list_style())
        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)
        # `setMovement(Static)` tiene un efecto secundario real de Qt: deja
        # `dragEnabled` en `False` y `dragDropMode` en `DropOnly`, aunque ya
        # se hubieran fijado antes a lo contrario en este mismo constructor
        # (confirmado leyendo `dragEnabled()`/`dragDropMode()` justo después
        # de esta llamada). Por eso la configuración de arrastre tiene que
        # fijarse DESPUÉS de `setMovement`/`setViewMode`, no antes — si no,
        # ningún ítem arranca un arrastre nunca, sin ningún error visible.
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setGridSize(_ITEM_SIZE)
        self.setSpacing(0)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFixedWidth(style.PALETTE_GRID_WIDTH)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self.setDragEnabled(True)
        # `dragDropMode` es la forma completa de dejar esta lista como
        # origen de arrastre puro (sin aceptar sueltos aquí, que no le
        # corresponde a ella sino al grafo) — más explícito que depender
        # solo de `setDragEnabled`.
        self.setDragDropMode(QListWidget.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)

    def mimeData(self, items: List[QListWidgetItem]) -> QMimeData:
        """Empaqueta el compatible del primer ítem arrastrado como texto plano."""
        mime = QMimeData()
        if items:
            mime.setText(items[0].data(COMPATIBLE_ROLE))
        return mime

    def startDrag(self, supported_actions) -> None:
        """Avisa del inicio/fin real del arrastre (`dragStarted`/`dragFinished`).

        `QDrag.exec()`, dentro de `super().startDrag`, bloquea hasta que el
        arrastre termina (soltado o cancelado) — por eso `dragFinished` se
        emite justo después, no en un `dragLeaveEvent` que aquí nunca
        llegaría (el origen del arrastre no recibe sus propios eventos de
        soltar).
        """
        selected = self.selectedItems()
        if selected:
            self.dragStarted.emit(selected[0].data(COMPATIBLE_ROLE))
        super().startDrag(supported_actions)
        self.dragFinished.emit()

    def sync_height(self) -> None:
        """Ajusta la altura a lo que ocupan sus filas — sin scroll propio.

        La cuadrícula entera vive dentro del `QScrollArea` de la paleta, así
        que cada sección debe medir justo lo suyo en vez de traer su propia
        barra de desplazamiento (que dejaría scrolls anidados).
        """
        visible = sum(
            1 for row in range(self.count()) if not self.item(row).isHidden()
        )
        rows = max(1, -(-visible // style.PALETTE_COLUMNS)) if visible else 0
        self.setFixedHeight(rows * _ITEM_SIZE.height())


class _CollapsibleSection(Retranslates, QWidget):
    """Cabecera "[icono] ▸ grupo (N)" que pliega/despliega su cuadrícula."""

    toggled = Signal()

    def __init__(self, group_key: str, parent=None):
        """Monta la cabecera y la cuadrícula, plegada de entrada."""
        super().__init__(parent)
        self.group_key = group_key
        self._collapsed = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # `QPushButton` y no `QToolButton`: el segundo centra su contenido
        # pase lo que pase en el `text-align` de la hoja de estilos, y una
        # columna de grupos con el nombre bailando en el centro es
        # imposible de recorrer con la vista.
        self.header = QPushButton()
        self.header.setFlat(True)
        self.header.setStyleSheet(_header_style())
        self.header.setCursor(Qt.PointingHandCursor)
        icon_size = style.PALETTE_GROUP_ICON_SIZE
        self.header.setIconSize(QSize(icon_size, icon_size))
        # Explícito en vez de confiar en el estiramiento implícito del
        # `QVBoxLayout`: sin esto un `QToolButton` puede quedarse a su
        # `sizeHint`, más estrecho que la paleta, en vez de ocupar todo el
        # ancho del desplegable como pide el usuario.
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.header.clicked.connect(self._toggle)
        layout.addWidget(self.header)

        self.list_widget = _DraggableList()
        self.list_widget.setVisible(False)
        layout.addWidget(self.list_widget)

        self.refresh_icons()
        self.set_collapsed(True)

    def _toggle(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        """Pliega o despliega, y actualiza la flecha de la cabecera."""
        self._collapsed = collapsed
        self.list_widget.setVisible(not collapsed)
        arrow = "▸" if collapsed else "▾"
        # `&&` y no `&`: en un `QPushButton` un `&` suelto marca el
        # mnemotécnico del botón (subraya la letra siguiente y desaparece él
        # mismo), y "Buses & expanders" salía como "Buses  expanders" — un
        # grupo con el nombre partido a la mitad.
        label = binding_groups.group_label(self.group_key).replace("&", "&&")
        self.header.setText(f"{arrow} {label} ({self.list_widget.count()})")
        self.toggled.emit()

    def retranslate(self) -> None:
        """Rehace el texto de la cabecera en el idioma activo (ver `Retranslates`)."""
        self.set_collapsed(self._collapsed)

    def refresh_icons(self) -> None:
        """Redibuja el icono del grupo (el "logo") en el acento activo.

        Se pinta a mano con `QPainter` (`widgets/icons.py`), así que no lo
        alcanza la hoja de estilos y hay que rehacerlo al cambiar de piel —
        `MainWindow._repaint_theme` lo encuentra solo, recorriendo el árbol
        de widgets en busca de `refresh_icons`.
        """
        self.header.setIcon(
            binding_groups.group_icon(
                self.group_key, style.PALETTE_GROUP_ICON_SIZE, theme.ACCENT
            )
        )

    def set_options(self, options: List[BindingOption]) -> None:
        """Puebla la cuadrícula de este grupo, ordenada por compatible."""
        self.list_widget.clear()
        for option in sorted(options, key=lambda item: item.compatible):
            item = QListWidgetItem(option.compatible)
            item.setTextAlignment(Qt.AlignCenter)
            item.setData(COMPATIBLE_ROLE, option.compatible)
            item.setToolTip(
                f"{option.label}\n"
                + self.tr("Group: {group}").format(
                    group=binding_groups.group_label(self.group_key)
                )
            )
            self.list_widget.addItem(item)
        self.set_collapsed(self._collapsed)
        self.list_widget.sync_height()

    def apply_filter(self, needle: str) -> bool:
        """Oculta lo que no casa; devuelve si queda algo visible en la sección.

        Con filtro activo la sección se despliega sola si tiene alguna
        coincidencia, para no obligar a abrir cada desplegable a mano
        mientras se busca.
        """
        any_visible = False
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            match = needle in item.text().lower()
            item.setHidden(not match)
            any_visible = any_visible or match

        self.setVisible(any_visible)
        if needle:
            self.set_collapsed(not any_visible and self._collapsed)
        self.list_widget.sync_height()
        return any_visible


class BindingPalette(Retranslates, QWidget):
    """Filtro de texto + desplegables por subsistema de dispositivos conectables."""

    # Reenviadas desde el `_DraggableList` de cada sección (ver `set_options`):
    # la paleta tiene varias, una por subsistema, pero quien escucha desde
    # fuera (`VisualizerTab`) solo quiere saber "se ha cogido/soltado algo",
    # sin que le importe de qué sección viene.
    dragStarted = Signal(str)
    dragFinished = Signal()
    # La paleta entera se pliega o despliega (ver `_toggle_collapsed`);
    # `VisualizerTab` lo escucha para encoger o devolver el hueco que le da
    # el splitter, ya que la paleta no sabe nada de él.
    collapseToggled = Signal(bool)

    def __init__(self, parent=None):
        """Monta el filtro y el área de desplegables, vacía hasta `set_options`."""
        super().__init__(parent)
        self._sections: Dict[str, _CollapsibleSection] = {}
        self._collapsed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.addStretch(1)
        # La flecha vive fuera de `self._content` (lo que se pliega) para
        # poder seguir pulsándola una vez plegado y así volver a desplegar
        # — si estuviera dentro, desaparecería con el resto.
        self._collapse_button = QToolButton()
        self._collapse_button.setObjectName("paletteCollapseButton")
        self._collapse_button.setText(_ARROW_COLLAPSE)
        self._collapse_button.setCursor(Qt.PointingHandCursor)
        self._collapse_button.clicked.connect(self._toggle_collapsed)
        header.addWidget(self._collapse_button)
        layout.addLayout(header)

        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)

        self.filter_edit = QLineEdit()
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        content_layout.addWidget(self.filter_edit)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)

        self._sections_container = QWidget()
        self._sections_layout = QVBoxLayout(self._sections_container)
        self._sections_layout.setContentsMargins(0, 0, 0, 0)
        self._sections_layout.setSpacing(4)
        self._sections_layout.addStretch(1)
        self._scroll.setWidget(self._sections_container)

        content_layout.addWidget(self._scroll, 1)
        layout.addWidget(self._content, 1)
        # Espaciador final: con el contenido oculto no queda ningún elemento
        # que estire, y un `QVBoxLayout` en ese caso **centra** el bloque —
        # por eso la flecha de desplegar aparecía flotando a media altura de
        # la franja plegada. Con el contenido visible no se lleva nada,
        # porque el factor de estiramiento de `_content` tiene prioridad.
        layout.addStretch(0)

        self.retranslate()

    def retranslate(self) -> None:
        """Rehace los textos fijos al cambiar de idioma (ver `Retranslates`).

        El tooltip de la flecha depende de si está plegada, así que lo pone
        `set_collapsed`, que ya conoce ese estado; aquí solo se le pide que
        lo vuelva a aplicar sin cambiar nada.
        """
        self.filter_edit.setPlaceholderText(self.tr("Filter devices…"))
        self._scroll.setToolTip(
            self.tr("Drag a device onto a controller in the graph to connect it.")
        )
        self._collapse_button.setToolTip(
            self.tr("Expand the device palette")
            if self._collapsed
            else self.tr("Collapse the device palette")
        )

    def _toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        """Pliega o despliega el cuerpo de la paleta, dejando la flecha visible.

        Plegada se fija el ancho a la franja: el `QSplitter` reparte según
        el `sizeHint` de cada lado, y sin fijarlo dejaba un hueco de aire
        entre el grafo y la flecha en vez de una franja pegada al borde.
        """
        self._collapsed = collapsed
        self._content.setVisible(not collapsed)
        if collapsed:
            self.setFixedWidth(style.DOCK_COLLAPSED_WIDTH)
        else:
            self.setMinimumWidth(style.DOCK_COLLAPSED_WIDTH)
            self.setMaximumWidth(style.WIDGET_SIZE_MAX)
        self._collapse_button.setText(
            _ARROW_EXPAND if collapsed else _ARROW_COLLAPSE
        )
        self._collapse_button.setToolTip(
            self.tr("Expand the device palette")
            if collapsed
            else self.tr("Collapse the device palette")
        )
        self.collapseToggled.emit(collapsed)

    def set_options(self, options: List[BindingOption]) -> None:
        """Reparte `options` en un desplegable por grupo (`binding_groups`)."""
        by_group: Dict[str, List[BindingOption]] = defaultdict(list)
        for option in options:
            by_group[binding_groups.group_for_subsystem(option.subsystem)].append(
                option
            )

        for group_key, group_options in by_group.items():
            self._section_for(group_key).set_options(group_options)

        self._apply_filter(self.filter_edit.text())

    def _section_for(self, group_key: str) -> "_CollapsibleSection":
        """Sección del grupo, creándola en su sitio del orden curado si hace falta.

        Los buses llegan de uno en uno según responde cada worker
        (`VisualizerTab._on_options_ready`), así que sin esto el orden visual
        dependería de qué bus respondiera antes en vez del `GROUP_ORDER`
        fijo: se busca el primer grupo ya creado que vaya *después* de este
        en el orden curado, y se inserta justo delante de él.
        """
        section = self._sections.get(group_key)
        if section is not None:
            return section

        section = _CollapsibleSection(group_key)
        section.list_widget.dragStarted.connect(self.dragStarted)
        section.list_widget.dragFinished.connect(self.dragFinished)
        self._sections[group_key] = section

        later = binding_groups.GROUP_ORDER[
            binding_groups.GROUP_ORDER.index(group_key) + 1 :
        ]
        before = next(
            (self._sections[key] for key in later if key in self._sections), None
        )
        index = (
            self._sections_layout.indexOf(before)
            if before is not None
            else self._sections_layout.count() - 1
        )
        self._sections_layout.insertWidget(index, section)
        return section

    def _apply_filter(self, needle: str) -> None:
        """Filtra dentro de cada sección y oculta las que se queden sin nada."""
        needle = needle.strip().lower()
        for section in self._sections.values():
            section.apply_filter(needle)
