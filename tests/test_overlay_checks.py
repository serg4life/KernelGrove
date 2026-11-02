"""Capa 6: lo único que no se puede saber sin mirar la base.

La regla que gobierna todas las capas se aplica aquí igual: **sin base
inyectada no se dice nada**. Que un `&i2c9` no exista solo es un error si se
ha podido comprobar contra el árbol donde tendría que estar; en un overlay
suelto, callar es lo correcto.
"""

from __future__ import annotations

from kernelgrove.dts_engine.checks.overlay import check_overlay_layer
from kernelgrove.dts_engine.diagnostics import DiagnosticCode, Severity
from kernelgrove.dts_engine.parser import parse_dts_source

BASE = """/dts-v1/;
/ {
    soc {
        i2c0: i2c@ff020000 { status = "disabled"; };
        i2c1: i2c@ff030000 { status = "disabled"; };
        serial@ff000000 { status = "disabled"; };
    };
};
"""


def base_tree():
    """Árbol base contra el que se valida el overlay."""
    return parse_dts_source(BASE).root


def check(overlay_text: str, base=None):
    """Ejecuta la capa 6 sobre un overlay."""
    return check_overlay_layer(parse_dts_source(overlay_text), base)


def test_un_objetivo_que_existe_no_produce_nada():
    """El caso normal no dice nada: el motor no felicita, solo avisa."""
    overlay = '/dts-v1/;\n/plugin/;\n&i2c0 { status = "okay"; };\n'

    assert check(overlay, base_tree()) == []


def test_una_etiqueta_que_no_existe_es_un_error():
    """Es el fallo que buscabas: el símbolo de un fichero no está en el otro."""
    diagnostics = check(
        '/dts-v1/;\n/plugin/;\n&i2c9 { status = "okay"; };\n', base_tree()
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].code is DiagnosticCode.OVERLAY_TARGET_NOT_FOUND
    assert diagnostics[0].severity is Severity.ERROR
    assert "&i2c9" in diagnostics[0].message


def test_el_aviso_sugiere_las_etiquetas_parecidas():
    """El fallo típico es el número: `&i2c9` cuando hay `&i2c0` e `&i2c1`."""
    diagnostics = check(
        '/dts-v1/;\n/plugin/;\n&i2c9 { status = "okay"; };\n', base_tree()
    )

    assert "«&i2c0»" in diagnostics[0].hint
    assert "«&i2c1»" in diagnostics[0].hint


def test_sin_parecidas_se_explica_la_alternativa():
    """Si el nodo existe pero no tiene etiqueta, se apunta por ruta."""
    diagnostics = check(
        '/dts-v1/;\n/plugin/;\n&pmic { status = "okay"; };\n', base_tree()
    )

    assert "&{/path/to/node}" in diagnostics[0].hint


def test_apuntar_por_ruta_tambien_se_comprueba():
    """`&{/…}` es la otra forma de apuntar, y también puede estar mal."""
    buena = check(
        '/dts-v1/;\n/plugin/;\n&{/soc/i2c@ff020000} { status = "okay"; };\n',
        base_tree(),
    )
    mala = check(
        '/dts-v1/;\n/plugin/;\n&{/soc/no-existe} { status = "okay"; };\n',
        base_tree(),
    )

    assert buena == []
    assert len(mala) == 1
    assert "path" in mala[0].message


def test_sin_base_la_capa_se_calla():
    """No se puede afirmar que algo falte sin haber podido mirar dónde."""
    assert check('/dts-v1/;\n/plugin/;\n&loquesea { status = "okay"; };\n') == []


def test_el_diagnostico_apunta_a_la_linea_del_bloque():
    """Un aviso sin línea correcta obliga a buscar a mano."""
    overlay = (
        "/dts-v1/;\n"
        "/plugin/;\n"
        "\n"
        '&i2c0 { status = "okay"; };\n'
        "\n"
        '&malo { status = "okay"; };\n'
    )

    diagnostics = check(overlay, base_tree())

    assert diagnostics[0].line == 6
