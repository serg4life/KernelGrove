"""Overlays: generar el fuente, resolver sus objetivos y ver qué cambian.

Un overlay es un device tree que se declara incompleto y dice a qué nodos de
otro árbol —la **base**— se engancha. No es un formato nuevo: el 96 % de los
del kernel usan `&etiqueta { … }`, que es exactamente lo que
`dt_model.resolve_label_overrides` ya sabe plegar sobre el árbol real. Por eso
aquí no hay ningún motor nuevo, solo tres operaciones sobre el que ya hay:

- **generar** el texto a partir de unos cambios elegidos en la interfaz;
- **resolver** a qué nodo de la base apunta cada bloque, que es la pregunta
  de «¿los símbolos de este fichero existen en el otro?»;
- **previsualizar** qué le haría a la base, comparando el árbol antes y
  después de aplicarlo.

El andamio se genera **una vez** y a partir de ahí el fichero es el modelo:
no se mantiene una representación paralela en memoria que haya que
sincronizar en los dos sentidos. Esa es la razón de que un overlay ajeno se
pueda abrir, editar y guardar sin que la herramienta le quite nada por el
camino.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from kernelgrove.dt_model.model import (
    DeviceTreeNode,
    apply_deletions,
    resolve_label_overrides,
)
from kernelgrove.dts_engine.parser import ParseResult, parse_dts_source

INDENT = "    "

# Cabecera de todo overlay: la versión del formato y la marca de que este
# fichero es un fragmento que se aplica sobre otro árbol.
OVERLAY_HEADER = "/dts-v1/;\n/plugin/;\n"


@dataclass(frozen=True)
class OverlayTarget:
    """A qué nodo de la base apunta un bloque del overlay.

    `reference` es lo que está escrito en el fichero (`&i2c0` o
    `&{/axi/i2c@ff020000}`) y `resolved_path` la ruta del nodo de la base al
    que corresponde, o `None` si no existe — que es justo el error que se
    busca al validar un overlay contra su base.
    """

    reference: str
    line: int
    resolved_path: Optional[str] = None

    @property
    def resolved(self) -> bool:
        """Si el objetivo existe en la base."""
        return self.resolved_path is not None


@dataclass
class PropertyEdit:
    """Una propiedad que el overlay escribe en un nodo de la base.

    `value` es el texto tal cual va a la derecha del `=`, ya con sus
    comillas o sus `<>`: quien lo compone es quien conoce el tipo que
    declara el binding (ver `format_value`). `None` significa propiedad sin
    valor, las que en device tree son una marca por su sola presencia
    (`gpio-controller;`).
    """

    name: str
    value: Optional[str] = None

    def as_line(self, indent: str = INDENT) -> str:
        """La propiedad escrita como línea de DTS."""
        if self.value is None:
            return f"{indent}{self.name};"
        return f"{indent}{self.name} = {self.value};"


@dataclass
class NodeAddition:
    """Un nodo nuevo que el overlay cuelga del objetivo.

    Se anida: un mux I2C que se añade a un bus puede a su vez llevar
    dispositivos colgando, y el asistente deja apuntar a cualquiera de ellos
    para seguir añadiendo dentro. Es la misma estructura del device tree, no
    una lista plana con rutas.
    """

    name: str
    properties: List[PropertyEdit] = field(default_factory=list)
    children: List["NodeAddition"] = field(default_factory=list)

    def find(self, names: Sequence[str]) -> Optional["NodeAddition"]:
        """El descendiente cuya ruta de nombres es `names`, o `None`."""
        node = self
        for name in names:
            for child in node.children:
                if child.name == name:
                    node = child
                    break
            else:
                return None
        return node


@dataclass
class OverlayFragment:
    """Todo lo que el overlay le hace a **un** nodo de la base.

    `target_label` y `target_path` son las dos formas de apuntar, y no son
    intercambiables: por etiqueta solo resuelve si el `.dtb` de la base se
    compiló con `dtc -@`, mientras que por ruta funciona sin símbolos. La
    interfaz elige, y aquí solo se escribe lo que se haya elegido.
    """

    target_label: Optional[str] = None
    target_path: Optional[str] = None
    properties: List[PropertyEdit] = field(default_factory=list)
    added_nodes: List[NodeAddition] = field(default_factory=list)

    def reference(self) -> str:
        """Cómo se escribe el objetivo en el fuente."""
        if self.target_label:
            return f"&{self.target_label}"
        if self.target_path:
            return f"&{{{self.target_path}}}"
        raise ValueError("a fragment needs a target label or path")

    def target_name(self) -> str:
        """Nombre del nodo al que apunta, sin la sintaxis de la referencia.

        Es con lo que se bautiza el fichero generado, así que sale de la
        etiqueta si la hay y del último tramo de la ruta si no: `&i2c0` →
        `i2c0`, `&{/soc/i2c@ff020000}` → `i2c@ff020000`.
        """
        if self.target_label:
            return self.target_label
        if self.target_path:
            return self.target_path.rstrip("/").rsplit("/", 1)[-1]
        raise ValueError("a fragment needs a target label or path")

    def is_empty(self) -> bool:
        """Si no cambia nada; un bloque vacío no se escribe."""
        return not self.properties and not self.added_nodes


def format_value(dt_type: Optional[str], raw: str) -> str:
    """Envuelve un valor según lo que su binding declare.

    En device tree la forma del valor **es** su tipo: entre comillas una
    cadena, entre `<>` una lista de celdas. Escribirlo mal no es un detalle
    de estilo, es otro tipo de dato. Si el texto ya viene envuelto se
    respeta tal cual, para no estropear lo que el usuario haya escrito a
    mano.
    """
    value = raw.strip()
    if not value:
        return '""'
    if value[0] in '"<[' or value.startswith("&"):
        return value

    if dt_type in ("string", "string-array"):
        return f'"{value}"'
    if dt_type in ("phandle", "phandle-array"):
        return f"<{value}>"
    if dt_type is None:
        # Sin tipo declarado se decide por la pinta del valor: lo que parece
        # un número o una macro va en celdas, y el resto entre comillas.
        return f"<{value}>" if _looks_numeric(value) else f'"{value}"'
    return f"<{value}>"


def _looks_numeric(value: str) -> bool:
    """Si el valor parece una celda (número, macro o lista de ellos)."""
    for token in value.replace(",", " ").split():
        if token.startswith("0x"):
            continue
        if token.isdigit():
            continue
        # Una macro de `dt-bindings/*.h` va también entre celdas.
        if token.isupper() and (token.isidentifier() or "(" in token):
            continue
        return False
    return bool(value.split())


def build_overlay_source(
    fragments: Sequence[OverlayFragment],
    includes: Sequence[str] = (),
    description: Optional[str] = None,
) -> str:
    """Escribe el fuente `.dtso` completo de una lista de fragmentos.

    Las cabeceras se emiten como `#include <…>`, nunca con su contenido
    pegado: además de ser lo legible, evita copiar texto de la cabecera
    dentro del fichero del usuario.
    """
    lines: List[str] = []
    if description:
        lines.extend(f"// {line}" for line in description.splitlines())
        lines.append("")
    lines.append(OVERLAY_HEADER.rstrip("\n"))
    if includes:
        lines.append("")
        lines.extend(f"#include <{name}>" for name in includes)

    for fragment in fragments:
        if fragment.is_empty():
            continue
        lines.append("")
        lines.extend(_fragment_lines(fragment))

    return "\n".join(lines) + "\n"


def _fragment_lines(fragment: OverlayFragment) -> List[str]:
    """El bloque `&objetivo { … };` de un fragmento."""
    lines = [f"{fragment.reference()} {{"]
    lines.extend(edit.as_line() for edit in fragment.properties)
    for node in fragment.added_nodes:
        lines.append("")
        lines.extend(_node_lines(node, 1))
    lines.append("};")
    return lines


def _node_lines(node: NodeAddition, depth: int) -> List[str]:
    """Un nodo añadido y todo lo que cuelga de él, sangrado a `depth`."""
    indent = INDENT * depth
    lines = [f"{indent}{node.name} {{"]
    lines.extend(edit.as_line(INDENT * (depth + 1)) for edit in node.properties)
    for child in node.children:
        lines.append("")
        lines.extend(_node_lines(child, depth + 1))
    lines.append(f"{indent}}};")
    return lines


# ----------------------------------------------------------------------
# Resolución de objetivos contra la base
# ----------------------------------------------------------------------
def label_index(base: DeviceTreeNode) -> Dict[str, str]:
    """Etiqueta -> ruta, de todos los nodos de la base.

    Es el equivalente en fuente de la tabla `__symbols__` que `dtc -@`
    escribe en el binario, y es contra lo que se resuelve un `&etiqueta`.
    """
    return {
        node.label: node.path
        for node in base.iter_tree()
        if node.label and node.path
    }


def overlay_targets(
    result: ParseResult, base: Optional[DeviceTreeNode]
) -> List[OverlayTarget]:
    """Objetivos que declara el overlay, resueltos contra la base.

    El parser deja cada bloque `&x { … }` como un pseudo-nodo colgado de la
    raíz con ese nombre literal (ver `dts_engine/parser.py`), así que los
    objetivos son sus hijos de primer nivel. Sin base no se resuelve nada y
    se devuelven sin ruta: no se puede afirmar que un símbolo falte si no
    hay contra qué comprobarlo.
    """
    etiquetas = label_index(base) if base is not None else {}
    targets: List[OverlayTarget] = []
    for node in result.root.children:
        if not node.name.startswith("&"):
            continue
        reference = node.name
        resolved: Optional[str] = None
        if base is not None:
            if reference.startswith("&{") and reference.endswith("}"):
                ruta = reference[2:-1]
                resolved = ruta if _path_exists(base, ruta) else None
            else:
                resolved = etiquetas.get(reference[1:])
        targets.append(
            OverlayTarget(
                reference=reference, line=node.line or 1, resolved_path=resolved
            )
        )
    return targets


def _path_exists(base: DeviceTreeNode, path: str) -> bool:
    """Si la base tiene un nodo en esa ruta absoluta."""
    objetivo = path.strip("/")
    return any(
        (node.path or "").strip("/") == objetivo for node in base.iter_tree()
    )


# ----------------------------------------------------------------------
# Previsualización
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class OverlayChange:
    """Un cambio concreto que el overlay le hace a la base."""

    path: str
    kind: str  # "node-added" | "property-added" | "property-changed"
    name: Optional[str] = None
    before: Optional[str] = None
    after: Optional[str] = None


def preview_overlay(
    base: DeviceTreeNode, overlay: ParseResult
) -> Tuple[DeviceTreeNode, List[OverlayChange]]:
    """Aplica el overlay sobre una copia de la base y dice qué ha cambiado.

    Devuelve el árbol resultante —el que dibujaría el grafo— y la lista de
    cambios. Aplicar es exactamente lo que ya hace el visualizador con los
    bloques `&etiqueta` de una board sobre su SoC: injertar los pseudo-nodos
    y dejar que `resolve_label_overrides` los funda en el nodo real.

    La base **no se toca**: se clona antes.
    """
    antes = _snapshot(base)

    resultado = base.clone()
    for pseudo in overlay.root.children:
        if pseudo.name.startswith("&"):
            resultado.add_child(pseudo.clone())
    resolve_label_overrides(resultado)
    apply_deletions(resultado, overlay.deletions)

    despues = _snapshot(resultado)
    return resultado, _diff(antes, despues)


def _snapshot(root: DeviceTreeNode) -> Dict[str, Dict[str, object]]:
    """Ruta -> propiedades, para poder comparar dos versiones del árbol.

    Se dejan fuera los pseudo-nodos `&x` que no se hayan podido resolver:
    `resolve_label_overrides` los abandona colgando de la raíz cuando la
    etiqueta no existe, y contarlos como «nodo añadido» sería enseñar dos
    veces el mismo problema —la capa 6 ya lo reporta como error, y ahí sí
    con el nombre y la línea.
    """
    return {
        (node.path or "/"): dict(node.properties)
        for node in root.iter_tree()
        if not (node.path or "").lstrip("/").startswith("&")
    }


def _diff(
    antes: Dict[str, Dict[str, object]], despues: Dict[str, Dict[str, object]]
) -> List[OverlayChange]:
    """Compara dos instantáneas y describe qué añadió o cambió el overlay.

    No se buscan nodos borrados: un overlay puede marcar un nodo como
    deshabilitado (`status = "disabled"`), que aparece como propiedad
    cambiada, pero quitarlo del árbol no está entre lo que esta herramienta
    genera.
    """
    cambios: List[OverlayChange] = []
    for path in sorted(despues):
        propiedades = despues[path]
        if path not in antes:
            cambios.append(OverlayChange(path=path, kind="node-added"))
            continue
        previas = antes[path]
        for name in sorted(propiedades):
            nuevo = propiedades[name]
            if name not in previas:
                cambios.append(
                    OverlayChange(
                        path=path,
                        kind="property-added",
                        name=name,
                        after=_as_text(nuevo),
                    )
                )
            elif previas[name] != nuevo:
                cambios.append(
                    OverlayChange(
                        path=path,
                        kind="property-changed",
                        name=name,
                        before=_as_text(previas[name]),
                        after=_as_text(nuevo),
                    )
                )
    return cambios


def _as_text(value: object) -> str:
    """Texto de una propiedad, con la marca de las que no llevan valor."""
    return "(marca)" if value is True else str(value)


def parse_overlay(text: str) -> ParseResult:
    """Parsea un overlay. Es el mismo parser: un overlay no es otro idioma."""
    return parse_dts_source(text)
