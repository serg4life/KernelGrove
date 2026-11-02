"""Guiones: una escena por funcionalidad. `python scenes.py <escena>`."""
from __future__ import annotations

import sys

from rec import REPO, SCRATCH, Rec

# Los guiones trabajan sobre una **copia** de los device trees del kernel, no
# sobre el checkout: compilar deja `.dtb` junto al fuente y el asistente de
# overlays escribe en la carpeta abierta. Es ademas un repositorio git, que
# es lo que la escena `git` necesita para tener algo que contar.
DTS = SCRATCH / "ws"
KERNEL_DTS = REPO / "kernel/linux/arch/arm64/boot/dts/xilinx"
SOC = DTS / "zynqmp.dtsi"
BOARD = DTS / "avnet-ultra96-rev1.dts"

SCENES = {}
OPTIONS = {}


def scene(**kwargs):
    def wrap(fn):
        SCENES[fn.__name__] = fn
        OPTIONS[fn.__name__] = kwargs
        return fn

    return wrap


def scroll(r, editor, target, step=26, hold=1):
    bar = editor.verticalScrollBar()
    start = bar.value()
    paso = step if target > start else -step
    for value in range(start, target, paso):
        bar.setValue(value)
        r.shot(hold)
    bar.setValue(target)
    r.shot(hold)


def ensure_workspace() -> None:
    """Crea la copia de trabajo la primera vez, con su commit inicial."""
    import shutil
    import subprocess

    if DTS.exists():
        return
    DTS.mkdir(parents=True)
    for source in KERNEL_DTS.iterdir():
        if source.suffix in (".dts", ".dtsi", ".dtso", ".h"):
            shutil.copy2(source, DTS / source.name)
    subprocess.run(["git", "-C", str(DTS), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(DTS), "add", "-A"], check=True)
    subprocess.run(
        [
            "git", "-C", str(DTS),
            "-c", "user.email=demo@kernelgrove",
            "-c", "user.name=demo",
            "commit", "-qm", "board files",
        ],
        check=True,
    )


def start(name, **kwargs):
    ensure_workspace()
    r = Rec(name, **{**OPTIONS.get(name, {}), **kwargs})
    r.use_folder(DTS)
    r.settle(0.4)
    return r


# ---------------------------------------------------------------- 1. editor
@scene()
def editor(r: Rec):
    """Abrir un device tree real y ver los diagnosticos del motor semantico."""
    r.hold(8)                                        # ventana vacia
    doc = r.open_file(SOC)
    r.hold(12)
    scroll(r, doc.editor, 700)
    r.hold(6)

    view = r.win.editor_tab.diagnostics_view
    for i in range(min(4, view.topLevelItemCount())):
        item = view.topLevelItem(i)
        view.setCurrentItem(item)
        r.point_item(view, item)
        r.shot(3)
        r.win.editor_tab._on_diagnostic_activated(item)
        r.shot(10)
    r.point(None)
    r.hold(10)


# ------------------------------------------------------------- 2. inspector
@scene()
def inspector(r: Rec):
    """El Inspector: que dice el binding del nodo donde esta el cursor."""
    r.open_file(SOC)
    r.hold(6)
    for prefijo in ("i2c1: i2c@", "uart0: serial@", "gem3: ethernet@", "can0: can@"):
        try:
            linea = r.line_of(prefijo)
        except AssertionError:
            continue
        r.goto_line(linea + 1)
        r.settle(0.5)
        r.hold(14)

    # Una propiedad de la ficha abre su pagina del binding.
    panel = r.win.inspector_panel
    arbol = panel._properties if hasattr(panel, "_properties") else None
    if arbol is not None and arbol.topLevelItemCount():
        item = arbol.topLevelItem(0)
        r.point_item(arbol, item)
        r.shot(5)
        panel._on_property_clicked(item, 0)
        r.settle(1.0)
        ficha = r.win.property_panel
        ficha.resize(560, 360)
        r.center(ficha)
        r.settle(0.3)
        r.point(None)
        r.hold(18)


# ----------------------------------------------------------------- 3. grafo
@scene()
def graph(r: Rec):
    """El mismo device tree como grafo de nodos, navegable."""
    from kernelgrove.gui.main_window import TAB_VISUALIZER

    r.open_file(BOARD)
    r.hold(4)
    r.win.show_view(TAB_VISUALIZER)
    r.settle(0.8)
    view = r.win.visualizer_tab.graph
    view.fit()
    r.hold(12)

    # Desplegar: la ficha de la placa se abre en el SoC y lo que lleva.
    for vuelta in range(3):
        badge = _first_badge(view)
        if badge is None:
            break
        punto = view.mapFromScene(badge.scenePos())
        r.point_at(view.viewport(), punto.x(), punto.y())
        r.shot(4)
        badge.node.collapsed = False
        view.redraw()
        view.fit()
        r.settle(0.3)
        r.hold(10)
    r.point(None)

    for _ in range(7):
        view.zoom_by(1.15)
        r.shot(2)
    r.hold(8)
    bar = view.horizontalScrollBar()
    destino = min(bar.maximum(), bar.value() + 700)
    while bar.value() < destino:
        bar.setValue(bar.value() + 26)
        r.shot(1)
    r.hold(6)
    view.fit()
    r.hold(12)


def _first_badge(view):
    """La primera insignia «+» que quede en el lienzo, si hay alguna."""
    from kernelgrove.gui.widgets.tree_graph import _ToggleBadge

    for item in view.scene().items():
        if isinstance(item, _ToggleBadge) and item.node.collapsed:
            return item
    return None


# ------------------------------------------------------------- 4. catalogo
@scene()
def catalogue(r: Rec):
    """El catalogo: SoCs, placas y bindings de la base de datos."""
    db = r.win.database_tab
    r.win.open_database()
    r.settle(1.2)
    db.resize(1120, 720)
    r.center(db)
    r.settle(0.3)
    r.hold(10)

    r.point(db.search)
    r.type_into(db.search, "zynqmp", hold=3)
    r.hold(12)
    db.search.clear()
    r.shot(2)

    # Y el otro lado del catalogo: los bindings del kernel, buscables.
    r.point(db._binding_button if hasattr(db, "_binding_button") else db.search)
    db.show_view("bindings")
    r.settle(0.8)
    r.hold(8)
    r.point(db.search)
    r.type_into(db.search, "i2c", hold=3)
    r.settle(0.8)
    r.hold(12)
    r.point(None)


# ---------------------------------------------------------- 5. autocompletado
@scene()
def completion(r: Rec):
    """Autocompletado que sale del binding del nodo, no de una lista fija."""
    from PySide6.QtGui import QTextCursor

    doc = r.open_file(SOC)
    linea = r.line_of("i2c1: i2c@")
    r.goto_line(linea + 3)
    r.settle(0.3)
    editor = doc.editor
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.EndOfLine)
    editor.setTextCursor(cursor)
    editor.setFocus()
    r.hold(10)

    r.type_into(editor, "\n", hold=2)
    r.type_into(editor, "cl", hold=4)
    r.settle(0.5)
    r.hold(16)
    r.type_into(editor, "o", hold=4)
    r.settle(0.5)
    r.hold(16)

    # Elegir de la lista, que es lo que se hace con Intro.
    item = _accept_completion(r, editor, ("clock-name", "clock-names"), hold=4)
    r.settle(0.4)
    r.hold(10)
    if item is not None and item.insert.endswith('"";'):
        r.type_into(editor, 'ref", "pclk', hold=3)
    r.win.editor_tab.analyze()
    r.settle(1.5)
    r.hold(14)


# ------------------------------------------------------------- 6. overlays
@scene()
def overlay(r: Rec):
    """El asistente de overlays: senalar el nodo, elegir que cambia, generarlo."""
    from PySide6.QtCore import Qt

    doc = r.open_file(SOC)
    r.hold(4)
    r.point(r.win.overlay_panel.create_button)
    r.shot(4)
    r.win.overlay_panel.create_button.click()
    r.settle(0.4)
    r.hold(8)

    linea = r.line_of("i2c1: i2c@")
    r.win.editor_tab._on_editor_hover(linea, 5, False)
    r.point_at(doc.editor.viewport(), 250, 40)
    r.settle(0.2)
    r.hold(8)

    nodo = r.win.editor_tab.node_at_line(doc, linea)
    r.win.editor_tab.node_clicked.emit(nodo)
    r.settle(0.6)
    r.point(None)
    r.hold(10)

    # El panel del preview, mas ancho: el .dtso se va escribiendo ahi.
    r.win.resizeDocks([r.win.left_dock], [400], Qt.Horizontal)
    r.settle(0.3)

    for lista, nombres in (
        (r.win.overlay_tab.existing, ("status", "clock-frequency")),
        (r.win.overlay_tab.available, ("clock-names",)),
    ):
        for indice in range(lista.topLevelItemCount()):
            item = lista.topLevelItem(indice)
            if item.text(0) in nombres:
                r.point_item(lista, item)
                r.shot(4)
                item.setCheckState(0, Qt.Checked)
                r.settle(0.4)
                r.hold(10)
    r.point(None)
    r.hold(8)

    # Y el fichero: se escribe en la carpeta abierta y aparece en el panel.
    r.point(r.win.overlay_panel.generate_button)
    r.shot(5)
    r.win.overlay_panel.generate_button.click()
    r.settle(1.0)
    r.point(None)
    r.hold(10)
    r.win.activity_bar.show_section(0)
    r.settle(0.8)
    r.hold(14)


# --------------------------------------------------------------- 7. compilar
@scene()
def build(r: Rec):
    """Comprobar y compilar: los overlays se validan antes de llamar a dtc."""
    from kernelgrove.gui.main_window import SECTION_BUILD

    from PySide6.QtCore import Qt
    from kernelgrove.gui.main_window import SECTION_OVERLAY

    r.open_file(BOARD)
    r.win.resizeDocks([r.win.left_dock], [420], Qt.Horizontal)
    r.settle(0.3)
    r.hold(4)

    # Primero los overlays: cuales entran en la compilacion.
    r.win.activity_bar.show_section(SECTION_OVERLAY)
    r.settle(1.0)
    r.hold(10)
    tabla = r.win.overlay_panel.overlay_list.table
    for indice in range(tabla.topLevelItemCount()):
        item = tabla.topLevelItem(indice)
        if "layer" in item.text(1) or indice == 0:
            r.point_item(tabla, item)
            r.shot(4)
            item.setCheckState(0, Qt.Checked)
            r.settle(0.6)
            r.hold(10)
            break
    r.point(None)

    # Y despues compilar: se comprueba contra la base y solo entonces dtc.
    r.win.activity_bar.show_section(SECTION_BUILD)
    r.settle(0.8)
    r.hold(10)
    panel = r.win.build_panel
    panel._select_key(str(BOARD))
    r.settle(0.3)
    r.point(panel.build_button)
    r.hold(8)
    r.win._build_device_tree()
    r.settle(1.2)
    r.point(None)
    r.hold(18)


# ------------------------------------------------------- 8. conectar un chip
@scene()
def connect(r: Rec):
    """Colgar un chip de un bus: el catalogo solo ofrece lo que encaja."""
    from PySide6.QtCore import Qt

    from kernelgrove.gui.main_window import TAB_VISUALIZER

    r.open_file(BOARD)
    r.win.show_view(TAB_VISUALIZER)
    r.settle(1.5)
    r.win.resizeDocks([r.win.left_dock], [230], Qt.Horizontal)
    view = r.win.visualizer_tab.graph
    for _ in range(3):
        badge = _first_badge(view)
        if badge is None:
            break
        badge.node.collapsed = False
        view.redraw()
    view.fit()
    r.settle(0.5)
    r.hold(8)

    compatibles = r.win.visualizer_tab._compatibles_by_bus.get("i2c", ())
    elegido = next(
        (
            c
            for clave in ("24c02", "eeprom", "ina226", "lm75", "rtc")
            for c in compatibles
            if clave in c
        ),
        next(iter(compatibles), None),
    )
    busqueda = elegido.split(",")[-1] if elegido else "i2c"

    palette = r.win.visualizer_tab.palette
    r.point(palette.filter_edit)
    r.type_into(palette.filter_edit, busqueda, hold=3)
    r.settle(0.6)
    view.fit()
    r.hold(14)

    # El bus se coge **del grafo**: lo que esta dibujado es lo que esta
    # encendido en esta placa, y es donde se puede soltar algo.
    hueco, chip = _bus_in_graph(view, "i2c")
    if elegido and hueco is not None:
        punto = view.mapFromScene(chip.sceneBoundingRect().center())
        r.point_at(view.viewport(), punto.x(), punto.y())
        r.shot(6)
        nuevo = r.win.tree_model.connect_to_slot(hueco, elegido)
        r.settle(0.8)
        view.fit()
        r.hold(10)

        # Acercarse a lo recien conectado, que es lo que hay que ver.
        item = _item_of_slot(view, nuevo)
        if item is not None:
            for _ in range(6):
                view.zoom_by(1.18)
                view.centerOn(item)
                r.shot(2)
            r.hold(18)
    r.point(None)
    r.hold(8)


def _bus_in_graph(view, bus):
    """Primer bloque del SoC dibujado que acepta dispositivos de ese bus.

    Los bloques de la ficha central son los controladores del SoC, que es
    donde la sesion de conexion sabe colgar lo que se suelta.
    """
    from kernelgrove.gui.widgets.tree_graph import _BlockChip

    for item in sorted(view.scene().items(), key=lambda i: i.sceneBoundingRect().x()):
        if not isinstance(item, _BlockChip):
            continue
        slot = getattr(item.node, "slot", None)
        if slot is not None and slot.child_bus == bus:
            return slot, item
    return None, None


def _item_of_slot(view, slot):
    """La ficha del grafo que representa ese slot recien conectado."""
    from kernelgrove.gui.widgets.tree_graph import _NodeItem

    for item in view.scene().items():
        if isinstance(item, _NodeItem) and item.node.connected_slot is slot:
            return item
    return None


def _all_slots(slots):
    for slot in slots:
        yield slot
        yield from _all_slots(slot.children)


# ------------------------------------------------------------------- 9. git
@scene()
def git(r: Rec):
    """Control de versiones de la carpeta abierta, dentro del editor."""
    import subprocess

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QTextCursor

    from kernelgrove.gui.main_window import SECTION_VERSIONS

    # La carpeta, limpia: lo unico que tiene que contar el panel es el
    # cambio que se hace en el guion.
    for basura in list(DTS.glob("*.dtb")) + list(DTS.glob("*.dtbo")):
        basura.unlink()
    subprocess.run(["git", "-C", str(DTS), "checkout", "--", "."], check=False)
    subprocess.run(["git", "-C", str(DTS), "clean", "-qfd"], check=False)

    doc = r.open_file(BOARD)
    r.win.resizeDocks([r.win.left_dock], [330], Qt.Horizontal)
    r.hold(4)

    # Un cambio de verdad, para que el margen y el panel tengan que hablar.
    cursor = doc.editor.textCursor()
    cursor.movePosition(QTextCursor.End)
    doc.editor.setTextCursor(cursor)
    doc.editor.setFocus()
    r.type_into(doc.editor, "\n&uart0 {\n\tstatus = \"okay\";\n};\n", hold=2)
    r.win.editor_tab.save_file()
    r.win.editor_tab.analyze()
    r.settle(1.5)
    r.hold(10)

    r.win.activity_bar.show_section(SECTION_VERSIONS)
    r.settle(0.8)
    r.hold(14)


# --------------------------------------------------------------- 10. pieles
@scene()
def themes(r: Rec):
    """Cinco pieles, dos modos y el idioma, en caliente."""
    from kernelgrove.gui import theme

    r.open_file(SOC)
    r.hold(10)
    for skin in (
        theme.SKIN_SITE,
        theme.SKIN_OBSIDIAN,
        theme.SKIN_COLORBLIND,
        theme.SKIN_CONTRAST,
        theme.SKIN_CLASSIC,
    ):
        r.win._set_skin(skin)
        r.settle(0.5)
        r.hold(12)
        # La clasica solo tiene oscuro; las demas se ven en los dos modos.
        if len(theme.modes_of(skin)) > 1:
            r.win._set_theme(theme.MODE_LIGHT)
            r.settle(0.5)
            r.hold(12)
            r.win._set_theme(theme.MODE_DARK)
            r.settle(0.4)
            r.hold(6)

    # Y el idioma, tambien en caliente.
    r.win._set_language("es")
    r.settle(0.8)
    r.hold(16)
    r.win._set_language("en")
    r.settle(0.8)
    r.hold(10)


# ------------------------------------------- 11. recorrido: abrir, ficha, teclear
def _accept_completion(r: Rec, editor, preferidas, hold: int = 6):
    """Baja por la lista hasta una de esas propiedades y la acepta con Intro.

    Con las teclas y no llamando a `_insert_completion(nombre)`: ese metodo
    indexa por **etiqueta**, que es el nombre mas las marcas que le pone el
    editor («clock-name    string-array»), asi que con el nombre a secas no
    encuentra nada y se traga la insercion sin decir nada -el GIF salia con
    el prefijo a medio escribir y sin completar-. Las teclas van al popup,
    que es quien las escucha: el editor las ignora a proposito para
    dejarselas (ver `DtsEditor.keyPressEvent`).

    `preferidas` es una lista y no un nombre porque lo que se ofrece sale de
    la base de datos: si ninguna esta, se acepta la primera de la lista en
    vez de no completar nada. Devuelve el `CompletionItem` aceptado, que es
    lo que dice que plantilla de valor ha quedado escrita.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    popup = editor._completer.popup()
    if not popup.isVisible():
        return None
    modelo = editor._completer.completionModel()
    filas = []
    for indice in range(modelo.rowCount()):
        etiqueta = modelo.index(indice, 0).data()
        filas.append((indice, editor._completion_items.get(etiqueta)))
    if not filas:
        return None
    elegida = next(
        (
            (indice, item)
            for nombre in preferidas
            for indice, item in filas
            if item is not None and item.key == nombre
        ),
        filas[0],
    )
    destino, item = elegida
    for _ in range(destino - popup.currentIndex().row()):
        QTest.keyClick(popup, Qt.Key_Down)
        r.shot(hold)
    r.shot(hold)
    QTest.keyClick(popup, Qt.Key_Return)
    return item


def _warning_of(vista, trozo: str):
    """La fila de diagnosticos cuyo mensaje nombra `trozo`.

    Si no hay ninguna -la base cambia con cada kernel-, la primera fila: el
    guion sigue contando lo mismo con otro nodo.
    """
    filas = [vista.topLevelItem(i) for i in range(vista.topLevelItemCount())]
    propias = [f for f in filas if trozo in f.text(2)]
    return (propias or filas or [None])[0]


def _first_entry(db):
    """La primera ficha que el filtro del catalogo deja a la vista."""
    for row in range(db.entries.count()):
        item = db.entries.item(row)
        if not item.isHidden():
            return item
    return None


def _line_point(editor, linea: int):
    """Donde cae una linea del editor, en coordenadas de su viewport.

    Con la linea ya a la vista: `cursorRect` de un bloque que esta fuera de
    la ventana devuelve una posicion que no sirve para poner el puntero.
    """
    from PySide6.QtGui import QTextCursor

    cursor = QTextCursor(editor.document().findBlockByNumber(linea - 1))
    rect = editor.cursorRect(cursor)
    return rect.x() + 170, rect.y() + rect.height() // 2


@scene()
def tour(r: Rec):
    """El recorrido largo: de la base al warning, al Inspector, a teclear, al grafo.

    Es la demo que se mira entera, no la de una funcionalidad: por eso el
    puntero recorre el camino en vez de saltar (`move*`) y la camara se
    acerca a lo que hay que leer (`zoom*`), que en una ventana de 1280
    reducida a 960 no se lee de otra forma. El orden cuenta una sola
    historia sobre un solo nodo de una placa real: el motor avisa de que la
    unit-address de `ethernet-phy@21` no casa con su `reg` (21 decimal es
    0x15, un fallo del propio kernel), el Inspector dice que binding le
    aplica y el autocompletado ofrece solo lo que el nodo aun no tiene.

    Una placa y no el SoC: en el `.dtsi` todo esta `disabled` y el grafo,
    que solo dibuja lo encendido, saldria con una ficha.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QTextCursor
    from PySide6.QtTest import QTest

    from kernelgrove.gui.main_window import SECTION_DATABASE, TAB_VISUALIZER

    r.hold(10)

    # --- 1. De la base de datos: el catalogo, buscar y abrir una placa.
    boton = r.win.activity_bar._group.button(SECTION_DATABASE)
    r.move(boton, steps=20)
    r.click()
    r.win.open_database()
    r.settle(1.2)
    db = r.win.database_tab
    db.resize(1120, 700)
    r.center(db)
    r.settle(0.4)
    r.hold(12)

    r.move(db.search, steps=18)
    r.click()
    r.type_into(db.search, "zcu102", hold=4)
    r.settle(0.8)
    r.hold(12)

    ficha = _first_entry(db)
    r.move_item(db.entries, ficha, steps=18)
    r.shot(3)
    punto = r.where_item(db.entries, ficha)
    r.zoom_to((punto[0] - 190, punto[1]), factor=1.5, steps=14)
    r.hold(14)
    r.click()
    db._on_entry_activated(ficha)
    r.settle(1.5)
    db.hide()
    r.win.editor_tab.analyze()
    r.settle(3.0)
    r.zoom_out(steps=14)
    r.hold(16)
    doc = r.win.editor_tab.current
    editor = doc.editor

    # --- 2. Un warning del motor semantico, y pulsarlo lleva a su linea.
    vista = r.win.editor_tab.diagnostics_view
    item = _warning_of(vista, "ethernet-phy@21")
    vista.scrollToItem(item)
    r.settle(0.3)
    r.move_item(vista, item, steps=20)
    r.shot(3)
    punto = r.where_item(vista, item)
    r.zoom_to((punto[0] - 80, punto[1] - 60), factor=1.7, steps=14)
    r.hold(22)
    r.click()
    vista.setCurrentItem(item)
    r.win.editor_tab._on_diagnostic_activated(item)
    r.settle(0.6)
    r.zoom_out(steps=12)
    r.hold(12)
    linea = int(item.text(1))

    # --- 3. El Inspector de ese nodo: que pide su binding.
    x, y = _line_point(editor, linea)
    r.move_at(editor.viewport(), x, y, steps=16)
    r.hold(6)
    r.move(r.win.inspector_panel, dy=0.3, steps=20)
    r.zoom_widget(r.win.inspector_panel, factor=1.7, steps=14)
    r.hold(30)
    r.zoom_out(steps=12)

    # --- 4. Anadir la propiedad que falta: el autocompletado solo ofrece
    # lo que el binding admite y el nodo aun no tiene.
    texto = editor.toPlainText().splitlines()
    cierre = next(
        i for i in range(linea, len(texto)) if texto[i].strip() == "};"
    )  # indice 0 de la linea `};` = numero de la linea anterior
    r.goto_line(cierre)
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.EndOfLine)
    editor.setTextCursor(cursor)
    editor.setFocus()
    caja = editor.cursorRect()
    r.move_at(editor.viewport(), caja.x() + 10, caja.y() + caja.height() // 2, steps=20)
    r.click()
    r.hold(8)

    # Intro no sangra la linea nueva: se copia la sangria de la anterior.
    anterior = texto[cierre - 1]
    sangria = anterior[: len(anterior) - len(anterior.lstrip())]
    r.type_into(editor, "\n" + sangria, hold=3)
    r.type_into(editor, "eee", hold=5)
    r.settle(0.5)
    r.hold(8)
    popup = editor._completer.popup()
    if popup.isVisible():
        punto = r.where(popup)
        r.zoom_to((punto[0] + 130, punto[1]), factor=1.95, steps=14)
    r.hold(22)

    _accept_completion(r, editor, ("eee-broken-1000t",))
    r.settle(0.4)
    r.hold(14)
    if editor._completer.popup().isVisible():
        QTest.keyClick(editor, Qt.Key_Escape)
        r.settle(0.3)
    r.zoom_out(steps=12)
    r.win.editor_tab.analyze()
    r.settle(2.0)
    r.hold(14)
    r.goto_line(linea + 1)
    r.settle(0.8)
    r.hold(18)

    # --- 5. El mismo documento, como grafo: lo cambia el pie del panel.
    pie = r.win.explorer_panel.footer.button
    r.move(pie, steps=22)
    r.click()
    r.win.show_view(TAB_VISUALIZER)
    r.settle(1.2)
    view = r.win.visualizer_tab.graph
    view.fit()
    r.settle(0.3)
    r.hold(14)
    for _ in range(3):
        badge = _first_badge(view)
        if badge is None:
            break
        p = view.mapFromScene(badge.scenePos())
        r.move_at(view.viewport(), p.x(), p.y(), steps=16)
        r.click()
        badge.node.collapsed = False
        view.redraw()
        view.fit()
        r.settle(0.3)
        r.hold(12)
    # Sin `fit()` al final: devolveria el grafo al tamano de sello.
    r.point(None)
    for _ in range(12):
        view.zoom_by(1.12)
        r.shot(2)
    r.hold(30)


if __name__ == "__main__":
    name = sys.argv[1]
    r = start(name)
    SCENES[name](r)
    r.finish()
