"""Contexto del cursor para el autocompletado.

Se resuelve sobre el texto, sin volver a analizarlo, porque mientras se
escribe el árbol va con retraso. Estas pruebas fijan lo que tiene que
reconocer, incluido lo que hay a medio escribir.
"""

from __future__ import annotations

from kernelgrove.api.completion import context_at

SOURCE = '''/dts-v1/;
/ {
    i2c@0 {
        compatible = "cdns,i2c-r1p14";
        rtc@51 {
            compatible = "nxp,pcf8563";
            clock-f
        };
    };
};

&uart0 {
    status = "ok
};
'''


def position_after(text: str, needle: str) -> int:
    """Posición justo después de la primera aparición de `needle`."""
    return text.index(needle) + len(needle)


def test_nodo_y_compatible_del_cursor():
    """Dentro de un nodo se reconoce su nombre y su compatible."""
    where = context_at(SOURCE, position_after(SOURCE, "clock-f"))

    assert where.node_name == "rtc@51"
    assert where.compatible == "nxp,pcf8563"
    assert where.property_name is None


def test_no_se_toma_el_compatible_del_padre():
    """El compatible del nodo es el suyo, no el del que lo contiene."""
    where = context_at(SOURCE, position_after(SOURCE, '"nxp,pcf8563";'))
    assert where.compatible == "nxp,pcf8563"


def test_cursor_en_el_valor():
    """Con un «=» delante, lo que se escribe es el valor de una propiedad."""
    where = context_at(SOURCE, position_after(SOURCE, 'status = "ok'))

    assert where.property_name == "status"
    # Y la cadena sin cerrar no descuadra el nodo que lo contiene.
    assert where.node_name == "&uart0"
    assert where.reference == "uart0"


def test_fuera_de_todo_nodo():
    """A nivel de fichero no hay nodo del que hablar."""
    where = context_at(SOURCE, position_after(SOURCE, "/dts-v1/;"))

    assert where.inside_node is False
    assert where.compatible is None


def test_los_comentarios_no_cuentan():
    """Una llave dentro de un comentario no abre ningún nodo."""
    source = '''/ {
    dev@0 {
        compatible = "acme,dev";  // no abre nada: {
        pro
    };
};
'''
    where = context_at(source, position_after(source, "        pro"))
    assert where.node_name == "dev@0"
    assert where.compatible == "acme,dev"


def test_nodo_sin_compatible():
    """Un contenedor sin compatible se reconoce igual, pero no tiene binding."""
    source = '''/ {
    soc {
        cl
    };
};
'''
    where = context_at(source, position_after(source, "        cl"))
    assert where.node_name == "soc"
    assert where.compatible is None
