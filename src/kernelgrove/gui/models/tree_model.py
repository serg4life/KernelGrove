"""Modelo Qt que expone los controladores del SoC y lo conectado a ellos.

El estado real vive en `kernelgrove.api.PeripheralSlot`; esta clase solo lo adapta a
la interfaz de modelo de Qt para que `QTreeView` pueda pintarlo.
"""

from __future__ import annotations

from typing import Any, List, Optional

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QFont

from kernelgrove.api import KernelGroveService, PeripheralSlot

COLUMN_NAME = 0
COLUMN_COMPATIBLE = 1
COLUMN_CONNECT = 2
COLUMN_BUS = 3

# Las cabeceras se traducen al pedirlas, en `headerData`, y escritas ahí
# literalmente: al importar el módulo todavía no hay `QApplication` ni
# idioma, y `lupdate` solo extrae lo que ve escrito dentro de la llamada
# —`self.tr(UNA_CONSTANTE)` no se extrae y en ejecución no encuentra nada—.
COLUMN_COUNT = 4


class PeripheralTreeModel(QAbstractItemModel):
    """Adapta los slots de controlador del SoC a la interfaz de modelo de Qt.

    En la columna `Conectar dispositivo` los controladores ofrecen la lista de
    bindings compatibles con su bus; al elegir uno se añade como hijo. Los
    hijos son dispositivos concretos y se habilitan con su casilla.
    """

    slotStateChanged = Signal()

    def __init__(self, service: KernelGroveService, parent=None):
        """Crea el modelo, que delega en el servicio para conectar dispositivos."""
        super().__init__(parent)
        self._service = service
        self._root_slots: List[PeripheralSlot] = []

    # ------------------------------------------------------------------
    # Carga de datos
    # ------------------------------------------------------------------
    def set_root_slots(self, root_slots: List[PeripheralSlot]) -> None:
        """Reemplaza por completo el contenido del árbol (al cambiar de SoC)."""
        self.beginResetModel()
        self._root_slots = root_slots
        self.endResetModel()

    def root_slots(self) -> List[PeripheralSlot]:
        """Devuelve los controladores de primer nivel del SoC."""
        return self._root_slots

    def slot_from_index(self, index: QModelIndex) -> Optional[PeripheralSlot]:
        """Traduce un índice de Qt al `PeripheralSlot` que representa."""
        if not index.isValid():
            return None
        return index.internalPointer()

    # ------------------------------------------------------------------
    # Interfaz obligatoria de QAbstractItemModel
    # ------------------------------------------------------------------
    def index(self, row: int, column: int, parent=QModelIndex()) -> QModelIndex:
        """Construye el índice del hijo `row` dentro de `parent`."""
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        siblings = self._siblings_for(parent)
        if row >= len(siblings):
            return QModelIndex()
        return self.createIndex(row, column, siblings[row])

    def parent(self, index: QModelIndex) -> QModelIndex:  # type: ignore[override]
        """Devuelve el índice del padre de `index` (inválido si es raíz)."""
        slot = self.slot_from_index(index)
        if slot is None or slot.parent is None:
            return QModelIndex()
        return self.createIndex(self._row_of(slot.parent), 0, slot.parent)

    def _row_of(self, slot: PeripheralSlot) -> int:
        """Fila que ocupa `slot` entre sus hermanos, o -1 si ya no está.

        Un controlador del SoC no tiene padre y sus hermanos son la lista de
        raíces, que solo conoce el modelo: por eso esto vive aquí y no en
        `PeripheralSlot`, donde `row()` devolvía 0 para **todas** las raíces
        —lo que hacía que desconectar algo colgado del segundo controlador
        borrara lo del primero, o no hiciera nada si el primero estaba
        vacío.

        La búsqueda es por identidad y no con `list.index`: dos slots del
        mismo compatible bajo el mismo padre son iguales campo a campo, y
        `==` sobre un `PeripheralSlot` recorre además padres e hijos.
        """
        siblings = self._root_slots if slot.parent is None else slot.parent.children
        return next(
            (row for row, sibling in enumerate(siblings) if sibling is slot), -1
        )

    def rowCount(self, parent=QModelIndex()) -> int:
        """Número de hijos colgando de `parent`."""
        if parent.column() > 0:
            return 0
        return len(self._siblings_for(parent))

    def columnCount(self, parent=QModelIndex()) -> int:
        """Número de columnas del árbol (fijo)."""
        return COLUMN_COUNT

    def _siblings_for(self, parent: QModelIndex) -> List[PeripheralSlot]:
        """Lista de slots que cuelgan de `parent`, o los raíz si no es válido."""
        parent_slot = self.slot_from_index(parent)
        if parent_slot is None:
            return self._root_slots
        return parent_slot.children

    def headerData(self, section: int, orientation, role=Qt.DisplayRole) -> Any:
        """Texto de cabecera de cada columna."""
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return (
                self.tr("Node"),
                self.tr("Compatible"),
                self.tr("Connect device"),
                self.tr("Bus"),
            )[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole) -> Any:
        """Devuelve el dato de la celda según el rol pedido por la vista."""
        slot = self.slot_from_index(index)
        if slot is None:
            return None

        column = index.column()

        if role in (Qt.DisplayRole, Qt.EditRole):
            if column == COLUMN_NAME:
                return slot.node_name
            if column == COLUMN_COMPATIBLE:
                return slot.display_name
            if column == COLUMN_CONNECT:
                # También se ofrece desplegable a un dispositivo con funciones
                # propias (un MFD), que no es un bus pero admite hijos.
                if not slot.accepts_children:
                    return ""
                if role == Qt.EditRole:
                    return ""
                connected = len(slot.children)
                # Texto corto: la columna es estrecha y el detalle ya se ve en
                # los hijos del árbol.
                return (
                    self.tr("+ connect ({count})").format(count=connected)
                    if connected
                    else self.tr("+ connect…")
                )
            if column == COLUMN_BUS:
                # Un mux cuelga de un bus y ofrece otro: se muestran los dos.
                parent_bus = slot.descriptor.parent_bus
                if slot.is_bus and parent_bus and not slot.is_root:
                    return f"{parent_bus} → {slot.child_bus}"
                if slot.is_bus:
                    return slot.child_bus or ""
                if slot.subdevice_parent:
                    return f"{parent_bus} → funciones" if parent_bus else "funciones"
                return parent_bus or ""

        if role == Qt.CheckStateRole and column == COLUMN_NAME and not slot.is_root:
            return Qt.Checked if slot.enabled else Qt.Unchecked

        if role == Qt.ToolTipRole:
            kind = (
                self.tr("SoC controller")
                if slot.is_root
                else self.tr("Connected device")
            )
            lines = [
                f"{kind}: {slot.display_name}",
                self.tr("Path: {path}").format(path=slot.descriptor.path or "—"),
            ]
            if not slot.is_root:
                lines.append(
                    self.tr("Connected to bus: {bus}").format(
                        bus=slot.descriptor.parent_bus or "—"
                    )
                )
            if slot.is_bus:
                lines.append(
                    self.tr("Offers bus: {bus}").format(bus=slot.child_bus)
                )
            if slot.subdevice_parent:
                lines.append(self.tr("Offers the functions its binding declares"))
                lines.append(self.tr("You can connect more nodes underneath."))
            return "\n".join(lines)

        if role == Qt.FontRole and column == COLUMN_NAME and slot.is_bus:
            font = QFont()
            font.setBold(True)
            return font

        return None

    def setData(self, index: QModelIndex, value: Any, role=Qt.EditRole) -> bool:
        """Aplica la edición del usuario (dispositivo conectado o casilla marcada)."""
        slot = self.slot_from_index(index)
        if slot is None:
            return False

        if role == Qt.CheckStateRole and index.column() == COLUMN_NAME:
            slot.enabled = Qt.CheckState(value) == Qt.Checked
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            self.slotStateChanged.emit()
            return True

        if (
            role == Qt.EditRole
            and index.column() == COLUMN_CONNECT
            and slot.accepts_children
        ):
            compatible = (value or "").strip()
            if not compatible or compatible == self.tr("+ connect…"):
                return False
            self._connect_device(index, slot, compatible)
            self.slotStateChanged.emit()
            return True

        return False

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        """Marca qué celdas son editables o marcables según el tipo de slot."""
        if not index.isValid():
            return Qt.NoItemFlags

        slot = self.slot_from_index(index)
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable

        if slot is None:
            return base

        # Un dispositivo conectado se habilita con su casilla; si además es un
        # bus (un mux), conserva también su desplegable para colgarle nodos.
        if index.column() == COLUMN_NAME and not slot.is_root:
            return base | Qt.ItemIsUserCheckable
        if index.column() == COLUMN_CONNECT and slot.accepts_children:
            return base | Qt.ItemIsEditable

        return base

    # ------------------------------------------------------------------
    # Conexión de dispositivos
    # ------------------------------------------------------------------
    def _connect_device(
        self, index: QModelIndex, slot: PeripheralSlot, compatible: str
    ) -> None:
        """Añade al controlador el dispositivo elegido, notificando a la vista."""
        parent_index = index.sibling(index.row(), 0)
        position = len(slot.children)

        self.beginInsertRows(parent_index, position, position)
        self._service.connect_binding(slot, compatible)
        self.endInsertRows()

        self.dataChanged.emit(index, index)

    def index_for_slot(self, slot: PeripheralSlot) -> QModelIndex:
        """Reconstruye el índice Qt de `slot`, para quien solo tiene el objeto.

        El grafo del visualizador conecta y desconecta dispositivos por
        `PeripheralSlot`, no por índice: sube por `slot.parent` recreando el
        índice en cada nivel, igual que hace `parent()` a la inversa. Un slot
        que ya no cuelga de nadie (`_row_of` devuelve -1) no tiene índice:
        `index()` devuelve uno inválido y quien llame se encuentra con que no
        hay nada que quitar, en vez de con la fila equivocada.
        """
        if slot.parent is None:
            return self.index(self._row_of(slot), 0, QModelIndex())
        return self.index(self._row_of(slot), 0, self.index_for_slot(slot.parent))

    def connect_to_slot(
        self, slot: PeripheralSlot, compatible: str
    ) -> Optional[PeripheralSlot]:
        """Conecta `compatible` a `slot` desde fuera del delegado del árbol.

        Punto de entrada del grafo del visualizador: reutiliza
        `_connect_device` para mantener el `beginInsertRows`/`endInsertRows`
        correcto, así que la vista en árbol del Generador también se entera.
        """
        if not slot.accepts_children:
            return None
        index = self.index_for_slot(slot)
        self._connect_device(index, slot, compatible)
        self.slotStateChanged.emit()
        return slot.children[-1]

    def disconnect_by_slot(self, slot: PeripheralSlot) -> bool:
        """Desconecta `slot` de su padre desde fuera del árbol Qt.

        Quitar un mux se lleva por delante lo que tenía conectado, así que
        desconectar varios de una vez (la selección del grafo) llega aquí
        con slots que ya no cuelgan de nadie; `index_for_slot` los resuelve
        a un índice inválido y `remove_slot` no hace nada con ellos.
        """
        if slot.parent is None:
            return False
        return self.remove_slot(self.index_for_slot(slot))

    def remove_slot(self, index: QModelIndex) -> bool:
        """Desconecta el dispositivo señalado por `index` de su controlador."""
        slot = self.slot_from_index(index)
        if slot is None or slot.parent is None:
            return False

        parent_slot = slot.parent
        parent_index = self.parent(index)
        position = self._row_of(slot)
        if position < 0:
            return False

        self.beginRemoveRows(parent_index, position, position)
        self._service.disconnect(parent_slot, slot)
        self.endRemoveRows()

        self.slotStateChanged.emit()
        return True
