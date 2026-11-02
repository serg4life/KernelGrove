"""Localización de los nodos conectables de un árbol de device tree.

Sobre un árbol ya parseado se buscan los nodos *controladores*: los que
exponen un bus y por tanto admiten que se les conecte un periférico. El árbol
llega siempre del parser (`KernelGroveService.soc_profile_from_tree`), nunca de una
copia serializada en la base: `socs`/`boards` guardan la ruta del fuente, y el
fuente entero vive en `sources`.
"""

from __future__ import annotations

from typing import List, Optional

from kernelgrove.api.database import BindingsDatabase
from kernelgrove.dt_model.model import CONTROLLER_LIST, DeviceTreeNode, PeripheralNode


def is_valid_compatible(compatible: str) -> bool:
    """Valida que un compatible tenga el formato "vendor,dispositivo"."""
    return isinstance(compatible, str) and "," in compatible


def _bus_for_node(
    node: DeviceTreeNode, db: BindingsDatabase
) -> Optional[tuple[str, Optional[str], Optional[str]]]:
    """Determina si `node` es un controlador y devuelve (child_bus, subsystem, compat).

    Primero consulta la base de datos con el compatible primario del nodo: si
    el binding declara `child_bus`, el nodo admite hijos. Si el compatible no
    está registrado, se recurre al nombre del nodo (`i2c@ff020000` -> `i2c`)
    contrastándolo con `CONTROLLER_LIST`. Devuelve None si el nodo no puede
    tener hijos.
    """
    compatibles = [c for c in node.compatible if is_valid_compatible(c)]
    node_prefix = node.name.split("@", 1)[0].lower()

    if compatibles:
        primary = compatibles[0]
        (
            _vendor,
            _title,
            binding_id,
            subsystem,
            _parent_bus,
            child_bus,
            _description,
        ) = db.get_binding_info(primary)

        if binding_id and child_bus:
            return (child_bus, subsystem, primary)

        if not binding_id and node_prefix in CONTROLLER_LIST:
            # El compatible no está en la base de datos, pero el nombre del
            # nodo identifica un controlador conocido.
            return (node_prefix, node_prefix, primary)

        return None

    if node_prefix in CONTROLLER_LIST:
        return (node_prefix, node_prefix, None)

    return None


def extract_connectable_nodes(
    root: DeviceTreeNode, db: BindingsDatabase
) -> List[PeripheralNode]:
    """Devuelve los nodos del árbol que pueden alojar periféricos hijos.

    Son los controladores de bus (un SPI, un I2C, un MDIO...): los únicos en
    los que tiene sentido ofrecer un desplegable para elegir qué se conecta.
    """
    found: List[PeripheralNode] = []
    for node in root.iter_tree():
        if node.name == "/":
            continue
        bus = _bus_for_node(node, db)
        if bus is None:
            continue
        child_bus, subsystem, primary = bus
        found.append(
            PeripheralNode(
                name=node.name,
                label=node.label,
                compatibles=[c for c in node.compatible if is_valid_compatible(c)],
                properties=node.properties,
                parent=node.parent,
                child_bus=child_bus,
                display_name=primary or node.name,
                subsystem=subsystem,
                path=node.path,
            )
        )
    return found
