"""Pestaña de herramientas: el catálogo de la base de datos, explorable.

Sustituye a los dos desplegables de SoC y de board que había en una franja
encima de las vistas. Allí ocupaban el ancho de la ventana entera de forma
permanente para algo que se usa al empezar a trabajar; aquí está el sitio
donde además se puede *mirar* qué hay en la base en vez de tener que
acertar con el nombre a ciegas.

**Un solo buscador y dos filtros**, no tres cajas donde escribir. Había un
buscador libre y dos desplegables que también buscaban —cada uno sobre su
mitad del catálogo—, y con tres sitios donde teclear lo mismo no se sabía
en cuál escribir. Ahora se escribe en uno (busca sobre nombre, compatible,
fabricante y ruta) y se estrecha con dos desplegables que **no** se
escriben: el fabricante y si es SoC o board. Abrir es doble clic en la
ficha, que es lo que hacía elegir en el desplegable.

Las fichas las pinta un `QStyledItemDelegate` y no son widgets: el catálogo
son ~3700 entradas entre SoCs y boards, y otros tantos widgets con su
layout no se montan en un tiempo razonable. Con el delegado solo se pinta lo
que se ve.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from kernelgrove.api import BindingEntry, SoCSummary
from kernelgrove.gui import style
from kernelgrove.gui.translations import Retranslates
from kernelgrove.gui.widgets import binding_groups, icons

# Qué es cada entrada de la lista. No es decoración: decide el icono, la
# insignia y —lo importante— con qué lector de la base se abre el fuente.
VIEW_TREES = "trees"
VIEW_BINDINGS = "bindings"

KIND_SOC = "soc"
KIND_BOARD = "board"
KIND_BINDING = "binding"

# Datos que el delegado lee de cada ítem. El texto visible no vale como
# fuente única: la ficha enseña cuatro cosas distintas y `DisplayRole` es
# una sola.
_ROLE_ENTRY = Qt.UserRole + 1  # (kind, índice dentro de su lista)
_ROLE_FIELDS = Qt.UserRole + 2  # ((etiqueta, valor), ...)
_ROLE_BADGE = Qt.UserRole + 3
# Texto sobre el que busca el filtro, ya en minúsculas y concatenado: se
# calcula al montar la lista para no rehacerlo en cada pulsación.
_ROLE_HAYSTACK = Qt.UserRole + 4
# Lo que va debajo de las columnas: la descripción que el propio árbol trae
# (`model`) y su frecuencia.
_ROLE_DESCRIPTION = Qt.UserRole + 6
_ROLE_CLOCK = Qt.UserRole + 7
# Los rótulos de los dos botones. Van en los datos del ítem porque el
# delegado se comparte y no tiene de dónde traducirlos.
_ROLE_LOAD_TEXT = Qt.UserRole + 8
_ROLE_GRAPH_TEXT = Qt.UserRole + 9
# Fabricante tal cual, para el desplegable que filtra por él: no vale
# buscarlo dentro del `haystack`, que también contiene la ruta y el
# compatible y daría por bueno «xlnx» dentro de `xlnx,zynq-7000`.
_ROLE_VENDOR = Qt.UserRole + 5
# La familia de arquitectura, ya resuelta, para el desplegable que filtra
# por ella.
_ROLE_ARCH = Qt.UserRole + 10
# Grupo de la paleta al que pertenece un binding: es lo que decide su
# glifo. Los mismos trece de `binding_groups`, no una categoría inventada
# aquí — un dispositivo se busca en el catálogo y se conecta desde la
# paleta, y con dos clasificaciones distintas serían dos catálogos.
_ROLE_GROUP = Qt.UserRole + 11

# Valor del desplegable que no filtra nada. Va en los datos del ítem y no
# en su texto, que está traducido.
FILTER_ALL = ""

# Familias de arquitectura, en el orden en que se ofrecen. El desplegable
# filtraba por `arch`, que es el compatible de la primera CPU: 115 opciones
# (`arm,cortex-a53`, `arm,cortex-a9`, `arm,cortex-a7`…) que son el modelo
# del núcleo, no la arquitectura, y nadie busca un catálogo por ahí. La
# familia sale del directorio del kernel donde vive el fuente
# (`arch/arm64/boot/dts/…`), que es la clasificación que hace el propio
# kernel y la única que no es ambigua: por el prefijo del compatible no se
# puede, `loongson` es MIPS y LoongArch, y `brcm` es ARM y MIPS. El modelo
# del núcleo se sigue viendo en la ficha, que es donde describe el hardware.
_ARCH_FAMILIES = {
    "arm": "ARM",
    "arm64": "ARM64",
    "riscv": "RISC-V",
    "mips": "MIPS",
    "powerpc": "PowerPC",
    "loongarch": "LoongArch",
    "arc": "ARC",
    "xtensa": "Xtensa",
    "microblaze": "MicroBlaze",
    "nios2": "Nios II",
    "openrisc": "OpenRISC",
    "sh": "SuperH",
    "x86": "x86",
}


def arch_family(item: SoCSummary) -> str:
    """La familia de arquitectura de una entrada, o «» si no se sabe.

    ponytail: una base construida fuera de un checkout del kernel no trae
    ese directorio y sus entradas se quedan sin familia —siguen saliendo,
    solo que no las estrecha este filtro—. Si eso pasa a ser lo normal, el
    sitio de calcularla es la ingesta, en una columna al lado de `arch`.
    """
    partes = (item.file_path or "").split("/")
    if "arch" not in partes:
        return ""
    resto = partes[partes.index("arch") + 1 :]
    return _ARCH_FAMILIES.get(resto[0], "") if resto else ""

def _vendor_combo(on_typed) -> QComboBox:
    """Un desplegable de fabricante: cerrado como filtro, escribible como lista.

    Hay uno por catálogo —los de hardware y los de bindings no son los
    mismos— y los dos se comportan igual, así que se montan aquí en vez de
    dos veces. Escribible porque son centenares y una lista cerrada de esas
    no se recorre; `on_typed` es lo que resuelve lo escrito contra la lista
    cuando se acaba de escribir.
    """
    combo = QComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    combo.completer().setCompletionMode(QCompleter.PopupCompletion)
    combo.completer().setFilterMode(Qt.MatchContains)
    combo.completer().setCaseSensitivity(Qt.CaseInsensitive)
    # Escribir un fabricante que no existe no puede dejar la lista filtrada
    # por lo anterior: se resuelve el texto contra la lista.
    combo.lineEdit().editingFinished.connect(on_typed)
    return combo


def _resolve_vendor(combo: QComboBox) -> None:
    """Deja el desplegable en la entrada que case con lo escrito, o en «todos».

    Es editable para poder buscar entre centenares, pero sigue siendo un
    filtro: lo que no está en la lista no filtra nada, así que se vuelve a
    «todos» en vez de dejar la lista vacía sin explicar por qué.
    """
    texto = combo.currentText().strip()
    indice = combo.findText(texto, Qt.MatchFixedString)
    combo.setCurrentIndex(indice if indice >= 0 else 0)


# El glifo del bloque de icono, ya rasterizado, por (tipo, grupo, color,
# tamaño).
# El delegado los pide en cada repintado: redibujarlos a `QPainterPath` en
# cada fila y en cada scroll cuesta lo que no vale.
_GLYPHS: dict = {}
# Y lo mismo para los iconos de los dos botones del pie.
_BUTTON_GLYPHS: dict = {}


def _button_glyph(draw, size: int, color: str):
    """Icono de un botón de la ficha, cacheado por (dibujo, tamaño, color)."""
    clave = (draw.__name__, size, color)
    pixmap = _BUTTON_GLYPHS.get(clave)
    if pixmap is None:
        pixmap = draw(size, color).pixmap(size, size)
        _BUTTON_GLYPHS[clave] = pixmap
    return pixmap


def _matches_threshold(value: Optional[int], threshold) -> bool:
    """Si `value` llega al mínimo pedido; sin mínimo, todo pasa.

    Los filtros de núcleos y de RAM son «al menos esto», no «exactamente
    esto»: quien busca una placa de 4 núcleos también quiere ver las de 8,
    y con igualdad exacta un catálogo con 2, 4, 6 y 8 obliga a probar
    cuatro veces. Una entrada que no declara el dato **no pasa** un filtro
    con mínimo: decir que sirve sería afirmar algo que no se sabe.
    """
    if not threshold:
        return True
    return bool(value) and value >= threshold


def entry_ref(entry: QListWidgetItem) -> Tuple[str, int]:
    """Qué entrada del catálogo es una ficha: su tipo y su posición.

    Es la identidad de la ficha, y lo único que hay que saber de ella para
    abrirla: el tipo dice con qué lector de la base se lee y la posición en
    qué lista buscarla. Va aquí y no como rol suelto para que nadie de
    fuera tenga que conocer la numeración de los `UserRole`.
    """
    return entry.data(_ROLE_ENTRY)


def card_layout(rect: QRectF) -> dict:
    """Dónde va cada pieza de la ficha, para pintarla y para acertarle.

    Una sola función porque el delegado no tiene widgets dentro: los dos
    botones se pintan a mano y hay que saber después dónde cayó el clic. Si
    el reparto se escribiera dos veces, pintar y pulsar acabarían en sitios
    distintos a la primera que alguien tocara un margen.
    """
    pad = style.DB_CARD_PADDING
    lado = style.DB_CARD_ICON_BOX
    icono = QRectF(rect.left() + pad, rect.top() + pad, lado, lado)
    izquierda = icono.right() + pad
    derecha = rect.right() - pad

    titulo = QRectF(izquierda, rect.top() + pad, derecha - izquierda, 20)
    columnas = QRectF(izquierda, titulo.bottom() + 4, derecha - izquierda, 30)
    descripcion = QRectF(izquierda, columnas.bottom() + 4, derecha - izquierda, 18)

    alto_boton = style.DB_CARD_BUTTON_HEIGHT
    pie = rect.bottom() - pad - alto_boton
    grafo = QRectF(
        derecha - style.DB_CARD_BUTTON_WIDTH,
        pie,
        style.DB_CARD_BUTTON_WIDTH,
        alto_boton,
    )
    cargar = QRectF(
        grafo.left() - 6 - style.DB_CARD_BUTTON_WIDTH,
        pie,
        style.DB_CARD_BUTTON_WIDTH,
        alto_boton,
    )
    reloj = QRectF(izquierda, pie, cargar.left() - izquierda - 8, alto_boton)
    return {
        "icon": icono,
        "title": titulo,
        "columns": columnas,
        "description": descripcion,
        "clock": reloj,
        "load": cargar,
        "graph": grafo,
    }


class _EntryDelegate(QStyledItemDelegate):
    """Dibuja una entrada del catálogo como la ficha del diseño.

    Bloque de icono a la izquierda, nombre e insignia de tipo arriba, cuatro
    columnas de dato, la descripción debajo y un pie con la frecuencia y los
    dos botones. Todo con `QPainter` y leyendo `style` en cada pintado, que
    es lo que hace que cambiar de piel llegue hasta aquí sin reconstruir la
    lista.
    """

    def __init__(self, parent=None, height: int = 0, buttons: bool = True):
        """Arranca sin ningún botón señalado.

        `height` y `buttons` son lo único que separa la ficha de un árbol de
        la de un binding: la segunda no tiene fuente que cargar ni grafo que
        abrir, así que acaba en la descripción y mide menos. El resto —el
        marco, el bloque de icono, la insignia y las columnas— es el mismo
        dibujo, que es de lo que se trata.
        """
        super().__init__(parent)
        self._height = height or style.DB_CARD_HEIGHT
        self._buttons = buttons
        # (fila, clave) del botón bajo el ratón, o None. Lo pone la vista,
        # que es la única que ve los movimientos del ratón; el delegado solo
        # pinta lo que le digan.
        self.hovered: Optional[Tuple[int, str]] = None

    def sizeHint(self, option, index) -> QSize:
        """Alto fijo: la lista lleva `setUniformItemSizes` (~3700 filas)."""
        return QSize(0, self._height)

    def paint(self, painter: QPainter, option, index) -> None:
        """Pinta la ficha entera; nada de esto lo puede hacer el QSS."""
        from PySide6.QtWidgets import QStyle

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        card = QRectF(option.rect).adjusted(0, 0, -1, -1)
        radius = style.DB_CARD_RADIUS
        caja = card_layout(card)

        seleccionado = bool(option.state & QStyle.State_Selected)
        encima = bool(option.state & QStyle.State_MouseOver)
        if seleccionado:
            fondo = style.DB_CARD_SELECTED_BG
        elif encima:
            fondo = style.DB_CARD_HOVER_BG
        else:
            fondo = style.DB_CARD_BG
        painter.setBrush(QBrush(QColor(fondo)))
        borde = (
            style.DB_CARD_SELECTED_BORDER if seleccionado else style.DB_CARD_BORDER
        )
        painter.setPen(QPen(QColor(borde), 1))
        painter.drawRoundedRect(card, radius, radius)

        painter.setBrush(QBrush(QColor(style.DB_CARD_ICON_BG)))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(caja["icon"], radius, radius)
        kind = (index.data(_ROLE_ENTRY) or (KIND_SOC, 0))[0]
        _paint_glyph(
            painter,
            caja["icon"],
            kind,
            style.DB_CARD_ICON_FG,
            index.data(_ROLE_GROUP) or "",
        )

        self._paint_header(painter, caja, index, radius)
        self._paint_columns(painter, caja, index)
        self._paint_footer(painter, caja, index, radius)
        painter.restore()

    def _paint_header(self, painter, caja, index, radius) -> None:
        """Nombre a la izquierda e insignia de tipo a la derecha."""
        badge_font = QFont(style.DB_MONO_FAMILY)
        badge_font.setPointSizeF(style.DB_SMALL_POINT_SIZE)
        painter.setFont(badge_font)
        badge = index.data(_ROLE_BADGE) or ""
        bm = QFontMetrics(badge_font)
        ancho = bm.horizontalAdvance(badge) + 12
        titulo = caja["title"]
        marco = QRectF(titulo.right() - ancho, titulo.top(), ancho, bm.height() + 4)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(style.DB_CARD_BORDER), 1))
        painter.drawRoundedRect(marco, radius, radius)
        painter.setPen(QPen(QColor(style.MUTED_TEXT_COLOR)))
        painter.drawText(marco, Qt.AlignCenter, badge)

        nombre_font = QFont()
        nombre_font.setBold(True)
        painter.setFont(nombre_font)
        painter.setPen(QPen(QColor(style.DB_CARD_TITLE)))
        fm = QFontMetrics(nombre_font)
        hueco = QRectF(
            titulo.left(),
            titulo.top(),
            marco.left() - titulo.left() - 8,
            titulo.height(),
        )
        painter.drawText(
            hueco,
            Qt.AlignVCenter | Qt.AlignLeft,
            fm.elidedText(
                index.data(Qt.DisplayRole) or "", Qt.ElideRight, hueco.width()
            ),
        )

    def _paint_columns(self, painter, caja, index) -> None:
        """Las columnas de dato: su rótulo arriba y el valor debajo."""
        campos: Sequence[Tuple[str, str]] = index.data(_ROLE_FIELDS) or ()
        if not campos:
            return
        zona = caja["columns"]
        etiqueta_font = QFont()
        etiqueta_font.setPointSizeF(style.DB_SMALL_POINT_SIZE)
        valor_font = QFont()
        em = QFontMetrics(etiqueta_font)
        vm = QFontMetrics(valor_font)
        ancho = zona.width() / len(campos)
        for posicion, (etiqueta, valor) in enumerate(campos):
            x = zona.left() + posicion * ancho
            painter.setFont(etiqueta_font)
            painter.setPen(QPen(QColor(style.FAINT_TEXT_COLOR)))
            painter.drawText(
                QRectF(x, zona.top(), ancho, em.height()),
                Qt.AlignVCenter | Qt.AlignLeft,
                etiqueta.upper(),
            )
            painter.setFont(valor_font)
            painter.setPen(QPen(QColor(style.MUTED_TEXT_COLOR)))
            painter.drawText(
                QRectF(x, zona.top() + em.height(), ancho, vm.height()),
                Qt.AlignVCenter | Qt.AlignLeft,
                vm.elidedText(valor, Qt.ElideMiddle, ancho - 8),
            )

    def _hovered_key(self, index) -> Optional[str]:
        """Cuál de los dos botones de ESTA fila tiene el ratón encima."""
        if self.hovered is None or self.hovered[0] != index.row():
            return None
        return self.hovered[1]

    def _paint_footer(self, painter, caja, index, radius) -> None:
        """Descripción, frecuencia y los dos botones."""
        texto_font = QFont()
        texto_font.setPointSizeF(style.DB_TEXT_POINT_SIZE)
        painter.setFont(texto_font)
        fm = QFontMetrics(texto_font)

        descripcion = index.data(_ROLE_DESCRIPTION) or ""
        if descripcion:
            painter.setPen(QPen(QColor(style.MUTED_TEXT_COLOR)))
            zona = caja["description"]
            painter.drawText(
                zona,
                Qt.AlignVCenter | Qt.AlignLeft,
                fm.elidedText(descripcion, Qt.ElideRight, zona.width()),
            )

        if not self._buttons:
            return

        painter.setPen(QPen(QColor(style.FAINT_TEXT_COLOR)))
        painter.drawText(
            caja["clock"],
            Qt.AlignVCenter | Qt.AlignLeft,
            index.data(_ROLE_CLOCK) or "",
        )

        # Los dos botones: el de ver en el grafo relleno de acento y el de
        # abrir con borde, la misma jerarquía que en el resto de la ventana.
        # Cada uno con su icono, dibujado a mano como los demás.
        # Cada botón responde al ratón por su cuenta. El de borde se pinta
        # con el fondo de la ficha **sin señalar** en vez de transparente:
        # así pasar por encima de la fila no lo tiñe de camino, que es lo
        # que hacía parecer que el botón se activaba cuando no.
        encima = self._hovered_key(index)
        for clave, relleno, texto, draw in (
            ("load", False, index.data(_ROLE_LOAD_TEXT) or "", icons.document_icon),
            ("graph", True, index.data(_ROLE_GRAPH_TEXT) or "", icons.tree_icon),
        ):
            marco = caja[clave]
            señalado = encima == clave
            color = (
                style.DB_CARD_ACTION_FG if relleno else style.ACCENT_TEXT_COLOR
            )
            if relleno:
                fondo_boton = (
                    style.DB_CARD_ACTION_HOVER_BG
                    if señalado
                    else style.DB_CARD_ACTION_BG
                )
            else:
                fondo_boton = (
                    style.DB_CARD_BUTTON_HOVER_BG if señalado else style.DB_CARD_BG
                )
            painter.setBrush(QBrush(QColor(fondo_boton)))
            painter.setPen(
                QPen(
                    QColor(
                        style.DB_CARD_SELECTED_BORDER
                        if señalado
                        else style.DB_CARD_BORDER
                    ),
                    1,
                )
            )
            painter.drawRoundedRect(marco, radius, radius)

            lado = style.DB_CARD_BUTTON_ICON
            recortado = fm.elidedText(texto, Qt.ElideRight, marco.width() - lado - 18)
            ancho = fm.horizontalAdvance(recortado)
            inicio = marco.left() + (marco.width() - lado - 6 - ancho) / 2
            painter.drawPixmap(
                QRectF(
                    inicio, marco.center().y() - lado / 2, lado, lado
                ).toRect(),
                _button_glyph(draw, lado, color),
            )
            painter.setPen(QPen(QColor(color)))
            painter.drawText(
                QRectF(
                    inicio + lado + 6,
                    marco.top(),
                    marco.right() - inicio - lado - 6,
                    marco.height(),
                ),
                Qt.AlignVCenter | Qt.AlignLeft,
                recortado,
            )


def _paint_glyph(
    painter: QPainter, box: QRectF, kind: str, color: str, group: str = ""
) -> None:
    """El símbolo del bloque de icono, según lo que sea la ficha.

    `memory` para un SoC, `developer_board` para una placa y, para un
    binding, el icono de su grupo en la paleta de dispositivos: es la misma
    clasificación con la que luego se conecta el dispositivo al árbol, así
    que el mismo dibujo lo identifica en los dos sitios.

    Son los mismos que dibuja `widgets/icons.py` para el resto de la
    ventana: se piden ahí en vez de repetir los trazos aquí, y se cachean
    por (tipo, color) porque el delegado los pide en cada repintado de cada
    fila visible.
    """
    lado = round(box.width() * 0.7)
    clave = (kind, group, color, lado)
    pixmap = _GLYPHS.get(clave)
    if pixmap is None:
        if kind == KIND_BINDING:
            icono = binding_groups.group_icon(group, lado, color)
        else:
            icono = (icons.chip_icon if kind == KIND_SOC else icons.board_icon)(
                lado, color
            )
        pixmap = icono.pixmap(lado, lado)
        _GLYPHS[clave] = pixmap
    painter.drawPixmap(
        QRectF(
            box.center().x() - lado / 2, box.center().y() - lado / 2, lado, lado
        ).toRect(),
        pixmap,
    )


class DatabaseTab(Retranslates, QWidget):
    """Explorador del catálogo: los dos desplegables y la lista de fichas."""

    # Índice dentro de la lista de SoCs / de boards que se ha elegido. Se
    # emite igual desde el desplegable y desde la lista: quien lo abre es
    # `MainWindow`, que es la única que sabe del editor y de la base.
    socChosen = Signal(int)
    boardChosen = Signal(int)
    # «Visual graph» de una ficha: abrir su fuente **y** llevar al grafo. Va
    # aparte de `socChosen`/`boardChosen` porque abrir es lo mismo y lo que
    # cambia es dónde te deja.
    graphRequested = Signal()
    # Compatible cuya ficha de binding se quiere abrir. La ventana es quien
    # abre el diálogo: este widget no tiene el servicio.
    bindingChosen = Signal(str)
    # Hay que rellenar la lista de bindings con este texto y estos dos
    # filtros: la búsqueda va contra la base y no sobre una lista ya cargada
    # (son 25 458), y los filtros van con ella por lo mismo — lo que vuelve
    # está recortado, así que filtrarlo después enseñaría solo lo que
    # cupiera en el recorte. Los subsistemas van resueltos: el agrupado por
    # tipo es de la paleta y vive aquí, no en la base.
    bindingSearchRequested = Signal(str, str, list)

    def __init__(self, parent=None):
        """Monta la cabecera, la fila de desplegables y la lista."""
        super().__init__(parent)
        self._socs: List[SoCSummary] = []
        self._boards: List[SoCSummary] = []
        self._bindings_total = 0
        # Se llenan en `_build_header`, que corre antes que la lista.
        self._view_buttons: Dict[str, QPushButton] = {}
        # Grupo de la paleta -> subsistemas crudos de la base que caen en
        # él. Se arma en `set_binding_filters` con lo que la base tenga, no
        # con la tabla entera de `binding_groups`: un grupo sin un solo
        # dispositivo en esta base no se ofrece.
        self._group_subsystems: Dict[str, List[str]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_header())
        self._filters = self._build_filters()
        layout.addWidget(self._filters)
        self._binding_filters = self._build_binding_filters()
        layout.addWidget(self._binding_filters)

        self.entries = QListWidget()
        self.entries.setObjectName("databaseEntries")
        self.entries.setUniformItemSizes(True)
        self.entries.setSpacing(style.DB_CARD_SPACING)
        self.entries.setMouseTracking(True)
        self._delegate = _EntryDelegate(self.entries)
        self.entries.setItemDelegate(self._delegate)
        self.entries.itemActivated.connect(self._on_entry_activated)
        # Los dos botones de la ficha los pinta el delegado, así que no hay
        # widget al que conectarse: se mira dónde cayó el clic contra el
        # mismo reparto con el que se pintaron (`card_layout`).
        self.entries.viewport().installEventFilter(self)

        # Los bindings comparten hueco con las fichas: es el mismo catálogo
        # visto por el otro lado —qué hardware hay y qué se sabe de cada
        # dispositivo—, y son dos listas que nunca se miran a la vez. Y se
        # enseñan igual, en fichas: era una tabla de tres columnas, que es
        # otra cosa distinta mirando al mismo catálogo, y el compatible
        # solo se leía por su texto —el icono de su grupo dice de qué
        # dispositivo se trata antes de leer nada.
        self.bindings = QListWidget()
        self.bindings.setObjectName("databaseEntries")
        self.bindings.setUniformItemSizes(True)
        self.bindings.setSpacing(style.DB_CARD_SPACING)
        self.bindings.setSelectionMode(QAbstractItemView.SingleSelection)
        self.bindings.setItemDelegate(
            _EntryDelegate(
                self.bindings, height=style.DB_BINDING_CARD_HEIGHT, buttons=False
            )
        )
        self.bindings.itemActivated.connect(self._on_binding_activated)

        self._stack = QStackedWidget()
        self._stack.addWidget(self.entries)
        self._stack.addWidget(self.bindings)
        layout.addWidget(self._stack, 1)

        self.retranslate()

    def _build_header(self) -> QWidget:
        """Título de la vista y buscador libre, en la misma franja."""
        header = QWidget()
        header.setObjectName("viewToolbar")
        row = QHBoxLayout(header)
        row.setContentsMargins(14, 9, 14, 9)
        row.setSpacing(8)

        self._title = QLabel()
        self._title.setObjectName("panelCaption")
        row.addWidget(self._title)

        # Dos pestañas de texto, como las del panel inferior: son dos y
        # siempre las mismas, así que enseñarlas cuesta lo mismo que
        # enseñar una con una flecha al lado.
        for key in (VIEW_TREES, VIEW_BINDINGS):
            tab = QPushButton()
            tab.setObjectName("logTab")
            tab.setCheckable(True)
            tab.setCursor(Qt.PointingHandCursor)
            tab.setChecked(key == VIEW_TREES)
            tab.clicked.connect(lambda _c=False, k=key: self.show_view(k))
            self._view_buttons[key] = tab
            row.addWidget(tab)
        row.addStretch(1)

        self.search = QLineEdit()
        # La lupa dentro del campo, como en el diseño: es lo que dice que
        # ahí se escribe para buscar y no para escribir un valor.
        self.search.addAction(
            icons.search_icon(style.ACTION_ICON_SIZE, style.MUTED_TEXT_COLOR),
            QLineEdit.LeadingPosition,
        )
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(style.DB_SEARCH_WIDTH)
        self.search.textChanged.connect(self._apply_filter)

        # Cuántos se ven de cuántos hay. En la cabecera y no en la franja
        # de filtros porque esa se va con la vista de bindings, que es
        # justo donde el recorte de la búsqueda hay que decirlo.
        self._binding_count = QLabel()
        self._binding_count.setObjectName("viewToolbarStatus")
        row.addWidget(self._binding_count)
        row.addWidget(self.search)
        return header

    def _build_filters(self) -> QWidget:
        """Los dos desplegables que estrechan la lista, cada uno con su rótulo.

        No son editables: no son buscadores. El único sitio donde se escribe
        es la caja de la cabecera; aquí se elige de una lista cerrada, que es
        lo que distingue un filtro de una búsqueda.
        """
        strip = QWidget()
        strip.setObjectName("databaseFilters")
        row = QHBoxLayout(strip)
        row.setContentsMargins(14, 9, 14, 9)
        row.setSpacing(16)

        # El de fabricante es **escribible**: son 541 y una lista cerrada de
        # 541 filas no se recorre. Los otros tres son listas de cinco
        # entradas y ahí escribir no ayuda.
        self.vendor_combo = _vendor_combo(self._on_vendor_typed)
        self.vendor_combo.currentIndexChanged.connect(self._on_filter_changed)

        self.kind_combo = QComboBox()
        self.kind_combo.currentIndexChanged.connect(self._on_filter_changed)
        self.arch_combo = QComboBox()
        self.arch_combo.currentIndexChanged.connect(self._on_filter_changed)
        self.cores_combo = QComboBox()
        self.cores_combo.currentIndexChanged.connect(self._on_filter_changed)
        self.ram_combo = QComboBox()
        self.ram_combo.currentIndexChanged.connect(self._on_filter_changed)

        self._captions = {}
        for name, combo in (
            ("vendor", self.vendor_combo),
            ("kind", self.kind_combo),
            ("arch", self.arch_combo),
            ("cores", self.cores_combo),
            ("ram", self.ram_combo),
        ):
            combo.setMinimumWidth(style.SOC_COMBO_MIN_WIDTH)
            combo.setMaximumWidth(style.DB_FILTER_MAX_WIDTH)
            caption = QLabel()
            caption.setObjectName("filterCaption")
            self._captions[name] = caption
            columna = QVBoxLayout()
            columna.setContentsMargins(0, 0, 0, 0)
            columna.setSpacing(4)
            columna.addWidget(caption)
            columna.addWidget(combo)
            row.addLayout(columna)

        row.addStretch(1)
        self._count_label = QLabel()
        self._count_label.setObjectName("viewToolbarStatus")
        row.addWidget(self._count_label)
        return strip

    def _build_binding_filters(self) -> QWidget:
        """Los dos filtros del catálogo de bindings: fabricante y tipo.

        Franja aparte y no los mismos desplegables de la de hardware, aun
        pareciéndose: son otro vocabulario. Los fabricantes de un
        compatible no son los del catálogo de placas —hay 1 200 que no
        fabrican ninguna—, y «SoC o placa», núcleos y RAM no dicen nada de
        un dispositivo. Un desplegable que cambia de contenido según la
        pestaña obliga a releerlo cada vez para saber sobre qué filtra.

        El tipo es el grupo de la paleta, con su mismo icono: es la
        clasificación con la que el dispositivo se conecta al árbol, y la
        que la ficha ya enseña como glifo. Dos clasificaciones para lo
        mismo serían dos catálogos.
        """
        strip = QWidget()
        strip.setObjectName("databaseFilters")
        row = QHBoxLayout(strip)
        row.setContentsMargins(14, 9, 14, 9)
        row.setSpacing(16)

        self.binding_vendor_combo = _vendor_combo(self._on_binding_vendor_typed)
        self.binding_vendor_combo.currentIndexChanged.connect(
            self._on_binding_filter_changed
        )
        self.device_type_combo = QComboBox()
        self.device_type_combo.currentIndexChanged.connect(
            self._on_binding_filter_changed
        )

        for name, combo in (
            ("binding_vendor", self.binding_vendor_combo),
            ("device_type", self.device_type_combo),
        ):
            combo.setMinimumWidth(style.SOC_COMBO_MIN_WIDTH)
            combo.setMaximumWidth(style.DB_FILTER_MAX_WIDTH)
            caption = QLabel()
            caption.setObjectName("filterCaption")
            self._captions[name] = caption
            columna = QVBoxLayout()
            columna.setContentsMargins(0, 0, 0, 0)
            columna.setSpacing(4)
            columna.addWidget(caption)
            columna.addWidget(combo)
            row.addLayout(columna)

        row.addStretch(1)
        return strip

    # ------------------------------------------------------------------
    # Contenido
    # ------------------------------------------------------------------
    def load(self, socs: Sequence[SoCSummary], boards: Sequence[SoCSummary]) -> None:
        """Puebla la lista y los filtros con el catálogo de la base."""
        self._socs = list(socs)
        self._boards = list(boards)

        self.entries.clear()
        for kind, items in ((KIND_SOC, self._socs), (KIND_BOARD, self._boards)):
            for posicion, item in enumerate(items):
                self.entries.addItem(self._make_item(kind, posicion, item))

        # Los fabricantes salen del propio catálogo, no de una lista escrita
        # a mano: una base construida de otro kernel trae otros, y una lista
        # fija enseñaría fabricantes que no están y escondería los que sí.
        fabricantes = sorted(
            {item.vendor for item in (*self._socs, *self._boards) if item.vendor}
        )
        self.vendor_combo.blockSignals(True)
        self.vendor_combo.clear()
        self.vendor_combo.addItem(self.tr("All vendors"), FILTER_ALL)
        for vendor in fabricantes:
            self.vendor_combo.addItem(vendor, vendor)
        self.vendor_combo.setCurrentIndex(0)
        self.vendor_combo.blockSignals(False)

        # La arquitectura sale igual del catálogo —una base construida de
        # otro kernel no trae estas— pero por familias, no por modelo de
        # núcleo (ver `_ARCH_FAMILIES`), y en el orden de la tabla: son
        # trece y ordenarlas alfabéticamente pone ARC delante de ARM.
        familias = {arch_family(item) for item in (*self._socs, *self._boards)}
        self.arch_combo.blockSignals(True)
        self.arch_combo.clear()
        self.arch_combo.addItem(self.tr("Any architecture"), FILTER_ALL)
        for nombre in _ARCH_FAMILIES.values():
            if nombre in familias:
                self.arch_combo.addItem(nombre, nombre)
        self.arch_combo.setCurrentIndex(0)
        self.arch_combo.blockSignals(False)

        self._apply_filter()

    def show_view(self, view: str) -> None:
        """Cambia entre el catálogo de hardware y el de bindings.

        Cada catálogo se lleva su franja de filtros: arquitectura, núcleos y
        RAM no dicen nada de un binding, y «SoC o placa» tampoco, así que en
        su sitio van los dos que sí —fabricante y tipo de dispositivo— en
        vez de dejar los otros ahí sin efecto.
        """
        for key, button in self._view_buttons.items():
            button.setChecked(key == view)
        self._stack.setCurrentIndex(0 if view == VIEW_TREES else 1)
        self._filters.setVisible(view == VIEW_TREES)
        self._binding_filters.setVisible(view == VIEW_BINDINGS)
        self._binding_count.setVisible(view == VIEW_BINDINGS)
        self.search.setPlaceholderText(
            self.tr("Search by name, compatible, vendor or file…")
            if view == VIEW_TREES
            else self.tr("Search a compatible or a device name…")
        )
        self._apply_filter(self.search.text())

    def current_view(self) -> str:
        """Cuál de los dos catálogos se está enseñando."""
        return VIEW_TREES if self._stack.currentIndex() == 0 else VIEW_BINDINGS

    def set_bindings(self, entries: Sequence[BindingEntry], total: int) -> None:
        """Enseña el resultado de una búsqueda de bindings.

        Con el total delante: la lista viene recortada —son 25 458
        compatibles— y una lista corta sin decir de cuántos sale parece la
        respuesta entera.
        """
        self.bindings.clear()
        for entry in entries:
            self.bindings.addItem(self._make_binding_item(entry))
        self._bindings_total = total
        self._refresh_binding_header(len(entries))

    def set_binding_filters(
        self, vendors: Sequence[str], subsystems: Sequence[str]
    ) -> None:
        """Puebla los dos filtros del catálogo de bindings con lo que hay en la base.

        Ni fabricantes ni tipos escritos a mano, por lo mismo que en el
        catálogo de hardware: una base construida de otro kernel trae otros
        fabricantes y otros directorios de `bindings/`, y una lista fija
        enseñaría los que no están y escondería los que sí.

        Los subsistemas llegan crudos y se agrupan aquí: el grupo es el de
        la paleta, y de cada uno se guarda con qué subsistemas se pide a la
        base, que es lo único que la base entiende.
        """
        self.binding_vendor_combo.blockSignals(True)
        self.binding_vendor_combo.clear()
        self.binding_vendor_combo.addItem(self.tr("All vendors"), FILTER_ALL)
        for vendor in vendors:
            self.binding_vendor_combo.addItem(vendor, vendor)
        self.binding_vendor_combo.setCurrentIndex(0)
        self.binding_vendor_combo.blockSignals(False)

        self._group_subsystems = {}
        for subsystem in subsystems:
            grupo = binding_groups.group_for_subsystem(subsystem)
            self._group_subsystems.setdefault(grupo, []).append(subsystem)

        self.device_type_combo.blockSignals(True)
        self.device_type_combo.clear()
        self.device_type_combo.addItem(self.tr("Any device type"), FILTER_ALL)
        # En el orden curado de la paleta, no alfabético: primero lo que
        # estructura el árbol y «Otros» al final.
        for grupo in binding_groups.GROUP_ORDER:
            if grupo in self._group_subsystems:
                self.device_type_combo.addItem(
                    binding_groups.group_icon(
                        grupo, style.ACTION_ICON_SIZE, style.MUTED_TEXT_COLOR
                    ),
                    binding_groups.group_label(grupo),
                    grupo,
                )
        self.device_type_combo.setCurrentIndex(0)
        self.device_type_combo.blockSignals(False)

    def binding_filters(self) -> Tuple[str, List[str]]:
        """Fabricante elegido y subsistemas del tipo elegido, para la consulta.

        El tipo baja resuelto a subsistemas y no como nombre de grupo: el
        agrupado es de la paleta y la base no lo conoce.
        """
        vendor = self.binding_vendor_combo.currentData() or FILTER_ALL
        grupo = self.device_type_combo.currentData() or FILTER_ALL
        return vendor, list(self._group_subsystems.get(grupo, []))

    def _make_binding_item(self, entry: BindingEntry) -> QListWidgetItem:
        """La ficha de un compatible documentado.

        Los mismos datos que la ficha de hardware enseña de un árbol, pero
        los de un dispositivo: el grupo al que pertenece —el de la paleta,
        que es de donde se conecta— como icono e insignia, el fabricante
        que dice su propio prefijo, y la prosa del binding como
        descripción. El fichero que lo documenta sigue en el tooltip: dice
        de dónde sale el dato, no qué dispositivo es.
        """
        group = binding_groups.group_for_subsystem(entry.subsystem)
        item = QListWidgetItem(entry.compatible)
        item.setData(_ROLE_ENTRY, (KIND_BINDING, 0))
        item.setData(_ROLE_GROUP, group)
        item.setData(_ROLE_BADGE, binding_groups.group_label(group))
        item.setData(
            _ROLE_FIELDS,
            (
                (self.tr("vendor"), entry.vendor or "—"),
                (self.tr("subsystem"), entry.subsystem or "—"),
                (self.tr("documented by"), entry.binding or "—"),
            ),
        )
        item.setData(_ROLE_DESCRIPTION, entry.description or entry.title)
        item.setData(Qt.UserRole, entry.compatible)
        item.setToolTip(
            self.tr("Documented by {binding}").format(binding=entry.binding)
        )
        return item

    def _refresh_binding_header(self, shown: int) -> None:
        """Dice cuántos se ven de cuántos hay."""
        self._binding_count.setText(
            self.tr("{shown} of {total} documented compatibles").format(
                shown=shown, total=self._bindings_total
            )
        )

    def _on_binding_activated(self, item: QListWidgetItem) -> None:
        """Pide abrir la ficha del compatible pulsado."""
        compatible = item.data(Qt.UserRole)
        if compatible:
            self.bindingChosen.emit(compatible)

    def _make_item(self, kind: str, position: int, item: SoCSummary) -> QListWidgetItem:
        """Una entrada de la lista, con lo que el delegado necesita dibujar.

        Los tres datos son los que la base sabe de verdad de cada entrada
        —compatible, fabricante y fichero de origen—; inventarle una
        arquitectura o un número de núcleos, que es lo que enseña el
        mockup, sería escribir en pantalla algo que nadie ha medido.
        """
        entry = QListWidgetItem(item.name)
        entry.setData(_ROLE_ENTRY, (kind, position))
        entry.setData(
            _ROLE_FIELDS,
            (
                (self.tr("architecture"), item.arch or "—"),
                (self.tr("vendor"), item.vendor or "—"),
                (self.tr("cores"), item.cores_label),
                (self.tr("ram"), item.ram_label),
            ),
        )
        entry.setData(_ROLE_DESCRIPTION, item.model or item.compatible or "")
        entry.setData(
            _ROLE_CLOCK, self.tr("Clock: {value}").format(value=item.clock_label)
        )
        entry.setData(_ROLE_LOAD_TEXT, self.tr("Load DTS"))
        entry.setData(_ROLE_GRAPH_TEXT, self.tr("Visual graph"))
        entry.setData(
            _ROLE_BADGE, self.tr("SoC") if kind == KIND_SOC else self.tr("Board")
        )
        entry.setData(_ROLE_VENDOR, item.vendor or "")
        entry.setData(_ROLE_ARCH, arch_family(item))
        entry.setData(
            _ROLE_HAYSTACK,
            " ".join(
                filter(None, (item.name, item.compatible, item.vendor, item.file_path))
            ).lower(),
        )
        entry.setToolTip(
            self.tr("{compatible}\n{path}").format(
                compatible=item.compatible or "", path=item.file_path or ""
            )
        )
        return entry

    def _summary_of(self, entry: QListWidgetItem) -> SoCSummary:
        """La entrada del catálogo a la que corresponde una ficha."""
        kind, position = entry_ref(entry)
        lista = self._socs if kind == KIND_SOC else self._boards
        return lista[position]

    def _on_vendor_typed(self) -> None:
        """Resuelve lo escrito en el fabricante del hardware (ver `_resolve_vendor`)."""
        _resolve_vendor(self.vendor_combo)

    def _on_binding_vendor_typed(self) -> None:
        """Lo mismo para el fabricante del catálogo de bindings."""
        _resolve_vendor(self.binding_vendor_combo)

    def _on_filter_changed(self, _index: int = 0) -> None:
        """Los dos desplegables acaban en el mismo sitio que el buscador."""
        self._apply_filter()

    def _on_binding_filter_changed(self, _index: int = 0) -> None:
        """Cambiar un filtro de bindings es pedir la búsqueda otra vez.

        Otra vez a la base y no un repaso de lo que hay en la lista: lo que
        hay son las primeras 300 de 25 458 (ver `bindingSearchRequested`).
        """
        self._apply_filter()

    def _apply_filter(self, _text: str = "") -> None:
        """Filtra la vista que esté delante (ver `_filter_entries`)."""
        if self.current_view() == VIEW_BINDINGS:
            # La búsqueda va contra la base y no sobre lo que haya cargado:
            # son 25 458 compatibles y traerlos todos para esconder filas
            # sería cargar el catálogo entero por cada letra.
            vendor, subsystems = self.binding_filters()
            self.bindingSearchRequested.emit(self.search.text(), vendor, subsystems)
            return
        self._filter_entries()

    def _filter_entries(self) -> None:
        """Aplica a la vez el texto buscado y los dos filtros.

        Los tres son condiciones sobre la misma lista, así que se resuelven
        en una pasada: filtrar por separado obligaría a recorrerla tres
        veces y a decidir en qué orden, que además no es lo que el usuario
        ve —él ve una lista que se estrecha.
        """
        needle = self.search.text().strip().lower()
        vendor = self.vendor_combo.currentData() or FILTER_ALL
        kind = self.kind_combo.currentData() or FILTER_ALL
        arch = self.arch_combo.currentData() or FILTER_ALL
        cores = self.cores_combo.currentData() or FILTER_ALL
        ram = self.ram_combo.currentData() or FILTER_ALL
        visibles = 0
        for row in range(self.entries.count()):
            entry = self.entries.item(row)
            item = self._summary_of(entry)
            oculto = (
                (bool(needle) and needle not in (entry.data(_ROLE_HAYSTACK) or ""))
                or (bool(vendor) and entry.data(_ROLE_VENDOR) != vendor)
                or (bool(kind) and entry_ref(entry)[0] != kind)
                or (bool(arch) and entry.data(_ROLE_ARCH) != arch)
                or not _matches_threshold(item.cores, cores)
                or not _matches_threshold(item.ram, ram)
            )
            entry.setHidden(oculto)
            visibles += not oculto
        self._count_label.setText(
            self.tr("{count} of {total}").format(
                count=visibles, total=self.entries.count()
            )
        )

    def eventFilter(self, obj, event):
        """Traduce el ratón sobre los botones pintados: pulsarlos y señalarlos."""
        from PySide6.QtCore import QEvent

        if obj is self.entries.viewport():
            if event.type() == QEvent.MouseButtonRelease:
                clave, entry = self._button_at(event.position())
                if clave is not None:
                    self._on_entry_activated(entry)
                    if clave == "graph":
                        self.graphRequested.emit()
                    return True
            elif event.type() == QEvent.MouseMove:
                self._set_hovered(*self._button_at(event.position()))
            elif event.type() == QEvent.Leave:
                self._set_hovered(None, None)
        return super().eventFilter(obj, event)

    def _button_at(self, punto):
        """Qué botón hay en ese punto del viewport, y de qué ficha.

        Devuelve `(clave, entrada)`, o `(None, entrada)` si el punto cae en
        la ficha pero fuera de los botones. Mismo reparto con el que se
        pintaron (`card_layout`), que es lo que evita que pintar y acertar
        se separen.
        """
        entry = self.entries.itemAt(punto.toPoint())
        if entry is None:
            return (None, None)
        caja = card_layout(QRectF(self.entries.visualItemRect(entry)))
        for clave in ("load", "graph"):
            if caja[clave].contains(punto):
                return (clave, entry)
        return (None, entry)

    def _set_hovered(self, clave, entry) -> None:
        """Marca el botón bajo el ratón y repinta solo lo que cambia."""
        nuevo = None if clave is None else (self.entries.row(entry), clave)
        if nuevo == self._delegate.hovered:
            return
        anterior = self._delegate.hovered
        self._delegate.hovered = nuevo
        # La mano dice que eso se pulsa: los botones los pinta el delegado,
        # así que no hay widget que lo haga por su cuenta.
        self.entries.viewport().setCursor(
            Qt.PointingHandCursor if nuevo else Qt.ArrowCursor
        )
        for fila in {posicion[0] for posicion in (anterior, nuevo) if posicion}:
            item = self.entries.item(fila)
            if item is not None:
                self.entries.viewport().update(self.entries.visualItemRect(item))

    def _on_entry_activated(self, entry: QListWidgetItem) -> None:
        """Traduce el doble clic en la ficha a la señal que abre su fuente."""
        kind, position = entry_ref(entry)
        (self.socChosen if kind == KIND_SOC else self.boardChosen).emit(position)

    def select_entry(self, kind: str, position: int) -> None:
        """Marca y enseña la ficha de una entrada abierta desde otro sitio.

        La paleta de comandos abre por nombre sin pasar por aquí; si luego
        se viene a esta vista, la lista tiene que estar señalando lo que hay
        en pantalla y no lo último que se pulsó en ella.
        """
        for row in range(self.entries.count()):
            entry = self.entries.item(row)
            if entry_ref(entry) == (kind, position):
                self.entries.setCurrentItem(entry)
                self.entries.scrollToItem(entry)
                return

    def refresh_icons(self) -> None:
        """Redibuja la lupa y vacía la caché de glifos de las fichas.

        Los glifos están cacheados por (tipo, color, tamaño), así que con
        otra paleta la clave ya es otra y se regeneran solos; lo que hay que
        rehacer a mano es la lupa, que se metió en el campo una sola vez.
        """
        for action in self.search.actions():
            action.setIcon(
                icons.search_icon(style.ACTION_ICON_SIZE, style.MUTED_TEXT_COLOR)
            )

    def retranslate(self) -> None:
        """Rehace los textos fijos (ver `Retranslates`).

        Las fichas no: sus etiquetas están dentro de los datos de cada ítem
        y se rehacen al volver a poblar la lista, que es lo que `MainWindow`
        hace al arrancar. Cambiar de idioma con la base ya cargada las deja
        como estaban hasta la siguiente carga — es lo mismo que ya pasa con
        el resto de contenido que viene de la base.
        """
        self._title.setText(self.tr("DATABASE EXPLORER"))
        self._view_buttons[VIEW_TREES].setText(self.tr("Device trees"))
        self._view_buttons[VIEW_BINDINGS].setText(self.tr("Bindings"))
        self._view_buttons[VIEW_BINDINGS].setToolTip(
            self.tr(
                "Every compatible the database documents. Open one to see "
                "what its binding requires and admits."
            )
        )
        self.show_view(self.current_view())
        self._refresh_binding_header(self.bindings.count())
        for name, texto in (
            ("vendor", self.tr("VENDOR")),
            ("kind", self.tr("TYPE")),
            ("arch", self.tr("ARCHITECTURE")),
            ("cores", self.tr("CORES")),
            ("ram", self.tr("RAM")),
            ("binding_vendor", self.tr("VENDOR")),
            ("device_type", self.tr("DEVICE TYPE")),
        ):
            self._captions[name].setText(texto)

        self.vendor_combo.setToolTip(
            self.tr("Show only one vendor's hardware. You can type in it.")
        )
        self.kind_combo.setToolTip(self.tr("Show only SoCs, or only boards."))
        self.arch_combo.setToolTip(self.tr("Show only one CPU architecture."))
        self.cores_combo.setToolTip(self.tr("Show hardware with at least N cores."))
        self.ram_combo.setToolTip(self.tr("Show hardware with at least this RAM."))
        self.binding_vendor_combo.setToolTip(
            self.tr(
                "Show only one vendor's devices, by the compatible's own "
                "prefix. You can type in it."
            )
        )
        self.device_type_combo.setToolTip(
            self.tr("Show only one kind of device, grouped as in the palette.")
        )

        # Las listas cerradas están traducidas, así que se rehacen enteras
        # conservando lo elegido.
        self._refill_closed(
            self.kind_combo,
            (
                (FILTER_ALL, self.tr("SoCs and boards")),
                (KIND_SOC, self.tr("SoCs only")),
                (KIND_BOARD, self.tr("Boards only")),
            ),
        )
        self._refill_closed(
            self.cores_combo,
            (
                (FILTER_ALL, self.tr("Any number")),
                (2, self.tr("2 or more")),
                (4, self.tr("4 or more")),
                (8, self.tr("8 or more")),
            ),
        )
        self._refill_closed(
            self.ram_combo,
            (
                (FILTER_ALL, self.tr("Any size")),
                (512 << 20, self.tr("512 MB or more")),
                (1 << 30, self.tr("1 GB or more")),
                (4 << 30, self.tr("4 GB or more")),
            ),
        )

        # Los rótulos de «todos» de las listas que salen del catálogo.
        if self.vendor_combo.count():
            self.vendor_combo.setItemText(0, self.tr("All vendors"))
        if self.arch_combo.count():
            self.arch_combo.setItemText(0, self.tr("Any architecture"))
        self._apply_filter()

    def _refill_closed(self, combo, options) -> None:
        """Rehace un desplegable de lista cerrada sin perder lo elegido."""
        elegido = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for value, label in options:
            combo.addItem(label, value)
        indice = combo.findData(elegido)
        combo.setCurrentIndex(max(indice, 0))
        combo.blockSignals(False)


