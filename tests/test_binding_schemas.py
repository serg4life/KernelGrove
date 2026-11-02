"""Resolución de schemas de binding contra la base de datos real.

Estas pruebas necesitan `database/bindings.db` con la tabla `schemas`, que se
genera con `scripts/build_database.sh` (ver `docs/DT-SCHEMA-INTEGRATION.md`).
Si no está, se saltan: la base no se versiona.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kernelgrove.api.binding_schemas import BindingSchemaLookup

DB_PATH = Path(__file__).resolve().parents[1] / "database" / "bindings.db"

lookup = BindingSchemaLookup(DB_PATH) if DB_PATH.exists() else None

pytestmark = pytest.mark.skipif(
    lookup is None or not lookup.is_available(),
    reason="hace falta database/bindings.db con la tabla `schemas`",
)


def test_propiedades_obligatorias_incluyen_las_heredadas():
    """`required` sale del binding y de los schemas que referencia."""
    schema = lookup.schema_for("cdns,i2c-r1p14")

    assert schema is not None
    # `clocks` lo exige el propio binding; el compatible se resuelve por el
    # índice de compatibles, no por el nombre del fichero.
    assert set(schema.required) >= {"compatible", "reg", "clocks"}
    assert schema.schema_id.endswith("cdns,i2c-r1p10.yaml")


def test_hereda_las_propiedades_del_bus():
    """Un controlador I2C hereda de `i2c-controller.yaml`."""
    schema = lookup.schema_for("cdns,i2c-r1p14")

    assert "#address-cells" in schema.properties
    assert schema.properties["#address-cells"].origin.endswith("i2c-controller.yaml")
    assert schema.properties["#address-cells"].dt_type == "uint32"


def test_hereda_las_propiedades_de_la_clase():
    """Un RTC hereda de `rtc.yaml`, con su descripción."""
    schema = lookup.schema_for("nxp,pcf8563")

    assert schema.closed is True
    assert set(schema.required) == {"compatible", "reg"}
    inherited = schema.properties["aux-voltage-chargeable"]
    assert inherited.origin.endswith("rtc.yaml")
    assert inherited.description  # las descripciones salen del YAML original


def test_compatible_de_subnodo():
    """Un compatible declarado en un subnodo resuelve a ese subnodo."""
    schema = lookup.schema_for("ti,twl4030-pwm")

    assert schema is not None
    assert schema.schema_id.endswith("ti,twl.yaml")
    # Del subnodo, no del MFD entero: el PWM exige `#pwm-cells`, no `reg`.
    assert "#pwm-cells" in schema.required
    assert "reg" not in schema.required


def test_compatible_inventado_no_resuelve():
    """Un compatible que no existe no casa con ningún schema."""
    assert lookup.schema_for("acme,inventado-2000") is None
    assert lookup.is_documented("acme,inventado-2000") is False


def test_compatible_generico_no_identifica_binding():
    """`simple-bus` resuelve a su schema genérico, no a un binding cualquiera."""
    schema = lookup.schema_for("simple-bus")

    assert schema is not None
    assert schema.schema_id.endswith("simple-bus.yaml")


def test_gana_el_binding_que_se_llama_como_el_compatible():
    """`panel-lvds` lo declaran seis paneles concretos y su propio binding."""
    schema = lookup.schema_for("panel-lvds")

    assert schema is not None
    assert schema.schema_id.endswith("panel-lvds.yaml")
    # Y el panel concreto sigue resolviendo al suyo.
    specific = lookup.schema_for("advantech,idk-1110wr")
    assert specific.schema_id.endswith("advantech,idk-1110wr.yaml")


def test_ramas_condicionales_solo_admiten():
    """Lo declarado en un `if/then` cuenta como admitido, nunca como obligatorio."""
    schema = lookup.schema_for("rockchip,px30-io-voltage-domain")

    assert schema is not None
    assert schema.allows("vccio1-supply")
    assert "vccio1-supply" not in schema.required


def test_propiedades_del_bus_para_sus_hijos():
    """El binding de un bus describe lo que pueden llevar sus hijos."""
    child = lookup.child_schema_for("st,stm32mp1-fmc2-ebi", "ethernet@1,0")

    assert child is not None
    assert child.allows("bank-width")


def test_subdispositivos_de_un_mfd():
    """Un MFD declara en su binding las funciones que lleva dentro."""
    subdevices = lookup.subdevices_of("ti,twl4030")

    assert "ti,twl4030-pwm" in subdevices
    assert "ti,twl4030-gpio" in subdevices
    # Un dispositivo corriente no tiene funciones internas que ofrecer.
    assert lookup.subdevices_of("nxp,pcf8563") == []


def test_forma_del_valor_de_una_propiedad():
    """La forma se deduce del tipo, y tolera que el tipo varíe si la forma no."""
    # `clock-frequency` es uint32 en unos bindings y uint64 en otros: el tipo
    # es ambiguo pero la forma no, y es la forma lo que hace falta.
    assert lookup.property_type("clock-frequency") is None
    assert lookup.property_shape("clock-frequency") == "scalar"

    assert lookup.property_shape("clock-names") == "string"
    assert lookup.property_shape("reg") == "matrix"
    assert lookup.property_shape("gpios") == "phandle"
    assert lookup.property_shape("#gpio-cells") == "scalar"


def test_registro_de_prefijos_de_fabricante():
    """El registro del kernel dice qué prefijos existen."""
    assert lookup.is_known_property_name("xlnx,foo") is True
    assert lookup.is_known_property_name("clock-frequency") is True
    assert lookup.is_known_property_name("noexisteestefabricante,foo") is False


def test_validacion_de_valores_contra_el_binding():
    """El schema del binding juzga el valor de una propiedad."""
    schema = lookup.schema_for("cdns,i2c-r1p14")
    instance = {"$nodename": ["i2c@0"], "clock-frequency": 9000000}

    keywords = {issue.keyword for issue in lookup.validate_node(schema, instance)}
    assert "maximum" in keywords


def test_validacion_contra_los_bindings_genericos():
    """Los schemas con `select` se aplican por la forma del nodo."""
    instance = {"$nodename": ["gpio@0"], "gpio-controller": True}

    issues = lookup.validate_generic(instance)
    assert any(issue.property_name == "#gpio-cells" for issue in issues)
