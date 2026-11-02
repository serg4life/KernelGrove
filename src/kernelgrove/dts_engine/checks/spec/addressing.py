"""Direccionamiento: `reg`, `unit-address`, `#address-cells` y `#size-cells`.

Reglas de la especificación Device Tree v0.4:

- §2.2.1: la unit-address debe coincidir con la primera dirección de `reg`;
  si el nodo no tiene `reg`, se omite la `@unit-address`.
- §2.3.5: `#address-cells` y `#size-cells` describen cuántas celdas ocupan la
  dirección y el tamaño en el `reg` de los hijos, no se heredan y deben
  declararse en todo nodo con hijos.
- §2.3.6: `reg` es una sucesión de pares (dirección, tamaño) con esos anchos;
  si el padre declara `#size-cells = <0>`, el tamaño se omite.

Todo lo que dependa de un número que aún es una macro de `dt-bindings/*.h`
(capa 3) se deja pasar: es preferible callar a inventarse un error.
"""

from __future__ import annotations

from typing import List, Optional

from kernelgrove.dt_model.model import DeviceTreeNode
from kernelgrove.dts_engine.checks import values
from kernelgrove.dts_engine.checks.context import (
    SpecContext,
    is_reference_node,
    unit_address,
)
from kernelgrove.dts_engine.diagnostics import DiagnosticCode, Severity


def check_addressing(ctx: SpecContext) -> None:
    """Aplica las comprobaciones de direccionamiento al árbol."""
    for node in ctx.walk():
        if is_reference_node(node):
            continue
        _check_unit_address_and_reg(ctx, node)
        _check_reg_cell_count(ctx, node)
        _check_children_need_cells(ctx, node)


def _check_unit_address_and_reg(ctx: SpecContext, node: DeviceTreeNode) -> None:
    """Contrasta la `@unit-address` con el `reg` del nodo (§2.2.1)."""
    address = unit_address(node)
    present = ctx.effective_properties(node)
    has_reg = "reg" in present
    has_ranges = "ranges" in present or "dma-ranges" in present

    if address is None:
        if has_reg:
            ctx.report(
                DiagnosticCode.SPEC_REG_MISMATCH,
                Severity.WARNING,
                f"«{node.name}» has «reg» but carries no unit-address",
                node,
                property_name="reg",
                hint="§2.2.1: the name should be "
                f"{node.name}@<first address in reg>",
            )
        return

    if not has_reg:
        # Un nodo de bus con `ranges` sí puede llevar unit-address aunque no
        # tenga `reg`: es la dirección desde la que traduce.
        if not has_ranges:
            ctx.report(
                DiagnosticCode.SPEC_REG_MISMATCH,
                Severity.WARNING,
                f"«{node.name}» carries a unit-address but has no «reg»",
                node,
                hint="§2.2.1: with no «reg» the «@unit-address» is omitted",
                missing=True,
            )
        return

    expected = _first_reg_address(ctx, node)
    if expected is None:
        return

    declared = _parse_unit_address(address)
    if declared is None or declared == expected:
        return

    ctx.report(
        DiagnosticCode.SPEC_REG_MISMATCH,
        Severity.WARNING,
        (
            f"The unit-address of «{node.name}» does not match its «reg» "
            f"(0x{expected:x})"
        ),
        node,
        property_name="reg",
        hint="§2.2.1: the unit-address is the first address in reg, in hex "
        "and with no «0x»",
    )


def _check_reg_cell_count(ctx: SpecContext, node: DeviceTreeNode) -> None:
    """El `reg` debe ser múltiplo de (#address-cells + #size-cells) (§2.3.6)."""
    if "reg" not in node.properties or node.parent is None:
        return

    address_cells = _cells_declared(ctx, node.parent, "#address-cells")
    size_cells = _cells_declared(ctx, node.parent, "#size-cells")
    if address_cells is None or size_cells is None:
        return

    entry = address_cells + size_cells
    if entry <= 0:
        return

    reg = values.cells(values.raw_text(node.properties["reg"]))
    if reg is None or not reg:
        return

    if len(reg) % entry:
        ctx.report(
            DiagnosticCode.SPEC_REG_MISMATCH,
            Severity.ERROR,
            (
                f"«reg» has {len(reg)} cells and «{node.parent.name}» asks for "
                f"groups of {entry} (#address-cells={address_cells}, "
                f"#size-cells={size_cells})"
            ),
            node,
            property_name="reg",
            hint="§2.3.6: reg is a sequence of (address, size) pairs",
        )


def _check_children_need_cells(ctx: SpecContext, node: DeviceTreeNode) -> None:
    """Un nodo con hijos direccionados declara los anchos de dirección (§2.3.5)."""
    if not node.children:
        return

    present = ctx.effective_properties(node)
    addressed = [
        child
        for child in node.children
        if "reg" in ctx.effective_properties(child) and not is_reference_node(child)
    ]
    if not addressed:
        return

    for required in ("#address-cells", "#size-cells"):
        if required not in present:
            ctx.report(
                DiagnosticCode.SPEC_MISSING_PROPERTY,
                Severity.WARNING,
                (
                    f"«{node.name}» has children with «reg» but does not declare "
                    f"«{required}»"
                ),
                node,
                hint="§2.3.5: it is not inherited from the parent, it must be declared",
                missing=True,
            )


# ----------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------
def _cells_declared(
    ctx: SpecContext, node: DeviceTreeNode, name: str
) -> Optional[int]:
    """Devuelve el valor de `#address-cells`/`#size-cells`, si es un número."""
    present = ctx.effective_properties(node)
    if name not in present:
        return None
    cells = values.cells(values.raw_text(present[name]))
    if not cells or len(cells) != 1:
        return None
    return values.number(cells[0])


def _first_reg_address(ctx: SpecContext, node: DeviceTreeNode) -> Optional[int]:
    """Calcula la primera dirección del `reg`, o None si no es comparable."""
    if node.parent is None:
        return None

    address_cells = _cells_declared(ctx, node.parent, "#address-cells")
    if address_cells is None or address_cells < 1:
        return None

    reg = values.cells(values.raw_text(ctx.effective_properties(node)["reg"]))
    if reg is None or len(reg) < address_cells:
        return None

    return _combine(reg[:address_cells])


def _combine(cells: List[str]) -> Optional[int]:
    """Une varias celdas de 32 bits en un solo número, o None si hay macros."""
    total = 0
    for cell in cells:
        value = values.number(cell)
        if value is None:
            return None
        total = (total << 32) | (value & 0xFFFFFFFF)
    return total


def _parse_unit_address(address: str) -> Optional[int]:
    """Interpreta la unit-address como hexadecimal, o None si no lo es.

    Las unit-address con formato propio del bus (`0,0` de PCI, `1p0` de
    algunos buses) no se comparan: su formato lo define el binding del bus,
    que es una capa posterior.
    """
    if not values.is_hex_literal(address):
        return None
    try:
        return int(address, 16)
    except ValueError:
        return None
