"""Overlays: generar el fuente, resolver objetivos y previsualizar cambios.

Todo esto es lógica pura sobre el árbol interno —sin base de datos y sin
Qt—, así que se prueba directamente. La capa 6 (¿existe el objetivo en la
base?) vive en `test_overlay_checks.py`.
"""

from __future__ import annotations

from kernelgrove.api.overlays import (
    NodeAddition,
    OverlayFragment,
    PropertyEdit,
    build_overlay_source,
    format_value,
    label_index,
    overlay_targets,
    parse_overlay,
    preview_overlay,
)
from kernelgrove.dts_engine.parser import parse_dts_source

BASE = """/dts-v1/;
/ {
    soc {
        i2c0: i2c@ff020000 {
            compatible = "cdns,i2c-r1p14";
            status = "disabled";
            #address-cells = <1>;
        };
        uart0: serial@ff000000 {
            status = "disabled";
        };
    };
};
"""


def base_tree():
    """Árbol de la base sobre el que se aplican los overlays de prueba."""
    return parse_dts_source(BASE).root


# ----------------------------------------------------------------------
# Generación
# ----------------------------------------------------------------------
def test_el_fuente_generado_lleva_la_cabecera_de_overlay():
    """Sin `/dts-v1/;` y `/plugin/;` no es un overlay, es un fragmento suelto."""
    fuente = build_overlay_source(
        [
            OverlayFragment(
                target_label="i2c0",
                properties=[PropertyEdit("status", '"okay"')],
            )
        ]
    )

    assert "/dts-v1/;" in fuente
    assert "/plugin/;" in fuente
    assert "&i2c0 {" in fuente
    assert '    status = "okay";' in fuente
    assert fuente.rstrip().endswith("};")


def test_un_nodo_nuevo_se_escribe_dentro_del_objetivo():
    """Lo que se añade cuelga del nodo de la base, con su propia sangría."""
    fuente = build_overlay_source(
        [
            OverlayFragment(
                target_label="i2c0",
                added_nodes=[
                    NodeAddition(
                        "rtc@68",
                        [
                            PropertyEdit("compatible", '"dallas,ds1307"'),
                            PropertyEdit("reg", "<0x68>"),
                        ],
                    )
                ],
            )
        ]
    )

    assert "    rtc@68 {" in fuente
    assert '        compatible = "dallas,ds1307";' in fuente
    assert "    };" in fuente


def test_una_propiedad_sin_valor_se_escribe_como_marca():
    """`gpio-controller;` no lleva `=`: en device tree vale por estar."""
    fuente = build_overlay_source(
        [
            OverlayFragment(
                target_label="gpio",
                properties=[PropertyEdit("gpio-controller")],
            )
        ]
    )

    assert "    gpio-controller;" in fuente
    assert "gpio-controller =" not in fuente


def test_las_cabeceras_se_incluyen_no_se_pegan():
    """Se emite `#include`; copiar el contenido metería texto ajeno dentro."""
    fuente = build_overlay_source(
        [
            OverlayFragment(
                target_label="gpio", properties=[PropertyEdit("x", "<1>")]
            )
        ],
        includes=["dt-bindings/gpio/gpio.h"],
    )

    assert "#include <dt-bindings/gpio/gpio.h>" in fuente


def test_un_fragmento_sin_cambios_no_escribe_bloque():
    """Un `&x { };` vacío no dice nada y ensucia el fichero."""
    fuente = build_overlay_source(
        [
            OverlayFragment(target_label="vacio"),
            OverlayFragment(
                target_label="util", properties=[PropertyEdit("s", '"ok"')]
            ),
        ]
    )

    assert "&vacio" not in fuente
    assert "&util" in fuente


def test_se_puede_apuntar_por_ruta_cuando_no_hay_etiqueta():
    """`&{/ruta}` es la única forma si la base no exporta símbolos."""
    fuente = build_overlay_source(
        [
            OverlayFragment(
                target_path="/soc/i2c@ff020000",
                properties=[PropertyEdit("status", '"okay"')],
            )
        ]
    )

    assert "&{/soc/i2c@ff020000} {" in fuente


# ----------------------------------------------------------------------
# Forma del valor: en device tree el envoltorio *es* el tipo
# ----------------------------------------------------------------------
def test_el_valor_se_envuelve_segun_el_tipo_del_binding():
    """Una cadena va entre comillas y una celda entre `<>`; no es estilo."""
    assert format_value("string", "okay") == '"okay"'
    assert format_value("uint32", "400000") == "<400000>"
    assert format_value("phandle", "&gpio") == "&gpio"


def test_sin_tipo_declarado_se_decide_por_la_pinta_del_valor():
    """El binding no siempre dice el tipo; un número sigue siendo una celda."""
    assert format_value(None, "0x68") == "<0x68>"
    assert format_value(None, "42") == "<42>"
    assert format_value(None, "GPIO_ACTIVE_HIGH") == "<GPIO_ACTIVE_HIGH>"
    assert format_value(None, "okay") == '"okay"'


def test_un_valor_ya_envuelto_se_respeta():
    """Si el usuario lo escribió a mano, no se le añade otra capa."""
    assert format_value("string", '"okay"') == '"okay"'
    assert format_value("uint32", "<1 2 3>") == "<1 2 3>"


# ----------------------------------------------------------------------
# Objetivos
# ----------------------------------------------------------------------
def test_los_objetivos_se_resuelven_contra_la_base():
    """La pregunta de «¿este símbolo existe en el otro fichero?»."""
    overlay = parse_overlay(
        "/dts-v1/;\n/plugin/;\n"
        '&i2c0 { status = "okay"; };\n&nada { status = "okay"; };\n'
    )

    objetivos = overlay_targets(overlay, base_tree())
    por_referencia = {t.reference: t for t in objetivos}

    assert por_referencia["&i2c0"].resolved
    assert por_referencia["&i2c0"].resolved_path.endswith("i2c@ff020000")
    assert not por_referencia["&nada"].resolved


def test_sin_base_no_se_afirma_que_falte_ningun_objetivo():
    """Misma regla que el resto del motor: sin fuente que lo diga, se calla."""
    overlay = parse_overlay('/dts-v1/;\n/plugin/;\n&loquesea { status = "okay"; };\n')

    objetivos = overlay_targets(overlay, None)

    assert len(objetivos) == 1
    assert not objetivos[0].resolved


def test_el_indice_de_etiquetas_es_el_equivalente_de_symbols():
    """Es contra esto que resuelve un `&etiqueta`, como `__symbols__` en el .dtb."""
    etiquetas = label_index(base_tree())

    assert set(etiquetas) >= {"i2c0", "uart0"}
    assert etiquetas["uart0"].endswith("serial@ff000000")


# ----------------------------------------------------------------------
# Previsualización
# ----------------------------------------------------------------------
def test_la_previsualizacion_dice_que_cambia_y_que_se_añade():
    """Es la respuesta a «¿qué le haría este .dtbo a mi árbol?»."""
    overlay = parse_overlay(
        "/dts-v1/;\n/plugin/;\n"
        '&i2c0 { status = "okay"; rtc@68 { compatible = "dallas,ds1307"; }; };\n'
    )

    _, cambios = preview_overlay(base_tree(), overlay)
    por_tipo = {c.kind for c in cambios}
    cambiada = next(c for c in cambios if c.kind == "property-changed")

    assert por_tipo == {"property-changed", "node-added"}
    assert cambiada.name == "status"
    assert cambiada.before == '"disabled"'
    assert cambiada.after == '"okay"'


def test_la_previsualizacion_no_toca_la_base():
    """El árbol original tiene que quedar como estaba: se clona antes."""
    base = base_tree()
    antes = {n.path: dict(n.properties) for n in base.iter_tree()}

    preview_overlay(
        base, parse_overlay('/dts-v1/;\n/plugin/;\n&i2c0 { status = "okay"; };\n')
    )

    assert {n.path: dict(n.properties) for n in base.iter_tree()} == antes


def test_un_objetivo_inexistente_no_aparece_como_nodo_nuevo():
    """Eso ya lo cuenta la capa 6; contarlo dos veces confunde."""
    overlay = parse_overlay('/dts-v1/;\n/plugin/;\n&noexiste { status = "okay"; };\n')

    _, cambios = preview_overlay(base_tree(), overlay)

    assert cambios == []
