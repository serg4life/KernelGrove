"""El logotipo de la marca, empaquetado con la aplicación.

Los SVG originales están en `brand/logos/` del repositorio; aquí viaja una
copia dentro del paquete (`gui/brand/`), por lo mismo que la tipografía: un
programa de escritorio no puede depender de que haya red ni de dónde esté
instalado para verse bien.

Se dibujan con la tinta del tema activo. Hay dos colores que se sustituyen
antes de rasterizar:

- el negro de marca (`#0a0a0c`), el del nombre, que sobre el fondo oscuro de
  la aplicación no se vería: pasa a ser el color de texto que toque;
- el morado del brote (`_MARCA`), porque el morado dioxazina de la web se
  queda en 1,96:1 sobre el fondo oscuro — invisible, que es justo el defecto
  que la piel `obsidian` ya documenta. Dentro de la aplicación se conoce el
  fondo, así que se usa el par de la landing (`#612e81` claro / `#c187d4`
  oscuro).

El color que llevan los SVG en disco es un tercero, equilibrado (4,2:1 sobre
blanco y 4,4:1 sobre negro), porque el fichero también se copia tal cual a
sitios donde nadie sabe qué fondo hay detrás: el icono del `.deb`, la entrada
`.desktop` y el `.ico` de Windows.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from kernelgrove.gui import theme

# Los dos colores del SVG que se recolorean.
_INK = "#0a0a0c"
_MARCA = "#8b5cf6"

# El brote, dentro de la aplicación, donde el fondo sí se conoce.
_MARCA_CLARO = "#612e81"
_MARCA_OSCURO = "#c187d4"

_CARPETA = Path(__file__).resolve().parent / "brand"


def _pixmap(nombre: str, alto: int, tinta: str) -> QPixmap:
    """Rasteriza uno de los SVG a la altura pedida, con la tinta indicada."""
    marca = _MARCA_OSCURO if theme.is_dark() else _MARCA_CLARO
    fuente = (
        (_CARPETA / nombre).read_text().replace(_INK, tinta).replace(_MARCA, marca)
    )
    renderer = QSvgRenderer(fuente.encode())
    caja = renderer.viewBoxF()
    ancho = max(1, round(alto * caja.width() / caja.height()))
    pixmap = QPixmap(ancho, alto)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, ancho, alto))
    painter.end()
    return pixmap


def app_icon() -> QIcon:
    """Icono de la aplicación: solo el símbolo, sin el nombre.

    Es lo que enseñan la barra de tareas, el gestor de ventanas y el
    «Acerca de» (Qt lo saca del icono de la ventana). Se rasteriza en varios
    tamaños porque cada sitio pide el suyo y escalar uno solo se ve sucio.
    """
    icono = QIcon()
    for lado in (16, 24, 32, 48, 64, 128, 256):
        icono.addPixmap(_pixmap("logo-icon.svg", lado, theme.FG))
    return icono


def wordmark(alto: int) -> QPixmap:
    """Logotipo completo —símbolo y nombre— para la pantalla de bienvenida."""
    return _pixmap("logo.svg", alto, theme.FG)
