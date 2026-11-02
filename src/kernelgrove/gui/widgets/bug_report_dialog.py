"""Parte de un fallo sobre un `compatible`, desde el Inspector.

**Nadie lo abre todavía**: el botón del Inspector está sin poner a
propósito. Hoy la única llamada de red de la aplicación es descargar la base
(`db_download`), que no manda nada del usuario; esto sí mandaría su texto a un
servicio de terceros. Antes de encenderlo hay que decidir si el parte va aquí
o directamente a las issues del repositorio.

El parte se manda desde el propio programa a un endpoint de formulario que
reenvía por correo: no hay que sacar al usuario a su cliente de correo (que
se abre por detrás y hay que ir a buscarlo), ni meter credenciales SMTP en
un binario que se distribuye. La clave del formulario es pública por diseño
—solo sirve para encaminar el mensaje al buzón del destinatario—.

La llamada va por `QtNetwork`, que es asíncrono: pulsar Enviar no congela la
ventana mientras la red responde, y no hace falta hilo ninguno.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from kernelgrove import __version__

# A dónde se manda el parte. Hay que sustituir la clave antes de encenderlo.
# ponytail: servicio de formularios (Web3Forms); si hace falta adjuntar el
# fuente o llevar seguimiento, esto pasa a ser un endpoint propio.
REPORT_URL = "https://api.web3forms.com/submit"
REPORT_KEY = "REPLACE_WITH_WEB3FORMS_KEY"


class BugReportDialog(QDialog):
    """Causa (desplegable) y mensaje opcional para un compatible concreto."""

    def __init__(self, compatible: str, node_name: str, parent=None):
        super().__init__(parent)
        self._compatible = compatible
        self._node_name = node_name
        self.setWindowTitle(self.tr("Report a bug"))

        self._causes = QComboBox()
        # El texto es el que se lee aquí, así que va traducido; lo que viaja
        # en el parte es la clave inglesa (`itemData`): quien lo recibe no
        # tiene por qué leer el idioma del que lo manda.
        for label, key in (
            (self.tr("No binding found for this compatible"), "no-binding"),
            (self.tr("Wrong properties listed (required/optional)"), "properties"),
            (self.tr("Wrong kernel version shown"), "kernel-version"),
            (self.tr("Wrong bus or device type"), "bus"),
            (self.tr("Wrong diagnostics on this node"), "diagnostics"),
            (self.tr("Something else"), "other"),
        ):
            self._causes.addItem(label, key)

        self._message = QPlainTextEdit()
        self._message.setPlaceholderText(
            self.tr("What did you expect to see? (optional)")
        )

        form = QFormLayout()
        form.addRow(self.tr("Compatible:"), QLabel(compatible or "—"))
        form.addRow(self.tr("What is wrong?"), self._causes)
        form.addRow(self.tr("Details:"), self._message)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self
        )
        self._buttons.button(QDialogButtonBox.Ok).setText(self.tr("Send"))
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._buttons)

        # El gestor tiene que sobrevivir a la petición, así que cuelga del
        # diálogo y no de la función que la lanza.
        self._network = QNetworkAccessManager(self)

    def accept(self) -> None:
        """Manda el parte. La ventana se cierra cuando la red contesta."""
        self._buttons.setEnabled(False)
        self._buttons.button(QDialogButtonBox.Ok).setText(self.tr("Sending…"))
        request = QNetworkRequest(QUrl(REPORT_URL))
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        payload = {
            "access_key": REPORT_KEY,
            "subject": f"[KernelGrove] {self._compatible or self._node_name}",
            "compatible": self._compatible,
            "node": self._node_name,
            "cause": self._causes.currentData(),
            "version": __version__,
            "message": self._message.toPlainText().strip(),
        }
        reply = self._network.post(request, json.dumps(payload).encode())
        reply.finished.connect(lambda: self._on_reply(reply, payload))

    def _on_reply(self, reply: QNetworkReply, payload: dict) -> None:
        """Cierra si llegó; si no, deja el parte en el portapapeles."""
        error = reply.errorString() if reply.error() != QNetworkReply.NoError else ""
        reply.deleteLater()
        if error:
            # Sin red no hay nada que reintentar automáticamente, y perder
            # lo escrito por un corte de red es la peor forma de acabar.
            QGuiApplication.clipboard().setText(json.dumps(payload, indent=2))
            QMessageBox.warning(
                self,
                self.tr("Report a bug"),
                self.tr(
                    "The report could not be sent: {error}. It was copied to "
                    "the clipboard."
                ).format(error=error),
            )
            self._buttons.setEnabled(True)
            self._buttons.button(QDialogButtonBox.Ok).setText(self.tr("Send"))
            return
        QMessageBox.information(
            self, self.tr("Report a bug"), self.tr("Report sent. Thank you.")
        )
        super().accept()
