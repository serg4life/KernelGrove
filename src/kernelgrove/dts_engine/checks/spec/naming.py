"""Nombres: nodos, unit-address, propiedades y etiquetas.

Reglas de la especificación Device Tree v0.4:

- §2.2.1 «Node Name Requirements»: `node-name@unit-address`, 1-31 characters
  del juego permitido y empezando por letra; sin `reg` no debe haber
  `@unit-address`; un node-name sin unit-address no puede coincidir con el
  nombre de una propiedad del mismo nivel.
- §2.2.3.1 «Property Names»: 1-31 characters del juego permitido.
- §6.2 «Labels»: 1-31 characters alfanuméricos o `_`, sin empezar por dígito.
- §6.3 «Node and property definitions»: las propiedades van antes que los
  nodos hijo.
"""

from __future__ import annotations

import string
from typing import Set

from kernelgrove.dts_engine.checks import values
from kernelgrove.dts_engine.checks.context import (
    SpecContext,
    base_name,
    is_reference_node,
    unit_address,
)
from kernelgrove.dts_engine.diagnostics import DiagnosticCode, Severity

MAX_NAME_LENGTH = 31

# La especificación fija el límite de 31 characters para nombres y etiquetas,
# pero ni dtc ni los device trees del kernel lo respetan (hay cientos de
# nombres más largos). Se sigue señalando —es lo que dice la norma— con la
# gravedad más baja, para no ahogar los problemas reales.
_LENGTH_HINT = "§2.2.1 and §2.2.3.1 set 31 characters; dtc does not check it"

# §2.2.1, tabla «Valid characters for node names».
NODE_NAME_CHARS: Set[str] = set(string.ascii_letters + string.digits + ",._+-")

# §2.2.3.1, tabla «Valid characters for property names».
PROPERTY_NAME_CHARS: Set[str] = NODE_NAME_CHARS | {"?", "#"}

# §6.2, tabla «Valid characters for DTS labels».
LABEL_CHARS: Set[str] = set(string.ascii_letters + string.digits + "_")


def check_names(ctx: SpecContext) -> None:
    """Aplica todas las comprobaciones de nombres al árbol."""
    for node in ctx.walk(include_root=True):
        # La raíz no tiene node-name ni etiqueta que validar (§2.2.1), pero sus
        # propiedades y sus hijos sí se comprueban como los de cualquier nodo.
        if node is not ctx.root and not is_reference_node(node):
            _check_node_name(ctx, node)
        _check_label(ctx, node)
        _check_property_names(ctx, node)
        _check_name_clashes(ctx, node)
        _check_property_order(ctx, node)


def _check_node_name(ctx: SpecContext, node) -> None:
    """Valida el `node-name` y la `unit-address` del nodo (§2.2.1)."""
    if "(" in node.name:
        # Nombre generado por una macro de C (`CP11X_NODE_NAME(bus)`): lo que
        # hay en el árbol no es el nombre real, así que no se juzga.
        return

    if node.name.count("@") > 1:
        ctx.report(
            DiagnosticCode.SPEC_NODE_NAME,
            Severity.ERROR,
            f"The name «{node.name}» has more than one «@»",
            node,
            hint="The format is node-name@unit-address (§2.2.1)",
        )
        return

    name = base_name(node)
    address = unit_address(node)

    if not name:
        ctx.report(
            DiagnosticCode.SPEC_NODE_NAME,
            Severity.ERROR,
            f"Node «{node.name}» has no node-name before the «@»",
            node,
            hint="The format is node-name@unit-address (§2.2.1)",
        )
    else:
        if len(name) > MAX_NAME_LENGTH:
            ctx.report(
                DiagnosticCode.SPEC_NODE_NAME,
                Severity.INFO,
                f"The node-name «{name}» is over {MAX_NAME_LENGTH} characters",
                node,
                hint=_LENGTH_HINT,
            )
        invalid = sorted(set(name) - NODE_NAME_CHARS)
        if invalid:
            ctx.report(
                DiagnosticCode.SPEC_NODE_NAME,
                Severity.ERROR,
                (
                    f"The node-name «{name}» uses characters that are not allowed: "
                    f"{' '.join(invalid)}"
                ),
                node,
                hint="§2.2.1: only 0-9 a-z A-Z , . _ + -",
            )
        elif not name[0].isalpha():
            ctx.report(
                DiagnosticCode.SPEC_NODE_NAME,
                Severity.WARNING,
                f"The node-name «{name}» does not start with a letter",
                node,
                hint="§2.2.1: a node-name starts with a letter and names the "
                "class of device",
            )

    if address is None:
        return

    if not address:
        ctx.report(
            DiagnosticCode.SPEC_UNIT_ADDRESS,
            Severity.ERROR,
            f"Node «{node.name}» carries «@» but no unit-address",
            node,
            hint="§2.2.1: with no reg the «@unit-address» is omitted",
        )
        return

    invalid = sorted(set(address) - NODE_NAME_CHARS)
    if invalid:
        ctx.report(
            DiagnosticCode.SPEC_UNIT_ADDRESS,
            Severity.ERROR,
            (
                f"The unit-address «{address}» uses characters that are not allowed: "
                f"{' '.join(invalid)}"
            ),
            node,
            hint="§2.2.1: only 0-9 a-z A-Z , . _ + -",
        )


def _check_label(ctx: SpecContext, node) -> None:
    """Valida la etiqueta del nodo (§6.2)."""
    label = node.label
    if not label or node.name == "/" or values.looks_like_macro_call(label):
        return

    if len(label) > MAX_NAME_LENGTH:
        ctx.report(
            DiagnosticCode.SPEC_LABEL,
            Severity.INFO,
            f"The label «{label}» is over {MAX_NAME_LENGTH} characters",
            node,
            hint=_LENGTH_HINT,
        )

    invalid = sorted(set(label) - LABEL_CHARS)
    if invalid:
        ctx.report(
            DiagnosticCode.SPEC_LABEL,
            Severity.ERROR,
            (
                f"The label «{label}» uses characters that are not allowed: "
                f"{' '.join(invalid)}"
            ),
            node,
            hint="§6.2: only 0-9 a-z A-Z _",
        )
    elif label[0].isdigit():
        ctx.report(
            DiagnosticCode.SPEC_LABEL,
            Severity.ERROR,
            f"The label «{label}» starts with a digit",
            node,
            hint="§6.2: a label cannot start with a number",
        )


def _check_property_names(ctx: SpecContext, node) -> None:
    """Valida los nombres de las propiedades del nodo (§2.2.3.1)."""
    for name in node.properties:
        if values.looks_like_macro_call(name):
            # Una macro que el fichero usa para generar propiedades enteras:
            # sin expandirla no hay nombre que validar (capa 3).
            continue

        if len(name) > MAX_NAME_LENGTH:
            ctx.report(
                DiagnosticCode.SPEC_PROPERTY_NAME,
                Severity.INFO,
                f"The property name «{name}» is over "
                f"{MAX_NAME_LENGTH} characters",
                node,
                property_name=name,
                hint=_LENGTH_HINT,
            )

        invalid = sorted(set(name) - PROPERTY_NAME_CHARS)
        if invalid:
            ctx.report(
                DiagnosticCode.SPEC_PROPERTY_NAME,
                Severity.ERROR,
                (
                    f"The property name «{name}» uses characters that are "
                    f"not allowed: {' '.join(invalid)}"
                ),
                node,
                property_name=name,
                hint="§2.2.3.1: only 0-9 a-z A-Z , . _ + ? # -",
            )


def _check_name_clashes(ctx: SpecContext, node) -> None:
    """Un nodo sin unit-address no puede llamarse como una propiedad (§2.2.1)."""
    if not node.properties:
        return

    for child in node.children:
        if "@" in child.name or is_reference_node(child):
            continue
        if child.name in node.properties:
            ctx.report(
                DiagnosticCode.SPEC_NAME_CLASH,
                Severity.ERROR,
                (
                    f"«{child.name}» is both a node and a property of "
                    f"«{node.name}»"
                ),
                child,
                hint="§2.2.1: a node-name with no unit-address must differ from "
                "the property names at the same level",
            )


def _check_property_order(ctx: SpecContext, node) -> None:
    """Las propiedades van antes que los nodos hijo (§6.3)."""
    if not node.children or not node.properties:
        return

    # Las reaperturas `&label { … }` son sentencias de primer nivel, no hijos
    # declarados dentro del cuerpo del nodo: el parser las cuelga de la raíz,
    # y contarlas haría que toda propiedad escrita después pareciera fuera de
    # sitio.
    child_lines = [
        child.line
        for child in node.children
        if child.line and not is_reference_node(child)
    ]
    if not child_lines:
        return
    first_child_line = min(child_lines)

    for name in node.properties:
        if not set(name) <= PROPERTY_NAME_CHARS:
            # No es un nombre de propiedad: suele ser una construcción que el
            # parser no sabe leer (una macro de C que genera nodos). Ya se
            # avisa de ello en `_check_property_names`; no hay que insistir.
            continue
        line = ctx.property_lines.get((ctx.node_key(node), name))
        if line is not None and line > first_child_line:
            ctx.report(
                DiagnosticCode.SPEC_PROPERTY_ORDER,
                Severity.WARNING,
                (
                    f"The property «{name}» comes after the child nodes of "
                    f"«{node.name}»"
                ),
                node,
                property_name=name,
                hint="§6.3: properties are declared before child nodes",
            )
