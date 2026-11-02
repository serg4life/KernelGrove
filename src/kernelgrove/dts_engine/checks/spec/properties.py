"""Propiedades estándar: tipo de valor, valores admitidos y obsoletas.

Reglas de la especificación Device Tree v0.4:

- §2.3.1 `compatible`: lista de cadenas, formato recomendado
  «fabricante,modelo» en minúsculas, dígitos y guiones.
- §2.3.2 `model`, §2.3.3 `phandle`, §2.3.4 `status`, §2.3.5
  `#address-cells`/`#size-cells`, §2.3.7 `virtual-reg`, §2.3.8 `ranges`,
  §2.3.9 `dma-ranges`, §2.3.10 `dma-coherent`/`dma-noncoherent`.
- §2.3.11 `name` y §2.3.12 `device_type`: obsoletas.
- §2.4 interrupciones: `interrupts` frente a `interrupts-extended`,
  `#interrupt-cells` en controladores y nexos.

Aquí solo se comprueba lo que el lenguaje define para *cualquier* nodo. Qué
propiedades adicionales exige un dispositivo concreto es cosa de los bindings
(capas 2 y 5 del flujo).
"""

from __future__ import annotations

import re
from typing import Optional, Set

from kernelgrove.dts_engine.checks import values
from kernelgrove.dts_engine.checks.context import SpecContext, base_name
from kernelgrove.dts_engine.diagnostics import DiagnosticCode, Severity

# §2.3.4, tabla «Values for status property».
STATUS_VALUES: Set[str] = {"okay", "disabled", "reserved", "fail"}

# Propiedades cuyo valor es `<empty>`: su presencia es toda la información.
EMPTY_PROPERTIES: Set[str] = {
    "interrupt-controller",  # §2.4.2.2
    "dma-coherent",  # §2.3.10
    "dma-noncoherent",  # §2.3.10
    "hotpluggable",  # §3.4
}

# Propiedades que valen exactamente una celda `<u32>`.
U32_PROPERTIES: Set[str] = {
    "#address-cells",  # §2.3.5
    "#size-cells",  # §2.3.5
    "#interrupt-cells",  # §2.4.2.1
    "phandle",  # §2.3.3
    "virtual-reg",  # §2.3.7
}

# Propiedades que valen una única cadena.
STRING_PROPERTIES: Set[str] = {
    "model",  # §2.3.2
    "status",  # §2.3.4
    "device_type",  # §2.3.12
    "name",  # §2.3.11
    "serial-number",  # §3.2
    "chassis-type",  # §3.2
    "bootargs",  # §3.6
    "stdout-path",  # §3.6
    "stdin-path",  # §3.6
}

# Propiedades cuya cadena es la ruta de un nodo. El §6.3 permite escribirla
# como referencia (`stdout-path = &uart0;`), que dtc expande a la ruta
# completa: no es un error de tipo.
PATH_PROPERTIES: Set[str] = {"stdout-path", "stdin-path"}

# Propiedades obsoletas -> sustituta recomendada (None si no hay).
DEPRECATED_PROPERTIES = {
    "name": "the node-name already identifies the node (§2.3.11)",
    "linux,phandle": "use «phandle» (§2.3.3)",
    "linux,stdout-path": "use «stdout-path» (§3.6)",
}

# §3.2, valores admitidos de `chassis-type`.
CHASSIS_TYPES: Set[str] = {
    "desktop",
    "laptop",
    "convertible",
    "server",
    "all-in-one",
    "tablet",
    "handheld",
    "handset",
    "watch",
    "embedded",
    "television",
    "spectacles",
}

# §2.3.12: `device_type` solo se conserva en nodos cpu y memory.
DEVICE_TYPE_NODES = {"cpu": "cpu", "memory": "memory"}

# `device_type = "pci"` no lo pide la especificación sino el binding del bus
# PCI, que sigue vigente. Señalarlo como obsoleto sería contradecir a la capa
# 2 desde la capa 1, así que se calla.
DEVICE_TYPE_ALLOWED_ELSEWHERE = {"pci"}

# §2.3.1: minúsculas, dígitos y guiones, empezando por letra, con una sola
# coma tras el prefijo del fabricante. Se admiten «.» y «+» en el modelo
# porque son habituales en compatibles genéricos del propio estándar
# (`ethernet-phy-ieee802.3-c22`).
_COMPATIBLE_RE = re.compile(r"^[a-z][a-z0-9.+-]*(,[a-z0-9][a-z0-9.+-]*)?$")


def check_properties(ctx: SpecContext) -> None:
    """Aplica las comprobaciones de propiedades estándar al árbol."""
    for node in ctx.walk(include_root=True):
        for name, value in node.properties.items():
            _check_value_shape(ctx, node, name, value)

        _check_compatible(ctx, node)
        _check_status(ctx, node)
        _check_chassis_type(ctx, node)
        _check_device_type(ctx, node)
        _check_deprecated(ctx, node)
        _check_interrupts(ctx, node)


def _check_value_shape(ctx: SpecContext, node, name: str, value: object) -> None:
    """Comprueba que el valor tenga la forma que el tipo de la propiedad exige."""
    empty = values.is_empty_value(value)
    raw = values.raw_text(value)

    if name in EMPTY_PROPERTIES and not empty:
        ctx.report(
            DiagnosticCode.SPEC_PROPERTY_VALUE,
            Severity.ERROR,
            f"«{name}» takes no value: declaring it is enough",
            node,
            property_name=name,
            hint="Its type is <empty>: the property being there is the datum",
        )
        return

    if empty:
        if name in U32_PROPERTIES or name in STRING_PROPERTIES:
            ctx.report(
                DiagnosticCode.SPEC_PROPERTY_VALUE,
                Severity.ERROR,
                f"«{name}» needs a value",
                node,
                property_name=name,
            )
        return

    if name in U32_PROPERTIES:
        cells = values.cells(raw)
        if cells is None:
            ctx.report(
                DiagnosticCode.SPEC_PROPERTY_VALUE,
                Severity.ERROR,
                f"«{name}» must be a <u32> cell, not {raw!r}",
                node,
                property_name=name,
                hint="It is written in angle brackets: <1>",
            )
        elif len(cells) != 1:
            ctx.report(
                DiagnosticCode.SPEC_PROPERTY_VALUE,
                Severity.ERROR,
                (
                    f"«{name}» must have a single <u32> cell, but has "
                    f"{len(cells)}"
                ),
                node,
                property_name=name,
            )

    elif name in STRING_PROPERTIES:
        if name in PATH_PROPERTIES and values.is_reference(raw):
            return
        strings = values.string_list(raw)
        if strings is None:
            ctx.report(
                DiagnosticCode.SPEC_PROPERTY_VALUE,
                Severity.ERROR,
                f"«{name}» must be a quoted string, not {raw!r}",
                node,
                property_name=name,
            )
        elif len(strings) != 1:
            ctx.report(
                DiagnosticCode.SPEC_PROPERTY_VALUE,
                Severity.ERROR,
                f"«{name}» must be a single string, but has {len(strings)}",
                node,
                property_name=name,
            )

    elif name in {"ranges", "dma-ranges"}:
        if values.cells(raw) is None:
            ctx.report(
                DiagnosticCode.SPEC_PROPERTY_VALUE,
                Severity.ERROR,
                f"«{name}» must be empty or an array of cells, not {raw!r}",
                node,
                property_name=name,
                hint="§2.3.8: triplets <child-address parent-address size>",
            )


def _check_compatible(ctx: SpecContext, node) -> None:
    """Valida el tipo y el formato de `compatible` (§2.3.1)."""
    if "compatible" not in node.properties:
        return

    raw = values.raw_text(node.properties["compatible"])
    strings = values.string_list(raw)
    if strings is None:
        ctx.report(
            DiagnosticCode.SPEC_PROPERTY_VALUE,
            Severity.ERROR,
            f"«compatible» must be a list of strings, not {raw!r}",
            node,
            property_name="compatible",
            hint='§2.3.1: compatible = "manufacturer,model", "…";',
        )
        return

    for item in strings:
        problem = _compatible_problem(item)
        if problem:
            ctx.report(
                DiagnosticCode.SPEC_PROPERTY_VALUE,
                Severity.WARNING,
                f"The compatible «{item}» {problem}",
                node,
                property_name="compatible",
                hint="§2.3.1: «manufacturer,model» in lowercase, digits and hyphens",
            )


def _compatible_problem(item: str) -> Optional[str]:
    """Describe por qué un compatible no sigue el formato recomendado."""
    if not item:
        return "is empty"
    if _COMPATIBLE_RE.match(item):
        return None
    if item.count(",") > 1:
        return "has more than one comma"
    if "_" in item:
        return "uses underscores"
    if any(char.isupper() for char in item):
        return "uses uppercase"
    if not item[0].isalpha():
        return "does not start with a letter"
    return "uses unusual characters"


def _check_status(ctx: SpecContext, node) -> None:
    """Valida el valor de `status` (§2.3.4)."""
    if "status" not in node.properties:
        return

    strings = values.string_list(values.raw_text(node.properties["status"]))
    if not strings or len(strings) != 1:
        return

    status = strings[0]
    if status in STATUS_VALUES or status.startswith("fail-"):
        return

    ctx.report(
        DiagnosticCode.SPEC_PROPERTY_VALUE,
        Severity.ERROR,
        f"«status» does not admit the value «{status}»",
        node,
        property_name="status",
        hint='§2.3.4: "okay", "disabled", "reserved", "fail" or "fail-sss"',
    )


def _check_chassis_type(ctx: SpecContext, node) -> None:
    """Valida el valor de `chassis-type` en la raíz (§3.2)."""
    if node.name != "/" or "chassis-type" not in node.properties:
        return

    strings = values.string_list(values.raw_text(node.properties["chassis-type"]))
    if not strings or len(strings) != 1 or strings[0] in CHASSIS_TYPES:
        return

    ctx.report(
        DiagnosticCode.SPEC_PROPERTY_VALUE,
        Severity.WARNING,
        f"«chassis-type» does not admit the value «{strings[0]}»",
        node,
        property_name="chassis-type",
        hint="§3.2: " + ", ".join(sorted(CHASSIS_TYPES)),
    )


def _check_device_type(ctx: SpecContext, node) -> None:
    """`device_type` solo se conserva en nodos cpu y memory (§2.3.12)."""
    if "device_type" not in node.properties:
        return

    strings = values.string_list(values.raw_text(node.properties["device_type"]))
    if not strings or len(strings) != 1:
        return

    declared = strings[0]
    expected = DEVICE_TYPE_NODES.get(base_name(node))

    if expected is None:
        if declared in DEVICE_TYPE_ALLOWED_ELSEWHERE:
            return
        ctx.report(
            DiagnosticCode.SPEC_DEPRECATED,
            Severity.INFO,
            f"«device_type» is deprecated and «{node.name}» is not a cpu "
            "or memory node",
            node,
            property_name="device_type",
            hint="§2.3.12: it is only kept on cpu and memory nodes",
        )
    elif declared != expected:
        ctx.report(
            DiagnosticCode.SPEC_PROPERTY_VALUE,
            Severity.ERROR,
            (
                f"«device_type» should be «{expected}» on «{node.name}», "
                f"not «{declared}»"
            ),
            node,
            property_name="device_type",
            hint="§3.4 and §3.7.1",
        )


def _check_deprecated(ctx: SpecContext, node) -> None:
    """Avisa de las propiedades marcadas como obsoletas."""
    for name, replacement in DEPRECATED_PROPERTIES.items():
        if name in node.properties:
            ctx.report(
                DiagnosticCode.SPEC_DEPRECATED,
                Severity.WARNING,
                f"The property «{name}» is deprecated",
                node,
                property_name=name,
                hint=replacement,
            )


def _check_interrupts(ctx: SpecContext, node) -> None:
    """Comprueba las reglas de interrupciones del §2.4.

    Lo que exige una propiedad de este nodo (que un controlador declare
    `#interrupt-cells`) se busca en el árbol fusionado: es normal que el
    `.dtsi` ponga las celdas y la placa solo reabra el nodo.
    """
    properties = ctx.effective_properties(node)

    if "interrupts" in properties and "interrupts-extended" in properties:
        ctx.report(
            DiagnosticCode.SPEC_CONFLICTING_PROPERTIES,
            Severity.WARNING,
            "«interrupts» and «interrupts-extended» are mutually exclusive",
            node,
            property_name="interrupts",
            hint="§2.4.1.3: use one or the other; with both, "
            "interrupts-extended wins",
        )

    if "interrupt-controller" in properties and "#interrupt-cells" not in properties:
        ctx.report(
            DiagnosticCode.SPEC_MISSING_PROPERTY,
            Severity.ERROR,
            f"«{node.name}» is an interrupt controller with no "
            "«#interrupt-cells»",
            node,
            property_name="interrupt-controller",
            hint="§2.4.2.1: it says how many cells an interrupt specifier "
            "takes",
            missing=True,
        )

    if "interrupt-map" in properties:
        for required in ("#interrupt-cells", "#address-cells"):
            if required not in properties:
                ctx.report(
                    DiagnosticCode.SPEC_MISSING_PROPERTY,
                    Severity.ERROR,
                    f"«{node.name}» has «interrupt-map» but not «{required}»",
                    node,
                    property_name="interrupt-map",
                    hint="§2.4.3: an interrupt nexus needs both to read the table",
                    missing=True,
                )

    if "interrupt-map-mask" in properties and "interrupt-map" not in properties:
        ctx.report(
            DiagnosticCode.SPEC_PROPERTY_VALUE,
            Severity.WARNING,
            f"«{node.name}» has «interrupt-map-mask» with no «interrupt-map»",
            node,
            property_name="interrupt-map-mask",
            hint="§2.4.3.2: the mask only means anything next to the table",
        )
