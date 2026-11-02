"""Ventana principal de KernelGrove.

La barra de SoCs vive aquí, no dentro de una pestaña: elegir un device tree no
es una acción del generador, sino de la aplicación entera. Hay dos formas de
hacerlo —el catálogo de la base de datos o un fichero del PC— y ambas
desembocan en lo mismo: el fuente se abre en el editor, y de ahí salen el
visualizador y el generador.

Por lo mismo, la barra con los ficheros abiertos también está aquí, encima de
las tres vistas: el documento activo es el que se edita **y** el que se
visualiza, así que se puede cambiar de fichero sin volver al editor.
"""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from kernelgrove import __version__
from PySide6.QtCore import (
    QCoreApplication,
    QFileSystemWatcher,
    QSettings,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QKeySequence,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from kernelgrove.api import (
    DeviceTreeNode,
    find_by_reference,
    KernelGroveService,
    PropertyOverride,
    ResolvedInclude,
    cpp_version,
    decompile_blob,
    detect_toolchain,
    dtc_version,
    extract_hardware,
    SoCSummary,
    StoredSource,
    apply_overrides,
    node_span,
)
from kernelgrove.gui import features, file_io, messages, style, theme, translations
from kernelgrove.gui.translations import Retranslates
from kernelgrove.gui.models.tree_model import PeripheralTreeModel
from kernelgrove.gui.tabs import (
    DatabaseTab,
    EditorTab,
    GeneratorTab,
    OverlayTab,
    VisualizerTab,
)
from kernelgrove.gui.tabs.database_tab import KIND_BOARD, KIND_SOC
from kernelgrove.gui.tabs.editor_tab import LOG_BUILD, LOG_DIAGNOSTICS, LOG_OVERLAYS
from kernelgrove.gui.widgets import icons
from kernelgrove.gui.widgets.activity_bar import ActivityBar, ActivitySection
from kernelgrove.gui.widgets.command_palette import CommandPalette, PaletteEntry
from kernelgrove.gui.widgets.card import Card
from kernelgrove.gui.widgets.overlay_list import (
    GLYPH_FAIL,
    GLYPH_INFO,
    GLYPH_OK,
    GLYPH_WARN,
    OVERLAY_SCAN_DEPTH,
    RULE,
)
from kernelgrove.gui.widgets.build_panel import BuildPanel
from kernelgrove.gui.widgets.overlay_panel import OverlayPanel
from kernelgrove.gui.widgets.schema_dialog import show_schema
from kernelgrove.gui.widgets.property_panel import PropertyPanel
from kernelgrove.gui.widgets.dts_editor import DtsEditor
from kernelgrove.gui.widgets.file_explorer import FileExplorerPanel
from kernelgrove.gui.widgets.git_panel import GitPanel
from kernelgrove.gui.widgets.inspector_panel import InspectorPanel
from kernelgrove.gui.widgets.legal_dialog import LegalDialog, licenses_text
from kernelgrove.gui.widgets.soc_properties_dialog import SocPropertiesDialog
from kernelgrove.gui.widgets.tab_close_button import TabCloseButton

# Flechas del botón de plegado de un dock: apunta hacia donde se va a
# esconder el contenido (plegado) o hacia donde va a reaparecer
# (desplegado), como en cualquier panel lateral colapsable.
COLLAPSE_ARROW_RIGHT = "›"
COLLAPSE_ARROW_LEFT = "‹"

TAB_EDITOR = 0
TAB_VISUALIZER = 1
TAB_GENERATOR = 2
# La última, porque es la única que no está siempre: se inserta al empezar
# un borrador de overlay y se quita al terminarlo (`_show_overlay_tab`).
# Ni la ficha de una propiedad ni el catálogo de la base están aquí: son
# **ventanas flotantes** (`PropertyPanel`, `DatabaseTab`), porque las dos se
# consultan mientras se escribe y quitarte el editor para enseñarlas obliga
# a volver.
TAB_OVERLAY = 3

# Secciones del panel lateral, en el orden en que las monta la barra.
# La franja de iconos de la izquierda es **la navegación principal**: cada
# sección elige a la vez qué panel lateral se ve y qué vista ocupa el
# centro, como la Activity Bar de VS Code y como el IDE de referencia. Antes
# había dos navegaciones para lo mismo -esta franja para el panel y una fila
# de pestañas para la vista-, y había que mover las dos para llegar a algún
# sitio.
SECTION_FOLDERS = 0
SECTION_CONNECTIONS = 1
SECTION_VERSIONS = 2
SECTION_OVERLAY = 3
# Compilar es otra tarea que escribir un overlay -otro momento y otras
# herramientas-, así que tiene su propia sección en vez de un bloque al pie
# de la de overlays. Lo único que comparten es qué overlays entran en la
# compilación, y eso se dice, no se repite.
SECTION_BUILD = 4
SECTION_DATABASE = 5

# Páginas del `QStackedWidget` lateral. No son las secciones: la lista de
# conexiones y el catálogo no traen panel propio y se quedan con el de
# carpetas.
PANEL_FOLDERS = 0
PANEL_VERSIONS = 1
PANEL_OVERLAY = 2
PANEL_BUILD = 3

# Qué vista central abre cada sección de la franja de iconos. Versiones y
# overlays se quedan en el editor: lo que se pulsa en sus paneles -un diff,
# un `.dtso` de la lista- se abre ahí.
SECTION_VIEWS = {
    # **Una sección elige panel, no vista.** La única que trae vista propia
    # es la lista de conexiones, que no es un panel sino una tabla a todo lo
    # ancho. Las demás -carpetas, versiones, overlays- son
    # paneles *sobre* el documento: cambiar de panel para mirar otra cosa no
    # puede llevarse por delante lo que estabas viendo en el centro.
    #
    # Quién decide si el documento se ve como texto o como grafo es **el pie
    # del panel** (`PanelFooter`, `_jump_to_other_view`), y solo él. El
    # catálogo tampoco está aquí: abre su propia ventana (`open_database`).
    SECTION_CONNECTIONS: TAB_GENERATOR,
}

# Las dos formas de ver el mismo documento. La que esté puesta es la que se
# usa al abrir un fichero o al elegir un nodo, y la alterna el pie del panel.
_DOCUMENT_VIEWS = (TAB_EDITOR, TAB_VISUALIZER)

# Las vistas que ocupan todo el ancho y no llevan panel al lado. Son a las
# que una sección de panel *sí* tiene que sacarte: abrir Carpetas sobre el
# catálogo dejaría el árbol de ficheros junto a una lista que se lee entera.
_FULL_WIDTH_VIEWS = (TAB_GENERATOR,)

# Ancho del hueco lateral: el de arranque y el mínimo al que se puede
# estrechar. El mínimo es poco a propósito: lo que hay dentro son árboles y
# texto, que ya se recortan y se desplazan solos, así que quien quiera el
# panel casi cerrado debe poder dejarlo así.
#
# **Es uno solo para las cuatro secciones que tienen panel.** Carpetas,
# estructura, versiones y overlays no son cuatro ventanas: son cuatro
# paneles en el mismo hueco, y el ancho es del hueco, no de lo que hay
# dentro. Overlays tenía el suyo -más ancho, por su lista de propiedades
# con el valor al lado- y el resultado era que el hueco daba un salto al
# entrar y otro al salir, deshaciendo de paso lo que el usuario hubiera
# ajustado a mano.
LEFT_DOCK_WIDTH = style.ACTIVITY_BAR_WIDTH + 180
# Cuánto se espera desde el último cambio en la carpeta antes de releer las
# listas. Una compilación escribe varios ficheros seguidos y cada uno avisa;
# volver a comprobar todos los overlays una vez por fichero es trabajo tirado
# y se nota.
FOLDER_REREAD_MS = 400

LEFT_PANEL_MIN_WIDTH = 60

# Ajustes que sobreviven entre sesiones. Por ahora solo la carpeta del panel
# lateral: la de partida (el directorio de la aplicación) casi nunca es donde
# el usuario tiene sus device trees.
SETTINGS_ORG = "KernelGrove"
SETTINGS_APP = "KernelGrove"
SETTING_EXPLORER_ROOT = "explorer/root"
# Idioma elegido en «Ver → Idioma». Vacío = el del sistema, que es como
# arranca la primera vez. Lo lee `gui/app.run_app` antes de construir nada.
SETTING_LANGUAGE = "ui/language"
# Modo claro/oscuro elegido en «Ver → Apariencia». Vacío o `system` = el del
# escritorio, que es como arranca la primera vez y es el equivalente del
# `prefers-color-scheme` de la web.
SETTING_THEME = "ui/theme"
# Piel elegida en «Ver → Apariencia»: la clásica (la de siempre) o la de la
# web. Vacío = la clásica.
SETTING_SKIN = "ui/skin"
# Release del kernel contra la que se trabaja, elegida en la barra de estado.
# Vacío = ninguna, y entonces no se comprueba la antigüedad de los bindings
# (ver `KernelGroveService.kernel_target` y `checks/bindings/rules.py`).
SETTING_KERNEL = "project/kernel"


def apply_theme(app, mode: str, skin: str = None) -> None:
    """Pone la aplicación en esa piel y ese modo.

    La paleta primero y la hoja de estilos después: la paleta es lo que usa
    el estilo nativo para dibujar lo que el QSS no alcanza (la marca de una
    casilla, las flechas), y el QSS manda sobre ella donde ambos opinan.

    Vive aquí y no en `theme` porque es lo único de ese módulo que necesita
    una `QApplication`, y `theme` se importa también sin ella.
    """
    theme.set_mode(mode, skin)
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.stylesheet())


# Controles cuyo ancho mínimo lo decide el texto que llevan dentro. Son los
# que hay que dejar estrechar para que el panel lateral se pueda cerrar casi
# del todo; el resto (árboles, editores) ya se desplazan solos.
_TEXT_SIZED_WIDGETS = (QCheckBox, QComboBox, QLabel, QLineEdit, QPushButton)


def _watched_dirs(folder: Path) -> List[Path]:
    """La carpeta y sus subcarpetas hasta donde llega el listado.

    Las mismas que recorre `scan_files`, y por lo mismo: las ocultas fuera
    —un `.git` son miles de ficheros y ninguno es un device tree— y sin
    bajar más allá de `OVERLAY_SCAN_DEPTH`.
    """
    carpetas = [folder]
    pendientes = [(folder, 0)]
    while pendientes:
        actual, nivel = pendientes.pop(0)
        if nivel >= OVERLAY_SCAN_DEPTH:
            continue
        try:
            hijos = sorted(actual.iterdir())
        except OSError:
            continue
        for hijo in hijos:
            if hijo.is_dir() and not hijo.name.startswith("."):
                carpetas.append(hijo)
                pendientes.append((hijo, nivel + 1))
    return carpetas


def _allow_narrow(page: QWidget) -> None:
    """Deja que el panel lateral se estreche por debajo del ancho de sus textos.

    Un botón pide de mínimo lo que ocupa su etiqueta, y en un `QStackedWidget`
    el mínimo del hueco es el del panel más ancho: «Start version control
    here» bastaba para que el dock entero no bajase de 370 px, mandara lo que
    mandara `setMinimumWidth`. Con la política `Ignored` el layout deja de
    tener en cuenta ese mínimo y el texto se recorta al estrechar, que es lo
    que hace cualquier barra lateral.
    """
    for child in page.findChildren(QWidget):
        if not isinstance(child, _TEXT_SIZED_WIDGETS):
            continue
        policy = child.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Ignored)
        child.setSizePolicy(policy)


class BaseChoiceDialog(Retranslates, QDialog):
    """Contra qué device tree comprobar un overlay.

    Existe porque un overlay no lleva su base dentro y la respuesta no se
    puede adivinar: el mismo `.dtso` puede ser correcto sobre una placa e
    imposible sobre otra. Tampoco se deduce del fichero —no se le anota la
    procedencia en un comentario—, así que este diálogo es la única fuente,
    y por eso ofrece las dos: el catálogo de la base de datos (con lo que
    hay abierto y la carpeta del proyecto delante) y un fichero cualquiera
    del disco.

    El combo es editable con autocompletado «contiene», como los selectores
    de SoC de la ventana: el catálogo son cientos de entradas y una lista
    desplegable a secas no se recorre.
    """

    def __init__(
        self,
        overlay: str,
        candidates,
        parent=None,
        title: str = "",
        caption: str = "",
    ):
        """Lista las bases posibles, con la salida a un fichero del disco.

        `title`/`caption` los pone quien lo abre para otra cosa —elegir qué
        device tree se va a compilar—: la lista de candidatos es la misma,
        la pregunta no.
        """
        super().__init__(parent)
        self._overlay = overlay
        self._title = title
        self._caption_text = caption
        self._chosen: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        self._caption = QLabel()
        self._caption.setWordWrap(True)
        self._combo = QComboBox()
        self._combo.setEditable(True)
        self._combo.setInsertPolicy(QComboBox.NoInsert)
        self._combo.completer().setCompletionMode(QCompleter.PopupCompletion)
        self._combo.completer().setFilterMode(Qt.MatchContains)
        self._combo.completer().setCaseSensitivity(Qt.CaseInsensitive)
        self._combo.setMinimumWidth(style.SOC_COMBO_MIN_WIDTH)
        for key, label in candidates:
            self._combo.addItem(label, key)

        self._browse_button = QPushButton()
        self._browse_button.clicked.connect(self._browse)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.addButton(self._browse_button, QDialogButtonBox.ActionRole)

        layout.addWidget(self._caption)
        layout.addWidget(self._combo)
        layout.addWidget(buttons)
        self.retranslate()

    def retranslate(self) -> None:
        """Rehace los textos fijos (ver `Retranslates`)."""
        self.setWindowTitle(self._title or self.tr("Validate overlay"))
        self._browse_button.setText(self.tr("From PC…"))
        self._caption.setText(
            self._caption_text
            or self.tr(
                "Check {overlay} against which device tree? An overlay is "
                "only correct with respect to the tree it is applied to."
            ).format(overlay=self._overlay)
        )

    def _browse(self) -> None:
        """Elige la base a mano: un fichero que no está ni abierto ni en la base.

        Se acepta el diálogo con lo elegido en vez de solo añadirlo a la
        lista: quien va a buscar un fichero al disco ya ha contestado a la
        pregunta, y hacerle confirmar otra vez sobra.
        """
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Choose the base device tree"),
            "",
            self.tr("Device trees (*.dts *.dtsi);;All files (*)"),
        )
        if not path:
            return
        self._chosen = path
        self.accept()

    def choose(self) -> Optional[str]:
        """Enseña el diálogo y devuelve la clave elegida, o `None` si se cancela."""
        if self.exec() != QDialog.Accepted:
            return None
        return self._chosen or self._combo.currentData()


class _StatusItem(QWidget):
    """Un indicador de la franja de abajo: su icono y su texto.

    Widget y no un `QLabel` con el icono metido en HTML: el color de la
    franja cambia con la piel (con la obsidiana va entera de acento, con
    texto oscuro encima), y un icono dibujado a mano tiene que repintarse
    en ese color. `refresh_icon` es lo que llama la ventana al cambiar de
    tema; un `<img>` incrustado no habría por dónde recolorearlo.
    """

    def __init__(self, draw, parent=None):
        """Monta icono (si lo hay) y etiqueta, en una fila apretada."""
        super().__init__(parent)
        self.setObjectName("statusItem")
        self._draw = draw
        row = QHBoxLayout(self)
        row.setContentsMargins(7, 0, 7, 0)
        row.setSpacing(4)
        self._icon = QLabel()
        self._icon.setObjectName("statusItemIcon")
        self._icon.setVisible(draw is not None)
        self._text = QLabel()
        self._text.setObjectName("statusItemText")
        row.addWidget(self._icon)
        row.addWidget(self._text)
        self.refresh_icons()

    def refresh_icons(self) -> None:
        """Redibuja el icono en el color activo de la franja."""
        if self._draw is None:
            return
        size = style.STATUS_ICON_SIZE
        self._icon.setPixmap(
            self._draw(size, theme.STATUSBAR_FG).pixmap(size, size)
        )

    def set_text(self, text: str) -> None:
        """Escribe el valor que acompaña al icono."""
        self._text.setText(text)

    def text(self) -> str:
        """Lo último escrito. Lo usan las pruebas y el cambio de idioma."""
        return self._text.text()


def _status_item(draw) -> _StatusItem:
    """Atajo para montar un indicador de la franja."""
    return _StatusItem(draw)


def _is_overlay(path: Path, text: str) -> bool:
    """Si un fichero del disco es un overlay, por su extensión o su contenido.

    `.dtso` lo dice el nombre; un `.dts` solo si lleva `/plugin/`, que es la
    marca con la que el propio formato declara que es un fragmento que se
    aplica sobre otro árbol.
    """
    if path.suffix.lower() == ".dtso":
        return True
    return path.suffix.lower() == ".dts" and "/plugin/" in text


def _find_node_by_path(root: DeviceTreeNode, path: str) -> Optional[DeviceTreeNode]:
    """Busca en `root` el nodo cuyo `path` es exactamente `path`.

    El grafo solo conserva el `path` de cada `GraphNode` (ver
    `tree_graph.build_graph`), no una referencia al `DeviceTreeNode` real —
    entre reconstrucciones del grafo el árbol fusionado cambia, así que hay
    que volver a resolverlo cada vez que se pide.
    """
    for node in root.iter_tree():
        if node.path == path:
            return node
    return None


def _show_tool_window(window) -> None:
    """Enseña una ventana auxiliar sin modal y la trae al frente si ya estaba.

    Es lo que hace que el panel del SoC y el Inspector del grafo se comporten
    como la ficha de propiedades del editor (`PropertyPanel`): una ventana
    propia que se puede mover y dejar a un lado mientras se sigue trabajando,
    en vez de un diálogo modal que bloquea la aplicación hasta cerrarlo.
    `Qt.Tool` la mantiene sobre su padre y la cierra con él, sin aparecer en
    la barra de tareas como una segunda aplicación.
    """
    window.setWindowFlag(Qt.Tool, True)
    if hasattr(window, "setModal"):
        window.setModal(False)
    window.show()
    window.raise_()
    window.activateWindow()


class MainWindow(Retranslates, QMainWindow):
    """Ventana con la barra de SoC y las tres vistas de la aplicación."""

    def __init__(self, db_path: Path, dtsi_folder: Path):
        """Crea el servicio, monta la barra de SoC y las pestañas."""
        super().__init__()
        # El nombre, no el descriptivo: Qt le añade detrás el
        # `applicationDisplayName` («Device Tree Studio»), así que la
        # barra de título queda «KernelGrove — Device Tree Studio».
        # Sin traducir, que es un nombre propio.
        self.setWindowTitle("KernelGrove")
        self.resize(*style.MAIN_WINDOW_SIZE)

        self.service = KernelGroveService(db_path)
        # Si se monta lo que todavía no va en una release (ver
        # `gui/features`): generar desde el grafo. Se pregunta **una vez**.
        self._experimental = features.experimental()
        # Secciones que no se montan. Se esconden, no se quitan: el índice
        # de sección es la clave de sus atajos, su panel y su vista.
        self._hidden_sections = (
            set() if self._experimental else {SECTION_CONNECTIONS}
        )
        # Sección activa de la franja de iconos. Se fija antes que nada
        # porque `show_view` la consulta y hay conmutaciones de vista
        # (abrir un fichero de arranque) antes de montar la barra.
        self._current_section = SECTION_FOLDERS
        # Último recuento de diagnósticos que mandó el editor. Se guarda
        # porque la franja se recompone entera al cambiar de idioma y ahí no
        # ha habido ningún análisis nuevo del que sacarlo.
        self._diagnostic_counts = (0, 0, 0)
        self._settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        # Contra qué kernel se está trabajando. Es un ajuste y no un dato del
        # documento a propósito: no está escrito en ningún `.dts` —el fuente
        # no dice para qué kernel se compila— y quien lo sabe es quien monta
        # el sistema, una vez para todo el proyecto.
        self.service.kernel_target = self._settings.value(SETTING_KERNEL) or None
        # La carpeta del panel lateral es la última que eligió el usuario; la
        # que llega por parámetro (el directorio de la aplicación) es solo el
        # punto de partida de la primera sesión.
        self.dtsi_folder = self._remembered_folder(dtsi_folder)
        self.socs: List[SoCSummary] = []
        self.boards: List[SoCSummary] = []
        # Índices sobre `self.socs` para identificar, al visualizar un árbol,
        # a qué SoC de la base de datos corresponde (ver `_soc_name_for`).
        self._socs_by_path: Dict[str, SoCSummary] = {}
        self._socs_by_compatible: Dict[str, SoCSummary] = {}
        # Mismos índices, para la board (ver `_board_name_for`).
        self._boards_by_path: Dict[str, SoCSummary] = {}
        self._boards_by_compatible: Dict[str, SoCSummary] = {}
        # Árbol fusionado del documento activo, para el panel de propiedades
        # del SoC (ver `_open_soc_properties`): lo construye `_on_document_
        # analyzed`, que es lo único que lo necesita además del grafo.
        self._current_merged_root: Optional[DeviceTreeNode] = None
        self._current_soc_compatible: Optional[str] = None
        # Las dos ventanas auxiliares del grafo (`_show_tool_window`). Se
        # guardan porque no son modales: sin una referencia viva, Python las
        # recogería nada más volver de `show()` y desaparecerían solas.
        self._soc_dialog: Optional[SocPropertiesDialog] = None
        # Las licencias abiertas desde «Ayuda», por lo mismo: sin referencia
        # viva Python se las llevaría nada más volver de `show()`.
        self._licenses_window: Optional[LegalDialog] = None
        # Cómo se está mirando el documento: como texto o como grafo. Lo
        # alterna el pie del panel, y es lo que se respeta al abrir un
        # fichero o al elegir un nodo — abrir siempre en el editor obligaba
        # a volver al grafo cada vez.
        self._document_view = TAB_EDITOR
        # Ancho del hueco lateral, compartido por las cuatro secciones que
        # tienen panel: lo que se ajuste en una lo tienen todas (ver
        # `LEFT_DOCK_WIDTH`).
        self._left_dock_width = LEFT_DOCK_WIDTH
        self._inspector_dialog: Optional[QDialog] = None
        self._inspector_panel: Optional[InspectorPanel] = None
        # Documento que originó la sesión de conexión activa (ver
        # `_on_document_analyzed`): el Generador y el Visualizador comparten
        # `self.tree_model`, pero su solapado sobre el grafo solo tiene
        # sentido mientras se sigue mostrando ese mismo documento.
        self._edit_session_document = None
        # Documento mostrado la última vez que se analizó algo — compararlo
        # es cómo `_on_document_analyzed` distingue "se ha cambiado de
        # pestaña" (hay que refrescar el Generador con el perfil de la
        # nueva) de "se sigue editando la misma" (no hay que tocar nada).
        self._active_document = None
        # El asistente de overlays está esperando a que se señale el nodo
        # objetivo en el editor (ver `_start_overlay_pick`).
        self._picking_overlay_target = False
        # Último device tree completo analizado: la base por defecto para
        # comprobar overlays cuando el fichero no declara la suya.
        self._overlay_base = None
        # Árboles de base ya resueltos, por su clave (ver `_resolve_base`).
        self._base_cache = {}

        # Árbol de `PeripheralSlot` compartido entre Generador y
        # Visualizador: "mismo motor, dos interfaces" — conectar un
        # dispositivo en uno se ve en el otro.
        self.tree_model = PeripheralTreeModel(self.service, parent=self)

        self.editor_tab = EditorTab(self.service)
        self.visualizer_tab = VisualizerTab(self.service, self.tree_model)
        # Ver el grafo es estable; tocarlo desde él (paleta, quitar nodos,
        # panel del SoC) todavía no (ver `gui/features`).
        self.visualizer_tab.set_editable(self._experimental)
        self.generator_tab = GeneratorTab(self.service, self.tree_model)
        self.overlay_tab = OverlayTab(self.service)
        # El catálogo es una **ventana flotante**, no una vista central: se
        # busca un SoC mientras se está editando otra cosa, y ocupar el
        # centro obligaba a salir del editor para mirarlo y a volver
        # después. `Qt.Tool` la mantiene sobre la principal y la cierra con
        # ella, como la ficha de una propiedad.
        self.database_tab = DatabaseTab()
        self.database_tab.setWindowFlag(Qt.Tool, True)
        self.database_tab.resize(*style.DATABASE_WINDOW_SIZE)
        self.database_tab.hide()
        self.database_tab.socChosen.connect(self._on_soc_selected)
        self.database_tab.boardChosen.connect(self._on_board_selected)
        # «Visual graph»: abrir ya lo hizo la señal de arriba; esto solo
        # cambia a dónde se mira. Pide la **vista**, no una sección: desde
        # que una sección no arrastra el centro, pedir la del árbol de nodos
        # no llevaba al grafo, que es lo único que ese botón promete.
        self.database_tab.graphRequested.connect(
            lambda: self.show_view(TAB_VISUALIZER)
        )
        self.database_tab.bindingSearchRequested.connect(self._search_bindings)
        self.database_tab.bindingChosen.connect(self._show_schema)

        self._build_top_bar()
        self._build_ui()
        self._connect_signals()
        self._load_socs()
        self._load_boards()
        # Monta los menús y fija todos los textos: es el mismo trabajo que
        # hay que rehacer al cambiar de idioma, así que se hace por el mismo
        # camino en vez de duplicarlo aquí.
        self.retranslate()
        self._warn_about_database()

    def _remembered_folder(self, fallback: Path) -> Path:
        """Última carpeta abierta en el panel lateral, si sigue existiendo."""
        stored = self._settings.value(SETTING_EXPLORER_ROOT)
        if isinstance(stored, str) and stored:
            path = Path(stored)
            if path.is_dir():
                return path
        return fallback

    def _warn_about_database(self) -> None:
        """Avisa si la base abierta no es de esta versión o está incompleta.

        La base se distribuye aparte del software, así que puede ser vieja,
        ajena o estar construida a medias. Sin este aviso, "la capa 5 no
        dice nada" se ve exactamente igual que "no hay nada que decir sobre
        tu device tree", que es la peor confusión posible en una herramienta
        de validación.

        El diálogo es **no modal** a propósito: sale durante el arranque, y
        uno modal deja la aplicación esperando un clic antes de haber
        mostrado nada — lo que además cuelga cualquier arranque sin persona
        delante (CI, `QT_QPA_PLATFORM=offscreen`). El aviso se queda además
        en la barra de estado, que es donde se puede volver a leer.
        """
        warning = self.service.database_warning()
        if warning is None:
            return
        self._set_status(warning)

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(messages.title_database())
        box.setText(warning)
        box.setModal(False)
        box.setAttribute(Qt.WA_DeleteOnClose)
        box.show()

    # ------------------------------------------------------------------
    # Construcción
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        """Monta el panel de carpetas, la barra de SoC y las pestañas."""
        central = QWidget()
        layout = QVBoxLayout(central)
        # Sin márgenes ni espaciado: cada zona (barra superior, solapas de
        # fichero, vista) se delimita con su propia línea de 1 px, no con
        # aire alrededor. El aire dentro de cada una lo pone su relleno.
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.document_bar = self._build_document_bar()
        layout.addWidget(self.document_bar)

        self.tabs = QTabWidget()
        # Sin fila de pestañas: quien elige la vista es la franja de iconos
        # de la izquierda (`ActivityBar`). Dos navegaciones para lo mismo
        # obligaban a mover las dos para llegar a algún sitio. El
        # `QTabWidget` se queda porque es lo que apila las vistas; lo único
        # que se va es su barra, igual que `EditorTab` esconde la suya.
        self.tabs.tabBar().hide()
        # El Visualizador y el Generador son dos interfaces del MISMO motor
        # de conexión (comparten `PeripheralTreeModel`), así que sus nombres
        # lo dicen: antes eran "Node Graph" y "Generador", dos etiquetas sin
        # nada en común -y una de ellas en inglés entre dos en español-.
        # Sin `tr()`: la fila de pestañas está escondida, así que estos
        # nombres no los lee nadie. Quien los enseña es la franja de iconos
        # (con sus tooltips) y el menú Ver, y allí sí van traducidos.
        self.tabs.addTab(self.editor_tab, "Editor")
        self.tabs.addTab(self.visualizer_tab, "Node graph")
        self.tabs.addTab(self.generator_tab, "Connections · list")
        # El catálogo de la base es una herramienta, no una vista del
        # documento abierto: por eso va detrás de las tres y no en una
        # franja permanente encima de todas, que es donde estaban sus dos
        # desplegables.
        # La de overlays no: solo aparece mientras hay un borrador en marcha
        # (`_show_overlay_tab`). El asistente y el listado viven en la
        # sección OVERLAYS del panel izquierdo, y una pestaña permanente
        # para lo que casi siempre está vacío era sitio ocupado por nada.
        self.overlay_tab.setParent(self)
        self.overlay_tab.hide()
        # La ficha de una propiedad flota sobre la ventana en vez de ocupar
        # el centro: se consulta mientras se escribe, y como vista central
        # habría tapado el texto que explica cómo corregir.
        self.property_panel = PropertyPanel(self)
        self.property_panel.hide()
        # Directo, sin `show_view`: la franja de iconos aún no existe (se
        # monta después, en `_build_left_dock`) y ya arranca en su primera
        # sección, que es justamente esta vista.
        self.tabs.setCurrentIndex(TAB_EDITOR)

        layout.addWidget(self.tabs, 1)

        self.setCentralWidget(central)
        # El inspector primero: `_build_left_dock` monta la franja de iconos
        # y su primera sección ya decide si el inspector se ve o no.
        self._build_inspector_dock()
        self._build_left_dock()
        self._build_status_bar()
        # Lo que depende de **qué vista ocupa el centro** cuelga de aquí, no
        # de la sección. Eran la misma cosa cuando cambiar de sección movía
        # el centro; desde que no (`_on_activity_section_changed`), colgarlo
        # de la sección dejaba el inspector escondido después de cualquier
        # cambio de vista que no pasara por la franja de iconos —cerrar el
        # borrador de un overlay, por ejemplo—.
        self.tabs.currentChanged.connect(self._on_central_view_changed)
        self._on_central_view_changed(self.tabs.currentIndex())

    def _on_central_view_changed(self, index: int) -> None:
        """Ajusta lo que depende de la vista central: inspector y pies.

        El inspector enseña el nodo **bajo el cursor del editor**: fuera del
        editor no tiene de dónde sacarlo, y un panel que solo dice «ningún
        nodo» es ancho gastado.
        """
        if index in _DOCUMENT_VIEWS:
            self._document_view = index
        self.inspector_dock.setVisible(index == TAB_EDITOR)
        self._refresh_panel_footers()

    def _refresh_panel_footers(self) -> None:
        """Pone en los pies de los paneles el salto a la *otra* vista.

        Los dos pies enseñan lo mismo, y lo que enseñan lo decide **en qué
        vista se está**, no en qué panel viven: desde el grafo se salta al
        editor y desde el editor al grafo. Cuando lo decidía el panel, abrir
        Carpetas mientras se miraba el grafo ofrecía «ver en el grafo», que
        es donde ya estabas.
        """
        en_el_grafo = self.tabs.currentIndex() == TAB_VISUALIZER
        if en_el_grafo:
            destino = (
                icons.document_icon,
                self.tr("Visualize in DTS editor"),
                self.tr("Bring the active document forward in the editor"),
            )
        else:
            destino = (
                icons.tree_icon,
                self.tr("Visualize in node graph"),
                self.tr("Open the active document in the node graph"),
            )
        self.explorer_panel.footer.set_target(*destino)

    def _jump_to_other_view(self) -> None:
        """El pie de cualquier panel lleva a la vista que no se está mirando."""
        self.show_view(
            TAB_EDITOR
            if self.tabs.currentIndex() == TAB_VISUALIZER
            else TAB_VISUALIZER
        )

    def _make_fixed_dock(self, object_name: str, widget: QWidget) -> QDockWidget:
        """Un `QDockWidget` sin cerrar/flotar/mover, base de los paneles laterales.

        El pedido es que estén "siempre ahí", así que se les quitan las
        características que permitirían quitarlos de en medio por accidente
        — solo queda el redimensionado, que hereda de ser un dock.
        """
        dock = QDockWidget(self)
        dock.setObjectName(object_name)
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        dock.setWidget(widget)
        return dock

    def _build_left_dock(self) -> None:
        """Panel izquierdo: franja de iconos + el panel que toque mostrar.

        Antes "carpetas" y "árbol de nodos" eran dos docks apilados, ambos
        visibles a la vez. Ahora comparten un único hueco: una
        `ActivityBar` a la izquierda del todo elige cuál de los dos ocupa
        ese hueco (`QStackedWidget`), como la barra de actividad de VS
        Code — la información del panel va cambiando, no se apilan.
        """
        self.explorer_panel = FileExplorerPanel(self.dtsi_folder)
        self.explorer_panel.fileActivated.connect(self._open_explorer_file)
        # El pie de un panel es el salto a la *otra vista*, así que pide vista
        # y no sección: desde que la sección ya no arrastra el centro, pedirla
        # dejaría el botón sin hacer lo único que hace. Y a cuál se salta lo
        # decide la vista actual, no el panel (`_refresh_panel_footers`).
        self.explorer_panel.graphRequested.connect(self._jump_to_other_view)

        self.git_panel = GitPanel()
        self.git_panel.diffRequested.connect(self._open_diff)
        self.git_panel.statusMessage.connect(self._set_status)
        # El árbol de carpetas se tiñe con el estado que el panel acaba de
        # leer, en vez de pedir otro `git status` por su cuenta.
        self.git_panel.statusRefreshed.connect(self.explorer_panel.set_git_status)
        self.git_panel.set_root(self.dtsi_folder)
        self._refresh_git_decoration()

        self.overlay_panel = OverlayPanel(self.service)
        self.overlay_panel.createRequested.connect(self._start_overlay_pick)
        self.overlay_panel.cancelRequested.connect(self._cancel_overlay)
        self.overlay_panel.generateRequested.connect(self.overlay_tab.generate)
        self.overlay_panel.lineSelected.connect(self.overlay_tab.select_line)
        self.overlay_panel.previewEdited.connect(self.overlay_tab.set_source)
        self.overlay_panel.overlay_list.checkedChanged.connect(
            self._refresh_overlay_count
        )

        self.build_panel = BuildPanel()
        self.build_panel.buildRequested.connect(self._build_device_tree)
        self.build_panel.decompileRequested.connect(self._decompile_blob)
        self.build_panel.databasePickRequested.connect(self._add_database_tree)
        tools = detect_toolchain()
        self.build_panel.set_toolchain(
            dtc=tools.dtc is not None, cpp=tools.cpp is not None
        )
        self.build_panel.set_folder(self.explorer_panel.current_root())
        # Y a partir de aquí la carpeta se vigila: las dos listas son una
        # lectura del disco, no un modelo vivo, y quien borra un `.dtso` o
        # deja caer un `.dtb` espera verlo sin salir de la sección y volver
        # a entrar. El panel de carpetas ya se entera solo —su
        # `QFileSystemModel` vigila el disco—, así que esto es para las que
        # no.
        self._folder_watcher = QFileSystemWatcher(self)
        self._folder_watcher.directoryChanged.connect(self._on_folder_contents_changed)
        # Con retardo: una compilación escribe varios ficheros seguidos y
        # cada uno dispara el aviso; releer la carpeta y **volver a
        # comprobar cada overlay** una vez por fichero es trabajo tirado.
        self._folder_reread = QTimer(self)
        self._folder_reread.setSingleShot(True)
        self._folder_reread.setInterval(FOLDER_REREAD_MS)
        self._folder_reread.timeout.connect(self._reread_folder_lists)
        self._watch_folder(self.explorer_panel.current_root())
        # La carpeta, ya: el listado la recibía solo desde
        # `_on_document_analyzed`, así que al abrir la aplicación y entrar
        # en Overlays sin haber abierto ningún fichero la lista salía vacía
        # aunque la carpeta estuviera llena de `.dtso`.
        self.overlay_panel.set_library(self.explorer_panel.current_root(), None)

        sections = self._activity_sections()
        self._current_section = SECTION_FOLDERS
        self._left_sections = [section.title for section in sections]
        self.activity_bar = ActivityBar(sections)
        # El catálogo abre una ventana y no ocupa el centro, así que su
        # icono no se queda marcado: es una acción, no una sección.
        self.activity_bar.set_section_action(SECTION_DATABASE)
        for oculta in self._hidden_sections:
            self.activity_bar.set_section_visible(oculta, False)
        self.activity_bar.sectionChanged.connect(self._on_activity_section_changed)

        self._left_stack = QStackedWidget()
        self._left_stack.addWidget(self.explorer_panel)
        self._left_stack.addWidget(self.git_panel)
        self._left_stack.addWidget(self.overlay_panel)
        self._left_stack.addWidget(self.build_panel)
        for index in range(self._left_stack.count()):
            _allow_narrow(self._left_stack.widget(index))

        self._left_header = QLabel(self._left_sections[0])
        self._left_header.setObjectName("explorerHeader")

        panel_column = QWidget()
        self._left_panel_column = panel_column
        column_layout = QVBoxLayout(panel_column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(0)
        column_layout.addWidget(self._left_header)
        column_layout.addWidget(self._left_stack, 1)

        content = QWidget()
        row = QHBoxLayout(content)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.activity_bar)
        row.addWidget(panel_column, 1)

        dock = self._make_fixed_dock("leftDock", content)
        # Sin barra de título. Un `QDockWidget` dibuja la suya aunque no
        # tenga nada que poner en ella —ni cerrar, ni flotar, ni texto—, y
        # eran ~20 px de franja vacía encima del rótulo de la sección. El
        # inspector no la tiene porque le puso la suya (`setTitleBarWidget`);
        # este se queda sin ninguna, que es lo que hace falta.
        dock.setTitleBarWidget(QWidget())
        dock.setMinimumWidth(style.ACTIVITY_BAR_WIDTH + LEFT_PANEL_MIN_WIDTH)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self.left_dock = dock
        # Ancho inicial compacto — sin esto el dock arranca tan ancho como el
        # `sizeHint` del árbol, que para un `QTreeView` es más de lo que hace
        # falta para una barra lateral de navegación.
        self.resizeDocks([dock], [LEFT_DOCK_WIDTH], Qt.Horizontal)

    def _activity_sections(self) -> List[ActivitySection]:
        """Secciones del panel izquierdo, con sus textos ya traducidos."""
        return [
            ActivitySection(
                self.tr("FOLDERS"),
                icons.folder_icon(
                    style.ACTIVITY_ICON_SIZE,
                    style.MUTED_TEXT_COLOR,
                    active_color=style.GRAPH_COLOR_TEXT,
                ),
                self.tr("Folders"),
            ),
            ActivitySection(
                self.tr("CONNECTIONS"),
                icons.list_icon(
                    style.ACTIVITY_ICON_SIZE,
                    style.MUTED_TEXT_COLOR,
                    active_color=style.GRAPH_COLOR_TEXT,
                ),
                self.tr("Connections, as a list"),
            ),
            ActivitySection(
                self.tr("SOURCE CONTROL"),
                icons.branch_icon(
                    style.ACTIVITY_ICON_SIZE,
                    style.MUTED_TEXT_COLOR,
                    active_color=style.GRAPH_COLOR_TEXT,
                ),
                self.tr("Version control of the open folder"),
            ),
            ActivitySection(
                self.tr("OVERLAYS"),
                icons.layers_icon(
                    style.ACTIVITY_ICON_SIZE,
                    style.MUTED_TEXT_COLOR,
                    active_color=style.GRAPH_COLOR_TEXT,
                ),
                self.tr("Build an overlay over the active document"),
            ),
            ActivitySection(
                self.tr("BUILD TOOLS"),
                icons.build_icon(
                    style.ACTIVITY_ICON_SIZE,
                    style.MUTED_TEXT_COLOR,
                    active_color=style.GRAPH_COLOR_TEXT,
                ),
                self.tr("Compile a device tree with its overlays"),
            ),
            ActivitySection(
                self.tr("DATABASE"),
                icons.database_icon(
                    style.ACTIVITY_ICON_SIZE,
                    style.MUTED_TEXT_COLOR,
                    active_color=style.GRAPH_COLOR_TEXT,
                ),
                self.tr("SoC and board catalogue of the database"),
            ),
        ]

    def _on_activity_section_changed(self, index: int) -> None:
        """Cambia el panel lateral, y la vista central solo si es suya.

        **Una sección que no tiene vista propia no te saca de la que estás
        mirando.** Carpetas, versiones y overlays son paneles sobre el
        documento, no ventanas: mirar el grafo y abrir el control de código
        para ver qué has tocado es una sola tarea, y que el centro saltara al
        editor obligaba a volver atrás cada vez. Las que sí tienen vista
        propia -grafo, lista de conexiones y catálogo- siguen cambiándola,
        porque ahí la sección *es* la ventana.

        La excepción son las vistas que se leen a todo lo ancho y no admiten
        panel al lado (catálogo y lista de conexiones): desde ellas sí hay que
        volver al editor, o el panel se abriría junto a una vista que lo tapa.

        Y de paso qué enseña la franja de registro de abajo: entrar en la
        herramienta de overlays la pone en el registro de comprobaciones, que
        es lo que se va a mirar allí, y salir la devuelve a los diagnósticos
        del documento, que es lo que se mira en todo lo demás.
        """
        # El catálogo no es una sección: es una ventana. No mueve el centro,
        # no cambia el panel y no deja su icono marcado — se abre encima de
        # lo que estuvieras haciendo, que es la razón de que sea una ventana.
        if index == SECTION_DATABASE:
            self.open_database()
            return

        # El ancho es del hueco y no de la sección: se anota el que hay justo
        # antes de cambiar, que es el que el usuario haya dejado a mano, para
        # devolvérselo al panel que entra.
        if self._left_panel_column.isVisible():
            self._left_dock_width = self.left_dock.width()

        self._current_section = index
        self._left_stack.setCurrentIndex(self._panel_of_section(index))
        self._left_header.setText(self._left_sections[index])
        self.editor_tab.show_log_page(
            LOG_OVERLAYS
            if index == SECTION_OVERLAY
            else LOG_BUILD
            if index == SECTION_BUILD
            else LOG_DIAGNOSTICS
        )
        # Una sección de panel deja el centro donde está. La excepción es
        # volver de una vista a todo lo ancho: ahí el panel se abriría al
        # lado de algo que lo tapa, así que se recupera la última forma en
        # que se estaba mirando el documento.
        vista = SECTION_VIEWS.get(index)
        if vista is None:
            actual = self.tabs.currentIndex()
            vista = (
                actual if actual not in _FULL_WIDTH_VIEWS else self._document_view
            )
        # La de overlays es la excepción: mientras hay un borrador en marcha
        # su pestaña existe y es lo que hay que enseñar; sin borrador, el
        # editor, que es donde se ven los `.dtso` que la lista abre.
        if index == SECTION_OVERLAY and self.tabs.indexOf(self.overlay_tab) != -1:
            vista = self.tabs.indexOf(self.overlay_tab)
        self.tabs.setCurrentIndex(vista)

        # El catálogo se mira a pantalla completa: no tiene panel lateral
        # propio y dejarle uno vacío al lado sería un hueco por nada. La
        # franja de iconos se queda, que es por donde se sale.
        # Sin panel lateral: el catálogo y la lista de conexiones se leen a
        # todo lo ancho. La de conexiones, además, no puede seguir enseñando
        # el árbol de nodos — ese es el panel de la ventana de nodos, y
        # dejarlo puesto hacía que no desapareciera al cambiar de sección.
        catalogo = index == SECTION_CONNECTIONS
        self._left_panel_column.setVisible(not catalogo)
        # El mismo para las cuatro secciones con panel, y el que el usuario
        # haya dejado a mano (ver `LEFT_DOCK_WIDTH`).
        ancho = style.ACTIVITY_BAR_WIDTH if catalogo else self._left_dock_width
        self.left_dock.setMinimumWidth(
            style.ACTIVITY_BAR_WIDTH + (0 if catalogo else LEFT_PANEL_MIN_WIDTH)
        )
        self.resizeDocks([self.left_dock], [ancho], Qt.Horizontal)

    def open_database(self) -> None:
        """Abre el catálogo en su ventana, o lo trae al frente si ya estaba.

        La lista de bindings se llena la primera vez que se abre y no al
        arrancar: es una consulta a la base, y quien no entre al catálogo no
        tiene por qué pagarla.
        """
        if not self.database_tab.bindings.count():
            # Los filtros se llenan aquí y no al arrancar, por lo mismo que
            # la lista: son dos consultas más a la base, y quien no entre al
            # catálogo no tiene por qué pagarlas.
            self.database_tab.set_binding_filters(
                self.service.binding_vendors(), self.service.binding_subsystems()
            )
            self._search_bindings("")
        _show_tool_window(self.database_tab)

    def open_command_palette(self) -> None:
        """Abre la paleta con lo que hay ahora mismo: ficheros, vistas, catálogo.

        Se construye en cada apertura y no una vez: los ficheros abiertos y
        el catálogo cambian, y una paleta que enseña lo de hace media hora
        es peor que no tenerla.
        """
        CommandPalette(self._palette_entries(), self).exec()

    def _palette_entries(self) -> List[PaletteEntry]:
        """Todo lo que la paleta puede llevarte a hacer, ya resuelto.

        En este orden a propósito: primero las vistas (siempre son pocas y
        siempre valen), después los ficheros abiertos, y al final el
        catálogo, que son miles y solo aparece cuando se escribe algo que
        lo estreche.
        """
        entries: List[PaletteEntry] = []

        vista = self.tr("View")
        for section, name in (
            (SECTION_FOLDERS, self.tr("Folders")),
            (SECTION_CONNECTIONS, self.tr("Connections · list")),
            (SECTION_VERSIONS, self.tr("Source control")),
            (SECTION_OVERLAY, self.tr("Overlays")),
            (SECTION_BUILD, self.tr("Build tools")),
            (SECTION_DATABASE, self.tr("Database")),
        ):
            if section in self._hidden_sections:
                continue
            entries.append(
                PaletteEntry(
                    name, vista, lambda s=section: self.activity_bar.show_section(s)
                )
            )

        accion = self.tr("Action")
        entries.append(
            PaletteEntry(
                self.tr("Analyze the document"), accion, self.editor_tab.analyze
            )
        )
        entries.append(
            PaletteEntry(self.tr("Open folder…"), accion, self.open_folder)
        )

        fichero = self.tr("Open file")
        for index, (title, detail, _dirty) in enumerate(
            self.editor_tab.document_labels()
        ):
            entries.append(
                PaletteEntry(
                    title,
                    f"{fichero} · {detail}" if detail else fichero,
                    lambda i=index: self.editor_tab.activate_document(i),
                )
            )

        soc, board = self.tr("SoC"), self.tr("Board")
        for index, item in enumerate(self.socs):
            entries.append(
                PaletteEntry(item.label, soc, lambda i=index: self._on_soc_selected(i))
            )
        for index, item in enumerate(self.boards):
            entries.append(
                PaletteEntry(
                    item.label, board, lambda i=index: self._on_board_selected(i)
                )
            )
        return entries

    def _search_bindings(
        self, text: str, vendor: str = "", subsystems: Optional[List[str]] = None
    ) -> None:
        """Busca compatibles en la base, con sus filtros, y se los da al catálogo.

        La búsqueda va contra SQL con tope, no sobre una lista cargada en
        memoria: son 25 458 compatibles declarados y traerlos todos para
        esconder filas costaría el catálogo entero por cada letra. Los dos
        filtros bajan con ella y no se aplican a lo que vuelve, que está
        recortado a las primeras 300.
        """
        self.database_tab.set_bindings(
            self.service.search_bindings(text, vendor=vendor, subsystems=subsystems),
            self.service.binding_count(text, vendor, subsystems),
        )

    def _show_schema(self, compatible: str) -> None:
        """Abre la ficha legible del binding de un compatible.

        Ventana `Qt.Tool` como el resto de fichas: se consulta un binding
        *mientras* se edita otra cosa, y llevarse el centro para enseñarlo
        obligaba a volver después.
        """
        self._schema_dialog = show_schema(self.service, compatible, self)

    def _refresh_overlay_count(self) -> None:
        """Dice a BUILD TOOLS cuántos overlays hay encendidos en OVERLAYS.

        El número y no la lista: marcarlos vive en una sección y compilarlos
        en otra, y repetir ahí las mismas casillas sería una segunda copia
        del mismo estado que habría que mantener a la par.
        """
        self.build_panel.set_overlay_count(
            len(self.overlay_panel.overlay_list.checked_paths())
        )

    def _add_database_tree(self) -> None:
        """Trae un device tree del catálogo a la lista de compilables.

        No se copia nada todavía: se apunta su clave, y sacarlo de la base
        al disco ocurre al construir, en un directorio temporal que se borra
        después (ver `_build_device_tree`). Un árbol del catálogo no es un
        fichero del proyecto y dejarlo escrito en la carpeta del usuario
        sería decidir por él dónde va.
        """
        chosen = BaseChoiceDialog(
            "",
            self._base_candidates(),
            self,
            title=self.tr("Add a device tree"),
            caption=self.tr("Which device tree do you want to be able to build?"),
        ).choose()
        if chosen:
            self.build_panel.add_database_entry(chosen, Path(chosen).name)

    def _build_device_tree(self) -> None:
        """Comprueba y compila el árbol elegido junto a los overlays encendidos.

        Todo el ciclo en una pulsación, y en este orden: los overlays se
        comprueban **contra el `.dts` que se va a compilar** —que es lo que
        hace interpretable el veredicto de la capa 6— y solo si pasan se
        llama a `cpp` y `dtc`. Los binarios se dejan junto a su fuente, que
        es lo que hace `dtc` por defecto y lo que espera quien luego los
        copia a la placa.

        Si lo elegido es del catálogo, el fuente y sus inclusiones se
        escriben antes en un temporal (`materialize_source`) y el `.dtb`
        sale en la carpeta abierta: la base de datos es de solo lectura y
        el binario tiene que quedar en algún sitio del usuario.

        El registro se escribe **según van llegando los pasos**, no al
        final: es la razón del `processEvents`, porque compilar un árbol
        entero tarda lo suyo y un registro que aparece de golpe al terminar
        no cuenta lo que está pasando.

        ponytail: síncrono con la ventana ocupada; si compilar llega a
        tardar de verdad, esto es un `QThread` como `SchemaChecksWorker`.
        """
        key = self.build_panel.selected_key()
        if key is None:
            self._set_status(self.tr("Pick the device tree to build."))
            return
        overlays = [Path(p) for p in self.overlay_panel.overlay_list.checked_paths()]
        nombre = self.build_panel.selected_name()

        self.editor_tab.show_log_page(LOG_BUILD)
        self.editor_tab.append_build_log(
            "\n".join(
                [
                    RULE,
                    "{time} · {title}".format(
                        time=datetime.now().strftime("%H:%M:%S"),
                        title=self.tr("building {tree} with {count} overlays").format(
                            tree=nombre, count=len(overlays)
                        ),
                    ),
                ]
            )
        )

        base = self._resolve_base(key)
        if base is None:
            self.editor_tab.append_build_log(
                f"  {GLYPH_WARN} "
                + self.tr("{tree} could not be read: nothing was checked").format(
                    tree=nombre
                )
            )

        self._set_busy(True)
        try:
            if self.build_panel.selected_is_from_database():
                outcome = self._build_from_database(key, overlays)
            else:
                outcome = self.service.build_device_tree(
                    Path(key), overlays, base, self._log_build_step
                )
        finally:
            self._set_busy(False)
        if outcome is None:
            return

        resumen = (
            self.tr("{count} files built").format(count=len(outcome.outputs))
            if outcome.ok
            else self.tr("the build failed")
        )
        self.editor_tab.append_build_log(
            f"{GLYPH_OK if outcome.ok else GLYPH_FAIL} {resumen}"
        )
        # Construir deja binarios nuevos junto a su fuente, y la lista de
        # COMPILED es una lectura del disco: sin esto no aparecen hasta que
        # se cambia de carpeta.
        self.build_panel.set_folder(self.explorer_panel.current_root())
        self._set_status(resumen)

    def _build_from_database(self, key: str, overlays):
        """Saca del catálogo el árbol y sus inclusiones, y lo compila ahí.

        El temporal se borra al salir: lo que se conserva es el `.dtb`, que
        se copia a la carpeta abierta —la que el usuario llama su proyecto—
        porque dentro del temporal no le serviría de nada.
        """
        with tempfile.TemporaryDirectory(prefix="kernelgrove-catalog-") as tmp:
            carpeta = Path(tmp)
            fuente = self.service.materialize_source(key, carpeta)
            if fuente is None:
                self.editor_tab.append_build_log(
                    f"  {GLYPH_FAIL} "
                    + self.tr("{tree} is not in the database").format(
                        tree=Path(key).name
                    )
                )
                self._set_status(self.tr("the build failed"))
                return None
            base = self._resolve_base(key)
            outcome = self.service.build_device_tree(
                fuente, overlays, base, self._log_build_step
            )
            destino = self.explorer_panel.current_root() / f"{fuente.stem}.dtb"
            binario = fuente.with_suffix(".dtb")
            if outcome.ok and binario.is_file():
                destino.write_bytes(binario.read_bytes())
                self.editor_tab.append_build_log(
                    f"  {GLYPH_INFO} "
                    + self.tr("{name} written to {folder}").format(
                        name=destino.name, folder=str(destino.parent)
                    )
                )
            return outcome

    def _log_build_step(self, step) -> None:
        """Escribe un paso de la compilación en el registro, según ocurre.

        La interfaz es la que redacta —es la que está traducida— y la que
        elige el glifo; la API solo dice qué pasó con qué fichero (ver
        `KernelGroveService.build_device_tree`).
        """
        glifo = GLYPH_OK if step.ok else GLYPH_FAIL
        if step.kind == "check":
            detalle = (
                self.tr("{errors} errors · {warnings} warnings").format(
                    errors=step.errors, warnings=step.warnings
                )
                if step.errors or step.warnings
                else self.tr("passed")
            )
            lineas = [f"  {glifo} {step.path.name}: {detalle}"]
            for diagnostic in step.diagnostics[:8]:
                lineas.append(f"      {diagnostic.line}: {diagnostic.message}")
        else:
            # **Tal cual**: la orden y lo que contestaron `cpp` y `dtc`, sin
            # sangrar, sin glifo y sin tirar las líneas en blanco. Lo que se
            # viene a leer aquí es lo mismo que se habría visto lanzándolo en
            # un terminal, y adornarlo obliga a traducir mentalmente entre lo
            # que pone en el registro y lo que sale en la consola. El
            # veredicto ya lo dice la línea de resumen del final.
            destino = step.output.name if step.output else ""
            lineas = [
                f"{glifo} {step.path.name}"
                + (f" → {destino}" if destino else "")
            ]
            lineas.extend(step.messages)
        self.editor_tab.append_build_log("\n".join(lineas))
        QCoreApplication.processEvents()

    def _decompile_blob(self, path: str = "") -> None:
        """Abre un `.dtb`/`.dtbo` ya compilado como fuente legible.

        `path` es el binario elegido en la lista de COMPILED; vacío significa
        que no había ninguno elegido y hay que preguntar, porque lo compilado
        puede estar fuera de la carpeta abierta y ahí esa lista no llega.

        El resultado se abre en el editor y no se escribe a disco: lo que
        se hace con un árbol descompilado es leerlo, y guardarlo sin que
        nadie lo haya pedido deja ficheros por el proyecto.
        """
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self,
                self.tr("Choose the compiled device tree"),
                str(self.explorer_panel.current_root()),
                self.tr("Compiled device trees (*.dtb *.dtbo);;All files (*)"),
            )
        if not path:
            return
        result = decompile_blob(Path(path))
        if result.unavailable:
            QMessageBox.information(
                self, messages.title_compile(), result.unavailable
            )
            return
        if not result.ok:
            self.editor_tab.show_log_page(LOG_OVERLAYS)
            self.editor_tab.append_overlay_log(
                "\n".join(
                    [
                        RULE,
                        "{time} · {name}".format(
                            time=datetime.now().strftime("%H:%M:%S"),
                            name=Path(path).name,
                        ),
                        *(f"  {GLYPH_FAIL} {line}" for line in result.messages),
                    ]
                )
            )
            self._set_status(self.tr("{name} could not be decompiled").format(
                name=Path(path).name
            ))
            return
        self.editor_tab.open_source(
            title=f"{Path(path).stem}.dts", text=result.messages[0]
        )
        self.show_view(TAB_EDITOR)
        self._set_status(
            self.tr("{name} decompiled").format(name=Path(path).name)
        )

    def show_view(self, tab: int) -> None:
        """Enseña una vista central y deja la franja de iconos de acuerdo.

        Con la barra de actividad como navegación, poner la pestaña a mano
        dejaría el icono marcado apuntando a otra cosa. Si la sección activa
        ya lleva a esa vista no se toca —Versiones y Overlays llevan las dos
        al editor, y abrir un diff desde el panel de versiones no puede
        echarte de Versiones—; si no, se cambia a la primera que lleve.

        **Y luego se pone la vista, siempre.** Cambiar de sección ya no
        arrastra el centro consigo (ver `_on_activity_section_changed`), así
        que dejarlo en manos de la sección haría que este método no cumpliera
        lo único que promete: es el camino explícito -«enséñame esta vista»-
        y por eso lo usan los pies de los paneles y todo lo que abre algo.
        """
        if SECTION_VIEWS.get(self._current_section) != tab:
            for section, destino in SECTION_VIEWS.items():
                if destino == tab:
                    self.activity_bar.show_section(section)
                    break
        self.tabs.setCurrentIndex(tab)

    def _panel_of_section(self, index: int) -> int:
        """Qué página del `QStackedWidget` lateral le toca a cada sección.

        No es la identidad porque hay secciones que comparten panel (grafo y
        lista son dos interfaces del mismo motor de conexión, así que las dos
        enseñan la estructura del documento) y una que no tiene ninguno.
        """
        return {
            SECTION_FOLDERS: PANEL_FOLDERS,
            SECTION_CONNECTIONS: PANEL_FOLDERS,
            SECTION_VERSIONS: PANEL_VERSIONS,
            SECTION_OVERLAY: PANEL_OVERLAY,
            SECTION_BUILD: PANEL_BUILD,
            SECTION_DATABASE: PANEL_FOLDERS,
        }[index]

    def _build_inspector_dock(self) -> None:
        """Ficha del nodo bajo el cursor, a la derecha de las pestañas.

        Con flecha propia de plegado en su cabecera (`_toggle_inspector`):
        a diferencia del panel izquierdo (que siempre muestra algo, solo
        cambia qué), el Inspector es más prescindible mientras no se está
        mirando un nodo concreto, así que se puede recoger sin cerrarlo del
        todo -seguiría sin tener por dónde volver a abrirse si se cerrara-.
        """
        self.inspector_panel = InspectorPanel(self.service)
        self.inspector_panel.propertyActivated.connect(self._show_property_panel)
        self._inspector_width = 360

        (
            header,
            self._inspector_header_label,
            self._inspector_collapse_button,
        ) = self._build_collapsible_header(self.tr("INSPECTOR"), self._toggle_inspector)

        dock = self._make_fixed_dock("inspectorDock", self.inspector_panel)
        dock.setTitleBarWidget(header)
        dock.setMinimumWidth(style.DOCK_COLLAPSED_WIDTH)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.inspector_dock = dock
        self.resizeDocks([dock], [self._inspector_width], Qt.Horizontal)

    def _build_collapsible_header(
        self, title: str, on_toggle: Callable[[], None]
    ) -> Tuple[QWidget, QLabel, QToolButton]:
        """Cabecera "título + flecha" para un dock que se puede plegar.

        La flecha vive en la cabecera y no en el contenido a propósito: el
        contenido es justo lo que desaparece al plegar, así que si el botón
        estuviera dentro no habría forma de volver a pulsarlo. Se devuelve
        también la etiqueta del título porque `_toggle_inspector` la oculta
        al plegar — con el título de vuelta, el ancho mínimo de la cabecera
        no dejaría encoger el dock más allá de lo que ocupa ese texto.
        """
        header = QWidget()
        header.setObjectName("dockHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(10, 6, 4, 6)
        row.setSpacing(4)

        label = QLabel(title)
        label.setObjectName("explorerHeaderLabel")
        row.addWidget(label)
        row.addStretch(1)

        button = QToolButton()
        button.setObjectName("dockCollapseButton")
        button.setText(COLLAPSE_ARROW_RIGHT)
        button.setToolTip(self.tr("Collapse {title}").format(title=title.lower()))
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(on_toggle)
        row.addWidget(button)

        return header, label, button

    def _toggle_inspector(self) -> None:
        """Pliega el Inspector a una franja mínima, o lo devuelve a su ancho."""
        collapsed = self.inspector_panel.isHidden()
        if collapsed:
            self.inspector_panel.show()
            self._inspector_header_label.show()
            self._inspector_collapse_button.setText(COLLAPSE_ARROW_RIGHT)
            self._inspector_collapse_button.setToolTip(self.tr("Collapse inspector"))
            # Se devuelve el margen de maniobra antes de repartir: mientras
            # estuvo plegado el ancho estaba fijo.
            self.inspector_dock.setMinimumWidth(style.DOCK_COLLAPSED_WIDTH)
            self.inspector_dock.setMaximumWidth(style.WIDGET_SIZE_MAX)
            self.resizeDocks(
                [self.inspector_dock], [self._inspector_width], Qt.Horizontal
            )
        else:
            self._inspector_width = self.inspector_dock.width() or self._inspector_width
            self.inspector_panel.hide()
            self._inspector_header_label.hide()
            self._inspector_collapse_button.setText(COLLAPSE_ARROW_LEFT)
            self._inspector_collapse_button.setToolTip(self.tr("Expand inspector"))
            # `resizeDocks` es solo una sugerencia: un `QDockWidget` no baja
            # de su propio mínimo, que aquí eran 120 px —y eso dejaba una
            # franja vacía de la anchura de un panel a la derecha de la
            # ventana—. Fijar el ancho es lo único que la encoge de verdad.
            self.inspector_dock.setFixedWidth(style.DOCK_COLLAPSED_WIDTH)

    def _build_document_bar(self) -> QTabBar:
        """Barra con los ficheros abiertos, común a las tres vistas.

        El editor guarda los documentos; aquí solo se dibujan y se le pide que
        active o cierre el que toque. Se oculta mientras no haya ninguno para
        no dejar una franja vacía.
        """
        bar = QTabBar()
        bar.setObjectName("documentBar")
        bar.setDocumentMode(True)
        bar.setDrawBase(False)
        bar.setExpanding(False)
        # El cierre no usa `setTabsClosable`: su icono nativo es un bitmap de
        # baja resolución en Fusion. En su lugar, cada pestaña recibe un
        # `TabCloseButton` propio (ver `_sync_document_bar`), dibujado a mano.
        bar.setUsesScrollButtons(True)
        bar.setToolTip(
            self.tr(
                "Open files: the selected one is the file being edited and "
                "the one drawn in the visualizer."
            )
        )
        bar.currentChanged.connect(self.editor_tab.activate_document)
        bar.hide()
        return bar

    def _make_close_button(self) -> TabCloseButton:
        """Botón «×» de una pestaña de la barra de ficheros abiertos.

        Resuelve el índice en el momento del clic (`tabAt`) en vez de
        capturarlo al crear el botón: las pestañas se reordenan por índice
        cuando se cierra alguna anterior, y un índice capturado quedaría
        apuntando a la pestaña equivocada.
        """
        button = TabCloseButton()
        button.clicked.connect(
            lambda: self.editor_tab.close_document(
                self.document_bar.tabAt(button.pos())
            )
        )
        return button

    def refresh_icons(self) -> None:
        """Redibuja la lupa de la franja de arriba (ver `_repaint_theme`)."""
        self.palette_button.setIcon(
            icons.search_icon(style.ACTION_ICON_SIZE, style.MUTED_TEXT_COLOR)
        )

    def _build_top_bar(self) -> None:
        """Franja de arriba: los menús a la izquierda y el buscador centrado.

        No es la `QMenuBar` de la ventana con algo en una esquina —Qt solo
        deja poner un widget en las esquinas, y ahí el buscador queda
        pegado al borde—: es un widget propio en el hueco de la barra de
        menús (`setMenuWidget`), con la barra dentro. Así el buscador se
        centra en el hueco que dejan los menús, que es donde lo pone el
        diseño de referencia.

        Se monta **una vez**: `_build_menus` se vuelve a llamar al cambiar
        de idioma y vacía la barra, pero esta franja y su botón sobreviven
        —los textos los rehace `retranslate`—.
        """
        # Pública y no `self.menuBar()`: con `setMenuWidget` la barra va
        # dentro de la franja, y `menuBar()` de Qt crearía otra vacía por
        # su cuenta a la primera que alguien la llamara.
        self.menu_bar = QMenuBar()

        self.palette_button = QPushButton()
        self.palette_button.setObjectName("commandPaletteButton")
        # Sin foco: es una caja de búsqueda de mentira que abre la paleta, y
        # al arrancar se quedaba con el foco dibujando su aro de acento como
        # si se fuera a escribir ahí.
        self.palette_button.setFocusPolicy(Qt.NoFocus)
        self.palette_button.setFixedWidth(style.COMMAND_PALETTE_BUTTON_WIDTH)
        self.palette_button.setIcon(
            icons.search_icon(style.ACTION_ICON_SIZE, style.MUTED_TEXT_COLOR)
        )
        self.palette_button.setIconSize(
            QSize(style.ACTION_ICON_SIZE, style.ACTION_ICON_SIZE)
        )
        self.palette_button.clicked.connect(self.open_command_palette)

        # Centrado en la **ventana**, no en el hueco que dejan los menús: con
        # solo dos espaciadores el buscador se iba a la derecha tanto como
        # midieran «Archivo Editar Ver Ayuda». El contrapeso de la derecha es
        # un hueco vacío del ancho exacto de la barra de menús, así que los
        # dos espaciadores quedan iguales y el botón cae en el centro. Se
        # reajusta al cambiar de idioma, que es cuando los menús cambian de
        # ancho (ver `_sync_top_bar`).
        self._menu_counterweight = QWidget()
        # Transparente: es un hueco, no una zona. Con el fondo que le da la
        # regla general de `QWidget` tapaba la línea inferior de la franja
        # -el layout no tiene márgenes, así que un hijo llega hasta el borde
        # y pinta encima- y la raya se cortaba de golpe a la altura de los
        # menús, dejando la esquina superior derecha sin separar.
        self._menu_counterweight.setObjectName("topBarSpacer")
        top = QWidget()
        top.setObjectName("topBar")
        row = QHBoxLayout(top)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.menu_bar)
        row.addStretch(1)
        row.addWidget(self.palette_button)
        row.addStretch(1)
        row.addWidget(self._menu_counterweight)
        self.setMenuWidget(top)

    def _sync_top_bar(self) -> None:
        """Iguala el contrapeso al ancho real de los menús."""
        self._menu_counterweight.setFixedWidth(self.menu_bar.sizeHint().width())

    def _build_status_bar(self) -> None:
        """Monta la barra de estado: analizar, progreso y versión.

        Los widgets "permanentes" de una `QStatusBar` se apilan de izquierda a
        derecha en su franja derecha según el orden de inserción, así que la
        versión se añade la última para que quede en la esquina inferior
        derecha, después del indicador de progreso.

        «Analizar» está aquí y no sobre el editor porque el análisis se
        dispara solo al escribir: el botón es el rearranque manual, no la
        acción principal, y una franja entera encima del texto para él —y
        para un «Guardar» que ya está en el menú con su Ctrl+S— era sitio
        gastado en lo que menos se usa.
        """
        self.analyze_button = QPushButton()
        self.analyze_button.setObjectName("statusAction")
        self.analyze_button.clicked.connect(self.editor_tab.analyze)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumWidth(160)
        self.progress.hide()

        # Indicadores fijos de la izquierda, los del IDE de referencia: la
        # rama y el recuento de errores y avisos. Son los datos que uno mira
        # sin dejar de escribir, y por eso están siempre y no dentro del
        # mensaje, que va cambiando. **Cuántas entradas trae la base no está
        # entre ellos**: es un dato del arranque, no de lo que se está
        # editando, no cambia en toda la sesión y no se actúa sobre él — vive
        # en «Ayuda → Acerca de», que es donde se va a mirar qué base hay.
        # Cada indicador va con el icono que el proyecto de referencia le
        # pone: la bifurcación de la rama, el círculo y el triángulo de los
        # problemas. Se dibujan a mano (`widgets/icons.py`) en el color de la
        # franja, que con la piel obsidiana es texto oscuro sobre acento y no
        # el gris de siempre.
        self.branch_label = _status_item(icons.split_icon)
        self.problems_error_label = _status_item(icons.error_icon)
        self.problems_label = _status_item(icons.warning_icon)
        for widget in (
            self.branch_label,
            self.problems_error_label,
            self.problems_label,
        ):
            self.statusBar().addWidget(widget)

        self.status_label = QLabel(self.tr("Ready"))
        self.statusBar().addWidget(self.status_label, 1)

        # Y los de la derecha: dónde está el cursor y en qué está escrito el
        # fichero. La codificación es fija porque el editor solo lee y
        # escribe UTF-8; decirlo es más honesto que ofrecer un selector que
        # no cambia nada. El **tipo** sí sale del documento abierto: decía
        # «DTS» con un `.json` delante, que es lo mismo que no decir nada.
        self.cursor_label = _status_item(None)
        self.language_label = _status_item(None)
        # El fin de línea, y se puede cambiar. Es el mismo tipo de ajuste
        # que el kernel objetivo —del documento, visible sin buscarlo y
        # cambiable sin salir de lo que se hace— y hace falta de verdad:
        # un proyecto compartido entre Windows y Linux acaba con ficheros
        # de los dos, y hasta ahora se guardaba siempre con el del sistema.
        self.newline_button = QPushButton()
        self.newline_button.setObjectName("statusAction")
        self.newline_button.clicked.connect(self._toggle_newline)
        # Contra qué kernel se comprueba. Va aquí, en la franja, por lo mismo
        # que el IDE de referencia pone ahí el lenguaje y la codificación:
        # es un ajuste del documento que hay que poder ver sin buscarlo y
        # cambiar sin salir de lo que se está haciendo. Y era la pregunta que
        # no tenía sitio: el fuente no dice para qué kernel se compila.
        self.kernel_button = QPushButton()
        self.kernel_button.setObjectName("statusAction")
        self.kernel_button.clicked.connect(self._choose_kernel_target)
        self.statusBar().addPermanentWidget(self.cursor_label)
        self.statusBar().addPermanentWidget(self.kernel_button)
        self.statusBar().addPermanentWidget(self.newline_button)
        self.statusBar().addPermanentWidget(self.language_label)
        self.statusBar().addPermanentWidget(self.analyze_button)
        self.statusBar().addPermanentWidget(self.progress)

        self._version_label = QLabel(f"v{__version__}")
        # Sin hoja propia: el color lo pone el QSS (`#statusVersion`), que es
        # lo único que sabe de qué color es la franja en cada piel — con la
        # obsidiana va entera de acento y un gris apagado ahí no se lee.
        self._version_label.setObjectName("statusVersion")
        self.analyze_button.setText(self.tr("Analyze"))
        self.analyze_button.setToolTip(
            self.tr("Re-run the analysis on the active document")
        )
        self._version_label.setToolTip(self.tr("KernelGrove version"))
        self.statusBar().addPermanentWidget(self._version_label)

    def _connect_signals(self) -> None:
        """Enlaza las pestañas entre sí y con la barra de estado."""
        self.editor_tab.status_changed.connect(self._set_status)
        self.editor_tab.busy_changed.connect(self._set_busy)
        self.editor_tab.document_analyzed.connect(self._on_document_analyzed)
        self.editor_tab.cursor_moved.connect(self._on_cursor_moved)
        self.editor_tab.diagnostics_changed.connect(self._on_diagnostics_changed)
        self.editor_tab.documents_changed.connect(self._sync_document_bar)
        # Guardar es cuando el disco cambia, y el árbol de carpetas pinta el
        # disco: es aquí y no en cada análisis (ver `_mark_git_changes`).
        self.editor_tab.document_saved.connect(self._refresh_git_decoration)
        self.property_panel.closeRequested.connect(self.property_panel.hide)
        self.property_panel.findUsagesRequested.connect(self._find_property_usages)
        self.property_panel.usageActivated.connect(self._go_to_line)
        self.editor_tab.database_requested.connect(
            lambda: self.activity_bar.show_section(SECTION_DATABASE)
        )
        self.editor_tab.include_requested.connect(self._open_include)
        self.editor_tab.definition_requested.connect(self._go_to_definition)
        self.editor_tab.node_at_cursor_changed.connect(self._on_node_at_cursor_changed)

        self.generator_tab.status_changed.connect(self._set_status)
        self.generator_tab.busy_changed.connect(self._set_busy)

        self.overlay_tab.status_changed.connect(self._set_status)
        self.overlay_tab.overlayGenerated.connect(self._save_generated_overlay)
        self.overlay_tab.draftChanged.connect(self._on_overlay_draft_changed)
        self.overlay_panel.overlay_list.overlayActivated.connect(
            self._open_explorer_file
        )
        self.overlay_panel.overlay_list.validateRequested.connect(
            self._validate_overlay
        )
        self.overlay_panel.overlay_list.set_base_resolver(self._resolve_base)
        self.overlay_panel.overlay_list.reportReady.connect(
            self.editor_tab.append_overlay_log
        )
        self.explorer_panel.fileRenamed.connect(self._on_file_renamed)
        self.editor_tab.node_clicked.connect(self._on_editor_node_clicked)

        self.visualizer_tab.includeActivated.connect(self._open_include)
        self.visualizer_tab.socActivated.connect(self._open_soc_properties)
        self.visualizer_tab.nodeInspectRequested.connect(self._open_node_inspector)
        self.visualizer_tab.nodeSourceRequested.connect(self._open_node_source)
        self.visualizer_tab.nodesDeleteRequested.connect(self._delete_source_nodes)

    def _disconnect_selected(self) -> None:
        """Quita lo seleccionado en la vista que está delante.

        La acción del menú siempre iba al árbol del Generador, así que
        estando en el grafo -donde también se selecciona y donde se conecta
        arrastrando- no hacía nada: la vista que se está mirando no era la
        que se consultaba. En el grafo hace lo mismo que Supr allí, para que
        la tecla y el menú no signifiquen dos cosas distintas.
        """
        if self.tabs.currentIndex() == TAB_VISUALIZER:
            quitados = self.visualizer_tab.graph.remove_selected()
            if not quitados:
                self.statusBar().showMessage(
                    self.tr(
                        "Nothing to remove there: a node that comes from an "
                        "#include is written in another file, and the SoC's "
                        "own blocks are part of it."
                    )
                )
            return
        self.generator_tab.disconnect_selected()

    def _add_action(
        self, menu, title: str, shortcut, slot: Callable[[], None]
    ) -> QAction:
        """Crea una acción de menú con su atajo y la engancha a `slot`.

        La acción cuelga del **menú**, no de la ventana: al cambiar de idioma
        los menús se rehacen enteros, y unas acciones que sobrevivieran a su
        menú dejarían dos `QAction` con el mismo atajo colgando de la
        ventana — Qt lo resuelve como "atajo ambiguo" y deja de disparar
        ninguna de las dos.
        """
        action = QAction(title, menu)
        if shortcut is not None:
            action.setShortcut(shortcut)
        # `triggered` entrega un `checked` que ninguna de estas acciones
        # quiere; se descarta aquí y no en cada lambda del menú, que es donde
        # antes se colaba como primer argumento posicional.
        action.triggered.connect(lambda _checked=False, run=slot: run())
        menu.addAction(action)
        return action

    def _build_menus(self) -> None:
        """Define menús y atajos de teclado, desde cero.

        Se vuelve a llamar al cambiar de idioma, así que primero se vacía la
        barra y se destruyen los menús anteriores (con sus acciones dentro,
        ver `_add_action`).

        Todo lo que la aplicación sabe hacer tiene que estar aquí, con su
        atajo: una función que solo existe si ya sabes que existe (la
        búsqueda con Ctrl+F, por ejemplo) es una función que la mayoría no
        va a encontrar.
        """
        bar = self.menu_bar
        for action in bar.actions():
            menu = action.menu()
            if menu is not None:
                menu.deleteLater()
        bar.clear()

        file_menu = bar.addMenu(self.tr("&File"))
        # Una sola forma de abrir del disco, y es la carpeta. «Abrir del
        # PC…» abría un fichero suelto y cerraba lo demás; abrir su carpeta
        # hace lo mismo y además deja el resto del proyecto a mano en el
        # panel —los includes hermanos, los overlays, el `.dts` de al lado—,
        # que es de lo que va editar un device tree. Dos diálogos para lo
        # mismo obligaban a elegir cuál antes de saber qué se iba a abrir.
        # Se queda con `Ctrl+O`, que es el atajo de «abrir» en todas partes.
        self._add_action(
            file_menu, self.tr("&Open folder…"), QKeySequence.Open, self.open_folder
        )

        file_menu.addSeparator()
        self._add_action(
            file_menu, self.tr("&Save"), QKeySequence.Save, self.editor_tab.save_file
        )
        self._add_action(
            file_menu,
            self.tr("Save &as…"),
            "Ctrl+Shift+S",
            self.editor_tab.save_file_as,
        )
        self._add_action(
            file_menu, self.tr("&Close file"), "Ctrl+W", self.close_current_document
        )

        file_menu.addSeparator()
        self._add_action(file_menu, self.tr("&Quit"), QKeySequence.Quit, self.close)

        edit_menu = bar.addMenu(self.tr("&Edit"))
        self._add_action(
            edit_menu, self.tr("&Find…"), QKeySequence.Find, self.find_in_document
        )
        self._add_action(
            edit_menu,
            self.tr("&Analyze device tree"),
            "Ctrl+R",
            self.editor_tab.analyze,
        )

        # Desconectar es de las dos vistas que conectan, y sin las funciones
        # experimentales no hay ninguna: una entrada de menú que no puede
        # hacer nada es peor que no tenerla.
        if self._experimental:
            edit_menu.addSeparator()
            desconectar = self._add_action(
                edit_menu,
                self.tr("&Disconnect device"),
                QKeySequence.Delete,
                self._disconnect_selected,
            )
            # Supr solo desconecta **dentro del generador**: en el panel de
            # carpetas esa misma tecla borra lo seleccionado, y dos atajos
            # iguales a nivel de ventana se anulan entre sí (Qt los da por
            # ambiguos y no dispara ninguno). Desde el menú sigue funcionando
            # esté donde esté el foco, que es para lo que está el menú.
            desconectar.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            self.generator_tab.addAction(desconectar)

        # El menú nombra las **secciones**, que es lo que se elige de verdad:
        # cada una trae su panel y su vista. Los atajos siguen su orden en la
        # franja de iconos, así que Ctrl+N y el enésimo icono son lo mismo.
        view_menu = bar.addMenu(self.tr("&View"))
        self._add_action(
            view_menu,
            self.tr("Command &palette…"),
            "Ctrl+P",
            self.open_command_palette,
        )
        view_menu.addSeparator()
        for index, name in (
            (SECTION_FOLDERS, self.tr("&Folders")),
            (SECTION_CONNECTIONS, self.tr("Connections · &list")),
            (SECTION_VERSIONS, self.tr("&Source control")),
            (SECTION_OVERLAY, self.tr("&Overlays")),
            (SECTION_DATABASE, self.tr("&Database")),
        ):
            if index in self._hidden_sections:
                continue
            self._add_action(
                view_menu,
                name,
                f"Ctrl+{index + 1}",
                lambda target=index: self.activity_bar.show_section(target),
            )

        view_menu.addSeparator()
        # La franja de abajo se cierra con su «✕» y se vuelve a abrir aquí:
        # antes se plegaba a su cabecera con una flecha que no movía el
        # reparto del splitter, así que parecía no hacer nada.
        self._add_action(
            view_menu,
            self.tr("&Logging panel"),
            "Ctrl+J",
            self.editor_tab.show_log_panel,
        )

        view_menu.addSeparator()
        # Cambiar de fichero abierto sin pasar por el ratón. Se resuelven en
        # la ventana, así que ganan al Ctrl+Tab que el `QTabWidget` de las
        # vistas usaría para lo suyo.
        self._add_action(
            view_menu, self.tr("&Next file"), "Ctrl+Tab", lambda: self._step_document(1)
        )
        self._add_action(
            view_menu,
            self.tr("&Previous file"),
            "Ctrl+Shift+Tab",
            lambda: self._step_document(-1),
        )

        view_menu.addSeparator()
        self._build_theme_menu(view_menu)
        self._build_language_menu(view_menu)

        help_menu = bar.addMenu(self.tr("&Help"))
        # La base se distribuye aparte y se descarga sola la primera vez
        # (`gui/app.ensure_database`). Estas dos son para después: traer una
        # más nueva, y señalar una propia cuando la descarga no sirve —que
        # hoy es siempre, porque todavía no hay nada publicado.
        self._add_action(
            help_menu, self.tr("&Update database…"), None, self.update_database
        )
        self._add_action(
            help_menu, self.tr("Use a &local database…"), None, self.use_local_database
        )

        help_menu.addSeparator()
        self._add_action(help_menu, self.tr("&Licenses…"), None, self.show_licenses)
        self._add_action(
            help_menu, self.tr("&About KernelGrove"), None, self.show_about
        )

    def _build_theme_menu(self, parent_menu) -> None:
        """Submenú de apariencia: primero la piel, después el modo.

        Los modos que se ofrecen dependen de la piel: la clásica solo tiene
        oscuro, así que con ella puestos se deshabilitan en vez de mentir
        con una opción que no hace nada.
        """
        menu = QMenu(self.tr("&Appearance"), self)
        parent_menu.addMenu(menu)

        skin = self._settings.value(SETTING_SKIN) or theme.SKIN_CLASSIC
        skins = QActionGroup(self)
        skins.setExclusive(True)
        for value, label in (
            (theme.SKIN_CLASSIC, self.tr("Classic")),
            (theme.SKIN_SITE, self.tr("KernelGrove site")),
            (theme.SKIN_OBSIDIAN, self.tr("Obsidian Deep")),
            (theme.SKIN_CONTRAST, self.tr("High contrast")),
            (theme.SKIN_COLORBLIND, self.tr("Colorblind-safe")),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(value == skin)
            action.triggered.connect(lambda _c=False, s=value: self._set_skin(s))
            skins.addAction(action)
            menu.addAction(action)

        menu.addSeparator()
        modes = QActionGroup(self)
        modes.setExclusive(True)
        stored = self._settings.value(SETTING_THEME) or theme.MODE_DARK
        disponibles = theme.modes_of(skin)
        for mode, label in (
            (theme.MODE_LIGHT, self.tr("Light")),
            (theme.MODE_DARK, self.tr("Dark")),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(mode == stored)
            action.setEnabled(len(disponibles) > 1)
            action.triggered.connect(lambda _c=False, m=mode: self._set_theme(m))
            modes.addAction(action)
            menu.addAction(action)

    def _set_skin(self, skin: str) -> None:
        """Cambia de piel en caliente y la recuerda para la próxima sesión."""
        self._settings.setValue(SETTING_SKIN, skin)
        self._settings.sync()
        self._repaint_theme(
            self._settings.value(SETTING_THEME) or theme.MODE_DARK, skin
        )

    def _set_theme(self, mode: str) -> None:
        """Cambia el modo en caliente y lo recuerda para la próxima sesión."""
        self._settings.setValue(SETTING_THEME, mode)
        self._settings.sync()
        self._repaint_theme(mode)

    def _repaint_theme(self, mode: str, skin: str = None) -> None:
        """Aplica piel y modo, y repinta lo que el QSS no alcanza.

        En caliente de verdad: `apply_theme` recompone la hoja y los colores
        que usan los `QPainter` (`style.refresh`), y lo que queda es pedir un
        repintado a lo que dibuja por su cuenta — el grafo, que tiene sus
        colores metidos en cada `QGraphicsItem`.
        """
        # La piel se pasa cuando quien llama acaba de decidirla: leerla de
        # vuelta de `QSettings` para aplicar lo que uno mismo acaba de
        # escribir es un viaje de ida y vuelta que solo puede salir mal.
        skin = skin or self._settings.value(SETTING_SKIN) or theme.SKIN_CLASSIC
        apply_theme(QApplication.instance(), mode, skin)
        # `retranslate` rehace los iconos de la barra de actividad, que se
        # dibujan con `QPainter` en el color del texto atenuado y por tanto
        # no los alcanza el QSS, y redibuja el grafo (cada nodo lleva su
        # color dentro del `QGraphicsItem`).
        self.retranslate()
        # Las tarjetas del mockup solo existen en la piel de la web; se
        # buscan en el árbol de widgets en vez de enumerarlas aquí, que es
        # una lista que se queda vieja en cuanto alguien añade una.
        for card in self.findChildren(Card):
            card.refresh_skin()
        # Todo lo que lleva un icono dibujado a mano tiene que rehacerlo: se
        # pintó con `QPainter` en un color de la piel anterior. Se busca por
        # el árbol de widgets en vez de enumerarlos aquí, que es una lista
        # que se queda vieja en cuanto alguien añade un botón con icono.
        for widget in self.findChildren(QWidget):
            refrescar = getattr(widget, "refresh_icons", None)
            if callable(refrescar):
                refrescar()
        self.inspector_panel.refresh_skin()
        for document in self.editor_tab.all_documents():
            document.editor.refresh_theme()
        self.editor_tab.refresh_theme()
        self._set_status(
            self.tr("Appearance: {skin} · {mode}").format(
                skin=skin, mode=theme.resolve_mode()
            )
        )

    def _build_language_menu(self, parent_menu) -> None:
        """Submenú con los idiomas disponibles, marcando el activo.

        La lista sale de los ficheros `.qm` que haya (`available_languages`),
        no de una tabla en el código: añadir un idioma es añadir su fichero.
        Los nombres los da Qt en el propio idioma («English», «Español»).
        """
        # El submenú se construye con la ventana como padre y se guarda en
        # `self`: el `QMenu` que devuelve `addMenu(texto)` no queda retenido
        # por nadie del lado de Python, y el recolector se lleva el objeto C++
        # con él — el menú desaparece, o revienta al pulsarlo.
        menu = QMenu(self.tr("&Language"), self)
        parent_menu.addMenu(menu)

        group = QActionGroup(self)
        group.setExclusive(True)

        stored = self._settings.value(SETTING_LANGUAGE) or ""
        entries = [("", self.tr("System language"))]
        entries += [
            (code, translations.language_name(code))
            for code in translations.available_languages()
        ]

        for code, label in entries:
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(code == stored)
            action.triggered.connect(
                lambda _checked=False, value=code: self._set_language(value)
            )
            group.addAction(action)
            menu.addAction(action)

    def _set_language(self, language: str) -> None:
        """Cambia el idioma en caliente y lo recuerda para la próxima sesión.

        Instalar el traductor hace que Qt reparta `LanguageChange` por todos
        los widgets, y cada uno rehace sus textos (`Retranslates`). Lo que no
        es un widget no recibe ese evento y se refresca aquí: los menús, el
        modelo del árbol de periféricos y las secciones del panel izquierdo.
        """
        if (self._settings.value(SETTING_LANGUAGE) or "") == language:
            return
        self._settings.setValue(SETTING_LANGUAGE, language)
        self._settings.sync()
        active = translations.install_translations(QApplication.instance(), language)
        # Después de instalar, no antes: el `retranslate` que dispara el
        # cambio de idioma devuelve la barra de estado a su mensaje en reposo
        # y se llevaría este por delante.
        self._set_status(
            self.tr("Language: {language}").format(
                language=translations.language_name(active)
            )
        )

    def retranslate(self) -> None:
        """Rehace todo lo que la ventana pone y no se retraduce solo."""
        # Los menús se reconstruyen enteros: son acciones, no widgets con
        # texto que se pueda re-fijar, y así el idioma marcado en «Idioma»
        # queda al día de paso.
        self._build_menus()
        self._retranslate_tool_windows()
        self.palette_button.setText(self.tr("  Search…    Ctrl+P"))
        self.palette_button.setToolTip(
            self.tr("Search files, views, SoCs and boards")
        )
        self._sync_top_bar()

        # Sin tocar `_current_section`: cambiar de idioma no cambia de
        # sección, solo rehace sus nombres.
        sections = self._activity_sections()
        self._left_sections = [section.title for section in sections]
        self.activity_bar.set_sections(sections)
        self._left_header.setText(
            self._left_sections[self._left_stack.currentIndex()]
        )
        self._inspector_header_label.setText(self.tr("INSPECTOR"))
        self.database_tab.setWindowTitle(messages.title_database_catalogue())
        # Los pies de los paneles ya no traen su propio texto: lo pone la
        # vista central, así que se rehacen desde aquí.
        self._refresh_panel_footers()
        self._inspector_collapse_button.setToolTip(
            self.tr("Expand inspector")
            if self.inspector_panel.isHidden()
            else self.tr("Collapse inspector")
        )

        self._refresh_status_items(self._active_document)
        self.document_bar.setToolTip(
            self.tr(
                "Open files: the selected one is the file being edited and "
                "the one drawn in the visualizer."
            )
        )
        self.analyze_button.setText(self.tr("Analyze"))
        self.analyze_button.setToolTip(
            self.tr("Re-run the analysis on the active document")
        )
        self._version_label.setToolTip(self.tr("KernelGrove version"))

        # El modelo del árbol de periféricos es un `QAbstractItemModel`, no un
        # widget: no le llega `LanguageChange`. Sus cabeceras y sus tooltips
        # se refrescan avisando a las vistas que lo muestran.
        self.tree_model.headerDataChanged.emit(Qt.Horizontal, 0, 3)
        self.tree_model.layoutChanged.emit()

        # La barra de estado se queda con el último mensaje, que puede ser de
        # cualquier momento; se vuelve al resumen de la base, que es lo que
        # muestra en reposo.
        self._set_status(self._database_summary())

    def close_current_document(self) -> None:
        """Cierra el fichero activo (Ctrl+W), preguntando si tiene cambios."""
        self.editor_tab.close_document(self.editor_tab.current_document_index())

    def find_in_document(self) -> None:
        """Abre la barra de búsqueda en el editor donde esté el cursor.

        La ventana es la **única** dueña de Ctrl+F. Registrarlo también en
        cada `DtsEditor` hacía que Qt viera el mismo atajo por duplicado y no
        disparara ninguno de los dos ("Ambiguous shortcut overload"), con lo
        que la búsqueda dejaba de existir.

        Se busca en el editor que tenga el foco, no en el del documento
        activo: así Ctrl+F también funciona sobre el "DTS completo" del
        Generador, que es otro `DtsEditor` de solo lectura. Sin foco en
        ninguno se cae al documento abierto, cambiando a su pestaña.
        """
        editor = self._focused_editor()
        if editor is not None:
            editor.open_find()
            return

        document = self.editor_tab.current
        if document is None:
            return
        self.show_view(TAB_EDITOR)
        document.editor.open_find()

    def _focused_editor(self) -> Optional[DtsEditor]:
        """`DtsEditor` que tiene el foco, o que contiene al que lo tiene.

        Se sube por los padres porque el foco puede estar en un hijo del
        editor —la propia barra de búsqueda, sin ir más lejos— y seguir
        queriendo decir "busca aquí".
        """
        widget = QApplication.focusWidget()
        while widget is not None:
            if isinstance(widget, DtsEditor):
                return widget
            widget = widget.parentWidget()
        return None

    def _step_document(self, delta: int) -> None:
        """Pasa al fichero siguiente o anterior, dando la vuelta al llegar al final."""
        count = self.document_bar.count()
        if count < 2:
            return
        index = (self.document_bar.currentIndex() + delta) % count
        self.editor_tab.activate_document(index)

    def update_database(self) -> None:
        """Trae la base publicada, si la hay más nueva o si falta.

        No se recarga en caliente: la base la tienen abierta varias capas
        con su conexión por hilo y sus cachés, y cambiar el fichero por
        debajo es de las cosas que funcionan a medias. Se dice que hay que
        reiniciar, que es una vez y es verdad.
        """
        from kernelgrove.gui.app import download_database
        from kernelgrove.main import USER_DB_PATH, remember_db_path

        descargada = download_database(USER_DB_PATH)
        if descargada is None:
            from kernelgrove.gui.app import _ultimo_error

            QMessageBox.warning(
                self, messages.title_database(), _ultimo_error[0]
            )
            return
        remember_db_path(descargada)
        self._database_changed(descargada)

    def use_local_database(self) -> None:
        """Señala una base que ya se tiene, y la recuerda para la próxima."""
        from kernelgrove.gui.app import ask_for_database

        elegida = ask_for_database(self)
        if elegida is not None:
            self._database_changed(elegida)

    def _database_changed(self, path: Path) -> None:
        """Avisa de que la base nueva entra en el próximo arranque."""
        self._set_status(self.tr("Database: {path}").format(path=path))
        QMessageBox.information(
            self,
            messages.title_database(),
            self.tr(
                "The database is ready. Restart KernelGrove to start using it."
            ),
        )

    def show_licenses(self) -> None:
        """Enseña la licencia del proyecto y las de sus componentes.

        Flotante y no modal, como el resto de ventanas de consulta: leerla
        es algo que se hace *mientras* se trabaja.
        """
        if self._licenses_window is None:
            self._licenses_window = LegalDialog(
                self, licenses_text(), messages.title_licenses()
            )
        _show_tool_window(self._licenses_window)

    def show_about(self) -> None:
        """Ficha con la versión y con qué se compila en esta máquina.

        Se consulta cada vez y no al arrancar: `dtc` se puede instalar con
        la aplicación abierta —que es justo lo que pide el mensaje de ayuda
        cuando falta— y enseñar aquí lo que había al arrancar sería mentir
        justo donde se va a mirar para comprobarlo.
        """
        herramientas = self.service.toolchain()
        no_esta = messages.tool_not_found()
        # La **versión**, no la ruta: dónde está instalada no dice nada de
        # si va a compilar, y la ruta de un `cpp` de distribución es larga
        # y ocupa la línea entera.
        version_dtc = dtc_version(herramientas)
        if herramientas.dtc is None:
            dtc = no_esta
        else:
            dtc = version_dtc or self.tr("unknown version")
            if herramientas.dtc_supports_symbols:
                dtc = messages.tool_with_symbols(dtc)
        cpp = no_esta
        if herramientas.cpp is not None:
            cpp = cpp_version(herramientas) or self.tr("unknown version")
        QMessageBox.about(
            self,
            messages.title_about(),
            messages.about_text(
                version=__version__,
                dtc=dtc,
                cpp=cpp,
                dtschema=self.service.dtschema_version() or self.tr("unknown"),
            ),
        )

    # ------------------------------------------------------------------
    # Selección del device tree
    # ------------------------------------------------------------------
    @staticmethod
    def _index_by(
        items: Sequence[SoCSummary],
    ) -> Tuple[Dict[str, SoCSummary], Dict[str, SoCSummary]]:
        """Índices por ruta y por compatible, comunes a SoCs y boards."""
        by_path = {item.file_path: item for item in items if item.file_path}
        by_compatible = {item.compatible: item for item in items if item.compatible}
        return by_path, by_compatible

    def _load_socs(self) -> None:
        """Puebla el selector con los device trees de la base de datos."""
        self.socs = self.service.list_socs()
        self._socs_by_path, self._socs_by_compatible = self._index_by(self.socs)
        if not self.socs:
            self._set_status(self._database_summary())
            return

        self._set_status(self._database_summary())

    def _database_summary(self) -> str:
        """Qué trae la base abierta: el mensaje que la barra muestra en reposo.

        Es también a lo que se vuelve al cambiar de idioma, porque el último
        mensaje de la barra puede ser de cualquier momento y no se puede
        retraducir sin saber cuál era.
        """
        if not self.socs:
            return self.tr(
                "The database contains no SoCs. Build it with "
                "scripts/build_database.sh"
            )

        # Si la base no trae los schemas de binding (se construyó sin
        # dtschema), la capa 5 del motor no se ejecuta: conviene que se vea.
        if not self.service.binding_schemas_available():
            return self.tr(
                "The database carries no binding schemas: nothing is validated "
                "against them"
            )

        # Y con la base en orden, nada. Aquí se enumeraba cuántos SoCs,
        # ficheros y schemas trae: son datos del arranque, no dicen nada de
        # lo que se está editando y no cambian en toda la sesión, así que
        # ocupaban en permanente el sitio del mensaje. Están en «Acerca de».
        return self.tr("Ready")

    def _load_boards(self) -> None:
        """Puebla el selector con las boards de la base de datos."""
        self.boards = self.service.list_boards()
        self._boards_by_path, self._boards_by_compatible = self._index_by(self.boards)
        # El catálogo entero de una vez, no lista por lista: la pestaña
        # pinta SoCs y boards en la misma lista de fichas, así que poblarla
        # dos veces la reconstruiría entera para nada.
        self.database_tab.load(self.socs, self.boards)
        self._refresh_status_items(self._active_document)

    def _open_summary(
        self,
        items: List[SoCSummary],
        index: int,
        kind: str,
        read_source: Callable[[SoCSummary], Optional[StoredSource]],
    ) -> None:
        """Abre en el editor, en una pestaña nueva, el fuente del elemento elegido.

        Común a `_on_soc_selected` y `_on_board_selected`: los dos resuelven y
        abren su fuente igual, solo cambia de qué lista y con qué lector de
        la base de datos se hace.
        """
        if index < 0 or index >= len(items):
            return

        item = items[index]
        self.database_tab.select_entry(kind, index)
        source = read_source(item)
        if source is None:
            QMessageBox.warning(
                self,
                messages.title_source_not_available(),
                messages.source_not_available(item.name),
            )
            return

        self.editor_tab.open_source(
            title=Path(source.path).name,
            text=source.text,
            source_key=source.path,
        )
        self.show_view(TAB_EDITOR)
        self._set_status(
            self.tr("{name} opened from the database").format(name=item.name)
        )

    def _on_soc_selected(self, index: int) -> None:
        """Abre en el editor, en una pestaña nueva, el fuente del SoC elegido."""
        self._open_summary(
            self.socs,
            index,
            KIND_SOC,
            self.service.read_soc_source,
        )

    def _on_board_selected(self, index: int) -> None:
        """Abre en el editor, en una pestaña nueva, el fuente de la board elegida."""
        self._open_summary(
            self.boards,
            index,
            KIND_BOARD,
            self.service.read_board_source,
        )

    def _read_disk_text(self, path: Path) -> Optional[str]:
        """Lee un fichero del disco como texto, o avisa y devuelve `None`.

        Leer y decidir si el fichero es apto vive en `gui.file_io`, que no
        sabe nada de Qt; aquí solo se traduce el motivo del rechazo al
        diálogo que le corresponde.
        """
        text, error = file_io.read_text_file(path)
        if error is None:
            return text

        if isinstance(error, file_io.FileTooLargeError):
            QMessageBox.warning(
                self,
                messages.title_file_not_text(),
                messages.file_too_large(error.path, error.size, error.limit),
            )
        elif isinstance(error, file_io.FileLooksBinaryError):
            QMessageBox.warning(
                self, messages.title_file_not_text(), messages.file_looks_binary(path)
            )
        else:
            QMessageBox.critical(
                self, messages.title_file_open_error(), messages.file_error(error)
            )
        return None

    def open_folder(self) -> None:
        """Cambia la carpeta que muestra el panel lateral, y la recuerda."""
        folder = QFileDialog.getExistingDirectory(
            self, self.tr("Open folder"), str(self.explorer_panel.current_root())
        )
        if not folder:
            return
        path = Path(folder)
        self.explorer_panel.set_root(path)
        self.git_panel.set_root(path)
        # El repositorio es otro, así que los estados de antes no valen: sin
        # esto el árbol nuevo sale teñido con los cambios de la carpeta que
        # se acaba de dejar, hasta el siguiente análisis.
        self._refresh_git_decoration()
        # Y el listado de overlays, que si no se queda enseñando los de la
        # carpeta anterior hasta el siguiente análisis: su carpeta solo se
        # le pasaba desde `_on_document_analyzed`.
        self.overlay_panel.set_library(path, self._overlay_base)
        self.build_panel.set_folder(path)
        self._watch_folder(path)
        self._settings.setValue(SETTING_EXPLORER_ROOT, str(path))
        self.activity_bar.show_section(SECTION_FOLDERS)
        self._set_status(self.tr("Folder: {path}").format(path=path))

    def _open_explorer_file(self, filename: str) -> None:
        """Abre en una pestaña nueva el fichero elegido en el panel de carpetas.

        Un clic en el explorador solo añade una pestaña más, no sustituye lo
        que hubiera abierto (que es lo que sí hace elegir otro SoC del
        catálogo) — es un atajo de navegación, no una elección de "con
        qué device tree trabajar ahora", así que no debe cerrar lo que ya
        estaba abierto. Igual que `_open_include`. El fichero puede ser
        cualquier cosa (el panel ya no filtra por extensión); si no es un
        `.dts`/`.dtsi`, `EditorTab` simplemente no lo analiza.
        """
        path = Path(filename)
        text = self._read_disk_text(path)
        if text is None:
            return

        self.editor_tab.open_source(
            title=path.name,
            text=text,
            source_key=str(path),
            disk_path=path,
            overlay_base=self._overlay_base if _is_overlay(path, text) else None,
        )
        # En el modo que esté puesto, no siempre en el editor: quien esté
        # mirando el grafo abre el fichero en el grafo.
        self.show_view(self._document_view)
        self._set_status(self.tr("Opened {path}").format(path=path))

    def _on_node_at_cursor_changed(self, node) -> None:
        """Refresca el Inspector con el nodo donde ha caído el cursor."""
        self.inspector_panel.show_node(node)

    # ------------------------------------------------------------------
    # Coordinación entre pestañas
    # ------------------------------------------------------------------
    def _sync_document_bar(self) -> None:
        """Refleja en la barra común los documentos abiertos en el editor.

        Se reaprovechan las pestañas existentes en lugar de reconstruirlas:
        esto también se llama al cambiar de documento activo, y rehacer la
        barra en cada cambio la haría parpadear.
        """
        labels = self.editor_tab.document_labels()

        self.document_bar.blockSignals(True)
        while self.document_bar.count() > len(labels):
            self.document_bar.removeTab(self.document_bar.count() - 1)
        for index, (title, tooltip, modified) in enumerate(labels):
            if index >= self.document_bar.count():
                self.document_bar.addTab(title)
                self.document_bar.setTabButton(
                    index, QTabBar.RightSide, self._make_close_button()
                )
            elif self.document_bar.tabText(index) != title:
                self.document_bar.setTabText(index, title)
            self.document_bar.setTabToolTip(index, tooltip)
            close_button = self.document_bar.tabButton(index, QTabBar.RightSide)
            if isinstance(close_button, TabCloseButton):
                close_button.set_modified(modified)
        self.document_bar.setCurrentIndex(self.editor_tab.current_document_index())
        self.document_bar.blockSignals(False)

        self.document_bar.setVisible(bool(labels))
        document = self.editor_tab.current
        # El tipo de fichero y el fin de línea son del documento activo, y
        # este es el único sitio por el que pasa cualquier cambio de cuál lo
        # es —abrir, cerrar, cambiar de pestaña—. Colgarlos del análisis
        # dejaba la franja en blanco hasta el primer análisis, y describiendo
        # el fichero anterior al cambiar de pestaña.
        self._refresh_document_items(document)
        if not labels:
            self.visualizer_tab.clear()
            # `_on_document_analyzed` no vuelve a dispararse si ya no queda
            # ningún documento que analizar — sin esto, el Inspector se
            # quedaría mostrando el último fichero cerrado.
            self.inspector_panel.show_node(None)

    def _on_document_analyzed(self, document) -> None:
        """Refresca Visualizador y Generador con el árbol del documento activo.

        `soc_profile_from_tree` (y por tanto los controladores resaltados) se
        calcula sobre el árbol ya fusionado: un controlador declarado en un
        `.dtsi` incluido no aparecía antes en `document.parse_result.root`, y
        ahí sí forma parte de la jerarquía real.

        Se dispara tanto al cargar un fichero como al cambiar de pestaña
        activa o al reanalizar por una edición — `EditorTab` no distingue
        estos casos con señales separadas. Aquí sí importa distinguirlos:
        cambiar de documento activo (`is_new_active_document`) tiene que
        refrescar también el Generador con el perfil de ESE documento, igual
        que ya hacen el Editor (que simplemente muestra la pestaña elegida) y
        el Visualizador; una reanálisis del documento que ya estaba activo
        (seguir escribiendo) no debe tocar la sesión de conexión, o se
        perderían las conexiones que el usuario ya hubiera hecho en él.
        """
        self._mark_git_changes(document)
        self._refresh_status_items(document)

        result = document.parse_result

        if result is None:
            self._current_merged_root = None
            self._current_soc_compatible = None
            self._active_document = None
            self._edit_session_document = None
            self.visualizer_tab.clear()
            return

        is_new_active_document = document is not self._active_document
        self._active_document = document

        if document.overlay_base is not None:
            # Un overlay solo, dibujado tal cual, son dos pseudo-nodos sin
            # sentido. Lo que interesa ver es su efecto: la base con el
            # overlay ya aplicado, que es justo lo que devuelve el preview.
            merged_root, cambios = self.service.preview_overlay(
                document.overlay_base, result
            )
            unresolved = []
            self._set_status(
                self.tr("Overlay: {count} changes over the base").format(
                    count=len(cambios)
                )
            )
        else:
            merged_root, unresolved = self.service.build_visual_tree(
                result, document.source_key
            )
        self._current_merged_root = merged_root
        if document.overlay_base is None:
            # La base para comprobar overlays es un árbol **completo**: si el
            # documento activo ya es un overlay, `merged_root` es la base con
            # ese overlay aplicado, que no sirve de referencia para los demás.
            self._overlay_base = merged_root
        profile = self.service.soc_profile_from_tree(
            merged_root, Path(document.title).stem
        )
        controllers = {node.name for node in profile.peripherals}
        soc_name = self._soc_name_for(document.source_key, merged_root.compatible) or (
            merged_root.compatible[0] if merged_root.compatible else document.title
        )
        self._current_soc_compatible = soc_name
        board_name = (
            self._board_name_for(document.source_key, merged_root.compatible)
            or soc_name
        )

        if is_new_active_document:
            self._edit_session_document = document
            self.generator_tab.load_profile(profile, document.editor.toPlainText())

        # La sesión de conexión compartida (`self.tree_model`) solo se
        # solapa sobre el grafo si pertenece a este mismo documento — con lo
        # de arriba, eso es siempre que haya un documento activo con
        # contenido analizable, pero la comprobación se queda por si algún
        # día vuelve a haber casos donde no coincidan.
        session_slots = (
            self.tree_model.root_slots()
            if document is self._edit_session_document
            else None
        )
        self.visualizer_tab.show_tree(
            merged_root,
            unresolved,
            controllers,
            soc_name,
            board_name,
            session_slots,
            # Sobre el árbol **fusionado**: los cpus de una board están en el
            # `.dtsi` del SoC que incluye, así que su propio árbol no los
            # tiene. Es el mismo dato que la ingesta guarda por entrada del
            # catálogo, calculado aquí sobre lo que hay en pantalla.
            hardware=extract_hardware(merged_root),
        )

        # El asistente de overlays trabaja siempre contra un árbol completo:
        # si el documento activo ya es un overlay, su base sigue siendo la
        # referencia, no el resultado de aplicarlo sobre sí mismo.
        self.overlay_tab.set_base(document.overlay_base or merged_root)
        self.overlay_panel.set_library(
            self.explorer_panel.current_root(), self._overlay_base
        )

    def _mark_git_changes(self, document) -> None:
        """Marca en el margen del editor lo que no está en la última versión.

        Se compara el **texto que hay escrito** contra el que guardó git, no
        el fichero del disco: mientras se escribe, el disco va por detrás de
        lo que se ve, y el margen tiene que hablar de lo que se ve. El coste
        es un `git show` por análisis (~25 ms, y el análisis ya está retardado
        600 ms tras la última tecla).

        **Aquí no se decora el árbol de carpetas.** Se hacía, con el
        argumento de que era el mismo momento y salía gratis; no salía; era
        un `git status` entero por análisis —~200 ms en un repositorio
        grande, bloqueando la interfaz cada vez que se dejaba de teclear—, y
        además contestaba a otra pregunta: el árbol pinta lo que hay en el
        **disco**, que no cambia por escribir. Ahora se pinta cuando el disco
        cambia (`EditorTab.document_saved`) y cuando el panel de git ya ha
        leído el estado por su cuenta (`GitPanel.statusRefreshed`).

        Un documento sin fichero propio, o fuera del repositorio, no tiene
        contra qué compararse y se queda sin marcas.
        """
        editor = document.editor
        changes = self.git_panel.line_changes(
            document.disk_path, editor.toPlainText()
        )
        editor.set_change_lines(changes.added, changes.modified, changes.deleted)

    def _refresh_git_decoration(self) -> None:
        """Repinta el estado de git en el árbol de carpetas.

        Un solo `git status`, y solo cuando el disco ha cambiado: al guardar,
        al abrir otra carpeta, y cuando el propio panel de git se refresca
        (que lo publica ya leído, `GitPanel.statusRefreshed`).
        """
        self.explorer_panel.set_git_status(self.git_panel.file_status())

    def _soc_name_for(
        self, source_key: Optional[str], compatible: Sequence[str]
    ) -> Optional[str]:
        """Identifica el SoC al que corresponde el árbol mostrado.

        El nodo central del grafo debe ser "el SoC", no la raíz DTS: para
        saberlo hay que identificar qué `.dtsi` es ese SoC. El caso habitual
        es directo —es justo el fichero abierto, el que se eligió en el
        desplegable o el que se abrió al hacer doble clic en un include—, así
        que primero se busca por su ruta exacta entre los SoCs de la base de
        datos. Si no está registrado por ruta (un fichero suelto del PC, o un
        `.dts` que no se ingiere como SoC), se busca por `compatible`, que es
        como se identifica cualquier SoC en la tabla. Si tampoco así se
        encuentra, el llamante decide el respaldo (compatible propio o
        título del documento).

        Se devuelve `soc.compatible`, no `soc.name`: el nombre de fila viene
        del nombre de fichero, y lo que identifica al SoC de verdad —lo que
        hay que mostrar— es su compatible.
        """
        if source_key:
            soc = self._socs_by_path.get(source_key)
            if soc is not None:
                return soc.compatible

        for value in compatible:
            soc = self._socs_by_compatible.get(value)
            if soc is not None:
                return soc.compatible

        return None

    def _board_name_for(
        self, source_key: Optional[str], compatible: Sequence[str]
    ) -> Optional[str]:
        """Identifica la board a la que corresponde el árbol mostrado.

        Simétrico a `_soc_name_for`, pero contra la tabla `boards`: mientras
        el SoC se etiqueta al desplegar el nodo central, la board es lo que
        se ve mientras está plegado -"la placa vista desde fuera"-, así que
        `_on_document_analyzed` la calcula igual y se la pasa a
        `VisualizerTab.show_tree` como `board_name`.
        """
        if source_key:
            board = self._boards_by_path.get(source_key)
            if board is not None:
                return board.compatible

        for value in compatible:
            board = self._boards_by_compatible.get(value)
            if board is not None:
                return board.compatible

        return None

    def _open_soc_properties(self) -> None:
        """Abre el panel de lo empaquetado dentro del nodo central del grafo.

        Doble clic en el SoC, igual que doble clic en el bloque PS de Vivado
        abre su asistente: no hay nada que colgar, solo el estado de los
        controladores que trae integrados (`build_soc_package`).

        Es una ventana suelta y **no modal**, como la ficha de propiedades
        del editor (`PropertyPanel`): encender un controlador es algo que se
        hace mirando el grafo y el fuente, así que la ventana tiene que poder
        quedarse a un lado mientras se trabaja, no bloquear la aplicación
        hasta cerrarla. Se reutiliza la misma en vez de apilar una por cada
        doble clic.
        """
        if self._current_merged_root is None:
            return

        package = self.service.build_soc_package(
            self._current_merged_root, self._current_soc_compatible
        )
        if self._soc_dialog is None:
            self._soc_dialog = SocPropertiesDialog(package, self)
            self._soc_dialog.applyRequested.connect(self._apply_soc_overrides)
        else:
            self._soc_dialog.show_package(package)
        _show_tool_window(self._soc_dialog)

    def _open_node_inspector(self, path: str) -> None:
        """Abre la ficha del Inspector para un nodo del grafo, en un diálogo.

        El dock del Inspector solo existe con la vista central en el Editor
        (lee el nodo bajo *su* cursor), así que desde el grafo no hay dónde
        enseñarlo sin abandonar la vista que se está mirando — de ahí el
        diálogo, igual que "Open inspector" (grafo) reutiliza el mismo
        widget en vez de duplicar su lógica.

        Igual que el panel del SoC, es una ventana suelta y **no modal**
        (`PropertyPanel`): se consulta un nodo *mientras* se mira el grafo o
        se edita el fuente, así que no puede bloquear el resto. Se reutiliza
        la misma ventana, enseñando en ella el nodo que se pida cada vez.
        """
        if self._current_merged_root is None:
            return
        node = _find_node_by_path(self._current_merged_root, path)
        if node is None:
            return

        if self._inspector_dialog is None:
            dialog = QDialog(self)
            dialog.resize(*style.NODE_INSPECTOR_DIALOG_SIZE)
            layout = QVBoxLayout(dialog)
            self._inspector_panel = InspectorPanel(self.service)
            layout.addWidget(self._inspector_panel)
            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(dialog.close)
            layout.addWidget(buttons)
            self._inspector_dialog = dialog
            self._retranslate_tool_windows()

        self._inspector_panel.show_node(node)
        _show_tool_window(self._inspector_dialog)

    def _retranslate_tool_windows(self) -> None:
        """El título del Inspector del grafo, que no es un widget con texto.

        El diálogo se monta a mano, así que su título no viaja en ningún
        `retranslate()` propio y hay que rehacerlo desde aquí al cambiar de
        idioma (mismo caso que los menús).
        """
        if self._inspector_dialog is not None:
            self._inspector_dialog.setWindowTitle(self.tr("Inspector"))

    def _open_node_source(self, path: str, label: str) -> None:
        """Lleva el editor a donde está escrito un nodo del grafo.

        El grafo dibuja el árbol **fusionado**, así que la línea que arrastra
        un nodo cuenta sobre el fichero que lo declara, y ese puede no ser el
        que se está editando: en una placa, sus controladores los declara el
        `.dtsi` del SoC, con líneas que en el documento abierto no existen
        siquiera. De ahí que se resuelva aquí y en este orden:

        1. El nodo escrito tal cual en el documento abierto.
        2. El `&etiqueta { … }` / `&{/ruta} { … }` con el que el documento lo
           reabre —lo normal en una placa, y además lo que se quiere ver: lo
           que *este* fichero le hace al nodo, no cómo lo define el SoC—.
        3. El include que lo declara, que se abre en otra pestaña
           (`find_node_source`).

        Si no aparece en ninguno de los tres se dice, en vez de saltar a una
        línea cualquiera.
        """
        document = self.editor_tab.current
        if document is None or document.parse_result is None:
            return

        own_root = document.parse_result.root
        node = _find_node_by_path(own_root, path)
        if node is None and label:
            node = own_root.find_child(f"&{label}")
        if node is None:
            node = own_root.find_child("&{/" + path + "}")
        if node is not None and node.line:
            self._go_to_line(node.line)
            return

        found = self.service.find_node_source(
            document.parse_result, document.source_key, path
        )
        if found is None:
            self._set_status(
                self.tr("{node} is not written in any file reachable from here")
                .format(node=path)
            )
            return

        include, line = found
        self._open_include(include)
        self._go_to_line(line)

    def _apply_soc_overrides(self, changes: List[PropertyOverride]) -> None:
        """Escribe los cambios del panel de propiedades sobre el documento activo.

        Se generan como bloques `&label { … }` (ver `api.overrides`): es la
        misma forma que `resolve_label_overrides` funde de vuelta en el nodo
        real, así que el grafo y el propio panel reflejan el cambio en
        cuanto se reanaliza. Se guarda directamente si el documento tiene un
        fichero local asociado; si no, se ofrece el diálogo de guardar como.
        """
        document = self.editor_tab.current
        if document is None:
            return

        new_text = apply_overrides(document.editor.toPlainText(), changes)
        document.editor.setPlainText(new_text)
        self.editor_tab.analyze()
        # Escribir a disco es cosa del editor, que es quien sabe si el
        # documento tiene fichero propio o hay que preguntar dónde ponerlo.
        # Aquí había una segunda copia de esa lógica, con su propio manejo
        # de `OSError`: dos sitios donde arreglar el próximo fallo de
        # escritura.
        self.editor_tab.save_file()

        # `analyze()` ya ha refrescado `_current_merged_root` (conexión
        # directa, mismo hilo): el panel se rellena con el estado real, no
        # con lo que se acaba de pedir, por si el override no ha cuajado.
        if self._current_merged_root is not None and self._soc_dialog is not None:
            self._soc_dialog.show_package(
                self.service.build_soc_package(
                    self._current_merged_root, self._current_soc_compatible
                )
            )

    def _delete_source_nodes(self, nodes: List[Tuple[int, str]]) -> None:
        """Borra del documento abierto los nodos que el grafo señala.

        Solo llegan aquí los que ese documento escribe (`GraphNode.editable`):
        lo que trae un `#include` -el SoC bajo una placa- está en otro
        fichero y el grafo ni lo ofrece.

        Se borra sobre el `QTextDocument` del editor y no sustituyendo el
        texto entero, para que Ctrl+Z lo deshaga como cualquier otra
        edición, y **de abajo arriba**: cada corte mueve lo que va después,
        así que empezando por el final las líneas de los demás siguen
        valiendo. Tampoco se guarda a disco: queda como un cambio sin
        guardar más, visible en el margen del editor.
        """
        document = self.editor_tab.current
        if document is None or not nodes:
            return

        nombres = ", ".join(name for _line, name in nodes)
        answer = QMessageBox.question(
            self,
            self.tr("Delete node"),
            self.tr("Delete {names} from {file}?").format(
                names=nombres, file=document.title
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        editor = document.editor
        text = editor.toPlainText()
        spans = [
            span
            for span in (node_span(text, line) for line, _name in nodes)
            if span is not None
        ]
        cursor = editor.textCursor()
        cursor.beginEditBlock()
        for start, end in sorted(spans, reverse=True):
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
        cursor.endEditBlock()

        self.editor_tab.analyze()
        self._set_status(
            self.tr("{count} nodes deleted from the source").format(count=len(spans))
            if len(spans) != 1
            else self.tr("{name} deleted from the source").format(name=nombres)
        )

    # ------------------------------------------------------------------
    # Asistente de overlays
    # ------------------------------------------------------------------
    def _start_overlay_pick(self) -> None:
        """Pide el nodo objetivo: al editor, y con el device tree delante.

        Elegir el nodo se hace señalándolo en el fuente, así que lo primero
        es asegurarse de que hay un fuente delante: si la vista activa es
        otra (el grafo, el generador) se vuelve al editor, y si el documento
        activo no es un device tree se pone al frente el último que lo sea.
        """
        document = self.editor_tab.activate_last_device_tree()
        if document is None:
            self._set_status(
                self.tr("Open a device tree first: an overlay changes a node "
                        "of an existing tree.")
            )
            return

        self._picking_overlay_target = True
        self.show_view(TAB_EDITOR)
        self.editor_tab.focus_editor()
        self.editor_tab.set_node_picking(True)
        self.overlay_panel.show_picking()
        # El panel es donde se explica qué se espera ahora y por dónde
        # salirse, así que tiene que estar a la vista mientras se elige.
        self.activity_bar.show_section(SECTION_OVERLAY)
        self._set_status(self.tr("Click the node the overlay will change."))

    def _on_editor_node_clicked(self, node) -> None:
        """Clic en el editor: si se estaba eligiendo objetivo, ese es.

        Fuera del modo de selección no hace nada: un clic en el editor es
        mover el cursor, y solo cuando se ha pedido «elige un nodo» significa
        además elegirlo.
        """
        if not self._picking_overlay_target:
            return
        if node is None:
            self._set_status(
                self.tr("That is not inside a node. Click inside the one to change.")
            )
            return
        if not self.overlay_tab.start_draft(node):
            self._set_status(
                self.tr("That node has no label or path: an overlay cannot point "
                        "at it.")
            )
            return

        self._picking_overlay_target = False
        self.editor_tab.set_node_picking(False)
        self._show_overlay_tab(True)

    def _cancel_overlay(self) -> None:
        """Sale del asistente, esté eligiendo o a medio construir."""
        self._picking_overlay_target = False
        self.editor_tab.set_node_picking(False)
        self.overlay_tab.discard_draft()
        self.overlay_panel.show_idle()
        self._show_overlay_tab(False)

    def _show_overlay_tab(self, visible: bool) -> None:
        """Pone o quita la pestaña del borrador, según haya uno o no.

        Es la única vista que no está siempre: sin borrador no tiene nada
        que enseñar, y una pestaña permanentemente vacía es una invitación a
        entrar donde no hay nada.
        """
        index = self.tabs.indexOf(self.overlay_tab)
        if visible and index < 0:
            self.tabs.insertTab(TAB_OVERLAY, self.overlay_tab, "Overlays")
            self.tabs.setCurrentIndex(TAB_OVERLAY)
        elif not visible and index >= 0:
            self.tabs.removeTab(index)
            self.overlay_tab.setParent(self)
            self.overlay_tab.hide()
            self.show_view(TAB_EDITOR)

    def _show_property_panel(self, name: str, compatible: str) -> None:
        """Abre la ficha de una propiedad, pulsada en el inspector.

        La misma ventana siempre: pulsar otra propiedad la reutiliza en vez
        de dejar un reguero de ventanas abiertas por la pantalla.
        """
        self.property_panel.show_property(
            self.service.property_details(name, compatible or None), compatible
        )
        self.property_panel.show()
        self.property_panel.raise_()
        self.property_panel.activateWindow()

    def _find_property_usages(self, name: str) -> None:
        """Dónde se escribe esa propiedad en el documento que está abierto.

        En el documento **propio**, no en el árbol fusionado: las líneas de
        un nodo que viene de un include son líneas de otro fichero, y
        llevar el cursor a ellas señalaría a un sitio que no es. El parser
        ya indexa cada propiedad por (nodo, nombre) para poder situar los
        avisos, así que esto es leer ese índice, no recorrer el árbol.
        """
        document = self.editor_tab.current
        if document is None or document.parse_result is None:
            self.property_panel.show_usages([], self.tr("no open document"))
            return
        usages = sorted(
            (
                (path, line)
                for (path, prop), line in document.parse_result.property_lines.items()
                if prop == name
            ),
            key=lambda usage: usage[1],
        )
        self.property_panel.show_usages(usages, document.title)

    def _go_to_definition(self, reference: str) -> None:
        """Lleva el editor a donde se declara el nodo de un `&label`.

        La referencia se resuelve sobre el árbol **fusionado**, que es el
        único que sabe de qué fichero viene cada nodo: en una placa, `&i2c0`
        lo declara el `.dtsi` del SoC y en el documento abierto no hay
        ninguna línea que le corresponda. Si el nodo sí es de este documento
        —o no consta de dónde viene— se salta aquí mismo.
        """
        if self._current_merged_root is None:
            self._set_status(self.tr("Analyze the file first"))
            return

        node = find_by_reference(self._current_merged_root, reference)
        if node is None or not node.line:
            self._set_status(
                self.tr("{name} is not declared in any file reachable from here")
                .format(name=reference)
            )
            return

        if node.source_key is not None and not self._open_source_key(
            node.source_key
        ):
            self._set_status(
                self.tr("Could not open {path}").format(path=node.source_key)
            )
            return

        self._go_to_line(node.line)

    def _open_source_key(self, key: str) -> bool:
        """Abre en el editor el fuente con esa clave, o vuelve a él si ya estaba.

        La clave es la del `sources` de la base de datos
        (`xilinx/zynqmp.dtsi`) o una ruta absoluta, si el include se resolvió
        en el disco junto al fichero que lo abre. `open_source` ya reutiliza
        la pestaña cuando la clave coincide, así que ir dos veces a la misma
        definición no acumula copias.
        """
        path = Path(key)
        if path.is_absolute():
            text, error = file_io.read_text_file(path)
            if error is not None or text is None:
                return False
            self.editor_tab.open_source(
                title=path.name, text=text, source_key=key, disk_path=path
            )
            return True

        text = self.service.read_source(key)
        if text is None:
            return False
        self.editor_tab.open_source(
            title=Path(key).name, text=text, source_key=key
        )
        return True

    def _go_to_line(self, line: int) -> None:
        """Lleva el cursor del editor a una línea y enseña el editor."""
        document = self.editor_tab.current
        if document is None:
            return
        self.show_view(TAB_EDITOR)
        document.editor.go_to_line(line)

    def _on_overlay_draft_changed(self, source: str, line: int) -> None:
        """Refleja el borrador en el preview del panel lateral.

        Y se lleva la pestaña del borrador con él: al generar el fichero el
        asistente lo descarta, y una pestaña vacía sobreviviéndole no dice
        nada.
        """
        if not source:
            self.overlay_panel.show_idle()
            self._show_overlay_tab(False)
            return
        self.overlay_panel.show_preview(source)
        self.overlay_panel.highlight_line(line or None)

    def _watch_folder(self, folder: Path) -> None:
        """Vigila la carpeta abierta y sus subcarpetas, y suelta la anterior.

        Las mismas subcarpetas que se listan (`OVERLAY_SCAN_DEPTH`): vigilar
        el árbol entero sería vigilar un checkout del kernel si lo hay
        dentro, y vigilar solo la raíz dejaría fuera el `overlays/` donde
        todo el mundo los guarda.
        """
        anteriores = self._folder_watcher.directories()
        if anteriores:
            self._folder_watcher.removePaths(anteriores)
        if folder.is_dir():
            self._folder_watcher.addPaths([str(d) for d in _watched_dirs(folder)])

    def _on_folder_contents_changed(self, _path: str) -> None:
        """Algo ha cambiado en la carpeta: se relee, con retardo."""
        self._folder_reread.start()

    def _reread_folder_lists(self) -> None:
        """Relee las listas que salen del disco, y rehace la vigilancia.

        Lo segundo no es un detalle: una carpeta nueva —o una borrada—
        cambia qué hay que vigilar, y sin rehacerlo el aviso deja de llegar
        de donde ya no se mira.
        """
        folder = self.explorer_panel.current_root()
        self._watch_folder(folder)
        self.build_panel.set_folder(folder)
        self.overlay_panel.overlay_list.refresh()

    def _on_file_renamed(self, old: str, new: str) -> None:
        """Sigue al fichero renombrado —o movido— allí donde su ruta estaba anotada.

        La pestaña que lo tuviera abierto (o «Guardar» escribiría en el
        nombre viejo), la caché de bases resueltas —cuya clave es la ruta—
        y las dos listas de la sección de overlays, que son un listado del
        disco y no un modelo vivo.

        Y lo que colgaba de ello: cuando lo que se mueve es una carpeta,
        cambia la ruta de todo su contenido, así que la caché se vacía por
        prefijo y no solo por la clave exacta.
        """
        self.editor_tab.rename_document(Path(old), Path(new))
        dentro = old + os.sep
        for clave in [
            k for k in self._base_cache if k == old or k.startswith(dentro)
        ]:
            self._base_cache.pop(clave)
        self.build_panel.set_folder(self.explorer_panel.current_root())
        self.overlay_panel.overlay_list.refresh()

    def _resolve_base(self, key: str) -> Optional[DeviceTreeNode]:
        """Árbol fusionado de la base identificada por `key`, o `None`.

        `key` es un `source_key`: la ruta de un fichero del disco o la clave
        relativa de un fuente del catálogo. Se busca primero entre los
        documentos abiertos —ahí el texto puede estar sin guardar y es el que
        vale— y después en el disco y en la base de datos.

        El resultado se recuerda: comprobar una carpeta con varios overlays
        de la misma base repetiría el parseo y la fusión de un `.dtsi` de SoC
        entero una vez por fichero.
        """
        if key in self._base_cache:
            return self._base_cache[key]

        text = self.editor_tab.text_of(key)
        if text is None:
            text = self.service.read_source(key)
        if text is None:
            path = Path(key)
            if not path.is_file():
                # Un proyecto que ha cambiado de sitio se lleva consigo su
                # base, pero no la ruta con la que se anotó: se busca el
                # mismo nombre en la carpeta abierta antes de darla por
                # perdida.
                path = self.explorer_panel.current_root() / path.name
            text = self._read_disk_text(path) if path.is_file() else None
        if text is None:
            self._base_cache[key] = None
            return None

        result, _ = self.service.analyze_source(text, fragment=True, base_path=key)
        merged, _ = self.service.build_visual_tree(result, key)
        self._base_cache[key] = merged
        return merged

    def _validate_overlay(self, paths) -> None:
        """Pregunta contra qué base comprobar unos overlays y los comprueba.

        La base se pregunta **una vez** para todo lo seleccionado: un
        proyecto tiene varios overlays de la misma placa, y contestar lo
        mismo una vez por fichero no es elegir, es un peaje. El fichero no
        declara nada -no se anota su procedencia en un comentario-, así que
        esta pregunta es la única fuente: o un `.dts`/`.dtsi` del disco, o
        una entrada del catálogo de la base de datos.
        """
        if isinstance(paths, str):
            paths = [paths]
        if not paths:
            return

        nombres = ", ".join(Path(path).name for path in paths)
        chosen = BaseChoiceDialog(
            nombres, self._base_candidates(), self
        ).choose()
        if chosen is None:
            return
        self.overlay_panel.overlay_list.validate(paths, chosen)

    def _base_candidates(self) -> List[Tuple[str, str]]:
        """Bases que se pueden elegir: (clave, cómo se enseña).

        Los device tree completos que hay abiertos (`open`), los `.dts`/
        `.dtsi` de la carpeta del proyecto (`local`) y el catálogo entero de
        la base de datos (`SoC`, `board`). El prefijo no es decoración: la
        misma placa puede estar en las tres, y de dónde sale la que se elige
        cambia lo que se comprueba —el documento abierto puede tener cambios
        sin guardar que el fichero del disco no tiene—. Un overlay no entra:
        la base de un overlay es un árbol completo. Lo que no esté en
        ninguna de las tres se elige a mano con «From PC…», que es la salida
        para un fichero de cualquier otro sitio.
        """
        candidates: List[Tuple[str, str]] = []
        seen = set()

        def add(key: str, label: str) -> None:
            if key and key not in seen:
                seen.add(key)
                candidates.append((key, label))

        for document in self.editor_tab.device_tree_documents():
            add(
                document.source_key or str(document.disk_path or ""),
                self.tr("open · {name}").format(name=document.title),
            )

        folder = self.explorer_panel.current_root()
        if folder.is_dir():
            for item in sorted(folder.iterdir()):
                if item.suffix.lower() in (".dts", ".dtsi"):
                    add(
                        str(item),
                        self.tr("local · {name}").format(name=item.name),
                    )

        for entry in self.socs:
            add(entry.file_path, self.tr("SoC · {name}").format(name=entry.label))
        for entry in self.boards:
            add(entry.file_path, self.tr("board · {name}").format(name=entry.label))
        return candidates

    def _save_generated_overlay(self, source: str, target: str = "") -> None:
        """Escribe el overlay recién generado en la carpeta del proyecto.

        Sin diálogo y sin abrirlo en el editor: para ver lo que se iba a
        escribir ya estaba el preview, donde además se podía corregir. Lo que
        queda por hacer aquí es dejar el fichero puesto y decir dónde — el
        panel de carpetas lo enseña en cuanto se refresca.
        """
        # La carpeta del panel, no la de arranque: es la que el usuario
        # tiene abierta y llama «su proyecto», y «Archivo → Abrir carpeta…»
        # la cambia.
        folder = self.explorer_panel.current_root()
        destination = folder / self._next_overlay_name(folder, target)
        try:
            destination.write_text(source, encoding="utf-8")
        except OSError as error:
            QMessageBox.warning(
                self,
                self.tr("Create overlay file"),
                self.tr("{path} could not be written: {reason}").format(
                    path=destination, reason=error.strerror or error
                ),
            )
            return

        # El panel de carpetas no hay que refrescarlo (su `QFileSystemModel`
        # vigila el disco), pero el listado de overlays sí: lo suyo es una
        # lectura de la carpeta, no un modelo vivo.
        self.overlay_panel.set_library(folder, self._overlay_base)
        self.overlay_panel.overlay_list.refresh()
        self._set_status(
            self.tr("Overlay saved to {path}").format(path=destination)
        )

    @staticmethod
    def _next_overlay_name(folder: Path, target: str = "") -> str:
        """Nombre para el overlay nuevo, sin pisar ninguno que ya esté en disco.

        Lleva dentro a qué nodo apunta —`i2c0_layer.dtso`—, que es lo único
        que distingue un overlay de otro en una carpeta con varios: con
        `overlay-1`, `overlay-2`… hay que abrirlos todos para saber cuál es
        cuál. Se limpia lo que no sea un nombre de fichero razonable (una
        ruta trae `/`, y un nombre de nodo puede traer `@`), y si el nombre
        ya está cogido se numera a partir del segundo.
        """
        stem = re.sub(r"[^A-Za-z0-9_.-]", "_", target).strip("_") or "overlay"
        candidate = f"{stem}_layer.dtso"
        indice = 1
        while (folder / candidate).exists():
            indice += 1
            candidate = f"{stem}_layer-{indice}.dtso"
        return candidate

    def _open_include(self, include: ResolvedInclude) -> None:
        """Abre en un editor adicional el contenido de una inclusión."""
        if not include.found:
            QMessageBox.warning(
                self,
                messages.title_include_not_found(),
                messages.include_not_found(include.directive.target),
            )
            return

        # Si se resolvió en disco (ruta absoluta, ver `IncludeResolver`), la
        # nueva pestaña conoce su fichero real y "Guardar" escribe ahí
        # directamente, igual que un documento abierto con "Abrir del PC…" —
        # en vez de obligar a "Guardar como…" cada vez para un include propio.
        source_path = Path(include.source.path)
        disk_path = source_path if source_path.is_absolute() else None

        self.editor_tab.open_source(
            title=include.label,
            text=include.source.text,
            source_key=include.source.path,
            disk_path=disk_path,
        )
        self.show_view(TAB_EDITOR)
        self._set_status(
            self.tr("Opened include {path}").format(path=include.source.path)
        )

    def _open_diff(self, title: str, diff: str) -> None:
        """Abre un diff del panel de versiones como una pestaña más.

        En solo lectura y sin fichero asociado: no es de nadie, y guardarlo
        encima del original sería sustituir el device tree por su propio
        diff. El título termina en `.diff`, con lo que el motor semántico
        tampoco lo analiza.

        Volver a pedir el mismo diff sustituye a la pestaña anterior en vez
        de acumular copias con el mismo nombre: recorrer la lista de
        cambios abriendo uno tras otro es justo lo que se hace aquí, y el
        contenido del anterior ya no valdría si mientras tanto se ha
        guardado una versión.
        """
        for index, (label, _tooltip, _modified) in enumerate(
            self.editor_tab.document_labels()
        ):
            if label == title:
                self.editor_tab.close_document(index)
                break

        self.editor_tab.open_source(title=title, text=diff, read_only=True)
        self.show_view(TAB_EDITOR)

    # ------------------------------------------------------------------
    # Barra de estado
    # ------------------------------------------------------------------
    def _set_status(self, message: str) -> None:
        """Escribe un mensaje en la barra de estado."""
        self.status_label.setText(message)

    def _refresh_status_items(self, document=None) -> None:
        """Recompone los indicadores fijos de la franja de abajo.

        Se llama tras cada análisis y al cambiar de idioma, porque son
        textos compuestos: no basta con volver a traducir una constante.
        La rama se pregunta al panel de versiones, que es quien habla con
        git; si no hay repositorio no se enseña nada en vez de un hueco con
        un guion, que solo añadiría ruido.
        """
        rama = self.git_panel.branch_name()
        self.branch_label.set_text(rama)
        self.branch_label.setVisible(bool(rama))

        self._on_diagnostics_changed(*self._diagnostic_counts)

        self._refresh_document_items(document)
        self._refresh_kernel_button()
        self._refresh_cursor_position()

    def _refresh_document_items(self, document=None) -> None:
        """Tipo de fichero y fin de línea del documento que se está editando.

        Sin documento no se enseña ninguno de los dos: un «DTS · UTF-8» con
        el editor vacío describe un fichero que no existe.
        """
        document = document or self.editor_tab.current
        self.language_label.setVisible(document is not None)
        self.newline_button.setVisible(document is not None)
        if document is None:
            return

        self.language_label.set_text(
            "{language} · UTF-8".format(language=file_io.language_of(document.title))
        )
        crlf = document.newline == file_io.CRLF
        self.newline_button.setText("CRLF" if crlf else "LF")
        self.newline_button.setToolTip(
            self.tr(
                "Line endings this file is saved with. Click to switch to {other}."
            ).format(other="LF" if crlf else "CRLF")
        )

    def _toggle_newline(self) -> None:
        """Cambia el fin de línea del documento activo, LF ↔ CRLF."""
        document = self.editor_tab.current
        if document is None or document.read_only:
            return
        document.newline = (
            file_io.LF if document.newline == file_io.CRLF else file_io.CRLF
        )
        # No toca una letra del texto, así que hay que avisar aparte de que
        # el fichero ya no es el que hay en disco.
        self.editor_tab.refresh_modified_state(document)
        self._refresh_document_items(document)

    def _refresh_kernel_button(self) -> None:
        """Escribe en la franja contra qué kernel se está comprobando."""
        objetivo = self.service.kernel_target
        self.kernel_button.setText(
            self.tr("Kernel: {version}").format(version=objetivo)
            if objetivo
            else self.tr("Kernel: any")
        )
        self.kernel_button.setToolTip(
            self.tr(
                "Kernel release this device tree targets. With one chosen, a "
                "compatible whose binding is newer is reported as a warning."
            )
        )

    def _choose_kernel_target(self) -> None:
        """Pregunta contra qué release del kernel se está trabajando.

        La lista sale de la base (`schemas.since`), no de una tabla escrita
        a mano: dice exactamente hasta dónde se puede comprobar.
        """
        releases = self.service.kernel_releases()
        if not releases:
            self._set_status(
                self.tr("The database carries no kernel versions for the bindings")
            )
            return

        ninguno = self.tr("Any (do not check)")
        opciones = [ninguno] + releases
        actual = self.service.kernel_target
        indice = opciones.index(actual) if actual in opciones else 0
        elegido, aceptado = QInputDialog.getItem(
            self,
            self.tr("Target kernel"),
            self.tr("Check the device tree against this Linux release:"),
            opciones,
            indice,
            False,
        )
        if not aceptado:
            return

        self.service.kernel_target = None if elegido == ninguno else elegido
        self._settings.setValue(SETTING_KERNEL, self.service.kernel_target or "")
        self._settings.sync()
        self._refresh_kernel_button()
        # Cambiar el objetivo cambia lo que hay que avisar: se vuelve a
        # analizar en vez de dejar en pantalla los avisos del anterior.
        self.editor_tab.analyze()

    def _on_diagnostics_changed(self, errors: int, warnings: int, info: int) -> None:
        """Refleja en la franja el mismo recuento que enseña el panel.

        Lo manda el editor al rehacer la lista, así que los dos números
        salen del mismo sitio y del mismo momento — antes se contaban aquí
        tras el análisis y el pase diferido añadía diagnósticos después, lo
        que dejaba la franja diciendo menos de lo que había abajo.
        """
        self._diagnostic_counts = (errors, warnings, info)
        self.problems_error_label.set_text(str(errors))
        self.problems_label.set_text(str(warnings))

    def _refresh_cursor_position(self) -> None:
        """Línea y columna del cursor, como en cualquier editor.

        Sale del editor activo y no del documento: es lo único de la franja
        que cambia mientras se escribe, y por eso va colgado de la señal de
        posición del cursor y no del análisis.
        """
        posicion = self.editor_tab.cursor_position()
        if posicion is None:
            self.cursor_label.set_text("")
            return
        self._on_cursor_moved(*posicion)

    def _on_cursor_moved(self, line: int, column: int, depth: str) -> None:
        """Refleja la posición del cursor en su hueco de la franja de abajo."""
        texto = self.tr("Ln {line}, Col {column}").format(line=line, column=column)
        self.cursor_label.set_text(f"{texto} · {depth}" if depth else texto)

    def _set_busy(self, busy: bool) -> None:
        """Muestra u oculta el indicador de progreso."""
        self.progress.setVisible(busy)

    def stop_background_work(self) -> None:
        """Detiene los hilos en curso; debe llamarse antes de destruir la ventana."""
        self.generator_tab.stop_workers()
        self.visualizer_tab.stop_workers()
        self.editor_tab.stop_workers()

    def closeEvent(self, event) -> None:
        """Pregunta por cambios sin guardar y detiene los hilos antes de cerrar.

        Cerrar la ventana descarta de golpe todo lo que hubiera abierto en el
        editor — la misma pérdida de trabajo que cerrar una pestaña sola sin
        avisar, solo que más fácil de disparar sin querer (Alt+F4, la aspa de
        la ventana...), así que pasa por el mismo `confirm_discard_all` que
        usa cerrar una pestaña o cambiar de SoC.
        """
        if not self.editor_tab.confirm_discard_all():
            event.ignore()
            return
        self.stop_background_work()
        super().closeEvent(event)
