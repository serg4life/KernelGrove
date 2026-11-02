"""Capa 3: existencia de las macros de `dt-bindings/*.h` usadas en un valor.

Los valores reales no son números sino macros (`GIC_SPI`, `IRQ_TYPE_LEVEL_
HIGH`, `RK3399_CLK_I2C1`...), y `checks/values.has_macro` hace que las capas
2 y 5 se callen en vez de juzgarlas: no se puede comprobar un rango o un
`enum` sin conocer el número. Esta capa no resuelve ese número —eso exigiría
expandir la macro de verdad, con `cpp` y un evaluador de expresiones, y por
ahora no hace falta para el caso de uso real— sino algo más barato y ya útil
por sí solo: **¿existe esa macro en algún sitio?** Coge exactamente los
mismos tokens que `has_macro` ya identifica y en vez de callarse pregunta al
`MacroLookup` inyectado.

Se distinguen dos gravedades porque la evidencia no es igual de fuerte:

- Si el nombre existe en alguna cabecera `dt-bindings/*.h` conocida pero no
  entre las que este documento incluye (`local_macros`, calculado por quien
  llama a partir de sus `#include` reales, en cascada), lo más probable es
  que falte ese `#include` — un error real, aunque el motor no pueda estar
  seguro de que no venga de otro sitio (`WARNING`).
- Si no existe en ninguna cabecera conocida, la certeza es mucho menor:
  algunos drivers definen sus propias macros fuera de `dt-bindings/`, así que
  ausencia de prueba no es prueba de ausencia — igual que
  `binding-unknown-compatible` (`INFO`).

`local_macros` es responsabilidad de quien llama (`api/service.py`, con
`IncludeResolver.macro_names`), no de esta capa: el motor no toca la base de
datos ni el disco, solo recibe ya resuelto qué es visible en este documento
concreto, igual que `merged_root` para la fusión de includes.
"""

from __future__ import annotations

from typing import List, Optional, Protocol, Sequence

from kernelgrove.dt_model.model import DeviceTreeNode
from kernelgrove.dts_engine.checks import values
from kernelgrove.dts_engine.checks.context import SpecContext, build_context
from kernelgrove.dts_engine.diagnostics import Diagnostic, DiagnosticCode, Severity
from kernelgrove.dts_engine.parser import ParseResult


class MacroLookup(Protocol):
    """Acceso al índice de macros que el motor consulta."""

    def is_known(self, name: str) -> bool:
        """Indica si `name` está definida en alguna cabecera dt-bindings conocida."""
        ...

    def headers_defining(self, name: str) -> Sequence[str]:
        """Cabeceras que declaran `name`, para sugerir el `#include` que falta."""
        ...


def check_macros(
    ctx: SpecContext, lookup: MacroLookup, local_macros: Sequence[str]
) -> None:
    """Contrasta cada token con forma de macro contra el índice inyectado."""
    local = (
        local_macros
        if isinstance(local_macros, frozenset)
        else frozenset(local_macros)
    )

    for node in ctx.walk():
        for name, value in node.properties.items():
            if not isinstance(value, str):
                continue
            for component in values.split_components(value):
                if not values.is_cell_array(component):
                    continue
                for token in values.cell_tokens(component):
                    if not values.is_macro(token) or token in local:
                        continue
                    _report_unresolved(ctx, lookup, node, name, token)


def _report_unresolved(
    ctx: SpecContext,
    lookup: MacroLookup,
    node: DeviceTreeNode,
    property_name: str,
    token: str,
) -> None:
    """Emite el diagnóstico según se conozca `token` en otra cabecera o en ninguna."""
    if lookup.is_known(token):
        headers = lookup.headers_defining(token)
        ctx.report(
            DiagnosticCode.MACRO_MISSING_INCLUDE,
            Severity.WARNING,
            f"«{token}» is not known in the headers included here",
            node,
            property_name=property_name,
            hint=f"defined in «{headers[0]}»" if headers else None,
        )
        return

    ctx.report(
        DiagnosticCode.MACRO_UNKNOWN,
        Severity.INFO,
        f"«{token}» is not known in any dt-bindings header",
        node,
        property_name=property_name,
        hint="it may be a driver-local macro, not a dt-bindings one",
    )


def check_macro_layer(
    result: ParseResult,
    lookup: MacroLookup,
    local_macros: Sequence[str],
    *,
    fragment: bool = False,
    merged_root: Optional[DeviceTreeNode] = None,
    includes_resolved: bool = True,
) -> List[Diagnostic]:
    """Entrada desde el orquestador: construye su propio contexto y comprueba.

    Mismos argumentos que la capa 5 salvo `local_macros`, que sustituye a
    `schema_lookup` porque esta capa no valida contra un schema.
    """
    ctx = build_context(
        result,
        fragment=fragment,
        merged_root=merged_root,
        includes_resolved=includes_resolved,
    )
    check_macros(ctx, lookup, local_macros)
    return ctx.diagnostics
