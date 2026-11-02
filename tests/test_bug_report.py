"""El parte de fallo del Inspector: que salga por la red y con qué datos.

Con un servidor de verdad y no con un doble: lo que se prueba es que la
petición sale bien formada de `QtNetwork` y que el diálogo se cierra cuando
llega la respuesta, y eso no lo prueba un `QNetworkAccessManager` fingido.
"""

from __future__ import annotations

import http.server
import json
import os
import socketserver
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="el parte es de la GUI")

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from kernelgrove.gui.widgets import bug_report_dialog  # noqa: E402


@pytest.fixture
def buzon(tmp_path):
    """Un endpoint que se queda con lo que le manden."""
    recibido = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - nombre de la API de http.server
            largo = int(self.headers["Content-Length"])
            recibido.append(json.loads(self.rfile.read(largo)))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"success": true}')

        def log_message(self, *args):
            """Sin ruido en la salida de las pruebas."""

    servidor = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{servidor.server_address[1]}/submit", recibido
    servidor.shutdown()
    servidor.server_close()


def test_el_parte_sale_con_el_compatible_y_la_causa(buzon, monkeypatch):
    """Enviar manda el nodo, su compatible y la causa elegida, y cierra."""
    url, recibido = buzon
    monkeypatch.setattr(bug_report_dialog, "REPORT_URL", url)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    app = QApplication.instance() or QApplication([])

    dialogo = bug_report_dialog.BugReportDialog("ti,twl4030", "pmic@48")
    dialogo._causes.setCurrentIndex(2)  # kernel-version
    dialogo._message.setPlainText("la versión de kernel no cuadra")
    dialogo.accept()

    # Con plazo, no con un número de vueltas: `processEvents` vuelve
    # enseguida cuando no hay nada que hacer, así que doscientas vueltas se
    # agotan en menos de un milisegundo y la respuesta del servidor local
    # todavía no ha llegado. `qWait` reparte eventos *y* espera.
    for _ in range(200):
        QTest.qWait(10)
        if dialogo.result() == QDialog.Accepted:
            break

    assert dialogo.result() == QDialog.Accepted
    # El diálogo se destruye aquí y no cuando el recolector pase: sin
    # padre, lo que queda es una ventana de nivel superior a la que Qt
    # sigue mandando eventos -un cambio de idioma, sin ir más lejos- con el
    # objeto de C++ ya liberado por Python, y eso es una segfault en la
    # prueba siguiente, no en ésta.
    dialogo.deleteLater()
    app.processEvents()

    assert recibido == [
        {
            "access_key": bug_report_dialog.REPORT_KEY,
            "subject": "[KernelGrove] ti,twl4030",
            "compatible": "ti,twl4030",
            "node": "pmic@48",
            "cause": "kernel-version",
            "version": recibido[0]["version"],
            "message": "la versión de kernel no cuadra",
        }
    ]
