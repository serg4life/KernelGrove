"""Tarjeta con barra de título: la forma del mockup de la web.

Es lo que en `landing_page/css/style.css` son `.mockup` y `.mockup-bar`: un
recuadro de 1 px con esquina de 12 px sobre el fondo elevado, y encima una
franja con el nombre del fichero. Los tres puntos de ventana del mockup no
están: en la web dicen «esto es una ventana de código» a quien todavía no ha
instalado nada, y dentro de la aplicación —donde ya se está mirando una— no
dicen nada y se comen el ancho del nombre.

Se dibuja igual con **cualquier piel**: la forma de la aplicación es una
sola y lo único que una piel cambia es la paleta. Antes solo aparecía con
la de la web y con la clásica se quedaba en un contenedor pelado, con lo
que cambiar de tema movía de sitio el contenido de dos paneles.

La usan el Inspector y la ficha de una propiedad, que son las dos que
enseñan lo que la base sabe del nodo que se está mirando.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget


class Card(QWidget):
    """Tarjeta del mockup: barra con tres puntos y título, y su contenido."""

    def __init__(self, parent=None):
        """Monta la barra vacía; el contenido lo pone `set_content`."""
        super().__init__(parent)
        self.setObjectName("card")
        # Una subclase de QWidget no pinta el fondo ni el borde que le
        # da la hoja de estilos si no se le pide: sin esto la franja
        # salía del color de su padre y se fundía con el panel de al
        # lado, que es justo lo que la línea de zona tiene que separar.
        self.setAttribute(Qt.WA_StyledBackground, True)

        bar = QWidget()
        bar.setObjectName("cardBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 10, 14, 10)

        self.title = QLabel("")
        self.title.setObjectName("cardTitle")
        self.title.setContentsMargins(6, 0, 0, 0)
        row.addWidget(self.title, 1)

        self._column = QVBoxLayout(self)
        self._column.setSpacing(0)
        # 1 px, el del propio marco: el contenido no puede pintarse encima
        # de la línea de la tarjeta.
        self._column.setContentsMargins(1, 1, 1, 1)
        self._column.addWidget(bar)

    def set_content(self, widget: QWidget) -> None:
        """Pone el widget que va dentro de la tarjeta, debajo de la barra."""
        self._column.addWidget(widget, 1)

    def set_title(self, text: Optional[str]) -> None:
        """Nombre que enseña la barra; vacío si no hay ninguno."""
        self.title.setText(text or "")

    def refresh_skin(self) -> None:
        """Vuelve a pulir el widget tras un cambio de piel.

        La forma no cambia —la tarjeta se dibuja siempre—, pero sus colores
        salen de la hoja QSS y Qt no la reevalúa por su cuenta cuando la
        hoja se recompone con otra paleta.
        """
        self.style().unpolish(self)
        self.style().polish(self)


