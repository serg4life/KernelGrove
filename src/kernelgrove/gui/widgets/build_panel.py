"""Sección «BUILD TOOLS»: qué árbol se compila y con qué se compila.

Separada de OVERLAYS a propósito: allí se *escriben* overlays —elegir el
nodo, marcar propiedades, generar el fichero— y aquí se *construye* lo que
haya, que es otra tarea y otro momento. Lo único que comparten es que los
overlays encendidos en aquella lista entran en esta compilación, y por eso
esta sección dice cuántos son en vez de repetir la lista: dos sitios donde
marcar lo mismo es un sitio de más para que se desincronicen.

El panel no compila: pide que se compile (`buildRequested`). Quien sabe
resolver la base, lanzar las comprobaciones y escribir el registro es
`MainWindow`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from kernelgrove.gui import style, theme
from kernelgrove.gui.translations import Retranslates
from kernelgrove.gui.widgets import icons
from kernelgrove.gui.widgets.overlay_list import OVERLAY_SCAN_DEPTH, scan_files

# Lo que se puede compilar como árbol completo. Un `.dtsi` no entra: es un
# fragmento pensado para ser incluido, y compilarlo solo da un árbol sin
# raíz. La lista es «qué se construye», no «qué ficheros hay».
DEVICE_TREE_SUFFIXES = (".dts",)

# Lo que sale de compilar, que es lo que se puede descompilar. Va en su
# propia lista y no mezclado con lo de arriba: la de arriba es «qué se
# construye» y su elección es además la base contra la que se comprueban los
# overlays, así que elegir ahí un binario no querría decir nada.
BLOB_SUFFIXES = (".dtb", ".dtbo")

# Clave del catálogo de una entrada elegida de la base de datos; las de la
# carpeta llevan su ruta del disco.
ROLE_KEY = Qt.UserRole
ROLE_FROM_DB = Qt.UserRole + 1


# La nube, dibujada una vez por color de piel: la piden todas las filas del
# catálogo en cada repintado.
_CLOUDS: dict = {}


def _cloud() -> QIcon:
    """El glifo de «esto viene de la base», en el color de la piel activa."""
    clave = (style.MUTED_TEXT_COLOR, style.ACTION_ICON_SIZE)
    if clave not in _CLOUDS:
        _CLOUDS[clave] = icons.cloud_icon(*reversed(clave))
    return _CLOUDS[clave]


def _file_item(path: Path) -> QListWidgetItem:
    """Una fila de la carpeta: su nombre, y su ruta entera en el tooltip."""
    item = QListWidgetItem(path.name)
    item.setData(ROLE_KEY, str(path))
    item.setData(ROLE_FROM_DB, False)
    item.setToolTip(str(path))
    return item


class BuildPanel(Retranslates, QWidget):
    """Los árboles que se pueden construir, y los botones que lo hacen."""

    buildRequested = Signal()
    # Ruta del binario que se quiere leer como fuente, o cadena vacía para
    # que la ventana pregunte por uno: lo compilado puede estar fuera de la
    # carpeta abierta y ahí esta lista no llega.
    decompileRequested = Signal(str)
    # Traer un device tree del catálogo a la lista de compilables.
    databasePickRequested = Signal()

    def __init__(self, parent=None):
        """Monta la lista y las acciones, sin carpeta y sin herramientas."""
        super().__init__(parent)
        self._dtc = False
        self._cpp = False
        self._overlays = 0
        self._folder: Optional[Path] = None

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        self._trees_caption = QLabel()
        self._trees_caption.setObjectName("panelCaption")
        self._trees_caption.setContentsMargins(12, 10, 12, 4)
        # Selección **única**: se compila un árbol, y ese árbol es además la
        # base de los overlays encendidos. Poder elegir dos dejaría sin
        # respuesta contra cuál se comprueban.
        self.tree_list = QListWidget()
        self.tree_list.setObjectName("deviceTreeList")
        self.tree_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree_list.itemSelectionChanged.connect(self._refresh_build_button)

        self._blobs_caption = QLabel()
        self._blobs_caption.setObjectName("panelCaption")
        self._blobs_caption.setContentsMargins(12, 10, 12, 4)
        self.blob_list = QListWidget()
        self.blob_list.setObjectName("deviceTreeList")
        self.blob_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.blob_list.itemSelectionChanged.connect(self._refresh_decompile_button)

        actions = QWidget()
        action_column = QVBoxLayout(actions)
        action_column.setContentsMargins(12, 8, 12, 8)
        action_column.setSpacing(6)
        self.database_button = QPushButton()
        self.database_button.clicked.connect(self.databasePickRequested)
        self._overlays_label = QLabel()
        self._overlays_label.setWordWrap(True)
        self._overlays_label.setStyleSheet(f"color: {style.MUTED_TEXT_COLOR};")
        action_column.addWidget(self.database_button)
        action_column.addWidget(self._overlays_label)

        column.addWidget(self._trees_caption)
        column.addWidget(self.tree_list, 1)
        column.addWidget(actions)
        column.addWidget(self._blobs_caption)
        column.addWidget(self.blob_list, 1)
        column.addWidget(self._build_tools())
        self.retranslate()

    def _build_tools(self) -> QWidget:
        """Construir y descompilar, con lo que puedan decir de sí mismos.

        Un solo botón para todo el ciclo porque es un solo acto: se
        comprueban los overlays encendidos contra el árbol elegido y, solo
        si pasan, se compila todo. Compilar antes de comprobar produce un
        binario que solo falla al aplicarlo en la placa, que es el peor
        sitio donde enterarse.

        Necesita `dtc` y `cpp`, que **no se empaquetan** (ver
        `api/toolchain.py`), así que si faltan el botón lo dice en vez de
        fallar. Lo que digan las dos herramientas va al registro BUILD de la
        franja de abajo.
        """
        tools = QWidget()
        tools.setObjectName("overlayTools")
        box = QVBoxLayout(tools)
        box.setContentsMargins(12, 10, 12, 12)
        box.setSpacing(6)

        self._tools_caption = QLabel()
        self._tools_caption.setObjectName("panelCaption")
        box.addWidget(self._tools_caption)

        # Construir es la acción principal y va con relleno de acento;
        # descompilar es la de vuelta y se queda en botón fantasma. Dos
        # botones idénticos uno encima de otro no dicen cuál es cuál.
        self.build_button = QPushButton()
        self.build_button.setObjectName("primaryButton")
        self.build_button.clicked.connect(self.buildRequested)
        self.decompile_button = QPushButton()
        self.decompile_button.clicked.connect(
            lambda: self.decompileRequested.emit(self.selected_blob() or "")
        )
        self.refresh_icons()
        box.addWidget(self.build_button)
        box.addWidget(self.decompile_button)

        self._tools_hint = QLabel()
        self._tools_hint.setWordWrap(True)
        self._tools_hint.setObjectName("overlayToolsHint")
        box.addWidget(self._tools_hint)
        return tools

    def refresh_icons(self) -> None:
        """Redibuja los iconos en los colores de la piel activa."""
        tamano = style.ACTION_ICON_SIZE
        for button, draw, color in (
            (self.build_button, icons.build_icon, theme.ACCENT_FG),
            (self.decompile_button, icons.unarchive_icon, style.ACCENT_TEXT_COLOR),
        ):
            button.setIcon(draw(tamano, color))
            button.setIconSize(QSize(tamano, tamano))
        # Y la nube de cada fila del catálogo, que también está horneada.
        _CLOUDS.clear()
        for index in range(self.tree_list.count()):
            item = self.tree_list.item(index)
            if item.data(ROLE_FROM_DB):
                item.setIcon(_cloud())

    def retranslate(self) -> None:
        """Rehace los textos fijos (ver `Retranslates`)."""
        self._trees_caption.setText(self.tr("DEVICE TREES"))
        self.tree_list.setToolTip(
            self.tr(
                "The device tree that gets built, and the base its overlays "
                "are checked against."
            )
        )
        self.database_button.setText(self.tr("Add from the database…"))
        self.database_button.setToolTip(
            self.tr(
                "Bring a device tree from the catalogue: its source and its "
                "includes are written to a temporary folder to be compiled."
            )
        )
        self._blobs_caption.setText(self.tr("COMPILED"))
        self.blob_list.setToolTip(
            self.tr(
                "What building leaves behind. Pick one and read it back as "
                "device tree source with the button below."
            )
        )
        self._tools_caption.setText(self.tr("BUILD"))
        self.build_button.setText(self.tr("Build device tree"))
        self.build_button.setToolTip(
            self.tr(
                "Check the overlays switched on in OVERLAYS against the "
                "selected device tree and, if they pass, compile all of them "
                "with cpp and dtc."
            )
        )
        self.decompile_button.setToolTip(
            self.tr("Read a compiled .dtb/.dtbo back as device tree source.")
        )
        self._refresh_overlays_label()
        self._refresh_build_button()
        self._refresh_decompile_button()

    # ------------------------------------------------------------------
    # Contenido
    # ------------------------------------------------------------------
    def set_folder(self, folder: Optional[Path]) -> None:
        """Relista los `.dts` y los binarios de la carpeta, conservando lo demás.

        Lo traído del catálogo no se toca: no es de la carpeta y cambiar de
        carpeta no lo deshace.

        Los binarios se releen aquí y no solo al abrir otra carpeta, porque
        construir escribe unos nuevos junto a su fuente y la lista tiene que
        enterarse — es una lectura del disco, no un modelo vivo.
        """
        self._folder = folder
        elegido = self.selected_key()
        for index in reversed(range(self.tree_list.count())):
            if not self.tree_list.item(index).data(ROLE_FROM_DB):
                self.tree_list.takeItem(index)
        if folder is not None and folder.is_dir():
            for position, path in enumerate(
                sorted(scan_files(folder, DEVICE_TREE_SUFFIXES, OVERLAY_SCAN_DEPTH))
            ):
                self.tree_list.insertItem(position, _file_item(path))
        self._select_key(elegido)
        self._refresh_build_button()
        self._refresh_blobs()

    def _refresh_blobs(self) -> None:
        """Relee los `.dtb`/`.dtbo` de la carpeta, conservando el elegido."""
        elegido = self.selected_blob()
        self.blob_list.clear()
        if self._folder is not None and self._folder.is_dir():
            for path in sorted(
                scan_files(self._folder, BLOB_SUFFIXES, OVERLAY_SCAN_DEPTH)
            ):
                self.blob_list.addItem(_file_item(path))
        for index in range(self.blob_list.count()):
            if self.blob_list.item(index).data(ROLE_KEY) == elegido:
                self.blob_list.setCurrentRow(index)
                break
        self._refresh_decompile_button()

    def showEvent(self, event) -> None:  # noqa: N802 - override de Qt
        """Al volver a esta sección se relee: las dos listas son del disco.

        Además de la vigilancia que `MainWindow` monta sobre la carpeta: un
        `QFileSystemWatcher` no llega a todo —un volumen de red, una carpeta
        que se quedó fuera de la profundidad que se recorre— y volver a
        entrar es el momento en que se mira.
        """
        super().showEvent(event)
        self.set_folder(self._folder)

    def selected_blob(self) -> Optional[str]:
        """Ruta del binario elegido, si hay alguno."""
        items = self.blob_list.selectedItems()
        return items[0].data(ROLE_KEY) if items else None

    def add_database_entry(self, key: str, label: str) -> None:
        """Añade —y elige— un device tree del catálogo, sin repetirlo."""
        for index in range(self.tree_list.count()):
            if self.tree_list.item(index).data(ROLE_KEY) == key:
                self.tree_list.setCurrentRow(index)
                return
        item = QListWidgetItem(label)
        item.setData(ROLE_KEY, key)
        item.setData(ROLE_FROM_DB, True)
        # La nube dice lo único que no se ve en el nombre: esto no está en
        # la carpeta, sale de la base y se escribe a un temporal para
        # compilarlo. Sin ella, quien luego lo busque en su proyecto no lo
        # encuentra y no sabe por qué.
        item.setIcon(_cloud())
        item.setToolTip(
            self.tr("{key} · from the database, not in this folder").format(key=key)
        )
        self.tree_list.addItem(item)
        self.tree_list.setCurrentItem(item)

    def selected_key(self) -> Optional[str]:
        """Clave de lo elegido: una ruta del disco o una clave del catálogo."""
        items = self.tree_list.selectedItems()
        return items[0].data(ROLE_KEY) if items else None

    def selected_is_from_database(self) -> bool:
        """Si lo elegido hay que sacarlo de la base antes de compilarlo."""
        items = self.tree_list.selectedItems()
        return bool(items and items[0].data(ROLE_FROM_DB))

    def selected_name(self) -> str:
        """Cómo se llama lo elegido, para los mensajes."""
        items = self.tree_list.selectedItems()
        return items[0].text() if items else ""

    def set_overlay_count(self, count: int) -> None:
        """Cuántos overlays entran en la compilación (los de la otra sección)."""
        self._overlays = count
        self._refresh_overlays_label()
        self._refresh_build_button()

    def set_toolchain(self, dtc: bool, cpp: bool) -> None:
        """Guarda qué hay instalado y ajusta lo que se puede pulsar.

        Se pasa lo que hay en vez de mirarlo aquí: sondear `dtc` es un
        `subprocess`, y este panel se reconstruye al cambiar de idioma.
        """
        self._dtc = dtc
        self._cpp = cpp
        self.decompile_button.setEnabled(dtc)
        self._refresh_build_button()

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------
    def _select_key(self, key: Optional[str]) -> None:
        """Vuelve a elegir lo que estaba elegido, si sigue en la lista."""
        if key is None:
            return
        for index in range(self.tree_list.count()):
            if self.tree_list.item(index).data(ROLE_KEY) == key:
                self.tree_list.setCurrentRow(index)
                return

    def _refresh_overlays_label(self) -> None:
        """Dice cuántos overlays van a entrar, que se marcan en otra sección."""
        self._overlays_label.setText(
            self.tr("No overlay is switched on in OVERLAYS.")
            if not self._overlays
            else self.tr("{count} overlays switched on in OVERLAYS.").format(
                count=self._overlays
            )
        )

    def _refresh_decompile_button(self) -> None:
        """Descompilar dice sobre qué va a actuar: lo elegido, o lo que se pida.

        Sin binario elegido el botón no se apaga —lo compilado puede estar
        fuera de la carpeta abierta— sino que pregunta por un fichero, que es
        lo que hacía antes siempre.
        """
        elegido = self.selected_blob()
        self.decompile_button.setText(
            self.tr("Decompile {name}").format(name=Path(elegido).name)
            if elegido
            else self.tr("Decompile (.dts)")
        )

    def _refresh_build_button(self) -> None:
        """Construir pide herramientas **y** un árbol elegido, y dice cuál falta.

        Un botón apagado sin explicación es indistinguible de uno roto, y
        aquí hay dos motivos distintos por los que puede estarlo.
        """
        nombre = self.selected_name()
        self.build_button.setEnabled(self._dtc and self._cpp and bool(nombre))
        if not self._dtc:
            self._tools_hint.setText(
                self.tr("«dtc» is not installed: building is unavailable.")
            )
        elif not self._cpp:
            self._tools_hint.setText(
                self.tr("«cpp» is missing: only decompiling is available.")
            )
        elif not nombre:
            self._tools_hint.setText(
                self.tr("Pick the device tree to build from the list above.")
            )
        else:
            self._tools_hint.setText(
                self.tr("{tree} and every overlay switched on, checked first.")
                .format(tree=nombre)
            )
