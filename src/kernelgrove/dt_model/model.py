from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

# Forma admisible de un `compatible` de device tree: normalmente
# "vendor,modelo" (p. ej. "xlnx,zynqmp-spi"), aunque también existen nombres
# genéricos sin vendor ("simple-bus", "gpio-keys").
COMPATIBLE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9,._+-]*$")


def is_valid_compatible(value: object) -> bool:
    """Comprueba que `value` tenga forma de compatible de device tree.

    El extractor de la ingesta recorre el YAML buscando claves `compatible`
    anidadas y, como último recurso, cualquier `const`/`enum` del documento.
    Eso arrastra ruido que no es un compatible: referencias a schemas
    ("/schemas/types.yaml#/definitions/string"), nombres de propiedad
    ("#mux-control-cells"), expresiones regulares de `patternProperties` y
    hasta descripciones en prosa. Este filtro los descarta.
    """
    return isinstance(value, str) and bool(COMPATIBLE_PATTERN.match(value))


# still under development
BUS_TYPES = [
    "platform",
    "simple-bus",
    "i2c",
    "spi",
    "mmc",
    "mdio",
    "pci",
    "usb",
    "nand",
    "pcie",
]

# List of known controller nodes that can have child peripherals
CONTROLLER_LIST = [
    "i2c",
    "spi",
    "mmc",
    "usb",
    "pci",
    "pcie",
    "nand-controller",
]

# Categorización de bindings por el tipo de bus que ofrecen y del que cuelgan.
#
# Ambas dimensiones son independientes y hay nodos que cumplen las dos: un mux
# I2C cuelga de un bus I2C y a su vez ofrece un bus I2C a sus hijos. Por eso
# no se modelan como una única tupla (parent, child): un mismo `$ref` puede
# aportar solo una de las dos, y hay que recorrer todas las referencias en
# lugar de parar en la primera que encaje.

# $ref del schema -> bus que el nodo ofrece a sus hijos (lo convierte en controlador)
CHILD_BUS_RULES = {
    "i2c-controller.yaml": "i2c",
    "i2c-mux.yaml": "i2c",
    "i2c-gate.yaml": "i2c",
    "spi-controller.yaml": "spi",
    "mdio.yaml": "mdio",
    "simple-bus.yaml": "simple-bus",
    "mmc-controller.yaml": "mmc",
}

# $ref del schema -> bus del que cuelga el nodo
PARENT_BUS_RULES = {
    "spi-peripheral-props.yaml": "spi",
    "i2c-mux.yaml": "i2c",
    "i2c-gate.yaml": "i2c",
}


@dataclass
class DeviceTreeNode:
    """Nodo de árbol format-agnóstico: unidad común entre parser, DB y GUI.

    Representa un nodo de device tree con su compatible, propiedades y
    enlaces padre/hijo. No es DTS ni JSON; es el modelo interno intermedio
    que luego se exporta a otros formatos.
    """

    name: str
    label: Optional[str] = None
    compatible: List[str] = field(default_factory=list)
    properties: Dict[str, object] = field(default_factory=dict)
    children: Optional[List["DeviceTreeNode"]] = field(default_factory=list)
    parent: Optional["DeviceTreeNode"] = field(default=None, repr=False)
    parent_bus: Optional[str] = None
    child_bus: Optional[str] = None
    path: Optional[str] = None
    # Línea del fuente donde se abre el nodo (1-based). Solo la rellena el
    # parser de texto; los árboles rehidratados desde la base de datos no
    # tienen fuente al que apuntar.
    line: Optional[int] = None
    # Clave del fuente que declara el nodo (la del `sources` de la base de
    # datos, o una ruta absoluta si se resolvió en disco). La rellena
    # `IncludeResolver` al parsear cada fichero incluido; los nodos escritos
    # en el documento que se está editando la dejan a None, que es
    # precisamente lo que los distingue. Es lo que permite ir de un `&i2c0`
    # de una placa hasta su declaración en el `.dtsi` del SoC.
    source_key: Optional[str] = None
    # True si el nodo viene de un `#include`/`/include/` fusionado (el
    # `.dtsi` del SoC, o el de cualquier fichero que este a su vez incluya),
    # en vez de haber sido escrito directamente en el documento que se está
    # editando. Lo marca `IncludeResolver` al parsear el fuente incluido, y
    # `merge_device_tree` lo propaga: un nodo ya presente en el `.dtsi` del
    # SoC (un `i2c0`) es "propio del SoC" aunque la placa lo reabra para
    # encenderlo; uno que la placa añade de cero bajo un `&label { … }`
    # (un `rtc@68` colgado de ese mismo `i2c0`) es un chip conectado, no
    # parte del silicio. Ver `gui/widgets/tree_graph.py`.
    soc_defined: bool = False

    def add_child(self, child: "DeviceTreeNode") -> None:
        """Añade `child` a este nodo, enlazando el padre y calculando su path DT."""
        # Link child back to parent and update child's path
        child.parent = self
        if self.path:
            child.path = f"{self.path}/{child.name}"
        else:
            child.path = child.name
        self.children.append(child)

    def find_child(self, name: str) -> Optional["DeviceTreeNode"]:
        """Busca un hijo directo por nombre de nodo o por label."""
        for child in self.children:
            if child.name == name or child.label == name:
                return child
        return None

    def iter_tree(self, include_self: bool = True) -> Iterator["DeviceTreeNode"]:
        """Recorre el subárbol en profundidad, en preorden y orden real de hijos.

        Punto único para lo que cada llamador (visualizador, generador de
        perfiles, motor semántico...) reimplementaba por su cuenta como un
        `walk(node)` local casi idéntico.
        """
        if include_self:
            yield self
        for child in self.children:
            yield from child.iter_tree(include_self=True)

    def clone(self) -> "DeviceTreeNode":
        """Copia profunda del nodo y su subárbol.

        La usa la fusión de includes del visualizador (`merge_device_tree`)
        para no mutar el árbol que comparten el editor y el generador: se
        fusiona sobre una copia, nunca sobre el original.
        """
        copy = DeviceTreeNode(
            name=self.name,
            label=self.label,
            compatible=list(self.compatible),
            properties=dict(self.properties),
            parent_bus=self.parent_bus,
            child_bus=self.child_bus,
            path=self.path,
            line=self.line,
            source_key=self.source_key,
            soc_defined=self.soc_defined,
        )
        for child in self.children:
            copy.add_child(child.clone())
        return copy

    def to_dict(self) -> Dict[str, object]:
        """Serializa el nodo y sus hijos (recursivamente) a un dict apto para JSON."""
        return {
            "name": self.name,
            "label": self.label,
            "compatible": self.compatible,
            "properties": self.properties,
            "children": [child.to_dict() for child in self.children],
            "parent": self.parent.name if self.parent else None,
        }


def merge_device_tree(
    target: DeviceTreeNode, source: DeviceTreeNode, override: bool = False
) -> None:
    """Fusiona `source` dentro de `target`, nodo a nodo por nombre.

    Reproduce lo que hace `/include/`/`#include` en un device tree real: el
    contenido del `.dtsi` incluido pasa a formar parte del árbol en el punto
    de inclusión, y si el fichero que incluye vuelve a abrir el mismo nodo
    (mismo `name`, que ya lleva la `@dirección` si la tiene) sus propiedades
    priman sobre las heredadas. `target` es el árbol del fichero que incluye
    y se modifica in place; `source` es el árbol ya resuelto del `.dtsi`
    incluido, y sus nodos se reenganchan a `target` cuando no hay coincidencia
    (no se copian, así que `source` no debe reutilizarse después).

    `override=True` invierte quién gana: lo usa `resolve_label_overrides`,
    donde `source` es un `&label { … }` / `&{/path} { … }` que reabre un nodo
    para *cambiar* su comportamiento (p. ej. encender un periférico que el
    `.dtsi` del SoC trae apagado), así que sus propiedades deben imponerse en
    vez de rellenar solo lo que falte.

    `soc_defined` se propaga de `source` a `target` sin condición al
    `override`: reabrir con `&i2c0 { status = "okay"; }` un nodo que ya
    venía del `.dtsi` del SoC no le hace perder esa procedencia, y si
    `target` todavía no la tenía marcada (viene de una fusión anterior en la
    que aún no se sabía) la adquiere de `source` en cuanto coincide con algo
    que sí la trae.
    """
    if source.soc_defined and not target.soc_defined:
        target.soc_defined = True
    # Igual que `soc_defined`: quien declara el nodo es el fichero incluido,
    # aunque el que incluye lo reabra para cambiarle una propiedad. Reabrir no
    # es declarar, así que la clave del que ya la tiene no se pisa.
    if target.source_key is None:
        target.source_key = source.source_key
    if override:
        target.properties.update(source.properties)
    else:
        for key, value in source.properties.items():
            target.properties.setdefault(key, value)
    if not target.compatible or override and source.compatible:
        target.compatible = list(source.compatible) or target.compatible
    if target.label is None:
        target.label = source.label

    existing = {child.name: child for child in target.children}
    for child in source.children:
        match = existing.get(child.name)
        if match is not None:
            merge_device_tree(match, child, override=override)
        else:
            target.add_child(child)
            _fix_subtree_paths(child)
            existing[child.name] = child


def resolve_label_overrides(root: DeviceTreeNode) -> None:
    """Resuelve los pseudo-nodos `&label { }` / `&{/path} { }` de `root`.

    El parser no sabe a qué nodo apunta un `&label` o un `&{/path}` (ver
    `dts_engine/parser.py`): lo trata como un nodo nuevo y lo cuelga de la
    raíz con un nombre literal que empieza por `&`. Una vez fusionados los
    includes, aquí se localiza el nodo real -por su label o por su ruta- y el
    contenido del pseudo-nodo se aplica como una modificación de
    comportamiento sobre él, no como un elemento aparte que cuelga de la
    raíz; sus propiedades ganan sobre las ya presentes (`override=True`).

    Los que no se pueden resolver (label que no existe en el árbol fusionado,
    ruta que no aparece) se dejan tal cual: mejor mostrar el hueco que perder
    en silencio lo que el usuario escribió.
    """
    labels = _index_labels(root)

    pending = [child for child in root.children if child.name.startswith("&")]
    for pseudo in pending:
        target = _resolve_reference(root, labels, pseudo.name)
        if target is None or target is pseudo:
            continue
        merge_device_tree(target, pseudo, override=True)
        root.children.remove(pseudo)


def _index_labels(root: DeviceTreeNode) -> Dict[str, DeviceTreeNode]:
    """Etiqueta -> nodo que la lleva, para resolver las referencias `&label`."""
    labels: Dict[str, DeviceTreeNode] = {}
    for node in root.iter_tree():
        if node.label:
            labels.setdefault(node.label, node)
    return labels


def _split_reference_head(path: str) -> Tuple[str, List[str]]:
    """Parte una ruta en (primer segmento, resto), respetando `&{/a/b}`.

    Las llaves de una referencia por ruta contienen barras que no separan
    segmentos, así que no se puede partir por «/» a ciegas.
    """
    if path.startswith("&{"):
        close = path.find("}")
        if close != -1:
            resto = path[close + 1 :].strip("/")
            return (path[: close + 1], [s for s in resto.split("/") if s])
    segments = [s for s in path.split("/") if s]
    if not segments:
        return ("", [])
    return (segments[0], segments[1:])


def _node_at(
    root: DeviceTreeNode, labels: Dict[str, DeviceTreeNode], path: str
) -> Optional[DeviceTreeNode]:
    """Nodo de `root` en esa ruta, resolviendo un `&label` inicial si lo hay.

    El parser cuelga las reaperturas `&i2c0 { … }` de la raíz con ese nombre
    literal, así que la ruta anotada en una directiva escrita dentro de una de
    ellas empieza por «&» y hay que traducirla al nodo real. Ya fusionado el
    árbol el pseudo-nodo no existe, y sin esta traducción no se encontraría
    nada.
    """
    head, rest = _split_reference_head(path)
    if not head:
        return root
    if head.startswith("&"):
        node = _resolve_reference(root, labels, head)
    else:
        node = root.find_child(head)
    for segment in rest:
        if node is None:
            return None
        node = node.find_child(segment)
    return node


def apply_deletions(root: DeviceTreeNode, deletions: Iterable[Any]) -> None:
    """Aplica los `/delete-node/` y `/delete-property/` sobre el árbol fusionado.

    Es lo que hace dtc: lo que se nombra desaparece del árbol, así que sin
    esto las capas de comprobación juzgan nodos y propiedades que el binario
    no tiene —el caso normal es una placa que incluye el `.dtsi` de su SoC y
    apaga de él lo que no lleva—. Se llama **después** de fusionar los
    includes y de plegar las reaperturas `&label`, porque el objetivo casi
    nunca está en el fichero que escribe la directiva.

    El tipo es `Any` a propósito: lo que llega son los `DeleteDirective` del
    parser (`kind`/`target`/`node_path`), y `dt_model` no puede importarlos
    —es `dts_engine` quien depende de él, y esa dirección hay que mantenerla—.

    Techo conocido: se aplican todas al final, no en el orden secuencial en
    que dtc las procesa. Un fuente que borra un nodo y vuelve a declararlo
    después lo perdería; borrar y volver a declarar es raro y el orden
    contrario —declarar, incluir y borrar— es el que se usa de verdad.
    """
    deletions = list(deletions)
    if not deletions:
        return

    labels = _index_labels(root)
    for deletion in deletions:
        container = _node_at(root, labels, deletion.node_path)
        if container is None:
            continue

        target = deletion.target
        if deletion.kind == "property":
            container.properties.pop(target, None)
            continue

        if target.startswith("&"):
            # `/delete-node/ &label;` borra el nodo esté donde esté, no un
            # hijo del nodo en el que está escrita la directiva.
            victim = _resolve_reference(root, labels, target)
        else:
            victim = container.find_child(target)
        if victim is None or victim.parent is None:
            continue
        parent = victim.parent
        if victim in parent.children:
            parent.children.remove(victim)
        if victim.label:
            labels.pop(victim.label, None)


def find_by_reference(
    root: DeviceTreeNode, reference: str
) -> Optional[DeviceTreeNode]:
    """Nodo de `root` al que apunta un `&label` o un `&{/ruta}`, si existe.

    La versión pública de lo que ya usan `resolve_label_overrides` y
    `apply_deletions`. La pide el «ir a la definición» del editor: sobre el
    árbol fusionado, la referencia lleva al nodo real y este sabe de qué
    fichero viene (`source_key`).
    """
    return _resolve_reference(root, _index_labels(root), reference)


def _resolve_reference(
    root: DeviceTreeNode, labels: Dict[str, DeviceTreeNode], reference: str
) -> Optional[DeviceTreeNode]:
    """Localiza el nodo real al que apunta un `&label` o un `&{/path}`."""
    body = reference[1:]
    if body.startswith("{") and body.endswith("}"):
        node = root
        for segment in body[1:-1].split("/"):
            if not segment:
                continue
            node = node.find_child(segment)
            if node is None:
                return None
        return node
    return labels.get(body)


def _fix_subtree_paths(node: DeviceTreeNode) -> None:
    """Recalcula el path de un subárbol tras reengancharlo bajo otro padre.

    `add_child` solo corrige el path del hijo directo; los suyos propios
    siguen arrastrando el path calculado bajo la raíz del fichero incluido.
    """
    for child in node.children:
        child.path = f"{node.path}/{child.name}" if node.path else child.name
        _fix_subtree_paths(child)


@dataclass
class PeripheralNode(DeviceTreeNode):
    """Descriptor de periférico orientado a la GUI, construido sobre `DeviceTreeNode`.

    Añade campos de presentación (`display_name`, `subsystem`) usados al
    listar periféricos seleccionables para un SoC.
    """

    def __init__(
        self,
        name: str,
        label: Optional[str] = None,
        compatibles: List[str] | None = None,
        properties: Dict[str, object] = None,
        children: Optional[List["DeviceTreeNode"]] = None,
        parent: Optional["DeviceTreeNode"] = None,
        parent_bus: Optional[str] = None,
        child_bus: Optional[str] = None,
        display_name: Optional[str] = None,
        subsystem: Optional[str] = None,
        path: Optional[str] = None,
    ):
        """Inicializa el descriptor, delegando los campos comunes en DeviceTreeNode."""
        # map compatibles -> compatible (DeviceTreeNode uses `compatible`)
        super().__init__(
            name,
            label,
            compatibles or [],
            properties or {},
            children or [],
            parent,
            parent_bus or None,
            child_bus or None,
        )
        # high-level UI/descriptor fields
        self.display_name = display_name or (compatibles[0] if compatibles else name)
        self.subsystem = subsystem
        if path is not None:
            self.path = path

    @property
    def node_name(self) -> str:
        """Alias de `name`, usado como etiqueta legible en la GUI."""
        return self.name

    @property
    def compatibles(self) -> List[str]:
        """Alias de `compatible`, con el nombre plural usado por la GUI."""
        return self.compatible


@dataclass
class SoCProfile:
    """Perfil de un SoC: su(s) compatible(s) y la lista de periféricos detectados."""

    soc_name: str
    compatible: List[str]
    peripherals: List[PeripheralNode] = field(default_factory=list)


@dataclass
class InternalDeviceTreeModel:
    """Modelo interno completo que la GUI construye a partir de las selecciones
    del usuario, listo para serializarse y, en el futuro, exportarse a DTS/JSON.
    """

    soc_profile: SoCProfile
    selected_peripheral: Optional[PeripheralNode] = None
    selected_binding: Optional[str] = None
    nodes: List[DeviceTreeNode] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        """Serializa el modelo (perfil de SoC, selecciones y nodos) a un dict JSON."""
        return {
            "soc_name": self.soc_profile.soc_name,
            "compatible": self.soc_profile.compatible,
            "selected_peripheral": self.selected_peripheral.name
            if self.selected_peripheral
            else None,
            "selected_binding": self.selected_binding,
            "nodes": [node.to_dict() for node in self.nodes],
        }
