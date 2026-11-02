"""Contexto compartido por las comprobaciones de todas las capas.

Reúne lo que todas necesitan: el árbol del documento, el árbol con los
includes ya fusionados (si quien llama ha podido construirlo), la línea de
cada propiedad —para señalar el aviso donde está escrito y no en la cabecera
del nodo— y la política de qué se puede afirmar que *falta*.

**Presencia y localización son cosas distintas.** Si una propiedad existe se
mira en el árbol fusionado, porque un `#include` aporta nodos y propiedades
igual que si estuvieran escritos aquí. Dónde se avisa se decide siempre sobre
el árbol del documento, que es el único cuyas líneas corresponden al texto
que el usuario tiene delante.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from kernelgrove.dt_model.model import DeviceTreeNode
from kernelgrove.dts_engine.diagnostics import Diagnostic, DiagnosticCode, Severity

# Nodos que el parser fabrica al encontrar `&label { … }` o `&{/ruta} { … }`:
# no son nodos nuevos, sino la reapertura de uno existente. Su «nombre» no es
# un node-name y no debe validarse como tal.
REFERENCE_PREFIX = "&"

# Propiedades cuyo valor valida la capa 1 con la especificación en la mano
# (ver `spec/properties.py`). Las capas que vienen después no vuelven a
# mirarlas aunque un binding las restrinja: el aviso sería el mismo dos veces
# y con menos autoridad.
SPEC_OWNED_PROPERTIES = frozenset(
    {
        "compatible",
        "model",
        "name",
        "phandle",
        "linux,phandle",
        "status",
        "device_type",
        "#address-cells",
        "#size-cells",
        "#interrupt-cells",
        "virtual-reg",
    }
)

# Al rebajar un diagnóstico que no es concluyente se baja un escalón.
_DOWNGRADE = {Severity.ERROR: Severity.WARNING, Severity.WARNING: Severity.INFO}


@dataclass
class SpecContext:
    """Estado común de una pasada de comprobaciones."""

    root: DeviceTreeNode
    # (ruta del nodo, propiedad) -> línea, tal y como lo da el parser.
    property_lines: Dict[Tuple[str, str], int] = field(default_factory=dict)
    # Texto del fuente, para las reglas que son de fichero y no de árbol.
    text: Optional[str] = None
    # Un `.dtsi` es un trozo: lo que falta puede aportarlo quien lo incluya.
    fragment: bool = False
    # Árbol del documento con el contenido de sus includes ya fusionado. Es lo
    # que hay que mirar para saber si algo existe; None si no se ha resuelto.
    merged_root: Optional[DeviceTreeNode] = None
    # False si algún include de device tree no se ha podido fusionar: entonces
    # lo que parece ausente puede estar en él.
    includes_resolved: bool = True
    # Si `/dts-v1/;` aparece en el documento o en alguno de sus includes. Solo
    # lo sabe quien resuelve los includes; None significa «no consta».
    dts_version_seen: Optional[bool] = None
    # El documento incluye otros device trees, de los que hereda tanto nodos
    # como las directivas de fichero.
    includes_device_tree: bool = False
    # Acceso a los bindings, cuando la capa que corre lo necesita (capas 2 y
    # 5). Vive aquí porque codificar el valor de una propiedad requiere saber
    # su tipo, y eso lo hacen las dos capas por igual. La capa 1 lo ignora.
    schema_lookup: Optional[object] = None
    # Valor ya resuelto (por `cpp`, en la ingesta) de las macros que este
    # documento ve por sus propios includes. Lo usa `checks/bindings/
    # instance.py` para codificar celdas como `<GIC_SPI 42
    # IRQ_TYPE_LEVEL_HIGH>` en vez de descartarlas: sin esto son invisibles
    # para las capas 2 y 5, que nunca llegan a comprobar su rango o su enum.
    local_macro_values: Mapping[str, int] = field(default_factory=dict)

    diagnostics: List[Diagnostic] = field(default_factory=list)
    _merged_index: Optional[Dict[str, DeviceTreeNode]] = field(
        default=None, repr=False
    )
    _label_index: Dict[str, DeviceTreeNode] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------
    # Qué se puede afirmar que falta
    # ------------------------------------------------------------------
    def missing_is_conclusive(self, node: DeviceTreeNode) -> Optional[str]:
        """Devuelve None si se puede afirmar que a `node` le falta algo.

        Si no, devuelve el motivo por el que no es concluyente, que se añade
        como pista al diagnóstico rebajado. Son tres situaciones distintas:
        el documento es un fragmento, tiene includes que no se han podido
        fusionar, o el nodo concreto es la reapertura de otro definido fuera.
        """
        if self.fragment:
            return "in a .dtsi the including file may provide it"
        if not self.includes_resolved:
            return "an include that could not be resolved may provide it"
        if under_reference(node) and self._merged_node(node) is None:
            # Una reapertura `&label { … }` sí es concluyente cuando el nodo
            # original aparece en el árbol fusionado: entonces se ve todo lo
            # que tiene. Solo cuando no se localiza hay que rebajar.
            return "the node is defined in another file; here it is only reopened"
        return None

    def is_partial_view(self, node: DeviceTreeNode) -> bool:
        """Indica si del nodo solo se está viendo un trozo.

        Un `&gpio1 { gpio-line-names = …; }` no describe un nodo entero: son
        los retoques que un fichero le hace a uno definido en otro sitio. No
        se ve entero en dos casos: cuando la referencia no se resuelve, y
        cuando el documento es un fragmento —ahí el original puede estar en
        cualquiera de los ficheros que lo incluyan, y lo que se fusione aquí
        es, como mucho, una parte.

        Las capas que hablan de bindings se callan entonces en vez de rebajar
        el aviso: decir «puede que falte `#gpio-cells`» sobre un `&gpio1` de
        un `.dtsi` es ruido garantizado, no una duda razonable.
        """
        if not under_reference(node):
            return False
        return self.fragment or self._merged_node(node) is None

    @property
    def is_complete_document(self) -> bool:
        """Indica si se puede juzgar el documento como un device tree entero.

        Hacen falta dos cosas para que las reglas del documento completo
        (nodo raíz, `/cpus`, `/memory`, `/dts-v1/;`) signifiquen algo: que no
        sea un `.dtsi` —un trozo del árbol de otro— y que se vea el árbol
        completo, es decir, que no declare includes o que estén fusionados.
        Sin lo segundo, una placa que hereda medio árbol de su `.dtsi`
        parecería vacía.
        """
        if self.fragment:
            return False
        return self.merged_root is not None or not self.includes_device_tree

    # ------------------------------------------------------------------
    # Presencia: siempre sobre el árbol fusionado
    # ------------------------------------------------------------------
    def effective_properties(self, node: DeviceTreeNode) -> Mapping[str, object]:
        """Propiedades del nodo contando las que aportan sus includes."""
        merged = self._merged_node(node)
        if merged is None or merged is node:
            return node.properties
        combined = dict(merged.properties)
        combined.update(node.properties)
        return combined

    def effective_children(self, node: DeviceTreeNode) -> Sequence[DeviceTreeNode]:
        """Hijos del nodo contando los que aportan sus includes."""
        merged = self._merged_node(node)
        if merged is None or merged is node:
            return node.children
        known = {child.name for child in node.children}
        return list(node.children) + [
            child for child in merged.children if child.name not in known
        ]

    def merged_node(self, node: DeviceTreeNode) -> Optional[DeviceTreeNode]:
        """Devuelve el nodo equivalente en el árbol fusionado, si lo hay.

        Hace falta fuera del contexto para saber de quién cuelga *de verdad*
        un nodo: un `&usb_dwc3_0 { … }` está escrito colgando de la raíz, pero
        su sitio real está dentro del `soc`, que es quien decide cuántas
        celdas ocupa una dirección.
        """
        return self._merged_node(node)

    def _merged_node(self, node: DeviceTreeNode) -> Optional[DeviceTreeNode]:
        """Busca el nodo equivalente en el árbol fusionado.

        Primero por ruta, que es el caso normal. Si el nodo está escrito bajo
        una reapertura `&label { … }` su ruta no existe en el árbol fusionado
        —ahí el contenido ya se ha plegado sobre el nodo real— así que se
        resuelve la referencia igual que hizo la fusión: por etiqueta o por
        ruta, y luego bajando por los nombres de los hijos.
        """
        if self.merged_root is None:
            return None
        if self._merged_index is None:
            self._build_indexes()
        direct = self._merged_index.get(node.path or node.name)
        if direct is not None:
            return direct
        return self._merged_by_reference(node)

    def _build_indexes(self) -> None:
        """Indexa el árbol fusionado por ruta y por etiqueta."""
        self._merged_index = {}
        stack = [self.merged_root]
        while stack:
            current = stack.pop()
            if current is None:
                continue
            self._merged_index[current.path or current.name] = current
            if current.label:
                self._label_index.setdefault(current.label, current)
            stack.extend(current.children)

    def _merged_by_reference(
        self, node: DeviceTreeNode
    ) -> Optional[DeviceTreeNode]:
        """Localiza en el árbol fusionado un nodo escrito bajo una reapertura."""
        segments: List[str] = []
        current: Optional[DeviceTreeNode] = node
        while current is not None and not is_reference_node(current):
            segments.append(current.name)
            current = current.parent
        if current is None:
            return None

        target = self._reference_target(current.name)
        for name in reversed(segments):
            if target is None:
                return None
            target = target.find_child(name)
        return target

    def _reference_target(self, reference: str) -> Optional[DeviceTreeNode]:
        """Nodo al que apunta un `&label` o un `&{/ruta}` del documento."""
        body = reference[1:]
        if body.startswith("{") and body.endswith("}"):
            node = self.merged_root
            for segment in body[1:-1].split("/"):
                if not segment:
                    continue
                if node is None:
                    return None
                node = node.find_child(segment)
            return node
        return self._label_index.get(body)

    # ------------------------------------------------------------------
    # Localización
    # ------------------------------------------------------------------
    def node_key(self, node: DeviceTreeNode) -> str:
        """Clave con la que el parser indexó las propiedades del nodo."""
        return node.path or node.name

    def line_of(self, node: DeviceTreeNode, property_name: str) -> int:
        """Línea donde se escribió una propiedad, o la del nodo si no consta."""
        line = self.property_lines.get((self.node_key(node), property_name))
        return line or node.line or 1

    # ------------------------------------------------------------------
    # Emisión
    # ------------------------------------------------------------------
    def report(
        self,
        code: DiagnosticCode,
        severity: Severity,
        message: str,
        node: DeviceTreeNode,
        *,
        property_name: Optional[str] = None,
        hint: Optional[str] = None,
        missing: bool = False,
    ) -> None:
        """Añade un diagnóstico situado en el nodo o en una de sus propiedades.

        Con `missing=True` el diagnóstico afirma que algo falta: si el
        documento no permite afirmarlo se rebaja un escalón de gravedad y se
        explica por qué, en lugar de callarlo (que era lo que dejaba sin
        comprobar prácticamente todos los ficheros reales) o de afirmarlo con
        una seguridad que no se tiene.
        """
        if missing:
            reason = self.missing_is_conclusive(node)
            if reason is not None:
                severity = _DOWNGRADE.get(severity, severity)
                hint = f"{hint}; {reason}" if hint else reason[0].upper() + reason[1:]

        line = (
            self.line_of(node, property_name)
            if property_name is not None
            else (node.line or 1)
        )
        self.diagnostics.append(
            Diagnostic(
                code=code,
                severity=severity,
                message=message,
                line=line,
                node_path=node.path,
                hint=hint,
                property_name=property_name,
            )
        )

    # ------------------------------------------------------------------
    # Recorrido
    # ------------------------------------------------------------------
    def walk(self, include_root: bool = False) -> Iterator[DeviceTreeNode]:
        """Recorre el árbol del documento en profundidad.

        Nunca el fusionado: solo los nodos escritos aquí tienen una línea a la
        que apuntar en el editor.
        """
        yield from self.root.iter_tree(include_self=include_root)


def is_reference_node(node: DeviceTreeNode) -> bool:
    """Indica si el nodo es la reapertura de otro por referencia."""
    return node.name.startswith(REFERENCE_PREFIX)


def under_reference(node: DeviceTreeNode) -> bool:
    """Indica si el nodo desciende de una reapertura `&label { … }`."""
    current: Optional[DeviceTreeNode] = node
    while current is not None:
        if is_reference_node(current):
            return True
        current = current.parent
    return False


def base_name(node: DeviceTreeNode) -> str:
    """Devuelve el node-name sin la `@unit-address`."""
    return node.name.split("@", 1)[0]


def unit_address(node: DeviceTreeNode) -> Optional[str]:
    """Devuelve la `unit-address` del nodo, o None si no la lleva."""
    if "@" not in node.name:
        return None
    return node.name.split("@", 1)[1]


def build_context(
    result,
    *,
    text: Optional[str] = None,
    fragment: bool = False,
    merged_root: Optional[DeviceTreeNode] = None,
    includes_resolved: bool = True,
    dts_version_seen: Optional[bool] = None,
    schema_lookup: Optional[object] = None,
    local_macro_values: Optional[Mapping[str, int]] = None,
) -> SpecContext:
    """Construye el contexto de una pasada a partir de lo que dio el parser.

    Lo usan por igual todas las capas: el árbol, las líneas de cada
    propiedad y la política de qué se puede afirmar que falta son los mismos
    hable quien hable.
    """
    return SpecContext(
        root=result.root,
        property_lines=result.property_lines,
        text=text,
        fragment=fragment,
        merged_root=merged_root,
        includes_resolved=includes_resolved,
        dts_version_seen=dts_version_seen,
        includes_device_tree=any(
            not include.is_header for include in result.includes
        ),
        schema_lookup=schema_lookup,
        local_macro_values=local_macro_values or {},
    )
