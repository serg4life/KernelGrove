"""Traer la base de datos de donde esté publicada.

La base no viaja con el programa, así que la primera vez que se arranca hay
que ir a por ella. Lo que se comprueba aquí es lo que puede salir mal: que
no haya nada al otro lado (que es **hoy**, porque todavía no está
publicada), que llegue a medias, o que se cancele a mitad.

Con un servidor de verdad y no con un doble: lo que se prueba es leer un
`Content-Length`, trocear una descarga y comparar un `sha256`, y un doble de
`urlopen` no prueba ninguna de las tres.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import socketserver
import threading

import pytest

from kernelgrove import db_download


@pytest.fixture
def hosting(tmp_path):
    """Un servidor estático con su manifiesto y su base, como el de verdad."""
    contenido = os.urandom(300_000)
    (tmp_path / "bindings.db").write_bytes(contenido)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(tmp_path), **kwargs)

        def log_message(self, *args):
            """Sin ruido en la salida de las pruebas."""

    servidor = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    puerto = servidor.server_address[1]
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "version": "6.12",
                "url": f"http://127.0.0.1:{puerto}/bindings.db",
                "sha256": hashlib.sha256(contenido).hexdigest(),
                "bytes": len(contenido),
            }
        )
    )
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{puerto}/manifest.json", contenido
    servidor.shutdown()
    servidor.server_close()


def test_se_trae_la_base_y_se_comprueba_lo_que_ha_llegado(hosting, tmp_path):
    """Y se escribe en su sitio solo cuando está entera y es la que dice."""
    url, contenido = hosting
    manifest = db_download.fetch_manifest(url)
    assert manifest.version == "6.12"
    assert manifest.bytes == len(contenido)

    pasos = []
    destino = tmp_path / "nueva" / "bindings.db"
    resultado = db_download.download(
        manifest, destino, progress=lambda leidos, total: pasos.append(leidos) or True
    )

    assert resultado == destino
    assert destino.read_bytes() == contenido
    assert pasos and pasos[-1] == len(contenido)
    assert not list(destino.parent.glob("*.part")), "el temporal no se queda"


def test_una_base_que_no_cuadra_no_sustituye_a_la_que_habia(hosting, tmp_path):
    """68 MB por una red cualquiera: media descarga pesa como una entera.

    Y una base truncada falla mucho más tarde y de forma mucho más confusa
    que aquí.
    """
    url, contenido = hosting
    # En su propia carpeta: `tmp_path` es también la del servidor, y ahí
    # `bindings.db` es el fichero que se sirve.
    destino = tmp_path / "local" / "bindings.db"
    buena = db_download.fetch_manifest(url)
    db_download.download(buena, destino)

    mentirosa = db_download.fetch_manifest(url)
    mentirosa.sha256 = "0" * 64
    with pytest.raises(db_download.DatabaseDownloadError, match="corrupt"):
        db_download.download(mentirosa, destino)

    assert destino.read_bytes() == contenido, "la que había sigue entera"
    assert not list(destino.parent.glob("*.part"))


def test_cancelar_no_deja_restos(hosting, tmp_path):
    """Devolver `False` desde el progreso es lo que para la descarga."""
    url, _ = hosting
    destino = tmp_path / "local" / "bindings.db"
    with pytest.raises(db_download.DatabaseDownloadError, match="cancelled"):
        db_download.download(
            db_download.fetch_manifest(url), destino, progress=lambda *_: False
        )
    assert not destino.exists()
    assert not list(destino.parent.glob("*.part"))


def test_sin_nada_publicado_el_error_dice_dónde_se_ha_buscado():
    """Es el caso de hoy: el placeholder no existe todavía.

    Y es lo que dispara la salida de siempre —dar una base local—, así que
    tiene que fallar rápido y con un motivo legible, no con una traza.
    """
    with pytest.raises(db_download.DatabaseDownloadError) as error:
        db_download.fetch_manifest("http://no-existe.invalid/db/manifest.json")
    assert "no-existe.invalid" in str(error.value)


def test_un_manifiesto_sin_url_no_es_un_manifiesto(tmp_path):
    """Mejor decirlo aquí que intentar descargar de una cadena vacía."""
    with pytest.raises(db_download.DatabaseDownloadError):
        db_download.Manifest({"version": "6.12"})
