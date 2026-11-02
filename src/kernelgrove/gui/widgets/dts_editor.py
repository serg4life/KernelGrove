"""Editor de texto para fuentes Device Tree, con numeración y resaltado.

Incluye lo mínimo que hace usable un editor de código: números de línea,
coloreado de la sintaxis DTS, marcado de las líneas con diagnósticos y
autocompletado.

El editor **no sabe qué ofrecer**: pide las sugerencias a quien le haya puesto
un proveedor (`set_completion_provider`), que es `EditorTab`, el único que
conoce el documento y la base de bindings. Aquí solo está la mecánica de
mostrar la lista, insertar lo elegido y avisar de que se ha insertado, por si
lo elegido lleva una segunda lista detrás (los valores de un `enum`).
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, NamedTuple, Optional, Tuple

from PySide6.QtCore import (
    QPoint,
    QPointF,
    QRect,
    QRegularExpression,
    QSize,
    QStringListModel,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPolygonF,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
)
from PySide6.QtWidgets import QCompleter, QPlainTextEdit, QTextEdit, QWidget

from kernelgrove.api import Diagnostic, Severity, find_matching_brace
from kernelgrove.gui import style
from kernelgrove.gui.translations import Retranslates
from kernelgrove.gui.widgets.find_bar import FindBar
from kernelgrove.gui.widgets.regex_highlighter import RegexHighlighter

# Colores en `gui/style.py`; aquí solo los nombres cortos que usa el resto
# del fichero.
def severity_background(severity: Severity) -> str:
    """Fondo de línea de un diagnóstico, en el modo activo.

    Función y no diccionario de módulo: con dos modos, una tabla construida
    al importar se queda con los colores del que hubiera al arrancar.
    """
    return {
        Severity.ERROR: style.EDITOR_SEVERITY_ERROR_BG,
        Severity.WARNING: style.EDITOR_SEVERITY_WARNING_BG,
        Severity.INFO: style.EDITOR_SEVERITY_INFO_BG,
    }[severity]

# Bandas del minimapa, en los colores de VS Code (`minimap.errorHighlight`
# y `warningHighlight`). INFO no aparece: es la severidad más numerosa con
# diferencia y una banda por cada una dejaría el minimapa lleno.
def severity_mark(severity: Severity) -> Optional[str]:
    """Color de la banda del minimapa, o `None` si esa severidad no lleva."""
    return {
        Severity.ERROR: style.MINIMAP_ERROR_HIGHLIGHT,
        Severity.WARNING: style.MINIMAP_WARNING_HIGHLIGHT,
    }.get(severity)

# Colores del emparejado de llaves: verde cuando se encuentra la pareja, rojo
# cuando la llave está huérfana (justo el caso que hay que ver de un vistazo).

# Coincidencias de la búsqueda (Ctrl+F): un amarillo apagado para todas, uno
# más marcado para la actual, igual que distingue VS Code.

# Fondo de las líneas añadidas (`set_added_lines`): morado dioxazina, igual
# idea que el borde de un nodo conectado en el grafo (`COLOR_GENERATED` en
# `tree_graph.py`) — antes era amarillo y se confundía con el de los avisos
# de severidad WARNING; ahora "morado" es consistente en toda la app.

# Caracteres que pueden formar parte de un nombre de propiedad de device tree
# (§2.2.4 de la especificación). Delimitan el prefijo que se está escribiendo.
_NAME_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789,._+-#"
)

# A partir de cuántos caracteres escritos aparece la lista sola. Con uno solo
# saldría constantemente y estorbaría más que ayuda.
_MIN_PREFIX = 2


class CompletionItem(NamedTuple):
    """Una sugerencia lista para mostrar e insertar."""

    # Lo que se ve en la lista: nombre y, detrás, tipo y obligatoriedad.
    label: str
    # Texto que sustituye a lo que se estaba escribiendo.
    insert: str
    # Cuántos caracteres retroceder tras insertar, para dejar el cursor dentro
    # del valor (`clock-frequency = <|>;`).
    cursor_back: int = 0
    # Identificador estable de la sugerencia (el nombre de la propiedad o el
    # valor), con el que se avisa a quien la proveyó.
    key: str = ""


class DtsHighlighter(RegexHighlighter):
    """Colorea nodos, propiedades, valores y comentarios de un fuente DTS."""

    def __init__(self, document: QTextDocument):
        """Define las reglas de coloreado por expresión regular."""
        super().__init__(document)

        def make(color: str, bold: bool = False) -> QTextCharFormat:
            """Crea un formato de texto con el color (y grosor) indicados."""
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold:
                fmt.setFontWeight(QFont.Bold)
            return fmt

        self._rules = [
            # Cabecera de nodo: "label: nombre@dirección {"
            (QRegularExpression(r"^\s*[\w-]+\s*:"), make(*style.EDITOR_SYNTAX_LABEL)),
            (
                QRegularExpression(r"[\w,.+-]+@[0-9a-fA-F]+\s*(?=\{)"),
                make(*style.EDITOR_SYNTAX_UNIT_ADDRESS),
            ),
            # Propiedades antes del "="
            (
                QRegularExpression(r"^\s*[#\w,.+-]+(?=\s*=)"),
                make(*style.EDITOR_SYNTAX_PROPERTY),
            ),
            # Valores
            (QRegularExpression(r'"[^"]*"'), make(*style.EDITOR_SYNTAX_STRING_VALUE)),
            (QRegularExpression(r"<[^>]*>"), make(*style.EDITOR_SYNTAX_CELL_VALUE)),
            (QRegularExpression(r"&[\w-]+"), make(*style.EDITOR_SYNTAX_REFERENCE)),
            # Directivas del preprocesador y del propio DTS
            (
                QRegularExpression(r"^\s*#\s*\w+.*$"),
                make(*style.EDITOR_SYNTAX_DIRECTIVE),
            ),
            (QRegularExpression(r"/[\w-]+/"), make(*style.EDITOR_SYNTAX_DIRECTIVE)),
            # Comentarios (van los últimos para pisar al resto)
            (QRegularExpression(r"//[^\n]*"), make(*style.EDITOR_SYNTAX_COMMENT)),
        ]


class DiffHighlighter(RegexHighlighter):
    """Colorea la salida de `git diff`: añadido, quitado, cabecera de tramo.

    Vive junto a `DtsHighlighter` porque es lo mismo con otras cuatro reglas,
    y lo usa el mismo `DtsEditor`: una versión o un cambio se abren como una
    pestaña más, en solo lectura (ver `EditorTab.open_source`).
    """

    def __init__(self, document: QTextDocument):
        """Cuatro reglas, en orden: quitado, añadido, tramo y cabecera."""
        super().__init__(document)

        def make(color: str, bold: bool = False) -> QTextCharFormat:
            """Crea un formato de texto con el color (y grosor) indicados."""
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold:
                fmt.setFontWeight(QFont.Bold)
            return fmt

        self._rules = [
            # `---`/`+++` son cabeceras, no líneas quitadas/añadidas: por eso
            # las de contenido piden que el segundo carácter no repita.
            (
                QRegularExpression(r"^-(?!--).*$"),
                make(*style.DIFF_SYNTAX_REMOVED),
            ),
            (
                QRegularExpression(r"^\+(?!\+\+).*$"),
                make(*style.DIFF_SYNTAX_ADDED),
            ),
            (QRegularExpression(r"^@@.*$"), make(*style.DIFF_SYNTAX_HUNK)),
            (
                QRegularExpression(r"^(diff |index |--- |\+\+\+ |commit |new file|"
                                   r"deleted file|similarity|rename ).*$"),
                make(*style.DIFF_SYNTAX_HEADER),
            ),
        ]


class OverlayLogHighlighter(RegexHighlighter):
    """Colorea el registro de comprobación de overlays.

    Vive aquí por lo mismo que `DiffHighlighter`: es el mismo mecanismo con
    otras cinco reglas. Y las reglas miran el **glifo** con el que empieza
    la línea, nunca su texto: el informe está traducido y colorear por la
    palabra «passed» dejaría el registro en gris en cuanto se cambiara de
    idioma. Quien escribe el informe pone el glifo (`overlay_list`,
    `MainWindow._compile_selected`), que es además lo que lo hace legible
    sin color.
    """

    def __init__(self, document: QTextDocument):
        """Cinco reglas, todas por el glifo con el que empieza la línea."""
        super().__init__(document)

        def make(color: str, bold: bool = False) -> QTextCharFormat:
            """Crea un formato de texto con el color (y grosor) indicados."""
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold:
                fmt.setFontWeight(QFont.Bold)
            return fmt

        self._rules = [
            (QRegularExpression(r"^\s*·.*$"), make(*style.LOG_SYNTAX_DETAIL)),
            (QRegularExpression(r"^\s*✓.*$"), make(*style.LOG_SYNTAX_OK)),
            (QRegularExpression(r"^\s*✗.*$"), make(*style.LOG_SYNTAX_ERROR)),
            (QRegularExpression(r"^\s*!.*$"), make(*style.LOG_SYNTAX_WARNING)),
            # La cabecera de cada informe: hora, fichero y una regla encima.
            (
                QRegularExpression(r"^(─+|\d\d:\d\d:\d\d .*)$"),
                make(*style.LOG_SYNTAX_HEADER),
            ),
        ]


class _LineNumberArea(QWidget):
    """Franja lateral donde se pintan los números de línea."""

    def __init__(self, editor: "DtsEditor"):
        """Se asocia al editor cuyo desplazamiento debe seguir."""
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        """Ancho necesario para el número de línea más largo."""
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        """Delega el pintado en el editor, que conoce los bloques visibles."""
        self._editor.paint_line_numbers(event)

    def mousePressEvent(self, event) -> None:
        """Clic en la flecha de plegado: el resto del margen no hace nada."""
        self._editor.handle_gutter_click(event.position().toPoint())


class _Minimap(QWidget):
    """Vista en miniatura del fichero entero, pegada al borde derecho.

    Sirve para dos cosas a la vez, y la segunda es la que la justifica: para
    saltar a cualquier punto de un `.dtsi` de miles de líneas sin recorrer la
    barra de desplazamiento a ciegas, y para **ver dónde está lo que hay que
    mirar** — los cambios sin guardar y los errores y avisos, con los mismos
    colores que en el margen, pero sobre el fichero completo en vez de sobre
    la pantalla que se está viendo.

    No dibuja texto. A esta escala no se leería, y renderizarlo obligaría a
    pasar el resaltador por el fichero entero en cada repintado; una barra
    del ancho de cada línea da la misma forma reconocible por la que uno se
    orienta en un fichero que conoce.
    """

    def __init__(self, editor: "DtsEditor"):
        """Se asocia al editor cuyo contenido resume."""
        super().__init__(editor)
        self._editor = editor
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self) -> QSize:
        """Ancho fijo; el alto lo pone el editor."""
        return QSize(style.MINIMAP_WIDTH, 0)

    # ------------------------------------------------------------------
    # Pintado
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        """La silueta del fichero, las marcas y el recuadro de lo que se ve."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(style.MINIMAP_BG))

        if self.height() <= 0:
            return

        marca = style.MINIMAP_MARK_WIDTH
        izquierda = marca + 2
        util = max(1, self.width() - izquierda - 2)
        paso = self._step()
        grueso = max(1, int(paso))

        # El recuadro de lo que se ve va **debajo** de todo lo demás: si se
        # pinta encima, en un fichero corto -donde ocupa el minimapa entero-
        # tapa la silueta y las marcas, y el minimapa se queda en una caja
        # de color sin información.
        self._paint_viewport(painter, paso)

        painter.setPen(Qt.NoPen)
        color_linea = QColor(style.MINIMAP_LINE_COLOR)
        for numero, ancho in self._editor.line_shapes():
            largo = int(util * ancho)
            if largo <= 0:
                continue
            painter.fillRect(
                izquierda, int(numero * paso), largo, grueso, color_linea
            )

        self._paint_marks(painter, paso, grueso)

    def _paint_marks(self, painter: QPainter, paso: float, grueso: int) -> None:
        """Cambios de git al borde izquierdo, diagnósticos sobre la línea.

        El reparto es el de VS Code, y el motivo se ve en un fichero real:
        un cambio se busca recorriendo el borde, y para eso basta una franja
        fina; un error hay que verlo aunque no se esté buscando, y una marca
        de tres píxeles al otro borde se pierde entre la silueta.
        """
        marca = style.MINIMAP_MARK_WIDTH
        # Suelo de tres píxeles: en un fichero de miles de líneas una marca
        # de un píxel de alto no se encuentra, y encontrarlas es justo para
        # lo que está el minimapa.
        alto = max(3, grueso)
        for line in range(1, self._editor.blockCount() + 1):
            arriba = int((line - 1) * paso)
            severity = self._editor.diagnostic_severity(line)
            color = severity_mark(severity) if severity else None
            if color is not None:
                banda = QColor(color)
                banda.setAlpha(style.MINIMAP_HIGHLIGHT_ALPHA)
                painter.fillRect(marca, arriba, self.width() - marca, alto, banda)
            change = self._editor.change_color(line)
            if change is not None:
                painter.fillRect(0, arriba, marca, alto, QColor(change))

    def _paint_viewport(self, painter: QPainter, paso: float) -> None:
        """Recuadro de las líneas que se están viendo en el editor."""
        first, last = self._editor.visible_line_range()
        top = int((first - 1) * paso)
        height = max(4, int((last - first + 1) * paso))
        painter.fillRect(
            0, top, self.width(), height, QColor(style.MINIMAP_VIEWPORT_BG)
        )
        painter.setPen(QColor(style.MINIMAP_VIEWPORT_BORDER))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(0, top, self.width() - 1, height - 1)
        painter.setPen(Qt.NoPen)

    def _step(self) -> float:
        """Altura de una línea en el minimapa.

        Con tope (`MINIMAP_MAX_LINE_HEIGHT`) para que un fichero corto no se
        estire hasta llenar la franja, y sin suelo: en uno más largo que la
        franja varias líneas caen en la misma fila y se pintan encima unas
        de otras, que es exactamente el resumen que se quiere.
        """
        total = max(1, self._editor.blockCount())
        return min(style.MINIMAP_MAX_LINE_HEIGHT, max(1, self.height()) / total)

    # ------------------------------------------------------------------
    # Navegación
    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        """Salta a la línea pulsada."""
        self._scroll_to(event.position().y())

    def mouseMoveEvent(self, event) -> None:
        """Arrastrar recorre el fichero, como la barra de desplazamiento."""
        if event.buttons() & Qt.LeftButton:
            self._scroll_to(event.position().y())

    def _scroll_to(self, y: float) -> None:
        """Centra el editor en la línea que corresponde a la altura `y`."""
        total = max(1, self._editor.blockCount())
        line = min(total, max(1, int(y / self._step()) + 1))
        self._editor.center_on_line(line)


class DtsEditor(Retranslates, QPlainTextEdit):
    """Editor de fuentes Device Tree con números de línea y diagnósticos."""

    # Ctrl+clic sobre el texto: línea (1-based) y columna dentro de ella
    # (0-based). El editor no sabe de DTS ni de includes —eso es cosa de
    # `EditorTab`, que conoce el resultado del análisis—; aquí solo se informa
    # de dónde se ha hecho el clic. La columna hace falta porque en una misma
    # línea puede haber más de un destino al que ir (`&a`, `&b`), a diferencia
    # de un include, que ocupa la línea entera.
    ctrlLineClicked = Signal(int, int)

    # Clic normal sobre una línea (1-based). Igual que el anterior, el
    # editor no sabe qué hay ahí; quien escucha decide. Lo usa el asistente
    # de overlays para que «elegir el nodo» sea señalarlo en el fuente.
    lineClicked = Signal(int)

    # El ratón se ha movido sobre el texto: línea (1-based), columna dentro
    # de la línea (0-based) y si Ctrl estaba pulsado en ese momento. Sirve
    # para que `EditorTab` decida si ahí hay un include y pida `set_include_
    # hint` para subrayarlo — el propio editor no sabe qué es un include,
    # solo dónde está el ratón.
    hoverMoved = Signal(int, int, bool)

    # Se ha insertado una sugerencia (su `key`). Quien provee las sugerencias
    # decide si detrás va otra lista: al aceptar una propiedad con `enum`, lo
    # siguiente que hace falta son sus valores.
    completionInserted = Signal(str)

    def __init__(self, parent=None, highlighter=DtsHighlighter):
        """Configura la fuente monoespaciada, el resaltador y el margen.

        `highlighter` se puede cambiar porque el mismo editor sirve para
        enseñar un diff (`DiffHighlighter`) además de un fuente DTS; el
        resto del comportamiento —números de línea, plegado, búsqueda— vale
        igual para los dos.
        """
        super().__init__(parent)
        # Pila de familias, no `QFont("monospace")`: ese nombre genérico lo
        # resuelve fontconfig a lo que haya, que en muchos sistemas es una
        # fuente de mapa de bits con poco contraste entre `0`/`O` y `1`/`l`
        # — justo lo que hay que distinguir en un `reg = <0x0 0xff010000>`.
        editor_font = QFont()
        editor_font.setFamilies(style.EDITOR_FONT_FAMILIES)
        editor_font.setStyleHint(QFont.Monospace)
        editor_font.setFixedPitch(True)
        self.setFont(editor_font)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabStopDistance(32)
        self.retranslate()

        self._highlighter = highlighter(self.document())
        self._line_numbers = _LineNumberArea(self)
        self._minimap = _Minimap(self)
        # Silueta del fichero para el minimapa: (índice 0-based, 0..1 de lo
        # llena que está la línea). Se recalcula al cambiar el texto y no en
        # cada repintado — el minimapa se repinta con cada desplazamiento y
        # recorrer un `.dtsi` de 6000 líneas por scroll sí se notaría.
        self._line_shapes: List[Tuple[int, float]] = []
        self._diagnostic_lines: Dict[int, Severity] = {}
        self._added_lines: set = set()
        # Barra de cambios del margen: qué líneas no están en la última
        # versión guardada en git (ver `set_change_lines`).
        self._added_changes: set = set()
        self._modified_lines: set = set()
        self._deleted_lines: set = set()

        # Plegado de nodos: `_fold_regions` (línea de apertura -> línea de
        # cierre, ambas 1-based) se recalcula tras cada cambio de texto;
        # `_folded` es el subconjunto actualmente plegado. Las líneas
        # ocultas son un mecanismo nativo de Qt (`QTextBlock.setVisible`),
        # no un truco propio: el resto del editor (numeración, cursor,
        # scroll) ya sabe tratar un bloque invisible como de alto cero.
        self._fold_regions: Dict[int, int] = {}
        self._folded: Dict[int, int] = {}

        # Para el subrayado de includes al pasar el ratón con Ctrl pulsado:
        # posición conocida del ratón (para recalcular si Ctrl se suelta o se
        # pulsa sin que el ratón se mueva) y el tramo subrayado actualmente.
        self.setMouseTracking(True)
        self._last_mouse_pos: Optional[QPoint] = None
        self._hint: Optional[Tuple[int, int, int]] = None
        # Bloque de líneas del nodo señalado mientras se elige el objetivo de
        # un overlay (ver `set_node_hint`).
        self._node_hint: Optional[Tuple[int, int]] = None

        self._completion_provider: Optional[Callable] = None
        self._completion_items: Dict[str, CompletionItem] = {}
        self._completer = QCompleter(self)
        self._completer.setWidget(self)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setModel(QStringListModel([], self._completer))
        self._completer.activated[str].connect(self._insert_completion)

        # Búsqueda (Ctrl+F): la barra es una superposición flotante, no ocupa
        # espacio del layout mientras está oculta. `_search_matches` guarda
        # los tramos (inicio, fin) de cada coincidencia en el texto completo.
        self._search_term = ""
        self._search_matches: List[Tuple[int, int]] = []
        self._search_current = -1
        self._find_bar = FindBar(self)
        self._find_bar.queryChanged.connect(self._update_search)
        self._find_bar.findNext.connect(self._find_next)
        self._find_bar.findPrevious.connect(self._find_previous)
        self._find_bar.closed.connect(self._close_find_bar)

        # El atajo Ctrl+F NO se registra aquí: lo tiene la acción del menú
        # «Editar → Buscar…», que lo dirige al editor con el foco
        # (`MainWindow.find_in_document`). Con los dos registrados, Qt los ve
        # como el mismo atajo por duplicado —"Ambiguous shortcut overload"— y
        # deja de disparar **ninguno**: la búsqueda se quedaba muerta.

        self.textChanged.connect(self._refresh_line_shapes)
        self.blockCountChanged.connect(self._update_margin)
        self.updateRequest.connect(self._update_line_number_area)
        self.verticalScrollBar().valueChanged.connect(self._minimap.update)
        self.cursorPositionChanged.connect(self._refresh_selections)
        self.textChanged.connect(self._on_text_changed_for_search)
        self.textChanged.connect(self._refresh_fold_regions)

        self._update_margin()

    # ------------------------------------------------------------------
    # Números de línea
    # ------------------------------------------------------------------
    def line_number_area_width(self) -> int:
        """Ancho del margen: barra de cambios + plegado + dígitos de la última línea."""
        digits = max(2, len(str(max(1, self.blockCount()))))
        return (
            style.EDITOR_CHANGE_BAR_WIDTH
            + style.EDITOR_FOLD_MARKER_WIDTH
            + 12
            + self.fontMetrics().horizontalAdvance("9") * digits
        )

    def _update_margin(self) -> None:
        """Reserva el margen de números a la izquierda y el minimapa a la derecha."""
        self.setViewportMargins(
            self.line_number_area_width(), 0, style.MINIMAP_WIDTH, 0
        )

    def _update_line_number_area(self, rect: QRect, dy: int) -> None:
        """Repinta o desplaza el margen al moverse el editor."""
        if dy:
            self._line_numbers.scroll(0, dy)
        else:
            self._line_numbers.update(
                0, rect.y(), self._line_numbers.width(), rect.height()
            )
        if rect.contains(self.viewport().rect()):
            self._update_margin()

    def resizeEvent(self, event) -> None:
        """Reajusta el margen y la barra de búsqueda al cambiar el tamaño del editor."""
        super().resizeEvent(event)
        contents = self.contentsRect()
        self._line_numbers.setGeometry(
            QRect(
                contents.left(),
                contents.top(),
                self.line_number_area_width(),
                contents.height(),
            )
        )
        # Pegado al borde derecho y de arriba abajo: empieza en la esquina
        # superior derecha y llega al final porque resume el fichero
        # **entero**; recortado a media altura no se podría saltar a la
        # segunda mitad. Se coloca a partir del `viewport`, no del
        # `contentsRect`, porque este último incluye la barra de
        # desplazamiento y el minimapa acabaría debajo de ella.
        viewport = self.viewport().geometry()
        self._minimap.setGeometry(
            QRect(
                viewport.right() + 1,
                contents.top(),
                style.MINIMAP_WIDTH,
                contents.height(),
            )
        )
        self._position_find_bar()

    def paint_line_numbers(self, event) -> None:
        """Dibuja los números de las líneas visibles y la flecha de plegado."""
        painter = QPainter(self._line_numbers)
        painter.fillRect(event.rect(), QColor(style.EDITOR_LINE_NUMBER_BG))

        bar_width = style.EDITOR_CHANGE_BAR_WIDTH
        marker_width = bar_width + style.EDITOR_FOLD_MARKER_WIDTH
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                line = number + 1
                severity = self._diagnostic_lines.get(line)
                if severity is Severity.ERROR:
                    painter.setPen(QColor(style.EDITOR_ERROR_ACCENT))
                elif severity is Severity.WARNING:
                    painter.setPen(QColor(style.EDITOR_WARNING_ACCENT))
                else:
                    painter.setPen(QColor(style.EDITOR_INFO_ACCENT))
                painter.drawText(
                    marker_width,
                    int(top),
                    self._line_numbers.width() - marker_width - 6,
                    self.fontMetrics().height(),
                    Qt.AlignRight,
                    str(line),
                )

                if line in self._fold_regions:
                    painter.setPen(QColor(style.EDITOR_FOLD_MARKER_COLOR))
                    arrow = "▸" if line in self._folded else "▾"
                    painter.drawText(
                        bar_width,
                        int(top),
                        marker_width - bar_width,
                        self.fontMetrics().height(),
                        Qt.AlignCenter,
                        arrow,
                    )

                # La barra de cambios va pegada al borde izquierdo, antes de
                # la flecha de plegado: es lo primero que se ve al recorrer
                # el fichero con la vista, que es para lo que sirve.
                altura = self.fontMetrics().height()
                if line in self._added_changes:
                    painter.fillRect(
                        0, int(top), bar_width, altura,
                        QColor(style.EDITOR_CHANGE_ADDED),
                    )
                elif line in self._modified_lines:
                    painter.fillRect(
                        0, int(top), bar_width, altura,
                        QColor(style.EDITOR_CHANGE_MODIFIED),
                    )
                if line in self._deleted_lines:
                    self._paint_deletion(painter, int(top) + altura)

            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            number += 1

    def _paint_deletion(self, painter: QPainter, bottom: int) -> None:
        """Marca de borrado: un triángulo en la junta entre las dos líneas.

        Lo borrado no ocupa ninguna línea del texto actual, así que no hay
        barra que pintar — igual que en VS Code, se señala el punto de unión
        con una punta de flecha, y su forma distinta dice por sí sola que
        eso no es "una línea cambiada" sino "aquí faltaba algo".

        Puede coincidir con una línea añadida o modificada, y entonces se
        pintan las dos cosas: son dos hechos distintos sobre el mismo sitio.
        """
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(QColor(style.EDITOR_CHANGE_DELETED))
        painter.setPen(Qt.NoPen)
        lado = style.EDITOR_CHANGE_DELETED_SIZE
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(0, bottom - lado / 2),
                    QPointF(lado, bottom),
                    QPointF(0, bottom + lado / 2),
                ]
            )
        )
        painter.restore()

    # ------------------------------------------------------------------
    # Plegado de nodos
    # ------------------------------------------------------------------
    def _compute_fold_regions(self, text: str) -> Dict[int, int]:
        """Empareja cada «{» que abre línea con la línea de su «}»."""
        regions: Dict[int, int] = {}
        line = 1
        in_string = False
        index = 0
        length = len(text)
        while index < length:
            char = text[index]
            if char == '"':
                in_string = not in_string
            elif char == "\n":
                line += 1
            elif char == "{" and not in_string:
                match = find_matching_brace(text, index)
                if match is not None:
                    end_line = line + text.count("\n", index, match)
                    if end_line > line:
                        regions[line] = end_line
            index += 1
        return regions

    def _refresh_fold_regions(self) -> None:
        """Recalcula qué líneas son plegables tras un cambio de texto.

        Una región plegada que ya no case exactamente con lo recalculado
        (el usuario borró o movió la llave) se despliega sola en vez de
        quedarse escondiendo lo que ya no le corresponde.
        """
        self._fold_regions = self._compute_fold_regions(self.toPlainText())
        self._folded = {
            line: end
            for line, end in self._folded.items()
            if self._fold_regions.get(line) == end
        }
        self._apply_fold_visibility()

    def _apply_fold_visibility(self) -> None:
        """Oculta los bloques de cada región plegada; el resto queda visible.

        `QTextBlock.setVisible` es el mecanismo nativo de Qt para esto -un
        bloque invisible mide alto cero en el layout-, así que el resto del
        editor (numeración de línea, scroll, cursor) no necesita saber nada
        de plegado.
        """
        document = self.document()
        total = document.blockCount()
        hidden = [False] * total
        for start_line, end_line in self._folded.items():
            for block_number in range(start_line, min(end_line, total)):
                hidden[block_number] = True

        changed = False
        block = document.firstBlock()
        while block.isValid():
            want_visible = not hidden[block.blockNumber()]
            if block.isVisible() != want_visible:
                block.setVisible(want_visible)
                changed = True
            block = block.next()

        if changed:
            document.markContentsDirty(0, document.characterCount())
            self._update_margin()
            self.viewport().update()
            self._line_numbers.update()

    def innermost_fold_region(self, line: int) -> Optional[Tuple[int, int]]:
        """La región `{`/`}` más interna que contiene `line`, si hay alguna.

        En DTS, cada par `{`/`}` es el cuerpo de un nodo (los valores usan
        `<>`/`[]`, nunca llaves), así que esto es "en qué nodo está esta
        línea" reutilizando el mismo emparejado que ya mantiene el plegado
        -siempre al día con el texto en pantalla, a diferencia del árbol del
        último análisis, que va con retraso mientras se escribe-. Lo usa
        `EditorTab` para el Inspector.
        """
        best: Optional[Tuple[int, int]] = None
        for start, end in self._fold_regions.items():
            if start <= line <= end:
                if best is None or (end - start) < (best[1] - best[0]):
                    best = (start, end)
        return best

    def toggle_fold(self, line: int) -> None:
        """Pliega o despliega la región que empieza en `line` (1-based)."""
        end_line = self._fold_regions.get(line)
        if end_line is None:
            return
        if line in self._folded:
            del self._folded[line]
        else:
            self._folded[line] = end_line
        self._apply_fold_visibility()

    def handle_gutter_click(self, pos: QPoint) -> None:
        """Traduce un clic del margen a un plegado, si cae sobre la flecha."""
        if pos.x() > style.EDITOR_FOLD_MARKER_WIDTH:
            return
        line = self._line_at_gutter_y(pos.y())
        if line is not None:
            self.toggle_fold(line)

    def _line_at_gutter_y(self, y: int) -> Optional[int]:
        """Línea (1-based) cuyo bloque visible ocupa la coordenada `y` del margen."""
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()

        while block.isValid() and top <= y:
            if block.isVisible() and top <= y < bottom:
                return number + 1
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            number += 1
        return None

    def _paint_fold_indicators(self) -> None:
        """Dibuja un «⋯» al final de cada línea que esconde contenido plegado."""
        if not self._folded:
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor(style.EDITOR_FOLD_MARKER_COLOR))
        document = self.document()
        offset = self.contentOffset()
        for start_line in self._folded:
            block = document.findBlockByNumber(start_line - 1)
            if not block.isValid() or not block.isVisible():
                continue
            geometry = self.blockBoundingGeometry(block).translated(offset)
            text_width = self.fontMetrics().horizontalAdvance(block.text())
            painter.drawText(
                int(geometry.left() + text_width + 6),
                int(geometry.top()),
                60,
                self.fontMetrics().height(),
                Qt.AlignLeft,
                "⋯",
            )

    def paintEvent(self, event) -> None:
        """Pinta el texto como siempre y, encima, el «⋯» de las líneas plegadas."""
        super().paintEvent(event)
        self._paint_fold_indicators()

    # ------------------------------------------------------------------
    # Diagnósticos
    # ------------------------------------------------------------------
    def refresh_theme(self) -> None:
        """Rehace lo que se pintó con los colores del modo anterior.

        El resaltador construye un `QTextCharFormat` por regla al crearse, y
        los resaltados de línea son `ExtraSelection` ya compuestas: ninguna
        de las dos cosas se entera de que los tokens han cambiado, así que
        al cambiar de claro a oscuro hay que rehacerlas.
        """
        self._highlighter = type(self._highlighter)(self.document())
        self._refresh_selections()
        self._line_numbers.update()
        self._minimap.update()

    def set_diagnostics(self, diagnostics: Iterable[Diagnostic]) -> None:
        """Marca las líneas con problemas, quedándose con la peor gravedad."""
        self._diagnostic_lines = {}
        for diagnostic in diagnostics:
            current = self._diagnostic_lines.get(diagnostic.line)
            if current is Severity.ERROR:
                continue
            self._diagnostic_lines[diagnostic.line] = diagnostic.severity

        self._refresh_selections()
        self._line_numbers.update()
        self._minimap.update()

    def set_change_lines(
        self,
        added: Iterable[int] = (),
        modified: Iterable[int] = (),
        deleted: Iterable[int] = (),
    ) -> None:
        """Marca en el margen qué líneas no están en la última versión de git.

        Solo pinta la franja del margen, no el fondo del texto: lo que se
        está leyendo es el device tree, y teñir media pantalla porque está
        sin guardar taparía los avisos, que sí hay que ver.
        """
        self._added_changes = set(added)
        self._modified_lines = set(modified)
        self._deleted_lines = set(deleted)
        self._line_numbers.update()
        self._minimap.update()

    def line_shapes(self) -> List[Tuple[int, float]]:
        """Silueta del fichero: (línea 0-based, cuánto ocupa de 0 a 1)."""
        return self._line_shapes

    def _refresh_line_shapes(self) -> None:
        """Recalcula la silueta que dibuja el minimapa."""
        lines = self.toPlainText().split("\n")
        # Referencia de "línea llena": la más larga, con un suelo para que
        # un fichero de líneas cortas no salga con todas al máximo.
        longest = max(40, max((len(line) for line in lines), default=1))
        self._line_shapes = [
            (index, min(1.0, len(line.rstrip()) / longest))
            for index, line in enumerate(lines)
            if line.strip()
        ]
        self._minimap.update()

    def visible_line_range(self) -> Tuple[int, int]:
        """Primera y última línea (1-based) que se ven ahora en el editor."""
        first = self.firstVisibleBlock().blockNumber() + 1
        alto = max(1, int(self.fontMetrics().height()))
        cuantas = max(1, self.viewport().height() // alto)
        return first, min(self.blockCount(), first + cuantas - 1)

    def center_on_line(self, line: int) -> None:
        """Lleva la vista a `line` sin mover el cursor (clic en el minimapa)."""
        bar = self.verticalScrollBar()
        first, last = self.visible_line_range()
        bar.setValue(max(0, line - (last - first) // 2 - 1))

    def diagnostic_severity(self, line: int) -> Optional[Severity]:
        """Gravedad del peor diagnóstico de una línea, si tiene alguno."""
        return self._diagnostic_lines.get(line)

    def change_color(self, line: int) -> Optional[str]:
        """Color de la barra de cambios de una línea, si tiene alguno."""
        if line in self._added_changes:
            return style.EDITOR_CHANGE_ADDED
        if line in self._modified_lines:
            return style.EDITOR_CHANGE_MODIFIED
        if line in self._deleted_lines:
            return style.EDITOR_CHANGE_DELETED
        return None

    def set_added_lines(self, lines: Iterable[int]) -> None:
        """Resalta en verde las líneas indicadas (1-based), como un "+" de git.

        Pensado para el "DTS completo" del generador: las líneas que vienen
        del fragmento generado, no del SoC original, se distinguen de un
        vistazo.
        """
        self._added_lines = set(lines)
        self._refresh_selections()

    def _refresh_selections(self) -> None:
        """Repinta el fondo de la línea actual y el de las líneas con avisos."""
        selections: List[QTextEdit.ExtraSelection] = []

        current = QTextEdit.ExtraSelection()
        current.format.setBackground(QColor(style.EDITOR_CURRENT_LINE_BG))
        current.format.setProperty(QTextFormat.FullWidthSelection, True)
        current.cursor = self.textCursor()
        current.cursor.clearSelection()
        selections.append(current)

        document = self.document()
        for line in self._added_lines:
            block = document.findBlockByNumber(line - 1)
            if not block.isValid():
                continue
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor(style.COLOR_GENERATED_DARK))
            selection.format.setProperty(QTextFormat.FullWidthSelection, True)
            selection.cursor = QTextCursor(block)
            selection.cursor.clearSelection()
            selections.append(selection)

        for line, severity in self._diagnostic_lines.items():
            block = document.findBlockByNumber(line - 1)
            if not block.isValid():
                continue
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor(severity_background(severity)))
            selection.format.setProperty(QTextFormat.FullWidthSelection, True)
            selection.cursor = QTextCursor(block)
            selection.cursor.clearSelection()
            selections.append(selection)

        # El destello del nodo al que se acaba de saltar. Va después del
        # resto para pintarse encima: durante ese segundo es lo único que
        # hay que ver.
        for span in (self._node_hint,):
            if span is None:
                continue
            first, last = span
            for number in range(first, last + 1):
                block = document.findBlockByNumber(number - 1)
                if not block.isValid():
                    continue
                selection = QTextEdit.ExtraSelection()
                selection.format.setBackground(QColor(style.EDITOR_NODE_HINT_BG))
                selection.format.setProperty(QTextFormat.FullWidthSelection, True)
                selection.cursor = QTextCursor(block)
                selection.cursor.clearSelection()
                selections.append(selection)

        selections.extend(self._brace_selections())
        selections.extend(self._search_selections())

        if self._hint is not None:
            hint_line, start_col, length = self._hint
            block = document.findBlockByNumber(hint_line - 1)
            if block.isValid():
                selection = QTextEdit.ExtraSelection()
                selection.format.setFontUnderline(True)
                selection.format.setUnderlineStyle(QTextCharFormat.SingleUnderline)
                selection.format.setUnderlineColor(QColor(style.EDITOR_INCLUDE_HINT_COLOR))
                selection.format.setForeground(QColor(style.EDITOR_INCLUDE_HINT_COLOR))
                cursor = QTextCursor(block)
                cursor.setPosition(block.position() + start_col)
                cursor.setPosition(
                    block.position() + start_col + length, QTextCursor.KeepAnchor
                )
                selection.cursor = cursor
                selections.append(selection)

        self.setExtraSelections(selections)

    def _brace_selections(self) -> List[QTextEdit.ExtraSelection]:
        """Resalta la llave bajo el cursor y su pareja.

        Se mira tanto el carácter sobre el cursor como el anterior, que es
        donde queda al escribir una llave. Si no tiene pareja se pinta en rojo:
        así se ve de un vistazo qué «{» se ha quedado sin cerrar.
        """
        text = self.toPlainText()
        position = self.textCursor().position()

        for candidate in (position, position - 1):
            if candidate < 0 or candidate >= len(text):
                continue
            if text[candidate] not in "{}":
                continue

            match = find_matching_brace(text, candidate)
            color = QColor(
                style.EDITOR_BRACE_MATCH_COLOR
                if match is not None
                else style.EDITOR_BRACE_ORPHAN_COLOR
            )

            selections = []
            for spot in filter(lambda value: value is not None, (candidate, match)):
                selection = QTextEdit.ExtraSelection()
                selection.format.setBackground(color)
                selection.format.setForeground(QColor(style.EDITOR_BRACE_MATCH_FOREGROUND))
                cursor = self.textCursor()
                cursor.setPosition(spot)
                cursor.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
                selection.cursor = cursor
                selections.append(selection)
            return selections

        return []

    def _search_selections(self) -> List[QTextEdit.ExtraSelection]:
        """Resalta todas las coincidencias de la búsqueda, la actual más marcada."""
        if not self._search_matches:
            return []

        selections = []
        for index, (start, end) in enumerate(self._search_matches):
            is_current = index == self._search_current
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(
                QColor(
                    style.EDITOR_FIND_CURRENT_MATCH_COLOR
                    if is_current
                    else style.EDITOR_FIND_MATCH_COLOR
                )
            )
            if is_current:
                selection.format.setForeground(QColor(style.EDITOR_BRACE_MATCH_FOREGROUND))
            cursor = self.textCursor()
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.KeepAnchor)
            selection.cursor = cursor
            selections.append(selection)
        return selections

    def current_depth_label(self) -> str:
        """Describe la anidación en la posición del cursor, para la barra de estado."""
        text = self.toPlainText()[: self.textCursor().position()]
        depth = 0
        in_string = False
        for char in text:
            if char == '"':
                in_string = not in_string
            elif not in_string:
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
        return self.tr("level {depth}").format(depth=max(0, depth))

    # ------------------------------------------------------------------
    # Autocompletado
    # ------------------------------------------------------------------
    def set_completion_provider(self, provider: Optional[Callable]) -> None:
        """Fija quién decide qué sugerir.

        `provider(prefijo, contexto)` devuelve una lista de `CompletionItem`.
        El contexto es «property» cuando se está escribiendo el nombre de una
        propiedad y «value» cuando se está escribiendo su valor.
        """
        self._completion_provider = provider

    def show_completions(self, context: str = "property") -> None:
        """Pide sugerencias para lo que hay bajo el cursor y muestra la lista."""
        if self._completion_provider is None:
            return

        prefix = self._current_prefix()
        items = self._completion_provider(prefix, context)
        if not items:
            self._completer.popup().hide()
            return

        self._completion_items = {item.label: item for item in items}
        self._completer.model().setStringList(sorted(self._completion_items))
        self._completer.setCompletionPrefix(prefix)
        if self._completer.completionCount() == 0:
            self._completer.popup().hide()
            return

        popup = self._completer.popup()
        popup.setCurrentIndex(self._completer.completionModel().index(0, 0))
        rect = self.cursorRect()
        rect.setWidth(
            popup.sizeHintForColumn(0) + popup.verticalScrollBar().sizeHint().width()
        )
        self._completer.complete(rect)

    def _current_prefix(self) -> str:
        """Texto que se está escribiendo justo antes del cursor."""
        cursor = self.textCursor()
        line = cursor.block().text()[: cursor.positionInBlock()]
        index = len(line)
        while index > 0 and line[index - 1] in _NAME_CHARS:
            index -= 1
        return line[index:]

    def _insert_completion(self, label: str) -> None:
        """Sustituye lo escrito por la sugerencia elegida."""
        item = self._completion_items.get(label)
        if item is None:
            return

        cursor = self.textCursor()
        prefix = self._current_prefix()
        if prefix:
            cursor.movePosition(
                QTextCursor.Left, QTextCursor.KeepAnchor, len(prefix)
            )
            cursor.removeSelectedText()
        cursor.insertText(item.insert)
        if item.cursor_back:
            cursor.movePosition(QTextCursor.Left, QTextCursor.MoveAnchor,
                                item.cursor_back)
        self.setTextCursor(cursor)
        self.completionInserted.emit(item.key or label)

    def keyPressEvent(self, event) -> None:
        """Deja que la lista se maneje sola cuando está abierta.

        Con la lista visible, las teclas de navegación y aceptación son suyas;
        si no, se escribe con normalidad y después se decide si toca ofrecer
        algo. `Ctrl+Space` la abre siempre.
        """
        if event.key() == Qt.Key_Control:
            # Ctrl puede pulsarse sin mover el ratón (ya estaba encima de un
            # include): sin este refresco, el subrayado solo aparecería al
            # siguiente movimiento y el usuario no vería la pista al momento.
            self._refresh_hover(ctrl=True)

        popup = self._completer.popup()
        if popup.isVisible() and event.key() in (
            Qt.Key_Enter,
            Qt.Key_Return,
            Qt.Key_Tab,
            Qt.Key_Up,
            Qt.Key_Down,
            Qt.Key_PageUp,
            Qt.Key_PageDown,
        ):
            event.ignore()
            return

        forced = event.key() == Qt.Key_Space and event.modifiers() & Qt.ControlModifier
        if forced:
            self.show_completions(self._context_at_cursor())
            return

        super().keyPressEvent(event)

        if event.key() == Qt.Key_Escape:
            popup.hide()
            return

        text = event.text()
        if not text or not (text in _NAME_CHARS or text in '"<'):
            if popup.isVisible():
                popup.hide()
            return

        context = self._context_at_cursor()
        if context == "property" and len(self._current_prefix()) < _MIN_PREFIX:
            popup.hide()
            return
        self.show_completions(context)

    def _context_at_cursor(self) -> str:
        """Decide si se está escribiendo el nombre de una propiedad o su valor.

        Basta mirar la línea hasta el cursor: en cuanto aparece un «=» lo que
        viene es el valor. No hace falta el árbol para esto, y así funciona
        mientras se escribe, antes de que el análisis se haya rehecho.
        """
        cursor = self.textCursor()
        line = cursor.block().text()[: cursor.positionInBlock()]
        return "value" if "=" in line else "property"

    def keyReleaseEvent(self, event) -> None:
        """Al soltar Ctrl, quita el subrayado sin esperar a que el ratón se mueva."""
        super().keyReleaseEvent(event)
        if event.key() == Qt.Key_Control:
            self._refresh_hover(ctrl=False)

    def mousePressEvent(self, event) -> None:
        """Coloca el cursor como siempre y, con Ctrl, avisa de la línea.

        Sustituye al doble clic: abrir un include con Ctrl+clic es el gesto
        habitual de "ir a la definición" en un IDE, y deja el doble clic
        libre para lo que ya hace por defecto (seleccionar la palabra).
        """
        super().mousePressEvent(event)
        if event.button() != Qt.LeftButton:
            return
        cursor = self.cursorForPosition(event.position().toPoint())
        line = cursor.blockNumber() + 1
        if event.modifiers() & Qt.ControlModifier:
            self.ctrlLineClicked.emit(line, cursor.positionInBlock())
        else:
            self.lineClicked.emit(line)

    def mouseMoveEvent(self, event) -> None:
        """Sigue el movimiento normal y, además, informa de dónde está el ratón.

        `EditorTab` es quien decide con esa posición si hay un include justo
        ahí (este widget no sabe de DTS) y pide `set_include_hint` en
        consecuencia.
        """
        super().mouseMoveEvent(event)
        pos = event.position().toPoint()
        self._last_mouse_pos = pos
        self._emit_hover(pos, bool(event.modifiers() & Qt.ControlModifier))

    def leaveEvent(self, event) -> None:
        """El ratón sale del editor: no hay nada bajo qué mantener la pista."""
        super().leaveEvent(event)
        self._last_mouse_pos = None
        self.set_include_hint(None)
        self.set_node_hint(None)

    def _refresh_hover(self, ctrl: bool) -> None:
        """Recalcula la pista con la última posición conocida del ratón."""
        if self._last_mouse_pos is not None:
            self._emit_hover(self._last_mouse_pos, ctrl)

    def _emit_hover(self, pos: QPoint, ctrl: bool) -> None:
        cursor = self.cursorForPosition(pos)
        self.hoverMoved.emit(cursor.blockNumber() + 1, cursor.positionInBlock(), ctrl)

    def set_include_hint(self, span: Optional[Tuple[int, int, int]]) -> None:
        """Subraya `span` = (línea 1-based, columna inicial, longitud), o lo quita.

        Lo decide `EditorTab`: solo él sabe si la posición del ratón cae
        sobre el `target` de un include. Aquí solo se dibuja el subrayado y
        se cambia el cursor a una mano, para que se note que se puede pulsar.
        """
        if span == self._hint:
            return
        self._hint = span
        self._update_cursor_shape()
        self._refresh_selections()

    def set_node_hint(self, span: Optional[Tuple[int, int]]) -> None:
        """Resalta el bloque de líneas `(primera, última)`, o lo quita.

        Es el equivalente de `set_include_hint` para un nodo entero: mientras
        se elige el objetivo de un overlay, el nodo bajo el ratón se pinta de
        arriba abajo para que se vea **qué** se va a elegir antes de pulsar,
        no después. Igual que allí, el widget no sabe qué es un nodo: quién
        decide el bloque es `EditorTab`.
        """
        if span == self._node_hint:
            return
        self._node_hint = span
        self._update_cursor_shape()
        self._refresh_selections()

    def _update_cursor_shape(self) -> None:
        """Mano cuando hay algo que pulsar bajo el ratón, cursor de texto si no."""
        pulsable = self._hint is not None or self._node_hint is not None
        self.viewport().setCursor(
            Qt.PointingHandCursor if pulsable else Qt.IBeamCursor
        )

    def go_to_line(self, line: int) -> None:
        """Lleva el cursor al principio de `line` y la deja visible."""
        block = self.document().findBlockByNumber(max(0, line - 1))
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        self.setTextCursor(cursor)
        self.centerCursor()
        self.setFocus()

    # ------------------------------------------------------------------
    # Búsqueda (Ctrl+F)
    # ------------------------------------------------------------------
    def _position_find_bar(self) -> None:
        """Coloca la barra flotante en la esquina superior derecha del editor."""
        margin = 10
        hint = self._find_bar.sizeHint()
        width = min(hint.width(), max(0, self.width() - 2 * margin))
        self._find_bar.setGeometry(
            self.width() - width - margin, margin, width, hint.height()
        )

    def retranslate(self) -> None:
        """Rehace el texto de fondo del editor vacío (ver `Retranslates`)."""
        self.setPlaceholderText(
            self.tr("Open a .dts or .dtsi file, or type here directly.")
        )

    def open_find(self) -> None:
        """Abre la barra de búsqueda; lo llama el menú «Editar → Buscar…».

        El atajo Ctrl+F lo monta el propio editor, pero una función que solo
        existe si ya sabes que existe no la encuentra nadie: el menú necesita
        poder pedirlo igual que la tecla.
        """
        self.setFocus()
        self._open_find_bar()

    def _open_find_bar(self) -> None:
        """Abre (o enfoca) la barra, con la selección actual como texto inicial.

        Una selección que abarca varias líneas no sirve como término de
        búsqueda razonable (el separador de párrafo de Qt, `\\u2029`, no
        aparece nunca en el texto real), así que en ese caso se conserva la
        última búsqueda en vez de sustituirla por la selección.
        """
        selected = self.textCursor().selectedText()
        initial = selected if selected and " " not in selected else None
        self._find_bar.open(initial)
        self._position_find_bar()
        self._update_search(self._find_bar.current_text())

    def _close_find_bar(self) -> None:
        """Oculta la barra y quita el resaltado de coincidencias."""
        self._find_bar.hide()
        self._search_term = ""
        self._search_matches = []
        self._search_current = -1
        self._refresh_selections()
        self.setFocus()

    def _find_matches(self, term: str) -> List[Tuple[int, int]]:
        """Tramos (inicio, fin) de cada aparición de `term`, sin distinguir mayúsc."""
        if not term:
            return []
        haystack = self.toPlainText().lower()
        needle = term.lower()
        matches = []
        start = 0
        while True:
            index = haystack.find(needle, start)
            if index < 0:
                break
            matches.append((index, index + len(needle)))
            start = index + len(needle)
        return matches

    def _update_search(self, term: str, jump: bool = True) -> None:
        """Recalcula las coincidencias de `term` y, si `jump`, salta a la más cercana.

        `jump=False` es para cuando el texto del documento cambia con la
        barra abierta (`_on_text_changed_for_search`): hay que recalcular las
        posiciones, pero saltar la vista mientras se está escribiendo el
        cuerpo del documento sería más molesto que ayudar.
        """
        self._search_term = term
        self._search_matches = self._find_matches(term)
        self._search_current = -1

        if self._search_matches:
            if jump:
                position = self.textCursor().position()
                self._search_current = next(
                    (
                        i
                        for i, (start, _) in enumerate(self._search_matches)
                        if start >= position
                    ),
                    0,
                )
                self._goto_current_match()
            else:
                self._search_current = 0

        self._update_match_label()
        self._refresh_selections()

    def _on_text_changed_for_search(self) -> None:
        """Si la barra está abierta, recalcula las coincidencias tras cada edición."""
        if self._find_bar.isVisible() and self._search_term:
            self._update_search(self._search_term, jump=False)

    def _find_next(self) -> None:
        """Salta a la siguiente coincidencia, dando la vuelta al llegar al final."""
        if not self._search_matches:
            return
        self._search_current = (self._search_current + 1) % len(self._search_matches)
        self._goto_current_match()
        self._update_match_label()
        self._refresh_selections()

    def _find_previous(self) -> None:
        """Salta a la coincidencia anterior, dando la vuelta al llegar al principio."""
        if not self._search_matches:
            return
        self._search_current = (self._search_current - 1) % len(self._search_matches)
        self._goto_current_match()
        self._update_match_label()
        self._refresh_selections()

    def _goto_current_match(self) -> None:
        """Lleva el cursor (sin seleccionar) a la coincidencia actual y la centra.

        No se usa la selección nativa: el resaltado ya lo da `_search_selections`
        con un fondo propio, igual que hace el emparejado de llaves.
        """
        start, _ = self._search_matches[self._search_current]
        cursor = self.textCursor()
        cursor.setPosition(start)
        cursor.clearSelection()
        self.setTextCursor(cursor)
        self.centerCursor()

    def _update_match_label(self) -> None:
        """Actualiza el contador de la barra ("3/12", "Sin resultados"…)."""
        if not self._search_term:
            self._find_bar.set_match_label("")
        elif not self._search_matches:
            self._find_bar.set_match_label(self.tr("No results"))
        else:
            total = len(self._search_matches)
            self._find_bar.set_match_label(f"{self._search_current + 1}/{total}")
