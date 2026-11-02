"""Iconos planos dibujados a mano, para no depender de iconografía de sistema.

Mismo criterio que `TabCloseButton` o el icono de fichero de
`FileExplorerPanel`: un `QPainterPath` minúsculo es más simple, más
consistente entre plataformas y más nítido a cualquier resolución que tirar
de un fichero de recursos o de los iconos que trae el estilo Qt.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)


def folder_icon(size: int, color: str, active_color: Optional[str] = None) -> QIcon:
    """Carpeta: cuerpo rectangular con una pestaña en la esquina superior."""
    return _icon(_folder_pixmap, size, color, active_color)


def tree_icon(size: int, color: str, active_color: Optional[str] = None) -> QIcon:
    """Estructura: un nodo raíz ramificando en dos hojas, como un mini organigrama."""
    return _icon(_tree_pixmap, size, color, active_color)


def branch_icon(size: int, color: str, active_color: Optional[str] = None) -> QIcon:
    """Versiones: la rama de git de toda la vida, dos puntos y una derivación."""
    return _icon(_branch_pixmap, size, color, active_color)


def layers_icon(size: int, color: str, active_color: Optional[str] = None) -> QIcon:
    """Overlays: dos láminas desplazadas, una encima de otra."""
    return _icon(_layers_pixmap, size, color, active_color)


def database_icon(size: int, color: str, active_color: Optional[str] = None) -> QIcon:
    """Base de datos: el `dns` del proyecto de referencia, dos bastidores."""
    return _icon(_database_pixmap, size, color, active_color)


def list_icon(size: int, color: str, active_color: Optional[str] = None) -> QIcon:
    """Lista: tres filas con su viñeta, frente al organigrama del grafo."""
    return _icon(_list_pixmap, size, color, active_color)


def chip_icon(size: int, color: str, active_color: Optional[str] = None) -> QIcon:
    """`memory`: el chip con sus patillas. Marca un SoC."""
    return _icon(_chip_pixmap, size, color, active_color)


def board_icon(size: int, color: str, active_color: Optional[str] = None) -> QIcon:
    """`developer_board`: la placa con su chip dentro. Marca una board."""
    return _icon(_board_pixmap, size, color, active_color)


def search_icon(size: int, color: str) -> QIcon:
    """`search`: la lupa, dentro de las cajas de búsqueda."""
    return _icon(_search_pixmap, size, color, None)


def split_icon(size: int, color: str) -> QIcon:
    """`call_split`: la rama que se bifurca, junto al nombre de la rama."""
    return _icon(_split_pixmap, size, color, None)


def error_icon(size: int, color: str) -> QIcon:
    """`error`: el círculo con la admiración."""
    return _icon(_error_pixmap, size, color, None)


def warning_icon(size: int, color: str) -> QIcon:
    """`warning`: el triángulo con la admiración."""
    return _icon(_warning_pixmap, size, color, None)


def cable_icon(size: int, color: str) -> QIcon:
    """`cable`: el conector, junto a lo que trae la base de datos."""
    return _icon(_cable_pixmap, size, color, None)


def plus_icon(size: int, color: str) -> QIcon:
    """`add`: acercar en el lienzo."""
    return _icon(_plus_pixmap, size, color, None)


def minus_icon(size: int, color: str) -> QIcon:
    """`remove`: alejar en el lienzo."""
    return _icon(_minus_pixmap, size, color, None)


def fit_icon(size: int, color: str) -> QIcon:
    """`fit_screen`: encuadrar; las cuatro esquinas de un marco."""
    return _icon(_fit_pixmap, size, color, None)


def build_icon(size: int, color: str, active_color: Optional[str] = None) -> QIcon:
    """`build`: la llave inglesa. Compilar.

    Con `active_color` porque también es el icono de una sección de la
    franja lateral, y ahí el estado marcado se pinta en otro tono.
    """
    return _icon(_build_pixmap, size, color, active_color)


def unarchive_icon(size: int, color: str) -> QIcon:
    """`unarchive`: la caja con la flecha saliendo. Descompilar."""
    return _icon(_unarchive_pixmap, size, color, None)


def cloud_icon(size: int, color: str) -> QIcon:
    """`cloud`: lo que no está en la carpeta del usuario sino en la base.

    La lista de BUILD TOOLS mezcla ficheros del proyecto con árboles del
    catálogo, y un árbol del catálogo no está en ninguna ruta del disco: se
    escribe a un temporal para compilarlo y el temporal se borra. Ese es el
    dato que la fila tiene que decir antes de que alguien lo busque en su
    carpeta y no lo encuentre.
    """
    return _icon(_cloud_pixmap, size, color, None)


def usb_icon(size: int, color: str) -> QIcon:
    """Puerto genérico: una clavija encajada en su zócalo."""
    return _icon(_usb_pixmap, size, color, None)


def network_icon(size: int, color: str) -> QIcon:
    """Red: un nodo central con sus enlaces a cuatro puntos."""
    return _icon(_network_pixmap, size, color, None)


def sensor_icon(size: int, color: str) -> QIcon:
    """`sensors`: un punto emitiendo dos arcos concéntricos."""
    return _icon(_sensor_pixmap, size, color, None)


def speaker_icon(size: int, color: str) -> QIcon:
    """Altavoz: el cono y dos arcos de sonido saliendo."""
    return _icon(_speaker_pixmap, size, color, None)


def display_icon(size: int, color: str) -> QIcon:
    """Pantalla: el marco y su peana."""
    return _icon(_display_pixmap, size, color, None)


def keyboard_icon(size: int, color: str) -> QIcon:
    """Teclado: el cuerpo y dos filas de teclas."""
    return _icon(_keyboard_pixmap, size, color, None)


def led_icon(size: int, color: str) -> QIcon:
    """Bombilla: el globo, el filamento y la rosca."""
    return _icon(_led_pixmap, size, color, None)


def bolt_icon(size: int, color: str) -> QIcon:
    """Rayo: alimentación."""
    return _icon(_bolt_pixmap, size, color, None)


def pulse_icon(size: int, color: str) -> QIcon:
    """Onda cuadrada: temporización (relojes, PWM)."""
    return _icon(_pulse_pixmap, size, color, None)


def shield_icon(size: int, color: str) -> QIcon:
    """Escudo: seguridad."""
    return _icon(_shield_pixmap, size, color, None)


def dots_icon(size: int, color: str) -> QIcon:
    """Cuadrícula de cuatro: lo que no encaja en ningún otro grupo."""
    return _icon(_dots_pixmap, size, color, None)


def chevron_icon(size: int, color: str, expanded: bool = False) -> QIcon:
    """Galón de plegado: a la derecha plegado, hacia abajo desplegado.

    Lo dibuja el panel de carpetas **en el hueco del icono** de la fila, no
    en la columna de ramas que `QTreeView` reserva a su izquierda: ahí
    quedaba a un paso de sangrado del nombre, leyéndose como una columna
    aparte. Aquí ocupa el mismo sitio que el icono de un fichero, así que
    los nombres de carpeta y de fichero caen en la misma vertical.
    """
    draw = _chevron_down_pixmap if expanded else _chevron_right_pixmap
    return _icon(draw, size, color, None)


def document_icon(size: int, color: str) -> QIcon:
    """Documento: contorno con la esquina superior derecha doblada.

    Lo usa el explorador de carpetas para sus ficheros. Vivía allí con su
    propia copia del andamiaje de `QPixmap`/`QPainter`; aquí comparte el de
    los demás iconos, y con él el ajuste de densidad de pantalla.
    """
    return _icon(_document_pixmap, size, color, None)


def _chip_pixmap(size: int, color: str) -> QPixmap:
    """`memory`: cuadrado con núcleo dentro y patillas por los cuatro lados."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    cuerpo = QRectF(size * 0.24, size * 0.24, size * 0.52, size * 0.52)
    painter.drawRect(cuerpo)
    painter.drawRect(
        QRectF(size * 0.38, size * 0.38, size * 0.24, size * 0.24)
    )
    for fraccion in (0.38, 0.62):
        painter.drawLine(
            QPointF(size * fraccion, size * 0.09),
            QPointF(size * fraccion, cuerpo.top()),
        )
        painter.drawLine(
            QPointF(size * fraccion, cuerpo.bottom()),
            QPointF(size * fraccion, size * 0.91),
        )
        painter.drawLine(
            QPointF(size * 0.09, size * fraccion),
            QPointF(cuerpo.left(), size * fraccion),
        )
        painter.drawLine(
            QPointF(cuerpo.right(), size * fraccion),
            QPointF(size * 0.91, size * fraccion),
        )

    painter.end()
    return pixmap


def _board_pixmap(size: int, color: str) -> QPixmap:
    """`developer_board`: la placa, con un chip pequeño y sus pistas."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    placa = QRectF(size * 0.12, size * 0.2, size * 0.76, size * 0.6)
    painter.drawRoundedRect(placa, size * 0.06, size * 0.06)
    painter.drawRect(
        QRectF(size * 0.22, size * 0.32, size * 0.26, size * 0.26)
    )
    for fraccion in (0.36, 0.5, 0.64):
        painter.drawLine(
            QPointF(size * 0.58, size * fraccion),
            QPointF(size * 0.78, size * fraccion),
        )

    painter.end()
    return pixmap


def _search_pixmap(size: int, color: str) -> QPixmap:
    """`search`: la lupa, con su mango hacia abajo a la derecha."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    centro = QPointF(size * 0.43, size * 0.43)
    radio = size * 0.24
    painter.drawEllipse(centro, radio, radio)
    painter.drawLine(
        QPointF(centro.x() + radio * 0.72, centro.y() + radio * 0.72),
        QPointF(size * 0.86, size * 0.86),
    )

    painter.end()
    return pixmap


def _split_pixmap(size: int, color: str) -> QPixmap:
    """`call_split`: un camino que sube y se abre en dos."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    painter.drawLine(QPointF(size * 0.5, size * 0.9), QPointF(size * 0.5, size * 0.55))
    for lado in (-1, 1):
        extremo = QPointF(size * (0.5 + lado * 0.28), size * 0.24)
        painter.drawLine(QPointF(size * 0.5, size * 0.55), extremo)
        # Punta de flecha: dos trazos cortos hacia dentro.
        painter.drawLine(extremo, QPointF(extremo.x(), size * 0.4))
        painter.drawLine(extremo, QPointF(size * (0.5 + lado * 0.1), size * 0.24))

    painter.end()
    return pixmap


def _error_pixmap(size: int, color: str) -> QPixmap:
    """`error`: círculo con la admiración dentro."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    painter.drawEllipse(QPointF(size * 0.5, size * 0.5), size * 0.36, size * 0.36)
    painter.drawLine(QPointF(size * 0.5, size * 0.28), QPointF(size * 0.5, size * 0.56))
    painter.setBrush(QColor(color))
    painter.drawEllipse(QPointF(size * 0.5, size * 0.7), size * 0.055, size * 0.055)

    painter.end()
    return pixmap


def _warning_pixmap(size: int, color: str) -> QPixmap:
    """`warning`: triángulo con la admiración dentro."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    triangulo = QPainterPath()
    triangulo.moveTo(size * 0.5, size * 0.14)
    triangulo.lineTo(size * 0.92, size * 0.84)
    triangulo.lineTo(size * 0.08, size * 0.84)
    triangulo.closeSubpath()
    painter.drawPath(triangulo)
    painter.drawLine(QPointF(size * 0.5, size * 0.42), QPointF(size * 0.5, size * 0.63))
    painter.setBrush(QColor(color))
    painter.drawEllipse(QPointF(size * 0.5, size * 0.74), size * 0.05, size * 0.05)

    painter.end()
    return pixmap


def _cable_pixmap(size: int, color: str) -> QPixmap:
    """`cable`: dos conectores enfrentados unidos por su cable."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    for lado in (0, 1):
        x = size * (0.1 if lado == 0 else 0.62)
        cuerpo = QRectF(x, size * 0.3, size * 0.28, size * 0.4)
        painter.drawRoundedRect(cuerpo, size * 0.05, size * 0.05)
        for fraccion in (0.42, 0.58):
            borde = cuerpo.right() if lado == 0 else cuerpo.left()
            fuera = borde + (size * 0.1 if lado == 0 else -size * 0.1)
            painter.drawLine(
                QPointF(borde, size * fraccion), QPointF(fuera, size * fraccion)
            )

    painter.end()
    return pixmap


def _plus_pixmap(size: int, color: str) -> QPixmap:
    """`add`: la cruz."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)
    painter.drawLine(QPointF(size * 0.5, size * 0.2), QPointF(size * 0.5, size * 0.8))
    painter.drawLine(QPointF(size * 0.2, size * 0.5), QPointF(size * 0.8, size * 0.5))
    painter.end()
    return pixmap


def _minus_pixmap(size: int, color: str) -> QPixmap:
    """`remove`: el trazo horizontal."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)
    painter.drawLine(QPointF(size * 0.2, size * 0.5), QPointF(size * 0.8, size * 0.5))
    painter.end()
    return pixmap


def _fit_pixmap(size: int, color: str) -> QPixmap:
    """`fit_screen`: las cuatro esquinas de un marco, sin sus lados."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    corto = size * 0.16
    for x, y, dx, dy in (
        (0.18, 0.18, 1, 1),
        (0.82, 0.18, -1, 1),
        (0.18, 0.82, 1, -1),
        (0.82, 0.82, -1, -1),
    ):
        esquina = QPointF(size * x, size * y)
        painter.drawLine(esquina, QPointF(esquina.x() + dx * corto, esquina.y()))
        painter.drawLine(esquina, QPointF(esquina.x(), esquina.y() + dy * corto))

    painter.end()
    return pixmap


def _build_pixmap(size: int, color: str) -> QPixmap:
    """`build`: la llave inglesa — boca abierta arriba y mango en diagonal.

    La boca es un arco al que le falta el cuadrante superior izquierdo, que
    es lo que la hace reconocible como llave y no como un círculo con un
    palo. Dibujarla como un rombo (lo que había antes) salía como una
    punta de flecha.
    """
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    radio = size * 0.19
    centro = QPointF(size * 0.32, size * 0.32)
    boca = QRectF(
        centro.x() - radio, centro.y() - radio, radio * 2, radio * 2
    )
    # De 180° recorriendo -270°: queda sin dibujar el cuadrante de 90° a
    # 180°, o sea la esquina superior izquierda. Qt cuenta en 1/16 de grado
    # y en sentido antihorario desde las tres en punto.
    painter.drawArc(boca, 180 * 16, -270 * 16)
    painter.drawLine(
        QPointF(centro.x() + radio * 0.7, centro.y() + radio * 0.7),
        QPointF(size * 0.84, size * 0.84),
    )

    painter.end()
    return pixmap


def _unarchive_pixmap(size: int, color: str) -> QPixmap:
    """`unarchive`: la tapa arriba, la caja debajo y algo saliendo por dentro."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    painter.drawRect(QRectF(size * 0.1, size * 0.14, size * 0.8, size * 0.16))
    painter.drawRect(QRectF(size * 0.18, size * 0.36, size * 0.64, size * 0.5))
    flecha = QPointF(size * 0.5, size * 0.46)
    painter.drawLine(QPointF(size * 0.5, size * 0.78), flecha)
    painter.drawLine(flecha, QPointF(size * 0.36, size * 0.6))
    painter.drawLine(flecha, QPointF(size * 0.64, size * 0.6))

    painter.end()
    return pixmap


def _icon(
    draw: Callable[[int, str], QPixmap],
    size: int,
    color: str,
    active_color: Optional[str],
) -> QIcon:
    """Compone un `QIcon` con un pixmap "apagado" y, si se da, uno "activo".

    Un `QToolButton` marcable (`setCheckable`) cambia solo entre los estados
    `Off`/`On` de su icono al pulsarse — sin esto, el icono se quedaría del
    mismo gris apagado tanto elegido como sin elegir en la `ActivityBar`, y
    la única pista de cuál está activo sería el fondo del botón.
    """
    icon = QIcon()
    icon.addPixmap(draw(size, color), QIcon.Normal, QIcon.Off)
    if active_color:
        icon.addPixmap(draw(size, active_color), QIcon.Normal, QIcon.On)
    return icon


def _folder_pixmap(size: int, color: str) -> QPixmap:
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    tab_width = size * 0.42
    tab_height = size * 0.14
    body_top = size * 0.28
    margin = size * 0.12

    path = QPainterPath()
    path.moveTo(margin, body_top)
    path.lineTo(margin, body_top - tab_height)
    path.lineTo(margin + tab_width * 0.5, body_top - tab_height)
    path.lineTo(margin + tab_width * 0.5 + tab_height, body_top)
    path.closeSubpath()
    painter.drawPath(path)

    body = QRectF(margin, body_top, size - 2 * margin, size - body_top - margin)
    painter.drawRoundedRect(body, size * 0.06, size * 0.06)

    painter.end()
    return pixmap


def _tree_pixmap(size: int, color: str) -> QPixmap:
    """`account_tree`: un nodo a la izquierda y dos a la derecha, con su enlace.

    Rectángulos y no puntos, como el icono del proyecto de referencia y
    como las fichas que dibuja el propio grafo.
    """
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    ancho, alto = size * 0.26, size * 0.2
    raiz = QRectF(size * 0.08, size * 0.4, ancho, alto)
    superior = QRectF(size * 0.62, size * 0.14, ancho + size * 0.04, alto)
    inferior = QRectF(size * 0.62, size * 0.66, ancho + size * 0.04, alto)

    codo = size * 0.47
    painter.drawLine(
        QPointF(raiz.right(), raiz.center().y()), QPointF(codo, raiz.center().y())
    )
    painter.drawLine(
        QPointF(codo, superior.center().y()),
        QPointF(codo, inferior.center().y()),
    )
    for hoja in (superior, inferior):
        painter.drawLine(
            QPointF(codo, hoja.center().y()), QPointF(hoja.left(), hoja.center().y())
        )
    for caja in (raiz, superior, inferior):
        painter.drawRect(caja)

    painter.end()
    return pixmap


def _branch_pixmap(size: int, color: str) -> QPixmap:
    """`alt_route`: un tronco que sigue recto y una vía que se desvía.

    El icono que el proyecto de referencia usa para el control de
    versiones. Se distingue del organigrama (`_tree_pixmap`) en que aquí no
    hay cajas: son dos caminos.
    """
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    radio = size * 0.085
    salida = QPointF(size * 0.32, size * 0.84)
    bifurcacion = QPointF(size * 0.32, size * 0.5)
    recto = QPointF(size * 0.32, size * 0.16)
    desvio = QPointF(size * 0.74, size * 0.16)

    painter.drawLine(salida, recto)
    curva = QPainterPath()
    curva.moveTo(bifurcacion)
    curva.cubicTo(
        QPointF(size * 0.32, size * 0.3),
        QPointF(desvio.x(), size * 0.42),
        desvio,
    )
    painter.drawPath(curva)

    painter.setBrush(QColor(color))
    painter.setPen(Qt.NoPen)
    for punto in (salida, recto, desvio):
        painter.drawEllipse(punto, radio, radio)

    painter.end()
    return pixmap


def _layers_pixmap(size: int, color: str) -> QPixmap:
    """Dos rombos apilados: un overlay es una lámina sobre la base."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    for offset in (size * 0.22, size * 0.5):
        sheet = QPainterPath()
        sheet.moveTo(size * 0.5, offset - size * 0.14)
        sheet.lineTo(size * 0.84, offset)
        sheet.lineTo(size * 0.5, offset + size * 0.14)
        sheet.lineTo(size * 0.16, offset)
        sheet.closeSubpath()
        painter.drawPath(sheet)

    painter.end()
    return pixmap


def _database_pixmap(size: int, color: str) -> QPixmap:
    """`dns`: dos bastidores apilados, cada uno con su piloto a la izquierda.

    No es el cilindro de discos de una base de datos relacional: el
    proyecto de referencia usa `dns` para el catálogo de hardware, y en un
    catálogo de SoCs un bastidor dice más que un disco.
    """
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    alto = size * 0.26
    for arriba in (size * 0.16, size * 0.56):
        caja = QRectF(size * 0.14, arriba, size * 0.72, alto)
        painter.drawRoundedRect(caja, size * 0.06, size * 0.06)
        painter.setBrush(QColor(color))
        painter.drawEllipse(
            QPointF(caja.left() + size * 0.13, caja.center().y()),
            size * 0.055,
            size * 0.055,
        )
        painter.setBrush(Qt.NoBrush)

    painter.end()
    return pixmap


def _list_pixmap(size: int, color: str) -> QPixmap:
    """Tres filas con su viñeta: una lista, no un árbol."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    radio = size * 0.055
    for fraccion in (0.28, 0.5, 0.72):
        y = size * fraccion
        painter.setBrush(QColor(color))
        painter.drawEllipse(QPointF(size * 0.24, y), radio, radio)
        painter.setBrush(Qt.NoBrush)
        painter.drawLine(QPointF(size * 0.4, y), QPointF(size * 0.8, y))

    painter.end()
    return pixmap


def _document_pixmap(size: int, color: str) -> QPixmap:
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)
    painter.setPen(_thin_pen(painter, size))

    margin = size * 0.18
    fold = size * 0.32
    path = QPainterPath()
    path.moveTo(margin, margin)
    path.lineTo(size - margin - fold, margin)
    path.lineTo(size - margin, margin + fold)
    path.lineTo(size - margin, size - margin)
    path.lineTo(margin, size - margin)
    path.closeSubpath()
    painter.drawPath(path)

    fold_path = QPainterPath()
    fold_path.moveTo(size - margin - fold, margin)
    fold_path.lineTo(size - margin - fold, margin + fold)
    fold_path.lineTo(size - margin, margin + fold)
    painter.drawPath(fold_path)

    painter.end()
    return pixmap


def _thin_pen(painter: QPainter, size: int) -> QPen:
    """Trazo más fino que el común: el icono de fichero es mucho más pequeño."""
    pen = painter.pen()
    pen.setWidthF(max(1.0, size * 0.085))
    return pen


def _new_pixmap(size: int) -> QPixmap:
    """Pixmap cuadrado de `size` píxeles *lógicos*, nítido en pantallas HiDPI.

    Un `QPixmap(size, size)` a secas se crea en píxeles lógicos: con el
    escalado a ×2 de una pantalla de alta densidad, Qt lo amplía
    interpolando y el trazo fino queda borroso — justo lo que se quería
    evitar dibujándolo a mano. Se pinta al tamaño físico real y se declara
    la densidad con `setDevicePixelRatio`, con lo que el `QPainter` sigue
    aceptando coordenadas lógicas (de 0 a `size`) y el dibujo de cada icono
    no cambia.
    """
    ratio = _device_pixel_ratio()
    pixmap = QPixmap(round(size * ratio), round(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    return pixmap


def _device_pixel_ratio() -> float:
    """Densidad de la pantalla principal, o 1.0 si aún no hay `QGuiApplication`."""
    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    return screen.devicePixelRatio() if screen is not None else 1.0


def _chevron_right_pixmap(size: int, color: str) -> QPixmap:
    """`chevron_right`: dos trazos en punta hacia la derecha."""
    return _chevron_pixmap(size, color, expanded=False)


def _chevron_down_pixmap(size: int, color: str) -> QPixmap:
    """`expand_more`: los mismos dos trazos girados hacia abajo."""
    return _chevron_pixmap(size, color, expanded=True)


def _chevron_pixmap(size: int, color: str, expanded: bool) -> QPixmap:
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)
    painter.setPen(_thin_pen(painter, size))

    if expanded:
        vertice = QPointF(size * 0.5, size * 0.65)
        extremos = (QPointF(size * 0.26, size * 0.4), QPointF(size * 0.74, size * 0.4))
    else:
        vertice = QPointF(size * 0.64, size * 0.5)
        extremos = (QPointF(size * 0.4, size * 0.26), QPointF(size * 0.4, size * 0.74))
    for extremo in extremos:
        painter.drawLine(vertice, extremo)

    painter.end()
    return pixmap


def _cloud_pixmap(size: int, color: str) -> QPixmap:
    """`cloud`: tres arcos sobre una base recta, cerrados en un solo trazo.

    El último arco baja hasta la misma altura de la base, y por eso se cierra
    con `closeSubpath` en horizontal: acabándolo a media altura, la línea de
    cierre salía en diagonal y la nube parecía volcada.
    """
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)
    painter.setPen(_thin_pen(painter, size))

    base = size * 0.70
    path = QPainterPath()
    path.moveTo(size * 0.30, base)
    path.arcTo(
        QRectF(size * 0.13, base - size * 0.34, size * 0.34, size * 0.34), 270.0, -180.0
    )
    path.arcTo(
        QRectF(size * 0.26, size * 0.18, size * 0.40, size * 0.40), 170.0, -160.0
    )
    path.arcTo(
        QRectF(size * 0.56, base - size * 0.32, size * 0.32, size * 0.32), 105.0, -180.0
    )
    path.closeSubpath()
    painter.drawPath(path)

    painter.end()
    return pixmap


def _new_painter(pixmap: QPixmap, size: int, color: str) -> QPainter:
    """`QPainter` sobre `pixmap` con el trazo proporcional al tamaño lógico.

    `size` es el lógico, no `pixmap.width()`: ese último ya viene
    multiplicado por la densidad de pantalla (ver `_new_pixmap`) y usarlo
    engordaría el trazo a ×2 en un monitor HiDPI.
    """
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(size * 0.09)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    return painter


def _usb_pixmap(size: int, color: str) -> QPixmap:
    """Zócalo rectangular con una clavija encajándose por la derecha."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    puerto = QRectF(size * 0.14, size * 0.32, size * 0.6, size * 0.36)
    painter.drawRoundedRect(puerto, size * 0.05, size * 0.05)
    painter.drawRect(QRectF(size * 0.64, size * 0.4, size * 0.24, size * 0.2))
    painter.drawLine(
        QPointF(size * 0.08, size * 0.5), QPointF(puerto.left(), size * 0.5)
    )

    painter.end()
    return pixmap


def _network_pixmap(size: int, color: str) -> QPixmap:
    """Un nodo central enlazado a otros cuatro, en las cuatro esquinas."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    centro = QPointF(size * 0.5, size * 0.5)
    radio = size * 0.07
    for x, y in ((0.18, 0.22), (0.82, 0.22), (0.18, 0.78), (0.82, 0.78)):
        punto = QPointF(size * x, size * y)
        painter.drawLine(centro, punto)
        painter.setBrush(QColor(color))
        painter.drawEllipse(punto, radio * 0.75, radio * 0.75)
        painter.setBrush(Qt.NoBrush)
    painter.setBrush(QColor(color))
    painter.drawEllipse(centro, radio, radio)

    painter.end()
    return pixmap


def _sensor_pixmap(size: int, color: str) -> QPixmap:
    """`sensors`: un punto emitiendo dos arcos concéntricos hacia arriba."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    origen = QPointF(size * 0.24, size * 0.76)
    painter.setBrush(QColor(color))
    painter.drawEllipse(origen, size * 0.07, size * 0.07)
    painter.setBrush(Qt.NoBrush)
    for radio in (size * 0.28, size * 0.46):
        arco = QRectF(origen.x() - radio, origen.y() - radio, radio * 2, radio * 2)
        painter.drawArc(arco, 20 * 16, 55 * 16)

    painter.end()
    return pixmap


def _speaker_pixmap(size: int, color: str) -> QPixmap:
    """El cono del altavoz, con dos arcos de sonido saliendo por la derecha."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    cono = QPainterPath()
    cono.moveTo(size * 0.16, size * 0.4)
    cono.lineTo(size * 0.34, size * 0.4)
    cono.lineTo(size * 0.54, size * 0.22)
    cono.lineTo(size * 0.54, size * 0.78)
    cono.lineTo(size * 0.34, size * 0.6)
    cono.lineTo(size * 0.16, size * 0.6)
    cono.closeSubpath()
    painter.drawPath(cono)
    for radio in (size * 0.12, size * 0.22):
        arco = QRectF(
            size * 0.54 - radio * 0.2, size * 0.5 - radio, radio * 2, radio * 2
        )
        painter.drawArc(arco, -40 * 16, 80 * 16)

    painter.end()
    return pixmap


def _display_pixmap(size: int, color: str) -> QPixmap:
    """Una pantalla: el marco y su peana."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    pantalla = QRectF(size * 0.12, size * 0.18, size * 0.76, size * 0.5)
    painter.drawRoundedRect(pantalla, size * 0.05, size * 0.05)
    painter.drawLine(
        QPointF(size * 0.5, pantalla.bottom()), QPointF(size * 0.5, size * 0.82)
    )
    painter.drawLine(
        QPointF(size * 0.32, size * 0.82), QPointF(size * 0.68, size * 0.82)
    )

    painter.end()
    return pixmap


def _keyboard_pixmap(size: int, color: str) -> QPixmap:
    """El cuerpo del teclado con dos filas de teclas."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    cuerpo = QRectF(size * 0.1, size * 0.3, size * 0.8, size * 0.44)
    painter.drawRoundedRect(cuerpo, size * 0.05, size * 0.05)
    for fila in (0.42, 0.58):
        for columna in (0.24, 0.4, 0.56, 0.72):
            painter.drawLine(
                QPointF(size * columna, size * fila),
                QPointF(size * (columna + 0.06), size * fila),
            )

    painter.end()
    return pixmap


def _led_pixmap(size: int, color: str) -> QPixmap:
    """Una bombilla: el globo, el filamento y la rosca."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    painter.drawEllipse(QPointF(size * 0.5, size * 0.38), size * 0.24, size * 0.24)
    painter.drawLine(QPointF(size * 0.5, size * 0.5), QPointF(size * 0.5, size * 0.6))
    painter.drawLine(
        QPointF(size * 0.38, size * 0.66), QPointF(size * 0.62, size * 0.66)
    )
    painter.drawLine(
        QPointF(size * 0.42, size * 0.76), QPointF(size * 0.58, size * 0.76)
    )

    painter.end()
    return pixmap


def _bolt_pixmap(size: int, color: str) -> QPixmap:
    """Un rayo: alimentación."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    rayo = QPainterPath()
    rayo.moveTo(size * 0.56, size * 0.12)
    rayo.lineTo(size * 0.28, size * 0.56)
    rayo.lineTo(size * 0.46, size * 0.56)
    rayo.lineTo(size * 0.4, size * 0.88)
    rayo.lineTo(size * 0.72, size * 0.42)
    rayo.lineTo(size * 0.52, size * 0.42)
    rayo.closeSubpath()
    painter.drawPath(rayo)

    painter.end()
    return pixmap


def _pulse_pixmap(size: int, color: str) -> QPixmap:
    """Una onda cuadrada: temporización (relojes, PWM)."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    alta, baja = size * 0.3, size * 0.66
    onda = QPainterPath()
    onda.moveTo(size * 0.08, baja)
    onda.lineTo(size * 0.3, baja)
    onda.lineTo(size * 0.3, alta)
    onda.lineTo(size * 0.5, alta)
    onda.lineTo(size * 0.5, baja)
    onda.lineTo(size * 0.7, baja)
    onda.lineTo(size * 0.7, alta)
    onda.lineTo(size * 0.92, alta)
    painter.drawPath(onda)

    painter.end()
    return pixmap


def _shield_pixmap(size: int, color: str) -> QPixmap:
    """Un escudo: seguridad."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    escudo = QPainterPath()
    escudo.moveTo(size * 0.5, size * 0.12)
    escudo.lineTo(size * 0.82, size * 0.26)
    escudo.lineTo(size * 0.82, size * 0.5)
    escudo.cubicTo(
        QPointF(size * 0.82, size * 0.72),
        QPointF(size * 0.68, size * 0.84),
        QPointF(size * 0.5, size * 0.9),
    )
    escudo.cubicTo(
        QPointF(size * 0.32, size * 0.84),
        QPointF(size * 0.18, size * 0.72),
        QPointF(size * 0.18, size * 0.5),
    )
    escudo.lineTo(size * 0.18, size * 0.26)
    escudo.closeSubpath()
    painter.drawPath(escudo)

    painter.end()
    return pixmap


def _dots_pixmap(size: int, color: str) -> QPixmap:
    """Cuadrícula de cuatro: lo que no encaja en ningún otro grupo."""
    pixmap = _new_pixmap(size)
    painter = _new_painter(pixmap, size, color)

    lado = size * 0.22
    for x, y in ((0.2, 0.2), (0.58, 0.2), (0.2, 0.58), (0.58, 0.58)):
        painter.drawRoundedRect(
            QRectF(size * x, size * y, lado, lado), size * 0.04, size * 0.04
        )

    painter.end()
    return pixmap
