"""Comprobaciones de la capa 2: los bindings genéricos.

Como en la capa 5, el motor recibe un `SchemaLookup` de mentira: aquí se
prueba qué hace con lo que el validador le devuelve, no la validación en sí.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from kernelgrove.dts_engine.checks import run_schema_checks
from kernelgrove.dts_engine.checks.bindings.lookup import NodeSchema, SchemaIssue
from kernelgrove.dts_engine.diagnostics import Diagnostic, DiagnosticCode, Severity
from kernelgrove.dts_engine.parser import parse_dts_source


class FakeLookup:
    """`SchemaLookup` que devuelve los problemas que se le indiquen."""

    def __init__(
        self,
        generic_issues: tuple = (),
        shapes: Optional[Dict[str, str]] = None,
        unknown_names: tuple = (),
    ):
        """Recibe los problemas a devolver y las formas de las propiedades."""
        self._generic_issues = generic_issues
        self._shapes = shapes or {}
        self._unknown_names = set(unknown_names)

    def schema_for(self, compatible: str) -> Optional[NodeSchema]:
        """La capa 2 no resuelve por compatible."""
        return None

    def is_documented(self, compatible: str) -> bool:
        """Irrelevante para la capa 2."""
        return True

    def child_schema_for(self, compatible: str, node_name: str):
        """Irrelevante para la capa 2."""
        return None

    def property_type(self, name: str) -> Optional[str]:
        """Irrelevante para la capa 2."""
        return None

    def property_shape(self, name: str) -> Optional[str]:
        """Forma declarada en la prueba."""
        return self._shapes.get(name)

    def is_known_property_name(self, name: str) -> bool:
        """Prefijos de fabricante que la prueba da por buenos."""
        return name not in self._unknown_names

    def validate_node(self, schema, instance) -> List[SchemaIssue]:
        """La capa 2 no valida por binding concreto."""
        return []

    def validate_generic(self, instance) -> List[SchemaIssue]:
        """Problemas de los bindings genéricos, fijados en la prueba."""
        return list(self._generic_issues)


GPIO_ISSUE = SchemaIssue(
    keyword="dependentRequired",
    message="'#gpio-cells' is a dependency of 'gpio-controller'",
    property_name="#gpio-cells",
    schema_id="http://devicetree.org/schemas/gpio/gpio.yaml",
)

VALUE_ISSUE = SchemaIssue(
    keyword="maximum",
    message="9000000 is greater than the maximum of 5000000",
    property_name="clock-frequency",
    schema_id="http://devicetree.org/schemas/i2c/i2c-controller.yaml",
)


def analyze(source: str, lookup, fragment: bool = False) -> List[Diagnostic]:
    """Ejecuta la pasada diferida (valores de la capa 5 y capa 2) sobre el fuente."""
    return run_schema_checks(parse_dts_source(source), lookup, fragment=fragment)


DOCUMENT = '''/dts-v1/;
/ {
    model = "Prueba";
    compatible = "acme,board";
    #address-cells = <1>;
    #size-cells = <1>;

    gpio@1000 {
%(properties)s
    };
};
'''


def build(properties: str) -> str:
    """Documento con las propiedades indicadas en `gpio@1000`."""
    return DOCUMENT % {"properties": properties}


def test_propiedad_obligatoria_de_la_clase():
    """Lo que exige un binding genérico se reporta como error."""
    lookup = FakeLookup(generic_issues=(GPIO_ISSUE,))
    source = build("        reg = <0x1000 0x100>;\n        gpio-controller;")

    found = analyze(source, lookup)
    assert len(found) == 1
    assert found[0].code is DiagnosticCode.GENERIC_MISSING_PROPERTY
    assert found[0].severity is Severity.ERROR
    assert "#gpio-cells" in found[0].message


def test_no_se_avisa_de_lo_que_si_esta():
    """La instancia solo lleva lo codificable: la presencia se mira en el árbol."""
    lookup = FakeLookup(generic_issues=(GPIO_ISSUE,))
    source = build(
        "        reg = <0x1000 0x100>;\n"
        "        gpio-controller;\n"
        "        #gpio-cells = <2>;"
    )
    assert analyze(source, lookup) == []


def test_reapertura_en_fragmento_no_dice_que_falte_nada():
    """De un `&label { … }` en un `.dtsi` solo se ve un trozo del nodo."""
    lookup = FakeLookup(generic_issues=(GPIO_ISSUE,))
    source = '&gpioa {\n    gpio-line-names = "a";\n};\n'
    assert analyze(source, lookup, fragment=True) == []


def test_valor_fuera_de_lo_que_admite_la_clase():
    """Un valor que incumple el binding genérico se avisa."""
    lookup = FakeLookup(
        generic_issues=(VALUE_ISSUE,), shapes={"clock-frequency": "scalar"}
    )
    source = build(
        "        reg = <0x1000 0x100>;\n        clock-frequency = <9000000>;"
    )

    found = analyze(source, lookup)
    assert len(found) == 1
    assert found[0].code is DiagnosticCode.GENERIC_PROPERTY_VALUE
    assert found[0].property_name == "clock-frequency"
    assert "is greater than the maximum" in found[0].message


def test_valor_que_no_se_pudo_codificar_no_se_juzga():
    """Sin forma declarada la propiedad no entra en la instancia."""
    lookup = FakeLookup(generic_issues=(VALUE_ISSUE,), shapes={})
    source = build(
        "        reg = <0x1000 0x100>;\n        clock-frequency = <9000000>;"
    )
    assert analyze(source, lookup) == []


def test_prefijo_de_fabricante_desconocido():
    """Una propiedad con prefijo no registrado suele ser una errata."""
    lookup = FakeLookup(unknown_names=("noexiste,propiedad",))
    source = build("        reg = <0x1000 0x100>;\n        noexiste,propiedad = <1>;")

    found = [
        item
        for item in analyze(source, lookup)
        if item.code is DiagnosticCode.GENERIC_VENDOR_PREFIX
    ]
    assert len(found) == 1
    assert "noexiste" in found[0].message


def test_nombre_de_propiedad_con_macro_no_se_juzga():
    """Un nombre generado por una macro de C no es el nombre real."""
    lookup = FakeLookup(unknown_names=("EFUSE(10",))
    source = build("        reg = <0x1000 0x100>;\n        EFUSE(10, 27) = <1>;")
    assert [
        item
        for item in analyze(source, lookup)
        if item.code is DiagnosticCode.GENERIC_VENDOR_PREFIX
    ] == []

DOC_FOR_DEDUP = """/dts-v1/;
/ {
    model = "Prueba";
    compatible = "acme,board";
    #address-cells = <1>;
    #size-cells = <1>;

    i2c@2000 {
        compatible = "acme,i2c";
        clock-frequency = <9000000>;
    };
};
"""


def test_no_se_repite_lo_que_ya_dijo_el_binding():
    """Si el binding concreto y su clase dicen lo mismo, se cuenta una vez."""
    binding_issue = SchemaIssue(
        keyword="maximum",
        message="9000000 is greater than the maximum of 400000",
        property_name="clock-frequency",
        schema_id="http://devicetree.org/schemas/i2c/cdns,i2c-r1p10.yaml",
    )

    class BothLayers(FakeLookup):
        """El mismo compatible incumple su binding y su clase."""

        def schema_for(self, compatible):
            """Devuelve un schema para el compatible de la prueba."""
            return NodeSchema(compatible=compatible, schema_id="x", closed=False)

        def validate_node(self, schema, instance):
            """Lo que dice el binding concreto."""
            return [binding_issue]

    lookup = BothLayers(
        generic_issues=(VALUE_ISSUE,), shapes={"clock-frequency": "scalar"}
    )
    values = [
        item
        for item in analyze(DOC_FOR_DEDUP, lookup)
        if item.property_name == "clock-frequency"
    ]

    assert len(values) == 1
    assert values[0].code is DiagnosticCode.BINDING_PROPERTY_VALUE
