"""Captura una secuencia de pantallazos de KernelGrove y monta el GIF de demo.

    python scripts/make_demo_gif.py [salida.gif]

Va sin pantalla (`offscreen`), así que los popups —la lista de autocompletado
es una ventana aparte— se pegan a mano sobre la captura de la ventana. Cada
fotograma lleva su duración en el nombre (`-dNN`, centésimas), que es lo que
lee el montaje: así el ritmo se cambia en el sitio donde se decide.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["KERNELGROVE_LANG"] = "en"

ROOT = Path(__file__).resolve().parents[1]
GIF = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "docs" / "kernelgrove-demo.gif")
OUT = Path(tempfile.mkdtemp(prefix="kernelgrove-frames-"))
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QPainter, QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from kernelgrove.gui import theme, translations  # noqa: E402

translations.install_translations(app)

from kernelgrove.gui.main_window import (  # noqa: E402
    TAB_EDITOR,
    TAB_VISUALIZER,
    MainWindow,
)

win = MainWindow(db_path=ROOT / "database" / "bindings.db", dtsi_folder=ROOT)
win._repaint_theme(theme.MODE_DARK, theme.SKIN_OBSIDIAN)
win.resize(1440, 880)
win.show()

_n = 0


def settle(veces=25):
    for _ in range(veces):
        app.processEvents()


def shot(nombre, cs=100):
    """Ventana + cualquier popup visible, pegado en su sitio.

    `cs` es lo que dura el fotograma, en centésimas de segundo.
    """
    global _n
    settle()
    pix = win.grab()
    painter = QPainter(pix)
    for w in app.topLevelWidgets():
        if w is win or not w.isVisible() or w.isHidden():
            continue
        painter.drawPixmap(w.geometry().topLeft() - win.geometry().topLeft(), w.grab())
    painter.end()
    _n += 1
    destino = OUT / f"{_n:03d}-{nombre}-d{cs:03d}.png"
    pix.save(str(destino))


# --- 1. el fichero abierto y analizado -------------------------------------
FIX = ROOT / "tests/fixtures/zynqmp.dtsi"
win.editor_tab.open_source(
    title="zynqmp.dtsi", text=FIX.read_text(), source_key="xilinx/zynqmp.dtsi"
)
win.editor_tab.analyze()
settle(60)
shot("editor", 130)

# --- 2. el cursor dentro de i2c0: el inspector se llena ---------------------
doc = win.editor_tab.current
editor = doc.editor
cursor = editor.textCursor()
cursor.movePosition(QTextCursor.Start)
cursor.movePosition(QTextCursor.Down, QTextCursor.MoveAnchor, 909)
cursor.movePosition(QTextCursor.EndOfLine)
editor.setTextCursor(cursor)
editor.centerCursor()
editor.setFocus()
settle(40)
shot("inspector", 140)

# --- 3. escribir una propiedad nueva, tecla a tecla ------------------------
cursor.insertText("\n\t\t\t")
editor.setTextCursor(cursor)
settle()
for letra in "clo":
    QTest.keyClick(editor, letra)
    settle(15)
    shot("tecleando", 18)
shot("autocompletado", 150)

# --- 4. aceptarla: se inserta con su plantilla de valor --------------------
popup = editor._completer.popup()
if popup.isVisible():
    QTest.keyClick(popup, Qt.Key_Return)
settle(40)
shot("insertado", 150)

# --- 5. otra pestaña: una placa de verdad, con sus includes ----------------
BOARD = ROOT / "kernel/linux/arch/arm64/boot/dts/xilinx/avnet-ultra96-rev1.dts"
win.editor_tab.open_source(
    title=BOARD.name,
    text=BOARD.read_text(),
    source_key=str(BOARD),
    disk_path=BOARD,
)
win.editor_tab.analyze()
settle(80)
shot("placa", 70)

# --- 6. el grafo, desplegándose nodo a nodo --------------------------------
win.show_view(TAB_VISUALIZER)
settle(80)
shot("grafo", 90)

grafo = win.visualizer_tab.graph
raiz = grafo._root
if raiz is not None:
    raiz.collapsed = False
    grafo.redraw()
    grafo.fit()
    settle(40)
    shot("grafo-raiz", 45)
    for hijo in raiz.children:
        if not hijo.children:
            continue
        hijo.collapsed = False
        grafo.redraw()
        settle(30)
        shot("grafo-rama", 45)
    grafo.fit()
    settle(40)
shot("grafo-desplegado", 160)

# --- 7. el catálogo de la base ---------------------------------------------
win.show_view(TAB_EDITOR)
settle()
win.open_database()
db = win.database_tab
db.resize(1000, 640)
db.move(win.geometry().topLeft() + QPoint(220, 120))
settle(60)
shot("catalogo", 170)

win.stop_background_work()

# --- montaje: la duración de cada fotograma va en su nombre ----------------
orden = []
for png in sorted(OUT.glob("*.png")):
    orden += ["-delay", png.stem.rsplit("-d", 1)[1], str(png)]
subprocess.run(
    ["convert", "-loop", "0", *orden, "-resize", "1100x", "-colors", "128",
     "-layers", "Optimize", str(GIF)],
    check=True,
)
shutil.rmtree(OUT)
print(f"{GIF} · {_n} fotogramas · {GIF.stat().st_size // 1024} KB")
