#!/usr/bin/env python3
"""Genera `packaging/windows/kernelgrove.ico` del símbolo de la marca.

Windows quiere siete tamaños dentro del `.ico` (16…256). Cada uno se
rasteriza por separado desde el SVG, no reduciendo un PNG grande: a 16 px un
brote reescalado se emborrona. El color es el que lleva el fichero, sin
sustituir por el tema — quien lo pinta es la barra de tareas, y de su fondo
no se sabe nada (ver `gui/brand.py`).

Necesita PySide6 y el `convert` de ImageMagick. Se ejecuta a mano cuando
cambia el logotipo, no en el empaquetado: el `.ico` viaja en el repositorio.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

TAMANOS = (16, 24, 32, 48, 64, 128, 256)

RAIZ = Path(__file__).resolve().parent.parent
SVG = RAIZ / "src/kernelgrove/gui/brand/logo-icon.svg"
ICO = RAIZ / "packaging/windows/kernelgrove.ico"


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import QApplication

    QApplication([])
    fuente = SVG.read_bytes()

    with tempfile.TemporaryDirectory() as tmp:
        pngs = []
        for lado in TAMANOS:
            pixmap = QPixmap(lado, lado)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            QSvgRenderer(fuente).render(painter, QRectF(0, 0, lado, lado))
            painter.end()
            destino = Path(tmp) / f"{lado:03d}.png"
            pixmap.save(str(destino))
            pngs.append(str(destino))

        subprocess.run(["convert", *pngs, str(ICO)], check=True)

    print(f"{ICO.relative_to(RAIZ)}: {len(TAMANOS)} tamaños")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
