"""Pruebas de la capa 1 del motor semántico (especificación Device Tree).

Cada prueba cita la regla que comprueba; ver `docs/SEMANTIC-ENGINE-FLOW.md`.
"""

from __future__ import annotations

from typing import List

from kernelgrove.dt_model.model import merge_device_tree
from kernelgrove.dts_engine.checks import run_checks
from kernelgrove.dts_engine.diagnostics import Diagnostic, DiagnosticCode, Severity
from kernelgrove.dts_engine.parser import parse_dts_source


def analyze(text: str, fragment: bool = False) -> List[Diagnostic]:
    """Analiza un fuente con la capa 1 y devuelve sus diagnósticos."""
    result = parse_dts_source(text)
    return run_checks(result, text=text, fragment=fragment)


def codes(diagnostics: List[Diagnostic]) -> List[DiagnosticCode]:
    """Códigos de una lista de diagnósticos, para comparar cómodamente."""
    return [item.code for item in diagnostics]


# ----------------------------------------------------------------------
# §2.2 nombres
# ----------------------------------------------------------------------
def test_node_name_con_caracteres_invalidos():
    """§2.2.1: el node-name solo admite el juego de caracteres de la tabla."""
    diagnostics = analyze('/dts-v1/;\n/ {\n\tuart!bad {\n\t};\n};\n', fragment=True)
    assert DiagnosticCode.SPEC_NODE_NAME in codes(diagnostics)


def test_node_name_valido_no_avisa():
    """Un nodo corriente no genera avisos de nombre."""
    diagnostics = analyze('/ {\n\tserial@1000 {\n\t\treg = <0x1000 0x10>;\n\t};\n};\n')
    assert DiagnosticCode.SPEC_NODE_NAME not in codes(diagnostics)


def test_nombre_de_nodo_generado_por_macro_se_ignora():
    """Una macro sin expandir no es un nombre que la capa 1 pueda juzgar."""
    diagnostics = analyze("/ {\n\tDIE_NODE(pmgr): pmgr {\n\t};\n};\n")
    assert DiagnosticCode.SPEC_LABEL not in codes(diagnostics)


def test_nodo_y_propiedad_con_el_mismo_nombre():
    """§2.2.1: un node-name sin unit-address no puede repetir una propiedad."""
    text = '/ {\n\tprueba = "x";\n\tprueba {\n\t};\n};\n'
    assert DiagnosticCode.SPEC_NAME_CLASH in codes(analyze(text))


# ----------------------------------------------------------------------
# §2.3 y §2.4 propiedades estándar
# ----------------------------------------------------------------------
def test_status_con_valor_no_admitido():
    """§2.3.4: solo okay, disabled, reserved, fail y fail-sss."""
    diagnostics = analyze('/ {\n\tstatus = "enabled";\n};\n', fragment=True)
    assert any(
        item.code is DiagnosticCode.SPEC_PROPERTY_VALUE
        and item.severity is Severity.ERROR
        for item in diagnostics
    )


def test_status_valido_no_avisa():
    """Un `status` correcto no produce nada."""
    diagnostics = analyze('/ {\n\tstatus = "okay";\n};\n', fragment=True)
    assert DiagnosticCode.SPEC_PROPERTY_VALUE not in codes(diagnostics)


def test_propiedad_booleana_con_valor():
    """§2.4.2.2: `interrupt-controller` es de tipo <empty>."""
    text = (
        "/ {\n\tnodo {\n\t\tinterrupt-controller = <1>;\n"
        "\t\t#interrupt-cells = <1>;\n\t};\n};\n"
    )
    assert DiagnosticCode.SPEC_PROPERTY_VALUE in codes(analyze(text, fragment=True))


def test_interrupts_e_interrupts_extended_a_la_vez():
    """§2.4.1.3: son mutuamente excluyentes."""
    text = (
        "/ {\n\tnodo {\n\t\tinterrupts = <1>;\n"
        "\t\tinterrupts-extended = <&intc 1>;\n\t};\n};\n"
    )
    assert DiagnosticCode.SPEC_CONFLICTING_PROPERTIES in codes(
        analyze(text, fragment=True)
    )


def test_compatible_con_guion_bajo_avisa():
    """§2.3.1: el formato recomendado no usa guiones bajos."""
    text = '/ {\n\tnodo {\n\t\tcompatible = "vendor,mi_chip";\n\t};\n};\n'
    diagnostics = analyze(text, fragment=True)
    assert any(
        item.code is DiagnosticCode.SPEC_PROPERTY_VALUE
        and item.severity is Severity.WARNING
        for item in diagnostics
    )


def test_compatible_generico_del_estandar_no_avisa():
    """Los compatibles genéricos con punto son válidos (§2.3.1)."""
    text = '/ {\n\tnodo {\n\t\tcompatible = "ethernet-phy-ieee802.3-c22";\n\t};\n};\n'
    assert DiagnosticCode.SPEC_PROPERTY_VALUE not in codes(analyze(text, fragment=True))


def test_compatible_partido_con_continuacion_de_linea():
    """La barra de continuación del preprocesador no rompe el valor."""
    text = '/ {\n\tcompatible = "a,b", \\\n\t\t"c,d";\n};\n'
    assert DiagnosticCode.SPEC_PROPERTY_VALUE not in codes(analyze(text, fragment=True))


def test_stdout_path_por_referencia():
    """§6.3: fuera de un array de celdas, `&label` se expande a la ruta."""
    text = "/ {\n\tchosen {\n\t\tstdout-path = &uart0;\n\t};\n};\n"
    assert DiagnosticCode.SPEC_PROPERTY_VALUE not in codes(analyze(text, fragment=True))


def test_propiedad_name_obsoleta():
    """§2.3.11: `name` está obsoleta."""
    text = '/ {\n\tnodo {\n\t\tname = "nodo";\n\t};\n};\n'
    assert DiagnosticCode.SPEC_DEPRECATED in codes(analyze(text, fragment=True))


# ----------------------------------------------------------------------
# §2.2.1 y §2.3.5 direccionamiento
# ----------------------------------------------------------------------
def test_unit_address_no_coincide_con_reg():
    """§2.2.1: la unit-address es la primera dirección de `reg`."""
    text = (
        "/ {\n\t#address-cells = <1>;\n\t#size-cells = <1>;\n"
        "\tserial@1000 {\n\t\treg = <0x2000 0x10>;\n\t};\n};\n"
    )
    assert DiagnosticCode.SPEC_REG_MISMATCH in codes(analyze(text, fragment=True))


def test_unit_address_coincide_con_reg():
    """El caso correcto no produce nada."""
    text = (
        "/ {\n\t#address-cells = <1>;\n\t#size-cells = <1>;\n"
        "\tserial@2000 {\n\t\treg = <0x2000 0x10>;\n\t};\n};\n"
    )
    assert DiagnosticCode.SPEC_REG_MISMATCH not in codes(analyze(text, fragment=True))


def test_reg_con_macro_no_se_compara():
    """Un `reg` con macros pertenece a la capa 3: aquí no se juzga."""
    text = (
        "/ {\n\t#address-cells = <1>;\n\t#size-cells = <1>;\n"
        "\tserial@2000 {\n\t\treg = <SOC_UART_BASE 0x10>;\n\t};\n};\n"
    )
    assert DiagnosticCode.SPEC_REG_MISMATCH not in codes(analyze(text, fragment=True))


def test_reg_sin_unit_address():
    """§2.2.1: un nodo con `reg` debería llevar unit-address."""
    text = (
        "/ {\n\t#address-cells = <1>;\n\t#size-cells = <1>;\n"
        "\tserial {\n\t\treg = <0x2000 0x10>;\n\t};\n};\n"
    )
    assert DiagnosticCode.SPEC_REG_MISMATCH in codes(analyze(text, fragment=True))


def test_numero_de_celdas_de_reg():
    """§2.3.6: `reg` va en grupos de #address-cells + #size-cells."""
    text = (
        "/ {\n\t#address-cells = <1>;\n\t#size-cells = <1>;\n"
        "\tserial@2000 {\n\t\treg = <0x2000 0x10 0x30>;\n\t};\n};\n"
    )
    assert any(
        item.code is DiagnosticCode.SPEC_REG_MISMATCH
        and item.severity is Severity.ERROR
        for item in analyze(text, fragment=True)
    )


# ----------------------------------------------------------------------
# §3 y §6.4 estructura
# ----------------------------------------------------------------------
COMPLETO = (
    "/dts-v1/;\n"
    "/ {\n"
    '\tmodel = "Placa de prueba";\n'
    '\tcompatible = "vendor,placa";\n'
    "\t#address-cells = <1>;\n"
    "\t#size-cells = <1>;\n"
    "\tcpus {\n"
    "\t\t#address-cells = <1>;\n"
    "\t\t#size-cells = <0>;\n"
    "\t\tcpu@0 {\n"
    '\t\t\tdevice_type = "cpu";\n'
    "\t\t\treg = <0>;\n"
    "\t\t};\n"
    "\t};\n"
    "\tmemory@0 {\n"
    '\t\tdevice_type = "memory";\n'
    "\t\treg = <0x0 0x10000000>;\n"
    "\t};\n"
    "};\n"
)


def test_arbol_completo_sin_diagnosticos():
    """Un device tree mínimo y correcto no produce ningún diagnóstico."""
    assert analyze(COMPLETO) == []


def test_falta_cpus_y_memory():
    """§3.1: hacen falta `/cpus` y al menos un `/memory`."""
    text = (
        '/dts-v1/;\n/ {\n\tmodel = "x";\n\tcompatible = "v,x";\n'
        "\t#address-cells = <1>;\n\t#size-cells = <1>;\n};\n"
    )
    assert codes(analyze(text)).count(DiagnosticCode.SPEC_MISSING_NODE) == 2


def test_fragmento_no_reclama_lo_que_falta():
    """Un `.dtsi` es un trozo: no se le exigen `/cpus` ni `/memory`."""
    text = '/ {\n\tnodo {\n\t\tcompatible = "vendor,chip";\n\t};\n};\n'
    assert DiagnosticCode.SPEC_MISSING_NODE not in codes(analyze(text, fragment=True))


def test_sin_fusionar_los_includes_no_se_juzga_el_documento_entero():
    """Una placa hereda medio árbol de su `.dtsi`: sin fusionarlo no se juzga."""
    text = '/dts-v1/;\n#include "soc.dtsi"\n/ {\n\tmodel = "x";\n};\n'
    diagnostics = analyze(text)
    assert DiagnosticCode.SPEC_MISSING_NODE not in codes(diagnostics)
    assert DiagnosticCode.SPEC_MISSING_PROPERTY not in codes(diagnostics)


def test_un_include_sin_resolver_rebaja_el_aviso_en_vez_de_callarlo():
    """Si algún include no se encuentra, se avisa sin afirmar que falte."""
    text = (
        '/dts-v1/;\n#include "soc.dtsi"\n#include "otro.dtsi"\n/ {\n'
        '\tmodel = "x";\n\tcompatible = "v,x";\n'
        "\t#address-cells = <1>;\n\t#size-cells = <1>;\n};\n"
    )
    result = parse_dts_source(text)
    faltantes = [
        item
        for item in run_checks(
            result,
            text=text,
            merged_root=result.root.clone(),
            includes_resolved=False,
        )
        if item.code is DiagnosticCode.SPEC_MISSING_NODE
    ]
    assert faltantes
    # Se rebaja un escalón: /cpus pasa de error a aviso y /memory, que ya era
    # aviso, a informativo. Y se explica por qué.
    assert all(item.severity is not Severity.ERROR for item in faltantes)
    assert all("include" in (item.hint or "") for item in faltantes)


def test_reabrir_un_nodo_en_el_mismo_fichero_no_lo_duplica():
    """Reescribir un nodo con el mismo nombre amplía el que ya hay.

    Si el parser creara dos hermanos idénticos, cada comprobación vería solo
    la mitad de las propiedades del nodo.
    """
    text = (
        '/ {\n\tsoc {\n\t\tuart@1000 {\n\t\t\tcompatible = "v,uart";\n\t\t};\n\t};\n'
        '\tsoc {\n\t\tuart@1000 {\n\t\t\tstatus = "okay";\n\t\t};\n\t};\n};\n'
    )
    root = parse_dts_source(text).root
    assert [child.name for child in root.children] == ["soc"]
    uart = root.children[0].children[0]
    assert sorted(uart.properties) == ["compatible", "status"]


def test_arbol_fusionado_evita_el_falso_positivo():
    """Lo que aporta un include cuenta como presente."""
    incluido = parse_dts_source(
        "/ {\n\t#address-cells = <1>;\n\t#size-cells = <1>;\n"
        "\tcpus {\n\t\t#address-cells = <1>;\n\t\t#size-cells = <0>;\n\t};\n"
        "\tmemory@0 {\n\t\tdevice_type = \"memory\";\n\t\treg = <0 0x1000>;\n\t};\n};\n"
    ).root
    text = (
        '/dts-v1/;\n#include "soc.dtsi"\n/ {\n'
        '\tmodel = "x";\n\tcompatible = "v,x";\n};\n'
    )
    result = parse_dts_source(text)
    merged = result.root.clone()
    merge_device_tree(merged, incluido)

    diagnostics = run_checks(result, text=text, merged_root=merged)
    assert DiagnosticCode.SPEC_MISSING_NODE not in codes(diagnostics)
    assert DiagnosticCode.SPEC_MISSING_PROPERTY not in codes(diagnostics)


def test_arbol_fusionado_afirma_lo_que_falta_de_verdad():
    """Si tampoco lo aporta el include, el error se afirma con seguridad."""
    incluido = parse_dts_source(
        "/ {\n\t#address-cells = <1>;\n\t#size-cells = <1>;\n"
        "\tcpus {\n\t\t#address-cells = <1>;\n\t\t#size-cells = <0>;\n\t};\n"
        "\tmemory@0 {\n\t\tdevice_type = \"memory\";\n\t\treg = <0 0x1000>;\n\t};\n};\n"
    ).root
    text = '/dts-v1/;\n#include "soc.dtsi"\n/ {\n\tmodel = "x";\n};\n'
    result = parse_dts_source(text)
    merged = result.root.clone()
    merge_device_tree(merged, incluido)

    faltantes = [
        item
        for item in run_checks(result, text=text, merged_root=merged)
        if item.code is DiagnosticCode.SPEC_MISSING_PROPERTY
    ]
    assert [item.severity for item in faltantes] == [Severity.ERROR]
    assert "compatible" in faltantes[0].message


def test_fragmento_avisa_de_lo_que_falta_en_un_nodo():
    """Lo que le falta a un nodo escrito aquí se avisa aunque sea un `.dtsi`."""
    text = (
        "/ {\n\tcpus {\n\t\t#address-cells = <1>;\n\t\t#size-cells = <0>;\n"
        '\t\tcpu@0 {\n\t\t\tdevice_type = "cpu";\n\t\t};\n\t};\n};\n'
    )
    faltantes = [
        item
        for item in analyze(text, fragment=True)
        if item.code is DiagnosticCode.SPEC_MISSING_PROPERTY
    ]
    assert any("reg" in item.message for item in faltantes)
    assert all(item.severity is Severity.WARNING for item in faltantes)


def test_falta_dts_v1():
    """§6.4: un `.dts` completo empieza por `/dts-v1/;`."""
    text = (
        '/ {\n\tmodel = "x";\n\tcompatible = "v,x";\n'
        "\t#address-cells = <1>;\n\t#size-cells = <1>;\n"
        "\tcpus {\n\t};\n\tmemory@0 {\n\t};\n};\n"
    )
    assert DiagnosticCode.SPEC_DTS_VERSION in codes(analyze(text))


def test_alias_con_caracteres_invalidos():
    """§3.3: los alias son minúsculas, dígitos y guiones."""
    text = '/ {\n\taliases {\n\t\tserial_0 = "/soc/serial@0";\n\t};\n};\n'
    assert DiagnosticCode.SPEC_PROPERTY_NAME in codes(analyze(text, fragment=True))


def test_cpus_con_size_cells_distinto_de_cero():
    """§3.7: `/cpus` declara `#size-cells = <0>`."""
    text = (
        "/ {\n\tcpus {\n\t\t#address-cells = <1>;\n"
        "\t\t#size-cells = <1>;\n\t};\n};\n"
    )
    assert any(
        item.code is DiagnosticCode.SPEC_PROPERTY_VALUE
        and item.severity is Severity.ERROR
        for item in analyze(text, fragment=True)
    )


def test_nodo_cpu_mal_nombrado():
    """§3.8: el node-name de una CPU debería ser `cpu`."""
    text = (
        "/ {\n\tcpus {\n\t\t#address-cells = <1>;\n\t\t#size-cells = <0>;\n"
        '\t\tprocesador@0 {\n\t\t\tdevice_type = "cpu";\n\t\t\treg = <0>;\n\t\t};\n'
        "\t};\n};\n"
    )
    assert DiagnosticCode.SPEC_NODE_NAME in codes(analyze(text, fragment=True))


def test_nodos_auxiliares_de_cpus_no_avisan():
    """De `/cpus` cuelgan nodos que no son CPUs y no deben señalarse."""
    text = (
        "/ {\n\tcpus {\n\t\t#address-cells = <1>;\n\t\t#size-cells = <0>;\n"
        "\t\tl2-cache0 {\n\t\t\tcache-level = <2>;\n\t\t};\n\t};\n};\n"
    )
    assert DiagnosticCode.SPEC_NODE_NAME not in codes(analyze(text, fragment=True))
