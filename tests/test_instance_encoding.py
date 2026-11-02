"""Codificación de un nodo como la instancia que espera un schema.

Es la pieza que permite validar valores contra los bindings. La regla que
fijan estas pruebas es la de siempre: si el valor no se puede traducir con
certeza, la propiedad se queda fuera y nadie habla de ella.
"""

from __future__ import annotations

from typing import Optional

from kernelgrove.dts_engine.checks.bindings.instance import encode_node, parent_cells_of
from kernelgrove.dts_engine.parser import parse_dts_source

SHAPES = {
    "compatible": "string",
    "clock-frequency": "scalar",
    "clock-names": "string",
    "clocks": "phandle",
    "interrupts": "matrix",
    "reg": "matrix",
    "gpio-controller": "flag",
    "ngpios": "scalar",
    "dma-channels": "array",
}


def shape_of(name: str) -> Optional[str]:
    """Formas declaradas para la prueba; lo demás es desconocido."""
    return SHAPES.get(name)


def node_of(source: str, name: str):
    """Devuelve el nodo indicado del fuente ya parseado."""
    root = parse_dts_source(source).root
    stack = [root]
    while stack:
        node = stack.pop()
        if node.name == name:
            return node
        stack.extend(node.children)
    raise AssertionError(f"no existe el nodo {name}")


def encode(source: str, name: str, parent_cells=(1, 1), macro_values=None):
    """Codifica un nodo del fuente con las formas de prueba."""
    node = node_of(source, name)
    return encode_node(
        node, dict(node.properties), shape_of, parent_cells, macro_values
    )


SOURCE = '''/ {
    dev@1000 {
        compatible = "acme,dev";
        reg = <0x1000 0x100>;
        clock-frequency = <400000>;
        clock-names = "core", "bus";
        ngpios = <8>;
        gpio-controller;
        dma-channels = <1 2 3>;
        clocks = <&clk 3>;
        interrupts = <GIC_SPI 42 IRQ_TYPE_LEVEL_HIGH>;
        acme,desconocida = <7>;
    };
};
'''


def test_formas_basicas():
    """Cada forma declarada produce la estructura que espera el schema."""
    encoded = encode(SOURCE, "dev@1000")
    instance = encoded.instance

    assert instance["$nodename"] == ["dev@1000"]
    # `compatible` entra: hay schemas que deciden qué exigir mirándolo.
    assert instance["compatible"] == ["acme,dev"]
    assert instance["clock-frequency"] == 400000       # escalar
    assert instance["clock-names"] == ["core", "bus"]  # cadenas
    assert instance["dma-channels"] == [1, 2, 3]       # lista
    assert instance["gpio-controller"] is True         # propiedad sin valor
    assert instance["reg"] == [[0x1000, 0x100]]        # matriz por celdas del padre


def test_lo_que_no_se_puede_codificar_queda_fuera():
    """Macros, phandles y tipos desconocidos no entran en la instancia."""
    encoded = encode(SOURCE, "dev@1000")

    # `interrupts` lleva macros de `dt-bindings/*.h`: es la capa 3.
    assert "interrupts" not in encoded.instance
    # `clocks` es un phandle: cuántas celdas ocupa lo dice el nodo apuntado.
    assert "clocks" not in encoded.instance
    # Sin tipo declarado no se sabe qué forma darle.
    assert "acme,desconocida" not in encoded.instance

    assert {"interrupts", "clocks", "acme,desconocida"} <= encoded.skipped
    assert encoded.covers("interrupts") is False
    assert encoded.covers("clock-frequency") is True


MACRO_SOURCE = '''/ {
    dev@1000 {
        dma-channels = <GIC_SPI 2 IRQ_TYPE_LEVEL_HIGH>;
    };
};
'''


def test_macros_resueltas_se_codifican_si_se_conocen():
    """Con el valor de la capa 3 disponible, la celda deja de ser opaca."""
    encoded = encode(
        MACRO_SOURCE,
        "dev@1000",
        macro_values={"GIC_SPI": 0, "IRQ_TYPE_LEVEL_HIGH": 4},
    )

    assert encoded.instance["dma-channels"] == [0, 2, 4]
    assert "dma-channels" not in encoded.skipped


def test_macro_a_medias_sigue_sin_codificarse():
    """Si falta el valor de alguna de las macros, la propiedad entera se calla."""
    encoded = encode(MACRO_SOURCE, "dev@1000", macro_values={"GIC_SPI": 0})

    assert "dma-channels" not in encoded.instance
    assert "dma-channels" in encoded.skipped


def test_reg_usa_las_celdas_del_padre():
    """Las filas de `reg` miden `#address-cells` + `#size-cells` del padre."""
    source = '''/ {
    bus {
        dev@0 {
            reg = <0x0 0x0 0x1000 0x0 0x2000 0x100>;
        };
    };
};
'''
    # Con 2 celdas de dirección y 1 de tamaño, son filas de tres.
    encoded = encode(source, "dev@0", parent_cells=(2, 1))
    assert encoded.instance["reg"] == [[0x0, 0x0, 0x1000], [0x0, 0x2000, 0x100]]


def test_reg_no_se_codifica_si_no_cuadra():
    """Si las celdas no son múltiplo del tamaño de fila, no se afirma nada."""
    source = '/ { dev@0 { reg = <0x1000 0x100 0x5>; }; };'
    encoded = encode(source, "dev@0", parent_cells=(1, 1))

    assert "reg" not in encoded.instance
    assert "reg" in encoded.skipped


def test_celdas_por_omision_de_la_especificacion():
    """Sin `#address-cells`/`#size-cells` valen los de la especificación."""
    assert parent_cells_of({}) == (2, 1)


def test_celdas_declaradas_por_el_padre():
    """Cuando el padre las declara, mandan las suyas."""
    source = '/ { bus { #address-cells = <1>; #size-cells = <0>; }; };'
    node = node_of(source, "bus")
    assert parent_cells_of(dict(node.properties)) == (1, 0)
