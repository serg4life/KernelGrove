"""Capa 5 del motor semántico: el binding del `compatible` concreto.

`check_binding_layer` es la entrada desde el orquestador; `lookup` define qué
necesita saber el motor de un binding y quién se lo tiene que dar.
"""

from __future__ import annotations

from typing import List, Optional

from kernelgrove.dt_model.model import DeviceTreeNode
from kernelgrove.dts_engine.checks.bindings.lookup import (
    NodeSchema,
    SchemaLookup,
    SchemaProperty,
)
from kernelgrove.dts_engine.checks.bindings.rules import (
    check_binding_values,
    check_bindings,
)
from kernelgrove.dts_engine.checks.context import build_context
from kernelgrove.dts_engine.diagnostics import Diagnostic
from kernelgrove.dts_engine.parser import ParseResult

__all__ = [
    "NodeSchema",
    "SchemaLookup",
    "SchemaProperty",
    "check_bindings",
    "check_binding_values",
    "check_binding_layer",
]


def check_binding_layer(
    result: ParseResult,
    lookup: SchemaLookup,
    *,
    fragment: bool = False,
    merged_root: Optional[DeviceTreeNode] = None,
    includes_resolved: bool = True,
    kernel_version: Optional[str] = None,
) -> List[Diagnostic]:
    """Comprueba un documento contra los bindings de sus compatibles.

    Mismos argumentos que la capa 1 salvo `text` y `dts_version_seen`, que
    solo hacen falta para reglas de fichero: aquí todo es de nodo, más
    `kernel_version`: la release contra la que se está trabajando, si el
    usuario la ha declarado. Sin ella no se comprueba la antigüedad de
    ningún binding.
    """
    ctx = build_context(
        result,
        fragment=fragment,
        merged_root=merged_root,
        includes_resolved=includes_resolved,
        schema_lookup=lookup,
    )
    check_bindings(ctx, lookup, kernel_version)
    return ctx.diagnostics
