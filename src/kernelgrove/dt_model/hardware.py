"""Qué hardware describe un device tree: núcleos, RAM, arquitectura y reloj.

Vive en `dt_model` y no en `db_manager` porque lo usan los dos lados: la
ingesta, para guardarlo en `socs`/`boards` y no tener que resolverlo al
pintar una lista de 3700 filas, y la aplicación, para etiquetar la ficha
central del grafo con el árbol que hay abierto. Es una función pura sobre
un `DeviceTreeNode`, que es justo lo que este paquete es.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from kernelgrove.dt_model.model import DeviceTreeNode

_CELLS = re.compile(r"0x[0-9a-fA-F]+|\d+")
_CPU_NODE_NAME = re.compile(r"^cpu(@.*)?$")


def extract_hardware(root: DeviceTreeNode) -> Dict[str, Any]:
    """Qué hardware describe este árbol: arquitectura, núcleos, RAM y reloj.

    Todo sale del propio device tree, que es donde está escrito, y **sin
    resolver includes** —igual que el resto de la ingesta—: una board saca
    de aquí su `/memory` y su `model`, y hereda del SoC que incluye lo que
    su SoC declara (ver `main.inherit_from_socs`).

    - **arquitectura**: el `compatible` del primer `cpu@N`, que es donde el
      device tree escribe el núcleo (`arm,cortex-a9`). Se devuelve tal cual,
      sin maquillarlo: quien lo lea reconoce «arm,cortex-a9» antes que una
      versión inventada de «ARM Cortex-A9».
    - **núcleos**: cuántos `cpu@N` cuelgan de `/cpus`.
    - **RAM**: la suma de los tamaños que declara `/memory` en su `reg`.
    - **reloj**: `clock-frequency` del primer `cpu@N`, en Hz.
    - **modelo**: el `model` de la raíz, que es la descripción en prosa que
      el propio árbol trae («Xilinx Zynq-7000»).
    """
    cpus = root.find_child("cpus")
    nucleos = (
        [child for child in cpus.children if _CPU_NODE_NAME.match(child.name)]
        if cpus is not None
        else []
    )
    primero = nucleos[0] if nucleos else None

    return {
        "arch": _first_compatible(primero),
        "cores": len(nucleos) or None,
        "ram": _memory_bytes(root),
        "clock": _cell_value(primero, "clock-frequency") if primero else None,
        "model": _string_property(root, "model"),
    }


def _first_compatible(node: Optional[DeviceTreeNode]) -> Optional[str]:
    """Primer `compatible` de un nodo, o `None` si no declara ninguno."""
    if node is None or not node.compatible:
        return None
    return node.compatible[0]


def _string_property(node: DeviceTreeNode, name: str) -> Optional[str]:
    """Valor de una propiedad de texto, ya sin las comillas del DTS."""
    value = node.properties.get(name)
    if not isinstance(value, str):
        return None
    limpio = value.strip().strip('"').strip()
    return limpio or None


def _cell_value(node: DeviceTreeNode, name: str) -> Optional[int]:
    """Primer entero de una propiedad `<...>`, o `None` si no se puede leer.

    Solo literales: un valor con macros de `dt-bindings` no se resuelve en
    la ingesta, y adivinarlo sería inventar una frecuencia.
    """
    value = node.properties.get(name)
    if not isinstance(value, str):
        return None
    celdas = _CELLS.findall(value)
    if not celdas:
        return None
    try:
        return int(celdas[0], 0)
    except ValueError:
        return None


def _memory_bytes(root: DeviceTreeNode) -> Optional[int]:
    """Bytes que declaran los nodos `/memory`, sumando sus rangos.

    El `reg` de un `/memory` va en pares dirección/tamaño, así que los
    tamaños son las celdas impares. Se asume una celda por número, que es lo
    que usa la inmensa mayoría de los árboles de 32 bits; con
    `#address-cells = <2>` esto se queda corto y por eso se descarta
    cualquier resultado que no llegue a un mega: mejor no decir nada que
    decir «4 KB de RAM».
    """
    total = 0
    for child in root.children:
        if child.name != "memory" and not child.name.startswith("memory@"):
            continue
        celdas = _CELLS.findall(str(child.properties.get("reg", "")))
        for posicion in range(1, len(celdas), 2):
            try:
                total += int(celdas[posicion], 0)
            except ValueError:
                return None
    return total if total >= 1024 * 1024 else None
