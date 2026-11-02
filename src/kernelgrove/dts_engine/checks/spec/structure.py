"""Estructura del documento: nodo raíz, nodos obligatorios y formato DTS.

Reglas de la especificación Device Tree v0.4:

- §3.1: todo device tree tiene un nodo raíz, un `/cpus` y al menos un
  `/memory`.
- §3.2: la raíz declara `#address-cells`, `#size-cells`, `model` y
  `compatible`.
- §3.3: los nombres de alias de `/aliases` son minúsculas, dígitos y guiones,
  y su valor es la ruta completa a un nodo.
- §3.4: un nodo `memory` declara `device_type = "memory"` y `reg`.
- §3.7 y §3.8: `/cpus` declara `#address-cells` y `#size-cells = <0>`; cada
  `cpu` declara `device_type = "cpu"` y `reg`.
- §6.4: un fichero DTS versión 1 empieza por `/dts-v1/;`.

Hay dos clases de exigencia y no se tratan igual:

- **Del documento entero** (raíz, `/cpus`, `/memory`, `/dts-v1/;`): solo
  significan algo en un device tree completo, así que en un `.dtsi` —que es
  un trozo del árbol de otro— no se comprueban.
- **De un nodo concreto** (un `cpu` sin `reg`, un `memory` sin `device_type`):
  el nodo está escrito en este fichero, así que la comprobación vale siempre;
  si el documento no permite ser concluyente, el aviso se rebaja en vez de
  callarse (`SpecContext.report(..., missing=True)`).

La presencia se consulta con `effective_properties`/`effective_children`, que
cuentan lo que aportan los includes ya fusionados.
"""

from __future__ import annotations

import string
from typing import List, Set

from kernelgrove.dt_model.model import DeviceTreeNode
from kernelgrove.dts_engine.checks import values
from kernelgrove.dts_engine.checks.context import SpecContext, base_name
from kernelgrove.dts_engine.diagnostics import DiagnosticCode, Severity

# §3.2, propiedades obligatorias del nodo raíz.
ROOT_REQUIRED = ("#address-cells", "#size-cells", "model", "compatible")

# §3.3, tabla «Valid characters for alias names».
ALIAS_CHARS: Set[str] = set(string.ascii_lowercase + string.digits + "-")

MAX_ALIAS_LENGTH = 31

# Nodos que cuelgan de `/cpus` sin ser CPUs.
NON_CPU_CHILDREN = {"cpu-map", "idle-states", "domain-idle-states"}


def check_structure(ctx: SpecContext) -> None:
    """Aplica las comprobaciones de estructura al documento."""
    _check_aliases(ctx)
    _check_memory_nodes(ctx)
    _check_cpus(ctx)

    if not ctx.is_complete_document:
        return

    _check_dts_version(ctx)
    _check_root_properties(ctx)
    _check_required_nodes(ctx)


def _check_dts_version(ctx: SpecContext) -> None:
    """Un `.dts` completo se identifica con `/dts-v1/;` (§6.4).

    `dtc` ve el texto de todos los ficheros pegados, así que la marca vale
    esté donde esté: hay placas que la heredan del `.dtsi` que incluyen. Si
    nadie ha mirado dentro de los includes (`dts_version_seen` sin fijar) y el
    documento incluye device trees, no se puede afirmar que falte.
    """
    if ctx.text is None:
        return

    if ctx.dts_version_seen is None:
        if ctx.includes_device_tree or "/dts-v1/" in ctx.text:
            return
    elif ctx.dts_version_seen:
        return

    ctx.report(
        DiagnosticCode.SPEC_DTS_VERSION,
        Severity.ERROR,
        "The file does not start with «/dts-v1/;»",
        ctx.root,
        hint="§6.4: without that marker dtc treats it as DTS version 0",
        missing=True,
    )


def _check_root_properties(ctx: SpecContext) -> None:
    """La raíz declara model, compatible y los anchos de dirección (§3.2)."""
    present = ctx.effective_properties(ctx.root)
    for required in ROOT_REQUIRED:
        if required not in present:
            ctx.report(
                DiagnosticCode.SPEC_MISSING_PROPERTY,
                Severity.ERROR,
                f"The root node does not declare «{required}»",
                ctx.root,
                hint="§3.2: it is required at the root",
                missing=True,
            )


def _check_required_nodes(ctx: SpecContext) -> None:
    """Todo device tree tiene `/cpus` y al menos un `/memory` (§3.1).

    La memoria se avisa un escalón por debajo: la especificación la exige,
    pero en las placas reales es corriente que la escriba el cargador de
    arranque, y el `.dts` no la declara a propósito.
    """
    names = {base_name(child) for child in ctx.effective_children(ctx.root)}

    if "cpus" not in names:
        ctx.report(
            DiagnosticCode.SPEC_MISSING_NODE,
            Severity.ERROR,
            "The «/cpus» node is missing",
            ctx.root,
            hint="§3.1: it is required in every device tree",
            missing=True,
        )

    if "memory" not in names:
        ctx.report(
            DiagnosticCode.SPEC_MISSING_NODE,
            Severity.WARNING,
            "The «/memory» node is missing",
            ctx.root,
            hint="§3.1: at least one memory node is needed, though the boot "
            "loader often adds it",
            missing=True,
        )


def _check_aliases(ctx: SpecContext) -> None:
    """Valida los nombres y valores de `/aliases` (§3.3)."""
    for node in _root_children_named(ctx, "aliases"):
        for name, value in node.properties.items():
            invalid = sorted(set(name) - ALIAS_CHARS)
            if invalid:
                ctx.report(
                    DiagnosticCode.SPEC_PROPERTY_NAME,
                    Severity.ERROR,
                    (
                        f"The alias «{name}» uses characters that are not allowed: "
                        f"{' '.join(invalid)}"
                    ),
                    node,
                    property_name=name,
                    hint="§3.3: only lowercase, digits and hyphens",
                )
            elif len(name) > MAX_ALIAS_LENGTH:
                ctx.report(
                    DiagnosticCode.SPEC_PROPERTY_NAME,
                    Severity.ERROR,
                    f"The alias «{name}» is over {MAX_ALIAS_LENGTH} characters",
                    node,
                    property_name=name,
                    hint="§3.3: between 1 and 31 characters",
                )

            raw = values.raw_text(value)
            if values.is_empty_value(value) or values.cells(raw) is not None:
                ctx.report(
                    DiagnosticCode.SPEC_PROPERTY_VALUE,
                    Severity.ERROR,
                    f"The alias «{name}» must be the path of a node",
                    node,
                    property_name=name,
                    hint='§3.3: serial0 = "/soc/serial@0" or serial0 = &uart0;',
                )


def _check_memory_nodes(ctx: SpecContext) -> None:
    """Un nodo `memory` declara `device_type` y `reg` (§3.4)."""
    for node in ctx.walk():
        if base_name(node) != "memory" or node.parent is not ctx.root:
            continue

        present = ctx.effective_properties(node)
        if "device_type" not in present:
            ctx.report(
                DiagnosticCode.SPEC_MISSING_PROPERTY,
                Severity.ERROR,
                f"Node «{node.name}» does not declare «device_type»",
                node,
                hint='§3.4: a memory node declares device_type = "memory"',
                missing=True,
            )

        if "reg" not in present:
            ctx.report(
                DiagnosticCode.SPEC_MISSING_PROPERTY,
                Severity.WARNING,
                f"Node «{node.name}» does not declare «reg»",
                node,
                hint="§3.4: it is required, though it is often the boot loader "
                "that fills it in",
                missing=True,
            )


def _check_cpus(ctx: SpecContext) -> None:
    """Valida `/cpus` y sus hijos `cpu` (§3.7 y §3.8)."""
    for node in _root_children_named(ctx, "cpus"):
        present = ctx.effective_properties(node)

        size_cells = present.get("#size-cells")
        if size_cells is not None:
            cells = values.cells(values.raw_text(size_cells))
            declared = values.number(cells[0]) if cells and len(cells) == 1 else None
            if declared is not None and declared != 0:
                ctx.report(
                    DiagnosticCode.SPEC_PROPERTY_VALUE,
                    Severity.ERROR,
                    f"«/cpus» declares «#size-cells = <{cells[0]}>» and it must be <0>",
                    node,
                    property_name="#size-cells",
                    hint="§3.7: cpu nodes carry no size in their reg",
                )

        for required, explanation in (
            ("#address-cells", "§3.7: it says how many cells each cpu's reg takes"),
            ("#size-cells", "§3.7: it is required and its value is <0>"),
        ):
            if required not in present:
                ctx.report(
                    DiagnosticCode.SPEC_MISSING_PROPERTY,
                    Severity.ERROR,
                    f"«/cpus» does not declare «{required}»",
                    node,
                    hint=explanation,
                    missing=True,
                )

        for child in node.children:
            _check_cpu_node(ctx, child)


def _check_cpu_node(ctx: SpecContext, node: DeviceTreeNode) -> None:
    """Valida un nodo `cpu` colgado de `/cpus` (§3.8).

    De `/cpus` cuelgan también nodos auxiliares (`cpu-map`, `l2-cache`,
    `idle-states`…) que no son CPUs. Se considera CPU la que lo declara con
    `device_type = "cpu"` o la que se llama `cpu`, que es lo que la
    especificación pide.
    """
    name = base_name(node)
    present = ctx.effective_properties(node)

    declared = values.string_list(values.raw_text(present.get("device_type", True)))
    is_cpu = bool(declared) and declared[0] == "cpu"

    if is_cpu and name != "cpu":
        ctx.report(
            DiagnosticCode.SPEC_NODE_NAME,
            Severity.WARNING,
            f"Node «{node.name}» is a CPU but is not named «cpu»",
            node,
            hint="§3.8: the node-name of every CPU node should be «cpu»",
        )

    if name != "cpu" or name in NON_CPU_CHILDREN:
        return

    for required in ("device_type", "reg"):
        if required not in present:
            ctx.report(
                DiagnosticCode.SPEC_MISSING_PROPERTY,
                Severity.ERROR,
                f"Node «{node.name}» does not declare «{required}»",
                node,
                hint="§3.8: required on a cpu node",
                missing=True,
            )


# ----------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------
def _root_children_named(ctx: SpecContext, name: str) -> List[DeviceTreeNode]:
    """Hijos directos de la raíz del documento con ese node-name."""
    return [child for child in ctx.root.children if base_name(child) == name]
