"""Estado de edición de un SoC y su traducción al modelo interno.

Vive en la API, no en la GUI, porque no depende de ningún widget: describe
qué se ha conectado en cada controlador y cómo eso se convierte en un
`InternalDeviceTreeModel`. La interfaz solo lo renderiza.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, List, Optional

from kernelgrove.dt_model.model import (
    DeviceTreeNode,
    InternalDeviceTreeModel,
    PeripheralNode,
    SoCProfile,
)


@dataclass
class PeripheralSlot:
    """Un controlador del SoC junto a lo que el usuario ha decidido conectarle.

    Los slots raíz son controladores de bus (`is_bus`) y se editan eligiendo
    un binding. Los hijos que se generan al elegirlo son dispositivos
    concretos, que se habilitan o deshabilitan.
    """

    descriptor: PeripheralNode
    parent: Optional["PeripheralSlot"] = None
    children: List["PeripheralSlot"] = field(default_factory=list)
    selected_binding: Optional[str] = None
    enabled: bool = False
    # Compatible del dispositivo cuyos **subnodos** admite este slot, si es
    # que admite alguno. No es un bus: un MFD describe sus funciones internas
    # en su propio binding, y por eso va en un campo aparte en vez de
    # colarse en `child_bus`, que la GUI y el visualizador usan como nombre
    # de bus real.
    subdevice_parent: Optional[str] = None

    @property
    def is_bus(self) -> bool:
        """Indica si el slot expone un bus hijo y por tanto acepta periféricos."""
        return bool(self.descriptor.child_bus)

    @property
    def accepts_children(self) -> bool:
        """Indica si se le puede conectar algo: un bus o un MFD con funciones."""
        return self.is_bus or bool(self.subdevice_parent)

    @property
    def is_root(self) -> bool:
        """Indica si es un controlador del propio SoC (no algo que se ha conectado).

        Los controladores raíz ya forman parte del SoC, así que no se
        habilitan ni deshabilitan: solo sirven de anclaje. Los slots con padre
        son dispositivos que el usuario ha conectado.
        """
        return self.parent is None

    @property
    def child_bus(self) -> Optional[str]:
        """Tipo de bus que este controlador ofrece a sus hijos."""
        return self.descriptor.child_bus

    @property
    def display_name(self) -> str:
        """Etiqueta legible del slot (compatible primario o nombre de nodo)."""
        return self.descriptor.display_name or self.descriptor.name

    @property
    def node_name(self) -> str:
        """Nombre del nodo de device tree que representa este slot."""
        return self.descriptor.name

    def add_child(self, child: "PeripheralSlot") -> None:
        """Engancha `child` a este slot, fijando la relación padre/hijo."""
        child.parent = self
        self.children.append(child)

    def iter_descendants(self) -> Iterator["PeripheralSlot"]:
        """Recorre en profundidad todos los descendientes de este slot."""
        for child in self.children:
            yield child
            yield from child.iter_descendants()

    def is_active(self) -> bool:
        """Indica si el slot debe aparecer en el modelo interno generado.

        Un controlador del SoC solo se emite si aloja algo; un dispositivo
        conectado, si está habilitado.
        """
        if self.is_root:
            return any(child.is_active() for child in self.children)
        return self.enabled


def make_connected_slot(
    parent: PeripheralSlot,
    compatible: str,
    child_bus: Optional[str] = None,
    subdevice_parent: Optional[str] = None,
) -> PeripheralSlot:
    """Crea el slot del dispositivo que se conecta a un controlador.

    El nodo resultante cuelga del controlador, hereda su bus como bus padre y
    toma el compatible elegido por el usuario. Si el propio dispositivo ofrece
    un bus (`child_bus`), queda a su vez como controlador y admitirá hijos; si
    lo que ofrece son subnodos propios (`subdevice_parent`, el caso de un MFD),
    admitirá esos.
    """
    node_name = compatible.split(",", 1)[-1]
    descriptor = PeripheralNode(
        name=node_name,
        compatibles=[compatible],
        display_name=compatible,
        parent_bus=parent.child_bus,
        child_bus=child_bus,
        subsystem=parent.descriptor.subsystem,
        path=f"{parent.descriptor.path or parent.node_name}/{node_name}",
    )
    return PeripheralSlot(
        descriptor=descriptor,
        parent=parent,
        enabled=True,
        subdevice_parent=subdevice_parent,
    )


def build_node_from_slot(slot: PeripheralSlot) -> Optional[DeviceTreeNode]:
    """Convierte un slot en `DeviceTreeNode`, o None si no debe generarse.

    Un controlador del SoC solo se emite si aloja algún dispositivo activo (no
    tiene sentido declararlo vacío). Un dispositivo conectado se emite si está
    habilitado, y arrastra consigo lo que cuelgue de él: si además es un bus
    (un mux), sus propios hijos van dentro.
    """
    child_nodes = [
        node
        for node in (build_node_from_slot(child) for child in slot.children)
        if node is not None
    ]

    if slot.is_root:
        if not child_nodes:
            return None

        node = DeviceTreeNode(
            name=slot.node_name,
            label=slot.descriptor.label,
            compatible=list(slot.descriptor.compatibles),
        )
        node.path = slot.descriptor.path
        node.properties["bus"] = slot.child_bus
        node.properties["subsystem"] = slot.descriptor.subsystem
        for child_node in child_nodes:
            node.add_child(child_node)
        return node

    if not slot.enabled:
        return None

    node = DeviceTreeNode(
        name=slot.node_name,
        compatible=list(slot.descriptor.compatibles),
    )
    node.properties["enabled"] = True
    node.properties["parent_bus"] = slot.descriptor.parent_bus
    node.properties["subsystem"] = slot.descriptor.subsystem
    if slot.is_bus:
        node.properties["bus"] = slot.child_bus
    for child_node in child_nodes:
        node.add_child(child_node)
    return node


def build_internal_model(
    soc_profile: SoCProfile, root_slots: List[PeripheralSlot]
) -> InternalDeviceTreeModel:
    """Ensambla el `InternalDeviceTreeModel` a partir de los slots activos."""
    nodes: List[DeviceTreeNode] = []
    for slot in root_slots:
        node = build_node_from_slot(slot)
        if node is not None:
            nodes.append(node)

    return InternalDeviceTreeModel(
        soc_profile=soc_profile,
        selected_peripheral=None,
        selected_binding=None,
        nodes=nodes,
    )


def count_connected_devices(root_slots: List[PeripheralSlot]) -> int:
    """Cuenta cuántos dispositivos hay conectados y habilitados en total."""
    total = 0
    for slot in root_slots:
        for descendant in slot.iter_descendants():
            if descendant.enabled:
                total += 1
    return total
