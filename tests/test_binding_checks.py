"""Comprobaciones de la capa 5: el binding del `compatible` del nodo.

El motor no toca la base de datos: recibe un `SchemaLookup`. Aquí se le
inyecta uno de mentira, construido a mano, para que cada caso diga
exactamente qué schema se está usando.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from kernelgrove.dts_engine.checks import run_checks, run_schema_checks
from kernelgrove.dts_engine.checks.bindings.lookup import (
    NodeSchema,
    SchemaIssue,
    SchemaProperty,
)
from kernelgrove.dts_engine.diagnostics import Diagnostic, DiagnosticCode, Severity
from kernelgrove.dts_engine.parser import parse_dts_source


def make_schema(
    compatible: str,
    *,
    properties: Optional[Dict[str, dict]] = None,
    required: tuple = (),
    closed: bool = True,
    nodes: tuple = (),
    schema_id: str = "http://devicetree.org/schemas/test.yaml",
) -> NodeSchema:
    """Construye un `NodeSchema` mínimo para las pruebas."""
    entries = {
        name: SchemaProperty(
            name=name,
            schema=definition,
            required=name in required,
            origin=schema_id,
            is_node=name in nodes,
        )
        for name, definition in (properties or {}).items()
    }
    return NodeSchema(
        compatible=compatible,
        schema_id=schema_id,
        title="Dispositivo de prueba",
        properties=entries,
        required=tuple(required),
        closed=closed,
    )


class FakeLookup:
    """`SchemaLookup` en memoria."""

    def __init__(
        self,
        schemas: Optional[Dict[str, NodeSchema]] = None,
        children: Optional[Dict[tuple, NodeSchema]] = None,
        documented: tuple = (),
        types: Optional[Dict[str, str]] = None,
        issues: tuple = (),
        generic_issues: tuple = (),
        since: Optional[Dict[str, str]] = None,
    ):
        """Recibe los schemas por compatible y los de subnodo por (padre, nombre)."""
        self._schemas = schemas or {}
        self._children = children or {}
        self._documented = set(documented) | set(self._schemas)
        self._types = types or {}
        self._issues = issues
        self._generic_issues = generic_issues
        self._since = since or {}

    def schema_for(self, compatible: str) -> Optional[NodeSchema]:
        """Devuelve el schema registrado para ese compatible."""
        return self._schemas.get(compatible)

    def is_documented(self, compatible: str) -> bool:
        """Indica si el compatible está registrado."""
        return compatible in self._documented

    def child_schema_for(
        self, compatible: str, node_name: str
    ) -> Optional[NodeSchema]:
        """Devuelve lo que el padre dice de un hijo suyo."""
        return self._children.get((compatible, node_name))

    def property_type(self, name: str) -> Optional[str]:
        """Tipo de la propiedad, de los declarados al construir el falso."""
        return self._types.get(name)

    def property_shape(self, name: str) -> Optional[str]:
        """Forma del valor: se deduce del tipo declarado en el falso."""
        dt_type = self._types.get(name)
        if dt_type is None:
            return None
        if dt_type in ("string", "string-array"):
            return "string"
        if dt_type.endswith("-matrix") or dt_type == "address":
            return "matrix"
        if dt_type.endswith("-array"):
            return "array"
        if dt_type in ("phandle", "phandle-array"):
            return "phandle"
        return "scalar" if dt_type != "flag" else "flag"

    def since(self, schema_id: str) -> Optional[str]:
        """Release del kernel en la que apareció ese binding."""
        return self._since.get(schema_id)

    def is_known_property_name(self, name: str) -> bool:
        """En las pruebas del motor todos los prefijos se dan por válidos."""
        return True

    def validate_node(self, schema: NodeSchema, instance) -> List[SchemaIssue]:
        """Problemas que devolvería el validador de schemas.

        Se devuelven los que se le hayan puesto a mano: aquí se prueba qué
        hace el motor con ellos, no la validación en sí, que es de `api` y se
        prueba contra la base real en `test_binding_schemas.py`.
        """
        return list(self._issues)

    def validate_generic(self, instance) -> List[SchemaIssue]:
        """Problemas de los bindings genéricos (capa 2)."""
        return list(self._generic_issues)


def analyze(
    source: str,
    lookup,
    fragment: bool = False,
    kernel_version: Optional[str] = None,
) -> List[Diagnostic]:
    """Analiza un fuente completo con la capa 5 activada."""
    result = parse_dts_source(source)
    return run_checks(
        result,
        text=source,
        fragment=fragment,
        schema_lookup=lookup,
        kernel_version=kernel_version,
    )


def analyze_deferred(source: str, lookup, fragment: bool = False) -> List[Diagnostic]:
    """Analiza con la pasada diferida, la que valida los valores por schema.

    Va aparte del camino de `run_checks` porque es la parte cara: darle el
    nodo entero al schema cuesta milisegundos, y la aplicación lo hace en un
    hilo de fondo.
    """
    return run_schema_checks(parse_dts_source(source), lookup, fragment=fragment)


def codes(diagnostics: List[Diagnostic], code: DiagnosticCode) -> List[Diagnostic]:
    """Filtra los diagnósticos de un código concreto."""
    return [item for item in diagnostics if item.code == code]


DEVICE = '''/dts-v1/;
/ {
    model = "Placa de prueba";
    compatible = "test,board";
    #address-cells = <1>;
    #size-cells = <1>;

    cpus {
        #address-cells = <1>;
        #size-cells = <0>;
        cpu@0 {
            device_type = "cpu";
            reg = <0>;
        };
    };

    memory@0 {
        device_type = "memory";
        reg = <0 0x1000>;
    };

    rtc@51 {
%(properties)s
    };
};
'''


def build(properties: str) -> str:
    """Devuelve un documento completo con las propiedades indicadas en `rtc@51`."""
    return DEVICE % {"properties": properties}


def test_falta_propiedad_obligatoria():
    """Lo que el binding exige y no está se reporta como error."""
    lookup = FakeLookup(
        {
            "acme,rtc": make_schema(
                "acme,rtc",
                properties={"compatible": {}, "reg": {}, "clocks": {}},
                required=("compatible", "reg", "clocks"),
            )
        }
    )
    source = build('        compatible = "acme,rtc";\n        reg = <0x51>;')
    found = codes(analyze(source, lookup), DiagnosticCode.BINDING_MISSING_PROPERTY)

    assert len(found) == 1
    assert "clocks" in found[0].message
    assert found[0].severity is Severity.ERROR


def test_propiedades_obligatorias_presentes():
    """Con todo lo exigido presente no se dice nada."""
    lookup = FakeLookup(
        {
            "acme,rtc": make_schema(
                "acme,rtc",
                properties={"compatible": {}, "reg": {}},
                required=("compatible", "reg"),
            )
        }
    )
    source = build('        compatible = "acme,rtc";\n        reg = <0x51>;')
    assert codes(analyze(source, lookup), DiagnosticCode.BINDING_MISSING_PROPERTY) == []


def test_nodo_obligatorio_presente_no_avisa():
    """Un `required` que es un subnodo se busca entre los hijos.

    No entre las propiedades: hay subnodos definidos solo con un `$ref`.
    """
    lookup = FakeLookup(
        {
            "acme,bridge": make_schema(
                "acme,bridge",
                properties={"compatible": {}, "ports": {"type": "object"}},
                required=("compatible", "ports"),
                nodes=("ports",),
            )
        }
    )
    source = build(
        '        compatible = "acme,bridge";\n'
        "        ports {\n"
        "            port {\n"
        "            };\n"
        "        };"
    )
    diagnostics = analyze(source, lookup)
    assert codes(diagnostics, DiagnosticCode.BINDING_MISSING_NODE) == []


def test_nodo_obligatorio_ausente():
    """Un subnodo exigido que no está se reporta como nodo, no como propiedad."""
    lookup = FakeLookup(
        {
            "acme,bridge": make_schema(
                "acme,bridge",
                properties={"compatible": {}, "ports": {"type": "object"}},
                required=("compatible", "ports"),
                nodes=("ports",),
            )
        }
    )
    source = build('        compatible = "acme,bridge";')
    found = codes(analyze(source, lookup), DiagnosticCode.BINDING_MISSING_NODE)
    assert len(found) == 1
    assert "ports" in found[0].message


def test_nodo_deshabilitado_no_exige_nada():
    """De un nodo `disabled` no se puede exigir lo que la placa completará."""
    lookup = FakeLookup(
        {
            "acme,rtc": make_schema(
                "acme,rtc",
                properties={"compatible": {}, "reg": {}, "clocks": {}},
                required=("compatible", "reg", "clocks"),
            )
        }
    )
    source = build(
        '        compatible = "acme,rtc";\n'
        "        reg = <0x51>;\n"
        '        status = "disabled";'
    )
    assert codes(analyze(source, lookup), DiagnosticCode.BINDING_MISSING_PROPERTY) == []


def test_propiedad_no_admitida_en_schema_cerrado():
    """Un schema cerrado enumera todo lo admisible: lo demás sobra."""
    lookup = FakeLookup(
        {
            "acme,rtc": make_schema(
                "acme,rtc",
                properties={"compatible": {}, "reg": {}},
                required=("compatible",),
                closed=True,
            )
        }
    )
    source = build(
        '        compatible = "acme,rtc";\n'
        "        reg = <0x51>;\n"
        "        acme,invented = <1>;"
    )
    found = codes(analyze(source, lookup), DiagnosticCode.BINDING_UNKNOWN_PROPERTY)
    assert len(found) == 1
    assert "acme,invented" in found[0].message
    assert found[0].severity is Severity.WARNING


def test_schema_abierto_no_juzga_propiedades():
    """Con `additionalProperties: true` no se puede afirmar que nada sobre."""
    lookup = FakeLookup(
        {
            "acme,rtc": make_schema(
                "acme,rtc",
                properties={"compatible": {}, "reg": {}},
                closed=False,
            )
        }
    )
    source = build(
        '        compatible = "acme,rtc";\n'
        "        reg = <0x51>;\n"
        "        acme,invented = <1>;"
    )
    assert codes(analyze(source, lookup), DiagnosticCode.BINDING_UNKNOWN_PROPERTY) == []


def test_propiedad_admitida_por_el_binding_del_padre():
    """Lo que el bus declara para sus hijos no sobra en el hijo."""
    child = make_schema(
        "acme,bus", properties={"acme,cs-timing": {}}, closed=False
    )
    lookup = FakeLookup(
        schemas={
            "acme,rtc": make_schema(
                "acme,rtc", properties={"compatible": {}, "reg": {}}, closed=True
            ),
            "acme,bus": make_schema(
                "acme,bus", properties={"compatible": {}}, closed=False
            ),
        },
        children={("acme,bus", "rtc@51"): child},
    )
    source = '''/dts-v1/;
/ {
    model = "Placa de prueba";
    compatible = "test,board";
    #address-cells = <1>;
    #size-cells = <1>;

    bus@0 {
        compatible = "acme,bus";
        #address-cells = <1>;
        #size-cells = <0>;
        reg = <0 0x100>;

        rtc@51 {
            compatible = "acme,rtc";
            reg = <0x51>;
            acme,cs-timing = <3>;
        };
    };
};
'''
    assert codes(analyze(source, lookup), DiagnosticCode.BINDING_UNKNOWN_PROPERTY) == []


def test_compatible_sin_binding():
    """Un compatible que no documenta ningún binding se avisa como INFO."""
    lookup = FakeLookup({})
    source = build('        compatible = "acme,rtc";\n        reg = <0x51>;')
    found = codes(analyze(source, lookup), DiagnosticCode.BINDING_UNKNOWN_COMPATIBLE)
    assert len(found) == 1
    assert found[0].severity is Severity.INFO


def test_compatible_generico_documentado_no_avisa():
    """Basta con que uno de los compatibles del nodo esté documentado."""
    lookup = FakeLookup(
        {"acme,generic": make_schema("acme,generic", properties={"compatible": {}})}
    )
    source = build(
        '        compatible = "acme,specific", "acme,generic";\n        reg = <0x51>;'
    )
    assert (
        codes(analyze(source, lookup), DiagnosticCode.BINDING_UNKNOWN_COMPATIBLE) == []
    )


def test_compatible_rechazado():
    """Los compatibles de `incomplete-devices.yaml` se dicen por su nombre."""
    schema_id = "http://devicetree.org/schemas/incomplete-devices.yaml"
    lookup = FakeLookup(
        {
            "ohci-le": make_schema(
                "ohci-le",
                properties={"compatible": {}},
                required=("broken-usage-of-incorrect-compatible",),
                schema_id=schema_id,
            )
        }
    )
    source = build('        compatible = "ohci-le";\n        reg = <0x51>;')
    diagnostics = analyze(source, lookup)
    found = codes(diagnostics, DiagnosticCode.BINDING_REJECTED_COMPATIBLE)
    assert len(found) == 1
    # Y no se repite el requisito artificial que el propio schema inventa.
    assert codes(diagnostics, DiagnosticCode.BINDING_MISSING_PROPERTY) == []


def test_valor_fuera_del_enum():
    """Un valor que el schema no admite se reporta con su mensaje."""
    lookup = FakeLookup(
        {
            "acme,rtc": make_schema(
                "acme,rtc",
                properties={"compatible": {}, "reg": {}, "acme,mode": {}},
            )
        },
        types={"acme,mode": "string"},
        issues=(
            SchemaIssue(
                keyword="enum",
                message="'turbo' is not one of ['fast', 'slow']",
                property_name="acme,mode",
                schema_id="http://devicetree.org/schemas/test.yaml",
            ),
        ),
    )
    source = build(
        '        compatible = "acme,rtc";\n'
        "        reg = <0x51>;\n"
        '        acme,mode = "turbo";'
    )
    diagnostics = analyze_deferred(source, lookup)
    found = codes(diagnostics, DiagnosticCode.BINDING_PROPERTY_VALUE)
    assert len(found) == 1
    assert "turbo" in found[0].message
    assert found[0].property_name == "acme,mode"


def test_un_solo_aviso_por_propiedad():
    """El mismo valor puede incumplir al binding y a lo que hereda: se dice una vez."""
    issue = SchemaIssue(
        keyword="maximum",
        message="9000000 is greater than the maximum of 400000",
        property_name="clock-frequency",
        schema_id="http://devicetree.org/schemas/test.yaml",
    )
    lookup = FakeLookup(
        {
            "acme,rtc": make_schema(
                "acme,rtc", properties={"compatible": {}, "clock-frequency": {}}
            )
        },
        types={"clock-frequency": "uint32"},
        issues=(issue, issue),
    )
    source = build(
        '        compatible = "acme,rtc";\n        clock-frequency = <9000000>;'
    )
    diagnostics = analyze_deferred(source, lookup)
    found = codes(diagnostics, DiagnosticCode.BINDING_PROPERTY_VALUE)
    assert len(found) == 1


def test_valor_con_macro_no_se_juzga():
    """Mientras la macro no se resuelva (capa 3) el valor no se codifica."""
    lookup = FakeLookup(
        {
            "acme,rtc": make_schema(
                "acme,rtc", properties={"compatible": {}, "clock-frequency": {}}
            )
        },
        types={"clock-frequency": "uint32"},
        issues=(
            SchemaIssue(
                keyword="maximum",
                message="is greater than the maximum",
                property_name="clock-frequency",
                schema_id="http://devicetree.org/schemas/test.yaml",
            ),
        ),
    )
    source = build(
        '        compatible = "acme,rtc";\n'
        "        reg = <0x51>;\n"
        "        clock-frequency = <ACME_FAST_CLOCK>;"
    )
    diagnostics = analyze_deferred(source, lookup)
    assert codes(diagnostics, DiagnosticCode.BINDING_PROPERTY_VALUE) == []


def test_los_problemas_de_valor_del_schema_se_reportan():
    """De `validate_node` se cuentan los problemas de valor."""
    lookup = FakeLookup(
        {"acme,rtc": make_schema("acme,rtc", properties={"compatible": {}, "reg": {}})},
        issues=(
            SchemaIssue(
                keyword="maxItems",
                message="['a', 'b'] is too long",
                property_name="clock-output-names",
                schema_id="http://devicetree.org/schemas/test.yaml",
            ),
        ),
    )
    source = build(
        '        compatible = "acme,rtc";\n'
        "        reg = <0x51>;\n"
        '        clock-output-names = "a", "b";'
    )
    diagnostics = analyze_deferred(source, lookup)
    found = codes(diagnostics, DiagnosticCode.BINDING_PROPERTY_VALUE)
    assert len(found) == 1
    assert "clock-output-names" in found[0].message
    # El mensaje de la librería se traduce en lo reconocible.
    assert "is too long" in found[0].message


def test_los_problemas_estructurales_del_schema_no_se_repiten():
    """`required` y `additionalProperties` los cubren las reglas propias."""
    lookup = FakeLookup(
        {"acme,rtc": make_schema("acme,rtc", properties={"compatible": {}, "reg": {}})},
        issues=(
            SchemaIssue(
                keyword="required",
                message="'clocks' is a required property",
                property_name="clocks",
                schema_id="http://devicetree.org/schemas/test.yaml",
            ),
            SchemaIssue(
                keyword="additionalProperties",
                message="'acme,x' does not match any of the regexes",
                property_name="acme,x",
                schema_id="http://devicetree.org/schemas/test.yaml",
            ),
        ),
    )
    source = build('        compatible = "acme,rtc";\n        reg = <0x51>;')
    diagnostics = analyze_deferred(source, lookup)
    assert codes(diagnostics, DiagnosticCode.BINDING_PROPERTY_VALUE) == []


def test_sin_lookup_no_hay_capa_5():
    """Sin schemas inyectados el motor no dice nada de bindings."""
    source = build('        compatible = "acme,rtc";\n        reg = <0x51>;')
    result = parse_dts_source(source)
    diagnostics = run_checks(result, text=source)
    assert [d for d in diagnostics if d.code.value.startswith("binding-")] == []


def test_avisa_de_un_binding_posterior_al_kernel_objetivo():
    """Con un kernel declarado, un compatible más nuevo que él es un aviso.

    Y sin declararlo no se dice nada: es un dato que no está escrito en
    ningún device tree —el fuente no dice para qué kernel se compila—, así
    que mientras nadie lo aporte la regla se calla, como todas.
    """
    esquema = "http://devicetree.org/schemas/rtc/acme,rtc.yaml"
    lookup = FakeLookup(
        {
            "acme,rtc": make_schema(
                "acme,rtc",
                schema_id=esquema,
                properties={"compatible": {}, "reg": {}},
            )
        },
        since={esquema: "6.3"},
    )
    source = build('        compatible = "acme,rtc";\n        reg = <0x51>;')

    sin_objetivo = analyze(source, lookup)
    assert codes(sin_objetivo, DiagnosticCode.BINDING_NEWER_THAN_KERNEL) == []

    viejo = analyze(source, lookup, kernel_version="5.10")
    avisos = codes(viejo, DiagnosticCode.BINDING_NEWER_THAN_KERNEL)
    assert len(avisos) == 1
    assert "6.3" in avisos[0].message

    # 6.10 es posterior a 6.3, aunque como texto sea "menor".
    nuevo = analyze(source, lookup, kernel_version="6.10")
    assert codes(nuevo, DiagnosticCode.BINDING_NEWER_THAN_KERNEL) == []
