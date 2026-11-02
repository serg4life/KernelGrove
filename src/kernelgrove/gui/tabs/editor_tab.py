"""Pestaña de edición: escribir device trees y validarlos al vuelo.

Admite varios documentos abiertos a la vez, porque al abrir una inclusión
desde el grafo su contenido se muestra en un editor adicional sin perder el
fichero de partida.

La barra con esos documentos no se dibuja aquí: los ficheros abiertos son de
la aplicación entera —el que esté activo es el que se edita y el que se
visualiza—, así que la pinta `MainWindow` sobre las tres vistas y la maneja a
través de `document_labels`, `activate_document` y `close_document`. Aquí solo
queda la pila de editores, con su propia barra oculta.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QCoreApplication, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
QButtonGroup,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from kernelgrove.api import (
    Diagnostic,
    DeviceTreeNode,
    KernelGroveService,
    IncludeDirective,
    ParseResult,
    PropertySuggestion,
    Severity,
)
from kernelgrove.gui import brand, file_io, messages, style
from kernelgrove.gui.translations import Retranslates
from kernelgrove.gui.widgets import icons
from kernelgrove.gui.widgets.dts_editor import (
    CompletionItem,
    DiffHighlighter,
    DtsEditor,
    DtsHighlighter,
    OverlayLogHighlighter,
)
from kernelgrove.gui.workers import SchemaCheckScheduler

# Espera tras la última pulsación antes de re-analizar, para no lanzar el
# análisis en cada tecla.
ANALYSIS_DELAY_MS = 600

# Espera antes del primer análisis de un documento recién mostrado (al
# abrirlo, o al cambiar a una pestaña que todavía no se había analizado). En
# un SoC grande, el análisis síncrono (capa 1 + capa 5 barata) tarda cientos
# de milisegundos — lanzarlo en la misma pasada que `addTab`/
# `setCurrentWidget` bloqueaba el hilo de Qt antes de que llegara a pintar
# ni el texto ni la propia pestaña, así que "abrir" se sentía lento aunque
# el fichero ya estuviera cargado en el editor. Este margen, aunque
# pequeño, es tiempo de sobra para que Qt vuelva al bucle de eventos y
# pinte lo que ya hay antes de ponerse a analizar; el análisis en sí no se
# acorta, solo deja de tapar la primera pintura.
INITIAL_ANALYSIS_DELAY_MS = 30

# Lo que valida el propio schema tarda milisegundos por nodo, o segundos en un
# SoC entero, así que espera a que se deje de escribir un poco más que el
# análisis normal.
SCHEMA_CHECKS_DELAY_MS = 1500

# Glifo y color de cada severidad en la lista de diagnósticos. El color no
# es decoración: es lo que permite ver de un vistazo si lo que hay son
# errores o avisos sin leer una sola línea. El glifo se queda porque el
# color solo no puede ser el único portador de la información (un daltónico
# no lo distingue), que es la regla 1.4.1 de WCAG.
SEVERITY_ICON = {
    Severity.ERROR: "✕",
    Severity.WARNING: "!",
    Severity.INFO: "i",
}

SEVERITY_COLOR = {
    Severity.ERROR: style.EDITOR_ERROR_ACCENT,
    Severity.WARNING: style.EDITOR_WARNING_ACCENT,
    Severity.INFO: style.MUTED_TEXT_COLOR,
}

# Extensiones que el motor semántico sabe analizar. El panel de carpetas deja
# abrir cualquier fichero (ver `FileExplorerPanel`), pero solo tiene sentido
# ejecutar el análisis -sintaxis, capas de binding, esquema...- sobre estas:
# un `.c`, un `.h` o un `Makefile` no son device trees y comprobarlos como si
# lo fueran solo gastaría ciclos sin decir nada útil.
_DEVICE_TREE_EXTENSIONS = (".dts", ".dtsi", ".dtso")

# Referencia a un nodo: por etiqueta (`&i2c0`) o por ruta (`&{/soc/i2c@0}`).
# Es la misma forma en la cabecera de una reapertura y dentro de un valor, que
# es justo lo que permite ir a la definición desde un phandle.
_REFERENCE_RE = re.compile(r"&\{[^}]*\}|&[A-Za-z_][A-Za-z0-9_,.+-]*")

# Las tres páginas del panel inferior: los diagnósticos del documento, el
# registro de comprobación de overlays y el de la compilación —lo que dicen
# `cpp` y `dtc` con la orden con la que se les ha llamado—.
LOG_DIAGNOSTICS = 0
LOG_OVERLAYS = 1
LOG_BUILD = 2


def _write_text(path: Path, text: str, newline: str) -> None:
    """Escribe con el terminador del documento, no con el del sistema.

    Con `newline=""` Python no traduce nada por su cuenta: el terminador lo
    pone `file_io.apply_newlines` y es el que dice el indicador de la franja,
    en Linux y en Windows igual.
    """
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(file_io.apply_newlines(text, newline))


def _reapuntada(ruta, old: Path, new: Path) -> Optional[Path]:
    """`ruta` con `old` sustituido por `new`, o None si no cuelga de ahí.

    Lo segundo es lo que hace que renombrar o mover una **carpeta** siga a
    lo que tenía dentro. Un `source_key` que no es una ruta del disco —una
    clave relativa del catálogo, `xilinx/zynqmp.dtsi`— nunca cuelga de una
    ruta absoluta, así que cae solo por este mismo camino.
    """
    if not ruta:
        return None
    ruta = Path(ruta)
    if ruta == old:
        return new
    return new / ruta.relative_to(old) if ruta.is_relative_to(old) else None


def _is_device_tree_title(title: str) -> bool:
    """Si `title` es un fichero de device tree, a juzgar por su extensión."""
    return title.lower().endswith(_DEVICE_TREE_EXTENSIONS)


@dataclass
class Document:
    """Un fichero abierto en el editor y su último análisis."""

    editor: DtsEditor
    title: str
    # Clave del fuente en la base de datos, o ruta del disco si viene del PC.
    source_key: Optional[str] = None
    disk_path: Optional[Path] = None
    # Si el documento es un fragmento (`.dtsi`): en uno, una propiedad
    # obligatoria que falta es un aviso y no un error, porque el `.dts` que
    # lo incluya puede ponerla. Lo decide la extensión al abrirlo; no hay
    # casilla para contradecirla, porque contradecirla no significaba nada.
    fragment: bool = True
    # Si el motor semántico debe decir algo sobre este documento (ver
    # `_DEVICE_TREE_EXTENSIONS`). Se fija una vez, al abrirlo.
    is_device_tree: bool = True
    # Solo lectura: hoy son los diffs del panel de versiones, que no son un
    # fichero de nadie y guardarlos encima del original sería destruirlo.
    read_only: bool = False
    # Contenido tal como está guardado ahora mismo (lo que había al abrirlo,
    # o lo último escrito a disco) — contra esto se compara para saber si hay
    # cambios de verdad, no con `QTextDocument.isModified()` de Qt (ver
    # `EditorTab._refresh_modified_state`).
    saved_text: str = ""
    is_dirty: bool = False
    # Con qué terminador se escribe el fichero al guardarlo (`file_io.LF` o
    # `CRLF`). Se detecta del texto que se abre y se conserva: un `.dts` de
    # un proyecto Windows no tiene por qué salir de aquí convertido a LF sin
    # que nadie lo haya pedido. Dentro del editor el texto va siempre en
    # `\n`; el terminador solo se aplica al escribir a disco.
    newline: str = file_io.LF
    saved_newline: str = file_io.LF
    # Árbol de la base sobre la que se aplica, si este documento es un
    # overlay. Un overlay **no incluye su base** —duplicaría el árbol
    # entero—, así que sin esto el motor no tiene contra qué comprobar
    # nada: ni resuelve `&i2c0` a su compatible, ni puede decir que un
    # objetivo no exista. Es el cable que hace que la ayuda semántica
    # funcione dentro de un overlay.
    overlay_base: Optional[DeviceTreeNode] = None
    parse_result: Optional[ParseResult] = None
    diagnostics: List[Diagnostic] = field(default_factory=list)

    @property
    def is_overlay(self) -> bool:
        """Si el documento se está editando como overlay de otro árbol."""
        return self.overlay_base is not None


class EditorTab(Retranslates, QWidget):
    """Editor de device tree con diagnósticos del motor semántico."""

    status_changed = Signal(str)
    # Hay comprobaciones de esquema en marcha: la ventana enciende con esto
    # su indicador de progreso, para que los avisos que llegan segundos
    # después de dejar de escribir no aparezcan sin explicación.
    busy_changed = Signal(bool)
    document_analyzed = Signal(object)
    # Los documentos abiertos han cambiado (se ha abierto o cerrado uno, o es
    # otro el activo): la ventana refresca con esto su barra de ficheros.
    documents_changed = Signal()
    # Se acaba de escribir en el disco. Lo que decora el árbol de
    # carpetas depende del disco y no de lo que se teclea, así que este
    # es su momento —y no cada análisis (ver `MainWindow`).
    document_saved = Signal()
    # Lo pide el cartel de sesión vacía; quien sabe llevar a la sección de
    # base de datos es la ventana, no esta pestaña.
    database_requested = Signal()
    # Doble clic sobre una línea de include, ya resuelto contra la base de
    # datos (encontrado o no): la ventana decide si abrirlo o avisar.
    include_requested = Signal(object)

    # Ctrl+clic sobre una referencia (`&i2c0`, `&{/soc/i2c@0}`): se pide ir a
    # donde ese nodo está declarado, que casi siempre es otro fichero. Aquí no
    # se resuelve porque el árbol fusionado —el único que sabe de qué `.dtsi`
    # viene cada nodo— lo tiene la ventana.
    definition_requested = Signal(str)
    # Nodo del árbol analizado que contiene la línea del cursor -o `None`
    # si no está dentro de ninguno-, para el panel Inspector. Solo se emite
    # cuando cambia de un nodo a otro, no en cada movimiento del cursor.
    node_at_cursor_changed = Signal(object)
    # Nodo sobre el que se ha hecho clic (o `None` si el clic cayó fuera de
    # todo nodo). A diferencia de la anterior, esta se emite en **cada**
    # clic, aunque sea el mismo nodo: es un gesto deliberado del usuario, no
    # un efecto de mover el cursor, y es con lo que el asistente de overlays
    # deja elegir el nodo objetivo señalándolo en el fuente.
    node_clicked = Signal(object)
    # Dónde está el cursor: línea, columna y la ruta del nodo que lo
    # contiene. Va aparte de `status_changed` porque tiene su propio hueco
    # fijo en la franja de abajo: metido en el mensaje, cada pulsación de
    # una flecha borraba lo último que la aplicación había dicho.
    cursor_moved = Signal(int, int, str)
    # Cuántos diagnósticos hay de cada gravedad, cada vez que la lista se
    # rehace. La franja de estado los enseña a partir de aquí y no
    # contándolos por su cuenta: el pase diferido (capas 2 y 5-valores)
    # llega después del análisis y añade más, así que quien cuente antes se
    # queda con un número que ya no es el de la lista de abajo.
    diagnostics_changed = Signal(int, int, int)

    def __init__(self, service: KernelGroveService, parent=None):
        """Monta la barra de acciones, los documentos y la lista de avisos."""
        super().__init__(parent)
        self.service = service
        self._documents: Dict[QWidget, Document] = {}
        # Último nodo avisado por `node_at_cursor_changed`, para no repetir
        # el aviso -y las consultas a la base de datos que dispara, en el
        # Inspector- mientras el cursor se mueve dentro del mismo nodo.
        self._last_inspected_node: Optional[DeviceTreeNode] = None
        # Modo «señala el nodo objetivo» del asistente de overlays: mientras
        # está encendido, el hover resalta el nodo entero (`set_node_picking`).
        self._node_picking = False

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(ANALYSIS_DELAY_MS)
        self._timer.timeout.connect(self._on_analysis_timeout)

        # Lo que valida el propio schema (valores de la capa 5 y capa 2
        # entera) se lanza en un hilo aparte: cuesta milisegundos por nodo y
        # no cabe en cada pulsación de tecla. Espera algo más que el análisis
        # normal —en un SoC entero son segundos— y solo se ejecuta sobre el
        # último texto: mientras hay una pasada en marcha, la siguiente queda
        # anotada y arranca cuando aquella termina (`SchemaCheckScheduler`).
        self._schema_scheduler = SchemaCheckScheduler(
            service, SCHEMA_CHECKS_DELAY_MS, parent=self
        )
        self._schema_scheduler.checks_ready.connect(self._on_schema_checks)
        self._schema_scheduler.busy_changed.connect(self._on_schema_busy)

        self._build_ui()

    # ------------------------------------------------------------------
    # Construcción
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        """Monta la barra de acciones y el divisor documentos / diagnósticos."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Vertical)
        self._splitter = splitter

        self.documents = QTabWidget()
        self.documents.setDocumentMode(True)
        # La barra visible es la de la ventana; aquí el QTabWidget solo hace de
        # pila de editores.
        self.documents.tabBar().hide()
        self.documents.currentChanged.connect(self._on_document_changed)

        # Con la sesión recién abierta no hay ningún documento, y las tres
        # vistas se quedaban en blanco sin decir por dónde empezar. La pila
        # arranca en este cartel y pasa a los editores en cuanto hay uno.
        self._empty_hint = QLabel()
        self._empty_hint.setObjectName("emptyStateHint")
        self._empty_hint.setAlignment(Qt.AlignCenter)
        self._empty_hint.setWordWrap(True)
        # De las tres formas de empezar, la del catálogo es la única que no
        # se hace desde un menú ni desde un panel que ya está a la vista, así
        # que aquí es un botón y no un renglón más: el cartel decía «elige un
        # SoC en los desplegables de arriba» y esos desplegables se fueron a
        # la pestaña de base de datos hace tiempo.
        self._empty_button = QPushButton()
        self._empty_button.setObjectName("primaryButton")
        self._empty_button.setCursor(Qt.PointingHandCursor)
        self._empty_button.setIconSize(
            QSize(style.ACTION_ICON_SIZE, style.ACTION_ICON_SIZE)
        )
        self._empty_button.clicked.connect(self.database_requested)
        # El logotipo, que es donde tiene sentido: la única pantalla de la
        # aplicación que está vacía y puede permitirse la marca.
        self._empty_logo = QLabel()
        self._empty_logo.setAlignment(Qt.AlignCenter)
        self.refresh_icons()

        self._empty_page = QWidget()
        empty_column = QVBoxLayout(self._empty_page)
        empty_column.addStretch(1)
        empty_column.addWidget(self._empty_logo)
        empty_column.addSpacing(20)
        empty_column.addWidget(self._empty_hint)
        empty_column.addSpacing(16)
        empty_column.addWidget(self._empty_button, 0, Qt.AlignHCenter)
        empty_column.addStretch(1)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._empty_page)
        self._stack.addWidget(self.documents)
        splitter.addWidget(self._stack)

        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)
        filter_bar = QWidget()
        filter_bar.setObjectName("viewToolbar")
        filter_bar.setLayout(self._build_filter_bar())
        # **Esta franja no puede fijar el ancho mínimo de la aplicación.**
        # Sus dos pestañas, tres casillas, contador y botones suman 653 px de
        # mínimo, y `QMainWindow` reparte lo que sobre del centro entre los
        # docks: con ese suelo el Inspector no pasaba de ~500 px por mucho
        # que se arrastrase, y la única forma de ensancharlo era ensanchar
        # la ventana entera. Con la política `Ignored` su `minimumSizeHint`
        # deja de contar y la franja se recorta como cualquier barra de
        # herramientas — el mínimo del centro baja de 653 a 239 px. Es el
        # mismo recurso que `MainWindow._allow_narrow` usa en el dock
        # izquierdo, aquí aplicado al contenedor en vez de a cada hijo.
        filter_bar.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        panel_layout.addWidget(filter_bar)

        self.diagnostics_view = QTreeWidget()
        self.diagnostics_view.setColumnCount(4)
        self.diagnostics_view.setRootIsDecorated(False)
        # Las dos columnas de texto se estiran con la ventana; el icono y la
        # línea se quedan al ancho de su contenido. Sin esto, al estrechar la
        # ventana "Problema"/"Sugerencia" quedaban recortadas tras una barra
        # de desplazamiento horizontal en vez de reajustarse.
        header = self.diagnostics_view.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        self.diagnostics_view.itemActivated.connect(self._on_diagnostic_activated)
        self.diagnostics_view.itemClicked.connect(self._on_diagnostic_activated)

        # El registro de la comprobación de overlays comparte este hueco con
        # los diagnósticos, en vez de tener el suyo en el panel lateral: son
        # dos cosas que se leen igual —«qué ha salido de lo último que se ha
        # comprobado»— y dos ventanas de registro en la misma pantalla es una
        # de más. Cuál se ve lo decide el selector de la barra, y elegir la
        # herramienta de overlays lo cambia solo (`show_log_page`).
        self.overlay_log = QPlainTextEdit()
        self.overlay_log.setReadOnly(True)
        self.overlay_log.setObjectName("overlayLog")
        # Monoespaciada: el informe se lee por su sangrado (qué objetivo
        # cuelga de qué comprobación), y con una proporcional eso se pierde.
        fuente = QFont()
        fuente.setFamilies(style.EDITOR_FONT_FAMILIES)
        fuente.setStyleHint(QFont.Monospace)
        self.overlay_log.setFont(fuente)
        # Coloreado por glifo: el informe se lee de un vistazo (qué pasó,
        # qué no) en vez de obligar a leerlo entero. Ver
        # `OverlayLogHighlighter`.
        self._overlay_log_highlighter = OverlayLogHighlighter(
            self.overlay_log.document()
        )

        # El registro de la compilación aparte del de las comprobaciones:
        # las dos cosas ocurren en la misma pulsación de «Build», pero se
        # leen por separado —«¿pasó la capa 6?» y «¿qué dijo dtc?»— y
        # mezclarlas obliga a buscar la respuesta a una entre la otra.
        self.build_log = QPlainTextEdit()
        self.build_log.setReadOnly(True)
        self.build_log.setObjectName("overlayLog")
        self.build_log.setFont(fuente)
        self._build_log_highlighter = OverlayLogHighlighter(
            self.build_log.document()
        )

        self._log_stack = QStackedWidget()
        self._log_stack.addWidget(self.diagnostics_view)
        self._log_stack.addWidget(self.overlay_log)
        self._log_stack.addWidget(self.build_log)
        panel_layout.addWidget(self._log_stack, 1)
        self._log_panel = panel
        splitter.addWidget(panel)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        # Tamaño inicial, no un límite: el usuario sigue pudiendo arrastrar el
        # divisor. Sin esto, con la lista de diagnósticos vacía (nada abierto
        # aún) el splitter la reparte a partes iguales con el editor, dejando
        # el panel de avisos ocupando media ventana de entrada.
        splitter.setSizes([700, 180])
        layout.addWidget(splitter, 1)

        # Deja la cabecera coherente con la página que se ve de entrada: sin
        # esto, «Clear» —que solo vale para el registro— sale con los
        # diagnósticos delante, porque `_on_log_selected` solo salta cuando
        # el selector cambia.
        self._on_log_selected(LOG_DIAGNOSTICS)
        self.retranslate()

    def retranslate(self) -> None:
        """Rehace los textos fijos y el resumen (ver `Retranslates`).

        `_fill_diagnostics` va al final porque regenera el resumen («N
        errores · N avisos») y la etiqueta de "ocultos por el filtro", que
        también están traducidos; y `analyze` no se relanza: el análisis no
        depende del idioma, solo su presentación.
        """
        self.log_tabs[LOG_DIAGNOSTICS].setText(self.tr("PROBLEMS"))
        self.log_tabs[LOG_OVERLAYS].setText(self.tr("OUTPUT"))
        self.log_tabs[LOG_BUILD].setText(self.tr("BUILD"))
        self.close_log_button.setToolTip(self.tr("Close the panel"))
        self.clear_log_button.setText(self.tr("Clear"))
        self.clear_log_button.setToolTip(self.tr("Empty this log"))
        self.overlay_log.setPlaceholderText(
            self.tr(
                "Every check run on an overlay is logged here, whether it "
                "passes or not. Run one from the OVERLAYS section of the "
                "left panel."
            )
        )
        self.build_log.setPlaceholderText(
            self.tr(
                "What cpp and dtc say while building is written here, with "
                "the command each one was called with. Build from the "
                "OVERLAYS section of the left panel."
            )
        )
        for severity, text in (
            (Severity.ERROR, self.tr("Errors")),
            (Severity.WARNING, self.tr("Warnings")),
            (Severity.INFO, self.tr("Information")),
        ):
            self.severity_checks[severity].setText(text)
        self.diagnostics_view.setHeaderLabels(
            ["", self.tr("Line"), self.tr("Problem"), self.tr("Suggestion")]
        )
        self._empty_hint.setText(messages.empty_editor_hint())
        self._empty_button.setText(self.tr("Browse the database…"))
        if self.current is None:
            self.summary_label.setText(self.tr("Not analyzed"))
        else:
            self._fill_diagnostics()

    def _build_filter_bar(self) -> QHBoxLayout:
        """Qué registro se ve, su filtro y su recuento: la cabecera del panel."""
        bar = QHBoxLayout()
        bar.setContentsMargins(12, 5, 12, 5)
        bar.setSpacing(8)

        # Dos pestañas de texto, no un desplegable: son dos y siempre las
        # mismas, así que enseñarlas las dos cuesta lo mismo que enseñar una
        # con una flecha al lado, y se ve de un vistazo cuál está delante.
        # Es además la forma del panel inferior de cualquier IDE.
        self.log_tabs: Dict[int, QPushButton] = {}
        self._log_group = QButtonGroup(self)
        self._log_group.setExclusive(True)
        for page in (LOG_DIAGNOSTICS, LOG_OVERLAYS, LOG_BUILD):
            tab = QPushButton()
            tab.setObjectName("logTab")
            tab.setCheckable(True)
            tab.setCursor(Qt.PointingHandCursor)
            self._log_group.addButton(tab, page)
            self.log_tabs[page] = tab
            bar.addWidget(tab)
        self.log_tabs[LOG_DIAGNOSTICS].setChecked(True)
        self._log_group.idClicked.connect(self._on_log_selected)

        # INFO viene apagado de fábrica. Es la severidad más numerosa con
        # diferencia —en el corpus del kernel, 5 143 avisos de capa 5, de los
        # que 4 930 son `binding-unknown-compatible`: esperados, no
        # accionables— y encendida sepulta los errores igual que antes los
        # sepultaba ordenar solo por línea. El contador de "ocultos por el
        # filtro" deja claro que hay más.
        self.severity_checks: Dict[Severity, QCheckBox] = {}
        for severity, enabled in (
            (Severity.ERROR, True),
            (Severity.WARNING, True),
            (Severity.INFO, False),
        ):
            check = QCheckBox()
            check.setChecked(enabled)
            check.toggled.connect(self._fill_diagnostics)
            self.severity_checks[severity] = check
            bar.addWidget(check)

        bar.addStretch(1)
        # El recuento vive aquí, sobre la lista que cuenta, y no en una
        # franja de acciones arriba del editor: leer «3 errores» a media
        # ventana de distancia de los tres errores era mirar dos sitios para
        # una sola cosa.
        self.summary_label = QLabel()
        self.summary_label.setObjectName("viewToolbarStatus")
        self.filtered_label = QLabel("")
        self.filtered_label.setObjectName("viewToolbarStatus")
        bar.addWidget(self.summary_label)
        bar.addWidget(self.filtered_label)

        # Vaciar el registro solo vale para el de overlays: los diagnósticos
        # no se acumulan —cada análisis los reemplaza— mientras que el
        # registro va sumando informes hasta llenarse de comprobaciones
        # viejas que ya no dicen nada de lo que se está mirando ahora.
        self.clear_log_button = QPushButton()
        self.clear_log_button.setObjectName("statusAction")
        # A un método y no a `overlay_log.clear`: esta barra se monta antes
        # que el propio registro (ver `_build_ui`).
        self.clear_log_button.clicked.connect(self._clear_overlay_log)
        bar.addWidget(self.clear_log_button)

        # **Cerrar** la franja, no plegarla. Plegar escondía lo de dentro
        # pero no tocaba el reparto del `QSplitter`, así que «plegado» era
        # una cabecera flotando sobre medio panel vacío: el botón parecía no
        # hacer nada. Cerrada desaparece del todo —un hijo escondido de un
        # splitter no ocupa— y se vuelve a abrir por Ver → Logging panel.
        self.close_log_button = QToolButton()
        self.close_log_button.setObjectName("dockCollapseButton")
        self.close_log_button.setText("✕")
        self.close_log_button.setCursor(Qt.PointingHandCursor)
        self.close_log_button.clicked.connect(lambda *_: self.hide_log_panel())
        bar.addWidget(self.close_log_button)

        # Lo que solo tiene sentido sobre la lista de diagnósticos: filtrar
        # por gravedad y contar. Con el registro de overlays delante no
        # filtran nada, así que se van con él.
        self._diagnostic_only = [
            *self.severity_checks.values(),
            self.summary_label,
            self.filtered_label,
        ]
        return bar

    def show_log_page(self, page: int) -> None:
        """Cambia qué registro se ve en el panel inferior."""
        tab = self.log_tabs.get(page)
        if tab is None or tab.isChecked():
            return
        tab.setChecked(True)
        self._on_log_selected(page)

    def hide_log_panel(self) -> None:
        """Cierra la franja inferior, recordando el alto que tenía.

        Se recuerda para devolvérselo al abrirla: lo que el usuario había
        ajustado a mano es justamente lo que quiere de vuelta, y repartir el
        hueco otra vez a partes iguales no es eso.
        """
        sizes = self._splitter.sizes()
        if len(sizes) >= 2 and sizes[1]:
            self._log_height = sizes[1]
        self._log_panel.hide()

    def show_log_panel(self) -> None:
        """La devuelve al alto que tenía (Ver → Logging panel)."""
        if not self._log_panel.isHidden():
            return
        self._log_panel.show()
        sizes = self._splitter.sizes()
        alto = getattr(self, "_log_height", 0) or int(sum(sizes) * 0.25)
        self._splitter.setSizes([max(sum(sizes) - alto, 1), alto])

    def log_panel_visible(self) -> bool:
        """Si la franja inferior está a la vista."""
        return not self._log_panel.isHidden()

    def refresh_theme(self) -> None:
        """Rehace lo que se pintó con los colores de la piel anterior.

        El resaltado del registro (sus `QTextCharFormat` se construyen una
        vez y el QSS no los alcanza, igual que los del editor —
        `DtsEditor.refresh_theme`) y el logotipo, que se rasteriza con la
        tinta del tema.
        """
        self._overlay_log_highlighter = OverlayLogHighlighter(
            self.overlay_log.document()
        )
        self._build_log_highlighter = OverlayLogHighlighter(
            self.build_log.document()
        )

    def refresh_icons(self) -> None:
        """Repinta lo que se dibujó con `QPainter` en el color de otra piel.

        El logotipo del cartel de bienvenida y el icono de su botón. Lo llama
        `MainWindow._repaint_theme` recorriendo el árbol de widgets, como a
        todo lo que lleva un icono dibujado a mano.
        """
        self._empty_logo.setPixmap(brand.wordmark(style.EMPTY_LOGO_HEIGHT))
        # El glifo de la sección a la que lleva —el mismo de la franja de
        # iconos—, en el color que va encima del relleno de acento.
        self._empty_button.setIcon(
            icons.database_icon(style.ACTION_ICON_SIZE, style.ON_ACCENT_COLOR)
        )

    def _clear_overlay_log(self) -> None:
        """Vacía el registro que se está viendo, sea cual sea de los dos."""
        if self._log_stack.currentIndex() == LOG_BUILD:
            self.build_log.clear()
        else:
            self.overlay_log.clear()

    def append_overlay_log(self, report: str) -> None:
        """Añade un informe de comprobación de overlays al registro inferior.

        Y abre la franja si estaba cerrada: quien acaba de pulsar «Validate»
        o «Check again» ha pedido justamente esto, y escribirlo donde no se
        ve es lo mismo que no escribirlo.
        """
        self.show_log_panel()
        self.overlay_log.appendPlainText(report)
        self.overlay_log.verticalScrollBar().setValue(
            self.overlay_log.verticalScrollBar().maximum()
        )

    def append_build_log(self, text: str) -> None:
        """Añade una línea del registro de compilación, y abre la franja.

        Se escribe según van llegando los pasos, no al final: compilar un
        árbol entero tarda lo suyo y un registro que aparece de golpe
        cuando ya ha terminado no cuenta lo que está pasando, solo lo que
        pasó.
        """
        self.show_log_panel()
        self.build_log.appendPlainText(text)
        self.build_log.verticalScrollBar().setValue(
            self.build_log.verticalScrollBar().maximum()
        )

    def _on_log_selected(self, page: int) -> None:
        """Enseña el registro elegido y esconde lo que no le sirve."""
        self._log_stack.setCurrentIndex(page)
        for widget in self._diagnostic_only:
            widget.setVisible(page == LOG_DIAGNOSTICS)
        self.clear_log_button.setVisible(page != LOG_DIAGNOSTICS)

    def _enabled_severities(self) -> Set[Severity]:
        """Niveles de gravedad que el usuario quiere ver."""
        return {
            severity
            for severity, check in self.severity_checks.items()
            if check.isChecked()
        }

    # ------------------------------------------------------------------
    # Documentos
    # ------------------------------------------------------------------
    @property
    def current(self) -> Optional[Document]:
        """Documento activo, si hay alguno abierto."""
        return self._documents.get(self.documents.currentWidget())

    # ------------------------------------------------------------------
    # Autocompletado
    # ------------------------------------------------------------------
    def _completion_items(self, prefix: str, context: str) -> List[CompletionItem]:
        """Sugerencias para lo que se está escribiendo en el editor.

        Con el cursor en el nombre de una propiedad se ofrecen las que admite
        el binding del nodo; escribiendo su valor, los que el binding enumera.
        Sin binding conocido no se ofrece nada: inventar nombres de propiedad
        sería peor que no ayudar.
        """
        document = self.current
        if (
            document is None
            or not document.is_device_tree
            or not self.service.binding_schemas_available()
        ):
            return []

        text = document.editor.toPlainText()
        position = document.editor.textCursor().position()
        where = self.service.completion_context(
            text,
            position,
            base_path=document.source_key,
            overlay_base=document.overlay_base,
        )
        if where.compatible is None:
            return []

        suggestions = self.service.suggest_properties(where.compatible)
        if context == "value":
            return _value_items(suggestions, where.property_name, prefix)
        written = self._written_properties(where.node_name, text, position)
        return _property_items(suggestions, prefix, written)

    def _written_properties(
        self, node_name: str, text: str, position: int
    ) -> Set[str]:
        """Propiedades ya escritas en el nodo donde está el cursor.

        Ofrecer una que ya está solo estorba; y las que faltan son justo las
        que interesan. Se descuenta la de la línea que se está escribiendo:
        si no, corregir el nombre de una propiedad existente dejaría la lista
        vacía justo cuando hace falta.
        """
        document = self.current
        if document is None or document.parse_result is None:
            return set()

        for node in document.parse_result.root.iter_tree():
            if node.name == node_name:
                return set(node.properties) - {_property_being_written(text, position)}
        return set()

    def _on_completion_inserted(self, key: str) -> None:
        """Tras aceptar una propiedad con valores enumerados, ofrece los valores."""
        document = self.current
        if document is None:
            return
        editor = document.editor
        text = editor.toPlainText()
        where = self.service.completion_context(
            text,
            editor.textCursor().position(),
            base_path=document.source_key,
            overlay_base=document.overlay_base,
        )
        if where.compatible is None:
            return
        for item in self.service.suggest_properties(where.compatible):
            if item.name == key and item.allowed_values:
                editor.show_completions("value")
                return

    def open_source(
        self,
        title: str,
        text: str,
        source_key: Optional[str] = None,
        disk_path: Optional[Path] = None,
        replace: bool = False,
        read_only: bool = False,
        overlay_base: Optional[DeviceTreeNode] = None,
    ) -> None:
        """Abre un fuente en el editor, o vuelve a él si ya estaba abierto.

        Con `replace=True` se descartan los documentos anteriores: es lo que
        ocurre al elegir otro SoC, que sustituye a lo que hubiera. Antes de
        descartarlos se pregunta por cualquiera con cambios sin guardar
        (`confirm_discard_all`), igual que al cerrar una pestaña suelta —
        cambiar de SoC no debe tirar ediciones a la papelera en silencio.

        Con `read_only=True` el documento no se puede editar ni guardar: es
        lo que abre el panel de versiones para enseñar un diff, que se
        colorea además con `DiffHighlighter` en vez de con el resaltador de
        DTS. El título de esos documentos termina en `.diff`, así que el
        motor semántico tampoco los analiza (`is_device_tree`).
        """
        if replace:
            if not self.confirm_discard_all():
                return
            self._clear_documents()

        for widget, document in self._documents.items():
            if source_key is not None and document.source_key == source_key:
                self.documents.setCurrentWidget(widget)
                self.documents_changed.emit()
                return

        editor = DtsEditor(
            highlighter=DiffHighlighter if read_only else DtsHighlighter
        )
        editor.setReadOnly(read_only)
        editor.cursorPositionChanged.connect(self._on_cursor_moved)
        editor.ctrlLineClicked.connect(self._on_editor_ctrl_click)
        editor.lineClicked.connect(self._on_editor_line_click)
        editor.hoverMoved.connect(self._on_editor_hover)
        editor.set_completion_provider(self._completion_items)
        editor.completionInserted.connect(self._on_completion_inserted)
        # Normalizado a `\n` dentro del editor: un `\r` suelto se dibujaría
        # como un carácter de control en mitad de la línea. Cuál era se
        # recuerda en `Document.newline` y vuelve al guardar.
        newline = file_io.detect_newline(text)
        text = file_io.normalize_newlines(text)
        editor.setPlainText(text)
        # Conectado después de `setPlainText`, no antes: si no, cargar el
        # texto inicial ya cuenta como "ha habido una edición" y arma el
        # temporizador de reanálisis (`ANALYSIS_DELAY_MS`) para nada — el
        # documento se analiza de todos modos en cuanto se activa su pestaña
        # (ver el comentario más abajo), así que ese análisis programado
        # sobraba entero.
        editor.textChanged.connect(self._on_text_changed)

        document = Document(
            editor=editor,
            title=title,
            source_key=source_key,
            disk_path=disk_path,
            fragment=not title.lower().endswith(".dts"),
            is_device_tree=_is_device_tree_title(title),
            read_only=read_only,
            saved_text=text,
            newline=newline,
            saved_newline=newline,
            overlay_base=overlay_base,
        )
        self._documents[editor] = document
        # El punto morado de "cambios sin guardar" en la pestaña de la
        # ventana lo decide `_refresh_modified_state` comparando contenido,
        # no `document().isModified()` de Qt directamente (ver su
        # docstring); esta conexión solo da la primera pista rápida de que
        # ha habido algún cambio -Qt la dispara al instante del primer
        # tecleo-, y el resto de reevaluaciones llegan por el temporizador
        # de análisis. Va después de crear `document` para poder cerrar
        # sobre él.
        editor.document().modificationChanged.connect(
            lambda _modified: self._refresh_modified_state(document)
        )
        self.documents.addTab(editor, title)
        # `addTab`/`setCurrentWidget` ya disparan `currentChanged` -uno de
        # los dos, según si esta es la primera pestaña o no- y por tanto
        # `_on_document_changed`, que analiza el documento nuevo
        # (`parse_result is None`) y emite `documents_changed` él solo. Antes
        # había aquí una llamada explícita a `analyze()` "por si acaso": esa
        # señal siempre llega antes de volver de `setCurrentWidget` (conexión
        # directa, mismo hilo), así que la llamada de más analizaba el mismo
        # documento dos veces —el doble de tiempo al abrir cualquier fichero,
        # sin ningún beneficio—.
        self.documents.setCurrentWidget(editor)

    def rename_document(self, old: Path, new: Path) -> bool:
        """Reapunta al fichero renombrado el documento que lo tuviera abierto.

        Sin esto, «Guardar» escribiría en el nombre viejo y lo resucitaría:
        la pestaña seguiría creyendo que edita un fichero que ya no existe.
        Devuelve si alguna pestaña era esa.

        Y también los que estaban **dentro**: renombrar o mover una carpeta
        cambia la ruta de todo lo que cuelga de ella, así que mirar solo si
        la ruta es exactamente la vieja dejaba resucitando el árbol entero
        en cuanto lo que se movía era una carpeta y no un fichero.
        """
        renamed = False
        for document in self._documents.values():
            clave = _reapuntada(document.source_key, old, new)
            destino = (
                _reapuntada(document.disk_path, old, new)
                or clave
            )
            if destino is None:
                continue
            if clave is not None:
                document.source_key = str(clave)
            document.disk_path = destino
            document.title = destino.name
            renamed = True
        if renamed:
            self.documents_changed.emit()
        return renamed

    def document_labels(self) -> List[Tuple[str, str, bool]]:
        """Título, descripción y si tiene cambios sin guardar, por pestaña.

        La ventana construye con esto su barra de ficheros, así que el orden
        debe ser el del `QTabWidget` y no el del diccionario de documentos.
        Lo de "sin guardar" es `document.is_dirty`, no
        `QTextDocument.isModified()` de Qt directamente — ver
        `_refresh_modified_state`.
        """
        labels: List[Tuple[str, str, bool]] = []
        for index in range(self.documents.count()):
            document = self._documents.get(self.documents.widget(index))
            if document is None:
                labels.append((self.documents.tabText(index), "", False))
                continue
            labels.append(
                (
                    document.title,
                    document.source_key or str(document.disk_path or document.title),
                    document.is_dirty,
                )
            )
        return labels

    def current_document_index(self) -> int:
        """Índice del documento activo, o -1 si no hay ninguno abierto."""
        return self.documents.currentIndex()

    def activate_document(self, index: int) -> None:
        """Pone al frente el documento indicado por la barra de la ventana."""
        if 0 <= index < self.documents.count():
            self.documents.setCurrentIndex(index)

    def close_document(self, index: int) -> None:
        """Cierra el documento indicado, tras confirmar si tiene cambios sin guardar."""
        widget = self.documents.widget(index)
        if widget is None:
            return

        document = self._documents.get(widget)
        if document is not None and not self._confirm_discard(document):
            return

        self._documents.pop(widget, None)
        self.documents.removeTab(index)
        widget.deleteLater()

        if self.documents.count() == 0:
            self.diagnostics_view.clear()
            self.summary_label.setText(self.tr("Not analyzed"))
            self._stack.setCurrentWidget(self._empty_page)
        self.documents_changed.emit()

    def confirm_discard_all(self) -> bool:
        """Pregunta, uno por uno, por cualquier documento con cambios sin guardar.

        Punto de entrada común antes de cerrar de golpe toda la sesión: al
        sustituirla entera (`open_source(replace=True)`, elegir otro SoC) o
        al cerrar la ventana (`MainWindow.closeEvent`). Ambas acciones
        descartaban antes lo que hubiera abierto sin avisar — la misma
        pérdida de trabajo que cerrar una pestaña sin preguntar, solo que de
        golpe y más fácil de disparar sin querer.
        """
        for index in range(self.documents.count()):
            document = self._documents.get(self.documents.widget(index))
            if document is not None and not self._confirm_discard(document):
                return False
        return True

    def _confirm_discard(self, document: Document) -> bool:
        """Si `document` tiene cambios, pregunta guardar/descartar/cancelar.

        Devuelve si es seguro seguir adelante con el cierre: `True` cuando no
        había nada que perder, se ha guardado, o el usuario ha elegido
        descartar a propósito; `False` cuando ha cancelado, momento en el que
        quien llama debe dejar el documento tal cual está.
        """
        if not document.is_dirty:
            return True

        choice = QMessageBox.question(
            self,
            messages.title_unsaved_changes(),
            messages.unsaved_changes(document.title),
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if choice == QMessageBox.Cancel:
            return False
        if choice == QMessageBox.Discard:
            return True
        return self._save_document(document)

    def _clear_documents(self) -> None:
        """Cierra todos los documentos abiertos."""
        while self.documents.count():
            widget = self.documents.widget(0)
            self._documents.pop(widget, None)
            self.documents.removeTab(0)
            widget.deleteLater()

    def _on_document_changed(self) -> None:
        """Refresca la interfaz al cambiar de documento activo."""
        self._stack.setCurrentWidget(
            self.documents if self.documents.count() else self._empty_page
        )
        self.documents_changed.emit()

        document = self.current
        if document is None:
            return
        self._fill_diagnostics()
        self._update_node_at_cursor(document)

        # Las demás vistas siguen al documento activo: al cambiar de fichero el
        # visualizador debe mostrar ese árbol, no el del anterior.
        if document.parse_result is None:
            # Diferido, no directo: esto se dispara en la misma pasada que
            # `addTab`/`setCurrentWidget` (ver `open_source`), y analizar ahí
            # mismo bloqueaba a Qt antes de que llegara a pintar el texto
            # recién cargado — ver `INITIAL_ANALYSIS_DELAY_MS`.
            QTimer.singleShot(
                INITIAL_ANALYSIS_DELAY_MS,
                lambda doc=document: self._analyze_if_current(doc),
            )
        else:
            self.document_analyzed.emit(document)

    def _analyze_if_current(self, document: Document) -> None:
        """Lanza el análisis diferido, solo si `document` sigue siendo el activo.

        Entre programar esto (`_on_document_changed`) y que el temporizador
        dispare, el usuario puede haber cambiado otra vez de pestaña —
        analizar entonces el documento equivocado, que ya ni se ve, sería
        trabajo tirado y podría además pisar el análisis que sí toca (el de
        la pestaña realmente activa, disparado por su propio
        `currentChanged`).
        """
        if self.current is document:
            self.analyze()

    # ------------------------------------------------------------------
    # Ficheros
    # ------------------------------------------------------------------
    def save_file(self) -> None:
        """Guarda el documento activo en el disco."""
        document = self.current
        if document is None:
            return
        self._save_document(document)

    def save_file_as(self) -> None:
        """Guarda el documento activo preguntando siempre dónde.

        «Guardar como…» existía solo como efecto secundario de guardar un
        documento que aún no tenía fichero propio; como acción no había forma
        de pedirla, ni desde el menú ni con atajo.
        """
        document = self.current
        if document is None:
            return
        self._save_document(document, ask_where=True)

    def _save_document(self, document: Document, ask_where: bool = False) -> bool:
        """Guarda `document` en disco; devuelve si llegó a guardarse.

        Independiente del documento activo a propósito: `_confirm_discard`
        necesita poder guardar uno que no lo sea (al cerrar una pestaña de
        fondo desde la barra de ficheros de la ventana, o todas de golpe con
        `confirm_discard_all`).

        Si ya tiene un fichero local asociado (`disk_path` — abierto con
        "Abrir del PC…" o como include resuelto en disco, ver
        `MainWindow._open_include`), se escribe directamente ahí: es lo que
        se espera de "Guardar" en cualquier editor de texto. El diálogo
        "Guardar como…" solo hace falta para un documento sin fichero propio
        (uno de la base de datos, o que aún no se ha guardado nunca).
        """
        if document.read_only:
            self.status_changed.emit(
                self.tr("{title} is read-only and cannot be saved").format(
                    title=document.title
                )
            )
            return False

        text = document.editor.toPlainText()

        if document.disk_path is not None and not ask_where:
            try:
                _write_text(document.disk_path, text, document.newline)
            except OSError as exc:
                QMessageBox.critical(
                    self, messages.title_file_save_error(), messages.file_error(exc)
                )
                return False
            self.mark_saved(document, text)
            self.status_changed.emit(
                self.tr("Saved to {path}").format(path=document.disk_path)
            )
            return True

        suggested = document.disk_path or (Path.cwd() / document.title)
        filename, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Save device tree"),
            str(suggested),
            self.tr("Device Tree (*.dts *.dtsi)"),
        )
        if not filename:
            return False

        path = Path(filename)
        try:
            _write_text(path, text, document.newline)
        except OSError as exc:
            QMessageBox.critical(
                self, messages.title_file_save_error(), messages.file_error(exc)
            )
            return False

        document.disk_path = path
        self.mark_saved(document, text)
        self.status_changed.emit(self.tr("Saved to {path}").format(path=path))
        return True

    def mark_saved(self, document: Document, text: str) -> None:
        """Registra `text` como el contenido guardado y limpia "sin guardar".

        Punto único desde el que cualquier ruta de guardado —`_save_document`,
        o una escritura directa como `MainWindow._apply_soc_overrides`—
        declara "esto es lo que hay en disco ahora"; el resto de la lógica de
        cambios sin guardar (`_refresh_modified_state`) compara siempre
        contra esto, no contra lo que hubiera al abrir el fichero.
        """
        document.saved_text = text
        document.saved_newline = document.newline
        document.editor.document().setModified(False)
        if document.is_dirty:
            document.is_dirty = False
            self.documents_changed.emit()
        self.document_saved.emit()

    # ------------------------------------------------------------------
    # Análisis
    # ------------------------------------------------------------------
    def _on_text_changed(self) -> None:
        """Reprograma, tras cada edición, el análisis y/o el chequeo de cambios.

        Se arma siempre, sea o no un device tree: incluso cuando el motor no
        analiza (`analyze` se salta entero), sigue haciendo falta reevaluar
        "sin guardar" por si el contenido ha vuelto a coincidir con lo
        guardado (ver `_refresh_modified_state`) — `_on_analysis_timeout`
        decide qué de los dos toca.
        """
        self._timer.start()

    def _on_analysis_timeout(self) -> None:
        """Qué hacer tras el retardo de `_on_text_changed`, según el documento."""
        document = self.current
        if document is None:
            return
        if document.is_device_tree:
            self.analyze()
        else:
            self._refresh_modified_state(document)

    def analyze(self) -> None:
        """Analiza el documento activo y vuelca sus diagnósticos.

        Se salta por completo para un documento que no es un device tree
        (`Document.is_device_tree`): el motor de análisis no tiene nada que
        decir sobre un `.c`, un `.h` o cualquier otro fichero abierto desde
        el panel de carpetas, y ejecutarlo ahí solo gastaría ciclos.
        """
        self._timer.stop()
        document = self.current
        if document is None:
            return

        if not document.is_device_tree:
            document.parse_result = None
            document.diagnostics = []
            self.diagnostics_view.clear()
            document.editor.set_diagnostics([])
            self.summary_label.setText(self.tr("No checks: not a .dts/.dtsi"))
            self._refresh_modified_state(document)
            self._update_node_at_cursor(document)
            self.document_analyzed.emit(document)
            return

        text = document.editor.toPlainText()
        if not text.strip():
            document.parse_result = None
            document.diagnostics = []
            self.diagnostics_view.clear()
            document.editor.set_diagnostics([])
            self.summary_label.setText(self.tr("Not analyzed"))
            self._refresh_modified_state(document, text)
            self._update_node_at_cursor(document)
            # También se avisa de un documento vacío: el visualizador tiene que
            # vaciarse al cambiar a él, no quedarse con el árbol anterior.
            self.document_analyzed.emit(document)
            return

        # La ruta del documento en la base es lo que permite resolver sus
        # includes relativos, y sin fusionarlos el análisis no puede afirmar
        # que a un nodo le falte nada.
        document.parse_result, document.diagnostics = self.service.analyze_source(
            text,
            fragment=document.fragment,
            base_path=document.source_key,
            overlay_base=document.overlay_base,
        )
        self._refresh_modified_state(document, text)
        self._fill_diagnostics()
        self._update_node_at_cursor(document)
        self.document_analyzed.emit(document)
        self._start_schema_checks(document, text)

    def refresh_modified_state(self, document: Document) -> None:
        """Vuelve a decidir si el documento tiene cambios sin guardar.

        Pública para lo que cambia el fichero **sin tocar el texto**: hoy es
        el fin de línea, que se elige en la franja de abajo.
        """
        self._refresh_modified_state(document)

    def _refresh_modified_state(
        self, document: Document, text: Optional[str] = None
    ) -> None:
        """Actualiza `document.is_dirty` comparando con lo último guardado.

        `QTextDocument.isModified()` de Qt solo sabe si ha habido *algún*
        cambio desde el último guardado, no si el contenido ha terminado
        siendo el mismo: borrar un carácter y volver a escribirlo lo dejaba
        marcado como "sin guardar" para siempre, aunque el fichero acabase
        siendo idéntico al que había. Aquí se compara de verdad, y solo se
        avisa (`documents_changed`, que es lo que repinta el punto morado de
        la pestaña) cuando el resultado cambia respecto al que ya se
        mostraba, no en cada llamada.
        """
        if text is None:
            text = document.editor.toPlainText()
        # El terminador cuenta como cambio: cambiar de LF a CRLF no toca una
        # sola letra del texto, pero sí cambia el fichero que se va a
        # escribir, y sin esto «Guardar» quedaba deshabilitado y el punto de
        # «sin guardar» no aparecía.
        dirty = (
            text != document.saved_text
            or document.newline != document.saved_newline
        )
        if dirty != document.is_dirty:
            document.is_dirty = dirty
            self.documents_changed.emit()

    def _start_schema_checks(self, document: Document, text: str) -> None:
        """Anota el documento a comprobar y reprograma la pasada de fondo."""
        self._schema_scheduler.schedule(
            self._document_token(document, text),
            text,
            document.fragment,
            document.source_key,
        )

    def _document_token(self, document: Document, text: str) -> str:
        """Identifica una versión concreta de un documento.

        El resultado de la capa 2 llega tarde: si mientras tanto se ha escrito
        o se ha cambiado de fichero, hay que descartarlo en vez de mezclar
        avisos de un texto con las líneas de otro.
        """
        return f"{document.title}\u0000{len(text)}\u0000{hash(text)}"

    def _on_schema_checks(self, token: str, diagnostics: List[Diagnostic]) -> None:
        """Incorpora los avisos diferidos si siguen correspondiendo al texto."""
        document = self.current
        if document is None or not diagnostics:
            return

        text = document.editor.toPlainText()
        if token != self._document_token(document, text):
            return

        document.diagnostics = self.service.merge_deferred(
            document.diagnostics, diagnostics
        )
        self._fill_diagnostics()
        self.status_changed.emit(self.tr("Schema checks finished"))

    def _on_schema_busy(self, busy: bool) -> None:
        """Traslada el estado de la pasada diferida a la ventana."""
        self.busy_changed.emit(busy)
        if busy:
            self.status_changed.emit(self.tr("Checking against the schemas…"))

    def stop_workers(self) -> None:
        """Detiene la comprobación de fondo; se llama al cerrar la ventana."""
        self._schema_scheduler.stop()

    def _on_cursor_moved(self) -> None:
        """Informa de la posición y del nivel de anidación en la barra de estado."""
        document = self.current
        if document is None:
            return
        cursor = document.editor.textCursor()
        self.cursor_moved.emit(
            cursor.blockNumber() + 1,
            cursor.columnNumber() + 1,
            document.editor.current_depth_label(),
        )
        self._update_node_at_cursor(document)

    def cursor_position(self) -> Optional[tuple]:
        """Línea, columna y ruta del nodo bajo el cursor, o `None` sin documento.

        Lo mismo que emite `cursor_moved`, para quien necesite el estado
        actual sin haber estado escuchando -la franja de abajo se recompone
        entera al cambiar de idioma, y ahí no ha habido ningún movimiento.
        """
        document = self.current
        if document is None:
            return None
        cursor = document.editor.textCursor()
        return (
            cursor.blockNumber() + 1,
            cursor.columnNumber() + 1,
            document.editor.current_depth_label(),
        )

    def _update_node_at_cursor(self, document: Document) -> None:
        """Recalcula el nodo bajo el cursor y avisa al Inspector si ha cambiado."""
        node = self._node_at_cursor(document)
        if node is not self._last_inspected_node:
            self._last_inspected_node = node
            self.node_at_cursor_changed.emit(node)

    def _node_at_cursor(self, document: Document) -> Optional[DeviceTreeNode]:
        """Nodo del último análisis que contiene la línea del cursor, si hay.

        Se apoya en el mismo emparejado de llaves que ya mantiene el
        plegado (`DtsEditor.innermost_fold_region`), que va siempre al día
        con el texto en pantalla, y lo cruza por número de línea con
        `document.parse_result` -que puede ir con retraso mientras se
        escribe-. Sin región (el cursor ni siquiera está dentro de `/ { }`)
        no hay nodo que señalar.

        La raíz es un caso aparte: `parse_dts_source` le fija `line = 1`
        siempre, a propósito, para que los diagnósticos de nivel de
        documento apunten ahí pase lo que pase antes del `/ {` real (un
        `#include`, comentarios...) — no a la línea real de su propia llave,
        que es justo lo que da `region`. Por eso, si ningún nodo casa con
        `region` es que el cursor está dentro del cuerpo de la raíz y no en
        el de ningún hijo (esos sí llevan su línea real, puesta por
        `_open_node`): se cae a la raíz en vez de a "ningún nodo".
        """
        if document.parse_result is None:
            return None
        line = document.editor.textCursor().blockNumber() + 1
        region = document.editor.innermost_fold_region(line)
        if region is None:
            return None
        start, _end = region
        for node in document.parse_result.root.iter_tree():
            if node.line == start:
                return self.service.resolve_inspected_node(
                    node, document.parse_result, document.source_key
                )
        return document.parse_result.root

    def _on_editor_line_click(self, line: int) -> None:
        """Avisa de qué nodo hay en la línea pulsada, si el documento es DTS."""
        document = self.current
        if document is None or not document.is_device_tree:
            return
        self.node_clicked.emit(self.node_at_line(document, line))

    def node_at_line(
        self, document: Document, line: int
    ) -> Optional[DeviceTreeNode]:
        """Nodo del último análisis que contiene `line`, por su región de llaves.

        Es lo mismo que hace `_node_at_cursor` pero para una línea dada en
        vez de para el cursor; ver allí por qué la raíz es un caso aparte.
        """
        if document.parse_result is None:
            return None
        region = document.editor.innermost_fold_region(line)
        if region is None:
            return None
        start, _end = region
        for node in document.parse_result.root.iter_tree():
            if node.line == start:
                return node
        return document.parse_result.root

    def all_documents(self) -> List[Document]:
        """Todos los documentos abiertos, en el orden de la barra."""
        return [
            self._documents[self.documents.widget(index)]
            for index in range(self.documents.count())
            if self.documents.widget(index) in self._documents
        ]

    def device_tree_documents(self) -> List[Document]:
        """Documentos abiertos que son un device tree completo, en orden.

        Sin los overlays: la base de un overlay es un árbol entero, y otro
        overlay no puede serlo.
        """
        documents = []
        for index in range(self.documents.count()):
            document = self._documents.get(self.documents.widget(index))
            if (
                document is not None
                and document.is_device_tree
                and not document.is_overlay
                and not document.read_only
            ):
                documents.append(document)
        return documents

    def text_of(self, key: str) -> Optional[str]:
        """Texto del documento abierto con esa clave, o `None` si no hay ninguno.

        Se mira antes que el disco: lo que está en pantalla puede tener
        cambios sin guardar, y comprobar un overlay contra la versión vieja
        de su base sería mentir sobre lo que se está viendo.
        """
        for document in self._documents.values():
            if document.source_key == key or str(document.disk_path or "") == key:
                return document.editor.toPlainText()
        return None

    def activate_last_device_tree(self) -> Optional[Document]:
        """Pone al frente el device tree abierto más reciente, si hay alguno.

        Si el que ya está activo lo es, no se toca nada: cambiar de fichero
        debajo de quien acaba de pedir "elige un nodo" sería justo lo
        contrario de ayudarle.
        """
        document = self.current
        if document is not None and document.is_device_tree:
            return document
        for index in reversed(range(self.documents.count())):
            candidate = self._documents.get(self.documents.widget(index))
            if candidate is not None and candidate.is_device_tree:
                self.documents.setCurrentIndex(index)
                return candidate
        return None

    def focus_editor(self) -> None:
        """Da el foco al texto del documento activo."""
        document = self.current
        if document is not None:
            document.editor.setFocus()

    def _on_editor_ctrl_click(self, line: int, column: int) -> None:
        """Ir a la definición de lo que hay bajo el cursor: include o referencia.

        Un include se abre entero (da igual de qué tipo sea: a diferencia del
        visualizador, aquí el usuario pide explícitamente abrirlo, así que no
        hay razón para filtrar por extensión). Un `&label` o un `&{/ruta}` —el
        de una reapertura o el de un phandle dentro de un valor— lleva a donde
        ese nodo se declara, que en una placa es el `.dtsi` de su SoC.
        """
        directive = self._include_at_line(line)
        if directive is not None:
            document = self.current
            resolved = self.service.resolve_include(directive, document.source_key)
            self.include_requested.emit(resolved)
            return

        reference = self._reference_at(line, column)
        if reference is not None:
            self.definition_requested.emit(reference[0])

    def _on_editor_hover(self, line: int, column: int, ctrl: bool) -> None:
        """Subraya el include bajo el ratón mientras se mantiene Ctrl pulsado.

        Solo una pista visual: el propio `DtsEditor` no sabe qué es un
        include, así que aquí se decide si la posición cae sobre el `target`
        de uno y se le pide que lo marque o que lo borre.
        """
        document = self.current
        if document is None:
            return

        if self._node_picking:
            self._hint_node(document, line)
            return

        if not ctrl:
            document.editor.set_include_hint(None)
            return

        directive = self._include_at_line(line)
        if directive is not None:
            line_text = document.editor.document().findBlockByNumber(line - 1).text()
            start = line_text.find(directive.target)
            if start >= 0 and start <= column <= start + len(directive.target):
                document.editor.set_include_hint(
                    (line, start, len(directive.target))
                )
                return

        # Misma pista para un `&label`: se ve qué se va a abrir antes de
        # pulsar, igual que con un include.
        reference = self._reference_at(line, column)
        if reference is None:
            document.editor.set_include_hint(None)
            return
        _, start, length = reference
        document.editor.set_include_hint((line, start, length))

    def set_node_picking(self, enabled: bool) -> None:
        """Enciende o apaga el modo «señala un nodo» del asistente de overlays.

        Mientras está encendido, pasar el ratón por encima resalta el nodo
        entero que hay debajo —si se puede elegir— y el cursor se convierte
        en una mano: se ve **qué** se va a elegir antes de pulsar. Al
        apagarlo se limpia la marca de todos los documentos, no solo del
        activo, porque se puede haber cambiado de fichero mientras tanto.
        """
        self._node_picking = enabled
        if not enabled:
            for document in self._documents.values():
                document.editor.set_node_hint(None)

    def _hint_node(self, document: Document, line: int) -> None:
        """Resalta el nodo de `line`, si es uno al que un overlay puede apuntar.

        Un nodo sin etiqueta ni ruta no se puede escribir como objetivo, así
        que no se marca: la pista tiene que decir la verdad sobre lo que va a
        pasar al pulsar.
        """
        document.editor.set_include_hint(None)
        region = document.editor.innermost_fold_region(line)
        node = self.node_at_line(document, line)
        if region is None or node is None or not (node.label or node.path):
            document.editor.set_node_hint(None)
            return
        document.editor.set_node_hint(region)

    def _reference_at(
        self, line: int, column: int
    ) -> Optional[Tuple[str, int, int]]:
        """Referencia `&…` bajo esa columna, como (texto, inicio, longitud).

        Se lee del texto y no del árbol: una referencia aparece tanto en la
        cabecera de una reapertura (`&i2c0 {`) como dentro de un valor
        (`clocks = <&clk 1>`), y el parser solo registra la primera. Una línea
        puede tener varias, de ahí la columna.
        """
        document = self.current
        if document is None or not document.is_device_tree:
            return None
        line_text = document.editor.document().findBlockByNumber(line - 1).text()
        for match in _REFERENCE_RE.finditer(line_text):
            if match.start() <= column <= match.end():
                return (match.group(), match.start(), len(match.group()))
        return None

    def _include_at_line(self, line: int) -> Optional[IncludeDirective]:
        """Directiva de include escrita en `line` del documento activo, si hay."""
        document = self.current
        if document is None or document.parse_result is None:
            return None
        return next(
            (item for item in document.parse_result.includes if item.line == line),
            None,
        )

    def _fill_diagnostics(self) -> None:
        """Rellena la lista de diagnósticos aplicando el filtro de gravedad."""
        self.diagnostics_view.clear()
        document = self.current
        if document is None:
            self.diagnostics_changed.emit(0, 0, 0)
            return

        enabled = self._enabled_severities()
        shown = 0
        for diagnostic in document.diagnostics:
            if diagnostic.severity not in enabled:
                continue
            shown += 1
            item = QTreeWidgetItem(
                [
                    SEVERITY_ICON.get(diagnostic.severity, "•"),
                    str(diagnostic.line),
                    diagnostic.message,
                    diagnostic.hint or "",
                ]
            )
            item.setData(0, Qt.UserRole, diagnostic.line)
            item.setToolTip(2, f"{diagnostic.code.value}\n{diagnostic.message}")
            color = QColor(SEVERITY_COLOR[diagnostic.severity])
            item.setForeground(0, color)
            item.setForeground(1, QColor(style.MUTED_TEXT_COLOR))
            item.setTextAlignment(0, Qt.AlignCenter)
            item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            self.diagnostics_view.addTopLevelItem(item)

        # Solo el icono y la línea se ajustan a contenido; "Problema" y
        # "Sugerencia" están en modo Stretch y se reparten el resto del
        # ancho disponible.
        for column in range(2):
            self.diagnostics_view.resizeColumnToContents(column)

        counts = {
            severity: sum(1 for d in document.diagnostics if d.severity is severity)
            for severity in Severity
        }
        self.summary_label.setText(
            self.tr("{errors} errors · {warnings} warnings · {info} info").format(
                errors=counts[Severity.ERROR],
                warnings=counts[Severity.WARNING],
                info=counts[Severity.INFO],
            )
        )

        hidden = len(document.diagnostics) - shown
        self.filtered_label.setText(
            self.tr("{hidden} hidden by the filter").format(hidden=hidden)
            if hidden
            else ""
        )
        document.editor.set_diagnostics(
            [d for d in document.diagnostics if d.severity in enabled]
        )
        self.diagnostics_changed.emit(
            counts[Severity.ERROR], counts[Severity.WARNING], counts[Severity.INFO]
        )

    def _on_diagnostic_activated(self, item: QTreeWidgetItem) -> None:
        """Lleva el cursor del editor a la línea del diagnóstico elegido."""
        document = self.current
        line = item.data(0, Qt.UserRole)
        if document is not None and isinstance(line, int):
            document.editor.go_to_line(line)


# Plantilla del valor según el tipo que declara el binding. Insertar el
# esqueleto ahorra el paso mecánico y, sobre todo, evita la duda de si el
# valor va entre `<>` (números) o entre comillas (cadenas).
_VALUE_TEMPLATES = {
    "flag": (";", 0),
    "string": (' = "";', 2),
    "string-array": (' = "";', 2),
    "phandle": (" = <&>;", 2),
    "phandle-array": (" = <&>;", 2),
}
_DEFAULT_TEMPLATE = (" = <>;", 2)


def _property_items(
    suggestions: List[PropertySuggestion], prefix: str, written: Set[str]
) -> List[CompletionItem]:
    """Convierte las propiedades sugeridas en entradas de la lista."""
    items: List[CompletionItem] = []
    for suggestion in suggestions:
        if suggestion.name in written or not suggestion.name.startswith(prefix):
            continue
        if suggestion.is_node:
            insert, back = (" {\n};", 3)
        else:
            insert, back = _VALUE_TEMPLATES.get(
                suggestion.dt_type or "", _DEFAULT_TEMPLATE
            )
        items.append(
            CompletionItem(
                label=_label_for(suggestion),
                insert=f"{suggestion.name}{insert}",
                cursor_back=back,
                key=suggestion.name,
            )
        )
    return items


def _value_items(
    suggestions: List[PropertySuggestion],
    property_name: Optional[str],
    prefix: str,
) -> List[CompletionItem]:
    """Valores admitidos por la propiedad que se está escribiendo."""
    if property_name is None:
        return []
    for suggestion in suggestions:
        if suggestion.name != property_name:
            continue
        return [
            CompletionItem(label=value, insert=value, key=value)
            for value in suggestion.allowed_values
            if value.startswith(prefix)
        ]
    return []


def _label_for(suggestion: PropertySuggestion) -> str:
    """Texto de una sugerencia: el nombre y, detrás, de qué tipo es.

    Las dos marcas son texto de usuario y pasan por `QCoreApplication.
    translate` —aquí no hay `QObject` del que colgar `self.tr()`—, como en
    `gui/messages.py`. El tipo (`dt_type`) no: es el nombre que le da el
    binding (`string-array`, `phandle-array`), y traducirlo sería inventarse
    un vocabulario que no existe en ningún schema.
    """
    marks = []
    if suggestion.required:
        marks.append(QCoreApplication.translate("EditorTab", "required"))
    if suggestion.dt_type:
        marks.append(suggestion.dt_type)
    if suggestion.is_node:
        marks.append(QCoreApplication.translate("EditorTab", "node"))
    return f"{suggestion.name}    {', '.join(marks)}" if marks else suggestion.name


def _property_being_written(text: str, position: int) -> str:
    """Nombre de la propiedad de la línea en la que está el cursor."""
    start = text.rfind("\n", 0, position) + 1
    end = text.find("\n", position)
    line = text[start:end if end != -1 else len(text)].strip()
    return line.split("=", 1)[0].strip().rstrip(";")
