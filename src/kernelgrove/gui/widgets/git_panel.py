"""Panel de control de versiones, al estilo del "Source Control" de VS Code.

Dos grupos de cambios —**preparados** (lo que entrará en la próxima versión)
y **cambios**—, cada fichero con sus acciones propias: prepararlo, sacarlo de
lo preparado, descartar lo que se le hizo o ver su diff. Debajo, el historial
de versiones, en el que **se ve en cuál se está** y del que se puede hacer
`checkout` de cualquier punto, o al que se puede devolver la rama entera
(«reset»). Estar fuera de una rama es un estado que se dice entero —en la
cabecera del panel y en la franja de estado— y del que se sale con un botón
que solo aparece ahí: es la mitad que faltaba para poder ofrecer `checkout`.

Es la cara visible de `api/git_repo.py` y hereda sus límites: no hay ramas,
remotos, stash ni herramienta de fusión.

Las llamadas a git son síncronas: son operaciones locales de milisegundos y
se disparan al mostrarse el panel o al pulsar algo, nunca al teclear.
ponytail: si `status()` se nota lento en una carpeta enorme, el patrón de
`gui/workers.py` (un `QThread` con señal de vuelta) es la salida.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

from PySide6.QtCore import QRect, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStyledItemDelegate,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from kernelgrove.api import git_repo
from kernelgrove.api.git_repo import FileChange, GitError, GitRepo
from kernelgrove.gui import style, theme
from kernelgrove.gui.translations import Retranslates

# Datos que lleva cada fila: el cambio (o el sha de la versión) con el que
# hablarle a git. La lista solo enseña texto legible.
# Ancho del canal del grafo y tamaño de sus puntos. Lo de Git Graph: una
# línea vertical con un nodo por versión, y el nodo relleno en la versión
# donde se está. Sustituye al «● » de texto que iba delante del mensaje —un
# carácter de la tipografía de la interfaz, del tamaño del texto y por
# tanto enorme para lo que dice—.
_GRAPH_GUTTER = 20
_GRAPH_DOT = 3.0
_GRAPH_DOT_CURRENT = 4.5

# La etiqueta de rama que se dibuja sobre el grafo: hueco a los lados del
# texto, separación con lo siguiente y radio de la esquina.
_BRANCH_PAD = 5
_BRANCH_GAP = 4
_BRANCH_RADIUS = 3

_PAYLOAD_ROLE = Qt.UserRole + 1
# Si la fila es la versión en la que se está (la dibuja el delegado).
_CURRENT_ROLE = Qt.UserRole + 4
# Ramas que apuntan a esa versión, la actual la primera (ver `Version`).
_BRANCHES_ROLE = Qt.UserRole + 5
# En qué rama está HEAD, o vacío fuera de toda rama. Va en la fila porque es
# lo que decide qué etiqueta se rellena, y «esta fila es la del commit
# actual» no basta: estando en un commit suelto, la rama que apunta ahí
# sigue siendo una rama en la que **no** se está.
_ON_BRANCH_ROLE = Qt.UserRole + 6
_SHORT_ROLE = Qt.UserRole + 2
# Marca de fila de grupo ("preparados" / "cambios"), para que actuar sobre
# ella valga por todos sus hijos.
# Columna en la que van los botones de cada fila.
_COLUMN_ACTIONS = 1

_GROUP_ROLE = Qt.UserRole + 3


class _VersionGraphDelegate(QStyledItemDelegate):
    """Dibuja el canal del grafo a la izquierda de cada versión.

    La línea vertical con un nodo por commit, como en Git Graph: es la
    forma con la que se lee un historial, y ocupa menos que el punto de
    texto que había antes. El nodo de la versión en la que se está va
    relleno con el acento y algo más grande; el resto son anillos. Sigue
    sin ser **solo** color —la fila va además en negrita—, porque en este
    panel el color ya significa el estado de un fichero.

    **Y las ramas van aquí, como etiquetas sobre la línea**, igual que en
    Git Graph y en la vista de VS Code: en un historial, «dónde está
    `main`» es una propiedad de un commit y se lee sobre él. Estuvo un rato
    en un desplegable aparte y era el mismo dato dicho en un sitio donde no
    se estaba mirando.
    """

    def paint(self, painter: QPainter, option, index) -> None:
        """Pinta el canal, las etiquetas de rama, y corre el texto detrás."""
        fila = QRect(option.rect)
        ramas = index.data(_BRANCHES_ROLE) or ()
        etiquetas = _branch_chips(option.fontMetrics, ramas)
        ancho = sum(w + _BRANCH_GAP for _, w in etiquetas)
        option.rect = fila.adjusted(_GRAPH_GUTTER + ancho, 0, 0, 0)
        super().paint(painter, option, index)

        x = fila.left() + _GRAPH_GUTTER / 2
        centro = fila.center().y() + 1
        actual = bool(index.data(_CURRENT_ROLE))
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        # La línea llega hasta el borde de la fila salvo en los extremos:
        # el historial no sigue por encima de la primera ni por debajo de
        # la última que se han traído.
        painter.setPen(QPen(QColor(theme.BORDER), 1))
        arriba = centro if index.row() == 0 else fila.top()
        abajo = (
            centro
            if index.row() == index.model().rowCount() - 1
            else fila.bottom()
        )
        painter.drawLine(int(x), int(arriba), int(x), int(abajo))

        radio = _GRAPH_DOT_CURRENT if actual else _GRAPH_DOT
        punto = QRectF(x - radio, centro - radio, radio * 2, radio * 2)
        painter.setPen(QPen(QColor(theme.ACCENT if actual else theme.BORDER), 1.4))
        painter.setBrush(
            QColor(theme.ACCENT) if actual else QColor(theme.PANEL)
        )
        painter.drawEllipse(punto)

        # Las etiquetas, entre el canal y el mensaje. La de la rama en la
        # que se está va rellena y las demás perfiladas: es la misma
        # gramática que el nodo del grafo, y así «estoy aquí» se lee sin
        # depender del color.
        izquierda = fila.left() + _GRAPH_GUTTER
        puesta_en = index.data(_ON_BRANCH_ROLE) or ""
        for nombre, w in etiquetas:
            caja = QRectF(izquierda, centro - 8, w, 16)
            puesta = nombre == puesta_en
            painter.setPen(QPen(QColor(theme.ACCENT), 1))
            painter.setBrush(QColor(theme.ACCENT) if puesta else Qt.NoBrush)
            painter.drawRoundedRect(caja, _BRANCH_RADIUS, _BRANCH_RADIUS)
            painter.setPen(
                QColor(theme.ACCENT_FG if puesta else theme.ACCENT_TEXT)
            )
            painter.drawText(caja, Qt.AlignCenter, nombre)
            izquierda += w + _BRANCH_GAP
        painter.restore()


def _branch_chips(metrics, branches) -> List[Tuple[str, int]]:
    """Cada rama con el ancho que ocupa su etiqueta, en orden."""
    return [
        (nombre, metrics.horizontalAdvance(nombre) + _BRANCH_PAD * 2)
        for nombre in branches
    ]


class GitPanel(Retranslates, QWidget):
    """Cambios, preparación e historial de la carpeta abierta."""

    # Título de la pestaña (termina en `.diff`, que es lo que hace que el
    # editor no intente analizarlo como device tree) y el texto del diff.
    diffRequested = Signal(str, str)
    statusMessage = Signal(str)
    # El estado por fichero que acaba de leerse, para quien lo pinte en
    # otro sitio (el árbol de carpetas). Se emite desde `refresh`, que ya
    # ha pagado el `git status`: pedirlo aparte era pagarlo dos veces.
    statusRefreshed = Signal(dict)

    def __init__(self, parent=None):
        """Monta el panel vacío; hasta `set_root` no hay repositorio."""
        super().__init__(parent)
        self._root: Optional[Path] = None
        self._repo: Optional[GitRepo] = None
        # Ruta (relativa al repositorio) del documento activo en el editor:
        # es lo que filtra el historial cuando se marca la casilla.
        # Hay un refresco aplazado en cola (ver `_schedule_refresh`).
        self._refresh_pending = False
        # Lo último que se pintó -`(status, versions, branch)`-, para no
        # rehacer las listas cuando no ha cambiado nada (ver `refresh`).
        self._painted = None

        self._info = QLabel()
        self._info.setObjectName("gitInfo")
        self._info.setWordWrap(True)

        self._init_button = QPushButton()
        self._init_button.setObjectName("primaryButton")
        self._init_button.clicked.connect(self._start_versioning)

        self._message = QComboBox()
        self._message.setObjectName("gitMessage")
        self._message.setEditable(True)
        self._message.setInsertPolicy(QComboBox.NoInsert)
        # Que el ancho del panel no lo decida el mensaje predefinido más
        # largo: sin esto el desplegable pide 218 px de mínimo y el panel
        # lateral entero no se puede estrechar por debajo de eso.
        self._message.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self._message.setMinimumContentsLength(6)
        self._save_button = QPushButton()
        self._save_button.setObjectName("primaryButton")
        self._save_button.clicked.connect(self._save_version)

        # El mensaje arriba y el botón **debajo**, a todo lo ancho, como en
        # VS Code. En la misma fila no se veía: `MainWindow._allow_narrow`
        # deja a cero el mínimo de todo lo que lleva texto en este dock, y
        # el desplegable con factor de estiramiento se comía el botón
        # entero.
        self._message_row = QWidget()
        message_layout = QVBoxLayout(self._message_row)
        message_layout.setContentsMargins(8, 6, 8, 6)
        message_layout.setSpacing(6)
        message_layout.addWidget(self._message)
        message_layout.addWidget(self._save_button)

        self._changes = QTreeWidget()
        self._changes.setObjectName("gitChanges")
        # Dos columnas: el nombre y, pegados a la derecha, los botones de esa
        # fila. Con una sola, `setItemWidget` taparía el nombre.
        self._changes.setColumnCount(2)
        self._changes.setHeaderHidden(True)
        # El nombre se queda con todo el ancho y los botones con el suyo: sin
        # esto Qt reparte a partes iguales y el fichero sale recortado a la
        # mitad de la fila.
        cabecera = self._changes.header()
        cabecera.setSectionResizeMode(0, QHeaderView.Stretch)
        cabecera.setSectionResizeMode(_COLUMN_ACTIONS, QHeaderView.ResizeToContents)
        self._changes.setIndentation(10)
        self._changes.setUniformRowHeights(True)
        self._changes.setAnimated(False)
        self._changes.setFrameShape(QTreeWidget.NoFrame)
        self._changes.setSelectionMode(QTreeWidget.ExtendedSelection)
        self._changes.setContextMenuPolicy(Qt.CustomContextMenu)
        self._changes.customContextMenuRequested.connect(self._show_changes_menu)
        self._changes.itemClicked.connect(self._show_working_diff)

        self._versions_header = QLabel()
        self._versions_header.setObjectName("gitSectionHeader")
        self._versions = QListWidget()
        self._versions.setObjectName("gitVersions")
        self._versions.setFrameShape(QListWidget.NoFrame)
        self._versions.setItemDelegate(_VersionGraphDelegate(self._versions))
        self._versions.itemClicked.connect(self._show_version_diff)
        self._versions.setContextMenuPolicy(Qt.CustomContextMenu)
        self._versions.customContextMenuRequested.connect(self._show_version_menu)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(_section(None, self._changes))
        splitter.addWidget(_section(self._versions_header, self._versions))
        # Las dos zonas crecen a la vez al agrandar la ventana: con solo la de
        # arriba estirable, el historial se quedaba pegado abajo en una franja
        # de dos filas por muy alto que fuera el panel.
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._info)
        layout.addWidget(self._init_button)
        layout.addWidget(self._message_row)
        layout.addWidget(splitter, 1)

        self.retranslate()

    def _action_button(self, symbol: str, tooltip: str, on_click) -> QToolButton:
        """Un botón de acción de una fila: símbolo, ayuda y qué hace."""
        button = QToolButton()
        button.setObjectName("gitActionButton")
        button.setText(symbol)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setCursor(Qt.PointingHandCursor)
        # `clicked` lleva un `checked` que Qt pasa siempre, y quien llama
        # trae el cambio en un argumento por defecto (`lambda c=change: …`):
        # PySide mira cuántos argumentos acepta el invocable y le mete ese
        # `False` en el primero, así que el botón acababa operando sobre
        # `False` en vez de sobre el fichero. Se traga aquí, en el único
        # sitio por el que pasan los tres botones.
        button.clicked.connect(lambda *_: on_click())
        return button

    def _row_actions(self, change: FileChange, staged: bool) -> QWidget:
        """Los botones que le tocan a **esa** fila, no a la selección.

        Es el gesto de VS Code: cada cambio lleva al lado lo que se puede
        hacer con él, y no hay que seleccionar primero y buscar después una
        barra compartida. Lo que se ofrece depende de en qué grupo está: lo
        preparado solo se puede quitar de la preparación, y lo que no lo
        está se puede preparar o descartar. Descartar no se ofrece sobre lo
        preparado a propósito —para deshacer algo ya preparado se quita
        primero—, así que «descartar» siempre significa lo mismo.
        """
        fila = QWidget()
        fila.setObjectName("gitRowActions")
        caja = QHBoxLayout(fila)
        caja.setContentsMargins(0, 0, 4, 0)
        caja.setSpacing(1)
        if staged:
            acciones = (
                ("−", self.tr("Remove from the next version"), self._unstage_change),
            )
        else:
            acciones = (
                ("↺", self.tr("Discard these changes"), self._discard_change),
                ("+", self.tr("Include in the next version"), self._stage_change),
            )
        for symbol, tooltip, slot in acciones:
            caja.addWidget(
                self._action_button(symbol, tooltip, lambda c=change, f=slot: f(c))
            )
        return fila

    def _stage_change(self, change: FileChange) -> None:
        """Prepara un fichero concreto."""
        self._apply(
            lambda repo, changes: repo.stage([item.path for item in changes]),
            [change],
        )

    def _unstage_change(self, change: FileChange) -> None:
        """Saca un fichero concreto de la preparación."""
        self._apply(
            lambda repo, changes: repo.unstage([item.path for item in changes]),
            [change],
        )

    def _discard_change(self, change: FileChange) -> None:
        """Descarta un fichero concreto, preguntando antes."""
        if not self._confirm_discard([change]):
            return
        self._apply(lambda repo, changes: repo.discard(changes), [change])

    # ------------------------------------------------------------------
    # Entradas desde la ventana
    # ------------------------------------------------------------------
    def set_root(self, root: Union[str, Path]) -> None:
        """Cambia la carpeta versionada (la misma que muestra el explorador)."""
        self._root = Path(root)
        self._repo = git_repo.find_repo(self._root)
        # Otro repositorio: lo pintado no describe a este.
        self._painted = None
        self.refresh()

    def line_changes(
        self, path: Optional[Union[str, Path]], text: str
    ) -> git_repo.LineChanges:
        """Qué líneas de `text` no están preparadas todavía.

        Contra el índice, que es el criterio de VS Code: preparar un cambio
        lo saca del margen del editor, porque a partir de ahí ya está
        descrito en la lista de cambios como «lo que va en la próxima
        versión».

        Vacío si no hay repositorio, si el fichero está fuera de él o si es
        nuevo del todo — en ese último caso marcarlo entero de verde sería
        pintar la pantalla para decir algo que ya dice el panel de cambios.
        """
        inside = self._relative_to_repo(path)
        if self._repo is None or inside is None:
            return git_repo.LineChanges()
        before = self._repo.file_in_index(inside)
        if before is None:
            return git_repo.LineChanges()
        return git_repo.changed_lines(before, text)

    def file_status(self) -> Dict[str, str]:
        """Estado de cada fichero tocado, por su ruta absoluta.

        Lo consume el panel de carpetas para colorear su árbol, que es donde
        se ve el proyecto entero: la lista de cambios de aquí dice *qué* ha
        cambiado, y el árbol dice *dónde* está sin tener que cambiar de
        sección.

        De los dos grupos, gana el que **no** está preparado: si un fichero
        tiene una modificación preparada y otra posterior sin preparar, lo
        que hay ahora en el disco es lo segundo, que es lo que el árbol
        enseña.
        """
        if self._repo is None:
            return {}
        try:
            return self._statuses(self._repo.status())
        except GitError:
            return {}

    def _statuses(self, status) -> Dict[str, str]:
        """Traduce un estado ya leído a «ruta absoluta → letra».

        Aparte de `file_status` porque `refresh` ya tiene el `status` en la
        mano: en un repositorio grande esa llamada cuesta ~200 ms, y volver a
        pedirla para pintar el árbol era pagarla dos veces por lo mismo.
        """
        if self._repo is None:
            return {}
        estados: Dict[str, str] = {}
        for change in (*status.staged, *status.unstaged):
            estados[str(self._repo.root / change.path)] = change.status
        return estados

    def showEvent(self, event) -> None:  # noqa: N802 - override de Qt
        """Relee el estado cada vez que el panel se hace visible.

        Es lo que sustituye a vigilar el disco: se ha guardado un fichero en
        el editor, se cambia a esta sección y lo que se ve ya está al día,
        sin `QFileSystemWatcher` ni temporizador de fondo.
        """
        super().showEvent(event)
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        """Refresca una sola vez aunque el panel se muestre dos veces seguidas.

        Entrar en la sección dispara dos `showEvent`: uno al cambiar de página
        el `QStackedWidget` y otro al volver visible la columna entera (ver
        `MainWindow._on_activity_section_changed`). Cada uno costaba un
        `git status` completo —~200 ms en un repositorio grande, pagado dos
        veces por el mismo cambio de sección—. Se aplaza al siguiente giro
        del bucle de eventos, donde los dos se juntan en uno.
        """
        if self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(0, self._refresh_now)

    def _refresh_now(self) -> None:
        """Ejecuta el refresco aplazado, si el panel sigue a la vista."""
        self._refresh_pending = False
        if self.isVisible():
            self.refresh()

    # ------------------------------------------------------------------
    # Pintado
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Vuelve a leer el repositorio y repinta las dos listas si han cambiado.

        **Releer es barato; repintar no.** Una fila por fichero, y cada una
        con sus dos botones como widgets de verdad (`_row_actions`): con el
        árbol lleno de cambios —un renombrado masivo son cientos— eso son
        más de medio millar de widgets construidos, ~120 ms, y se rehacían
        enteros cada vez que se entraba en la sección aunque no hubiera
        cambiado nada. Como `RepoStatus` y `Version` son `dataclass(frozen)`,
        basta comparar lo leído con lo que ya está pintado.
        """
        if not git_repo.git_available():
            self._discard_painted()
            self._show_notice(
                self.tr(
                    "Git is not installed on this computer, so versions cannot "
                    "be saved. Install it and reopen this panel."
                ),
                can_init=False,
            )
            return

        if self._repo is None:
            self._discard_painted()
            self._show_notice(
                self.tr("This folder is not under version control yet."),
                can_init=self._root is not None and self._root.is_dir(),
            )
            return

        try:
            status = self._repo.status()
            versions = self._repo.versions(limit=style.GIT_VERSION_LIMIT)
            head = self._repo.head()
        except GitError as exc:
            self._discard_painted()
            self._show_notice(str(exc), can_init=False)
            return

        self._set_versioning_visible(True)
        # Se puede guardar aunque no haya nada preparado: entonces se ofrece
        # preparar todo, como hace VS Code.
        self._save_button.setEnabled(not status.is_empty())
        # El árbol de carpetas se tiñe con esto, se repinte o no: es el
        # estado recién leído y a quien lo pinta le sale gratis.
        self.statusRefreshed.emit(self._statuses(status))

        pintado = (status, versions, head)
        if pintado == self._painted:
            return
        self._painted = pintado
        self._changes.clear()
        self._versions.clear()
        self._info.setText(self._summary(versions, head))
        self._fill_changes(status)
        self._fill_versions(versions, head)

    def _discard_painted(self) -> None:
        """Vacía las dos listas y olvida lo pintado (ver `refresh`)."""
        self._painted = None
        self._changes.clear()
        self._versions.clear()

    def branch_name(self) -> str:
        """Dónde está HEAD, para la franja de estado.

        La rama, o «commit suelto» con su sha si se ha hecho `checkout` de
        una versión anterior: ahí no hay rama, y dejar el indicador en
        blanco escondía justo el estado que hay que ver. Sin `try` en quien
        llama: no tener repositorio es un estado normal, no un error (ver
        `api/git_repo.find_repo`).
        """
        if self._repo is None:
            return ""
        try:
            head = self._repo.head()
        except GitError:
            return ""
        if head.detached:
            return self.tr("detached at {sha}").format(sha=head.short)
        return head.branch

    def _summary(
        self, versions: List[git_repo.Version], head: git_repo.HeadState
    ) -> str:
        """Línea de cabecera: dónde se está, y si eso es la punta de la rama.

        Estar en un commit suelto no es un detalle: guardar ahí no mueve
        ninguna rama y la versión nueva se pierde en cuanto se vuelva. Se
        dice entero, no con un sha entre paréntesis.
        """
        if head.detached:
            return self.tr(
                "On version {sha}, not on any branch — anything saved here "
                "is lost when you go back."
            ).format(sha=head.short)
        where = (
            self.tr("branch {branch}").format(branch=head.branch)
            if head.branch
            else ""
        )
        if not versions:
            current = self.tr("No versions saved yet")
        else:
            current = self.tr("Last version {sha}").format(sha=versions[0].short)
        return f"{current} · {where}" if where else current

    def _fill_changes(self, status: git_repo.RepoStatus) -> None:
        """Los dos grupos, con una fila por fichero y su letra en color."""
        if status.is_empty():
            empty = QTreeWidgetItem([self.tr("No changes since the last version")])
            empty.setFlags(Qt.NoItemFlags)
            empty.setForeground(0, QColor(style.FAINT_TEXT_COLOR))
            self._changes.addTopLevelItem(empty)
            return

        for changes, staged in ((status.staged, True), (status.unstaged, False)):
            if not changes:
                continue
            title = (
                self.tr("STAGED CHANGES ({count})")
                if staged
                else self.tr("CHANGES ({count})")
            )
            group = QTreeWidgetItem([title.format(count=len(changes))])
            group.setData(0, _GROUP_ROLE, "staged" if staged else "unstaged")
            group.setForeground(0, QColor(style.MUTED_TEXT_COLOR))
            self._changes.addTopLevelItem(group)
            for change in changes:
                item = QTreeWidgetItem([f"{change.status}   {change.path}", ""])
                item.setData(0, _PAYLOAD_ROLE, change)
                item.setToolTip(0, change.path)
                item.setForeground(
                    0,
                    QColor(
                        style.GIT_STATUS_COLORS.get(
                            change.status, style.GIT_STATUS_DEFAULT_COLOR
                        )
                    ),
                )
                group.addChild(item)
                # El widget se pone **después** de meter la fila en el
                # árbol: `setItemWidget` necesita que el item ya tenga
                # modelo, y antes de `addChild` no lo tiene.
                self._changes.setItemWidget(
                    item, _COLUMN_ACTIONS, self._row_actions(change, staged)
                )
            group.setExpanded(True)

    def _fill_versions(
        self, versions: List[git_repo.Version], head: git_repo.HeadState
    ) -> None:
        """Una fila por versión, con **la actual marcada**.

        Sin numerar. Los «v1, v2…» que había aquí se los inventaba este
        panel contando posiciones, y no coincidían con nada: ni con `git
        log`, ni con lo que ve otra persona que abra el proyecto, ni consigo
        mismos en cuanto se vuelve atrás.

        **Solo el mensaje.** El sha corto iba delante de cada línea y no se
        usa para nada aquí —se pulsa la fila, no se teclea el identificador—
        mientras que el mensaje es lo único que distingue una versión de
        otra de un vistazo, y con el panel estrecho eran siete caracteres
        comiéndose justo eso. Sigue entero en el aviso de la fila y en el
        menú contextual, que es donde se actúa sobre una versión concreta.

        La marca es el nodo del grafo (`_VersionGraphDelegate`) y la fila en
        negrita, no un color: el color en esta lista ya significa otra cosa
        (el estado de un fichero en la lista de arriba), y «dónde estoy»
        tiene que leerse igual con cualquier piel y con cualquier visión del
        color.
        """
        for version in versions:
            actual = version.sha == head.sha
            item = QListWidgetItem(version.message)
            item.setData(_CURRENT_ROLE, actual)
            item.setData(_BRANCHES_ROLE, version.branches)
            item.setData(_ON_BRANCH_ROLE, head.branch)
            item.setData(_PAYLOAD_ROLE, version.sha)
            item.setData(_SHORT_ROLE, version.short)
            detalle = self.tr("{date} · {author} · {sha}").format(
                date=version.date, author=version.author, sha=version.short
            )
            if actual:
                fuente = item.font()
                fuente.setBold(True)
                item.setFont(fuente)
                detalle = self.tr("{detail} · this is where you are").format(
                    detail=detalle
                )
            item.setToolTip(detalle)
            self._versions.addItem(item)

    def _show_notice(self, text: str, can_init: bool) -> None:
        """Deja el panel en "aquí no se puede guardar nada, y por esto"."""
        self._info.setText(text)
        self._set_versioning_visible(False)
        self._init_button.setVisible(can_init)

    def _set_versioning_visible(self, visible: bool) -> None:
        """Enseña u oculta todo lo que solo tiene sentido con repositorio."""
        self._init_button.setVisible(False)
        self._message_row.setVisible(visible)
        self._changes.setVisible(visible)
        self._versions_header.setVisible(visible)
        self._versions.setVisible(visible)

    # ------------------------------------------------------------------
    # Selección y acciones sobre ficheros
    # ------------------------------------------------------------------
    def _selected_changes(self, staged: Optional[bool] = None) -> List[FileChange]:
        """Ficheros sobre los que actuar, sin repetir y en orden.

        Seleccionar la fila de un grupo vale por todos sus ficheros, que es
        lo que hacen los "Stage all"/"Discard all" de VS Code sin necesidad
        de una acción aparte.
        """
        found: List[FileChange] = []
        for item in self._changes.selectedItems():
            children = (
                [item.child(index) for index in range(item.childCount())]
                if item.data(0, _GROUP_ROLE) is not None
                else [item]
            )
            for child in children:
                change = child.data(0, _PAYLOAD_ROLE)
                if not isinstance(change, FileChange) or change in found:
                    continue
                if staged is None or change.staged == staged:
                    found.append(change)
        return found

    def _stage_selection(self) -> None:
        """Mete lo seleccionado en la próxima versión."""
        self._apply(
            lambda repo, changes: repo.stage([change.path for change in changes]),
            self._selected_changes(staged=False),
        )

    def _unstage_selection(self) -> None:
        """Saca lo seleccionado de la próxima versión."""
        self._apply(
            lambda repo, changes: repo.unstage([change.path for change in changes]),
            self._selected_changes(staged=True),
        )

    def _discard_selection(self) -> None:
        """Deshace en el disco lo seleccionado, tras confirmarlo."""
        changes = self._selected_changes(staged=False)
        if not changes or not self._confirm_discard(changes):
            return
        self._apply(lambda repo, selected: repo.discard(selected), changes)

    def _confirm_discard(self, changes: List[FileChange]) -> bool:
        """Pregunta antes de descartar, nombrando lo que se pierde.

        Compartida por el botón de una fila y por la acción sobre la
        selección: nada de esto se recupera, así que la pregunta tiene que
        ser la misma se llegue por donde se llegue.
        """
        names = "\n".join(f"· {change.path}" for change in changes[:10])
        if len(changes) > 10:
            names += "\n…"
        confirmed = QMessageBox.warning(
            self,
            self.tr("Discard changes"),
            self.tr(
                "The changes in these {count} file(s) will be undone. "
                "This cannot be undone — they are not saved in any version:"
                "\n\n{files}"
            ).format(count=len(changes), files=names),
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return confirmed == QMessageBox.Yes

    def _apply(
        self,
        operation: Callable[[GitRepo, List[FileChange]], None],
        changes: List[FileChange],
    ) -> None:
        """Ejecuta una operación sobre unos ficheros y repinta el panel."""
        if self._repo is None or not changes:
            return
        try:
            operation(self._repo, changes)
        except GitError as exc:
            self._report(exc)
        self.refresh()

    def _show_changes_menu(self, position) -> None:
        """Menú de un fichero (o de un grupo entero): las mismas tres cosas."""
        item = self._changes.itemAt(position)
        if item is None or self._repo is None:
            return
        # Un clic derecho fuera de la selección actúa sobre lo que se acaba
        # de señalar, como en cualquier lista; dentro de ella, la respeta.
        if not item.isSelected():
            self._changes.setCurrentItem(item)

        menu = QMenu(self)
        if self._selected_changes(staged=False):
            self._add_action(menu, self.tr("Stage changes"), self._stage_selection)
        if self._selected_changes(staged=True):
            self._add_action(menu, self.tr("Unstage changes"), self._unstage_selection)
        if self._selected_changes(staged=False):
            self._add_action(menu, self.tr("Discard changes"), self._discard_selection)
        if item.data(0, _PAYLOAD_ROLE) is not None:
            self._add_action(
                menu, self.tr("Open changes"), lambda: self._show_working_diff(item)
            )
        if not menu.isEmpty():
            menu.exec(self._changes.viewport().mapToGlobal(position))

    def _add_action(self, menu: QMenu, text: str, slot: Callable[[], None]) -> None:
        """Añade una entrada al menú, con el padre correcto para que viva."""
        action = QAction(text, menu)
        action.triggered.connect(slot)
        menu.addAction(action)

    # ------------------------------------------------------------------
    # Versiones
    # ------------------------------------------------------------------
    def _start_versioning(self) -> None:
        """Empieza a versionar la carpeta abierta (`git init`).

        Solo a petición explícita: hacerlo solo al abrir una carpeta sería
        crear repositorios por sorpresa en sitios donde el usuario no
        quiere ninguno.
        """
        if self._root is None:
            return
        try:
            self._repo = git_repo.init_repo(self._root)
        except GitError as exc:
            self._report(exc)
            return
        self.statusMessage.emit(
            self.tr("Version control started in {folder}").format(folder=self._root)
        )
        self.refresh()

    def _save_version(self) -> None:
        """Guarda una versión con lo preparado, o con todo si no hay nada."""
        if self._repo is None:
            return
        message = self._message.currentText().strip()
        if not message:
            self.statusMessage.emit(
                self.tr("Type a message, or pick one from the list, to save a version")
            )
            self._message.setFocus()
            return
        try:
            if not self._repo.status().staged:
                confirmed = QMessageBox.question(
                    self,
                    self.tr("Commit"),
                    self.tr(
                        "There are no files staged for this version. Do you want "
                        "to include every change and save it anyway?"
                    ),
                    QMessageBox.Yes | QMessageBox.Cancel,
                    QMessageBox.Yes,
                )
                if confirmed != QMessageBox.Yes:
                    return
                self._repo.stage_all()
            self._repo.save_version(message)
        except GitError as exc:
            self._report(exc)
            return
        self._message.setCurrentIndex(-1)
        self._message.setEditText("")
        self.refresh()
        self.statusMessage.emit(self.tr("Version saved"))

    def _show_working_diff(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        """Abre lo que ha cambiado en ese fichero, del lado en que esté."""
        change = item.data(0, _PAYLOAD_ROLE)
        if self._repo is None or not isinstance(change, FileChange):
            return
        try:
            diff = self._repo.working_diff(change.path, staged=change.staged)
        except GitError as exc:
            self._report(exc)
            return
        if not diff.strip():
            self.statusMessage.emit(
                self.tr("Nothing to show for {file}").format(file=change.path)
            )
            return
        side = "staged" if change.staged else "changes"
        self.diffRequested.emit(f"{Path(change.path).name} · {side}.diff", diff)

    def _show_version_diff(self, item: QListWidgetItem) -> None:
        """Abre todo lo que cambió en esa versión respecto de la anterior."""
        sha = item.data(_PAYLOAD_ROLE)
        short = item.data(_SHORT_ROLE)
        if self._repo is None or not isinstance(sha, str):
            return
        try:
            diff = self._repo.version_diff(sha)
        except GitError as exc:
            self._report(exc)
            return
        self.diffRequested.emit(f"{short}.diff", diff)

    def _show_version_menu(self, position) -> None:
        """Menú de una versión: recuperar su contenido, o volver la rama a ella."""
        item = self._versions.itemAt(position)
        if item is None or self._repo is None:
            return
        menu = QMenu(self)
        # Si una rama apunta aquí, ir a **ella** va primero: es lo que se
        # quiere casi siempre —volver a `main`— y es lo único que deja el
        # repositorio dentro de una rama. Ir al commit suelto se ofrece
        # después, que es la otra cosa y no la misma.
        for rama in item.data(_BRANCHES_ROLE) or ():
            self._add_action(
                menu,
                self.tr("Check out {branch}").format(branch=rama),
                lambda _=False, destino=rama: self._checkout_branch(destino),
            )
        self._add_action(
            menu, self.tr("Check out this version"), lambda: self._checkout(item)
        )
        self._add_action(
            menu, self.tr("Start a branch here…"), lambda: self._branch_from(item)
        )
        menu.addSeparator()
        self._add_action(
            menu,
            self.tr("Reset here, keeping the files"),
            lambda: self._reset(item, hard=False),
        )
        self._add_action(
            menu,
            self.tr("Reset here and discard the files"),
            lambda: self._reset(item, hard=True),
        )
        menu.exec(self._versions.viewport().mapToGlobal(position))

    def _checkout_branch(self, branch: str) -> None:
        """Se sitúa en una rama, que es la forma de volver a estar en una.

        Sin preguntar: `checkout` no pierde nada —git se niega solo si
        hubiera cambios sin guardar que se perderían, y entonces lo dice— y
        un «¿seguro?» por cada cambio de rama es el diálogo que se deja de
        leer.
        """
        if self._repo is None:
            return
        try:
            self._repo.checkout(branch)
        except GitError as exc:
            self._report(exc)
            return
        self.statusMessage.emit(self.tr("Now on {branch}").format(branch=branch))
        self.refresh()

    def _branch_from(self, item: QListWidgetItem) -> None:
        """Abre una rama en esa versión y se sitúa en ella.

        Es la salida del callejón: mirar una versión antigua deja fuera de
        toda rama, y lo que se guarde ahí se pierde al volver. Abrir una
        rama en ese punto convierte eso en un sitio donde trabajar.
        """
        sha = item.data(_PAYLOAD_ROLE)
        short = item.data(_SHORT_ROLE)
        if self._repo is None or not isinstance(sha, str):
            return
        nombre, ok = QInputDialog.getText(
            self,
            self.tr("Start a branch"),
            self.tr("Name for the branch starting at {sha}:").format(sha=short),
        )
        nombre = nombre.strip()
        if not ok or not nombre:
            return
        try:
            self._repo.create_branch(nombre, sha)
        except GitError as exc:
            self._report(exc)
            return
        self.statusMessage.emit(self.tr("Now on {branch}").format(branch=nombre))
        self.refresh()

    def _reset(self, item: QListWidgetItem, hard: bool) -> None:
        """Devuelve la rama a esa versión, tirando todo lo posterior.

        Se pregunta siempre, y con dos textos distintos: en `mixed` lo que
        se pierde es la *historia* posterior (los ficheros se quedan como
        cambios sin guardar y se puede rehacer la versión), mientras que en
        `hard` se pierden además los ficheros y eso no lo recupera nada
        desde aquí.
        """
        sha = item.data(_PAYLOAD_ROLE)
        short = item.data(_SHORT_ROLE)
        if self._repo is None or not isinstance(sha, str):
            return
        question = (
            self.tr(
                "The branch will go back to {sha} and every version saved "
                "after it will be lost, along with the files as they are "
                "now. This cannot be undone."
            )
            if hard
            else self.tr(
                "The branch will go back to {sha}. Every version saved after "
                "it is lost, but the files stay as they are now — as "
                "unsaved changes, so you can save them again."
            )
        ).format(sha=short)
        confirmed = QMessageBox.question(
            self,
            self.tr("Reset to this version"),
            question,
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if confirmed != QMessageBox.Yes:
            return
        try:
            self._repo.reset(sha, hard=hard)
        except GitError as exc:
            self._report(exc)
            return
        self.statusMessage.emit(self.tr("Reset to {sha}").format(sha=short))
        self.refresh()

    def _checkout(self, item: QListWidgetItem) -> None:
        """Se sitúa en la versión elegida, sin tocar la historia.

        Se avisa de lo único que sorprende: se queda uno **fuera de la
        rama**. No se pregunta con un «¿seguro?» porque no se pierde nada —
        git se niega solo si hubiera cambios sin guardar que sí se
        perderían—, pero sí se dice antes, porque guardar estando ahí no
        mueve ninguna rama.
        """
        sha = item.data(_PAYLOAD_ROLE)
        short = item.data(_SHORT_ROLE)
        if self._repo is None or not isinstance(sha, str):
            return
        confirmed = QMessageBox.question(
            self,
            self.tr("Check out this version"),
            self.tr(
                "The files go back to how they were in {sha}, and you end up "
                "outside any branch.\n\n"
                "Nothing already saved is lost, and the panel shows a way "
                "back to the branch."
            ).format(sha=short),
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if confirmed != QMessageBox.Yes:
            return
        try:
            self._repo.checkout(sha)
        except GitError as exc:
            self._report(exc)
            return
        self.statusMessage.emit(self.tr("Now on {sha}").format(sha=short))
        self.refresh()

    def _report(self, error: GitError) -> None:
        """Enseña tal cual lo que dijo git, que suele explicar cómo salir.

        En un diálogo y no en la barra de estado: los fallos que llegan aquí
        (identidad sin configurar, un fichero bloqueado) exigen que el
        usuario haga algo, y la barra de estado se lee sola en un rato.
        """
        QMessageBox.warning(self, self.tr("Version control"), str(error))

    # ------------------------------------------------------------------
    # Auxiliares
    # ------------------------------------------------------------------
    def _relative_to_repo(self, path: Optional[Union[str, Path]]) -> Optional[str]:
        """Ruta de `path` dentro del repositorio, o None si está fuera."""
        if path is None or self._repo is None:
            return None
        try:
            inside = Path(path).resolve().relative_to(self._repo.root.resolve())
            return inside.as_posix()
        except ValueError:
            return None

    def retranslate(self) -> None:
        """Vuelve a poner los textos fijos y los mensajes de ejemplo."""
        self._init_button.setText(self.tr("Start version control here"))
        self._save_button.setText(self.tr("Commit"))
        self._versions_header.setText(self.tr("VERSIONS"))

        # Los botones de cada fila llevan su ayuda dentro (`_row_actions`) y
        # se rehacen en cada `refresh`, así que aquí no hay nada que
        # retraducir: basta con volver a listar. Olvidando antes lo pintado,
        # o `refresh` vería el mismo estado y se ahorraría el repintado —que
        # es justo lo que aquí hace falta, porque lo que cambió es el idioma
        # y no el repositorio.
        if self._repo is not None:
            self._painted = None
            self.refresh()

        typed = self._message.currentText()
        self._message.clear()
        self._message.addItems(self._presets())
        self._message.setCurrentIndex(-1)
        self._message.setEditText(typed)
        self._message.lineEdit().setPlaceholderText(self.tr("What changed?"))
        self.refresh()

    def _presets(self) -> List[str]:
        """Mensajes habituales, para no tener que escribir nada.

        Van aquí y no en una constante de módulo porque al importarse el
        módulo todavía no hay `QApplication` y se quedarían congelados en
        inglés (ver `gui/translations.py`).
        """
        return [
            self.tr("Initial version"),
            self.tr("Peripheral added"),
            self.tr("Peripheral removed"),
            self.tr("Peripheral configuration changed"),
            self.tr("Clocks adjusted"),
            self.tr("Pin configuration fixed"),
            self.tr("Work in progress"),
        ]


def _section(
    header: Optional[QLabel], content: QWidget, extra: Optional[QWidget] = None
):
    """Cabecera + contenido en una caja, que es lo que va en el `QSplitter`.

    La zona de cambios va sin cabecera: sus propios grupos («PREPARADOS»,
    «CAMBIOS») ya dicen lo que es, y una tercera etiqueta encima repetía la
    palabra dos veces seguidas.
    """
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    if header is not None:
        layout.addWidget(header)
    if extra is not None:
        layout.addWidget(extra)
    layout.addWidget(content, 1)
    return box
