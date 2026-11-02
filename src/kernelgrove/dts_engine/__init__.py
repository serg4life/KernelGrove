"""Motor Device Tree: análisis sintáctico y semántico de fuentes `.dts`/`.dtsi`.

Este paquete no depende de la base de datos ni de la interfaz: recibe texto y
(opcionalmente) una fuente de bindings inyectada, y devuelve un árbol de
`DeviceTreeNode` junto a los diagnósticos encontrados.

- `parser`: texto -> árbol + errores de sintaxis.
- `checks`: árbol -> errores semánticos, por capas (ver
  `docs/SEMANTIC-ENGINE-FLOW.md`). Están implementadas la capa 1 (la
  especificación Device Tree), la 2 (bindings genéricos) y la 5 (el binding
  del compatible concreto).
- `diagnostics`: vocabulario común de problemas.
"""

from kernelgrove.dts_engine.checks import check_spec, run_checks, run_schema_checks
from kernelgrove.dts_engine.checks.context import SPEC_OWNED_PROPERTIES
from kernelgrove.dts_engine.diagnostics import Diagnostic, DiagnosticCode, Severity
from kernelgrove.dts_engine.parser import (
    IncludeDirective,
    ParseResult,
    collect_includes,
    find_matching_brace,
    parse_compatible_value,
    parse_dts_file,
    parse_dts_source,
    parse_dtsi_file,
    strip_comments,
)

__all__ = [
    "Diagnostic",
    "DiagnosticCode",
    "Severity",
    "ParseResult",
    "IncludeDirective",
    "collect_includes",
    "parse_dts_source",
    "parse_dts_file",
    "parse_dtsi_file",
    "parse_compatible_value",
    "find_matching_brace",
    "strip_comments",
    "check_spec",
    "run_checks",
    "run_schema_checks",
    "SPEC_OWNED_PROPERTIES",
]
