"""Panel de carpetas, al estilo del explorador de VS Code.

Vive siempre a la izquierda de la ventana principal (ver
`MainWindow._build_explorer_dock`): un `QTreeView` sobre un
`QFileSystemModel` con la carpeta base de la app como raíz. Muestra
cualquier fichero, no solo `.dts`/`.dtsi` — igual que un explorador de
verdad, para poder navegar y abrir lo que haga falta (un `.h` referenciado,
un `Makefile`...); qué tan "device tree" es cada uno lo decide el editor al
abrirlo (`EditorTab.Document.is_device_tree`), no este panel.

Y también crea y borra, con el menú contextual o con la tecla Supr: un
proyecto se organiza en carpetas, y tener que salir a un explorador del
sistema para hacer una carpeta o tirar un `.dtso` de prueba rompía el
trabajo por la mitad. Siempre preguntando, y diciendo cuántos ficheros se
lleva una carpeta por delante: del disco no lo recupera nada desde aquí.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from typing import Dict, Optional

from PySide6.QtCore import QDir, QFileInfo, QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPalette, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QStyleOptionViewItem,
    QFileIconProvider,
    QFileSystemModel,
    QInputDialog,
    QMenu,
    QMessageBox,
    QStyledItemDelegate,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from kernelgrove.gui import style
from kernelgrove.gui.translations import Retranslates
from kernelgrove.gui.widgets import icons
from kernelgrove.gui.widgets.panel_footer import PanelFooter

# Tamaño del icono de fichero, y de la caja que ocupa en la fila — pequeño y
# discreto a propósito, para no competir con el propio nombre en un panel
# lateral estrecho.
_FILE_ICON_SIZE = 13

# Hueco que se reserva a la derecha para la letra de estado de git, y cuánto
# se la separa del borde.
_STATUS_BADGE_WIDTH = 16
_STATUS_BADGE_MARGIN = 6

# Sangrado por nivel. Con 12 px un fichero dentro de una carpeta apenas se
# despegaba de su vecino de fuera, y la flechita de plegar se comía casi
# todo ese hueco: la respuesta a «¿esto está dentro de qué?» había que
# buscarla contando. 18 px es lo que usa el explorador de VS Code, y con la
# guía de abajo se lee de un vistazo.
_INDENT = 18

# Cuánto hay que quedarse quieto sobre una carpeta plegada, con algo
# cogido, para que se abra sola. Es el valor de VS Code: menos y se abren
# carpetas de paso al cruzarlas de camino a otra.
_AUTO_EXPAND_MS = 500

# Carpetas que no se enseñan aunque el filtro incluya lo oculto. `.git` es
# la única por ahora, y por el mismo motivo por el que la esconde cualquier
# explorador: son miles de ficheros que no se editan nunca, y desplegarla
# por accidente llena el panel. El resto de lo oculto (`.gitignore`,
# `.vscode`, `.config`…) sí sale, que es contenido del proyecto.
_HIDDEN_NAMES = frozenset({".git"})

# Con qué letra se enseña cada estado. Son las de VS Code, no las de
# `git status --porcelain`, porque son las que la gente ya ha visto: lo que
# git llama `?` (sin seguimiento) se enseña como **U** de *untracked*, y lo
# que git llama `U` (sin fusionar) como **C** de conflicto. Los demás
# coinciden: M, A, D, R.
_STATUS_LETTERS = {"?": "U", "U": "C"}


class _ExplorerIconProvider(QFileIconProvider):
    """Un icono de documento discreto y propio para los ficheros.

    De las carpetas no dice nada: el suyo es el galón de plegado, y ese
    depende de si está abierta o cerrada, que es algo que un proveedor de
    iconos no puede saber. Lo pone el delegado (`_GitStatusDelegate`), que
    sí ve la vista.
    """

    def __init__(self) -> None:
        """Construye una vez el icono de fichero, común a toda la sesión."""
        super().__init__()
        self._file_icon = icons.document_icon(_FILE_ICON_SIZE, style.MUTED_TEXT_COLOR)

    def icon(self, *args, **kwargs) -> QIcon:  # noqa: D102 - override de Qt
        info = args[0] if args else None
        if isinstance(info, QFileInfo) and not info.isDir():
            return self._file_icon
        return QIcon()


class _GitStatusDelegate(QStyledItemDelegate):
    """Pinta el estado de git de cada fichero, como el explorador de VS Code.

    Dos marcas por fila y las dos del mismo color: el **nombre teñido** y
    una **letra a la derecha** (`M`, `U`, `A`, `D`, `C`). El color se lee en
    diagonal y la letra dice cuál de los estados es sin tener que
    recordarse la paleta; VS Code pone las dos por la misma razón.

    La letra va en un delegado y no pegada al nombre del fichero porque
    este panel se estrecha hasta cero (`MainWindow._allow_narrow`): pegada
    al nombre, es lo primero que se come el recorte con puntos suspensivos,
    justo cuando el panel es demasiado estrecho para leer los nombres y la
    letra es lo único que queda legible.

    Los estados salen del panel de control de versiones, que es quien habla
    con git; aquí solo se pintan.
    """

    def __init__(self, parent=None):
        """Sin estados de entrada: los pone `set_status`."""
        super().__init__(parent)
        self._status: Dict[str, str] = {}
        self._dirty_folders: set = set()
        # Los dos galones de plegado, dibujados una vez: el delegado los
        # pide en cada repintado de cada fila visible.
        self.refresh_icons()

    def refresh_icons(self) -> None:
        """Rehornea los galones con el color de la piel activa."""
        self._chevrons = {
            estado: icons.chevron_icon(
                _FILE_ICON_SIZE, style.MUTED_TEXT_COLOR, expanded=estado
            )
            for estado in (False, True)
        }

    def set_status(self, status: Dict[str, str]) -> None:
        """Fija el estado de cada ruta absoluta, y qué carpetas lo heredan.

        Las carpetas se tiñen también —sin letra, que sería mentira: la
        carpeta no está modificada, lo está algo de dentro—. Sin esto, un
        proyecto que guarda sus overlays en `overlays/` no enseña nada hasta
        que se despliega la carpeta, que es justo lo que había que evitar.
        """
        if status == self._status:
            # Mismo estado que ya está pintado: recalcular las carpetas es
            # un `Path(...).parents` por fichero tocado, y con un renombrado
            # masivo en el árbol son miles de rutas construidas para llegar
            # exactamente al mismo conjunto.
            return
        self._status = status
        carpetas = set()
        for ruta in status:
            carpetas.update(str(padre) for padre in Path(ruta).parents)
        self._dirty_folders = carpetas

    def _status_for(self, index: QModelIndex) -> Optional[str]:
        """Estado del fichero de esa fila, si git dice algo de él."""
        return self._status.get(self._path_of(index) or "")

    def _path_of(self, index: QModelIndex) -> Optional[str]:
        """Ruta absoluta de la fila, si el modelo es de ficheros."""
        model = index.model()
        return model.filePath(index) if hasattr(model, "filePath") else None

    def _color_for(self, index: QModelIndex) -> Optional[QColor]:
        """Color con el que se tiñe la fila: el suyo, o el de lo que contiene."""
        code = self._status_for(index)
        if code is not None:
            return QColor(
                style.GIT_STATUS_COLORS.get(code, style.GIT_STATUS_DEFAULT_COLOR)
            )
        ruta = self._path_of(index)
        if ruta and ruta in self._dirty_folders:
            return QColor(style.GIT_STATUS_COLORS.get("M"))
        return None

    def initStyleOption(self, option, index) -> None:  # noqa: N802 - override
        """Pone el galón de la carpeta y tiñe el nombre con su estado.

        El galón va aquí y no en el proveedor de iconos porque depende de
        si la carpeta está desplegada, que es de la vista. Y va en el hueco
        del icono, que es lo que alinea el nombre de una carpeta con el de
        un fichero: sin icono, el nombre se subía al sitio del icono y
        quedaba un paso de sangrado por delante del resto.
        """
        super().initStyleOption(option, index)
        vista = self.parent()
        model = index.model()
        if hasattr(model, "isDir") and model.isDir(index):
            option.icon = self._chevrons[vista.isExpanded(index)]
            option.features |= QStyleOptionViewItem.HasDecoration
        color = self._color_for(index)
        if color is None:
            return
        for group in (QPalette.Active, QPalette.Inactive):
            option.palette.setColor(group, QPalette.Text, color)
            option.palette.setColor(group, QPalette.HighlightedText, color)

    def paint(self, painter, option, index) -> None:
        """Dibuja la fila y, pegada al borde derecho, la letra del estado."""
        code = self._status_for(index)
        if code is None:
            super().paint(painter, option, index)
            return

        # Se le quita a la fila el hueco de la letra antes de pintarla, o el
        # nombre se dibuja por debajo y quedan superpuestos.
        hueco = option.rect.adjusted(0, 0, -_STATUS_BADGE_WIDTH, 0)
        recortada = QStyleOptionViewItem(option)
        recortada.rect = hueco
        super().paint(painter, recortada, index)

        painter.save()
        painter.setPen(
            QColor(
                style.GIT_STATUS_COLORS.get(code, style.GIT_STATUS_DEFAULT_COLOR)
            )
        )
        painter.drawText(
            option.rect.adjusted(0, 0, -_STATUS_BADGE_MARGIN, 0),
            Qt.AlignRight | Qt.AlignVCenter,
            _STATUS_LETTERS.get(code, code),
        )
        painter.restore()


class _IndentGuideTree(QTreeView):
    """El árbol, con una línea vertical por nivel de anidamiento.

    Es lo que hace visible de qué carpeta cuelga cada fichero sin tener que
    contar píxeles, y es lo mismo que dibuja VS Code (`tree.indentGuides`).
    Va aquí y no en el delegado porque el sangrado no es parte de la celda:
    en un `QTreeView` la columna 0 empieza **después** de él, y lo único que
    pinta esa banda es `drawBranches`.

    Y es donde se sueltan los ficheros que se arrastran: la vista es la
    única que sabe dónde cayó el ratón. Mover en el disco no lo hace ella
    —eso es del panel, que es quien avisa de que una ruta ha cambiado—, así
    que lo único que hace es decir qué se soltó y sobre qué fila.
    """

    # Rutas soltadas y fila sobre la que cayeron. La carpeta de destino la
    # resuelve el panel con el mismo `_folder_of` del menú contextual: la
    # regla de «sobre un fichero, a su lado» ya está escrita ahí.
    filesDropped = Signal(list, QModelIndex)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - override de Qt
        """Solo se acepta lo que sale de este mismo árbol.

        Nada de arrastrar desde el gestor de ficheros del sistema: eso sería
        copiar cosas al proyecto sin decirlo, que es otra operación y no la
        que se ha pedido.
        """
        if event.source() is self:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - override de Qt
        """Deja que Qt pinte el indicador, pero decide la aceptación aquí.

        Qt la decidiría por las banderas del modelo, y ahí solo una carpeta
        admite soltar; sobre un fichero hay que poder soltar también, que
        significa «en su carpeta» —lo mismo que ya hace el menú contextual y
        lo que hace cualquier explorador.
        """
        super().dragMoveEvent(event)
        if event.source() is self:
            event.setDropAction(Qt.MoveAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 - override de Qt
        """Anuncia lo soltado y **no** llama a `super`.

        Con el modelo escribible, `QFileSystemModel` movería el fichero él
        solo en su `dropMimeData` — y sin decirlo: la ruta cambiaría sin que
        nadie reapuntase la pestaña que lo tuviera abierto, ni la caché de
        bases, ni las listas de overlays. Mover es renombrar, y aquí se hace
        por donde ya se renombra.
        """
        if event.source() is not self:
            event.ignore()
            return
        rutas = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if rutas:
            self.filesDropped.emit(
                rutas, self.indexAt(event.position().toPoint())
            )
        event.acceptProposedAction()

    def drawBranches(self, painter, rect, index) -> None:  # noqa: N802 - de Qt
        """Solo las guías: la flecha de plegado ya no se dibuja aquí.

        Sin `super()`, a propósito. Qt pinta su flecha en el último paso de
        esta banda, que queda un sangrado entero a la izquierda del nombre
        y se lee como una columna aparte; ahora el galón es el icono de la
        fila (`_GitStatusDelegate.initStyleOption`) y esta banda es solo
        sangrado y guías.
        """
        painter.save()
        pluma = QPen(QColor(style.EXPLORER_INDENT_GUIDE))
        pluma.setWidth(1)
        painter.setPen(pluma)
        paso = self.indentation()
        # Una guía por cada **ancestro**, a media altura de su paso: es lo
        # que dice de qué carpeta cuelga la fila sin contar píxeles.
        raiz = self.rootIndex()
        padre = index.parent()
        x = rect.left() + paso // 2
        while padre.isValid() and padre != raiz:
            painter.drawLine(x, rect.top(), x, rect.bottom())
            x += paso
            padre = padre.parent()
        painter.restore()


class FileExplorerPanel(Retranslates, QWidget):
    """Árbol de carpetas completo, con un clic para abrir un fichero."""

    fileActivated = Signal(str)
    # «Ver en el grafo»: el panel no sabe qué es un grafo, solo pide que se
    # abra. Lo escucha `MainWindow`, que es quien tiene las vistas.
    graphRequested = Signal()
    # Un fichero ha cambiado de nombre en el disco: ruta vieja y nueva. La
    # ventana lo usa para que la pestaña que lo tenga abierto siga apuntando
    # al fichero de verdad — si no, «Guardar» resucitaría el nombre viejo.
    fileRenamed = Signal(str, str)

    def __init__(self, root: Path, parent=None):
        """Monta el árbol y lo enraíza en `root`."""
        super().__init__(parent)

        self._model = QFileSystemModel(self)
        # Guardado en un atributo, no pasado y olvidado: `setIconProvider`
        # no se queda con la propiedad del objeto.
        self._icon_provider = _ExplorerIconProvider()
        self._model.setIconProvider(self._icon_provider)
        # Con `Hidden`: un proyecto de device trees tiene `.git`, `.gitignore`
        # y a menudo un `.vscode` o un `.obsidian`, y un explorador que los
        # esconde obliga a salir a un gestor de ficheros para verlos. `.` y
        # `..` sí se quitan — son navegación, no contenido, y el árbol ya
        # navega solo.
        self._model.setFilter(
            QDir.AllDirs | QDir.Files | QDir.Hidden | QDir.NoDotAndDotDot
        )

        # Se esconden filas en vez de filtrar con un proxy: `QFileSystemModel`
        # no sabe excluir una carpeta por nombre, y un `QSortFilterProxyModel`
        # obligaría a mapear índices en la docena de sitios que hablan con el
        # modelo. `directoryLoaded` llega por cada carpeta que se despliega,
        # que es exactamente cuando hay filas nuevas que esconder.
        self._model.directoryLoaded.connect(self._hide_ignored)

        self.tree = _IndentGuideTree()
        self.tree.setObjectName("fileExplorerTree")
        self.tree.setModel(self._model)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(_INDENT)
        # Sin decoración de raíz: esa banda solo existía para la flecha, y
        # la flecha se ha mudado al hueco del icono. Dejarla habría sido un
        # sangrado entero de nada delante de todo lo del primer nivel.
        self.tree.setRootIsDecorated(False)
        # Selección múltiple con Ctrl y con Mayús, como en cualquier
        # explorador: borrar seis ficheros de prueba es una operación, no
        # seis con su pregunta cada una.
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # Arrastrar mueve, como en cualquier explorador: organizar un
        # proyecto en carpetas es tirar de un fichero, no abrir un menú.
        # `setReadOnly(False)` es lo único que hace falta del modelo —es lo
        # que le pone a las filas las banderas de arrastrar y soltar—; el
        # movimiento en el disco no se lo deja a él (ver `dropEvent`), y
        # editar el nombre en la fila sigue cerrado por `NoEditTriggers`.
        self._model.setReadOnly(False)
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDrop)
        self.tree.setDefaultDropAction(Qt.MoveAction)
        # Una carpeta plegada se abre al pasar por encima con algo cogido,
        # que es lo que permite soltar dentro de algo que no está a la
        # vista sin tener que desplegarlo antes y volver a empezar.
        self.tree.setAutoExpandDelay(_AUTO_EXPAND_MS)
        self.tree.filesDropped.connect(self._move_paths)
        self.tree.setIconSize(QSize(_FILE_ICON_SIZE, _FILE_ICON_SIZE))
        self.tree.setUniformRowHeights(True)
        # Sin animación de plegado: a cambio de un efecto vistoso, cada clic
        # tarda su duración en surtir efecto — con carpetas grandes (la
        # propia `kernel/`, miles de entradas) eso se notaba como si el
        # panel fuera lento en vez de responder al instante.
        self.tree.setAnimated(False)
        self.tree.setFrameShape(QTreeView.NoFrame)
        # Sin edición: un doble clic es "abrir", no "renombrar" — a
        # diferencia de un explorador de ficheros completo.
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # Solo el nombre; tamaño/tipo/fecha son ruido en un panel lateral
        # estrecho, y VS Code tampoco los muestra en su explorador.
        for column in range(1, self._model.columnCount()):
            self.tree.hideColumn(column)
        # Un solo clic decide: sobre una carpeta pliega/despliega -en
        # cualquier punto de la fila, no solo en la estrecha flechita
        # nativa, y así no depende de un doble clic cuyo intervalo varía de
        # un sistema a otro-; sobre un fichero, lo abre directamente en el
        # editor, sin paso intermedio.
        # El estado de git de cada fichero, con el mismo criterio que VS
        # Code: el color dice qué le pasa y la letra dice cuál es.
        self._git_delegate = _GitStatusDelegate(self.tree)
        self.tree.setItemDelegateForColumn(0, self._git_delegate)

        self.tree.clicked.connect(self._on_clicked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        # Supr borra lo seleccionado, que es lo que hace en cualquier
        # explorador. Acotado al árbol (`WidgetShortcut`): en el editor esa
        # misma tecla borra un carácter.
        borrar = QShortcut(QKeySequence.Delete, self.tree)
        borrar.setContext(Qt.WidgetShortcut)
        borrar.activated.connect(self._delete_selection)
        # F2 renombra, que es lo que hace en cualquier explorador. Acotado
        # al árbol por la misma razón que Supr.
        renombrar = QShortcut(QKeySequence(Qt.Key_F2), self.tree)
        renombrar.setContext(Qt.WidgetShortcut)
        renombrar.activated.connect(self._rename_selection)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self._build_summary())

        self.set_root(root)

    def refresh_icons(self) -> None:
        """Rehace los iconos horneados al cambiar de piel.

        Lo encuentra el recorrido de `MainWindow._repaint_theme`. Son el
        documento de los ficheros y los dos galones de las carpetas: se
        dibujan una vez con el color de la piel activa, así que sin esto se
        quedan del color de la anterior.
        """
        self._icon_provider = _ExplorerIconProvider()
        self._model.setIconProvider(self._icon_provider)
        self._git_delegate.refresh_icons()
        self.tree.viewport().update()

    def set_git_status(self, status: Dict[str, str]) -> None:
        """Colorea el árbol con lo que git dice de cada fichero.

        Lo llama la ventana tras cada análisis y al cambiar de carpeta, con
        lo que le da el panel de control de versiones. Repintar es barato
        —solo lo visible— y evita tener que vigilar el disco desde aquí.
        """
        self._git_delegate.set_status(status)
        self.tree.viewport().update()

    def _build_summary(self) -> QWidget:
        """Pie del panel: por dónde se salta al grafo de nodos.

        Es lo único que se hace desde este panel aparte de abrir ficheros,
        y por eso está aquí y no en una barra propia. El pie llevaba antes
        el destino del documento y la versión de `dtc`; se fueron porque al
        estrechar el panel se descolocaban (ver `widgets/panel_footer.py`).
        """
        self.footer = PanelFooter()
        self.footer.clicked.connect(self.graphRequested)
        self.graph_button = self.footer.button
        return self.footer

    def set_root(self, root: Path) -> None:
        """Cambia la carpeta raíz mostrada en el árbol.

        La usa «Archivo → Abrir carpeta…» además del constructor: la raíz de
        partida (el directorio de la aplicación) rara vez es donde el usuario
        tiene sus device trees, y empaquetada es directamente el directorio
        del ejecutable.
        """
        self.root = root
        root_index = self._model.setRootPath(str(root))
        self.tree.setRootIndex(root_index)

    def current_root(self) -> Path:
        """Carpeta que se está mostrando ahora mismo."""
        return self.root

    def _hide_ignored(self, path: str) -> None:
        """Esconde de la carpeta recién cargada lo que no se enseña.

        Llega una vez por carpeta desplegada, que es cuando aparecen filas
        nuevas. `setRowHidden` es de la vista, no del modelo, así que nada
        de lo que habla con el modelo se entera —ni el estado de git, ni el
        menú contextual—, que es justo lo que se quería evitar de un proxy.
        """
        padre = self._model.index(path)
        for fila in range(self._model.rowCount(padre)):
            nombre = self._model.fileName(self._model.index(fila, 0, padre))
            if nombre in _HIDDEN_NAMES:
                self.tree.setRowHidden(fila, padre, True)

    def _on_clicked(self, index: QModelIndex) -> None:
        """Carpeta: pliega/despliega. Fichero: lo abre en el editor.

        Con Ctrl o Mayús pulsados no se hace ninguna de las dos: ahí el
        clic está construyendo una selección (borrar varios ficheros de una
        vez), y abrir uno o plegar una carpeta de paso sería un efecto que
        nadie ha pedido.
        """
        if QApplication.keyboardModifiers() & (
            Qt.ControlModifier | Qt.ShiftModifier
        ):
            return
        if self._model.isDir(index):
            self.tree.setExpanded(index, not self.tree.isExpanded(index))
            return
        self.fileActivated.emit(self._model.filePath(index))

    # ------------------------------------------------------------------
    # Crear y borrar
    # ------------------------------------------------------------------
    def _on_context_menu(self, position) -> None:
        """Menú de crear/borrar sobre la fila pulsada, o sobre la raíz."""
        index = self.tree.indexAt(position)
        target = self._folder_of(index)

        menu = QMenu(self)
        menu.addAction(self.tr("New file…"), lambda: self._create(target, False))
        menu.addAction(self.tr("New folder…"), lambda: self._create(target, True))
        # Borrar actúa sobre **la selección** si la fila pulsada forma parte
        # de ella, y solo sobre esa fila si no: es lo que hace cualquier
        # explorador, y evita que un clic derecho descuidado tire por la
        # borda seis ficheros que estaban marcados para otra cosa.
        rutas = self._selected_paths()
        if index.isValid():
            propia = Path(self._model.filePath(index))
            if propia not in rutas:
                rutas = [propia]
            menu.addSeparator()
            # Renombrar es de uno en uno: un nombre nuevo para seis ficheros
            # no existe, y preguntarlo seis veces seguidas no es renombrar
            # una selección, es repetir la acción.
            menu.addAction(
                self.tr("Rename…"), lambda ruta=propia: self._rename(ruta)
            )
            menu.addAction(
                self.tr("Delete {count} items").format(count=len(rutas))
                if len(rutas) > 1
                else self.tr("Delete"),
                lambda seleccion=rutas: self._delete_paths(seleccion),
            )
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _selected_paths(self) -> list:
        """Rutas de lo marcado en el árbol, sin repetir y en orden."""
        vistas = []
        for index in self.tree.selectionModel().selectedRows():
            ruta = Path(self._model.filePath(index))
            if ruta not in vistas:
                vistas.append(ruta)
        return vistas

    def _folder_of(self, index: QModelIndex) -> Path:
        """Carpeta en la que crear algo, según dónde se haya pulsado.

        Sobre una carpeta, dentro de ella; sobre un fichero, al lado suyo;
        fuera de todo, en la raíz que se está enseñando.
        """
        if not index.isValid():
            return self.root
        path = Path(self._model.filePath(index))
        return path if self._model.isDir(index) else path.parent

    def _create(self, folder: Path, as_folder: bool) -> None:
        """Pide un nombre y crea el fichero o la carpeta dentro de `folder`."""
        title = self.tr("New folder") if as_folder else self.tr("New file")
        name, ok = QInputDialog.getText(self, title, self.tr("Name:"))
        name = name.strip()
        if not ok or not name:
            return

        destination = folder / name
        if destination.exists():
            QMessageBox.warning(
                self,
                title,
                self.tr("{name} already exists.").format(name=name),
            )
            return
        try:
            if as_folder:
                destination.mkdir(parents=True)
            else:
                # `parents` también aquí: escribir «sub/fichero.dts» es una
                # forma natural de crear la carpeta de paso.
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.touch()
        except OSError as error:
            QMessageBox.warning(
                self,
                title,
                self.tr("{name} could not be created: {reason}").format(
                    name=name, reason=error.strerror or error
                ),
            )

    def _rename_selection(self) -> None:
        """Renombra lo primero que esté seleccionado (tecla F2)."""
        rutas = self._selected_paths()
        if rutas:
            self._rename(rutas[0])

    def _rename(self, path: Path) -> None:
        """Pide el nombre nuevo y renombra en el disco.

        `Path.rename` y no `QFileSystemModel.setData`: el modelo ya vigila
        el disco, así que el árbol enseña el cambio sin pedirle nada, igual
        que al crear y al borrar.

        No se pisa nada que ya exista: `rename` sobrescribe en silencio en
        POSIX, y perder un fichero por escribir un nombre que ya estaba no
        es un renombrado, es un borrado sin preguntar.
        """
        title = self.tr("Rename")
        name, ok = QInputDialog.getText(
            self, title, self.tr("New name:"), text=path.name
        )
        name = name.strip()
        if not ok or not name or name == path.name:
            return

        destination = path.parent / name
        if destination.exists():
            QMessageBox.warning(
                self,
                title,
                self.tr("{name} already exists.").format(name=name),
            )
            return
        try:
            path.rename(destination)
        except OSError as error:
            QMessageBox.warning(
                self,
                title,
                self.tr("{name} could not be renamed: {reason}").format(
                    name=path.name, reason=error.strerror or error
                ),
            )
            return
        self.fileRenamed.emit(str(path), str(destination))

    def _move_paths(self, paths, index: QModelIndex) -> None:
        """Mueve a una carpeta lo que se haya soltado sobre ella.

        Mover es renombrar con otra carpeta, así que sale por la misma
        señal (`fileRenamed`) y hereda lo que ya cuelga de ella: la pestaña
        que tuviera el fichero abierto deja de apuntar al sitio viejo, y con
        ella la caché de bases y las listas de overlays.

        `shutil.move` y no `Path.rename` porque una carpeta de proyecto
        puede cruzar un punto de montaje, y ahí `rename` falla con EXDEV
        mientras que `move` copia y borra.

        Lo que no cabe se dice **una vez al final** y no fichero a fichero,
        por lo mismo que el borrado: seis diálogos seguidos es la forma más
        rápida de que nadie los lea. Y no se pregunta antes de mover: el
        arrastre *es* la confirmación, y se deshace arrastrando de vuelta.
        """
        destino = self._folder_of(index)
        problemas = []
        for path in paths:
            if path.parent == destino:
                continue
            # Una carpeta no cabe dentro de sí misma ni de lo que lleva
            # dentro: `move` lo haría desaparecer dentro de su propio
            # subárbol.
            if destino == path or destino.is_relative_to(path):
                problemas.append(
                    self.tr("{name} cannot go inside itself.").format(name=path.name)
                )
                continue
            if (destino / path.name).exists():
                problemas.append(
                    self.tr("{name} already exists there.").format(name=path.name)
                )
                continue
            try:
                shutil.move(str(path), str(destino / path.name))
            except OSError as error:
                problemas.append(
                    self.tr("{name} could not be moved: {reason}").format(
                        name=path.name, reason=error.strerror or error
                    )
                )
                continue
            self.fileRenamed.emit(str(path), str(destino / path.name))

        if problemas:
            QMessageBox.warning(
                self, self.tr("Move"), "\n".join(problemas)
            )

    def _delete_selection(self) -> None:
        """Borra lo que esté seleccionado en el árbol (tecla Supr)."""
        self._delete_paths(self._selected_paths())

    def _delete_paths(self, paths) -> None:
        """Borra varias rutas, con **una** pregunta para todas.

        Una por fichero convierte «he marcado seis y le doy a Supr» en seis
        cuadros de diálogo, que es la forma más rápida de que alguien deje
        de leerlos. Con una sola ruta se cae en `_delete`, que dice el
        nombre y, si es carpeta, cuánto se lleva dentro.
        """
        if not paths:
            return
        if len(paths) == 1:
            self._delete(paths[0])
            return

        nombres = ", ".join(ruta.name for ruta in paths[:6])
        if len(paths) > 6:
            nombres += "…"
        if (
            QMessageBox.question(
                self,
                self.tr("Delete"),
                self.tr(
                    "Delete these {count} items? This cannot be undone.\n\n{names}"
                ).format(count=len(paths), names=nombres),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        for ruta in paths:
            self._remove(ruta)

    def _delete(self, path: Path) -> None:
        """Borra un fichero o una carpeta, tras confirmarlo.

        Una carpeta se lleva por delante todo lo que tenga dentro, así que
        la pregunta dice cuánto es: «borrar `drivers`» y «borrar `drivers` y
        los 143 ficheros que hay dentro» no son la misma decisión.
        """
        if path.is_dir():
            dentro = sum(1 for _ in path.rglob("*") if _.is_file())
            question = (
                self.tr("Delete the folder {name} and the {count} files in it?")
                .format(name=path.name, count=dentro)
                if dentro
                else self.tr("Delete the empty folder {name}?").format(name=path.name)
            )
        else:
            question = self.tr("Delete {name}?").format(name=path.name)

        answer = QMessageBox.question(
            self,
            self.tr("Delete"),
            self.tr("{question} This cannot be undone.").format(question=question),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._remove(path)

    def _remove(self, path: Path) -> None:
        """Borra del disco, sin preguntar. La pregunta la hace quien llama."""
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError as error:
            QMessageBox.warning(
                self,
                self.tr("Delete"),
                self.tr("{name} could not be deleted: {reason}").format(
                    name=path.name, reason=error.strerror or error
                ),
            )
