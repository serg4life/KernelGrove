"""Vista de grafo del árbol de device tree.

Cada nodo es una **ficha** —cabecera con su nombre y cuerpo con sus
propiedades— y las aristas reproducen la jerarquía padre/hijo. Las
inclusiones (`#include`, `/include/`) aparecen como nodos aparte, porque no son
nodos del árbol sino paquetes de contenido: al abrirlos se despliega el
fichero que traen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

from PySide6.QtCore import QCoreApplication, QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QMenu,
)

from kernelgrove.api import DeviceTreeNode, PeripheralSlot, ResolvedInclude
from kernelgrove.gui import style


# Los items del grafo son `QGraphicsItem`, no `QObject`, y `build_graph` es
# una función suelta: ninguno tiene `self.tr()`. Sus textos pasan por
# `QCoreApplication.translate` con el contexto escrito a mano —el mismo que
# usaría `TreeGraphView.tr()`, para que todo el módulo quede junto— y sin
# envoltorio intermedio, que es lo que `lupdate` necesita para extraerlos
# (mismo motivo que en `gui/messages.py`).
_CONTEXT = "TreeGraphView"

# Periféricos integrados en el SoC que se muestran sueltos aunque no tengan
# nada conectado dentro (a diferencia del resto, que solo cuelgan del círculo
# central con `status` propio y al menos un hijo): ethernet/can/uart/serial
# son casi siempre nodos hoja, y quedarían empaquetados para siempre si se
# exigiera lo mismo que a un MFD. Mismo criterio de nombre que
# `soc_loader._bus_for_node` (prefijo antes de `@`).
HOISTED_LEAF_PREFIXES = {"ethernet", "can", "uart", "serial"}

# Medidas y colores viven en `gui/style.py`, no aquí — esto son solo los
# nombres cortos que usa el resto del fichero, para no reescribir cada
# referencia como `style.GRAPH_...`.
NODE_WIDTH = style.GRAPH_NODE_WIDTH
HEADER_HEIGHT = style.GRAPH_NODE_HEADER_HEIGHT
ROW_HEIGHT = style.GRAPH_NODE_ROW_HEIGHT
ROW_PADDING = style.GRAPH_NODE_ROW_PADDING
PADDING_X = style.GRAPH_NODE_PADDING_X
MAX_ROWS = style.GRAPH_NODE_MAX_ROWS
# El redondeo de la ficha **no** se copia aquí: lo pone la piel activa
# (`style.GRAPH_NODE_CORNER_RADIUS` sale de `theme.RADIUS_ITEM`) y cambiar
# de piel en caliente tiene que llegar hasta el grafo, así que se lee al
# pintar y no al importar el módulo.
HORIZONTAL_GAP = style.GRAPH_HORIZONTAL_GAP  # fichas sin solapar
VERTICAL_GAP = style.GRAPH_VERTICAL_GAP

# Límites del zoom manual (rueda del ratón). Sin ellos, alejar del todo reduce
# los nodos a menos de un píxel y el grafo se pierde de vista; acercar del
# todo tiene el mismo problema al revés. `fit()` no pasa por aquí -usa
# `fitInView` directamente-, así que un grafo grande se sigue viendo entero al
# ajustar aunque su zoom natural quede por debajo de `MIN_ZOOM`.
VERTICAL_EDGE_GAP = style.GRAPH_VERTICAL_EDGE_GAP
MIN_ZOOM = style.GRAPH_MIN_ZOOM
MAX_ZOOM = style.GRAPH_MAX_ZOOM


# Borde de un nodo conectado desde el visualizador (no existe aún en el
# árbol real) o de uno plegado que esconde algo así por debajo: morado
# dioxazina (`style.COLOR_GENERATED_BRIGHT`), distinto del amarillo de los
# avisos de severidad WARNING con el que se confundía a simple vista — ver
# también `ADDED_LINE_COLOR` en `dts_editor.py`, la misma idea en su fondo.
# Borde de un nodo mientras se arrastra sobre él algo soltable válido.


@dataclass
class GraphNode:
    """Un nodo del grafo, ya sea del árbol o una inclusión."""

    label: str
    detail: str = ""
    children: List["GraphNode"] = None
    include: Optional[ResolvedInclude] = None
    line: Optional[int] = None
    is_root: bool = False
    is_controller: bool = False
    # Un SoC completo pasa de 150 nodos: dibujarlos todos deja los círculos en
    # unos pocos píxeles. Se parte plegado y se despliega al hacer clic.
    collapsed: bool = False
    # Solo lo usa la raíz: plegada representa "la placa" (lo que se ve desde
    # fuera), desplegada pasa a etiquetarse como "el SoC" (lo que hay dentro
    # de la placa), ver `build_graph`.
    collapsed_label: Optional[str] = None
    # Solo lo usan los bloques: el texto corto con el que se dibujan dentro
    # de la ficha del SoC, ya numerado si comparte nombre con otros
    # (`i2c0`, `i2c1`). Lo pone `number_blocks`; `label` sigue siendo el
    # nombre completo del nodo, que es lo que enseña el tooltip.
    short_label: Optional[str] = None
    # Ruta del `DeviceTreeNode` de origen, para emparejar con el
    # `PeripheralSlot` de la sesión de conexión (ver `build_graph`).
    path: Optional[str] = None
    # Nombre del bloque del SoC del que cuelga, si cuelga de uno. Lo enseña
    # el tooltip de la ficha: con veinte bloques en la ficha central, saber
    # de cuál sale una arista mirándola es imposible, y esta es la respuesta
    # sin tener que pasar el ratón por el otro extremo (ver `highlight_link`).
    controller_label: Optional[str] = None
    # Etiqueta DTS del nodo (`i2c0` en `i2c0: i2c@ff030000`), si tiene. La usa
    # "ver en el editor DTS" para encontrar el `&i2c0 { … }` con el que el
    # documento abierto lo reabre, que suele ser lo que se quiere ver en una
    # placa. No se dibuja en ningún sitio.
    dt_label: Optional[str] = None
    # Propiedades a enseñar en el cuerpo de la ficha, ya en texto y en el
    # orden en que están escritas. Las pone `build_graph` desde el nodo real;
    # la ficha solo dibuja las `MAX_ROWS` primeras.
    properties: List[tuple] = None
    # Slot sobre el que se puede soltar un compatible arrastrado: un
    # controlador del SoC, o un dispositivo ya conectado que a su vez acepta
    # más (un mux, un MFD). None si el nodo no admite conexiones.
    slot: Optional[PeripheralSlot] = None
    # El slot que este nodo **es**, cuando viene de la sesión de conexión.
    # Va aparte de `slot` porque ese responde a otra pregunta -«¿se le puede
    # soltar algo encima?»- y solo lo tienen los que aceptan hijos: mientras
    # los dos fueron el mismo campo, un dispositivo corriente (una EEPROM, que
    # no aloja nada) se quedaba sin él y no había forma de quitarlo del grafo.
    connected_slot: Optional[PeripheralSlot] = None
    # True si el nodo viene de la sesión de conexión (Generador/Visualizador),
    # no del árbol real todavía.
    generated: bool = False
    # True si lo escribe el **documento abierto** y por tanto se puede
    # borrar de él: `line` es entonces una línea de este fuente. Lo que
    # llega por un `#include` -el SoC bajo una placa- no lo es: está escrito
    # en otro fichero, y borrarlo desde aquí sería editar algo que no se
    # está mirando (ver `build_graph`).
    editable: bool = False
    # Solo lo usa la raíz: cuántos nodos se han dejado fuera por estar
    # apagados. Un `.dtsi` de SoC trae apagado casi todo, y un grafo con una
    # sola ficha y sin explicación se lee como una avería, no como «esta
    # placa no lleva nada de eso encendido».
    hidden_disabled: int = 0
    # True si este nodo o alguno de sus descendientes es `generated`, aunque
    # esté plegado — lo calcula `build_graph` tras montar el árbol completo
    # (con el solapado ya aplicado) y lo usa `_NodeItem` para marcar en
    # amarillo un nodo plegado que esconde algo conectado.
    has_generated_descendant: bool = False
    # Si el `status` del nodo de origen lo deja encendido (o no declara
    # `status`, que por la especificación equivale a encendido). Solo lo
    # pinta `_BlockChip` -verde si está a True, sin relleno si no-; el resto
    # de fichas ni lo consultan, porque un nodo apagado que no es "propio
    # del SoC" ni siquiera llega a construirse (ver `is_disabled` en
    # `collect_hoisted`).
    enabled: bool = True
    # Solo lo usa la raíz: los controladores propios del SoC
    # (`DeviceTreeNode.soc_defined`), que se dibujan como bloques de color
    # dentro de su propia ficha en vez de colgar de ella con una arista -eso
    # sigue siendo `children`, para lo que no viene del `.dtsi` del SoC sino
    # de un chip conectado. Cada bloque conserva su propio subárbol
    # (`children`): lo que cuelgue de él -un dispositivo real, o uno de la
    # sesión de conexión- se sigue dibujando como una ficha aparte, con la
    # arista saliendo del bloque en vez de la ficha del SoC.
    blocks: List["GraphNode"] = None

    def __post_init__(self):
        """Garantiza que las listas existan."""
        if self.children is None:
            self.children = []
        if self.properties is None:
            self.properties = []
        if self.blocks is None:
            self.blocks = []

    @property
    def visible_children(self) -> List["GraphNode"]:
        """Hijos que deben dibujarse (ninguno si el nodo está plegado)."""
        return [] if self.collapsed else self.children

    @property
    def caption(self) -> str:
        """Etiqueta a dibujar, que en la raíz depende de si está plegada."""
        if self.is_root and self.collapsed and self.collapsed_label:
            return self.collapsed_label
        return self.label

    @property
    def rows(self) -> List[tuple]:
        """Propiedades que caben en el cuerpo de la ficha."""
        return self.properties[:MAX_ROWS]

    @property
    def color(self) -> str:
        """Color de la cabecera según lo que representa el nodo."""
        if self.include is not None:
            if self.include.found:
                return style.GRAPH_COLOR_INCLUDE_OK
            return style.GRAPH_COLOR_INCLUDE_MISSING
        if self.is_root:
            return style.GRAPH_COLOR_ROOT
        if self.is_controller:
            return style.GRAPH_COLOR_CONTROLLER
        return style.GRAPH_COLOR_NODE


def _collapse_key(node: GraphNode) -> object:
    """Identidad estable de `node` entre reconstrucciones del grafo.

    `path` identifica a un nodo del árbol real; uno generado no tiene path
    propio, así que se usa la identidad de su `PeripheralSlot` (el mismo
    objeto sobrevive a cada `connect_to_slot`/`disconnect_by_slot`). Sin
    ninguno de los dos (el paquete de includes, las ramas recortadas...) se
    usa la etiqueta: no son nodos que el usuario suela querer conservar
    plegados/desplegados entre reconstrucciones, así que una colisión ahí es
    inofensiva.
    """
    if node.path:
        return node.path
    slot = node.connected_slot or node.slot
    if slot is not None:
        return id(slot)
    return node.label


def _copy_collapsed_state(old_root: GraphNode, new_root: GraphNode) -> None:
    """Traslada el plegado de `old_root` a `new_root`, nodo a nodo por clave.

    Reconstruir el grafo (tras conectar/desconectar algo, o al reanalizar el
    documento) no debe replegar lo que el usuario ya había desplegado. Un
    nodo nuevo (no existía en `old_root`) conserva el plegado por profundidad
    que ya trae de `build_graph`.
    """
    previous: Dict[object, bool] = {}

    def collect(node: GraphNode) -> None:
        previous[_collapse_key(node)] = node.collapsed
        for child in node.children:
            collect(child)
        # Un bloque no pliega por su cuenta, pero lo que cuelga de él sí -un
        # mux conectado a un i2c propio del SoC sigue siendo una ficha con
        # su propia insignia «+»/«−».
        for block in node.blocks:
            for child in block.children:
                collect(child)

    collect(old_root)

    def apply(node: GraphNode) -> None:
        key = _collapse_key(node)
        if key in previous:
            node.collapsed = previous[key]
        for child in node.children:
            apply(child)
        for block in node.blocks:
            for child in block.children:
                apply(child)

    apply(new_root)


def _mark_generated_descendants(node: GraphNode) -> bool:
    """Post-orden: marca `has_generated_descendant` y lo devuelve.

    Tiene que mirar `children` entero, no `visible_children`: el aviso es
    precisamente para lo que el plegado esconde. Un dispositivo conectado a
    un bloque (un controlador propio del SoC) cuenta igual: cuelga de
    `block.children`, no de `node.children`, pero sigue siendo algo que la
    placa plegada esconde.
    """
    found = node.generated
    for child in node.children:
        if _mark_generated_descendants(child):
            found = True
    for block in node.blocks:
        for child in block.children:
            if _mark_generated_descendants(child):
                found = True
    node.has_generated_descendant = found
    return found


# Las propiedades que van primero en la ficha, en este orden. Son las que
# identifican al nodo -qué es, dónde está, si está activo-, y por eso son
# las que caben en las `MAX_ROWS` filas que se dibujan. El resto va detrás
# por orden alfabético.
#
# El orden importa porque la ficha enseña unas pocas: por el orden en que
# están escritas en el fuente, cada nodo ponía las suyas donde le tocaba y
# `reg` salía en una fila distinta en cada ficha, así que no se podía
# comparar dos nodos de un vistazo ni saber si a uno le faltaba algo. Con un
# orden fijo, la misma propiedad cae siempre en la misma altura.
PROPERTY_ORDER = ("compatible", "reg", "status")


def property_rows(properties: Dict[str, object]) -> List[tuple]:
    """Propiedades de un nodo tal y como se leen en la ficha, en orden fijo.

    Lo que guarda el analizador es el texto DTS crudo (`<1>`, `"okay"`,
    `True` para una propiedad bandera). En la ficha se enseña el valor
    pelado —sin los `<>` ni las comillas— porque lo que aporta ahí es el
    dato, no su sintaxis; para ver el texto exacto está el editor, que es
    donde se edita. Una bandera se queda sin valor, que es justo lo que es.

    El orden es el de `PROPERTY_ORDER` y después alfabético, no el del
    fuente: ver ahí arriba por qué.
    """

    def orden(name: str) -> tuple:
        try:
            return (0, PROPERTY_ORDER.index(name), "")
        except ValueError:
            return (1, 0, name)

    filas: List[tuple] = []
    for name in sorted(properties, key=orden):
        value = properties[name]
        if value is True:
            filas.append((name, ""))
            continue
        text = str(value).strip()
        if text.startswith("<") and text.endswith(">"):
            text = text[1:-1].strip()
        filas.append((name, text.replace('"', "")))
    return filas


def hardware_rows(hardware: Optional[dict]) -> List[tuple]:
    """El resumen de hardware como filas de ficha, saltándose lo que no hay.

    Recibe lo que devuelve `api.extract_hardware`. Una fila con «—» en la
    ficha central ocuparía sitio para decir que no se sabe; en el catálogo
    sí se enseña, porque allí las columnas están alineadas entre filas y un
    hueco se lee como parte de la tabla.
    """
    if not hardware:
        return []
    filas = []
    for name, value in (
        (QCoreApplication.translate(_CONTEXT, "architecture"), hardware.get("arch")),
        (QCoreApplication.translate(_CONTEXT, "cores"), hardware.get("cores")),
        (
            QCoreApplication.translate(_CONTEXT, "ram"),
            _bytes_label(hardware.get("ram")),
        ),
        (
            QCoreApplication.translate(_CONTEXT, "clock"),
            _hertz_label(hardware.get("clock")),
        ),
    ):
        if value:
            filas.append((name, str(value)))
    return filas


def _bytes_label(value: Optional[int]) -> str:
    """Bytes en su unidad, o cadena vacía si no se sabe."""
    if not value:
        return ""
    for unidad, factor in (("GB", 1 << 30), ("MB", 1 << 20)):
        if value >= factor:
            cantidad = value / factor
            entero = int(cantidad)
            if cantidad == entero:
                return f"{entero} {unidad}"
            return f"{cantidad:.1f} {unidad}"
    return f"{value} B"


def _hertz_label(value: Optional[int]) -> str:
    """Frecuencia en MHz o GHz, o cadena vacía."""
    if not value:
        return ""
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f} GHz".replace(".00 ", " ")
    return f"{round(value / 1_000_000)} MHz"


SOC_NODE_WIDTH = style.GRAPH_SOC_NODE_WIDTH
BLOCK_HEIGHT = style.GRAPH_BLOCK_HEIGHT
BLOCK_GAP = style.GRAPH_BLOCK_GAP
BLOCK_COLUMNS = style.GRAPH_BLOCK_COLUMNS


def block_caption(label: str) -> str:
    """Lo que se lee dentro de un bloque: el nombre del nodo sin su dirección.

    `spi@e0006000` se dibuja como `spi`. La dirección de unidad no cabe en un
    bloque de sesenta píxeles y no es lo que se busca de un vistazo -qué
    lleva el SoC-, así que se queda en el tooltip junto con el resto. Cuando
    varios bloques comparten nombre, `number_blocks` les añade su índice
    (`i2c0`, `i2c1`) para que sigan distinguiéndose.
    """
    return label.split("@", 1)[0]


def address_key(path: Optional[str]) -> tuple:
    """Direcciones de unidad de un path DT, de la raíz hacia abajo.

    `/ocp/target-module@48022000/serial@0` da `(0x48022000, 0)`. Es la clave
    por la que se ordenan los controladores del mismo tipo para numerarlos,
    y va por el path entero y no solo por el último tramo a propósito: en la
    familia OMAP de TI cada periférico vive dentro de un `target-module@…` y
    se llama `serial@0`/`i2c@0` -la dirección que los distingue es la del
    módulo que los envuelve, no la suya, que es siempre la misma-.

    Un tramo sin dirección ordena antes que uno con ella (`-1`), y uno cuya
    dirección no sea hexadecimal se trata igual en vez de reventar: numerar
    es cosmético y no puede tumbar el dibujado del grafo.
    """
    key = []
    for segment in (path or "").split("/"):
        if not segment:
            continue
        _, _, address = segment.partition("@")
        try:
            key.append(int(address, 16) if address else -1)
        except ValueError:
            key.append(-1)
    return tuple(key)


def number_blocks(
    blocks: List[GraphNode], universe: Optional[Sequence[tuple]] = None
) -> None:
    """Da a cada bloque el texto con el que se dibuja, numerando los repetidos.

    Un SoC lleva varios controladores del mismo tipo, y con la dirección
    fuera del bloque (ver `block_caption`) se leían todos igual: tres `i2c`
    seguidos no dicen cuál es cuál. Los que comparten nombre se ordenan por
    su dirección de unidad -que es la base de su `reg`- y se numeran desde
    cero, que es justo como los nombra el fabricante.

    `universe` son **todos** los controladores del SoC como `(nombre, path)`,
    incluidos los apagados que no se dibujan, y es lo que hace que el número
    sea el del hardware y no el de la lista. Un am335x trae tres `i2c`
    (`0x44e0b000`, `0x4802a000`, `0x4819c000`) y una placa suele encender
    solo el primero y el tercero: numerando por lo visible salían `i2c0` e
    `i2c1`, cuando el fabricante llama al segundo I2C2. Sin `universe` se
    numera por los bloques dados, que es lo correcto cuando son todos.

    Al que no comparte nombre con nadie no se le añade número: no hay de qué
    distinguirlo.
    """
    if universe is None:
        universe = [(block_caption(block.label), block.path) for block in blocks]

    grupos: Dict[str, List[Optional[str]]] = {}
    for nombre, path in universe:
        grupos.setdefault(nombre, []).append(path)
    for paths in grupos.values():
        paths.sort(key=address_key)

    for block in blocks:
        nombre = block_caption(block.label)
        paths = grupos.get(nombre, [])
        if len(paths) <= 1 or block.path not in paths:
            block.short_label = nombre
            continue
        block.short_label = f"{nombre}{paths.index(block.path)}"


def _blocks_grid_height(count: int) -> float:
    """Alto que añade a la ficha la rejilla de `count` bloques de controlador."""
    if not count:
        return 0.0
    filas = -(-count // BLOCK_COLUMNS)  # división entera hacia arriba
    return filas * BLOCK_HEIGHT + (filas + 1) * BLOCK_GAP


def _shows_blocks(node: GraphNode) -> bool:
    """Si la ficha de `node` tiene que hacer sitio a sus bloques ahora mismo.

    Plegada, la ficha del SoC representa la placa vista desde fuera y no
    enseña lo que lleva dentro; reservar el alto de la rejilla igualmente
    hacía que plegar no encogiera nada -la ficha ocupaba lo mismo abierta
    que cerrada, que es justo lo que plegar tiene que evitar-.
    """
    return bool(node.is_root and node.blocks and not node.collapsed)


def node_size(node: GraphNode) -> QRectF:
    """Rectángulo de la ficha de `node`, centrado en su posición.

    El alto lo pone el número de propiedades que enseña más, cuando se ven,
    la rejilla de `node.blocks` -los controladores propios del SoC, dibujados
    dentro en vez de colgar aparte (ver `build_graph`)-: una ficha sin
    ninguna cosa de las dos se queda en su cabecera, que es lo que hace que
    un árbol de nodos vacíos siga siendo compacto. El ancho es fijo, y el de
    la ficha del SoC mayor que el del resto: es la única que lleva bloques
    dentro. Lo usan tanto `_NodeItem` (para su geometría) como `_draw` (para
    saber de dónde a dónde va cada arista), y por eso vive fuera del item.
    """
    filas = len(node.rows)
    alto = HEADER_HEIGHT + (filas * ROW_HEIGHT + 2 * ROW_PADDING if filas else 0)
    if _shows_blocks(node):
        alto += _blocks_grid_height(len(node.blocks))
    ancho = SOC_NODE_WIDTH if node.is_root else NODE_WIDTH
    return QRectF(-ancho / 2, -alto / 2, ancho, alto)


def block_rects(node: GraphNode) -> List[QRectF]:
    """Rectángulo local de cada bloque de `node.blocks`, en fila-columna.

    Mismo sistema de coordenadas que `node_size` -centrado en el origen de
    la ficha-, así que sumarle la posición de la ficha (`positions[id(node)]`
    en `_draw`) da directamente el rectángulo en la escena. Van justo debajo
    de las propiedades, en tantas filas como hagan falta, y el ancho sale de
    repartir el de la ficha entre las columnas: los bloques son los
    inquilinos de esa ficha y tienen que llenarla.
    """
    if not _shows_blocks(node):
        return []
    rect = node_size(node)
    filas = len(node.rows)
    top = (
        rect.top()
        + HEADER_HEIGHT
        + (filas * ROW_HEIGHT + 2 * ROW_PADDING if filas else 0)
        + BLOCK_GAP
    )
    width = (rect.width() - (BLOCK_COLUMNS + 1) * BLOCK_GAP) / BLOCK_COLUMNS
    rects = []
    for index in range(len(node.blocks)):
        row, col = divmod(index, BLOCK_COLUMNS)
        x = rect.left() + BLOCK_GAP + col * (width + BLOCK_GAP)
        y = top + row * (BLOCK_HEIGHT + BLOCK_GAP)
        rects.append(QRectF(x, y, width, BLOCK_HEIGHT))
    return rects


TOGGLE_RADIUS = style.GRAPH_TOGGLE_BADGE_RADIUS
# Grosor del borde del nodo seleccionado: algo más que cualquier otro
# estado, para que se distinga aunque el nodo ya tuviera borde propio.
SELECTED_PEN_WIDTH = 2.4


class _ToggleBadge(QGraphicsEllipseItem):
    """Indicador «+»/«−» que pliega o despliega un nodo.

    Antes lo hacía un clic normal sobre el círculo, pero eso interfería con
    el doble clic (el primer clic ya replegaba/desplegaba y recolocaba el
    grafo, así que el segundo clic del gesto caía sobre otro sitio y el
    doble clic nunca llegaba a completarse -el caso más notorio era el SoC,
    cuyo doble clic abre su panel de propiedades-). Al aislar el pliegue en
    esta insignia, el círculo del nodo queda libre para el doble clic.
    """

    def __init__(self, node: GraphNode, view: "TreeGraphView", parent: QGraphicsItem):
        """Coloca la insignia en la esquina del rectángulo padre."""
        super().__init__(
            -TOGGLE_RADIUS, -TOGGLE_RADIUS, TOGGLE_RADIUS * 2, TOGGLE_RADIUS * 2, parent
        )
        self.node = node
        self._view = view
        # Esquina inferior derecha de la ficha, montada sobre el borde: es
        # el sitio donde no tapa ni el nombre ni ninguna fila.
        rect = node_size(node)
        self.setPos(rect.right() - TOGGLE_RADIUS, rect.bottom())
        self.setZValue(1)
        # Del mismo material que el nodo, no un disco blanco encima: la
        # insignia informa de que hay algo plegado, no compite con el nodo.
        self.setBrush(QBrush(QColor(style.GRAPH_TOGGLE_BADGE_BG)))
        self.setPen(QPen(QColor(style.GRAPH_TOGGLE_BADGE_BORDER), 1))
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(
            QCoreApplication.translate("TreeGraphView", "Collapse")
            if not node.collapsed
            else QCoreApplication.translate("TreeGraphView", "Expand")
        )

        self._label = QGraphicsSimpleTextItem(self)
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        self._label.setFont(font)
        self._label.setBrush(QBrush(QColor(style.GRAPH_TOGGLE_BADGE_TEXT)))
        text = "+" if node.collapsed else "−"
        self._label.setText(text)
        bounds = self._label.boundingRect()
        self._label.setPos(-bounds.width() / 2, -bounds.height() / 2 - 1)

    def mousePressEvent(self, event) -> None:
        """Pliega o despliega el nodo, sin propagar el clic al círculo padre."""
        self.node.collapsed = not self.node.collapsed
        self._view.redraw()
        event.accept()


def _node_menu_actions(menu: QMenu, node: GraphNode) -> tuple:
    """Añade a `menu` lo que se puede hacer con un nodo, sea ficha o bloque.

    Las dos cosas son el mismo nodo dibujado de otra forma, así que ofrecen
    lo mismo; solo la ficha añade además «Desconectar», que es suyo. Un nodo
    sin `path` -el paquete de includes, una rama recortada- no está escrito
    en ningún sitio y no se le ofrece nada.
    """
    if node.path is None:
        return None, None
    inspect_action = menu.addAction(
        QCoreApplication.translate("TreeGraphView", "Open inspector")
    )
    source_action = menu.addAction(
        QCoreApplication.translate("TreeGraphView", "View on DTS editor")
    )
    return inspect_action, source_action


def _run_node_action(view, node: GraphNode, chosen, inspect_action, source_action):
    """Emite la señal que toque según lo elegido en `_node_menu_actions`."""
    if chosen is None:
        return
    if chosen is inspect_action:
        view.nodeInspectRequested.emit(node.path)
    elif chosen is source_action:
        view.nodeSourceRequested.emit(node.path, node.dt_label or "")


class _NodeItem(QGraphicsEllipseItem):
    """Ficha de un nodo: cabecera con su nombre y cuerpo con sus propiedades.

    Hereda de `QGraphicsEllipseItem` solo para reutilizar su manejo de
    `rect`/`brush`/`pen`, selección y hover — `paint`/`shape` se sobrescriben
    para dibujar y recortar la ficha en vez de la elipse por defecto, así que
    el rectángulo entero (incluidas las esquinas) responde a clics, hover y
    soltar un arrastre, no solo la elipse inscrita.

    El nombre va **dentro**, en la cabecera, y no debajo de la forma como
    cuando el nodo era un círculo: con la etiqueta fuera había que dejar
    aire entre nodos solo para que dos etiquetas no se pisaran, y la ficha
    ya reserva ese sitio. El color semántico (qué es el nodo: SoC,
    controlador, inclusión…) se queda en la cabecera y no tiñe el cuerpo,
    que es donde se leen las propiedades.
    """

    def __init__(self, node: GraphNode, view: "TreeGraphView"):
        """Dibuja la ficha del nodo y guarda a qué elemento corresponde."""
        super().__init__(node_size(node))
        self.node = node
        self._view = view

        self.setBrush(QBrush(QColor(node.color)))
        # El borde dice el estado del nodo, y la cabecera qué es. De más
        # específico a más general: turquesa discontinuo = el nodo viene de
        # la sesión de edición y no existe aún en el `.dts`
        # (`GraphNode.generated`); turquesa continuo = plegado, y algo de lo
        # que esconde sí viene de ahí; claro = plegado, hay contenido
        # dentro; apagado = nada que señalar. El morado de marca no aparece
        # aquí: se reserva para la selección (ver `paint`).
        collapsed = node.collapsed and bool(node.children)
        if node.generated:
            self._base_pen = QPen(
                QColor(style.COLOR_GENERATED_BRIGHT), 1.6, Qt.DashLine
            )
        elif collapsed and node.has_generated_descendant:
            self._base_pen = QPen(QColor(style.COLOR_GENERATED_BRIGHT), 1.6)
        elif collapsed:
            self._base_pen = QPen(QColor(style.GRAPH_NODE_COLLAPSED_BORDER), 1.6)
        else:
            self._base_pen = QPen(QColor(style.GRAPH_NODE_DEFAULT_BORDER), 1.2)
        self.setPen(self._base_pen)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        # Movible a mano: el reparto automático (`_layout`) es un punto de
        # partida, no una imposición. Qt mueve de una vez todo lo que esté
        # seleccionado, así que el arrastre en grupo sale gratis con esto y
        # con la selección por recuadro de la vista.
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setCursor(Qt.SizeAllCursor)
        self.setAcceptHoverEvents(True)
        self.setToolTip(self._tooltip())
        self.setAcceptDrops(node.slot is not None)

        if node.children or (node.is_root and node.blocks):
            _ToggleBadge(node, view, self)

    def itemChange(self, change, value):
        """Avisa a la vista de cada desplazamiento, para recolocar las aristas.

        Solo cuando lo mueve el usuario: durante `_render` la vista misma
        coloca cada ficha y no debe apuntarlo como posición manual (ver
        `TreeGraphView.node_moved`).
        """
        if change == QGraphicsItem.ItemPositionHasChanged:
            self._view.node_moved(self)
        return super().itemChange(change, value)

    def _card_path(self) -> QPainterPath:
        """Contorno de la ficha, con el redondeo de la piel activa."""
        radius = style.GRAPH_NODE_CORNER_RADIUS
        path = QPainterPath()
        path.addRoundedRect(self.rect(), radius, radius)
        return path

    def shape(self) -> QPainterPath:
        """Recorta la ficha entera, no la elipse por defecto."""
        return self._card_path()

    def boundingRect(self) -> QRectF:
        """La ficha más el margen de los puntos de conexión.

        Van justo **sobre** el borde, o sea medio fuera del rectángulo: sin
        ensanchar la caja, Qt repinta solo el interior y al desplazarse
        quedan medias lunas cortadas por la escena.
        """
        margen = style.GRAPH_PORT_RADIUS + 2
        return self.rect().adjusted(-margen, -margen, margen, margen)

    def paint(self, painter, option, widget=None) -> None:
        """Dibuja la ficha: cuerpo, cabecera, textos, borde y puntos de conexión.

        El nodo seleccionado se marca con el acento de marca. El item ya era
        seleccionable (`ItemIsSelectable`), pero nadie lo dibujaba: se podía
        pulsar un nodo y no pasaba nada visible, que es la peor versión de
        una interacción — la que el usuario cree que no ha funcionado.

        El orden importa: el cuerpo, la cabecera recortada por el contorno
        (para que herede su redondeo sin tener que dibujar dos esquinas a
        mano), los textos, y el borde **el último**, encima de todo, porque
        si no la cabecera se le come el píxel de arriba.
        """
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        card = self._card_path()
        seleccionado = self.isSelected()

        painter.fillPath(card, QBrush(QColor(style.GRAPH_CARD_BG)))

        header = QRectF(rect.left(), rect.top(), rect.width(), HEADER_HEIGHT)
        painter.save()
        painter.setClipPath(card)
        painter.fillRect(header, self.brush())
        if self.node.rows:
            painter.setPen(QPen(QColor(style.GRAPH_NODE_DEFAULT_BORDER), 1))
            painter.drawLine(header.bottomLeft(), header.bottomRight())
        painter.restore()

        self._paint_texts(painter, rect, header)

        painter.setBrush(Qt.NoBrush)
        painter.setPen(
            QPen(QColor(style.GRAPH_NODE_SELECTED_BORDER), SELECTED_PEN_WIDTH)
            if seleccionado
            else self.pen()
        )
        painter.drawPath(card)

        self._paint_ports(painter, rect, seleccionado)

    def _paint_texts(self, painter, rect: QRectF, header: QRectF) -> None:
        """El nombre en la cabecera y las propiedades en el cuerpo.

        Los dos textos se recortan con puntos suspensivos en vez de
        desbordar la ficha: el ancho es fijo, y un `compatible` largo
        saliéndose por los lados destroza la lectura del grafo entero.
        """
        nombre = QFont()
        nombre.setPointSizeF(style.GRAPH_LABEL_POINT_SIZE)
        nombre.setBold(True)
        painter.setFont(nombre)
        painter.setPen(QPen(QColor(style.GRAPH_COLOR_TEXT)))

        metrics = QFontMetricsF(nombre)
        contador = ""
        total = len(self.node.children) + (
            len(self.node.blocks) if self.node.is_root else 0
        )
        if self.node.collapsed and total:
            contador = f"+{total}"
        ancho_contador = metrics.horizontalAdvance(contador) + 6 if contador else 0
        hueco = header.adjusted(PADDING_X, 0, -PADDING_X - ancho_contador, 0)
        painter.drawText(
            hueco,
            Qt.AlignVCenter | Qt.AlignLeft,
            metrics.elidedText(self.node.caption, Qt.ElideMiddle, hueco.width()),
        )
        if contador:
            painter.setPen(QPen(QColor(style.GRAPH_TOGGLE_BADGE_TEXT)))
            painter.drawText(
                header.adjusted(PADDING_X, 0, -PADDING_X, 0),
                Qt.AlignVCenter | Qt.AlignRight,
                contador,
            )

        filas = self.node.rows
        if not filas:
            return
        fila_font = QFont()
        fila_font.setPointSizeF(style.GRAPH_ROW_POINT_SIZE)
        painter.setFont(fila_font)
        fm = QFontMetricsF(fila_font)
        # La mitad para el nombre y la mitad para el valor: es el reparto
        # del diseño, y deja la columna de valores alineada de ficha a
        # ficha aunque los nombres midan cosas distintas.
        mitad = (rect.width() - 2 * PADDING_X) / 2
        y = rect.top() + HEADER_HEIGHT + ROW_PADDING
        for name, value in filas:
            izquierda = QRectF(rect.left() + PADDING_X, y, mitad, ROW_HEIGHT)
            derecha = QRectF(izquierda.right(), y, mitad, ROW_HEIGHT)
            painter.setPen(QPen(QColor(style.MUTED_TEXT_COLOR)))
            painter.drawText(
                izquierda,
                Qt.AlignVCenter | Qt.AlignLeft,
                fm.elidedText(name, Qt.ElideRight, mitad - 4),
            )
            painter.setPen(QPen(QColor(style.ACCENT_TEXT_COLOR)))
            painter.drawText(
                derecha,
                Qt.AlignVCenter | Qt.AlignRight,
                fm.elidedText(value, Qt.ElideRight, mitad),
            )
            y += ROW_HEIGHT

    def _paint_ports(self, painter, rect: QRectF, selected: bool) -> None:
        """Los puntos de conexión de la ficha, arriba y abajo.

        Arriba solo si el nodo cuelga de otro, y abajo solo si tiene hijos a
        la vista: un punto suelto sin arista que salga de él prometería una
        conexión que no existe.
        """
        radio = style.GRAPH_PORT_RADIUS
        color = QColor(
            style.GRAPH_NODE_SELECTED_BORDER if selected else style.GRAPH_COLOR_EDGE
        )
        painter.setPen(QPen(QColor(style.GRAPH_CARD_BG), 1.5))
        painter.setBrush(QBrush(color))
        if not self.node.is_root:
            painter.drawEllipse(QPointF(0, rect.top()), radio, radio)
        if self.node.visible_children:
            painter.drawEllipse(QPointF(0, rect.bottom()), radio, radio)

    def _tooltip(self) -> str:
        """Texto emergente con el detalle del nodo."""
        lines = [self.node.caption]
        if self.node.detail:
            lines.append(self.node.detail)
        if self.node.line:
            lines.append(
                QCoreApplication.translate("TreeGraphView", "Line {line}").format(
                    line=self.node.line
                )
            )
        if self.node.include is not None:
            lines.append(
                QCoreApplication.translate(
                    "TreeGraphView", "Double-click to open the included content"
                )
                if self.node.include.found
                else QCoreApplication.translate(
                    "TreeGraphView", "The included file cannot be found"
                )
            )
        if self.node.slot is not None:
            lines.append(
                QCoreApplication.translate(
                    "TreeGraphView",
                    "Drag a device from the palette here to connect it",
                )
            )
        if self.node.controller_label:
            lines.append(
                QCoreApplication.translate(
                    "TreeGraphView", "Connected to {controller}"
                ).format(controller=self.node.controller_label)
            )
        if self.node.generated:
            lines.append(
                QCoreApplication.translate(
                    "TreeGraphView",
                    "Connected from the editor, not in the .dts yet",
                )
            )
        return "\n".join(lines)

    def set_linked(self, active: bool) -> None:
        """Marca esta ficha como el otro extremo de la conexión señalada."""
        self.setPen(
            QPen(QColor(style.GRAPH_NODE_SELECTED_BORDER), SELECTED_PEN_WIDTH)
            if active
            else self._base_pen
        )

    def hoverEnterEvent(self, event) -> None:
        """Enciende la conexión con el bloque del SoC del que cuelga."""
        self._view.highlight_link(self.node, True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        """La apaga al salir."""
        self._view.highlight_link(self.node, False)
        super().hoverLeaveEvent(event)

    def set_glow(self, active: bool) -> None:
        """Enciende o apaga el halo morado de "aquí se puede soltar".

        Se dispara para TODOS los nodos válidos a la vez en cuanto se coge
        algo de la paleta (`TreeGraphView.highlight_drop_targets`), no solo
        el que está bajo el cursor en cada instante -ese ya tiene su propio
        aviso, el borde verde de `dragEnterEvent`-. Un
        `QGraphicsDropShadowEffect` con desplazamiento cero es la forma
        estándar de Qt de conseguir un resplandor uniforme alrededor de la
        forma en vez de una sombra proyectada a un lado.
        """
        if not active:
            self.setGraphicsEffect(None)
            return
        glow = QGraphicsDropShadowEffect()
        glow.setColor(QColor(style.GRAPH_DROP_TARGET_GLOW_COLOR))
        glow.setBlurRadius(style.GRAPH_DROP_TARGET_GLOW_RADIUS)
        glow.setOffset(0, 0)
        self.setGraphicsEffect(glow)

    def _is_valid_drop(self, event) -> bool:
        """Pregunta al validador de `TreeGraphView` si el arrastre es válido aquí."""
        if self.node.slot is None or not event.mimeData().hasText():
            return False
        validator = self._view.drop_validator
        return bool(validator and validator(self.node.slot, event.mimeData().text()))

    def dragEnterEvent(self, event) -> None:
        """Acepta el arrastre solo si el compatible es válido para este nodo."""
        if self._is_valid_drop(event):
            event.acceptProposedAction()
            self.setPen(QPen(QColor(style.COLOR_DROP_OK), 2))
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        """Mantiene aceptado el arrastre mientras siga siendo válido."""
        if self._is_valid_drop(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        """Restaura el borde original al salir del nodo sin soltar."""
        self.setPen(self._base_pen)

    def dropEvent(self, event) -> None:
        """Conecta el compatible soltado, si sigue siendo válido.

        `deviceDropped` dispara sincrónicamente `connect_to_slot` ->
        `slotStateChanged` -> un redibujado completo del grafo
        (`scene.clear()`), que destruye este mismo `_NodeItem` de Python
        mientras su propio `dropEvent` sigue en marcha — por eso no se toca
        `self` después de emitir; hacerlo (como antes, con
        `self.setPen(...)` al final) hacía petar con "objeto ya borrado".
        """
        if not self._is_valid_drop(event):
            event.ignore()
            self.setPen(self._base_pen)
            return
        event.acceptProposedAction()
        self._view.deviceDropped.emit(self.node.slot, event.mimeData().text())

    def contextMenuEvent(self, event) -> None:
        """Ofrece el Inspector, ver el nodo en el editor y, si aplica, desconectarlo.

        Las dos primeras solo se ofrecen si `path` existe: es lo que
        distingue un nodo real de un paquete de includes o de un hueco de
        conexión aún vacío, y ninguno de los dos está escrito en ningún
        fuente al que saltar.
        """
        # El menú actúa sobre la selección si este nodo forma parte de ella
        # -así «Desconectar» quita los cinco que se acaban de coger con el
        # recuadro, no solo aquel sobre el que se ha pulsado-; si no, solo
        # sobre él, que es lo que el clic derecho acaba de señalar.
        if not self.isSelected():
            self.scene().clearSelection()
            self.setSelected(True)
        seleccionados = self._view.selected_slots()
        borrables = self._view.selected_editable()

        menu = QMenu()
        inspect_action, source_action = _node_menu_actions(menu, self.node)
        disconnect_action = None
        if seleccionados:
            disconnect_action = menu.addAction(
                QCoreApplication.translate("TreeGraphView", "Disconnect")
                if len(seleccionados) == 1
                else QCoreApplication.translate(
                    "TreeGraphView", "Disconnect {count} devices"
                ).format(count=len(seleccionados))
            )
        # Borrar es del fuente, no del grafo, así que solo aparece sobre lo
        # que este documento escribe: un nodo del SoC llega por un
        # `#include` y vive en otro fichero.
        delete_action = None
        if borrables:
            delete_action = menu.addAction(
                QCoreApplication.translate("TreeGraphView", "Delete from source")
                if len(borrables) == 1
                else QCoreApplication.translate(
                    "TreeGraphView", "Delete {count} nodes from source"
                ).format(count=len(borrables))
            )
        if not menu.actions():
            return
        chosen = menu.exec(event.screenPos())
        if chosen is disconnect_action:
            self._view.disconnect_selected()
        elif chosen is delete_action:
            self._view.delete_selected()
        else:
            _run_node_action(
                self._view, self.node, chosen, inspect_action, source_action
            )

    def mouseDoubleClickEvent(self, event) -> None:
        """Propaga el doble clic: abre la inclusión, o el SoC si es la raíz."""
        if self.node.include is not None:
            self._view.includeActivated.emit(self.node.include)
        elif self.node.is_root:
            self._view.request_soc_properties()
        super().mouseDoubleClickEvent(event)


def _block_tooltip(node: GraphNode) -> str:
    """Lo que enseñaba la ficha del bloque antes de empaquetarse dentro del SoC.

    El bloque es demasiado pequeño para su nombre, su compatible y sus
    propiedades a la vez -es un indicador, no una ficha-, así que al pasar
    por encima se enseña lo mismo que se leía en su ficha cuando colgaba
    aparte: todas sus propiedades, no solo las `MAX_ROWS` que caben en una
    ficha real.
    """
    lines = [node.label]
    if node.detail:
        lines.append(node.detail)
    for name, value in node.properties:
        lines.append(f"{name}: {value}" if value else name)
    return "\n".join(lines)


class _BlockChip(QGraphicsRectItem):
    """Indicador de un controlador propio del SoC, dentro de la ficha central.

    No es una ficha (`_NodeItem`): no tiene cabecera ni cuerpo, solo un
    relleno que dice si está encendido y una etiqueta con su nombre. Verde
    si `node.enabled`, sin relleno -la falta de color es la señal de
    apagado- si no. Admite soltar un compatible igual que cualquier ficha de
    controlador (`node.slot`), porque sigue siéndolo: solo ha cambiado dónde
    se dibuja.
    """

    def __init__(
        self,
        node: GraphNode,
        view: "TreeGraphView",
        rect: QRectF,
        parent: QGraphicsItem,
    ):
        """Coloca el bloque en `rect`, en coordenadas locales de la ficha.

        Es hijo de la ficha del SoC y no un item suelto de la escena: la
        ficha se puede arrastrar, y un bloque colocado en coordenadas
        absolutas se quedaba donde estaba mientras su ficha se iba.
        """
        super().__init__(rect, parent)
        self.node = node
        self._view = view
        self.setToolTip(_block_tooltip(node))
        self.setAcceptDrops(node.slot is not None)
        self.setAcceptHoverEvents(True)
        self._paint_state()

    def set_linked(self, active: bool) -> None:
        """Marca este bloque como el controlador de la conexión señalada."""
        self.setPen(
            QPen(QColor(style.GRAPH_NODE_SELECTED_BORDER), 2.2)
            if active
            else self._base_pen
        )

    def hoverEnterEvent(self, event) -> None:
        """Enciende la conexión con lo que cuelga de este controlador."""
        self._view.highlight_link(self.node, True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        """La apaga al salir."""
        self._view.highlight_link(self.node, False)
        super().hoverLeaveEvent(event)

    def _paint_state(self) -> None:
        """Aplica el color de `node.enabled`: el único dato que dice este bloque."""
        radius = style.GRAPH_NODE_CORNER_RADIUS
        if self.node.enabled:
            self.setBrush(QBrush(QColor(style.GRAPH_BLOCK_ENABLED_BG)))
            self._base_pen = QPen(QColor(style.GRAPH_BLOCK_ENABLED_BG), 1)
            self._text_color = QColor(style.GRAPH_BLOCK_ENABLED_TEXT)
        else:
            self.setBrush(Qt.NoBrush)
            self._base_pen = QPen(QColor(style.GRAPH_NODE_DEFAULT_BORDER), 1)
            self._text_color = QColor(style.GRAPH_COLOR_TEXT)
        self.setPen(self._base_pen)
        # `QGraphicsRectItem` no redondea sus esquinas; sin esto los bloques
        # salían a escuadra aunque la piel activa pida `RADIUS_ITEM`.
        self._radius = radius

    def paint(self, painter, option, widget=None) -> None:
        """Rectángulo redondeado con el nombre centrado, elidido si no cabe."""
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(self.brush())
        painter.setPen(self.pen())
        painter.drawRoundedRect(self.rect(), self._radius, self._radius)

        font = QFont()
        font.setPointSizeF(style.GRAPH_ROW_POINT_SIZE)
        painter.setFont(font)
        painter.setPen(QPen(self._text_color))
        metrics = QFontMetricsF(font)
        text_rect = self.rect().adjusted(4, 0, -4, 0)
        painter.drawText(
            text_rect,
            Qt.AlignCenter,
            metrics.elidedText(
                self.node.short_label or block_caption(self.node.label),
                Qt.ElideMiddle,
                text_rect.width(),
            ),
        )

    def set_glow(self, active: bool) -> None:
        """Igual que `_NodeItem.set_glow`: el halo de "aquí se puede soltar"."""
        if not active:
            self.setGraphicsEffect(None)
            return
        glow = QGraphicsDropShadowEffect()
        glow.setColor(QColor(style.GRAPH_DROP_TARGET_GLOW_COLOR))
        glow.setBlurRadius(style.GRAPH_DROP_TARGET_GLOW_RADIUS)
        glow.setOffset(0, 0)
        self.setGraphicsEffect(glow)

    def _is_valid_drop(self, event) -> bool:
        """Igual que `_NodeItem._is_valid_drop`: pregunta al validador de la vista."""
        if self.node.slot is None or not event.mimeData().hasText():
            return False
        validator = self._view.drop_validator
        return bool(validator and validator(self.node.slot, event.mimeData().text()))

    def dragEnterEvent(self, event) -> None:
        """Acepta el arrastre solo si el compatible es válido para este bloque."""
        if self._is_valid_drop(event):
            event.acceptProposedAction()
            self.setPen(QPen(QColor(style.COLOR_DROP_OK), 2))
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        """Mantiene aceptado el arrastre mientras siga siendo válido."""
        if self._is_valid_drop(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        """Restaura el color de estado al salir del bloque sin soltar."""
        self.setPen(self._base_pen)

    def dropEvent(self, event) -> None:
        """Conecta el compatible soltado, si sigue siendo válido.

        Mismo cuidado que `_NodeItem.dropEvent`: `deviceDropped` dispara un
        redibujado completo del grafo (`scene.clear()`), que destruye este
        item de Python mientras su propio `dropEvent` sigue en marcha — no
        se toca `self` después de emitir.
        """
        if not self._is_valid_drop(event):
            event.ignore()
            self.setPen(self._base_pen)
            return
        event.acceptProposedAction()
        self._view.deviceDropped.emit(self.node.slot, event.mimeData().text())

    def mousePressEvent(self, event) -> None:
        """Un clic abre el diálogo de propiedades del SoC.

        A diferencia de la ficha central -que necesita doble clic, porque un
        solo clic ahí selecciona la ficha- el bloque no tiene nada propio
        que seleccionar: es un indicador, no un nodo que se explora por su
        cuenta, así que un clic ya basta. El botón derecho no entra aquí:
        Qt lo entrega como `contextMenuEvent`.
        """
        self._view.request_soc_properties()
        event.accept()

    def contextMenuEvent(self, event) -> None:
        """Lo mismo que ofrece una ficha: es el mismo nodo, dibujado dentro."""
        menu = QMenu()
        inspect_action, source_action = _node_menu_actions(menu, self.node)
        if not menu.actions():
            return
        chosen = menu.exec(event.screenPos())
        _run_node_action(self._view, self.node, chosen, inspect_action, source_action)


class TreeGraphView(QGraphicsView):
    """Vista con desplazamiento y zoom del grafo de nodos."""

    includeActivated = Signal(object)
    # Doble clic en el nodo raíz (el SoC empaquetado): abre su panel de
    # propiedades en vez de expandir/plegar como cualquier otro nodo.
    socActivated = Signal()
    # Se ha soltado un compatible (mimeData().text()) sobre el nodo cuyo
    # PeripheralSlot se pasa como primer argumento.
    deviceDropped = Signal(object, str)
    # Clic derecho en un nodo generado, pidiendo desconectarlo.
    deviceRemoved = Signal(object)
    # Nodos que el documento abierto escribe y que hay que borrar de su
    # fuente, como lista de `(línea, nombre)`. La vista no toca el texto: no
    # lo tiene, y quien lo tiene (`MainWindow`) es además quien puede
    # preguntar antes de borrarlo.
    nodesDeleteRequested = Signal(list)
    # "Abrir inspector" del menú contextual: el `path` del `DeviceTreeNode`
    # a mostrar. La vista no lo resuelve porque no conoce el árbol fusionado,
    # solo el grafo ya construido a partir de él.
    nodeInspectRequested = Signal(str)
    # "Ver en el editor DTS": el `path` del nodo y su etiqueta DTS (o cadena
    # vacía). Van los dos porque el documento abierto puede escribirlo de dos
    # formas -el nodo entero, o un `&etiqueta { … }` que lo reabre- y solo
    # `MainWindow` sabe cuál de ellas tiene delante. La vista no resuelve
    # nada: la línea que arrastra un nodo del árbol fusionado cuenta sobre el
    # fichero que lo declara, que puede no ser el que se está editando.
    nodeSourceRequested = Signal(str, str)
    # Zoom actual (1.0 = 100 %), cada vez que cambia. Lo enseña la botonera
    # flotante: la vista no tiene dónde escribirlo y tampoco le corresponde.
    zoomChanged = Signal(float)

    def __init__(self, parent=None):
        """Prepara la escena, el suavizado y el modo de arrastre."""
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setAcceptDrops(True)
        # `QGraphicsView` reenvía los eventos de soltar a la escena, pero
        # quien realmente los recibe del sistema de ventanas es su
        # `viewport()` — sin esto, un arrastre externo (desde la paleta)
        # nunca llegaba a entrar, aunque `setAcceptDrops` estuviera puesto en
        # la vista misma.
        self.viewport().setAcceptDrops(True)
        # Si se puede tocar el árbol desde aquí o solo mirarlo (ver
        # `set_editable`).
        self._editable = True
        # Decide si un compatible arrastrado es válido para un slot; lo
        # rellena quien conoce la base de datos (`VisualizerTab`), igual que
        # `DtsEditor.set_completion_provider` — el grafo no la conoce.
        self.drop_validator: Optional[Callable[[PeripheralSlot, str], bool]] = None
        self.setRenderHint(QPainter.Antialiasing)
        # Recuadro de selección con el botón izquierdo sobre el vacío, que es
        # lo que hace falta para coger varios nodos a la vez; desplazar el
        # lienzo pasa al botón central (ver `mousePressEvent`), el reparto
        # habitual en los editores de nodos. Antes el izquierdo desplazaba y
        # no había forma de seleccionar más de un nodo.
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor(style.GRAPH_SCENE_BACKGROUND)))
        self._next_x = 0.0
        # Coordenada vertical de cada nivel, recalculada en cada `_render`
        # (ver `_measure_levels`): depende de lo alta que sea la ficha mayor
        # de cada uno, y eso cambia al plegar, desplegar o conectar algo.
        self._level_y: Dict[int, float] = {}
        # Lo que hace falta para encender una conexión al pasar el ratón (ver
        # `highlight_link`): las aristas que salen de un bloque con sus dos
        # extremos, y los items dibujados de cada `GraphNode` por su id.
        self._links: List[tuple] = []
        self._items: Dict[int, "_NodeItem"] = {}
        self._chips: Dict[int, "_BlockChip"] = {}
        # Cada arista con sus dos extremos ya dibujados, para poder rehacer
        # su curva cuando uno de ellos se mueve.
        self._edges: List[tuple] = []
        # Dónde ha dejado el usuario cada ficha, por la misma identidad
        # estable que el plegado (`_collapse_key`): el grafo se reconstruye
        # entero en cada análisis, y sin esto cada pulsación de tecla en el
        # editor deshacía la colocación a mano. Se vacía al autoordenar.
        self._manual_pos: Dict[object, QPointF] = {}
        # Mientras `_render` coloca las fichas, sus movimientos no son del
        # usuario y no deben apuntarse como posición manual.
        self._placing = False
        # Punto desde el que se está desplazando el lienzo con el botón
        # central, o None si no se está desplazando.
        self._pan_from: Optional[QPointF] = None
        self._root: Optional[GraphNode] = None
        # El grafo suele construirse con la pestaña oculta, cuando la vista no
        # tiene aún su tamaño real y `fitInView` calcula mal la escala. Se
        # apunta que falta encuadrar y se hace en cuanto la vista se dimensiona.
        self._needs_fit = False

    def drawBackground(self, painter, rect) -> None:
        """Pinta una rejilla sobre el fondo, como en los editores de nodos habituales.

        Se recalcula en cada pintado a partir de `rect` (la porción visible de
        la escena, ya en sus coordenadas) en vez de guardarse como ítems fijos
        de la escena: así sigue encajando sin más al hacer scroll o zoom, sin
        tener que reposicionar nada.
        """
        super().drawBackground(painter, rect)

        grid = style.GRAPH_GRID_SIZE
        major_every = style.GRAPH_GRID_MAJOR_EVERY
        left = int(rect.left()) - (int(rect.left()) % grid)
        top = int(rect.top()) - (int(rect.top()) % grid)

        minor_lines: List[QLineF] = []
        major_lines: List[QLineF] = []

        x = left
        while x < rect.right():
            line = QLineF(x, rect.top(), x, rect.bottom())
            target = major_lines if (x // grid) % major_every == 0 else minor_lines
            target.append(line)
            x += grid

        y = top
        while y < rect.bottom():
            line = QLineF(rect.left(), y, rect.right(), y)
            target = major_lines if (y // grid) % major_every == 0 else minor_lines
            target.append(line)
            y += grid

        pen = QPen(QColor(style.GRAPH_GRID_MINOR_COLOR))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLines(minor_lines)

        pen.setColor(QColor(style.GRAPH_GRID_MAJOR_COLOR))
        painter.setPen(pen)
        painter.drawLines(major_lines)

    # ------------------------------------------------------------------
    # Construcción del grafo
    # ------------------------------------------------------------------
    def show_graph(self, root: Optional[GraphNode]) -> None:
        """Dibuja el grafo a partir de su nodo raíz y lo encuadra.

        Si ya había un grafo dibujado, el plegado de cada nodo se traslada al
        nuevo árbol por su identidad (`_collapse_key`): reconstruir el grafo
        en cada cambio no debe replegar lo que el usuario ya había
        desplegado.
        """
        if root is not None and self._root is not None:
            _copy_collapsed_state(self._root, root)
        self._root = root
        self._needs_fit = True
        self._render(fit=True)

    def redraw(self) -> None:
        """Vuelve a dibujar tras plegar o desplegar, sin mover el encuadre."""
        self._render(fit=False)

    def highlight_drop_targets(self, compatible: str) -> None:
        """Enciende el halo morado en cada nodo donde `compatible` sería válido.

        Se llama en cuanto se coge algo de la paleta (`BindingPalette.
        dragStarted`, ver `VisualizerTab`), no solo cuando el arrastre entra
        en esta vista: así los candidatos ya están iluminados aunque el
        cursor todavía esté sobre la paleta, un paso antes de que
        `dragEnterEvent` llegue a verlo.
        """
        if self.drop_validator is None:
            return
        for item in self.scene().items():
            if isinstance(item, (_NodeItem, _BlockChip)) and item.node.slot is not None:
                item.set_glow(self.drop_validator(item.node.slot, compatible))

    def clear_drop_highlights(self) -> None:
        """Apaga el halo morado de todos los nodos (arrastre soltado o cancelado)."""
        for item in self.scene().items():
            if isinstance(item, (_NodeItem, _BlockChip)):
                item.set_glow(False)

    def highlight_link(self, node: GraphNode, on: bool) -> None:
        """Resalta la conexión de un bloque del SoC con lo que cuelga de él.

        Con veinte controladores metidos en la ficha del SoC, las aristas
        salen todas del mismo sitio y cruzan por debajo unas de otras: mirando
        una ficha no se sabe de cuál de los bloques cuelga. Al pasar el ratón
        por cualquiera de los dos extremos se encienden los tres a la vez -el
        bloque, la arista y la ficha-, que es la respuesta a esa pregunta sin
        tener que seguir la línea con el dedo.

        Se acepta cualquiera de los dos extremos porque la pregunta se hace en
        las dos direcciones: «de qué controlador cuelga esto» y «qué lleva
        colgando este controlador».
        """
        for edge, block, child in self._links:
            if node is not block and node is not child:
                continue
            edge.setPen(
                QPen(QColor(style.GRAPH_NODE_SELECTED_BORDER), 2.2)
                if on
                else QPen(QColor(style.GRAPH_COLOR_EDGE), 1.2)
            )
            # Por encima del resto de aristas mientras está encendida, o se
            # pierde entre las que le pasan por delante.
            edge.setZValue(0 if on else -1)
            for item in (self._chips.get(id(block)), self._items.get(id(child))):
                if item is not None:
                    item.set_linked(on)

    def _render(self, fit: bool) -> None:
        """Reconstruye la escena con el estado de plegado actual."""
        root = self._root
        scene = self.scene()
        scene.clear()
        self._next_x = 0.0
        # La escena acaba de vaciarse: lo que hubiera aquí son items ya
        # borrados por Qt, y tocarlos revienta con "objeto ya borrado".
        self._links = []
        self._items = {}
        self._chips = {}
        self._edges = []

        if root is None:
            return

        positions: Dict[int, QPointF] = {}
        self._level_y = self._measure_levels(root)
        self._layout(root, depth=0, positions=positions)
        self._placing = True
        try:
            self._draw(root, positions, scene)
        finally:
            self._placing = False

        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-60, -60, 60, 60))
        if fit:
            self.fit()

    def _measure_levels(self, root: GraphNode) -> Dict[int, float]:
        """Coordenada vertical de cada nivel, según lo alta que sea su ficha mayor.

        `VERTICAL_GAP` mide de centro a centro, y con fichas de alto parecido
        basta. Deja de bastar en cuanto una crece: la del SoC con sus bloques
        dentro pasa de 380px y sus propios hijos, colocados 150px más abajo,
        le caían encima. Se mide el alto mayor de cada nivel y se separan los
        centros lo suficiente para que quede `VERTICAL_EDGE_GAP` de aire
        entre bordes — o `VERTICAL_GAP`, el que salga mayor, para que un
        árbol de fichas normales quede exactamente como estaba.
        """
        heights: Dict[int, float] = {}

        def measure(node: GraphNode, depth: int) -> None:
            heights[depth] = max(heights.get(depth, 0.0), node_size(node).height())
            for child in node.visible_children:
                measure(child, depth + 1)
            # Lo que cuelga de un bloque vive un nivel por debajo del SoC,
            # igual que un hijo normal, aunque su arista salga del bloque.
            if node.is_root and not node.collapsed:
                for block in node.blocks:
                    for child in block.children:
                        measure(child, depth + 1)

        measure(root, 0)

        levels: Dict[int, float] = {0: 0.0}
        for depth in sorted(heights)[1:]:
            step = max(
                VERTICAL_GAP,
                heights[depth - 1] / 2 + heights[depth] / 2 + VERTICAL_EDGE_GAP,
            )
            levels[depth] = levels[depth - 1] + step
        return levels

    def _layout(
        self, node: GraphNode, depth: int, positions: Dict[int, QPointF]
    ) -> float:
        """Asigna posición a cada nodo y devuelve su coordenada horizontal.

        Cada hoja ocupa una columna nueva y cada padre se centra sobre sus
        hijos, que es el reparto habitual para que un árbol se lea sin cruces.
        Los hijos de un bloque (lo conectado a un controlador propio del SoC,
        ver `build_graph`) cuentan como si fueran hijos directos de la raíz
        para este reparto: la arista sale de otro sitio (el bloque, no la
        ficha del SoC), pero la columna que ocupan es la misma.

        La coordenada vertical la pone `_measure_levels`, no el nivel por un
        paso fijo: una ficha alta -la del SoC con sus bloques- se comía a sus
        hijos si todos los niveles iban a la misma distancia.
        """
        y = self._level_y.get(depth, depth * VERTICAL_GAP)

        columns = [
            self._layout(child, depth + 1, positions)
            for child in node.visible_children
        ]
        if node.is_root and not node.collapsed:
            for block in node.blocks:
                columns.extend(
                    self._layout(child, depth + 1, positions)
                    for child in block.children
                )

        if not columns:
            x = self._next_x
            self._next_x += HORIZONTAL_GAP
        else:
            x = (columns[0] + columns[-1]) / 2

        positions[id(node)] = QPointF(x, y)
        return x

    def _edge_path(self, source: QGraphicsItem, target: "_NodeItem") -> QPainterPath:
        """Curva del borde inferior de `source` al superior de `target`.

        Se calcula sobre la posición **actual** de los dos items, no sobre el
        reparto automático: las fichas se pueden arrastrar, y una arista
        dibujada de una vez se quedaba clavada donde estaba el nodo.
        """
        if isinstance(source, _BlockChip):
            start = source.mapToScene(
                QPointF(source.rect().center().x(), source.rect().bottom())
            )
        else:
            start = source.mapToScene(QPointF(0, source.rect().bottom()))
        end = target.mapToScene(QPointF(0, target.rect().top()))
        middle = (start.y() + end.y()) / 2
        path = QPainterPath(start)
        path.cubicTo(QPointF(start.x(), middle), QPointF(end.x(), middle), end)
        return path

    def _add_edge(
        self, scene: QGraphicsScene, source: QGraphicsItem, target: "_NodeItem"
    ) -> QGraphicsPathItem:
        """Dibuja la arista entre dos items y la apunta para poder rehacerla."""
        edge = QGraphicsPathItem(self._edge_path(source, target))
        edge.setPen(QPen(QColor(style.GRAPH_COLOR_EDGE), 1.2))
        edge.setZValue(-1)
        scene.addItem(edge)
        self._edges.append((edge, source, target))
        return edge

    def _draw(
        self, node: GraphNode, positions: Dict[int, QPointF], scene: QGraphicsScene
    ) -> "_NodeItem":
        """Dibuja la ficha del nodo, sus bloques y las aristas hacia sus hijos.

        La ficha se coloca donde diga el reparto automático, salvo que el
        usuario la haya movido a mano (`_manual_pos`), que manda. Las aristas
        se trazan de item a item —no de posición a posición— porque tienen
        que seguir a las fichas cuando se arrastran.

        Ya no se dibuja etiqueta suelta: el nombre va dentro de la cabecera.
        """
        item = _NodeItem(node, self)
        item.setPos(self._manual_pos.get(_collapse_key(node), positions[id(node)]))
        scene.addItem(item)
        self._items[id(node)] = item

        for child in node.visible_children:
            child_item = self._draw(child, positions, scene)
            self._add_edge(scene, item, child_item)

        # Los bloques (controladores propios del SoC) son hijos de la ficha,
        # así que se pintan encima de ella -es lo que hace que se lean como
        # "dentro" en vez de tapados- y la acompañan si se arrastra. Solo
        # desplegada: plegada la ficha representa la placa vista desde fuera,
        # y lo que trae soldado el SoC no se ve desde ahí (ver `build_graph`).
        if node.is_root and not node.collapsed and node.blocks:
            for block, local_rect in zip(node.blocks, block_rects(node)):
                chip = _BlockChip(block, self, local_rect, item)
                self._chips[id(block)] = chip
                for child in block.children:
                    child_item = self._draw(child, positions, scene)
                    edge = self._add_edge(scene, chip, child_item)
                    # Los tres extremos juntos, para poder encenderlos a la
                    # vez al pasar el ratón (ver `highlight_link`).
                    self._links.append((edge, block, child))
        return item

    # ------------------------------------------------------------------
    # Interacción
    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:
        """Encuadra al hacerse visible, si quedaba pendiente."""
        super().showEvent(event)
        self.fit()

    def resizeEvent(self, event) -> None:
        """Encuadra al recibir su tamaño definitivo, si quedaba pendiente."""
        super().resizeEvent(event)
        if self._needs_fit:
            self.fit()

    def zoom_by(self, step: float) -> None:
        """Multiplica el zoom por `step`, acotado a `MIN_ZOOM`/`MAX_ZOOM`."""
        current_zoom = self.transform().m11()
        target_zoom = max(MIN_ZOOM, min(MAX_ZOOM, current_zoom * step))
        factor = target_zoom / current_zoom
        self.scale(factor, factor)
        self.zoomChanged.emit(target_zoom)

    def wheelEvent(self, event) -> None:
        """Acerca o aleja el grafo con la rueda."""
        self.zoom_by(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)

    def mousePressEvent(self, event) -> None:
        """El botón central empieza a desplazar el lienzo.

        El izquierdo lo dejó de hacer al pasar a `RubberBandDrag`, que es lo
        que permite coger varios nodos de una vez; desplazar se hace con el
        central, como en cualquier editor de nodos.
        """
        if event.button() == Qt.MiddleButton:
            self._pan_from = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """Mueve las barras de desplazamiento mientras se arrastra con el central."""
        if self._pan_from is not None:
            delta = event.position() - self._pan_from
            self._pan_from = event.position()
            for bar, step in (
                (self.horizontalScrollBar(), delta.x()),
                (self.verticalScrollBar(), delta.y()),
            ):
                bar.setValue(bar.value() - int(step))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        """Termina el desplazamiento con el botón central."""
        if event.button() == Qt.MiddleButton and self._pan_from is not None:
            self._pan_from = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def node_moved(self, item: "_NodeItem") -> None:
        """Apunta dónde ha quedado una ficha movida a mano y recoloca las aristas.

        La posición se guarda por la identidad estable del nodo
        (`_collapse_key`, la misma que conserva el plegado) porque el grafo
        se reconstruye entero en cada análisis: sin esto, escribir una letra
        en el editor devolvía todo al reparto automático.
        """
        if self._placing:
            return
        self._manual_pos[_collapse_key(item.node)] = item.pos()
        for edge, source, target in self._edges:
            edge.setPath(self._edge_path(source, target))
        # La escena solo crece: encogerla mientras se arrastra haría saltar
        # las barras de desplazamiento bajo el ratón.
        scene = self.scene()
        scene.setSceneRect(
            scene.sceneRect().united(
                scene.itemsBoundingRect().adjusted(-60, -60, 60, 60)
            )
        )

    def auto_arrange(self) -> None:
        """Olvida las posiciones manuales y vuelve al reparto automático."""
        self._manual_pos.clear()
        self._render(fit=True)

    def set_editable(self, editable: bool) -> None:
        """Pone el grafo en modo lectura, o lo devuelve a modo edición.

        En modo lectura se mira y se recorre —plegar, mover fichas, abrir el
        Inspector, saltar al fuente— pero no se toca el árbol: ni se sueltan
        dispositivos, ni se quita nada, ni se abre el panel del SoC, que
        enciende y apaga controladores escribiendo en el fuente. Un único
        interruptor porque las tres salen de aquí: las dos formas de quitar
        algo, de las mismas dos listas (`selected_slots` y
        `selected_editable`); soltar, del `setAcceptDrops` de la vista —sin
        él ningún item llega a ver el arrastre—; y el panel, de
        `request_soc_properties`.
        """
        self._editable = editable
        self.setAcceptDrops(editable)
        self.viewport().setAcceptDrops(editable)

    def request_soc_properties(self) -> None:
        """Pide abrir el panel del SoC, si el grafo no está en modo lectura.

        Las dos puertas a ese panel —doble clic en la ficha central y clic en
        un bloque del SoC— pasan por aquí en vez de emitir la señal cada una
        por su cuenta: la condición es la misma y escrita dos veces se
        separan a la primera. En modo lectura no se emite nada, que es lo
        que deja el gesto sin efecto en lugar de abrir una ventana cuyo
        «Apply» no puede aplicar.
        """
        if not self._editable:
            return
        self.socActivated.emit()

    def selected_editable(self) -> List[GraphNode]:
        """Los nodos seleccionados que escribe el documento abierto.

        Nunca la ficha central -es el documento entero- ni un bloque del
        SoC, que ni siquiera es una ficha: lo que hay aquí son los nodos que
        una placa añade sobre su SoC, que es lo único que se puede quitar
        del fuente que se está mirando.
        """
        if not self._editable:
            return []
        return [
            item.node
            for item in self.scene().selectedItems()
            if isinstance(item, _NodeItem)
            and item.node.editable
            and not item.node.is_root
        ]

    def selected_slots(self) -> List[PeripheralSlot]:
        """Los dispositivos de la sesión de conexión que hay seleccionados.

        Solo lo conectado desde la sesión de edición
        (`GraphNode.connected_slot`): un nodo que está escrito en el `.dts`
        no se quita del grafo, se quita del fuente, y eso es cosa del editor.
        """
        if not self._editable:
            return []
        slots = []
        for item in self.scene().selectedItems():
            node = getattr(item, "node", None)
            if node is not None and node.connected_slot is not None:
                slots.append(node.connected_slot)
        return slots

    def disconnect_selected(self) -> int:
        """Desconecta lo que la sesión de edición tenga seleccionado.

        Los slots se recogen **antes** de emitir nada: cada desconexión
        redibuja el grafo entero (`scene.clear()`) y destruye los items que
        se estarían recorriendo. Quitar un mux se lleva por delante lo que
        colgaba de él, así que un slot de la lista puede haber desaparecido
        ya cuando le toca -de eso se encarga `disconnect_by_slot`, que
        comprueba que siga enganchado a su padre.
        """
        slots = self.selected_slots()
        for slot in slots:
            self.deviceRemoved.emit(slot)
        return len(slots)

    def delete_selected(self) -> int:
        """Pide borrar del fuente los nodos seleccionados que este escribe."""
        nodes = self.selected_editable()
        if nodes:
            self.nodesDeleteRequested.emit([(node.line, node.label) for node in nodes])
        return len(nodes)

    def remove_selected(self) -> int:
        """Las dos formas de quitar algo, que es lo que hace Supr.

        Son dos cosas distintas con el mismo gesto: lo conectado en la
        sesión se **desconecta** (no está escrito en ningún sitio) y un nodo
        que escribe el documento abierto se **borra de su fuente**, que es
        donde vive. Lo que llega de un `#include` -el SoC de una placa- no
        está en ninguna de las dos listas y no se toca.
        """
        return self.delete_selected() + self.disconnect_selected()

    def keyPressEvent(self, event) -> None:
        """Supr quita del grafo los dispositivos seleccionados.

        Actúa sobre **toda** la selección, no sobre el primero que
        encuentre: se pueden coger varios con el recuadro y quitarlos de una
        vez.

        El atajo vive en la vista y no en la ventana a propósito: Supr ya
        está cogida por el panel de carpetas, y dos atajos iguales a nivel de
        ventana hacen que Qt no dispare ninguno (ver CLAUDE.md).
        """
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.remove_selected():
            event.accept()
            return
        super().keyPressEvent(event)

    def fit(self) -> None:
        """Ajusta el grafo completo a la vista, sin pasar del 100 %.

        `fitInView` estira hasta llenar el hueco, y con un árbol recién
        abierto —el SoC plegado, un solo nodo— eso significaba más de un
        400 % de zoom: un cuadrado enorme con su etiqueta gigante, que es lo
        que hacía que el grafo pareciera un juguete. El tope deja el nodo a
        un tamaño cómodo sin llenar la pantalla con él; ampliar más allá de
        eso no añade información y el usuario sigue teniendo la rueda.
        """
        if not self.scene().items():
            return
        self.resetTransform()
        self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)
        if self.transform().m11() > style.GRAPH_MAX_FIT_ZOOM:
            self.resetTransform()
            self.scale(style.GRAPH_MAX_FIT_ZOOM, style.GRAPH_MAX_FIT_ZOOM)
            self.centerOn(self.scene().sceneRect().center())
        # Solo se da por encuadrado cuando la vista ya tiene tamaño real; si
        # no, se reintenta en el siguiente `resizeEvent`.
        self._needs_fit = self.viewport().width() <= 1
        self.zoomChanged.emit(self.transform().m11())


def is_disabled(node: DeviceTreeNode) -> bool:
    """Si el nodo está apagado en el fuente (`status = "disabled"`).

    El valor llega tal cual se escribió, con sus comillas: el parser guarda
    el texto crudo de la propiedad y quitarlas es cosa de quien la lee.
    """
    value = node.properties.get("status")
    return isinstance(value, str) and value.strip().strip('"') == "disabled"


def leads_to_binding(node: DeviceTreeNode) -> bool:
    """Si `node`, o algo encendido por debajo de él, declara un `compatible`.

    Es lo que separa un **dispositivo** de una **configuración**. Un device
    tree usa nodos para las dos cosas: `i2c-mux@75` declara
    `compatible = "nxp,pca9548"` y es una pieza que existe, mientras que
    `uart1-default` es un grupo de pines del pinctrl —sin compatible, sin
    binding— y `ports` bajo un display es un contenedor del binding de
    grafo. Dibujarlos llenaba el grafo de fichas que no son hardware: el
    zcu100 sacaba diez (`uart0-default`, `usb1-default`…) colgando de su
    pinctrl.

    Se mira el subárbol entero y no solo el nodo porque un contenedor sin
    compatible puede ser el camino hasta uno que sí lo tiene: los canales de
    un mux I2C son `i2c@0`/`i2c@1` pelados y es dentro donde cuelgan los
    dispositivos. Podarlos se llevaría por delante lo que hay debajo.

    Lo apagado no cuenta: un contenedor cuyo único dispositivo está apagado
    no lleva a ninguna parte, y dibujarlo dejaría una ficha vacía.
    """
    if is_disabled(node):
        return False
    if node.compatible:
        return True
    return any(leads_to_binding(child) for child in node.children)


def build_graph(
    root: DeviceTreeNode,
    includes: Sequence[ResolvedInclude] = (),
    controller_names: Optional[set] = None,
    max_children: int = 60,
    initial_depth: int = 1,
    soc_name: Optional[str] = None,
    board_name: Optional[str] = None,
    root_slots: Optional[List[PeripheralSlot]] = None,
    hardware: Optional[dict] = None,
) -> GraphNode:
    """Traduce el árbol analizado (y sus inclusiones) a nodos de grafo.

    Los `.dts` reales tienen cientos de nodos, así que el grafo nace plegado a
    `initial_depth` niveles y se despliega con la insignia «+»/«−» de cada
    nodo (ver `_ToggleBadge`). `max_children` recorta además las ramas
    desmesuradamente anchas.

    El nodo raíz representa el SoC que se empaqueta, no la raíz DTS: si se da
    `soc_name` se usa como etiqueta del círculo central en vez de "/". Plegado
    representa la placa completa tal y como se ve desde fuera -se etiqueta con
    `board_name` si se da- y solo al desplegarlo se pasa a ver "el SoC" que
    hay dentro, con `soc_name`. Lo que va empaquetado dentro (`cpus`,
    `memory`, `clocks`, el propio nodo `soc` de envoltorio…) no se dibuja
    como hijo del círculo central; `collect_hoisted` atraviesa esos
    envoltorios intermedios sin dibujarlos para encontrar, a la profundidad
    real que tengan, lo que sí colgar o empaquetar. Y de eso hay dos clases,
    según `DeviceTreeNode.soc_defined` -si viene de un `#include` fusionado
    (el `.dtsi` del SoC) o lo escribió de cero la placa (un chip conectado)-:

    - **Propio del SoC y encendido** (buses o periféricos con `status` que
      vienen del `.dtsi`, como `i2c0` o un UART): se dibuja como **bloque**
      dentro de la ficha central (`GraphNode.blocks`, ver `_BlockChip`).
      Sigue siendo un controlador de verdad: admite que se le suelte un
      compatible encima (`node.slot`) igual que antes, y lo que se le conecta
      se sigue dibujando como una ficha aparte, con la arista saliendo del
      bloque en vez de la ficha del SoC. **Apagado no se dibuja en absoluto**:
      un bloque es algo a lo que conectar cosas, y a un bus apagado no se le
      conecta nada. Un `.dtsi` de SoC trae apagado casi todo lo que integra,
      así que de fábrica la ficha no lleva ningún bloque dentro y van
      apareciendo según se encienden desde el panel de propiedades del SoC
      -que es lo que convierte ese panel en el sitio donde se elige qué lleva
      la placa-.
    - **El resto** (`controller_names`, ver `extract_connectable_nodes`, y
      cualquier otro con `status` que no venga del `.dtsi` -un chip
      conectado que además ofrece más bus, como un mux I2C soldado por la
      placa-): sigue colgando aparte con su propia ficha y arista, como
      hasta ahora. `HOISTED_LEAF_PREFIXES` (ethernet/can/uart/serial) entra
      aquí solo si además le falta `soc_defined`; son casi siempre hojas y
      quedarían empaquetados para siempre si se les exigiera hijos como a un
      MFD.

    **Lo que está apagado no se dibuja**, sea de la clase que sea: un nodo
    con `status = "disabled"` no está en la máquina, así que ni él ni su
    subárbol salen en el grafo (`is_disabled`), y se cuenta en
    `hidden_disabled` para que el aviso del visualizador diga cuántos hay y
    dónde encenderlos. Un `.dtsi` de SoC declara apagado casi todo lo que
    integra —el zynq-7000 trae dos decenas así— y la placa enciende lo que
    lleva soldado; dibujarlo todo enseñaba el catálogo del silicio en vez de
    la placa que se está montando.

    Con `root_slots` (la sesión de conexión del Generador/Visualizador,
    `KernelGroveService.create_slots`), se solapan sobre el grafo los dispositivos
    que el usuario ha conectado pero que aún no existen en el `.dts` real:
    cada controlador se empareja con su slot por `path` (no por nombre, que
    puede repetirse entre controladores distintos) y se le añaden como hijos
    los nodos sintéticos de `PeripheralSlot.children`, marcados
    `generated=True` para que se dibujen con borde discontinuo.
    """
    controller_names = controller_names or set()
    nodes_by_path: Dict[str, GraphNode] = {}
    apagados = 0
    # Todos los controladores propios del SoC como `(nombre, path)`, se
    # dibujen o no: es el censo con el que `number_blocks` reparte los
    # índices, para que un `i2c` lleve el número que le da el fabricante y no
    # el que le tocaría entre los encendidos.
    censo: List[tuple] = []

    # Si **nada** del árbol viene de un include, el documento abierto *es* el
    # SoC y todo lo que declara es suyo. `IncludeResolver` solo marca
    # `soc_defined` sobre lo que fusiona, así que sin esto abrir el `.dtsi`
    # de un SoC directamente -la ruta normal desde el catálogo- no daba un
    # solo bloque: no había nada "de fuera" con lo que contrastar. Cuando el
    # documento sí incluye algo (una placa sobre su SoC) la marca por nodo ya
    # distingue, y esto no se activa.
    todo_es_del_soc = not any(node.soc_defined for node in root.iter_tree())

    def convert(node: DeviceTreeNode, depth: int) -> GraphNode:
        """Convierte un nodo ya considerado "colgante" y, recursivamente, sus hijos."""
        graph_node = GraphNode(
            label=node.name,
            detail=", ".join(node.compatible),
            line=node.line,
            is_controller=node.name in controller_names,
            collapsed=depth >= initial_depth,
            path=node.path,
            dt_label=node.label,
            properties=property_rows(node.properties),
            enabled=not is_disabled(node),
            # Lo escribe el documento abierto (no ha llegado por un
            # `#include`, ver `IncludeResolver.resolve_tree`), así que su
            # `line` es una línea de este fuente y se puede borrar de él.
            # Lo del SoC llega marcado y vive en otro fichero: desde aquí no
            # se toca. Lo que dibuja el SoC como bloque tampoco, pero eso ya
            # lo decide `_BlockChip`, que no ofrece borrar.
            #
            # Y si el documento *es* el SoC (`todo_es_del_soc`: no hay nada
            # incluido con lo que contrastar) no se ofrece borrar nada: sus
            # nodos son los del SoC, que es justo lo que no se toca desde
            # aquí. Para eso está el editor, que es donde se edita ese
            # fichero. Lo mismo vale cuando los includes no se han podido
            # resolver: sin saber qué es de quién, no se borra.
            editable=(
                not node.soc_defined
                and not todo_es_del_soc
                and node.line is not None
            ),
        )
        if node.path:
            nodes_by_path[node.path] = graph_node

        nonlocal apagados
        encendidos = [child for child in node.children if not is_disabled(child)]
        apagados += len(node.children) - len(encendidos)
        # Solo se dibuja lo que es hardware. Un nodo de configuración -un
        # grupo de pines del pinctrl, un contenedor `ports`- no declara
        # `compatible` ni lleva a nada que lo declare, y no es una pieza del
        # sistema (ver `leads_to_binding`). No cuenta como apagado: no está
        # porque no es un dispositivo, no porque esté desactivado.
        visibles = [child for child in encendidos if leads_to_binding(child)]
        children = visibles[:max_children]
        graph_node.children = [convert(child, depth + 1) for child in children]

        # Los apagados no cuentan como «rama recortada»: no están porque no
        # están puestos, no porque no quepan.
        hidden = len(visibles) - len(children)
        if hidden > 0:
            graph_node.children.append(
                GraphNode(
                    label=QCoreApplication.translate(
                        "TreeGraphView", "(+{count} nodes)"
                    ).format(count=hidden),
                    detail=QCoreApplication.translate(
                        "TreeGraphView", "Branch trimmed"
                    ),
                )
            )

        return graph_node

    def overlay_slot(slot: PeripheralSlot) -> GraphNode:
        """Nodo sintético para un dispositivo conectado desde la sesión de edición.

        Recursa en `slot.children`: un dispositivo conectado que a su vez
        admite más (un mux, un MFD) queda igual de "soltable" que un
        controlador real, vía `GraphNode.slot`. `connected_slot` lo lleva
        siempre, admita hijos o no: es por lo que se le puede quitar.
        """
        overlay = GraphNode(
            label=slot.display_name,
            detail=", ".join(slot.descriptor.compatibles),
            # Todavía no tiene nodo real del que leer propiedades: lo único
            # que se sabe de él es con qué compatible se ha conectado, que
            # es además lo que hay que comprobar de un vistazo.
            properties=[("compatible", slot.descriptor.compatibles[0])]
            if slot.descriptor.compatibles
            else [],
            is_controller=slot.is_bus,
            generated=True,
            collapsed=False,
            slot=slot if slot.accepts_children else None,
            connected_slot=slot,
        )
        overlay.children = [overlay_slot(child) for child in slot.children]
        return overlay

    def is_hoistable(node: DeviceTreeNode) -> bool:
        """Decide si `node` debe colgar del círculo del SoC en el grafo."""
        if node.name in controller_names:
            return True
        if "status" not in node.properties:
            return False
        if node.children:
            return True
        prefix = node.name.split("@", 1)[0].lower()
        return prefix in HOISTED_LEAF_PREFIXES

    def collect_hoisted(
        node: DeviceTreeNode, depth: int
    ) -> tuple[List[GraphNode], List[GraphNode]]:
        """Busca en profundidad lo colgante, sin dibujar lo que atraviesa.

        Devuelve dos listas: lo que sigue colgando aparte con su propia
        arista ("el resto" — un chip conectado, no definido en el `.dtsi`
        del SoC) y lo que pasa a ser un bloque dentro de la ficha central
        (`node.soc_defined`, ver `DeviceTreeNode`).
        """
        nonlocal apagados
        found: List[GraphNode] = []
        blocks: List[GraphNode] = []
        for child in node.children:
            # Dentro de la ficha del SoC solo van los controladores
            # **encendidos**. Un bloque es algo a lo que conectar cosas, y a
            # un bus apagado no se le conecta nada: un `.dtsi` de SoC trae
            # apagado casi todo lo que integra, así que de fábrica no hay
            # ningún bloque, y van apareciendo según se encienden desde el
            # panel de propiedades del SoC —que es lo que convierte ese panel
            # en el sitio donde se elige qué lleva la placa—. Los que quedan
            # fuera se cuentan como apagados, que es lo que dice el aviso del
            # grafo y lo que manda a ese panel a encenderlos.
            if (child.soc_defined or todo_es_del_soc) and is_hoistable(child):
                # Los apagados se apuntan igualmente en el censo: es lo que
                # hace que el número de un bloque sea el del hardware y no el
                # de la lista de los que se ven (ver `number_blocks`).
                censo.append((block_caption(child.name), child.path))
                if is_disabled(child):
                    apagados += 1
                    continue
                blocks.append(convert(child, depth))
                continue
            # Un nodo apagado que no es propio del SoC no está en la
            # máquina: ni se dibuja él ni se busca nada dentro de él —lo que
            # cuelga de un bus apagado tampoco está—. Encenderlo (`status =
            # "okay"`, también desde un `&label { … }` de una placa o de un
            # overlay, que se resuelven antes de llegar aquí) lo devuelve al
            # grafo en el siguiente análisis, sin nada más que hacer.
            if is_disabled(child):
                apagados += 1
                continue
            if is_hoistable(child):
                found.append(convert(child, depth))
            else:
                sub_found, sub_blocks = collect_hoisted(child, depth)
                found.extend(sub_found)
                blocks.extend(sub_blocks)
        return found, blocks

    graph_root = GraphNode(
        label=soc_name or root.name,
        detail=", ".join(root.compatible),
        line=root.line,
        # La ficha central enseña **qué hardware es** —arquitectura,
        # núcleos, RAM, reloj—, lo mismo que su entrada del catálogo, y no
        # sus `#address-cells`: de la pieza principal lo que se quiere saber
        # de un vistazo es eso, y las celdas de dirección de la raíz no lo
        # dicen. Si no se pasa, se cae a sus propiedades como cualquier otro
        # nodo.
        properties=hardware_rows(hardware) or property_rows(root.properties),
        is_root=True,
        # Siempre plegada de entrada, sin importar `initial_depth`: lo
        # primero que se ve es la placa (`board_name`); el SoC de dentro
        # solo aparece al desplegar con la insignia «+».
        collapsed=True,
        collapsed_label=board_name,
    )
    graph_root.children, graph_root.blocks = collect_hoisted(root, depth=1)
    graph_root.hidden_disabled = apagados
    # Se numera sobre las listas ya completas: el índice de un `i2c` depende
    # de cuántos más lleve el SoC y de dónde estén, así que no puede
    # decidirse mientras se recorren.
    number_blocks(graph_root.blocks, censo)
    # Después de numerar, para que el tooltip del hijo diga «i2c0» y no
    # «i2c», que es lo que hay que poder distinguir cuando el SoC lleva tres.
    for block in graph_root.blocks:
        for child in block.children:
            child.controller_label = block.short_label

    for slot in root_slots or []:
        target = nodes_by_path.get(slot.descriptor.path)
        if target is None:
            continue
        target.slot = slot
        target.children.extend(overlay_slot(child) for child in slot.children)

    # Los includes encontrados ya vienen fusionados en `root` por
    # `KernelGroveService.build_visual_tree`, así que lo único que llega hasta aquí
    # son los que no se han podido resolver: no hay contenido que fusionar, se
    # señalan aparte para que se note que falta parte del árbol.
    if includes:
        package = GraphNode(
            label=QCoreApplication.translate(
                "TreeGraphView", "includes not found ({count})"
            ).format(count=len(includes)),
            detail=QCoreApplication.translate(
                "TreeGraphView",
                "They are not in the database; the tree above is incomplete",
            ),
        )
        package.children = [
            GraphNode(
                label=item.label,
                detail=QCoreApplication.translate(
                    "TreeGraphView", "Not found in the database"
                ),
                include=item,
                line=item.directive.line,
            )
            for item in includes
        ]
        graph_root.children.insert(0, package)

    _mark_generated_descendants(graph_root)
    return graph_root
