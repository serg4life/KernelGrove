"""Comprobaciones de la capa 3: existencia de macros de `dt-bindings/*.h`.

El motor no toca la base de datos: recibe un `MacroLookup` y el conjunto de
macros visibles por los includes del propio documento (`local_macros`). Aquí
se inyectan ambos a mano, como en `test_binding_checks.py`.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

from kernelgrove.dts_engine.checks import run_checks
from kernelgrove.dts_engine.diagnostics import Diagnostic, DiagnosticCode
from kernelgrove.dts_engine.parser import parse_dts_source


class FakeMacroLookup:
    """`MacroLookup` en memoria: un diccionario nombre -> cabeceras."""

    def __init__(self, known: Dict[str, Sequence[str]]):
        self._known = known

    def is_known(self, name: str) -> bool:
        return name in self._known

    def headers_defining(self, name: str) -> Sequence[str]:
        return list(self._known.get(name, ()))


def analyze(
    source: str, lookup: FakeMacroLookup, local_macros: Sequence[str] = ()
) -> List[Diagnostic]:
    """Analiza un fuente completo con la capa 3 activada."""
    result = parse_dts_source(source)
    return run_checks(
        result,
        text=source,
        macro_lookup=lookup,
        local_macros=local_macros,
    )


def codes(diagnostics: List[Diagnostic], code: DiagnosticCode) -> List[Diagnostic]:
    """Filtra los diagnósticos de un código concreto."""
    return [item for item in diagnostics if item.code == code]


DEVICE = """/dts-v1/;
/ {{
    model = "Placa de prueba";
    compatible = "test,board";
    #address-cells = <1>;
    #size-cells = <1>;

    node@0 {{
        reg = <0x0 0x100>;
        flags = <{value}>;
    }};
}};
"""


def test_macro_conocida_globalmente_pero_no_incluida_aqui_avisa() -> None:
    """Existe en otra cabecera dt-bindings, pero este fichero no la incluye."""
    lookup = FakeMacroLookup({"GPIO_ACTIVE_LOW": ["dt-bindings/gpio/gpio.h"]})
    diagnostics = analyze(DEVICE.format(value="GPIO_ACTIVE_LOW"), lookup)

    found = codes(diagnostics, DiagnosticCode.MACRO_MISSING_INCLUDE)
    assert len(found) == 1
    assert "GPIO_ACTIVE_LOW" in found[0].message
    assert "gpio.h" in (found[0].hint or "")


def test_macro_desconocida_en_todo_el_indice_es_solo_info() -> None:
    """No existe en ninguna cabecera dt-bindings conocida: aviso débil."""
    lookup = FakeMacroLookup({})
    diagnostics = analyze(DEVICE.format(value="GPIO_HIGH"), lookup)

    found = codes(diagnostics, DiagnosticCode.MACRO_UNKNOWN)
    assert len(found) == 1
    assert "GPIO_HIGH" in found[0].message
    assert not codes(diagnostics, DiagnosticCode.MACRO_MISSING_INCLUDE)


def test_macro_visible_por_los_includes_del_documento_no_avisa() -> None:
    """Si `local_macros` ya la trae, el `#include` correcto está escrito."""
    lookup = FakeMacroLookup({"GPIO_ACTIVE_LOW": ["dt-bindings/gpio/gpio.h"]})
    diagnostics = analyze(
        DEVICE.format(value="GPIO_ACTIVE_LOW"),
        lookup,
        local_macros=["GPIO_ACTIVE_LOW"],
    )

    assert not codes(diagnostics, DiagnosticCode.MACRO_MISSING_INCLUDE)
    assert not codes(diagnostics, DiagnosticCode.MACRO_UNKNOWN)


def test_numeros_y_referencias_no_se_tratan_como_macros() -> None:
    """Un literal o un `&label` no son identificadores de macro."""
    lookup = FakeMacroLookup({})
    diagnostics = analyze(DEVICE.format(value="0x1 &gpio0"), lookup)

    assert not codes(diagnostics, DiagnosticCode.MACRO_MISSING_INCLUDE)
    assert not codes(diagnostics, DiagnosticCode.MACRO_UNKNOWN)


def test_sin_macro_lookup_la_capa_no_se_ejecuta() -> None:
    """Sin `MacroLookup` inyectado, igual que la capa 5 sin `SchemaLookup`."""
    result = parse_dts_source(DEVICE.format(value="GPIO_HIGH"))
    diagnostics = run_checks(result, text=DEVICE.format(value="GPIO_HIGH"))

    assert not codes(diagnostics, DiagnosticCode.MACRO_UNKNOWN)
    assert not codes(diagnostics, DiagnosticCode.MACRO_MISSING_INCLUDE)


def test_varias_macros_en_la_misma_celda_se_comprueban_todas() -> None:
    """Cada token de la celda se juzga por separado."""
    lookup = FakeMacroLookup({"GPIO_ACTIVE_LOW": ["dt-bindings/gpio/gpio.h"]})
    diagnostics = analyze(
        DEVICE.format(value="GPIO_ACTIVE_LOW GPIO_HIGH"), lookup
    )

    assert len(codes(diagnostics, DiagnosticCode.MACRO_MISSING_INCLUDE)) == 1
    assert len(codes(diagnostics, DiagnosticCode.MACRO_UNKNOWN)) == 1
