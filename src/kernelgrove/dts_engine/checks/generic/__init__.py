"""Capa 2 del motor semántico: los bindings genéricos.

`check_generic_layer` es la entrada. Va por separado de `run_checks` porque es
la pasada caras del motor: quien la llame decide cuándo puede permitírsela.
"""

from __future__ import annotations

from typing import List, Optional

from kernelgrove.dt_model.model import DeviceTreeNode
from kernelgrove.dts_engine.checks.bindings.lookup import SchemaLookup
from kernelgrove.dts_engine.checks.context import build_context
from kernelgrove.dts_engine.checks.generic.rules import check_generic
from kernelgrove.dts_engine.diagnostics import Diagnostic
from kernelgrove.dts_engine.parser import ParseResult

__all__ = ["check_generic", "check_generic_layer"]


def check_generic_layer(
    result: ParseResult,
    lookup: SchemaLookup,
    *,
    fragment: bool = False,
    merged_root: Optional[DeviceTreeNode] = None,
    includes_resolved: bool = True,
) -> List[Diagnostic]:
    """Comprueba un documento contra los bindings genéricos aplicables."""
    ctx = build_context(
        result,
        fragment=fragment,
        merged_root=merged_root,
        includes_resolved=includes_resolved,
        schema_lookup=lookup,
    )
    check_generic(ctx, lookup)
    return ctx.diagnostics
