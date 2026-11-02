"""Vista de edición del overlay: qué propiedades lleva el nodo apuntado.

El asistente son dos piezas que se reparten el trabajo:

- `widgets/overlay_panel.OverlayPanel`, en el panel lateral, arranca el flujo
  y enseña el **texto** del overlay según va quedando;
- esta vista, en el hueco central donde estaba el editor, enseña **el nodo
  apuntado**: lo que ya tiene, lo que su binding admite, y el botón de
  colgarle un nodo nuevo.

Aquí vive el borrador (`OverlayFragment`) y solo aquí. El preview no es una
segunda representación que haya que sincronizar: es ese mismo borrador ya
escrito como fuente. Y el nodo apuntado se elige señalándolo en el preview,
que es la razón de que un overlay con varios nodos no necesite ni un árbol
propio ni un desplegable — la estructura ya está a la vista en el texto.

Al terminar, el asistente escribe el fichero **una vez** y se aparta: a
partir de ahí el overlay es un documento más del editor, con el motor
semántico encima, y un overlay ajeno se puede abrir, editar y guardar sin
que la herramienta le quite nada por el camino.

**Una acción, no dos.** «Cambiar una propiedad» y «añadir una propiedad»
solo se diferencian en si la propiedad ya estaba en la base; en device tree
las dos son lo mismo al aplicar. Por eso son dos listas del mismo tipo, con
la misma casilla, y no dos flujos distintos.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from kernelgrove.api import (
    BindingOption,
    DeviceTreeNode,
    KernelGroveService,
    NodeAddition,
    OverlayFragment,
    PropertyEdit,
    PropertySuggestion,
    format_value,
    parse_overlay,
)
from kernelgrove.gui.translations import Retranslates

ROLE_SUGGESTION = Qt.UserRole + 1
ROLE_COMPATIBLE = Qt.UserRole + 2

COLUMN_NAME = 0
COLUMN_VALUE = 1
COLUMN_ORIGIN = 2

PAGE_EMPTY = 0
PAGE_EDIT = 1


class OverlayTab(Retranslates, QWidget):
    """El nodo apuntado del overlay: sus propiedades y lo que puede colgarle."""

    # El fuente generado y el nombre del nodo al que apunta, con el que la
    # ventana bautiza el fichero.
    overlayGenerated = Signal(str, str)
    status_changed = Signal(str)
    # El borrador ha cambiado: el fuente tal como queda y la línea del nodo
    # apuntado (0 si no hay ninguna), para que el panel lo enseñe y lo señale.
    draftChanged = Signal(str, int)

    def __init__(self, service: KernelGroveService, parent=None):
        """Monta las dos listas, vacías y sin borrador."""
        super().__init__(parent)
        self._service = service
        self._base: Optional[DeviceTreeNode] = None
        # Cómo se llama esa base (su `source_key`), que es lo que se escribe
        # en la cabecera del overlay generado para no perderla.
        self._target: Optional[DeviceTreeNode] = None
        self._fragment: Optional[OverlayFragment] = None
        # Ruta de nombres, desde el objetivo, del nodo al que apuntan ahora
        # mismo las listas. Vacía = el objetivo mismo.
        self._selected: Tuple[str, ...] = ()
        # Guarda mientras se rellenan las listas: `itemChanged` salta con
        # cada fila que se añade, y sin esto cada refresco reescribiría el
        # borrador con lo que acaba de leer de él.
        self._loading = False
        self._preview_text = ""
        # `#include` que el usuario haya escrito a mano en el preview: se
        # conservan al regenerar, o desaparecerían al marcar la siguiente
        # propiedad.
        self._extra_includes: List[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_empty())
        self._pages.addWidget(self._build_editor())
        layout.addWidget(self._pages, 1)

        self.retranslate()

    # ------------------------------------------------------------------
    # Construcción
    # ------------------------------------------------------------------
    def _build_empty(self) -> QWidget:
        """Sin borrador: por dónde se empieza.

        El listado de overlays de la carpeta y su comprobación no están
        aquí: viven en la sección «OVERLAYS» del panel izquierdo, junto al
        botón que arranca el asistente, porque construir un overlay y
        revisar los que ya hay son la misma tarea.
        """
        self._empty_hint = QLabel()
        self._empty_hint.setObjectName("emptyStateHint")
        self._empty_hint.setAlignment(Qt.AlignCenter)
        self._empty_hint.setWordWrap(True)
        return self._empty_hint

    def _build_editor(self) -> QWidget:
        """Con borrador: la barra del nodo apuntado y sus dos listas."""
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        toolbar = QWidget()
        toolbar.setObjectName("viewToolbar")
        toolbar.setLayout(self._build_toolbar())
        column.addWidget(toolbar)

        splitter = QSplitter(Qt.Horizontal)
        self.existing, existing_panel, self._existing_caption = self._build_list()
        self.available, available_panel, self._available_caption = self._build_list()
        splitter.addWidget(existing_panel)
        splitter.addWidget(available_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        column.addWidget(splitter, 1)
        return page

    def _build_toolbar(self) -> QHBoxLayout:
        """Qué nodo se está editando, y el botón de colgarle uno nuevo."""
        bar = QHBoxLayout()
        bar.setContentsMargins(12, 7, 12, 7)
        bar.setSpacing(8)

        self._reference_caption = QLabel()
        self._reference_caption.setObjectName("topBarCaption")
        self.reference_label = QLabel()
        self.compatible_label = QLabel()
        self.compatible_label.setObjectName("viewToolbarStatus")

        self.add_node_button = QPushButton()
        self.add_node_button.clicked.connect(self._add_node)

        bar.addWidget(self._reference_caption)
        bar.addWidget(self.reference_label)
        bar.addWidget(self.compatible_label)
        bar.addStretch(1)
        bar.addWidget(self.add_node_button)
        return bar

    def _build_list(self) -> Tuple[QTreeWidget, QWidget, QLabel]:
        """Una de las dos listas de propiedades, con su cabecera de zona."""
        panel = QWidget()
        column = QVBoxLayout(panel)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        caption = QLabel()
        caption.setObjectName("explorerHeader")

        tree = QTreeWidget()
        tree.setColumnCount(3)
        tree.setRootIsDecorated(False)
        tree.setUniformRowHeights(True)
        # Aquí solo se marca qué entra en el overlay; escribir se escribe en
        # el preview, que es el fuente de verdad y se edita como texto. Dos
        # sitios donde teclear el mismo valor sobraba, y el nombre de una
        # propiedad no es de nadie: lo pone el binding.
        tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tree.itemChanged.connect(self._on_item_changed)
        header = tree.header()
        # Nombre y marcas a un ancho fijo (arrastrable) y el valor
        # absorbiendo el resto: con las marcas a `ResizeToContents`, las dos
        # columnas de los lados sumaban más que el panel y el valor —lo que
        # se edita— se quedaba en su mínimo con barra horizontal.
        header.setSectionResizeMode(COLUMN_NAME, QHeaderView.Interactive)
        header.resizeSection(COLUMN_NAME, 150)
        header.setSectionResizeMode(COLUMN_VALUE, QHeaderView.Stretch)
        header.setSectionResizeMode(COLUMN_ORIGIN, QHeaderView.Interactive)
        header.resizeSection(COLUMN_ORIGIN, 100)

        column.addWidget(caption)
        column.addWidget(tree, 1)
        return tree, panel, caption

    def retranslate(self) -> None:
        """Rehace los textos fijos (ver `Retranslates`)."""
        self._empty_hint.setText(
            self.tr(
                "No overlay in progress.\n\nStart one from the OVERLAYS "
                "section of the left panel, where the overlays already in "
                "the folder are also listed and checked."
            )
        )
        self._reference_caption.setText(self.tr("Editing:"))
        self.add_node_button.setText(self.tr("Add new node"))
        self.add_node_button.setToolTip(
            self.tr("Hang a new device off the node being edited.")
        )
        self._existing_caption.setText(self.tr("EXISTING PROPERTIES"))
        self._available_caption.setText(self.tr("PROPERTIES THE BINDING ALLOWS"))
        for tree in (self.existing, self.available):
            # La tercera columna lleva las marcas («required», el tipo) y se
            # lee sola: un encabezado ahí solo sería ruido.
            tree.setHeaderLabels([self.tr("Property"), self.tr("Value"), ""])
        self._refresh_reference()

    # ------------------------------------------------------------------
    # Borrador
    # ------------------------------------------------------------------
    def set_base(self, base: Optional[DeviceTreeNode]) -> None:
        """Fija el árbol contra el que se resuelven objetivos y bindings.

        Llega tras **cada** análisis del editor, así que no toca el borrador
        en marcha: reconstruirlo se llevaría por delante lo que se acaba de
        marcar.
        """
        self._base = base

    @property
    def has_draft(self) -> bool:
        """Si hay un overlay en construcción ahora mismo."""
        return self._fragment is not None

    def start_draft(self, node: DeviceTreeNode) -> bool:
        """Empieza un overlay que apunta a `node`.

        `node` viene del árbol del documento que se está editando; lo que
        hace falta para el binding y las propiedades es su equivalente en el
        árbol **fusionado**, donde el nodo está entero (sus `.dtsi` ya
        pegados). Se busca por ruta, que es lo que comparten los dos.

        Un nodo sin etiqueta ni ruta no puede ser objetivo de un fragmento:
        no hay forma de escribirlo. Se rechaza en vez de generar un overlay
        que no apunta a ninguna parte.
        """
        target = self._resolve_in_base(node) or node
        if not target.label and not target.path:
            return False

        self._target = target
        self._fragment = OverlayFragment(
            target_label=target.label or None,
            target_path=None if target.label else target.path,
        )
        self._selected = ()
        self._extra_includes = []
        self._pages.setCurrentIndex(PAGE_EDIT)
        self._refresh()
        return True

    def set_source(self, text: str) -> None:
        """Relee el borrador del texto que se ha escrito a mano en el preview.

        A partir de una edición manual **manda el texto**: se vuelve a leer
        el fragmento de ahí y las listas pasan a enseñar lo que hay escrito,
        no lo que se había marcado. Es la misma regla que rige en el editor —
        el fichero es el modelo— aplicada un paso antes, y evita el problema
        clásico de estas herramientas: dos representaciones del mismo overlay
        que hay que mantener de acuerdo en los dos sentidos.

        No se reescribe el texto de vuelta (nada de `draftChanged`): quien lo
        está escribiendo tiene el cursor dentro. Un texto a medio escribir
        —una llave sin cerrar— no llega a tener fragmento; entonces se deja
        el anterior en pie en vez de vaciar las listas mientras se teclea.
        """
        if self._fragment is None:
            return
        fragment = _fragment_from_text(text)
        if fragment is None:
            return

        self._preview_text = text
        self._fragment = fragment
        self._extra_includes = _includes_in(text)
        # El nodo apuntado puede haber desaparecido del texto: se vuelve al
        # objetivo, que siempre está mientras haya fragmento.
        if self._selected and self._draft_node(self._selected) is None:
            self._selected = ()
        self._refresh_lists()
        self._refresh_reference()

    def discard_draft(self) -> None:
        """Tira el borrador y vuelve al estado inicial."""
        self._target = None
        self._fragment = None
        self._selected = ()
        self._preview_text = ""
        self._pages.setCurrentIndex(PAGE_EMPTY)
        self._refresh_lists()
        self._refresh_reference()
        # Avisa con un fuente vacío: es lo que devuelve el panel a su estado
        # inicial sin que haga falta una segunda señal para lo mismo.
        self.draftChanged.emit("", 0)

    def _resolve_in_base(self, node: DeviceTreeNode) -> Optional[DeviceTreeNode]:
        """El mismo nodo, pero en el árbol fusionado, buscándolo por su ruta."""
        if self._base is None or not node.path:
            return None
        for candidate in self._base.iter_tree():
            if candidate.path == node.path:
                return candidate
        return None

    # ------------------------------------------------------------------
    # Nodo apuntado
    # ------------------------------------------------------------------
    def select_line(self, line: int) -> None:
        """Apunta al nodo del preview que empieza en `line`.

        La línea la resuelve el panel con el mismo emparejado de llaves que
        usa el plegado del editor; aquí solo hay que traducir esa línea al
        nodo del borrador, lo que se hace releyendo el fuente que se acaba de
        generar — no hay ningún mapa que mantener al día.
        """
        names = self._names_at_line(line)
        if names is None or names == self._selected:
            return
        self._selected = names
        self._refresh_lists()
        self._refresh_reference()

    def _names_at_line(self, line: int) -> Optional[Tuple[str, ...]]:
        """Ruta de nombres, desde el objetivo, del nodo que empieza en `line`."""
        if not self._preview_text:
            return None
        for node in parse_overlay(self._preview_text).root.iter_tree():
            if node.line != line or node.parent is None:
                continue
            return self._names_of(node)
        return None

    @staticmethod
    def _names_of(node: DeviceTreeNode) -> Tuple[str, ...]:
        """Ruta de nombres de un nodo del preview, relativa al pseudo-objetivo.

        El pseudo-nodo del objetivo (`&i2c0`) cuelga directamente de la raíz,
        así que su ruta relativa es la vacía: es lo que identifica «el nodo
        de la base al que apunta el fragmento».
        """
        names: List[str] = []
        cursor: Optional[DeviceTreeNode] = node
        while cursor is not None and cursor.parent is not None:
            if cursor.parent.parent is None:
                break
            names.append(cursor.name)
            cursor = cursor.parent
        return tuple(reversed(names))

    def _line_of(self, names: Sequence[str]) -> int:
        """Línea del preview donde empieza el nodo `names`, o 0 si no está."""
        if not self._preview_text:
            return 0
        wanted = tuple(names)
        for node in parse_overlay(self._preview_text).root.iter_tree():
            if node.parent is not None and self._names_of(node) == wanted:
                return node.line
        return 0

    def _draft_node(self, names: Sequence[str]) -> Optional[NodeAddition]:
        """El nodo añadido que corresponde a `names`, o `None` si no existe."""
        if self._fragment is None:
            return None
        siblings = self._fragment.added_nodes
        node: Optional[NodeAddition] = None
        for name in names:
            node = next((item for item in siblings if item.name == name), None)
            if node is None:
                return None
            siblings = node.children
        return node

    def _container(self):
        """Dónde van las propiedades del nodo apuntado: el fragmento o un nodo."""
        if not self._selected:
            return self._fragment
        return self._draft_node(self._selected)

    def _selected_compatible(self) -> Optional[str]:
        """Compatible del nodo apuntado, para poder preguntarle a su binding.

        Para el objetivo sale del árbol de la base; para un nodo añadido, de
        la propiedad `compatible` que el propio overlay le escribe — que es
        lo único que se sabe de él, porque todavía no existe en ningún sitio.
        """
        if not self._selected:
            if self._target is not None and self._target.compatible:
                return self._target.compatible[0]
            return None
        node = self._draft_node(self._selected)
        if node is None:
            return None
        for edit in node.properties:
            if edit.name == "compatible" and edit.value:
                return edit.value.strip().strip('"').split('"')[0]
        return None

    # ------------------------------------------------------------------
    # Listas
    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        """Rehace las listas, la referencia y el preview desde el borrador."""
        self._refresh_lists()
        self._refresh_reference()
        self._emit_draft()

    def _refresh_lists(self) -> None:
        """Reparte las propiedades entre «ya las tiene» y «su binding admite».

        Las dos listas se reconstruyen enteras desde el borrador: el estado
        vive ahí y solo ahí, así que apuntar a otro nodo y volver devuelve
        exactamente lo que se había marcado, sin nada que sincronizar.
        """
        container = self._container()
        if container is None:
            self.existing.clear()
            self.available.clear()
            return

        edits = {edit.name: edit for edit in container.properties}
        # Un nodo que añade el overlay no existe todavía en la base: no tiene
        # ninguna propiedad «de antes», todas son añadidas.
        present = (
            dict(self._target.properties)
            if not self._selected and self._target is not None
            else {}
        )
        compatible = self._selected_compatible()
        known: Dict[str, PropertySuggestion] = {}
        if compatible:
            known = {
                item.name: item
                for item in self._service.suggest_properties(compatible)
            }

        existing = [
            known.get(name, PropertySuggestion(name=name)) for name in sorted(present)
        ]
        available = [
            item
            for name, item in sorted(known.items())
            if name not in present and not item.is_node
        ]
        # Lo que el overlay ya escribe y el binding no declara (o de lo que no
        # hay binding) tiene que verse igual, o desaparecería al refrescar.
        available.extend(
            PropertySuggestion(name=name)
            for name in sorted(edits)
            if name not in present and name not in known
        )

        self._fill(
            self.existing,
            existing,
            edits,
            present,
            self.tr("This node is new: everything it has, the overlay adds.")
            if self._selected
            else self.tr("The node has no properties of its own."),
        )
        self._fill(
            self.available,
            available,
            edits,
            {},
            self.tr("No binding for this node, so there is nothing to offer.")
            if not self._selected_compatible()
            else self.tr("Its binding declares no further properties."),
        )

    def _fill(
        self,
        tree: QTreeWidget,
        suggestions: List[PropertySuggestion],
        edits: Dict[str, PropertyEdit],
        present: Dict[str, object],
        empty_hint: str,
    ) -> None:
        """Vuelca una lista de propiedades, marcando las que el overlay escribe."""
        self._loading = True
        tree.clear()
        for suggestion in suggestions:
            edit = edits.get(suggestion.name)
            if edit is not None:
                text = "" if edit.value is None else edit.value
            else:
                text = _as_text(present.get(suggestion.name))
            item = QTreeWidgetItem([suggestion.name, text, ""])
            item.setFlags(
                Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
            )
            item.setCheckState(
                COLUMN_NAME, Qt.Checked if edit is not None else Qt.Unchecked
            )
            item.setData(COLUMN_NAME, ROLE_SUGGESTION, suggestion)
            marks = []
            if suggestion.required:
                marks.append(self.tr("required"))
            if suggestion.dt_type:
                marks.append(suggestion.dt_type)
            item.setText(COLUMN_ORIGIN, " · ".join(marks))
            if suggestion.description:
                item.setToolTip(COLUMN_NAME, suggestion.description)
            tree.addTopLevelItem(item)
        if tree.topLevelItemCount() == 0:
            _add_placeholder(tree, empty_hint)
        self._loading = False

    def _on_item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        """Marcar una propiedad o escribirle un valor cambia el borrador."""
        if self._loading:
            return
        container = self._container()
        if container is None:
            return

        suggestion = item.data(COLUMN_NAME, ROLE_SUGGESTION)
        edits = container.properties
        existing = next(
            (edit for edit in edits if edit.name == suggestion.name), None
        )

        if item.checkState(COLUMN_NAME) != Qt.Checked:
            if existing is not None:
                edits.remove(existing)
            self._emit_draft()
            return

        raw = item.text(COLUMN_VALUE).strip() or _starting_value(suggestion)
        value = format_value(suggestion.dt_type, raw) if raw else None
        if existing is None:
            edits.append(PropertyEdit(name=suggestion.name, value=value))
        else:
            existing.value = value
        # El valor con el que arranca se devuelve a la celda: si no, la lista
        # diría que la propiedad no lleva valor mientras el texto sí lo
        # escribe.
        if value is not None and value != item.text(COLUMN_VALUE):
            self._loading = True
            item.setText(COLUMN_VALUE, value)
            self._loading = False
        self._emit_draft()

    def _refresh_reference(self) -> None:
        """Enseña a qué nodo apuntan las listas ahora mismo."""
        if self._fragment is None:
            self.reference_label.setText("")
            self.compatible_label.setText("")
            return
        reference = self._fragment.reference()
        if self._selected:
            reference = reference + " / " + " / ".join(self._selected)
        self.reference_label.setText(reference)
        compatible = self._selected_compatible()
        self.compatible_label.setText(compatible or self.tr("no known binding"))
        # Sin binding no hay catálogo de lo que puede colgar: ofrecer el
        # botón sería ofrecer una lista vacía.
        self.add_node_button.setEnabled(bool(compatible))

    # ------------------------------------------------------------------
    # Nodo nuevo
    # ------------------------------------------------------------------
    def _add_node(self) -> None:
        """Elige un dispositivo del catálogo y lo cuelga del nodo apuntado."""
        container = self._container()
        compatible = self._selected_compatible()
        if container is None or compatible is None:
            return

        options = self._service.list_child_options(compatible)
        if not options:
            self.status_changed.emit(
                self.tr(
                    "The binding of {compatible} declares nothing that can hang "
                    "off it."
                ).format(compatible=compatible)
            )
            return

        dialog = AddNodeDialog(options, self)
        if dialog.exec() != QDialog.Accepted:
            return
        chosen, name = dialog.result_node()
        if chosen and name:
            self.add_node(chosen, name)

    def add_node(self, compatible: str, name: str) -> None:
        """Cuelga del nodo apuntado uno nuevo con ese compatible.

        Solo se escribe el `compatible`. Las demás propiedades obligatorias
        **no** se emiten vacías: un `reg = ;` no es DTS válido, y rellenarlo
        con un valor inventado es peor todavía. Quien recuerda lo que falta
        es el motor semántico, que avisa de cada obligatoria ausente con su
        línea — mirando el binding, que es su trabajo.
        """
        container = self._container()
        if container is None:
            return

        node = NodeAddition(
            name=name,
            properties=[
                PropertyEdit("compatible", format_value("string", compatible))
            ],
        )
        siblings = (
            self._fragment.added_nodes if not self._selected else container.children
        )
        siblings.append(node)
        # Se pasa a apuntar al nodo recién añadido: lo siguiente que se hará
        # es rellenarlo, no seguir en el de antes.
        self._selected = tuple(self._selected) + (name,)
        self._refresh()

    # ------------------------------------------------------------------
    # Salida
    # ------------------------------------------------------------------
    def _emit_draft(self) -> None:
        """Compone el fuente del borrador y lo publica con la línea apuntada."""
        if self._fragment is None:
            self._preview_text = ""
            self.draftChanged.emit("", 0)
            return
        self._preview_text = self._compose()
        self.draftChanged.emit(self._preview_text, self._line_of(self._selected))

    def _compose(self) -> str:
        """El `.dtso` del borrador, con las cabeceras que sus valores piden.

        No se anota contra qué base se construyó: la base se elige al
        comprobar (`OverlayList`), que es donde el usuario sabe qué está
        preguntando; escribirla en un comentario ataba el fichero a una
        procedencia que además nadie podía ver ni corregir desde la interfaz.
        """
        includes = self._service.includes_for_properties(self._values())
        includes = sorted(set(includes) | set(self._extra_includes))
        return self._service.build_overlay_source(
            [self._fragment],
            includes=includes,
            description=self.tr("Overlay generated by KernelGrove"),
        )

    def _values(self) -> List[str]:
        """Todos los valores que escribe el borrador, para buscarles includes."""
        values: List[str] = []

        def walk(nodes: Sequence[NodeAddition]) -> None:
            for node in nodes:
                values.extend(edit.value or "" for edit in node.properties)
                walk(node.children)

        values.extend(edit.value or "" for edit in self._fragment.properties)
        walk(self._fragment.added_nodes)
        return values

    def generate(self) -> None:
        """Entrega el fuente para que la ventana lo abra como documento."""
        if self._fragment is None or self._fragment.is_empty():
            self.status_changed.emit(
                self.tr("The overlay is empty: tick a property or add a node.")
            )
            return
        source = self._compose()
        reference = self._fragment.reference()
        self.overlayGenerated.emit(source, self._fragment.target_name())
        self.status_changed.emit(
            self.tr("Overlay generated for {target}").format(target=reference)
        )
        self.discard_draft()


def _fragment_from_text(text: str) -> Optional[OverlayFragment]:
    """Vuelve a leer el fragmento del fuente, para que el texto pueda mandar.

    Se apoya en el parser de siempre: un overlay es un device tree con
    pseudo-nodos `&etiqueta` colgando de la raíz, así que el primero de esos
    es el fragmento. Sin ninguno —texto a medias, llave sin cerrar— se
    devuelve `None` y quien llama decide qué hacer.
    """
    for node in parse_overlay(text).root.children:
        if not node.name.startswith("&"):
            continue
        por_ruta = node.name.startswith("&{")
        fragment = OverlayFragment(
            target_label=None if por_ruta else node.name[1:],
            target_path=node.name[2:-1] if por_ruta else None,
        )
        fragment.properties = _edits_of(node)
        fragment.added_nodes = [_addition_from(child) for child in node.children]
        return fragment
    return None


def _edits_of(node: DeviceTreeNode) -> List[PropertyEdit]:
    """Las propiedades de un nodo del texto, como escrituras del overlay.

    El parser guarda `True` para las que se escriben sin `=` (las marcas de
    device tree), que es exactamente lo que `PropertyEdit` representa con
    `value=None`.
    """
    return [
        PropertyEdit(name=name, value=None if value is True else str(value))
        for name, value in node.properties.items()
    ]


def _addition_from(node: DeviceTreeNode) -> NodeAddition:
    """Un nodo del texto y todo lo que cuelga de él, como nodo añadido."""
    return NodeAddition(
        name=node.name,
        properties=_edits_of(node),
        children=[_addition_from(child) for child in node.children],
    )


def _includes_in(text: str) -> List[str]:
    """Cabeceras que el fuente incluye ahora mismo, tal como están escritas."""
    return [
        directive.target
        for directive in parse_overlay(text).includes
        if directive.target
    ]


def _starting_value(suggestion: PropertySuggestion) -> str:
    """Con qué valor se escribe una propiedad recién marcada.

    En device tree solo las marcas (`flag`) se escriben sin `=`: cualquier
    otra propiedad sin valor es DTS mal formado, así que marcarla tiene que
    escribir **algo**. Se escribe lo más parecido a un dato real que se sepa
    —el primer valor del `enum` si el binding los enumera— y si no, el vacío
    de su tipo, que es un hueco visible y editable tanto en la lista como en
    el preview.

    Sin tipo declarado no se inventa nada: la propiedad aparece con tipos
    distintos en bindings distintos, así que cualquier hueco sería una
    apuesta. Se queda sin valor y de eso ya avisa el motor semántico.
    """
    if suggestion.dt_type in (None, "flag", "boolean"):
        return ""
    if suggestion.allowed_values:
        return str(suggestion.allowed_values[0])
    if suggestion.dt_type in ("string", "string-array"):
        return '""'
    return "<0>"


def _add_placeholder(tree: QTreeWidget, text: str) -> None:
    """Explica por qué una lista está vacía, en vez de dejar el hueco.

    Un panel vacío sin más se lee como «esto no funciona»; con una línea se
    lee como «aquí no hay nada que elegir», que es lo que pasa.

    El `setFirstColumnSpanned` va **después** de añadirla: sobre una fila
    suelta no hay árbol al que decírselo, y el texto se quedaría cortado en
    la primera columna en vez de ocupar la fila entera.
    """
    item = QTreeWidgetItem([text, "", ""])
    item.setFlags(Qt.NoItemFlags)
    tree.addTopLevelItem(item)
    item.setFirstColumnSpanned(True)


def _as_text(value: object) -> str:
    """El valor de una propiedad tal como se enseña en su columna."""
    if value is None or value is True:
        return ""
    return str(value)


class AddNodeDialog(Retranslates, QDialog):
    """Catálogo de lo que puede colgar del nodo apuntado, y el nombre del nuevo."""

    def __init__(self, options: List[BindingOption], parent=None):
        """Lista los dispositivos ofrecidos, con su filtro y el nombre a poner."""
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self._filter = QLineEdit()
        self._filter.textChanged.connect(self._apply_filter)
        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_selection)
        self._list.itemDoubleClicked.connect(lambda _item: self.accept())
        self._name = QLineEdit()

        self._name_caption = QLabel()
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        layout.addWidget(self._filter)
        layout.addWidget(self._list, 1)
        layout.addWidget(self._name_caption)
        layout.addWidget(self._name)
        layout.addWidget(self._buttons)

        self._fill(options)
        self.retranslate()
        self.resize(520, 460)

    def retranslate(self) -> None:
        """Rehace los textos fijos (ver `Retranslates`)."""
        self.setWindowTitle(self.tr("Add new node"))
        self._filter.setPlaceholderText(self.tr("Filter by compatible or name…"))
        self._name_caption.setText(self.tr("Node name"))
        self._name.setPlaceholderText(self.tr("e.g. rtc@68"))

    def _fill(self, options: List[BindingOption]) -> None:
        """Vuelca el catálogo; el compatible real viaja aparte de la etiqueta."""
        self._list.clear()
        for option in options:
            item = QListWidgetItem(option.label)
            item.setData(ROLE_COMPATIBLE, option.compatible)
            self._list.addItem(item)

    def _apply_filter(self, needle: str) -> None:
        """Deja visibles solo los que contienen `needle`."""
        text = needle.strip().lower()
        for index in range(self._list.count()):
            item = self._list.item(index)
            item.setHidden(bool(text) and text not in item.text().lower())

    def _on_selection(self, item: Optional[QListWidgetItem], _previous) -> None:
        """Propone como nombre el modelo del compatible elegido.

        `dallas,ds1307` → `ds1307`: la parte del fabricante no va en el nombre
        del nodo. La dirección (`@68`) no se puede adivinar —depende del bus—,
        así que se deja a medias para que se complete a mano.
        """
        if item is None or self._name.isModified():
            return
        compatible = item.data(ROLE_COMPATIBLE) or ""
        self._name.setText(compatible.split(",")[-1])

    def result_node(self) -> Tuple[Optional[str], str]:
        """El compatible elegido y el nombre escrito."""
        item = self._list.currentItem()
        compatible = item.data(ROLE_COMPATIBLE) if item is not None else None
        return compatible, self._name.text().strip()
