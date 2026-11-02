"""Grabador de fotogramas de la aplicacion para los GIFs de promocion."""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

# La raiz del repositorio, deducida de donde vive este fichero
# (`scripts/demo_gifs/rec.py`), y un sitio fuera de el para lo que se genera:
# los fotogramas son miles de PNG y no tienen por que aparecer en `git status`.
REPO = Path(__file__).resolve().parents[2]
SCRATCH = Path(os.environ.get("KERNELGROVE_GIF_DIR", tempfile.gettempdir()))
SCRATCH = SCRATCH / "kernelgrove-gifs"
CONFIG = SCRATCH / "config"
CONFIG.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["KERNELGROVE_LANG"] = "en"
os.environ["XDG_CONFIG_HOME"] = str(CONFIG)

from PySide6.QtCore import QPoint, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

W, H = 1280, 800
FIXTURE = REPO / "tests" / "fixtures" / "zynqmp.dtsi"


class Rec:
    def __init__(self, name: str, skin="classic", mode="dark"):
        self.app = QApplication.instance() or QApplication([])
        from kernelgrove.gui.main_window import (
            SETTING_SKIN,
            SETTING_THEME,
            MainWindow,
            apply_theme,
        )

        apply_theme(self.app, mode, skin)
        self.win = MainWindow(db_path=REPO / "database/bindings.db", dtsi_folder=REPO)
        self.win._settings.setValue(SETTING_SKIN, skin)
        self.win._settings.setValue(SETTING_THEME, mode)
        self.win.resize(W, H)
        self.win.show()
        self.out = SCRATCH / "frames" / name
        for old in sorted(self.out.glob("*.png")) if self.out.exists() else []:
            old.unlink()
        self.out.mkdir(parents=True, exist_ok=True)
        self.n = 0
        self._cursor = None
        # Encuadre de camara: `None` es la ventana entera, y si no
        # `(cx, cy, factor)` en coordenadas de la ventana. Es un recorte del
        # fotograma ya compuesto, no un cambio en la aplicacion: la ventana
        # sigue midiendo 1280x800 y nada se recoloca al acercarse.
        self._zoom = None
        self._ring = 0
        self.settle(0.6)

    # -- utilidades ---------------------------------------------------
    def settle(self, seconds: float = 0.15):
        end = time.time() + seconds
        while time.time() < end:
            self.app.processEvents()
        self.app.processEvents()

    def shot(self, hold: int = 1, settle: float = 0.05):
        """Un fotograma; `hold` lo repite para que se quede quieto un poco."""
        self.settle(settle)
        image = self.win.grab().toImage()
        # Los menus, dialogos y popups son ventanas aparte: se pegan encima
        # en su sitio para que el fotograma sea lo que ve el usuario.
        painter = QPainter(image)
        for top in self.app.topLevelWidgets():
            if top is self.win or not top.isVisible() or top.isHidden():
                continue
            if not top.isWindow():
                continue
            pos = top.mapToGlobal(QPoint(0, 0)) - self.win.mapToGlobal(QPoint(0, 0))
            painter.drawImage(pos, top.grab().toImage())
        painter.end()
        # El encuadre se aplica **despues** de componer y **antes** de pintar
        # el puntero: escalar el recorte con el cursor dentro lo dejaria
        # gigante y emborronado, que es justo lo que delata un zoom falso.
        image, cursor = self._framed(image)
        if cursor is not None:
            painter = QPainter(image)
            if self._ring:
                self._draw_ring(painter, *cursor, self._ring)
            self._draw_cursor(painter, *cursor)
            painter.end()
        for _ in range(hold):
            self.n += 1
            image.save(str(self.out / f"{self.n:04d}.png"))

    def _framed(self, image):
        """Recorta al encuadre actual; devuelve la imagen y donde cae el puntero."""
        if self._zoom is None or self._zoom[2] <= 1.001:
            return image, self._cursor
        cx, cy, factor = self._zoom
        ancho, alto = W / factor, H / factor
        # Pegado al borde antes que saliendose de el: un recorte fuera de la
        # imagen sale negro por ese lado.
        rx = min(max(cx - ancho / 2, 0.0), W - ancho)
        ry = min(max(cy - alto / 2, 0.0), H - alto)
        recorte = image.copy(QRect(round(rx), round(ry), round(ancho), round(alto)))
        recorte = recorte.scaled(W, H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        if self._cursor is None:
            return recorte, None
        x, y = self._cursor
        return recorte, ((x - rx) * factor, (y - ry) * factor)

    def point(self, widget=None, dx: float = 0.5, dy: float = 0.5):
        """Deja el puntero dibujado sobre ese widget (o lo quita)."""
        if widget is None:
            self._cursor = None
            return
        local = QPoint(int(widget.width() * dx), int(widget.height() * dy))
        origin = widget.mapToGlobal(local) - self.win.mapToGlobal(QPoint(0, 0))
        self._cursor = (origin.x(), origin.y())

    def point_at(self, widget, x: int, y: int):
        """El puntero en unas coordenadas locales de ese widget."""
        origin = widget.mapToGlobal(QPoint(int(x), int(y))) - self.win.mapToGlobal(
            QPoint(0, 0)
        )
        self._cursor = (origin.x(), origin.y())

    def point_item(self, view, item, column: int = 0):
        """El puntero sobre una fila de un QTreeWidget/QListWidget."""
        rect = (
            view.visualItemRect(item)
            if hasattr(view, "visualItemRect")
            else view.visualRect(item)
        )
        local = rect.center()
        if column:
            local.setX(view.header().sectionPosition(column) + 40)
        origin = view.viewport().mapToGlobal(local) - self.win.mapToGlobal(QPoint(0, 0))
        self._cursor = (origin.x(), origin.y())

    @staticmethod
    def _draw_cursor(painter, x, y):
        flecha = QPolygonF(
            [
                QPointF(x, y),
                QPointF(x, y + 17),
                QPointF(x + 4.5, y + 13),
                QPointF(x + 7.5, y + 19.5),
                QPointF(x + 10.5, y + 18),
                QPointF(x + 7.5, y + 11.5),
                QPointF(x + 13, y + 11),
            ]
        )
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(0, 0, 0, 200), 1.5))
        painter.setBrush(QColor(255, 255, 255, 240))
        painter.drawPolygon(flecha)

    def center(self, window):
        """Centra una ventana flotante sobre la principal, para el fotograma."""
        origin = self.win.mapToGlobal(QPoint(0, 0))
        window.move(
            origin.x() + (self.win.width() - window.width()) // 2,
            origin.y() + (self.win.height() - window.height()) // 2,
        )

    def use_folder(self, path):
        """La carpeta que enseña el panel lateral, sin pasar por el dialogo."""
        self.win.explorer_panel.set_root(path)
        self.win.git_panel.set_root(path)
        self.win.overlay_panel.set_library(path, self.win._overlay_base)
        self.win.build_panel.set_folder(path)
        self.win._settings.setValue("project/explorer_root", str(path))

    def open_file(self, path, wait: float = 3.0):
        self.win._open_explorer_file(str(path))
        self.win.editor_tab.analyze()
        self.settle(wait)
        return self.win.editor_tab.current

    def hold(self, frames: int = 8):
        self.shot(hold=frames)

    # -- acciones de guion --------------------------------------------
    def open_fixture(self, analyze=True, wait=2.5):
        self.win.editor_tab.open_source(
            title="zynqmp.dtsi",
            text=FIXTURE.read_text(encoding="utf-8"),
            source_key="xilinx/zynqmp.dtsi",
        )
        if analyze:
            self.win.editor_tab.analyze()
            self.settle(wait)
        return self.win.editor_tab.current

    def goto_line(self, line: int):
        self.win._go_to_line(line)

    def line_of(self, prefix: str) -> int:
        doc = self.win.editor_tab.current
        for i, text in enumerate(doc.editor.toPlainText().splitlines(), start=1):
            if text.strip().startswith(prefix):
                return i
        raise AssertionError(prefix)

    def type_into(self, widget, text: str, hold=1):
        from PySide6.QtTest import QTest

        for char in text:
            if char == "\n":
                QTest.keyClick(widget, Qt.Key_Return)
            elif char == "\t":
                QTest.keyClick(widget, Qt.Key_Tab)
            else:
                QTest.keyClicks(widget, char)
            self.shot(hold)

    def finish(self):
        self.win.stop_background_work()
        self.app.processEvents()
        print("frames:", self.n, "->", self.out)

    # -- puntero con movimiento y camara -------------------------------
    #
    # `point*` coloca el puntero de golpe, que es lo que sirve para una
    # captura suelta. Para un GIF que se mira, no: un cursor que aparece en
    # otro sitio entre dos fotogramas no se sigue con la vista. `move*`
    # recorre el camino dibujando un fotograma por paso, con arranque y
    # frenada suaves (`_ease`), y `zoom*` hace lo mismo con el encuadre.

    @staticmethod
    def _ease(t: float) -> float:
        """Suavizado en S: arranca despacio, corre en medio y frena al llegar."""
        return 4 * t**3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2

    def _win_point(self, widget, x, y):
        """Unas coordenadas locales de un widget, en las de la ventana."""
        origin = widget.mapToGlobal(QPoint(int(x), int(y))) - self.win.mapToGlobal(
            QPoint(0, 0)
        )
        return (origin.x(), origin.y())

    def where(self, widget, dx: float = 0.5, dy: float = 0.5):
        """Donde cae un punto relativo de un widget (0..1), sin mover nada."""
        return self._win_point(widget, widget.width() * dx, widget.height() * dy)

    def where_item(self, view, item, column: int = 0):
        """Donde cae una fila de una vista, sin mover nada."""
        rect = (
            view.visualItemRect(item)
            if hasattr(view, "visualItemRect")
            else view.visualRect(item)
        )
        local = rect.center()
        if column:
            local.setX(view.header().sectionPosition(column) + 40)
        return self._win_point(view.viewport(), local.x(), local.y())

    def move_to(self, target, steps: int = 16, hold: int = 1):
        """Lleva el puntero hasta ahi paso a paso, un fotograma por paso."""
        if self._cursor is None:
            # De abajo y del centro, que es de donde viene una mano que
            # acaba de soltar el raton, y no de una esquina cualquiera.
            self._cursor = (W // 2, H - 30)
        x0, y0 = self._cursor
        x1, y1 = target
        for paso in range(1, steps + 1):
            t = self._ease(paso / steps)
            self._cursor = (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
            self.shot(hold)
        self._cursor = (x1, y1)

    def move(self, widget, dx: float = 0.5, dy: float = 0.5, steps: int = 16, hold=1):
        """Hasta un punto relativo de un widget."""
        self.move_to(self.where(widget, dx, dy), steps, hold)

    def move_at(self, widget, x: int, y: int, steps: int = 16, hold: int = 1):
        """Hasta unas coordenadas locales de un widget."""
        self.move_to(self._win_point(widget, x, y), steps, hold)

    def move_item(self, view, item, steps: int = 16, hold: int = 1, column: int = 0):
        """Hasta una fila de una vista."""
        self.move_to(self.where_item(view, item, column), steps, hold)

    def click(self, frames: int = 2):
        """Un anillo que se abre donde esta el puntero: eso es el clic.

        Sin el, entre el fotograma de antes y el de despues no hay nada que
        diga que se ha pulsado, y el cambio de pantalla parece espontaneo.
        """
        for radio in (7, 13, 20):
            self._ring = radio
            self.shot(frames)
        self._ring = 0
        self.shot(frames)

    @staticmethod
    def _draw_ring(painter, x, y, radio: int):
        """El destello del clic: se abre y se apaga segun crece."""
        painter.setRenderHint(QPainter.Antialiasing, True)
        alpha = max(0, 210 - radio * 8)
        painter.setPen(QPen(QColor(120, 200, 255, alpha), 2.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(x, y), radio, radio)

    def zoom_to(self, target, factor: float = 1.8, steps: int = 14, hold: int = 1):
        """Acerca la camara a ese punto, sin salto: interpola centro y aumento."""
        cx0, cy0, f0 = self._zoom if self._zoom else (W / 2, H / 2, 1.0)
        cx1, cy1 = target
        for paso in range(1, steps + 1):
            t = self._ease(paso / steps)
            self._zoom = (
                cx0 + (cx1 - cx0) * t,
                cy0 + (cy1 - cy0) * t,
                f0 + (factor - f0) * t,
            )
            self.shot(hold)
        self._zoom = (cx1, cy1, factor)

    def zoom_widget(self, widget, factor: float = 1.8, steps: int = 14, hold: int = 1):
        """Lo mismo, encuadrando el centro de un widget."""
        self.zoom_to(self.where(widget), factor, steps, hold)

    def zoom_out(self, steps: int = 14, hold: int = 1):
        """Devuelve la camara a la ventana entera."""
        if self._zoom is None:
            return
        cx, cy, f0 = self._zoom
        for paso in range(1, steps + 1):
            t = self._ease(paso / steps)
            self._zoom = (
                cx + (W / 2 - cx) * t,
                cy + (H / 2 - cy) * t,
                f0 + (1.0 - f0) * t,
            )
            self.shot(hold)
        self._zoom = None
