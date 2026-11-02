"""Lectura de ficheros del editor: qué se abre y qué se rechaza antes de leer.

El panel de carpetas no filtra por extensión, así que por aquí puede pasar un
`.db` de SQLite o una imagen de kernel. Cargarlos enteros como texto cuelga
al editor —una sola "línea" de varios MB— en vez de fallar con un aviso.
"""

from __future__ import annotations

from pathlib import Path

from kernelgrove.gui import file_io


def test_lee_un_device_tree_normal(tmp_path: Path):
    """El caso de siempre: texto UTF-8 devuelto tal cual, sin error."""
    path = tmp_path / "board.dts"
    path.write_text('/dts-v1/;\n/ { model = "placa"; };\n', encoding="utf-8")

    text, error = file_io.read_text_file(path)

    assert error is None
    assert text is not None and "placa" in text


def test_rechaza_un_binario_por_los_bytes_nul(tmp_path: Path):
    """Un `.db` de SQLite empieza por `SQLite format 3\\0`: se descarta al vuelo."""
    path = tmp_path / "bindings.db"
    path.write_bytes(b"SQLite format 3\x00" + b"\x01\x02\x03" * 100)

    text, error = file_io.read_text_file(path)

    assert text is None
    assert isinstance(error, file_io.FileLooksBinaryError)


def test_rechaza_lo_descomunal_sin_leerlo(tmp_path: Path):
    """Por encima del límite ni se abre: el aviso dice el tamaño y el tope."""
    path = tmp_path / "enorme.dts"
    path.write_text("x" * 2048, encoding="utf-8")

    text, error = file_io.read_text_file(path, max_size=1024)

    assert text is None
    assert isinstance(error, file_io.FileTooLargeError)
    assert error.size == 2048 and error.limit == 1024


def test_un_fichero_que_no_existe_devuelve_el_error_del_sistema(tmp_path: Path):
    """No se propaga la excepción: se devuelve para que el llamante la traduzca."""
    text, error = file_io.read_text_file(tmp_path / "no-existe.dts")

    assert text is None
    assert isinstance(error, OSError)


def test_texto_con_bytes_invalidos_se_lee_igual(tmp_path: Path):
    """Un fuente en latin-1 se abre con reemplazos, no se rechaza.

    No es un binario —no lleva NUL—, así que negarse a mostrarlo sería peor
    que enseñarlo con algún carácter sustituido.
    """
    path = tmp_path / "raro.dtsi"
    path.write_bytes("// año de fabricación\n".encode("latin-1"))

    text, error = file_io.read_text_file(path)

    assert error is None
    assert text is not None and text.startswith("//")


# ----------------------------------------------------------------------
# Qué es el fichero y cómo termina sus líneas
# ----------------------------------------------------------------------
def test_el_tipo_de_fichero_sale_de_la_extension():
    """La franja decía «DTS» con un `.json` delante, que es no decir nada."""
    assert file_io.language_of("zynqmp.dtsi") == "DTS"
    assert file_io.language_of("overlay.dtso") == "DTS overlay"
    assert file_io.language_of("bindings.json") == "JSON"
    assert file_io.language_of("gpio.h") == "C header"
    # Una extensión que no está en la tabla se dice tal cual, en vez de
    # mentir con la del editor; y sin extensión, texto plano.
    assert file_io.language_of("notas.xyz") == "XYZ"
    assert file_io.language_of("Makefile") == "Plain text"


def test_el_fin_de_linea_se_detecta_y_se_conserva():
    """Un `.dts` que venga de Windows no sale de aquí convertido sin más."""
    assert file_io.detect_newline("a\r\nb\r\n") == file_io.CRLF
    assert file_io.detect_newline("a\nb\n") == file_io.LF

    # Dentro del editor todo va en `\n`; el terminador vuelve al guardar.
    plano = file_io.normalize_newlines("a\r\nb\r\n")
    assert plano == "a\nb\n"
    assert file_io.apply_newlines(plano, file_io.CRLF) == "a\r\nb\r\n"

    # Y de vuelta: convertir a LF sí quita los `\r` que hubiera.
    assert file_io.apply_newlines("a\r\nb\r\n", file_io.LF) == "a\nb\n"
