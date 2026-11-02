"""Humo de la interfaz: montar la ventana y abrir un device tree de verdad.

No pretende cubrir la GUI, sino que exista una red mínima donde antes no
había ninguna: la ventana se construye, un fichero se abre y se analiza, los
paneles laterales lo siguen y cerrarlo deja la sesión limpia. Se apoya en
`QT_QPA_PLATFORM=offscreen` (sin pantalla).

Necesita `database/bindings.db`, que no se versiona; sin ella se salta.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DB_PATH = Path(__file__).resolve().parents[1] / "database" / "bindings.db"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "zynqmp.dtsi"

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(), reason="hace falta database/bindings.db"
)

pytest.importorskip("PySide6", reason="la GUI necesita PySide6")

from kernelgrove.gui import style  # noqa: E402 - necesita PySide6 importable


@pytest.fixture(scope="module")
def app():
    """Un único `QApplication` para todo el módulo: Qt no admite dos."""
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def _filas(lista):
    """Los textos de una `QListWidget`, en orden."""
    return [lista.item(i).text() for i in range(lista.count())]


def _todos_los_nodos(root):
    """Recorre el árbol entero, de arriba abajo."""
    yield root
    for hijo in root.children:
        yield from _todos_los_nodos(hijo)


def _primer_nodo_con_label(root):
    """Primer nodo del árbol que puede ser objetivo de un overlay."""
    pila = [root]
    while pila:
        node = pila.pop(0)
        if node.label:
            return node
        pila.extend(node.children)
    raise AssertionError("el árbol no tiene ningún nodo con label")


@pytest.fixture
def window(app):
    """Ventana principal montada sobre la base real, cerrada al terminar."""
    from kernelgrove.gui.main_window import MainWindow

    win = MainWindow(db_path=DB_PATH, dtsi_folder=Path.cwd())
    yield win
    win.stop_background_work()
    win.deleteLater()


def test_la_ventana_arranca_vacia_pero_con_instrucciones(window):
    """Sin ningún fichero abierto se ve qué hacer, no un hueco en blanco.

    Y una de las tres formas de empezar es un botón: el catálogo es la
    única que no está ni en un menú ni en un panel a la vista.
    """
    from kernelgrove.gui.main_window import TAB_EDITOR

    assert window.editor_tab.current is None
    assert window.editor_tab._stack.currentWidget() is window.editor_tab._empty_page
    assert window.document_bar.count() == 0

    # El botón abre el catálogo **en su ventana**, sin llevarse el centro
    # ni la sección: se busca una placa mientras se sigue en lo de uno.
    previa = window._current_section
    assert window.editor_tab._empty_button.text()
    window.editor_tab._empty_button.click()
    assert not window.database_tab.isHidden()
    assert window.database_tab.isWindow()
    assert window._current_section == previa
    assert window.tabs.currentIndex() == TAB_EDITOR
    window.database_tab.hide()


def test_abrir_un_soc_lo_analiza_y_llena_los_paneles(window):
    """Abrir un `.dtsi` real deja editor, barra de ficheros y estructura al día."""
    window.editor_tab.open_source(
        title="zynqmp.dtsi",
        text=FIXTURE.read_text(encoding="utf-8"),
        source_key="xilinx/zynqmp.dtsi",
    )
    window.editor_tab.analyze()

    document = window.editor_tab.current
    assert document is not None
    assert document.parse_result is not None
    assert window.document_bar.count() == 1


def test_cerrar_el_ultimo_fichero_vacia_la_sesion(window):
    """Al cerrarlo todo, los paneles no pueden quedarse con lo anterior."""
    window.editor_tab.open_source(
        title="zynqmp.dtsi",
        text=FIXTURE.read_text(encoding="utf-8"),
        source_key="xilinx/zynqmp.dtsi",
    )
    window.editor_tab.analyze()
    window.close_current_document()

    assert window.document_bar.count() == 0
    assert window.editor_tab.current is None
    assert window.inspector_panel._node is None


def test_cambiar_de_idioma_repinta_la_ventana_sin_reiniciar(window, app):
    """Elegir otro idioma tiene que cambiar **todo** lo visible, al momento.

    Es la parte que se degrada en silencio: basta con que a un widget nuevo
    se le olvide `Retranslates` para que se quede en el idioma anterior y no
    lo note nadie hasta que un usuario lo vea. Se recorren aquí los textos de
    cada zona de la ventana, incluidos los que no llegan por
    `LanguageChange` —los menús y el modelo del árbol, que no son widgets—.
    """
    from PySide6.QtCore import QSettings, Qt

    from kernelgrove.gui.main_window import (
        SETTING_LANGUAGE,
        SETTINGS_APP,
        SETTINGS_ORG,
    )

    window.editor_tab.open_source(
        title="zynqmp.dtsi",
        text=FIXTURE.read_text(encoding="utf-8"),
        source_key="xilinx/zynqmp.dtsi",
    )
    window.editor_tab.analyze()

    from PySide6.QtWidgets import QToolButton

    def textos():
        editor = window.editor_tab
        return {
            "menús": [action.text() for action in window.menu_bar.actions()],
            # Las vistas ya no se eligen en una fila de pestañas sino en la
            # franja de iconos: lo que hay que traducir son sus tooltips.
            "vistas": [
                button.toolTip()
                for button in window.activity_bar.findChildren(QToolButton)
            ],
            "panel": window._left_header.text(),
            "inspector": window.inspector_panel._title.text(),
            "abrir": window.editor_tab._empty_hint.text(),
            "analizar": window.analyze_button.text(),
            "columnas": [
                editor.diagnostics_view.headerItem().text(i) for i in range(1, 4)
            ],
            "filtros": [c.text() for c in editor.severity_checks.values()],
            "grafo": window.visualizer_tab.canvas_controls._buttons[0].toolTip(),
            "paleta": window.visualizer_tab.palette.filter_edit.placeholderText(),
            "generador": [
                window.generator_tab._output_tabs.tabText(i) for i in range(3)
            ],
            "modelo": [
                window.tree_model.headerData(i, Qt.Horizontal, Qt.DisplayRole)
                for i in range(4)
            ],
        }

    # El idioma se guarda en los ajustes del usuario, así que se restaura al
    # terminar: una prueba no puede dejarle la aplicación en otro idioma.
    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    previo = settings.value(SETTING_LANGUAGE)
    try:
        window._set_language("en")
        app.processEvents()
        ingles = textos()

        window._set_language("es")
        app.processEvents()
        espanol = textos()

        window._set_language("en")
        app.processEvents()
        de_vuelta = textos()
    finally:
        settings.setValue(SETTING_LANGUAGE, previo or "")
        settings.sync()

    # Cada zona tiene que haber cambiado, y volver a ser la de antes. Solo
    # se comparan las que de verdad se traducen distinto: «SoCs:» o «Bus»
    # se escriben igual en los dos idiomas y no dirían nada.
    for zona, valor in ingles.items():
        assert espanol[zona] != valor, f"«{zona}» no cambió de idioma: {valor!r}"
        assert de_vuelta[zona] == valor, f"«{zona}» no volvió al inglés"

    assert espanol["analizar"] == "Analizar"
    assert espanol["modelo"][0] == "Nodo"


def test_ningun_atajo_de_teclado_esta_duplicado(window):
    """Dos atajos iguales en la misma ventana desactivan **los dos**.

    Qt lo resuelve como "Ambiguous shortcut overload" y no dispara ninguno:
    no hay excepción, no hay traza, la tecla simplemente deja de hacer nada.
    Pasó de verdad con Ctrl+F —la acción de menú «Buscar…» y el `QShortcut`
    del propio editor— y la búsqueda estuvo muerta sin que nada lo dijera.
    """
    from collections import Counter

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAction, QShortcut

    window.editor_tab.open_source(
        title="zynqmp.dtsi",
        text=FIXTURE.read_text(encoding="utf-8"),
        source_key="xilinx/zynqmp.dtsi",
    )

    # Solo los de ventana: dos atajos acotados cada uno a su widget con la
    # misma tecla no se estorban, y es lo que permite que Supr borre en el
    # panel de carpetas y desconecte en el generador sin anularse.
    de_ventana = (Qt.WindowShortcut, Qt.ApplicationShortcut)
    registro = Counter()
    for accion in window.findChildren(QAction):
        if accion.shortcutContext() not in de_ventana:
            continue
        for secuencia in accion.shortcuts():
            registro[secuencia.toString()] += 1
    for atajo in window.findChildren(QShortcut):
        if atajo.context() in de_ventana and atajo.key().toString():
            registro[atajo.key().toString()] += 1

    duplicados = {tecla: n for tecla, n in registro.items() if n > 1}
    assert duplicados == {}, f"atajos registrados más de una vez: {duplicados}"


def test_ctrl_f_abre_la_busqueda_del_editor_con_el_foco(window, app):
    """La búsqueda se abre donde está el cursor, no siempre en el Editor.

    El «DTS completo» del Generador es otro `DtsEditor`, y buscar ahí no
    puede llevarte a otra pestaña.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    window.show()
    window.editor_tab.open_source(
        title="zynqmp.dtsi",
        text=FIXTURE.read_text(encoding="utf-8"),
        source_key="xilinx/zynqmp.dtsi",
    )
    window.editor_tab.analyze()
    app.processEvents()

    editor = window.editor_tab.current.editor
    editor.setFocus(Qt.OtherFocusReason)
    app.processEvents()
    QTest.keyClick(editor, Qt.Key_F, Qt.ControlModifier)
    app.processEvents()
    assert editor._find_bar.isVisible()

    # El otro editor: el "DTS completo" del Generador.
    window.tabs.setCurrentIndex(2)
    window.generator_tab._output_tabs.setCurrentIndex(1)
    app.processEvents()
    salida = window.generator_tab.fragment_view
    salida.setFocus(Qt.OtherFocusReason)
    app.processEvents()

    window.find_in_document()
    app.processEvents()
    assert salida._find_bar.isVisible()
    assert window.tabs.currentIndex() == 2, "no debe saltar al Editor"


def test_el_arbol_fusionado_no_se_construye_dos_veces(window):
    """El visualizador reaprovecha el árbol que ya fusionó el análisis."""
    service = window.service
    result, _ = service.analyze_source(
        FIXTURE.read_text(encoding="utf-8"),
        fragment=True,
        base_path="xilinx/zynqmp.dtsi",
    )
    first, _ = service.build_visual_tree(result, "xilinx/zynqmp.dtsi")
    second, _ = service.build_visual_tree(result, "xilinx/zynqmp.dtsi")

    assert first is second


def _abrir_zynqmp(window):
    """Abre el SoC de prueba ya analizado, que es de donde se elige el nodo."""
    window.editor_tab.open_source(
        title="zynqmp.dtsi",
        text=FIXTURE.read_text(encoding="utf-8"),
        source_key="xilinx/zynqmp.dtsi",
    )
    window.editor_tab.analyze()
    return window.editor_tab.current


def _linea_de(document, prefijo: str) -> int:
    """Primera línea del documento cuyo texto empieza por `prefijo`."""
    for numero, texto in enumerate(
        document.editor.toPlainText().splitlines(), start=1
    ):
        if texto.strip().startswith(prefijo):
            return numero
    raise AssertionError(f"no hay ninguna línea que empiece por {prefijo!r}")


def test_al_elegir_objetivo_el_nodo_bajo_el_raton_se_resalta(window):
    """La pista tiene que decir qué se va a elegir antes de pulsar, no después."""
    from PySide6.QtCore import Qt

    document = _abrir_zynqmp(window)
    window.overlay_panel.create_button.click()
    linea = _linea_de(document, "i2c0: i2c@")

    window.editor_tab._on_editor_hover(linea, 5, False)

    inicio, fin = document.editor._node_hint
    assert inicio == linea and fin > linea, "se marca el nodo entero"
    assert (
        document.editor.viewport().cursor().shape() == Qt.PointingHandCursor
    ), "y se nota que se puede pulsar"

    # Fuera de todo nodo (la cabecera de licencia) no hay nada que elegir.
    window.editor_tab._on_editor_hover(2, 5, False)

    assert document.editor._node_hint is None


def test_fuera_del_modo_de_eleccion_el_raton_no_marca_nada(window):
    """Pasar el ratón por el editor es leerlo, no estar eligiendo un objetivo."""
    document = _abrir_zynqmp(window)

    window.editor_tab._on_editor_hover(_linea_de(document, "i2c0: i2c@"), 5, False)

    assert document.editor._node_hint is None


def test_generar_deja_el_fichero_en_la_carpeta_abierta(window, tmp_path):
    """Sin diálogo y sin abrirlo: para verlo ya estaba el preview."""
    from PySide6.QtCore import Qt

    document = _abrir_zynqmp(window)
    window.explorer_panel.set_root(tmp_path)
    window.overlay_panel.create_button.click()
    nodo = window.editor_tab.node_at_line(
        document, _linea_de(document, "i2c0: i2c@")
    )
    window.editor_tab.node_clicked.emit(nodo)

    lista = window.overlay_tab.available
    for indice in range(lista.topLevelItemCount()):
        if lista.topLevelItem(indice).text(0) == "label":
            lista.topLevelItem(indice).setCheckState(0, Qt.Checked)
    window.overlay_panel.generate_button.click()

    escrito = tmp_path / "i2c0_layer.dtso"
    assert escrito.exists(), sorted(p.name for p in tmp_path.iterdir())
    assert "&i2c0 {" in escrito.read_text(encoding="utf-8")
    # No se abre en el editor: sigue habiendo un solo documento, el SoC.
    assert [titulo for titulo, _t, _d in window.editor_tab.document_labels()] == [
        "zynqmp.dtsi"
    ]


def test_el_overlay_generado_lleva_su_nodo_en_el_nombre(window, tmp_path):
    """Con `overlay-1`, `overlay-2`… hay que abrirlos todos para saber cuál es cuál."""
    window.explorer_panel.set_root(tmp_path)

    assert window._next_overlay_name(tmp_path, "i2c0") == "i2c0_layer.dtso"
    # Un nodo apuntado por ruta trae `@` y, si viene de `&{/a/b}`, barras.
    assert (
        window._next_overlay_name(tmp_path, "i2c@ff020000")
        == "i2c_ff020000_layer.dtso"
    )

    # Y el segundo del mismo nodo no pisa al primero: se busca en el disco.
    (tmp_path / "i2c0_layer.dtso").write_text("// ya existía\n", encoding="utf-8")
    assert window._next_overlay_name(tmp_path, "i2c0") == "i2c0_layer-2.dtso"


def test_un_overlay_abierto_del_disco_llega_con_su_base(window, tmp_path):
    """La base hace falta para el árbol fusionado y el autocompletado.

    Lo que **no** hace es soltar veredictos de capa 6 en el editor: eso se
    pide desde el asistente, que sabe contra qué base compara y lo dice.
    """
    _abrir_zynqmp(window)
    overlay = tmp_path / "ajeno.dtso"
    overlay.write_text(
        '/dts-v1/;\n/plugin/;\n\n&no_existe {\n\tstatus = "okay";\n};\n',
        encoding="utf-8",
    )

    window._open_explorer_file(str(overlay))
    window.editor_tab.analyze()

    document = window.editor_tab.current
    assert document.title == "ajeno.dtso"
    assert document.is_overlay, "tiene que traer la base cargada"
    assert not any(
        d.code.value.startswith("overlay-") for d in document.diagnostics
    ), "la capa 6 es del asistente, no del editor"


def test_un_device_tree_normal_no_se_abre_como_overlay(window, tmp_path):
    """Un `.dts` sin `/plugin/` es un árbol completo, no un fragmento."""
    _abrir_zynqmp(window)
    normal = tmp_path / "placa.dts"
    normal.write_text("/dts-v1/;\n\n/ {\n\tmodel = \"x\";\n};\n", encoding="utf-8")

    window._open_explorer_file(str(normal))

    assert not window.editor_tab.current.is_overlay


def test_la_base_se_elige_entre_la_carpeta_y_el_catalogo(window, tmp_path):
    """Un overlay no dice a qué árbol pertenece: elegirlo es la única fuente.

    Y hay que poder elegir tanto un fichero que se tiene delante como una
    entrada de la base de datos, que es lo que hace que esto valga para un
    `.dtso` ajeno del que no se sabe nada.
    """
    from kernelgrove.gui.main_window import BaseChoiceDialog

    _abrir_zynqmp(window)
    window.explorer_panel.set_root(tmp_path)
    (tmp_path / "placa.dts").write_text("/dts-v1/;\n", encoding="utf-8")
    (tmp_path / "soc.dtsi").write_text("/dts-v1/;\n", encoding="utf-8")

    candidatos = window._base_candidates()
    claves = [clave for clave, _etiqueta in candidatos]
    assert str(tmp_path / "placa.dts") in claves
    assert str(tmp_path / "soc.dtsi") in claves
    assert "xilinx/zynqmp.dtsi" in claves, "el catálogo también se ofrece"

    dialogo = BaseChoiceDialog("overlay-1.dtso", candidatos, window)
    dialogo._combo.setCurrentIndex(claves.index(str(tmp_path / "soc.dtsi")))
    assert dialogo._combo.currentData() == str(tmp_path / "soc.dtsi")
    dialogo.deleteLater()



def test_el_panel_de_carpetas_crea_y_borra(app, tmp_path, monkeypatch):
    """Un proyecto se organiza en carpetas.

    Salir a un explorador del sistema para hacer una carpeta o tirar un
    `.dtso` de prueba partía el trabajo en dos.
    """
    from PySide6.QtWidgets import QInputDialog, QMessageBox
    from kernelgrove.gui.widgets.file_explorer import FileExplorerPanel

    panel = FileExplorerPanel(tmp_path)

    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("sub", True))
    panel._create(tmp_path, True)
    assert (tmp_path / "sub").is_dir()

    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("a.dts", True))
    panel._create(tmp_path / "sub", False)
    assert (tmp_path / "sub" / "a.dts").is_file()

    # Borrar pregunta, y un «No» deja el fichero donde estaba: del disco no
    # lo recupera nadie desde aquí.
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    panel._delete(tmp_path / "sub" / "a.dts")
    assert (tmp_path / "sub" / "a.dts").is_file()

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    panel._delete(tmp_path / "sub" / "a.dts")
    assert not (tmp_path / "sub" / "a.dts").exists()
    panel.deleteLater()


def test_la_pestana_de_overlays_solo_esta_mientras_hay_borrador(window):
    """Una pestaña permanentemente vacía invita a entrar donde no hay nada.

    El asistente y el listado viven en la sección OVERLAYS del panel
    izquierdo; la vista central solo existe mientras se está construyendo.
    """
    _abrir_zynqmp(window)
    titulos = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert "Overlays" not in titulos, titulos

    window._start_overlay_pick()
    nodo = _primer_nodo_con_label(window._overlay_base)
    window._on_editor_node_clicked(nodo)
    assert window.tabs.tabText(window.tabs.currentIndex()) == "Overlays"

    window._cancel_overlay()
    titulos = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert "Overlays" not in titulos, titulos


def test_la_franja_de_registro_sigue_a_la_herramienta_elegida(window):
    """Entrar en overlays enseña su registro; salir devuelve los diagnósticos."""
    from kernelgrove.gui.tabs.editor_tab import LOG_DIAGNOSTICS, LOG_OVERLAYS
    from kernelgrove.gui.main_window import SECTION_OVERLAY

    from kernelgrove.gui.main_window import SECTION_FOLDERS

    editor = window.editor_tab
    assert editor._log_stack.currentIndex() == LOG_DIAGNOSTICS
    assert editor.log_tabs[LOG_DIAGNOSTICS].isChecked()

    window.activity_bar.show_section(SECTION_OVERLAY)
    assert editor._log_stack.currentIndex() == LOG_OVERLAYS
    assert editor.log_tabs[LOG_OVERLAYS].isChecked()
    # El filtro por gravedad no dice nada sobre un registro de overlays.
    assert all(w.isHidden() for w in editor._diagnostic_only)

    window.activity_bar.show_section(SECTION_FOLDERS)
    assert editor._log_stack.currentIndex() == LOG_DIAGNOSTICS
    # «Clear» solo vale para el registro: los diagnósticos los reemplaza
    # cada análisis, no se acumulan.
    assert editor.clear_log_button.isHidden()


def test_el_registro_de_overlays_se_puede_vaciar(window):
    """Va sumando informes hasta llenarse de comprobaciones que ya no valen."""
    from kernelgrove.gui.main_window import SECTION_OVERLAY

    editor = window.editor_tab
    editor.append_overlay_log("una comprobación")
    window.activity_bar.show_section(SECTION_OVERLAY)
    assert not editor.clear_log_button.isHidden()

    editor.clear_log_button.click()
    assert editor.overlay_log.toPlainText() == ""


def test_el_informe_de_validacion_acaba_en_la_franja_de_abajo(window, tmp_path):
    """El registro de comprobaciones y el de diagnósticos comparten sitio."""
    (tmp_path / "roto.dtso").write_text(
        "/dts-v1/;\n/plugin/;\n&no_existe { status = \"okay\"; };\n",
        encoding="utf-8",
    )
    _abrir_zynqmp(window)
    window.explorer_panel.set_root(tmp_path)
    window.overlay_panel.set_library(tmp_path, window._overlay_base)

    window.overlay_panel.overlay_list.validate(
        [str(tmp_path / "roto.dtso")], "xilinx/zynqmp.dtsi"
    )

    registro = window.editor_tab.overlay_log.toPlainText()
    assert "roto.dtso" in registro
    assert "layer 6" in registro


def test_el_editor_marca_lo_editado_y_sin_guardar(window, tmp_path):
    """La franja del margen habla del texto que hay escrito, no del disco.

    Es la diferencia con llamar a `git diff`: mientras se escribe, el
    fichero guardado va por detrás de lo que se está viendo.
    """
    import subprocess

    from kernelgrove.api import git_repo

    if not git_repo.git_available():
        pytest.skip("hace falta git")

    repo = git_repo.init_repo(tmp_path)
    for clave, valor in (("user.name", "Test"), ("user.email", "t@example.com")):
        subprocess.run(["git", "config", clave, valor], cwd=tmp_path, check=True)
    fichero = tmp_path / "board.dts"
    fichero.write_text("/dts-v1/;\n/ {\n};\n", encoding="utf-8")
    repo.stage_all()
    repo.save_version("Initial version")

    window.explorer_panel.set_root(tmp_path)
    window.git_panel.set_root(tmp_path)
    window._open_explorer_file(str(fichero))
    document = window.editor_tab.current
    assert document is not None

    # Sin tocar nada no hay nada que marcar.
    window._mark_git_changes(document)
    assert not document.editor._modified_lines
    assert not document.editor._added_changes

    # Y con una línea cambiada y otra nueva, sin guardar, sí.
    document.editor.setPlainText("/dts-v2/;\n/ {\n};\n// nueva\n")
    window._mark_git_changes(document)
    assert document.editor._modified_lines == {1}
    assert document.editor._added_changes == {4}


def test_analizar_no_lanza_git_status(window, tmp_path, monkeypatch):
    """Teclear no cambia el disco, así que no puede costar un `git status`.

    Se hacía en cada análisis -o sea, cada vez que se dejaba de teclear 600
    ms- para teñir el árbol de carpetas, con el argumento de que era el mismo
    momento y salía gratis. No salía: en un repositorio grande (el checkout
    del kernel) son ~200 ms bloqueando la interfaz por pulsación. El margen
    del editor sí se recalcula aquí, que es un `git show` de unos ms y habla
    del texto escrito.
    """
    import subprocess

    from kernelgrove.api import git_repo

    if not git_repo.git_available():
        pytest.skip("hace falta git")

    repo = git_repo.init_repo(tmp_path)
    for clave, valor in (("user.name", "Test"), ("user.email", "t@example.com")):
        subprocess.run(["git", "config", clave, valor], cwd=tmp_path, check=True)
    fichero = tmp_path / "board.dts"
    fichero.write_text("/dts-v1/;\n/ {\n};\n", encoding="utf-8")
    repo.stage_all()
    repo.save_version("Initial version")

    window.explorer_panel.set_root(tmp_path)
    window.git_panel.set_root(tmp_path)
    window._open_explorer_file(str(fichero))
    document = window.editor_tab.current
    assert document is not None

    ordenes = []
    original = git_repo._run
    monkeypatch.setattr(
        git_repo,
        "_run",
        lambda args, cwd, check=True: (
            ordenes.append(args[0]), original(args, cwd, check)
        )[1],
    )

    document.editor.setPlainText("/dts-v1/;\n/ {\n};\n// nueva\n")
    window._mark_git_changes(document)
    assert "status" not in ordenes, "teclear no puede costar un git status"
    # Y lo que sí hace falta ahí sigue haciéndose: el margen se recalcula.
    assert document.editor._added_changes == {4}

    # Guardar sí toca el disco, y entonces el árbol se vuelve a teñir.
    teñidos = []
    monkeypatch.setattr(
        window.explorer_panel, "set_git_status", teñidos.append
    )
    window.editor_tab.mark_saved(document, document.editor.toPlainText())
    assert teñidos, "al guardar hay que repintar el estado del árbol"


def test_supr_borra_en_el_panel_de_carpetas(app, tmp_path, monkeypatch):
    """Es lo que hace esa tecla en cualquier explorador, carpetas incluidas."""
    from PySide6.QtWidgets import QMessageBox
    from kernelgrove.gui.widgets.file_explorer import FileExplorerPanel

    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "dentro.dts").write_text("x", encoding="utf-8")
    panel = FileExplorerPanel(tmp_path)

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    # Una carpeta se lleva por delante lo que tenga dentro.
    panel._delete(tmp_path / "sub")
    assert not (tmp_path / "sub").exists()
    panel.deleteLater()


def test_el_minimapa_resume_el_fichero_y_permite_saltar(app):
    """Es para lo que está: ver dónde hay algo y llegar allí de un salto."""
    from kernelgrove.api import Diagnostic, DiagnosticCode, Severity
    from kernelgrove.gui.widgets.dts_editor import DtsEditor

    editor = DtsEditor()
    editor.resize(600, 300)
    editor.setPlainText("\n".join(f"    linea {i}" for i in range(1, 401)))

    # Las líneas en blanco no dibujan nada; las demás, según lo llenas que
    # estén, que es la silueta por la que uno reconoce un fichero.
    formas = dict(editor.line_shapes())
    assert len(formas) == 400
    assert all(0 < ancho <= 1 for ancho in formas.values())

    editor.set_change_lines(added=[7], modified=[9])
    editor.set_diagnostics(
        [
            Diagnostic(
                code=DiagnosticCode.MISSING_SEMICOLON,
                severity=Severity.ERROR,
                message="x",
                line=300,
            )
        ]
    )
    assert editor.change_color(7) == style.EDITOR_CHANGE_ADDED
    assert editor.change_color(9) == style.EDITOR_CHANGE_MODIFIED
    assert editor.change_color(8) is None
    assert editor.diagnostic_severity(300) is Severity.ERROR

    # INFO no pinta banda en el minimapa: es la severidad más numerosa con
    # diferencia y lo dejaría pintado de arriba abajo sin decir nada.
    from kernelgrove.gui.widgets.dts_editor import severity_mark

    assert severity_mark(Severity.ERROR) is not None
    assert severity_mark(Severity.WARNING) is not None
    assert severity_mark(Severity.INFO) is None

    # Pulsar abajo del todo lleva al final del fichero, no a una línea suelta.
    antes = editor.visible_line_range()
    editor._minimap._scroll_to(editor._minimap.height())
    assert editor.visible_line_range()[0] > antes[0]
    editor.deleteLater()


def test_la_piel_de_la_web_trae_sus_tokens_tal_cual(window, app):
    """Los valores son los de `landing_page/css/style.css`, no unos parecidos.

    Y el cambio es en caliente: la hoja se recompone y los colores que usan
    los `QPainter` -donde el QSS no llega- se recalculan con ella.
    """
    from kernelgrove.gui import style, theme

    window._set_skin(theme.SKIN_SITE)
    window._set_theme(theme.MODE_LIGHT)
    assert theme.BG == "#ffffff"
    assert theme.ACCENT == "#6d5bff"
    assert theme.ACCENT_TEXT == "#5a45e0"
    claro = style.EDITOR_SYNTAX_PROPERTY[0]
    assert "#ffffff" in app.styleSheet()

    window._set_theme(theme.MODE_DARK)
    assert theme.BG == "#0a0a0c"
    assert theme.ACCENT == "#7261e8"
    assert theme.ACCENT_TEXT == "#a996ff"
    assert style.EDITOR_SYNTAX_PROPERTY[0] != claro, "el resaltado sigue al modo"
    assert "#0a0a0c" in app.styleSheet()

    # La forma **no** es suya: es la misma con cualquier piel.
    assert theme.RADIUS_PANEL == 0 and theme.RADIUS_CONTROL == 2


def test_la_piel_clasica_es_la_de_siempre_y_es_la_de_fabrica(window, app):
    """La que viene puesta es la densa de siempre, con sus cuatro superficies.

    Lo que conserva es su **paleta**: las cuatro superficies y el morado
    dioxazina. La forma ya no es suya —radios, rellenos y rótulos son los
    mismos con cualquier piel—, que es lo que hace que cambiar de tema no
    mueva nada de sitio.
    """
    from kernelgrove.gui import theme

    window._set_skin(theme.SKIN_CLASSIC)
    assert theme.current_skin() == theme.SKIN_CLASSIC
    assert theme.SUNKEN == "#0f1216"
    # `panel` se aclaró al ensanchar la rampa (ver `test_theme_contrast`):
    # las zonas se separan por tono, así que el escalón es parte de la
    # paleta clásica tanto como el morado.
    assert theme.PANEL == "#1f242c"
    assert theme.ACCENT == "#9a70f0"
    assert "Inter" in app.styleSheet(), "la tipografía es lo que sí cambia"
    # Solo tiene modo oscuro: no se le inventa uno claro.
    assert theme.modes_of(theme.SKIN_CLASSIC) == (theme.MODE_DARK,)
    assert theme.resolve_mode() == theme.MODE_DARK


def test_los_overlays_se_listan_tambien_desde_una_subcarpeta(window, app, tmp_path):
    """La carpeta `overlays/` es donde todo el mundo los guarda.

    Y las ocultas no: `.git` tiene miles de ficheros y ninguno es un
    overlay de nadie.
    """
    (tmp_path / "raiz.dtso").write_text("x", encoding="utf-8")
    (tmp_path / "overlays").mkdir()
    (tmp_path / "overlays" / "dentro.dtso").write_text("x", encoding="utf-8")
    (tmp_path / "a" / "b" / "c").mkdir(parents=True)
    (tmp_path / "a" / "b" / "c" / "hondo.dtso").write_text("x", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "oculto.dtso").write_text("x", encoding="utf-8")

    window.overlay_panel.set_library(tmp_path, None)
    listado = window.overlay_panel.overlay_list
    nombres = sorted(path.name for path in listado._overlay_files())
    assert nombres == ["dentro.dtso", "raiz.dtso"], nombres


def test_renombrar_en_el_panel_de_carpetas_arrastra_lo_que_apuntaba_al_fichero(
    window, app, tmp_path, monkeypatch
):
    """Renombrar y que «Guardar» no resucite el nombre viejo.

    Es lo que hace que renombrar sea renombrar y no «crear otro»: la
    pestaña abierta tiene que quedarse apuntando al fichero de verdad.
    """
    from PySide6.QtWidgets import QInputDialog

    origen = tmp_path / "viejo.dts"
    origen.write_text('/dts-v1/;\n/ { };\n', encoding="utf-8")

    window.explorer_panel.set_root(tmp_path)
    window.overlay_panel.set_library(tmp_path, None)
    window.editor_tab.open_source(
        title=origen.name,
        text=origen.read_text(encoding="utf-8"),
        source_key=str(origen),
        disk_path=origen,
    )
    app.processEvents()

    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("nuevo.dts", True))
    window.explorer_panel._rename(origen)
    app.processEvents()

    assert not origen.exists()
    assert (tmp_path / "nuevo.dts").is_file()
    documento = window.editor_tab.current
    assert documento.disk_path == tmp_path / "nuevo.dts"
    assert documento.source_key == str(tmp_path / "nuevo.dts")
    assert documento.title == "nuevo.dts"
    # Y la lista de árboles de BUILD TOOLS enseña el nombre nuevo.
    panel = window.build_panel
    nombres = [panel.tree_list.item(i).text() for i in range(panel.tree_list.count())]
    assert nombres == ["nuevo.dts"]


def test_arrastrar_en_el_panel_de_carpetas_mueve_el_fichero(
    window, app, tmp_path, monkeypatch
):
    """Mover arrastrando, y que lo movido siga siendo lo que la pestaña edita.

    Mover es renombrar con otra carpeta, así que lo que se comprueba es lo
    mismo que en el renombrado —«Guardar» no puede resucitar la ruta
    vieja— más lo que solo pasa moviendo: que arrastrando una **carpeta**
    la siguen los ficheros que tenía dentro abiertos.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractItemView, QMessageBox

    avisos = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: avisos.append(a[2]) or QMessageBox.Ok
    )

    (tmp_path / "overlays").mkdir()
    (tmp_path / "sub").mkdir()
    suelto = tmp_path / "board.dts"
    suelto.write_text("/dts-v1/;\n/ { };\n", encoding="utf-8")
    dentro = tmp_path / "sub" / "incluido.dtsi"
    dentro.write_text("/ { };\n", encoding="utf-8")

    panel = window.explorer_panel
    panel.set_root(tmp_path)
    window.overlay_panel.set_library(tmp_path, None)
    app.processEvents()

    # El arrastre está montado sobre el árbol: sin esto no empieza siquiera.
    assert panel.tree.dragEnabled() and panel.tree.acceptDrops()
    assert panel.tree.dragDropMode() == QAbstractItemView.DragDrop
    assert panel.tree.defaultDropAction() == Qt.MoveAction
    assert not panel._model.isReadOnly()
    # Y las filas lo llevan: sin las banderas del modelo el arrastre no
    # arranca, y lo que viaja es la ruta del fichero, que es lo que
    # `dropEvent` lee para saber qué mover.
    fila = panel._model.index(str(suelto))
    assert panel._model.flags(fila) & Qt.ItemIsDragEnabled
    assert panel._model.flags(panel._model.index(str(tmp_path / "overlays")))\
        & Qt.ItemIsDropEnabled
    assert panel._model.mimeData([fila]).urls()[0].toLocalFile() == str(suelto)

    def soltar_en(rutas, carpeta):
        """Lo que hace `dropEvent` una vez sabe dónde cayó el ratón."""
        panel._move_paths(list(rutas), panel._model.index(str(carpeta)))
        app.processEvents()

    def pestaña_de(ruta):
        """El documento abierto que apunta a esa ruta, si alguno."""
        for documento in window.editor_tab._documents.values():
            if documento.disk_path == ruta:
                return documento
        return None

    for ruta in (suelto, dentro):
        window.editor_tab.open_source(
            title=ruta.name,
            text=ruta.read_text(encoding="utf-8"),
            source_key=str(ruta),
            disk_path=ruta,
        )
    app.processEvents()

    soltar_en([suelto], tmp_path / "overlays")
    assert not suelto.exists()
    assert (tmp_path / "overlays" / "board.dts").is_file()
    assert pestaña_de(tmp_path / "overlays" / "board.dts") is not None

    # Una carpeta entera: lo que tenía dentro cambia de ruta con ella, y la
    # pestaña que lo tuviera abierto tiene que enterarse.
    soltar_en([tmp_path / "sub"], tmp_path / "overlays")
    nueva = tmp_path / "overlays" / "sub" / "incluido.dtsi"
    assert nueva.is_file()
    documento = pestaña_de(nueva)
    assert documento is not None, "la pestaña se quedó apuntando a la carpeta vieja"
    assert documento.source_key == str(nueva)

    # Y lo que no cabe se rechaza sin perder nada: ni pisando un fichero que
    # ya está ahí, ni metiendo una carpeta dentro de sí misma.
    otro = tmp_path / "board.dts"
    otro.write_text("otro\n", encoding="utf-8")
    soltar_en([otro], tmp_path / "overlays")
    assert otro.read_text(encoding="utf-8") == "otro\n"
    assert (tmp_path / "overlays" / "board.dts").read_text(encoding="utf-8").startswith(
        "/dts-v1/;"
    )
    soltar_en([tmp_path / "overlays"], tmp_path / "overlays" / "sub")
    assert (tmp_path / "overlays").is_dir()
    # Los dos rechazos se cuentan una vez cada uno, no uno por fichero.
    assert len(avisos) == 2


def test_el_catalogo_busca_bindings_y_abre_su_ficha(window, app):
    """El otro lado del catálogo: buscar un compatible y ver qué exige.

    Sustituye al volcado JSON del binding que había antes: lo que se viene a
    preguntar es qué propiedades lleva el dispositivo, no cómo está escrito
    el schema.
    """
    from kernelgrove.gui.tabs.database_tab import (
        _ROLE_DESCRIPTION,
        _ROLE_FIELDS,
        _ROLE_GROUP,
        VIEW_BINDINGS,
        VIEW_TREES,
    )
    from kernelgrove.gui.widgets.schema_dialog import SchemaDialog

    catalogo = window.database_tab
    catalogo.show_view(VIEW_BINDINGS)
    # Los filtros de hardware no dicen nada de un binding y se van con él.
    # `isHidden` y no `isVisible`: la ventana del catálogo está cerrada en
    # la prueba, y con el padre oculto nada de dentro se considera visible.
    assert catalogo._filters.isHidden()

    catalogo.search.setText("cdns,i2c-r1p14")
    app.processEvents()
    filas = [
        catalogo.bindings.item(i).text()
        for i in range(catalogo.bindings.count())
    ]
    assert "cdns,i2c-r1p14" in filas, filas
    # La ficha, no una fila de tabla: su grupo en la paleta —el mismo con el
    # que se conecta el dispositivo— decide el icono y la insignia.
    ficha = catalogo.bindings.item(filas.index("cdns,i2c-r1p14"))
    assert ficha.data(_ROLE_GROUP) == "buses"
    assert ficha.data(_ROLE_DESCRIPTION)
    campos = dict(ficha.data(_ROLE_FIELDS))
    assert campos[catalogo.tr("vendor")] == "cdns"

    dialogo = SchemaDialog(window.service, "cdns,i2c-r1p14")
    # La herencia resuelta: el binding declara catorce propiedades y hereda
    # cuarenta y ocho, así que la ficha no puede quedarse en las suyas.
    assert dialogo._properties.topLevelItemCount() > 14
    nombres = [
        dialogo._properties.topLevelItem(i).text(0)
        for i in range(dialogo._properties.topLevelItemCount())
    ]
    assert "reg" in nombres and "clocks" in nombres
    # Obligatorias primero, que es el orden en el que se escribe un nodo.
    assert dialogo._properties.topLevelItem(0).text(1) == dialogo.tr("REQUIRED")
    dialogo.deleteLater()
    app.processEvents()

    catalogo.show_view(VIEW_TREES)
    assert not catalogo._filters.isHidden()


def test_el_catalogo_de_bindings_filtra_por_fabricante_y_por_tipo(window, app):
    """Los dos filtros que sí dicen algo de un dispositivo, contra la base.

    Contra SQL y no sobre lo que hay cargado, que es lo único que puede
    fallar de forma invisible: la lista viene recortada a las primeras 300
    de 25 458, así que un fabricante cuyos compatibles caigan fuera de ese
    recorte —`abracon` se acaba dentro de la primera página, `xlnx` no—
    no saldría nunca si se filtrara después de traerlas.
    """
    from kernelgrove.gui.tabs.database_tab import _ROLE_FIELDS, VIEW_BINDINGS
    from kernelgrove.gui.widgets import binding_groups

    catalogo = window.database_tab
    # Los desplegables se llenan al abrir el catálogo, que es la única
    # puerta que tiene.
    window.open_database()
    catalogo.show_view(VIEW_BINDINGS)
    # Cada catálogo con su franja: la de hardware se va y esta se queda.
    assert catalogo._filters.isHidden()
    assert not catalogo._binding_filters.isHidden()

    # Los tipos son los grupos de la paleta y en su orden curado, no una
    # clasificación propia del catálogo: el mismo con el que el dispositivo
    # se conecta al árbol y el mismo que la ficha enseña como icono.
    tipos = [
        catalogo.device_type_combo.itemData(i)
        for i in range(1, catalogo.device_type_combo.count())
    ]
    assert tipos and all(g in binding_groups.GROUP_ORDER for g in tipos)
    assert tipos == [g for g in binding_groups.GROUP_ORDER if g in tipos]

    catalogo.binding_vendor_combo.setCurrentIndex(
        catalogo.binding_vendor_combo.findData("xlnx")
    )
    app.processEvents()
    de_xilinx = _filas(catalogo.bindings)
    assert de_xilinx and all(f.startswith("xlnx,") for f in de_xilinx)

    # Y el tipo cruza con el fabricante, no lo sustituye: lo que queda son
    # los de Xilinx cuyo subsistema cae en el grupo elegido.
    catalogo.device_type_combo.setCurrentIndex(
        catalogo.device_type_combo.findData("buses")
    )
    app.processEvents()
    buses = _filas(catalogo.bindings)
    assert buses and set(buses) < set(de_xilinx)
    de_ese_grupo = set(catalogo._group_subsystems["buses"])
    for fila in range(catalogo.bindings.count()):
        campos = dict(catalogo.bindings.item(fila).data(_ROLE_FIELDS))
        assert campos[catalogo.tr("subsystem")] in de_ese_grupo

    catalogo.device_type_combo.setCurrentIndex(0)
    app.processEvents()
    assert _filas(catalogo.bindings) == de_xilinx

    # La cuenta cuenta lo que se está filtrando y no la tabla entera: «300
    # de 25 458» con un filtro puesto estaría contando otra cosa que la que
    # se ve.
    assert catalogo._binding_count.text() == catalogo.tr(
        "{shown} of {total} documented compatibles"
    ).format(shown=len(de_xilinx), total=len(de_xilinx))


def test_build_tools_lista_los_binarios_y_marca_lo_que_sale_de_la_base(
    app, tmp_path
):
    """Lo compilado se ve y se descompila desde ahí; lo del catálogo se marca.

    Dos listas y no una: la de arriba es «qué se construye» y su elección es
    además la base contra la que se comprueban los overlays, así que elegir
    ahí un binario no querría decir nada.

    Sobre el panel suelto y no sobre la ventana: lo que se comprueba es lo
    que el panel enseña y lo que pide, y colgado de la ventana el botón
    llega hasta `dtc` y hasta un diálogo modal, que en una prueba se queda
    esperando para siempre.
    """
    from kernelgrove.gui.widgets.build_panel import BuildPanel

    (tmp_path / "board.dts").write_text("/dts-v1/;\n/ { };\n", encoding="utf-8")
    (tmp_path / "board.dtb").write_bytes(b"\xd0\x0d\xfe\xed")
    (tmp_path / "uno.dtso").write_text("/dts-v1/;\n/plugin/;\n", encoding="utf-8")
    (tmp_path / "uno.dtbo").write_bytes(b"\xd0\x0d\xfe\xed")

    build = BuildPanel()
    build.set_toolchain(dtc=True, cpp=True)
    build.set_folder(tmp_path)
    app.processEvents()

    # Arriba lo que se construye —el `.dtso` no es un árbol— y abajo lo que
    # sale de construirlo, que es lo que se puede leer de vuelta.
    assert [
        build.tree_list.item(i).text() for i in range(build.tree_list.count())
    ] == ["board.dts"]
    assert sorted(
        build.blob_list.item(i).text() for i in range(build.blob_list.count())
    ) == ["board.dtb", "uno.dtbo"]

    # Descompilar es cosa del botón: un doble clic en la lista no lanza
    # nada, que es lo que evita descompilar sin querer al elegir una fila.
    pedidos = []
    build.decompileRequested.connect(pedidos.append)
    build.blob_list.itemActivated.emit(build.blob_list.item(0))
    assert pedidos == []
    build.blob_list.setCurrentRow(0)
    app.processEvents()
    elegido = build.blob_list.item(0).text()
    assert elegido in build.decompile_button.text(), "el botón dice sobre qué actúa"
    build.decompile_button.click()
    assert pedidos == [str(tmp_path / elegido)]

    # Sin binario elegido no se apaga: pide uno, porque lo compilado puede
    # estar fuera de la carpeta abierta y ahí esta lista no llega.
    build.blob_list.clearSelection()
    app.processEvents()
    build.decompile_button.click()
    assert pedidos[-1] == ""

    # Y lo que sale de la base lleva la nube: no está en ninguna ruta del
    # disco, así que el nombre por sí solo engaña.
    build.add_database_entry("xilinx/zynqmp-zcu102-rev1.0.dts", "zcu102.dts")
    app.processEvents()
    filas = {
        build.tree_list.item(i).text(): build.tree_list.item(i)
        for i in range(build.tree_list.count())
    }
    assert not filas["zcu102.dts"].icon().isNull(), "la del catálogo va marcada"
    assert filas["board.dts"].icon().isNull(), "la del disco no necesita marca"
    build.deleteLater()
    app.processEvents()


def test_las_listas_de_la_carpeta_siguen_al_disco(window, app, tmp_path):
    """Borrar o dejar caer un fichero se ve sin salir de la sección y volver.

    Las dos listas —overlays y binarios— son una lectura del disco, no un
    modelo vivo, y hasta ahora solo se releían al entrar en su sección. El
    panel de carpetas sí se enteraba solo, porque su `QFileSystemModel`
    vigila; esto es lo mismo para las que no.
    """
    from PySide6.QtTest import QTest

    (tmp_path / "overlays").mkdir()
    (tmp_path / "board.dts").write_text("/dts-v1/;\n/ { };\n", encoding="utf-8")
    (tmp_path / "board.dtb").write_bytes(b"\xd0\x0d\xfe\xed")
    (tmp_path / "overlays" / "uno.dtso").write_text(
        "/dts-v1/;\n/plugin/;\n", encoding="utf-8"
    )

    window.explorer_panel.set_root(tmp_path)
    window.build_panel.set_folder(tmp_path)
    window.overlay_panel.set_library(tmp_path, None)
    window._watch_folder(tmp_path)
    QTest.qWait(100)

    def listas():
        build = window.build_panel
        tabla = window.overlay_panel.overlay_list.table
        return (
            sorted(_filas(build.tree_list)),
            sorted(_filas(build.blob_list)),
            sorted(
                tabla.topLevelItem(i).text(1)
                for i in range(tabla.topLevelItemCount())
            ),
        )

    assert listas() == (["board.dts"], ["board.dtb"], ["uno.dtso"])

    # Se toca el disco por fuera, sin pasar por ninguna sección.
    (tmp_path / "board.dtb").unlink()
    (tmp_path / "otro.dts").write_text("/dts-v1/;\n/ { };\n", encoding="utf-8")
    (tmp_path / "otro.dtbo").write_bytes(b"\xd0\x0d\xfe\xed")
    # En una subcarpeta, que es donde todo el mundo guarda los overlays.
    (tmp_path / "overlays" / "dos.dtso").write_text(
        "/dts-v1/;\n/plugin/;\n", encoding="utf-8"
    )

    for _ in range(40):
        QTest.qWait(50)
        if listas() == (
            ["board.dts", "otro.dts"], ["otro.dtbo"], ["dos.dtso", "uno.dtso"]
        ):
            break
    assert listas() == (
        ["board.dts", "otro.dts"], ["otro.dtbo"], ["dos.dtso", "uno.dtso"]
    )


def test_la_seccion_de_overlays_construye_el_arbol_elegido(window, app, tmp_path):
    """Interruptor por overlay, un árbol elegido, y el registro BUILD.

    Es el ciclo entero de la sección: se marca qué overlays entran, se
    elige el `.dts` que se construye —que es además la base contra la que
    se comprueban— y lo que dicen `cpp` y `dtc` sale en su propia página de
    la franja de abajo.
    """
    from PySide6.QtCore import Qt

    from kernelgrove.api.toolchain import detect_toolchain
    from kernelgrove.gui.tabs.editor_tab import LOG_BUILD
    from kernelgrove.gui.widgets.overlay_list import COLUMN_TOGGLE

    (tmp_path / "board.dts").write_text(
        '/dts-v1/;\n/ {\n  model = "T";\n  compatible = "t,b";\n'
        '  i2c0: i2c@1000 {\n    #address-cells = <1>;\n'
        '    #size-cells = <0>;\n  };\n};\n',
        encoding="utf-8",
    )
    (tmp_path / "uno.dtso").write_text(
        '/dts-v1/;\n/plugin/;\n\n&i2c0 {\n  status = "okay";\n};\n',
        encoding="utf-8",
    )

    panel = window.overlay_panel
    panel.set_library(tmp_path, None)
    build = window.build_panel
    build.set_folder(tmp_path)

    # Los `.dts` se listan en BUILD TOOLS, y el fragmento no entra.
    arboles = [build.tree_list.item(i).text() for i in range(build.tree_list.count())]
    assert arboles == ["board.dts"]

    # El interruptor decide qué entra en la compilación; la selección no.
    fila = panel.overlay_list.table.topLevelItem(0)
    assert panel.overlay_list.checked_paths() == []
    fila.setCheckState(COLUMN_TOGGLE, Qt.Checked)
    assert panel.overlay_list.checked_paths() == [str(tmp_path / "uno.dtso")]

    # El recuento de encendidos llega a la otra sección, que es la que compila.
    window._refresh_overlay_count()
    assert "1" in build._overlays_label.text()

    # La lista se pliega, que es lo que deja sitio al resto del panel.
    panel._overlays_toggle.setChecked(False)
    assert panel.overlay_list.isHidden()
    panel._overlays_toggle.setChecked(True)

    # Sin árbol elegido no se construye, y el botón dice por qué.
    assert not build.build_button.isEnabled()
    build.tree_list.item(0).setSelected(True)
    assert build.selected_key() == str(tmp_path / "board.dts")
    assert build.build_button.isEnabled() == detect_toolchain().can_compile

    if not detect_toolchain().can_compile:
        pytest.skip("hacen falta dtc y cpp para construir")

    window._build_device_tree()
    app.processEvents()

    registro = window.editor_tab.build_log.toPlainText()
    assert window.editor_tab._log_stack.currentIndex() == LOG_BUILD
    assert "board.dts" in registro and "uno.dtso" in registro
    assert "$ " in registro, "la orden de cpp y dtc queda registrada"
    assert (tmp_path / "board.dtb").is_file()
    assert (tmp_path / "uno.dtbo").is_file()


def test_cada_cambio_de_git_lleva_sus_botones(window, app, tmp_path):
    """Como en VS Code: lo que se puede hacer con un cambio, en su fila.

    Y depende de en qué grupo esté: lo preparado solo se puede sacar de la
    preparación; lo que no lo está, preparar o descartar.
    """
    import subprocess

    from PySide6.QtWidgets import QToolButton

    from kernelgrove.api import git_repo
    from kernelgrove.gui.widgets.git_panel import _COLUMN_ACTIONS, _PAYLOAD_ROLE

    if not git_repo.git_available():
        pytest.skip("git no está instalado")

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for name, valor in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(tmp_path), "config", name, valor], check=True)
    (tmp_path / "preparado.dts").write_text("/ { };", encoding="utf-8")
    (tmp_path / "suelto.dts").write_text("/ { };", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "preparado.dts"], check=True)

    panel = window.git_panel
    panel.set_root(tmp_path)
    panel.refresh()
    app.processEvents()

    # El botón de guardar existe y está a la vista: en la misma fila que el
    # mensaje se lo comía el desplegable.
    assert not panel._save_button.isHidden()
    assert panel._save_button.text()

    botones = {}
    for grupo in range(panel._changes.topLevelItemCount()):
        padre = panel._changes.topLevelItem(grupo)
        for fila in range(padre.childCount()):
            item = padre.child(fila)
            widget = panel._changes.itemWidget(item, _COLUMN_ACTIONS)
            assert widget is not None, "cada cambio lleva los suyos"
            botones[item.data(0, _PAYLOAD_ROLE).path] = {
                b.text(): b for b in widget.findChildren(QToolButton)
            }

    assert list(botones["preparado.dts"]) == ["−"], "lo preparado solo se saca"
    assert sorted(botones["suelto.dts"]) == sorted(["↺", "+"])

    # Y pulsarlos hace lo que dicen. `clicked` lleva un `checked` que Qt
    # pasa siempre y que aterrizaba en el argumento por defecto donde iba
    # el cambio: los tres botones operaban sobre `False` en vez de sobre su
    # fichero, y no hacían nada visible.
    botones["suelto.dts"]["+"].click()
    app.processEvents()
    assert "suelto.dts" in [c.path for c in panel._repo.status().staged]

    botones["preparado.dts"]["−"].click()
    app.processEvents()
    assert "preparado.dts" not in [c.path for c in panel._repo.status().staged]


def test_el_panel_de_git_no_repinta_si_nada_ha_cambiado(window, app, tmp_path):
    """Releer el repositorio es barato; rehacer la lista no.

    Cada cambio lleva sus dos botones como widgets de verdad, así que un
    árbol con un renombrado masivo son cientos de widgets construidos —~120
    ms— y se rehacían enteros cada vez que se entraba en la sección. Se
    comprueba por identidad: si hubiera repintado, las filas serían objetos
    nuevos.
    """
    import subprocess

    from kernelgrove.api import git_repo

    if not git_repo.git_available():
        pytest.skip("git no está instalado")

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for name, valor in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(tmp_path), "config", name, valor], check=True)
    (tmp_path / "uno.dts").write_text("/ { };", encoding="utf-8")

    panel = window.git_panel
    panel.set_root(tmp_path)
    panel.refresh()
    app.processEvents()
    fila = panel._changes.topLevelItem(0).child(0)
    assert fila is not None

    # Sin tocar nada, la lista es literalmente la misma.
    panel.refresh()
    assert panel._changes.topLevelItem(0).child(0) is fila

    # Y en cuanto el repositorio cambia, se repinta.
    (tmp_path / "dos.dts").write_text("/ { };", encoding="utf-8")
    panel.refresh()
    app.processEvents()
    assert panel._changes.topLevelItem(0).child(0) is not fila
    nombres = [
        panel._changes.topLevelItem(0).child(i).text(0)
        for i in range(panel._changes.topLevelItem(0).childCount())
    ]
    assert any("dos.dts" in texto for texto in nombres)


def test_la_franja_de_registro_se_cierra_y_se_reabre(window, app):
    """Se cierra con su «✕» y se recupera por Ver → Logging panel.

    La flecha de plegar que había escondía lo de dentro sin tocar el
    reparto del `QSplitter`: quedaba la cabecera flotando sobre medio panel
    vacío, que se lee como «el botón no hace nada».
    """
    from PySide6.QtWidgets import QMenu

    editor = window.editor_tab
    assert editor.log_panel_visible()

    editor.close_log_button.click()
    app.processEvents()
    assert not editor.log_panel_visible(), "el ✕ cierra la franja entera"

    # Y la entrada del menú la devuelve.
    acciones = [
        a for menu in window.menu_bar.findChildren(QMenu)
        for a in menu.actions()
        if "Logging" in a.text() or "registro" in a.text().lower()
    ]
    assert acciones, "Ver → Logging panel tiene que existir"
    acciones[0].trigger()
    app.processEvents()
    assert editor.log_panel_visible()

    # Y un informe la abre sola: escribirlo donde no se ve es no escribirlo.
    editor.close_log_button.click()
    editor.append_overlay_log("12:00:00 · algo")
    assert editor.log_panel_visible()


def test_el_registro_de_overlays_se_colorea_por_su_glifo(app):
    """Verde, rojo y ámbar salen del glifo, nunca de la palabra traducida."""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QPlainTextEdit

    from kernelgrove.gui.widgets.dts_editor import OverlayLogHighlighter

    caja = QPlainTextEdit()
    resaltador = OverlayLogHighlighter(caja.document())
    caja.setPlainText("\n".join(["─" * 8, "12:00:00 · a.dtso", "  ✓ bien", "  ✗ mal"]))
    resaltador.rehighlight()

    def color(linea: int) -> str:
        bloque = caja.document().findBlockByNumber(linea)
        formatos = bloque.layout().formats()
        assert formatos, f"la línea {linea} no está coloreada"
        return QColor(formatos[0].format.foreground().color()).name()

    assert color(2) == QColor(style.COLOR_DROP_OK).name()
    assert color(3) == QColor(style.EDITOR_ERROR_ACCENT).name()
    assert color(0) == color(1), "la regla y la hora son la misma cabecera"
    assert color(2) != color(3)
    caja.deleteLater()


def test_pulsar_una_propiedad_abre_su_ficha(window, app):
    """La lista del inspector dice el tipo; el detalle, en su ventana.

    El valor no se enseña: está escrito en el editor a media pantalla de
    ahí. Lo que no está escrito en ninguna parte es de qué tipo es cada
    propiedad, y eso es lo que decide si va entre `<>` o entre comillas.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor

    from kernelgrove.gui.main_window import TAB_EDITOR

    window.editor_tab.open_source(
        title="zynqmp.dtsi",
        text=FIXTURE.read_text(encoding="utf-8"),
        source_key="xilinx/zynqmp.dtsi",
    )
    window.editor_tab.analyze()
    app.processEvents()

    nodo = next(
        n
        for n in _todos_los_nodos(window.editor_tab.current.parse_result.root)
        if n.name.startswith("i2c@")
    )
    window.inspector_panel.show_node(nodo)
    lista = window.inspector_panel._properties
    filas = {
        lista.topLevelItem(i).data(0, Qt.UserRole): lista.topLevelItem(i)
        for i in range(lista.topLevelItemCount())
    }
    assert filas["compatible"].text(2) == "string-array", "la columna es el tipo"
    assert filas["status"].text(2) == "string"
    tipos = [item.text(2) for item in filas.values()]
    assert "<" not in "".join(tipos), "el valor no se repite aquí"

    # La lista es la del **binding**, no la del nodo: `clocks` es
    # obligatoria y este i2c no la escribe, que es justo cuando hay que
    # verla.
    assert "clocks" not in nodo.properties
    assert "clocks" in filas, "las del binding salen aunque no estén escritas"
    assert filas["clocks"].text(1) == "REQUIRED"
    assert filas["status"].text(1) == "OPTIONAL"
    # Y «REQUIRED» en el mismo verde que el «✓ correcto contra el binding»:
    # las dos dicen «esto es lo que el binding pide».
    assert (
        filas["clocks"].foreground(1).color().name()
        == QColor(style.CARD_OK_COLOR).name()
    )
    assert (
        filas["clocks"].foreground(0).color().name()
        == QColor(style.EDITOR_WARNING_ACCENT).name()
    ), "la que falta se marca en el ámbar del aviso de debajo"
    assert (
        filas["compatible"].foreground(0).color().name()
        != QColor(style.EDITOR_WARNING_ACCENT).name()
    ), "la que sí está, no"
    assert "clocks" in window.inspector_panel._missing_label.text()

    # Una propiedad escrita que el binding no declara se marca, en el ámbar
    # del aviso: no es necesariamente un error, pero es lo primero que hay
    # que mirar de la lista.
    nodo.properties["xlnx,invento"] = "<1>"
    window.inspector_panel.show_node(nodo)
    sobra = next(
        lista.topLevelItem(i)
        for i in range(lista.topLevelItemCount())
        if lista.topLevelItem(i).data(0, Qt.UserRole) == "xlnx,invento"
    )
    assert sobra.text(1) == "UNNECESSARY"
    assert (
        sobra.foreground(1).color().name()
        == QColor(style.EDITOR_WARNING_ACCENT).name()
    )
    del nodo.properties["xlnx,invento"]

    # Una propiedad de la especificación (`model`, `status`...) no es "que
    # sobra" aunque este binding no la declare como suya: la exige o no la
    # capa 1 del motor, no el binding del compatible concreto. Marcarla
    # UNNECESSARY aquí contradecía el registro general de diagnósticos, que
    # sí la exige en la raíz (§3.2).
    nodo.properties["model"] = '"Test"'
    window.inspector_panel.show_node(nodo)
    spec_owned = next(
        lista.topLevelItem(i)
        for i in range(lista.topLevelItemCount())
        if lista.topLevelItem(i).data(0, Qt.UserRole) == "model"
    )
    assert spec_owned.text(1) == ""
    del nodo.properties["model"]

    # Sin compatible no hay binding que resolver, y sin binding la ficha no
    # tiene nada propio que decir: se trata igual que "no hay nodo".
    suelto = next(
        n
        for n in _todos_los_nodos(window.editor_tab.current.parse_result.root)
        if n.properties and not n.compatible
    )
    window.inspector_panel.show_node(suelto)
    assert window.inspector_panel._properties.topLevelItemCount() == 0
    assert window.inspector_panel._title.text() != window.inspector_panel.tr(
        "No node"
    ), "el nodo existe, solo le falta compatible"
    window.inspector_panel.show_node(nodo)

    # Y la versión del kernel va dentro de la tarjeta, con su rótulo, no
    # colgada del final de la frase que describe el binding.
    if window.service.binding_since("cdns,i2c-r1p14"):
        assert window.inspector_panel._kernel_row.isVisibleTo(
            window.inspector_panel
        )
        assert "5.8" in window.inspector_panel._kernel_value.text()
        assert "Linux" not in window.inspector_panel._description.text()

    # Pulsar una abre su ficha, en su propia ventana flotante: se lee
    # mientras se escribe, así que no puede ocupar el centro.
    lista.itemClicked.emit(lista.topLevelItem(0), 0)
    app.processEvents()
    assert window.property_panel.isVisible()
    assert window.property_panel.isWindow(), "flota, no es una vista central"
    assert window.tabs.currentIndex() == TAB_EDITOR, "el editor sigue delante"

    window._show_property_panel("compatible", "cdns,i2c-r1p14")
    assert window.property_panel.property_name == "compatible"
    valores = _filas(window.property_panel._values)
    assert "cdns,i2c-r1p14" in valores, "los valores que enumera"


def test_el_inspector_resuelve_una_reapertura_por_label(window, app):
    """El cursor dentro de `&i2c0 { … }` sí encuentra el binding del real.

    El parser cuelga la reapertura de la raíz con el nombre literal
    `&i2c0`, sin `compatible` -el suyo está en el nodo que reabre, en este
    caso en el mismo fichero-. Sin resolverla contra el árbol fusionado
    (`resolve_label_overrides`, lo que ya hace el visualizador) el
    Inspector no encontraba ningún binding para el cursor puesto ahí.
    """
    from PySide6.QtCore import Qt

    texto = (
        "/dts-v1/;\n"
        "/ {\n"
        '\tmodel = "Test Board";\n'
        '\tcompatible = "test,board";\n'
        "\t#address-cells = <1>;\n"
        "\t#size-cells = <1>;\n"
        "\tsoc {\n"
        "\t\t#address-cells = <1>;\n"
        "\t\t#size-cells = <1>;\n"
        "\t\ti2c0: i2c@ff020000 {\n"
        '\t\t\tcompatible = "cdns,i2c-r1p14";\n'
        "\t\t\treg = <0xff020000 0x1000>;\n"
        '\t\t\tstatus = "disabled";\n'
        "\t\t};\n"
        "\t};\n"
        "};\n"
        "\n"
        "&i2c0 {\n"
        '\tstatus = "okay";\n'
        "};\n"
    )
    window.editor_tab.open_source(title="board.dts", text=texto, source_key=None)
    window.editor_tab.analyze()
    app.processEvents()

    document = window.editor_tab.current
    pseudo = next(
        n for n in document.parse_result.root.children if n.name == "&i2c0"
    )
    assert not pseudo.compatible, "la reapertura cruda no trae compatible"

    resuelto = window.service.resolve_inspected_node(
        pseudo, document.parse_result, document.source_key
    )
    assert resuelto is not pseudo
    assert resuelto.compatible == ["cdns,i2c-r1p14"]
    assert resuelto.properties["status"] == '"okay"', "el override manda"

    window.inspector_panel.show_node(resuelto)
    nombres = {
        window.inspector_panel._properties.topLevelItem(i).data(0, Qt.UserRole)
        for i in range(window.inspector_panel._properties.topLevelItemCount())
    }
    assert "clocks" in nombres, "con el compatible resuelto sí sale la ficha"

    # Y lo que el binding acota sin enumerarlo, que es la mayoría: un
    # entero viene con su rango y un array con cuántas entradas admite.
    window._show_property_panel("clock-frequency", "cdns,i2c-r1p14")
    assert any("400000" in fila for fila in _filas(window.property_panel._values))
    window._show_property_panel("reg", "cdns,i2c-r1p14")
    assert _filas(window.property_panel._values), "reg admite exactamente una"

    # Y si no hay ni una cosa ni otra, se dice: la ficha se abre pulsando,
    # así que siempre tiene que responder algo.
    window._show_property_panel("inventada-por-nadie", "cdns,i2c-r1p14")
    assert _filas(window.property_panel._values)

    # Desde qué kernel se puede usar: el único dato de la ficha que no está
    # escrito ni en el fuente ni en el binding. Sale de la historia del
    # repositorio, así que una base construida sin ella no lo trae.
    if window.service.binding_since("cdns,i2c-r1p14"):
        window._show_property_panel("clock-frequency", "cdns,i2c-r1p14")
        assert "Linux" in window.property_panel._subtitle.text()

    # «Find usages» busca en el documento propio, con líneas que existen.
    window.property_panel.findUsagesRequested.emit("status")
    usos = [
        window.property_panel._usages.item(i)
        for i in range(window.property_panel._usages.count())
    ]
    assert usos, "status se usa en toda la zynqmp"
    assert all(isinstance(item.data(Qt.UserRole), int) for item in usos)

    # Y cerrarla la esconde, sin tocar lo que se estaba mirando.
    window.property_panel.closeRequested.emit()
    app.processEvents()
    assert not window.property_panel.isVisible()


def test_el_grafo_no_dibuja_lo_que_esta_apagado(app):
    """`status = "disabled"` es «no está en la máquina», no «está atenuado».

    Un `.dtsi` de SoC declara apagado casi todo lo que integra y la placa
    enciende lo que lleva soldado; encenderlo después —desde la placa, un
    overlay o el diálogo de propiedades— lo devuelve al grafo solo.
    """
    from kernelgrove.dts_engine.parser import parse_dts_source
    from kernelgrove.gui.widgets.tree_graph import build_graph

    fuente = """
    / {
        soc {
            i2c@1 { status = "okay"; rtc@68 { compatible = "dallas,ds1307"; }; };
            i2c@2 { status = "disabled"; rtc@69 { compatible = "x,y"; }; };
        };
    };
    """
    controladores = {"i2c@1", "i2c@2"}
    raiz = parse_dts_source(fuente).root
    # Con un `.dtsi` de SoC por debajo: estos dos i2c los añade la placa, así
    # que son "el resto" y no bloques del SoC —a un bloque, estar apagado no
    # lo esconde, solo lo deja sin color (ver `build_graph`)—.
    next(n for n in _todos_los_nodos(raiz) if n.name == "soc").soc_defined = True

    grafo = build_graph(raiz, controller_names=controladores)
    assert grafo.blocks == []
    assert [hijo.label for hijo in grafo.children] == ["i2c@1"]

    # Y se dice cuántos se han quedado fuera: un grafo con una ficha sola
    # y sin explicación se lee como una avería.
    assert grafo.hidden_disabled == 1

    # Y encenderlo lo devuelve, sin nada más que hacer.
    apagado = next(
        n for n in _todos_los_nodos(raiz) if n.name == "i2c@2"
    )
    apagado.properties["status"] = '"okay"'
    grafo = build_graph(raiz, controller_names=controladores)
    assert sorted(hijo.label for hijo in grafo.children) == ["i2c@1", "i2c@2"]


def test_el_grafo_dibuja_ethernet_can_uart_sin_hijos(app):
    """Ethernet/can/uart/serial son casi siempre hojas: no exigirles hijos.

    El resto de periféricos integrados (un MFD, un UART con su bluetooth)
    solo cuelgan del círculo del SoC si tienen algo conectado dentro; a
    estos cuatro les basta con `status` propio, o quedarían empaquetados
    para siempre.
    """
    from kernelgrove.dts_engine.parser import parse_dts_source
    from kernelgrove.gui.widgets.tree_graph import build_graph

    fuente = """
    / {
        soc {
            ethernet@1 { status = "okay"; };
            can@1 { status = "okay"; };
            uart@1 { status = "okay"; };
            serial@1 { status = "okay"; };
            timer@1 { status = "okay"; };
        };
    };
    """
    raiz = parse_dts_source(fuente).root
    grafo = build_graph(raiz)
    # El fuente no incluye nada, así que el documento *es* el SoC y lo
    # colgante sale como bloques suyos (ver `build_graph`); lo que se
    # comprueba aquí es cuáles pasan el filtro de `is_hoistable`.
    etiquetas = {bloque.label for bloque in grafo.blocks}
    assert etiquetas == {"ethernet@1", "can@1", "uart@1", "serial@1"}
    assert "timer@1" not in etiquetas
    assert grafo.children == []


def test_soc_defined_se_propaga_al_fusionar_includes_y_overrides():
    """Lo que llega por `#include` es "propio del SoC"; lo que añade la placa no.

    `merge_device_tree` reengancha los nodos del `.dtsi` incluido (no los
    copia), así que basta con marcarlos antes de fusionar -lo que hace
    `IncludeResolver._resolved_source`- para que la marca sobreviva. Un
    `&i2c0 { … }` de la placa que reabre ese mismo nodo no le quita la
    marca; un `rtc@68` que ese mismo bloque añade de cero sí se queda sin
    ella, porque nunca estuvo en el `.dtsi`.
    """
    from kernelgrove.dt_model.model import merge_device_tree, resolve_label_overrides
    from kernelgrove.dts_engine.parser import parse_dts_source

    soc_dtsi = parse_dts_source(
        """
        / {
            soc {
                i2c0: i2c@1 { status = "disabled"; };
            };
        };
        """
    ).root
    for nodo in _todos_los_nodos(soc_dtsi):
        nodo.soc_defined = True

    board = parse_dts_source(
        """
        / {
            &i2c0 {
                status = "okay";
                rtc@68 { compatible = "dallas,ds1307"; };
            };
        };
        """
    ).root

    merge_device_tree(board, soc_dtsi)
    resolve_label_overrides(board)

    i2c0 = next(n for n in _todos_los_nodos(board) if n.name == "i2c@1")
    assert i2c0.soc_defined is True
    assert i2c0.properties["status"] == '"okay"'

    rtc = next(n for n in _todos_los_nodos(board) if n.name == "rtc@68")
    assert rtc.soc_defined is False


def test_el_grafo_agrupa_los_controladores_propios_del_soc_como_bloques(app):
    """`soc_defined` -viene del `.dtsi` fusionado- separa "propio" de "el resto".

    Un i2c encendido definido en el `.dtsi` del SoC se dibuja como bloque
    dentro de la ficha central, y lo que cuelga de él sigue siendo una ficha
    aparte con su propia arista, ahora saliendo del bloque. Un bus que la
    propia placa añade -no viene de ningún `.dtsi`, como un puente SPI por
    GPIO- sigue colgando aparte como "el resto".
    """
    from kernelgrove.dts_engine.parser import parse_dts_source
    from kernelgrove.gui.widgets.tree_graph import build_graph

    fuente = """
    / {
        soc {
            i2c0: i2c@1 { status = "okay"; rtc@68 { compatible = "dallas,ds1307"; }; };
            i2c1: i2c@2 { status = "disabled"; };
            spi-gpio@0 { status = "okay"; };
        };
    };
    """
    raiz = parse_dts_source(fuente).root
    for nodo in _todos_los_nodos(raiz):
        nodo.soc_defined = nodo.name != "spi-gpio@0"

    grafo = build_graph(raiz, controller_names={"i2c@1", "i2c@2", "spi-gpio@0"})
    grafo.collapsed = False

    bloques = {b.label: b for b in grafo.blocks}
    # El i2c@2 del SoC está apagado: no es un bloque, se cuenta en el aviso.
    assert set(bloques) == {"i2c@1"}
    assert [hijo.label for hijo in bloques["i2c@1"].children] == ["rtc@68"]
    assert grafo.hidden_disabled == 1

    assert [hijo.label for hijo in grafo.children] == ["spi-gpio@0"]


def test_abrir_el_dtsi_del_soc_tambien_da_bloques(app):
    """Si nada viene de un include, el documento *es* el SoC: todo es suyo.

    `IncludeResolver` solo marca `soc_defined` sobre lo que fusiona, así que
    abriendo el `.dtsi` de un SoC directamente -la ruta normal desde el
    catálogo- no había nada marcado y no salía un solo bloque.
    """
    from kernelgrove.dts_engine.parser import parse_dts_source
    from kernelgrove.gui.widgets.tree_graph import build_graph

    fuente = """
    / {
        soc {
            i2c@1 { status = "okay"; };
            i2c@2 { status = "disabled"; };
        };
    };
    """
    raiz = parse_dts_source(fuente).root
    assert not any(n.soc_defined for n in _todos_los_nodos(raiz))

    grafo = build_graph(raiz, controller_names={"i2c@1", "i2c@2"})
    assert [b.label for b in grafo.blocks] == ["i2c@1"]
    assert grafo.children == []


def test_solo_los_controladores_encendidos_son_bloques_del_soc(app):
    """De fábrica no hay bloques; van apareciendo según se encienden.

    Un `.dtsi` de SoC trae apagado casi todo lo que integra, y a un bus
    apagado no se le conecta nada. Así que la ficha del SoC nace vacía y
    cada controlador aparece al encenderlo desde su panel de propiedades;
    mientras tanto se cuentan en el aviso de «apagados», que es lo que manda
    a ese panel.
    """
    from kernelgrove.dts_engine.parser import parse_dts_source
    from kernelgrove.gui.widgets.tree_graph import build_graph

    fuente = """
    / {
        soc {
            i2c@1 { status = "disabled"; };
            i2c@2 { status = "disabled"; };
            spi@3 { status = "disabled"; };
        };
    };
    """
    raiz = parse_dts_source(fuente).root
    controladores = {"i2c@1", "i2c@2", "spi@3"}

    grafo = build_graph(raiz, controller_names=controladores)
    assert grafo.blocks == []
    assert grafo.hidden_disabled == 3

    # Encender uno -lo que hace el panel de propiedades del SoC, escribiendo
    # un `&label { status = "okay"; }`- lo trae al grafo sin nada más.
    next(n for n in _todos_los_nodos(raiz) if n.name == "i2c@1").properties[
        "status"
    ] = '"okay"'

    grafo = build_graph(raiz, controller_names=controladores)
    assert [b.label for b in grafo.blocks] == ["i2c@1"]
    assert grafo.hidden_disabled == 2


def test_las_propiedades_de_una_ficha_van_siempre_en_el_mismo_orden(app):
    """`compatible`, `reg`, `status` y luego alfabético, no el orden del fuente.

    La ficha solo enseña unas pocas filas: por el orden en que están
    escritas, `reg` salía a una altura distinta en cada nodo y no se podían
    comparar dos de un vistazo.
    """
    from kernelgrove.gui.widgets.tree_graph import property_rows

    filas = property_rows(
        {
            "vcc-supply": "<&ldo4_reg>",
            "status": '"okay"',
            "#address-cells": "<1>",
            "reg": "<0x54>",
            "compatible": '"atmel,24c256"',
            "wakeup-source": True,
        }
    )

    assert [nombre for nombre, _ in filas] == [
        "compatible",
        "reg",
        "status",
        "#address-cells",
        "vcc-supply",
        "wakeup-source",
    ]
    # Y el valor sigue llegando pelado, sin `<>` ni comillas; una bandera se
    # queda sin valor, que es justo lo que es.
    assert dict(filas)["reg"] == "0x54"
    assert dict(filas)["compatible"] == "atmel,24c256"
    assert dict(filas)["wakeup-source"] == ""


def test_cada_nodo_ofrece_verlo_en_el_editor(app):
    """La opción está tanto en una ficha como en un bloque, y lleva su ruta.

    Un bloque es el mismo nodo dibujado dentro de la ficha del SoC, así que
    ofrece lo mismo. Se emiten ruta y etiqueta porque el documento abierto
    puede escribirlo de dos formas -el nodo entero o un `&etiqueta { … }`-.
    """
    from kernelgrove.gui.widgets.tree_graph import (
        GraphNode,
        TreeGraphView,
        _node_menu_actions,
        _run_node_action,
    )
    from PySide6.QtWidgets import QMenu

    vista = TreeGraphView()
    pedidos = []
    vista.nodeSourceRequested.connect(lambda p, e: pedidos.append((p, e)))

    nodo = GraphNode(label="i2c@ff030000", path="axi/i2c@ff030000", dt_label="i2c1")
    menu = QMenu()
    inspeccionar, ver_fuente = _node_menu_actions(menu, nodo)
    assert [a.text() for a in menu.actions()] == [
        "Open inspector",
        "View on DTS editor",
    ]

    _run_node_action(vista, nodo, ver_fuente, inspeccionar, ver_fuente)
    assert pedidos == [("axi/i2c@ff030000", "i2c1")]

    # Un nodo que no está escrito en ningún sitio -el paquete de includes,
    # una rama recortada- no tiene ruta y no se le ofrece nada.
    suelto = QMenu()
    assert _node_menu_actions(suelto, GraphNode(label="includes not found")) == (
        None,
        None,
    )
    assert suelto.actions() == []


def test_el_grafo_solo_dibuja_dispositivos_no_configuracion(app):
    """Un nodo sin `compatible` no es hardware: es configuración.

    Un device tree usa nodos para las dos cosas. `uart1-default` es un grupo
    de pines del pinctrl y `ports` un contenedor del binding de grafo:
    ninguno declara un binding, y el zcu100 sacaba diez de esos colgando de
    su pinctrl. Pero un contenedor sin compatible puede ser el camino hasta
    un dispositivo -los canales de un mux I2C son `i2c@N` pelados-, así que
    se poda el subárbol solo cuando no hay ningún compatible debajo.
    """
    from kernelgrove.dts_engine.parser import parse_dts_source
    from kernelgrove.gui.widgets.tree_graph import build_graph

    fuente = """
    / {
        soc {
            pinctrl@ff180000 {
                compatible = "xlnx,zynqmp-pinctrl";
                status = "okay";
                uart1-default { mux { function = "uart1"; }; };
                usb1-default { mux { function = "usb1"; }; };
            };
            i2c@ff030000 {
                status = "okay";
                i2c-mux@75 {
                    compatible = "nxp,pca9548";
                    i2c@4 { pmic@5e { compatible = "ti,tps65086"; }; };
                    i2c@6 { };
                };
            };
        };
    };
    """
    raiz = parse_dts_source(fuente).root
    grafo = build_graph(
        raiz,
        controller_names={"i2c@ff030000"},
        initial_depth=9,
    )

    bloques = {b.short_label: b for b in grafo.blocks}
    # El pinctrl es un dispositivo de verdad y se queda; sus grupos de pines
    # no, y con ellos no queda nada colgando.
    assert bloques["pinctrl"].children == []

    # El mux sí, y con él el canal que lleva a algo -pero no el que está
    # vacío, que es solo direccionamiento-.
    mux = bloques["i2c"].children[0]
    assert mux.label == "i2c-mux@75"
    assert [c.label for c in mux.children] == ["i2c@4"]
    assert [c.label for c in mux.children[0].children] == ["pmic@5e"]

    # Y nada de esto se cuenta como apagado: no están porque no son
    # dispositivos, no porque estén desactivados.
    assert grafo.hidden_disabled == 0


def test_los_bloques_repetidos_se_numeran_por_su_reg(app):
    """`i2c0`/`i2c2`, el número del fabricante, no el de la lista.

    Con la dirección fuera del bloque, tres `i2c` seguidos se leen igual. Se
    numeran por su dirección de unidad -la base de su `reg`- contando
    **también los apagados**: un am335x trae tres y la placa enciende el
    primero y el tercero, que son su I2C0 y su I2C2. Numerando solo lo
    visible saldrían `i2c0` e `i2c1`, que es un chip que no existe.
    """
    from kernelgrove.dts_engine.parser import parse_dts_source
    from kernelgrove.gui.widgets.tree_graph import build_graph

    fuente = """
    / {
        soc {
            i2c@44e0b000 { status = "okay"; };
            i2c@4802a000 { status = "disabled"; };
            i2c@4819c000 { status = "okay"; };
            ethernet@4a100000 { status = "okay"; };
        };
    };
    """
    raiz = parse_dts_source(fuente).root
    grafo = build_graph(
        raiz,
        controller_names={"i2c@44e0b000", "i2c@4802a000", "i2c@4819c000"},
    )

    assert [b.short_label for b in grafo.blocks] == ["i2c0", "i2c2", "ethernet"]
    # El `ethernet` no comparte nombre con nadie: sin número, no hay de qué
    # distinguirlo.
    assert grafo.blocks[-1].label == "ethernet@4a100000"


def test_se_pueden_conectar_dispositivos_soltandolos_en_un_bloque(app):
    """El bloque sigue siendo un controlador: acepta que le suelten encima.

    Meter los controladores dentro de la ficha del SoC no puede costar la
    forma de conectarles cosas, que es arrastrar un compatible de la paleta
    hasta ellos.
    """
    from PySide6.QtCore import QMimeData

    from kernelgrove.gui.widgets.tree_graph import (
        GraphNode,
        TreeGraphView,
        _BlockChip,
    )

    class _SlotFalso:
        pass

    slot = _SlotFalso()
    raiz = GraphNode(label="soc", is_root=True, collapsed=False)
    raiz.blocks = [
        GraphNode(label="i2c@1", path="soc/i2c@1", slot=slot),
        GraphNode(label="rtc@2", path="soc/rtc@2"),
    ]

    vista = TreeGraphView()
    vista.drop_validator = lambda destino, compatible: (
        destino is slot and compatible == "dallas,ds1307"
    )
    vista.resize(600, 400)
    vista.show_graph(raiz)
    app.processEvents()

    chips = {
        c.node.label: c
        for c in vista.scene().items()
        if isinstance(c, _BlockChip)
    }
    assert chips["i2c@1"].acceptDrops()
    # Sin slot no hay nada que conectar, así que no se acepta el arrastre.
    assert not chips["rtc@2"].acceptDrops()

    class _EventoFalso:
        def __init__(self, texto):
            self._mime = QMimeData()
            self._mime.setText(texto)
            self.aceptado = False

        # Nombres en camelCase porque imitan la API de Qt, igual que el resto
        # de la GUI (por eso `src/kernelgrove/gui/**` ignora N802).
        def mimeData(self):  # noqa: N802
            return self._mime

        def acceptProposedAction(self):  # noqa: N802
            self.aceptado = True

        def ignore(self):
            pass

    soltados = []
    vista.deviceDropped.connect(lambda destino, compatible: soltados.append(compatible))

    evento = _EventoFalso("dallas,ds1307")
    chips["i2c@1"].dropEvent(evento)
    assert evento.aceptado
    assert soltados == ["dallas,ds1307"]

    # Y un compatible que el validador rechaza no conecta nada.
    rechazado = _EventoFalso("no,vale")
    chips["i2c@1"].dropEvent(rechazado)
    assert not rechazado.aceptado
    assert soltados == ["dallas,ds1307"]


def test_un_dispositivo_conectado_se_puede_quitar_aunque_no_aloje_nada(app):
    """`connected_slot` es el slot que el nodo *es*, no sobre el que se suelta.

    Mientras fueron el mismo campo, solo lo tenían los que aceptan hijos (un
    mux, un MFD): una EEPROM conectada se quedaba sin él y el menú no ofrecía
    quitarla, así que no había forma de deshacer la conexión desde el grafo.
    """
    from kernelgrove.gui.widgets.tree_graph import GraphNode, build_graph

    class _Descriptor:
        path = "soc/i2c@1"
        compatibles = ("atmel,24c256",)
        child_bus = None

    class _SlotHoja:
        """Un dispositivo conectado que no aloja nada, como una EEPROM."""

        descriptor = _Descriptor()
        display_name = "atmel,24c256"
        is_bus = False
        accepts_children = False
        children = ()

    from kernelgrove.dts_engine.parser import parse_dts_source

    fuente = '/ { soc { i2c@1 { status = "okay"; }; }; };'
    raiz = parse_dts_source(fuente).root

    class _SlotRaiz(_SlotHoja):
        descriptor = _Descriptor()
        children = (_SlotHoja(),)
        accepts_children = True
        is_bus = True

    grafo = build_graph(
        raiz, controller_names={"i2c@1"}, root_slots=[_SlotRaiz()]
    )
    conectado = grafo.blocks[0].children[0]

    assert conectado.generated
    # No admite hijos, así que no es destino de arrastre...
    assert conectado.slot is None
    # ...pero sí se sabe qué slot es, que es lo que permite quitarlo.
    assert conectado.connected_slot is not None

    # Y su identidad para conservar el plegado sale de ese mismo slot, no de
    # su etiqueta, que puede repetirse entre dos dispositivos iguales.
    from kernelgrove.gui.widgets.tree_graph import _collapse_key

    assert _collapse_key(conectado) == id(conectado.connected_slot)
    assert _collapse_key(GraphNode(label="x")) == "x"


def test_supr_quita_del_grafo_el_dispositivo_seleccionado(app):
    """Borrar algo seleccionado se intenta con la tecla antes que con el menú.

    Y solo se quita lo conectado desde la sesión de edición: un nodo escrito
    en el `.dts` no se quita del grafo, se quita del fuente.
    """
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    from kernelgrove.gui.widgets.tree_graph import GraphNode, TreeGraphView

    class _Slot:
        pass

    slot = _Slot()
    raiz = GraphNode(label="soc", is_root=True, collapsed=False)
    conectado = GraphNode(label="rtc@68", generated=True, connected_slot=slot)
    real = GraphNode(label="eeprom@50", path="soc/i2c@1/eeprom@50")
    raiz.blocks = [
        GraphNode(label="i2c@1", path="soc/i2c@1", children=[conectado, real])
    ]

    vista = TreeGraphView()
    vista.resize(600, 400)
    vista.show_graph(raiz)
    app.processEvents()

    quitados = []
    vista.deviceRemoved.connect(quitados.append)

    def pulsar_supr():
        vista.keyPressEvent(
            QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier)
        )

    # Sin nada seleccionado no se quita nada.
    pulsar_supr()
    assert quitados == []

    # Un nodo real tampoco: no es del grafo, es del fuente.
    vista._items[id(real)].setSelected(True)
    pulsar_supr()
    assert quitados == []

    vista._items[id(real)].setSelected(False)
    vista._items[id(conectado)].setSelected(True)
    pulsar_supr()
    assert quitados == [slot]


def test_las_ventanas_del_grafo_no_bloquean_la_aplicacion(window, app):
    """El panel del SoC y el Inspector se comportan como `PropertyPanel`.

    Se consultan *mientras* se mira el grafo o se edita el fuente, así que
    son ventanas sueltas y no modales que se pueden mover y dejar a un lado,
    no diálogos que bloqueen hasta cerrarlos. Y se reutiliza la misma en vez
    de apilar una por cada vez que se abren.
    """
    from PySide6.QtCore import Qt

    from kernelgrove.dts_engine.parser import parse_dts_source

    fuente = '/ { compatible = "x,y"; soc { i2c@1 { status = "okay"; }; }; };'
    window._current_merged_root = parse_dts_source(fuente).root
    window._current_soc_compatible = "x,y"

    window._open_soc_properties()
    app.processEvents()
    soc = window._soc_dialog
    assert soc is not None and soc.isVisible()
    assert not soc.isModal(), "no puede bloquear el resto de la ventana"
    assert soc.windowFlags() & Qt.Tool

    window._open_node_inspector("soc/i2c@1")
    app.processEvents()
    inspector = window._inspector_dialog
    assert inspector is not None and inspector.isVisible()
    assert not inspector.isModal()
    assert inspector.windowFlags() & Qt.Tool

    # Volver a abrirlas no crea otra ventana encima.
    window._open_soc_properties()
    window._open_node_inspector("soc/i2c@1")
    app.processEvents()
    assert window._soc_dialog is soc
    assert window._inspector_dialog is inspector

    soc.close()
    inspector.close()


def test_pasar_el_raton_enciende_la_conexion_con_su_controlador(app):
    """Con veinte bloques en la ficha del SoC, la arista sola no dice de cuál sale.

    Al señalar cualquiera de los dos extremos se encienden los tres a la vez
    -bloque, arista y ficha- y la arista sube por encima de las demás, que si
    no le pasan por delante.
    """
    from kernelgrove.gui.widgets.tree_graph import GraphNode, TreeGraphView

    raiz = GraphNode(label="soc", is_root=True, collapsed=False)
    hijo = GraphNode(label="rtc@68", path="soc/i2c@1/rtc@68")
    raiz.blocks = [
        GraphNode(label="i2c@1", path="soc/i2c@1", children=[hijo]),
        GraphNode(label="spi@2", path="soc/spi@2"),
    ]

    vista = TreeGraphView()
    vista.resize(600, 400)
    vista.show_graph(raiz)
    app.processEvents()

    assert len(vista._links) == 1
    arista, bloque, colgado = vista._links[0]
    chip = vista._chips[id(bloque)]
    ficha = vista._items[id(colgado)]
    grosor_arista = arista.pen().widthF()
    grosor_chip = chip.pen().widthF()

    # Señalando el hijo se enciende el controlador del que cuelga...
    vista.highlight_link(colgado, True)
    assert arista.pen().widthF() > grosor_arista
    assert arista.zValue() == 0, "por encima de las demás aristas"
    assert chip.pen().widthF() > grosor_chip

    vista.highlight_link(colgado, False)
    assert arista.pen().widthF() == grosor_arista
    assert arista.zValue() == -1

    # ...y desde el bloque funciona igual: la pregunta se hace en las dos
    # direcciones.
    vista.highlight_link(bloque, True)
    assert ficha.pen().widthF() > 1.2

    # Un bloque sin nada colgando no enciende nada, y no falla.
    vista.highlight_link(raiz.blocks[1], True)


def test_las_fichas_hijas_no_se_solapan_con_la_del_soc(app):
    """Una ficha alta no puede comerse a sus hijos.

    `GRAPH_VERTICAL_GAP` mide de centro a centro, y con la ficha del SoC
    llena de bloques (más de 380px de alto) los hijos, colocados 150px más
    abajo, le caían encima. `_measure_levels` separa los niveles por el alto
    real de cada uno.
    """
    from kernelgrove.gui.widgets.tree_graph import (
        GraphNode,
        TreeGraphView,
        _NodeItem,
    )

    raiz = GraphNode(label="soc", is_root=True, collapsed=False)
    raiz.blocks = [
        GraphNode(label=f"i2c@{i}", children=[GraphNode(label=f"rtc@{i}")])
        for i in range(12)
    ]

    vista = TreeGraphView()
    vista.resize(800, 600)
    vista.show_graph(raiz)
    app.processEvents()

    fichas = [i for i in vista.scene().items() if isinstance(i, _NodeItem)]
    ficha_soc = next(i for i in fichas if i.node.is_root)
    caja_soc = ficha_soc.sceneBoundingRect()
    assert len(fichas) == 13  # el SoC y los doce dispositivos conectados

    for ficha in fichas:
        if ficha is ficha_soc:
            continue
        assert not caja_soc.intersects(ficha.sceneBoundingRect()), (
            f"{ficha.node.label} se solapa con la ficha del SoC"
        )


def test_el_arbol_de_carpetas_enseña_el_estado_de_git(window, app, tmp_path):
    """Como en VS Code: el color dice qué le pasa y la letra dice cuál es.

    Y la carpeta que contiene algo cambiado se tiñe también, sin letra: en
    un proyecto que guarda sus overlays en `overlays/` no se vería nada
    hasta desplegarla.
    """
    import subprocess

    from PySide6.QtGui import QColor

    from kernelgrove.api import git_repo

    if not git_repo.git_available():
        pytest.skip("git no está instalado")

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for name, valor in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(tmp_path), "config", name, valor], check=True)
    (tmp_path / "overlays").mkdir()
    (tmp_path / "tocado.dts").write_text("/ { };", encoding="utf-8")
    (tmp_path / "intacto.dts").write_text("/ { };", encoding="utf-8")
    (tmp_path / "overlays" / "dentro.dtso").write_text("a", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "uno"], check=True)
    (tmp_path / "tocado.dts").write_text("/ { model = \"x\"; };", encoding="utf-8")
    (tmp_path / "overlays" / "dentro.dtso").write_text("b", encoding="utf-8")
    (tmp_path / "nuevo.dtso").write_text("/plugin/;", encoding="utf-8")

    window.git_panel.set_root(tmp_path)
    estados = window.git_panel.file_status()
    assert estados[str(tmp_path / "tocado.dts")] == "M"
    assert estados[str(tmp_path / "nuevo.dtso")] == "?"
    assert str(tmp_path / "intacto.dts") not in estados

    window.explorer_panel.set_root(tmp_path)
    window.explorer_panel.set_git_status(estados)
    app.processEvents()
    delegado = window.explorer_panel._git_delegate
    modelo = window.explorer_panel._model

    def color(ruta):
        c = delegado._color_for(modelo.index(str(ruta)))
        return c.name() if c is not None else None

    assert color(tmp_path / "tocado.dts") == QColor(style.GIT_STATUS_COLORS["M"]).name()
    assert color(tmp_path / "nuevo.dtso") == QColor(style.GIT_STATUS_COLORS["?"]).name()
    assert color(tmp_path / "intacto.dts") is None
    # La carpeta hereda el color de lo que lleva dentro, pero no la letra.
    assert color(tmp_path / "overlays") is not None
    assert delegado._status_for(modelo.index(str(tmp_path / "overlays"))) is None

    # Lo nuevo es verde y lo cambiado ámbar, no al revés.
    assert style.GIT_STATUS_COLORS["?"] != style.GIT_STATUS_COLORS["M"]


def test_los_iconos_se_dibujan_y_siguen_al_color_activo(app):
    """Están todos y no salen en blanco: se dibujan, no vienen de un fichero.

    Un `QIcon` vacío no da error en ninguna parte —el botón sale sin icono y
    ya—, así que lo que hay que comprobar es que cada pixmap tiene algo
    pintado dentro.
    """
    from kernelgrove.gui.widgets import icons

    dibujables = (
        icons.folder_icon,
        icons.tree_icon,
        icons.branch_icon,
        icons.layers_icon,
        icons.database_icon,
        icons.list_icon,
        icons.chip_icon,
        icons.board_icon,
        icons.search_icon,
        icons.split_icon,
        icons.error_icon,
        icons.warning_icon,
        icons.cable_icon,
        icons.plus_icon,
        icons.minus_icon,
        icons.fit_icon,
        icons.build_icon,
        icons.unarchive_icon,
        icons.document_icon,
    )
    for draw in dibujables:
        pixmap = draw(22, "#ffffff").pixmap(22, 22)
        assert not pixmap.isNull(), draw.__name__
        imagen = pixmap.toImage()
        pintados = sum(
            imagen.pixelColor(x, y).alpha() > 0
            for x in range(imagen.width())
            for y in range(imagen.height())
        )
        assert pintados > 10, f"{draw.__name__} sale vacío"

    # Y el color es el que se pide, no uno fijo: los de la franja de estado
    # se repintan al cambiar de piel.
    claro = icons.split_icon(22, "#ffffff").pixmap(22, 22).toImage()
    oscuro = icons.split_icon(22, "#000000").pixmap(22, 22).toImage()
    assert claro != oscuro


def test_la_franja_de_iconos_elige_panel_y_no_toca_el_centro(window):
    """Una sección elige **panel**. Lo que hay en el centro no lo toca.

    Es lo que hacía antes y era el mayor tropiezo de la navegación: abrir
    Carpetas mientras se miraba el grafo devolvía al texto, y mirar la
    estructura desde el texto saltaba al grafo. Quien alterna entre las dos
    formas de ver el documento es el pie del panel, y solo él. La única
    sección con vista propia es la lista de conexiones, que no es un panel
    sino una tabla a todo lo ancho.
    """
    from kernelgrove.gui.main_window import (
        SECTION_CONNECTIONS,
        SECTION_DATABASE,
        SECTION_FOLDERS,
        SECTION_OVERLAY,
        SECTION_VERSIONS,
        TAB_EDITOR,
        TAB_GENERATOR,
        TAB_VISUALIZER,
    )

    assert window.tabs.tabBar().isHidden(), "la fila de pestañas ya no navega"

    # Desde el texto, ninguna sección de panel se lleva el centro.
    window.show_view(TAB_EDITOR)
    for section in (SECTION_VERSIONS, SECTION_OVERLAY, SECTION_FOLDERS):
        window.activity_bar.show_section(section)
        assert window.tabs.currentIndex() == TAB_EDITOR

    # Y desde el grafo, tampoco.
    window.show_view(TAB_VISUALIZER)
    for section in (SECTION_FOLDERS, SECTION_VERSIONS, SECTION_OVERLAY):
        window.activity_bar.show_section(section)
        assert window.tabs.currentIndex() == TAB_VISUALIZER
        # Y el inspector sigue a la vista: fuera del editor no tiene nodo.
        assert window.inspector_dock.isHidden()

    # La lista de conexiones sí es una vista, y se lee a todo lo ancho.
    window.activity_bar.show_section(SECTION_CONNECTIONS)
    assert window.tabs.currentIndex() == TAB_GENERATOR
    assert window._left_panel_column.isHidden()

    # Y volver a un panel devuelve a **la forma en que se estaba mirando el
    # documento**, que aquí era el grafo: el panel se abriría al lado de una
    # tabla que lo tapa.
    window.activity_bar.show_section(SECTION_VERSIONS)
    assert window.tabs.currentIndex() == TAB_VISUALIZER
    assert not window._left_panel_column.isHidden()

    # El catálogo no es una sección: es una ventana que se abre encima. Ni
    # mueve el centro, ni cambia el panel, ni deja su icono marcado.
    window.activity_bar.show_section(SECTION_FOLDERS)
    window.show_view(TAB_EDITOR)
    window.activity_bar.show_section(SECTION_DATABASE)
    assert window.tabs.currentIndex() == TAB_EDITOR
    assert window._current_section == SECTION_FOLDERS
    assert not window.database_tab.isHidden()
    window.database_tab.hide()

    # Y ninguna sección se llama igual que otra.
    assert len(set(window._left_sections)) == len(window._left_sections)

def test_los_paneles_laterales_comparten_hueco_y_no_cambian_de_vista(window, app):
    """Cuatro paneles en un hueco, no cuatro ventanas.

    Dos cosas que se notaban al usarlo: el hueco daba un salto de ancho al
    entrar en Overlays y otro al salir, deshaciendo lo que se hubiera
    ajustado a mano; y abrir el control de código estando en el grafo te
    devolvía al editor, con lo que había que volver atrás cada vez.
    """
    from PySide6.QtCore import Qt

    from kernelgrove.gui.main_window import (
        LEFT_DOCK_WIDTH,
        SECTION_CONNECTIONS,
        SECTION_FOLDERS,
        SECTION_OVERLAY,
        SECTION_VERSIONS,
        TAB_EDITOR,
        TAB_VISUALIZER,
    )

    # Un panel es un panel: desde el grafo, ninguna sección de panel mueve
    # el centro. Quien alterna texto y grafo es el pie del panel.
    window.show_view(TAB_VISUALIZER)
    for section in (SECTION_VERSIONS, SECTION_OVERLAY, SECTION_FOLDERS):
        window.activity_bar.show_section(section)
        assert window.tabs.currentIndex() == TAB_VISUALIZER, (
            "cambiar de panel no puede cambiar de ventana"
        )
        # Y el inspector sigue la vista de verdad, no el destino de la
        # sección: fuera del editor no tiene nodo que enseñar.
        assert window.inspector_dock.isHidden()

    # Desde una vista que se lee a todo lo ancho sí hay que volver, y se
    # vuelve a **como se estaba mirando el documento**: aquí, el grafo.
    window.activity_bar.show_section(SECTION_CONNECTIONS)
    window.activity_bar.show_section(SECTION_VERSIONS)
    assert window.tabs.currentIndex() == TAB_VISUALIZER
    window.show_view(TAB_EDITOR)

    # El ancho es del hueco. Hace falta la ventana enseñada: el ancho que se
    # recuerda es el que tiene el dock de verdad, y sin mostrarla no lo tiene.
    window.resize(1400, 900)
    window.show()
    try:
        app.processEvents()
        window.activity_bar.show_section(SECTION_FOLDERS)
        app.processEvents()
        window.resizeDocks([window.left_dock], [520], Qt.Horizontal)
        app.processEvents()
        ajustado = window.left_dock.width()
        assert ajustado > LEFT_DOCK_WIDTH, "la prueba no llegó a ensanchar nada"
        for section in (SECTION_OVERLAY, SECTION_VERSIONS, SECTION_FOLDERS):
            window.activity_bar.show_section(section)
            app.processEvents()
            assert window.left_dock.width() == ajustado
    finally:
        window.hide()


def test_la_paleta_de_comandos_busca_ficheros_vistas_y_catalogo(window, app):
    """Un solo sitio donde escribir a dónde ir, y filtra sobre las tres cosas."""
    from kernelgrove.gui.widgets.command_palette import MAX_RESULTS, CommandPalette

    window.editor_tab.open_source("zynq-7000.dtsi", "/ { };")
    entries = window._palette_entries()
    categorias = {entry.category for entry in entries}
    assert len(entries) > len(window.socs), "el catálogo entero entra en la paleta"

    palette = CommandPalette(entries, window)
    # Sin filtro se corta: miles de filas no se recorren, se escriben dos
    # letras más.
    assert palette.results.count() == MAX_RESULTS

    palette._refill("zynq-7000")
    titulos = [
        palette.results.item(row).text() for row in range(palette.results.count())
    ]
    assert "zynq-7000.dtsi" in titulos, "el fichero abierto"
    assert any(t.startswith("zynq-7000 (") for t in titulos), "el SoC del catálogo"

    palette._refill("no-existe-este-cacharro")
    assert palette.results.count() == 0

    # Y ejecutar una entrada cierra la paleta antes de hacer nada: la acción
    # puede abrir otro diálogo y quedaría detrás del modal.
    palette._refill("")
    hechos = []
    from kernelgrove.gui.widgets.command_palette import PaletteEntry

    marcador = PaletteEntry("marca", "test", lambda: hechos.append(True))
    palette._entries = [marcador]
    palette._refill("marca")
    palette._run(palette.results.item(0))
    assert hechos == [True]
    assert palette.result() == CommandPalette.Accepted, "se cierra antes de actuar"
    assert categorias, "cada entrada dice de qué es"
    palette.deleteLater()


def test_el_explorador_de_la_base_lista_y_filtra_el_catalogo(window, app):
    """El catálogo entero en una lista, y elegir abre igual por los dos lados.

    Los dos desplegables ya no están encima de las vistas sino aquí, y
    siguen haciendo lo mismo; lo que se añade es la lista, que hace lo mismo
    con doble clic. Por eso ambas rutas terminan en la misma señal.
    """
    from kernelgrove.gui.tabs.database_tab import KIND_BOARD, KIND_SOC, entry_ref

    tab = window.database_tab
    # Es una ventana flotante, no una de las vistas centrales.
    assert tab not in [window.tabs.widget(i) for i in range(window.tabs.count())]
    assert tab.isWindow()
    assert not hasattr(window, "soc_combo"), "los combos son de la pestaña"

    total = len(window.socs) + len(window.boards)
    assert tab.entries.count() == total

    def visibles():
        return [
            tab.entries.item(row)
            for row in range(tab.entries.count())
            if not tab.entries.item(row).isHidden()
        ]

    # La ficha enseña el hardware, no la ruta del fichero: eso está en el
    # tooltip. Y sus dos botones caen dentro de ella y no se pisan, que es
    # lo único que el delegado no puede comprobar por su cuenta.
    from PySide6.QtCore import QRectF

    from kernelgrove.gui.tabs.database_tab import card_layout

    caja = card_layout(QRectF(0, 0, 900, style.DB_CARD_HEIGHT))
    assert not caja["load"].intersects(caja["graph"])
    assert QRectF(0, 0, 900, style.DB_CARD_HEIGHT).contains(caja["load"])
    assert QRectF(0, 0, 900, style.DB_CARD_HEIGHT).contains(caja["graph"])
    assert caja["clock"].right() <= caja["load"].left()

    tab.search.setText("zynq-7000")
    encontrados = visibles()
    assert 0 < len(encontrados) < total
    assert any(item.text() == "zynq-7000" for item in encontrados)
    # No busca solo por el título: también por el compatible, el fabricante
    # y la ruta del fichero, que es la mitad de para qué sirve un buscador
    # sobre un catálogo -y por eso entre los resultados hay entradas cuyo
    # nombre no contiene lo buscado.
    tab.search.setText("xilinx/zynq-7000.dtsi")
    assert visibles(), "no busca por la ruta del fichero"
    tab.search.setText("no-existe-este-cacharro")
    assert not visibles()

    tab.search.setText("")
    assert len(visibles()) == total

    # Y las dos rutas abren: el doble clic en la ficha emite lo mismo que
    # elegir en el desplegable.
    recibidos = []
    tab.socChosen.connect(recibidos.append)
    soc = next(
        tab.entries.item(row)
        for row in range(tab.entries.count())
        if entry_ref(tab.entries.item(row))[0] == KIND_SOC
    )
    tab.entries.itemActivated.emit(soc)
    assert recibidos == [entry_ref(soc)[1]]

    # Una board se distingue de un SoC en la ficha, que es lo que dice con
    # qué lector de la base se abre.
    assert any(
        entry_ref(tab.entries.item(row))[0] == KIND_BOARD
        for row in range(tab.entries.count())
    )


def test_los_dos_botones_de_una_ficha_se_senalan_solos(window, app):
    """Pasar por encima de la ficha no señala sus botones; solo el botón.

    Los pinta el delegado, así que no hay widget que responda al ratón por
    su cuenta y el señalado es un dato suyo. El caso que importa es el
    tercero: el ratón sobre la ficha, fuera de los dos botones, con la fila
    entera señalada -que era lo que teñía los botones de camino y hacía
    parecer que se activaban sin estar el ratón encima.
    """
    from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
    from PySide6.QtGui import QMouseEvent

    from kernelgrove.gui.tabs.database_tab import card_layout

    tab = window.database_tab
    # La lista no se llega a mostrar en las pruebas, así que se le da tamaño:
    # `visualItemRect` es lo que traduce fila a píxeles, aquí y al pintar.
    tab.entries.resize(900, 600)
    app.processEvents()
    caja = card_layout(QRectF(tab.entries.visualItemRect(tab.entries.item(0))))

    def mover(punto):
        tab.eventFilter(
            tab.entries.viewport(),
            QMouseEvent(
                QEvent.MouseMove,
                punto,
                tab.entries.viewport().mapToGlobal(punto),
                Qt.NoButton,
                Qt.NoButton,
                Qt.NoModifier,
            ),
        )

    for clave in ("load", "graph"):
        mover(caja[clave].center())
        assert tab._delegate.hovered == (0, clave)
        # La mano dice que eso se pulsa.
        assert tab.entries.viewport().cursor().shape() == Qt.PointingHandCursor

    # Sobre la ficha pero fuera de los botones: ninguno señalado.
    mover(QPointF(caja["description"].center()))
    assert tab._delegate.hovered is None
    assert tab.entries.viewport().cursor().shape() == Qt.ArrowCursor

    # Y salir de la lista lo apaga.
    mover(caja["load"].center())
    assert tab._delegate.hovered is not None
    tab.eventFilter(tab.entries.viewport(), QEvent(QEvent.Leave))
    assert tab._delegate.hovered is None

    # El botón de borde se pinta con el fondo de la ficha **sin** señalar,
    # que es lo que lo desengancha del señalado de la fila.
    assert style.DB_CARD_BUTTON_HOVER_BG != style.DB_CARD_BG
    assert style.DB_CARD_HOVER_BG != style.DB_CARD_BUTTON_HOVER_BG


def test_el_catalogo_tiene_un_buscador_y_cinco_filtros(window, app):
    """Un sitio donde buscar y cinco listas donde estrechar.

    Antes había tres cajas de texto —el buscador y dos desplegables
    editables, cada uno sobre su mitad del catálogo— y no se sabía en cuál
    escribir. El de fabricante **sí** se escribe, y es la excepción que se
    justifica sola: son 541 y una lista cerrada de 541 no se recorre.
    """
    from kernelgrove.gui.tabs.database_tab import FILTER_ALL, KIND_BOARD, KIND_SOC

    tab = window.database_tab
    assert tab.vendor_combo.isEditable(), "541 fabricantes se buscan escribiendo"
    for combo in (tab.kind_combo, tab.arch_combo, tab.cores_combo, tab.ram_combo):
        assert not combo.isEditable(), "los de lista corta se eligen"

    def visibles():
        return sum(
            not tab.entries.item(row).isHidden()
            for row in range(tab.entries.count())
        )

    total = tab.entries.count()
    assert visibles() == total

    tab.kind_combo.setCurrentIndex(tab.kind_combo.findData(KIND_SOC))
    assert visibles() == len(window.socs)
    tab.kind_combo.setCurrentIndex(tab.kind_combo.findData(KIND_BOARD))
    assert visibles() == len(window.boards)

    # Los fabricantes salen del catálogo, no de una lista escrita a mano.
    assert tab.vendor_combo.findData("xlnx") > 0
    tab.vendor_combo.setCurrentIndex(tab.vendor_combo.findData("xlnx"))
    solo_xlnx = visibles()
    assert 0 < solo_xlnx < len(window.boards)

    # Y los tres se combinan, no se pisan.
    tab.search.setText("zc702")
    assert 0 < visibles() <= solo_xlnx
    assert tab._count_label.text() == f"{visibles()} of {total}"

    tab.search.setText("")
    tab.vendor_combo.setCurrentIndex(tab.vendor_combo.findData(FILTER_ALL))
    tab.kind_combo.setCurrentIndex(tab.kind_combo.findData(FILTER_ALL))
    assert visibles() == total

    # Núcleos y RAM son «al menos», no «exactamente»: quien busca 4 núcleos
    # también quiere ver los de 8.
    tab.cores_combo.setCurrentIndex(tab.cores_combo.findData(4))
    con_cuatro = visibles()
    tab.cores_combo.setCurrentIndex(tab.cores_combo.findData(8))
    assert 0 < visibles() < con_cuatro < total
    tab.cores_combo.setCurrentIndex(0)

    tab.ram_combo.setCurrentIndex(tab.ram_combo.findData(1 << 30))
    assert 0 < visibles() < total
    tab.ram_combo.setCurrentIndex(0)

    # La arquitectura se filtra por familia, no por modelo de núcleo: el
    # desplegable ofrecía las 115 CPUs distintas del catálogo
    # (`arm,cortex-a53`, `arm,cortex-a9`…), que es una lista que no se
    # recorre y además no es lo que se busca.
    assert tab.arch_combo.count() < 20
    assert tab.arch_combo.findData("ARM") > 0
    assert not any(
        "," in (tab.arch_combo.itemData(i) or "")
        for i in range(tab.arch_combo.count())
    )
    tab.arch_combo.setCurrentIndex(tab.arch_combo.findData("ARM"))
    assert 0 < visibles() < total
    tab.arch_combo.setCurrentIndex(0)
    assert visibles() == total

    # Y escribir un fabricante que no existe no deja la lista vacía sin
    # explicar por qué: vuelve a «todos».
    tab.vendor_combo.setEditText("no-existe-este-fabricante")
    tab._on_vendor_typed()
    assert visibles() == total
    assert visibles() == total


def test_la_franja_de_abajo_cuenta_lo_mismo_que_el_panel(window, app):
    """Los dos números salen del editor, no se cuentan por separado.

    El pase diferido añade diagnósticos después del análisis, así que quien
    contara por su cuenta al analizar se quedaba con un número que ya no
    era el de la lista de abajo.
    """
    from kernelgrove.api import Severity

    editor = window.editor_tab
    editor.open_source("x.dtsi", "/ { cpus { }; };")
    app.processEvents()
    editor.analyze()
    app.processEvents()

    errores, avisos, _info = window._diagnostic_counts
    assert window.problems_error_label.text() == str(errores)
    assert window.problems_label.text() == str(avisos)

    # Y sigue al filtro de gravedad tan poco como debe: filtrar esconde
    # filas, no cambia cuántos problemas tiene el fichero.
    antes = window.problems_label.text()
    editor.severity_checks[Severity.WARNING].setChecked(False)
    app.processEvents()
    assert window.problems_label.text() == antes


def test_el_pie_del_panel_salta_de_una_vista_a_la_otra(window, app):
    """Un botón en el pie, y lo que ofrece lo decide **la vista**.

    Lo decidía el panel, y así el de carpetas ofrecía «ver en el grafo»
    aunque ya estuvieras en el grafo: llevaba a donde ya estabas.
    """
    from kernelgrove.gui.main_window import TAB_EDITOR, TAB_VISUALIZER

    panel = window.explorer_panel
    assert panel.graph_button.text(), "el rótulo no puede quedarse en blanco"
    en_el_editor = panel.graph_button.text()

    # Del editor al grafo…
    panel.footer.clicked.emit()
    app.processEvents()
    assert window.tabs.currentIndex() == TAB_VISUALIZER
    # …y allí ofrece la vuelta, no el sitio donde ya se está.
    assert panel.graph_button.text() != en_el_editor

    panel.footer.clicked.emit()
    app.processEvents()
    assert window.tabs.currentIndex() == TAB_EDITOR
    assert panel.graph_button.text() == en_el_editor


def test_el_inspector_sigue_a_la_vista_no_a_la_seccion(window, app):
    """Se veía o no según la última sección pulsada, no según qué hay delante.

    Cambiar de vista sin pasar por la franja de iconos —cerrar el borrador
    de un overlay, o el propio pie de un panel— dejaba el inspector
    escondido sobre el editor, o puesto sobre el grafo.
    """
    from kernelgrove.gui.main_window import TAB_EDITOR, TAB_VISUALIZER

    # `isHidden` y no `isVisible`: la ventana del fixture no se muestra, así
    # que nada dentro de ella es «visible» aunque esté puesto.
    window.tabs.setCurrentIndex(TAB_VISUALIZER)
    app.processEvents()
    assert window.inspector_dock.isHidden()

    window.tabs.setCurrentIndex(TAB_EDITOR)
    app.processEvents()
    assert not window.inspector_dock.isHidden()


def test_el_pie_se_queda_en_el_icono_cuando_no_cabe_el_rotulo(app):
    """Estrechando el panel, antes salía «Visu…»; ahora sale el icono solo."""
    from kernelgrove.gui.widgets import icons
    from kernelgrove.gui.widgets.panel_footer import PanelFooter

    pie = PanelFooter()
    pie.set_target(icons.tree_icon, "Visualize in node graph", "")
    pie.show()

    pie.setFixedWidth(300)
    app.processEvents()
    assert pie.button.text() == "Visualize in node graph"

    pie.setFixedWidth(110)
    app.processEvents()
    assert pie.button.text() == ""
    assert not pie.button.icon().isNull(), "sin rótulo, el icono es todo lo que queda"
    pie.deleteLater()


def test_un_nodo_del_grafo_es_una_ficha_con_sus_propiedades(app):
    """La ficha crece con lo que enseña, y enseña el valor pelado.

    Las dos cosas de las que cuelga el dibujo: `node_size` es lo que usan
    tanto el item como las aristas (si mintiera, las líneas saldrían de
    fuera de la ficha), y `property_rows` es lo que decide qué se lee
    dentro.
    """
    from kernelgrove.gui.widgets.tree_graph import GraphNode, node_size, property_rows

    filas = property_rows(
        {
            "#address-cells": "<1>",
            "status": '"okay"',
            "gpio-controller": True,
        }
    )
    # En el orden fijo de la ficha, no en el del fuente: `status` va con las
    # que identifican al nodo y el resto detrás, alfabéticamente (ver
    # `test_las_propiedades_de_una_ficha_van_siempre_en_el_mismo_orden`).
    assert filas == [
        ("status", "okay"),
        ("#address-cells", "1"),
        ("gpio-controller", ""),
    ]

    vacio = node_size(GraphNode(label="x"))
    con_filas = node_size(GraphNode(label="x", properties=filas))
    assert vacio.width() == con_filas.width(), "el ancho es fijo"
    assert con_filas.height() > vacio.height()
    # Centrada en su posición: es lo que hace que `setPos(punto)` deje la
    # ficha donde el reparto la ha colocado.
    assert con_filas.center().y() == 0

    # Y no crece sin límite: lo que no cabe se queda en el inspector.
    muchas = node_size(GraphNode(label="x", properties=[("p", "1")] * 40))
    assert muchas.height() == node_size(
        GraphNode(label="x", properties=[("p", "1")] * 4)
    ).height()


def test_la_piel_obsidiana_es_gris_neutro_y_a_escuadra(window, app):
    """«Obsidian Deep»: sus valores, no unos parecidos, y sin esquinas.

    Lo que la distingue de la clásica es exactamente eso — el gris neutro
    hundido, el morado de Material 3 con su texto encima, y 0 px en todo lo
    que es contenedor. Si algo de eso se pierde, deja de ser esa piel.
    """
    from kernelgrove.gui import style, theme

    window._set_skin(theme.SKIN_OBSIDIAN)
    assert theme.current_skin() == theme.SKIN_OBSIDIAN
    assert theme.SUNKEN == "#131313"
    assert theme.PANEL == "#242424"
    assert theme.ACCENT == "#d8baff"
    assert theme.ACCENT_FG == "#3d2163", "el texto del primario es `on-primary`"
    assert theme.RADIUS_PANEL == 0 and theme.RADIUS_CONTROL == 2
    hoja = app.styleSheet()
    assert "#131313" in hoja and "border-radius: 0px" in hoja
    # Oscura y nada más: un modo claro habría que inventarlo.
    assert theme.modes_of(theme.SKIN_OBSIDIAN) == (theme.MODE_DARK,)
    # Y los colores que el QSS no alcanza siguen a la piel.
    assert style.GRAPH_SCENE_BACKGROUND == "#131313"
    assert style.MUTED_TEXT_COLOR == theme.TEXT_MUTED

    window._set_skin(theme.SKIN_CLASSIC)


def test_las_pieles_solo_cambian_la_paleta(window, app):
    """Cambiar de tema no puede mover nada de sitio.

    Una piel es una tabla de colores y nada más: los radios, los rellenos y
    los tamaños de rótulo son de la aplicación. Cuando también eran de la
    piel, pasar de una a otra reajustaba botones, pestañas y esquinas —dos
    cosas distintas metidas en el mismo interruptor.
    """
    from kernelgrove.gui import theme

    forma = (
        "RADIUS_PANEL",
        "RADIUS_CONTROL",
        "RADIUS_ITEM",
        "BUTTON_PADDING",
        "BUTTON_WEIGHT",
        "PRIMARY_PADDING",
        "HEADER_SIZE",
        "TAB_PADDING",
    )
    medidas = {}
    colores = {}
    # Las cinco, no una lista escrita a mano: una piel nueva -las de
    # accesibilidad lo son- tiene que entrar aquí sola.
    pieles = (
        theme.SKIN_CLASSIC,
        theme.SKIN_SITE,
        theme.SKIN_OBSIDIAN,
        theme.SKIN_CONTRAST,
        theme.SKIN_COLORBLIND,
    )
    for skin in pieles:
        window._set_skin(skin)
        medidas[skin] = tuple(getattr(theme, name) for name in forma)
        colores[skin] = (theme.SUNKEN, theme.PANEL, theme.ACCENT)

    assert len(set(medidas.values())) == 1, f"la forma cambia con la piel: {medidas}"
    assert len(set(colores.values())) == len(pieles), "y la paleta sí tiene que cambiar"
    # Y es la de «Obsidian Deep»: a escuadra, 2 px solo en lo pequeño.
    assert medidas[theme.SKIN_CLASSIC][:3] == (0, 2, 2)

    window._set_skin(theme.SKIN_CLASSIC)


def test_la_tipografia_inter_viaja_con_la_aplicacion(app):
    """Enlazarla desde Google Fonts dejaría la app dependiendo de la red."""
    from PySide6.QtGui import QFontDatabase

    from kernelgrove.gui import theme

    assert theme.load_fonts(), "no se ha cargado ninguna Inter"
    assert "Inter" in QFontDatabase.families()
    # Los cinco pesos que pide el sistema de diseño (400..800).
    assert set(QFontDatabase.styles("Inter")) >= {
        "Regular",
        "Medium",
        "SemiBold",
        "Bold",
        "ExtraBold",
    }
    # La licencia obliga a distribuir su texto con la fuente.
    licencia = Path(theme.__file__).parent / "fonts" / "OFL.txt"
    assert "SIL Open Font License" in licencia.read_text(encoding="utf-8")


def _grafo_con_dos_conectados(window):
    """Abre el SoC con todo encendido y le cuelga un dispositivo de dos buses.

    El `.dtsi` real trae `status = "disabled"` en casi todo, y un
    controlador apagado no llega a dibujarse: sin encenderlos no hay dónde
    conectar nada ni, por tanto, nada que mover ni que quitar.
    """
    from kernelgrove.gui.widgets.tree_graph import _NodeItem

    window.editor_tab.open_source(
        title="zynqmp.dtsi",
        text=FIXTURE.read_text(encoding="utf-8").replace(
            'status = "disabled"', 'status = "okay"'
        ),
        source_key="xilinx/zynqmp.dtsi",
    )
    window.editor_tab.analyze()

    buses = [s for s in window.tree_model.root_slots() if s.child_bus == "i2c"]
    assert len(buses) >= 2, "hacen falta dos controladores para el caso interesante"
    for bus in buses[:2]:
        window.tree_model.connect_to_slot(bus, "dallas,ds1307")

    graph = window.visualizer_tab.graph
    graph._root.collapsed = False
    graph.redraw()
    fichas = [
        item
        for item in graph.scene().items()
        if isinstance(item, _NodeItem) and item.node.connected_slot is not None
    ]
    assert len(fichas) == 2
    return graph, buses[:2], fichas


def test_desconectar_quita_lo_del_controlador_senalado(window):
    """Y no lo del primero, que es lo que pasaba con `row()` devolviendo 0.

    Un controlador del SoC no tiene padre, así que su fila solo la sabe el
    modelo; mientras la puso el propio slot, desconectar algo colgado del
    segundo `i2c` borraba lo del primero —o no hacía nada si el primero
    estaba vacío, que es como se veía: un botón muerto.
    """
    graph, buses, fichas = _grafo_con_dos_conectados(window)

    victima = [f for f in fichas if f.node.connected_slot.parent is buses[1]][0]
    graph.deviceRemoved.emit(victima.node.connected_slot)

    assert len(buses[1].children) == 0, "se quita el señalado"
    assert len(buses[0].children) == 1, "y no se toca el otro"


def test_el_grafo_desconecta_toda_la_seleccion_de_una_vez(window):
    """Supr y el menú contextual actúan sobre lo seleccionado, no sobre uno."""
    graph, buses, fichas = _grafo_con_dos_conectados(window)

    for ficha in fichas:
        ficha.setSelected(True)
    assert len(graph.selected_slots()) == 2

    assert graph.remove_selected() == 2
    assert (len(buses[0].children), len(buses[1].children)) == (0, 0)


def test_una_ficha_movida_a_mano_se_queda_donde_la_dejan(window):
    """Reconstruir el grafo (cada análisis) no puede deshacer la colocación."""
    from PySide6.QtCore import QPointF
    from kernelgrove.gui.widgets.tree_graph import _NodeItem

    graph, _buses, fichas = _grafo_con_dos_conectados(window)
    ficha = fichas[0]
    slot = ficha.node.connected_slot
    destino = ficha.pos() + QPointF(400, 250)
    ficha.setPos(destino)

    graph.redraw()
    otra_vez = [
        item
        for item in graph.scene().items()
        if isinstance(item, _NodeItem) and item.node.connected_slot is slot
    ][0]
    assert otra_vez.pos() == destino

    # Y la arista que llega hasta ella la ha seguido.
    llegadas = [e for e, _s, t in graph._edges if t is otra_vez]
    assert llegadas, "la ficha cuelga de algo"
    assert llegadas[0].path().currentPosition() == QPointF(
        destino.x(), destino.y() + otra_vez.rect().top()
    )

    graph.auto_arrange()
    assert graph._manual_pos == {}, "autoordenar olvida lo movido a mano"
    vuelta = [
        item
        for item in graph.scene().items()
        if isinstance(item, _NodeItem) and item.node.connected_slot is slot
    ][0]
    assert vuelta.pos() != destino


BOARD_SOURCE = """/dts-v1/;
#include "zynqmp.dtsi"

/ {
\tmodel = "Placa de prueba";
\tcompatible = "test,board", "xlnx,zynqmp";

\tleds {
\t\tcompatible = "gpio-leds";
\t\tstatus = "okay";

\t\tled-0 {
\t\t\tlabel = "heartbeat";
\t\t};
\t};
};

&i2c0 {
\tstatus = "okay";

\trtc@68 {
\t\tcompatible = "dallas,ds1307";
\t\treg = <0x68>;
\t};
};
"""


def _abrir_placa(window, tmp_path):
    """Una placa de verdad: su fuente más el `.dtsi` del SoC al lado."""
    (tmp_path / "zynqmp.dtsi").write_text(
        FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    board = tmp_path / "board.dts"
    board.write_text(BOARD_SOURCE, encoding="utf-8")

    window.editor_tab.open_source(
        title="board.dts",
        text=BOARD_SOURCE,
        source_key=str(board),
        disk_path=board,
    )
    window.editor_tab.analyze()

    graph = window.visualizer_tab.graph
    graph._root.collapsed = False
    graph.redraw()
    return graph


def test_del_soc_no_se_borra_nada_pero_de_la_placa_si(window, tmp_path):
    """Lo que trae el `#include` vive en otro fichero y no se toca desde el grafo."""
    from kernelgrove.gui.widgets.tree_graph import _BlockChip, _NodeItem

    graph = _abrir_placa(window, tmp_path)
    fichas = {
        item.node.label: item
        for item in graph.scene().items()
        if isinstance(item, _NodeItem)
    }

    assert fichas["rtc@68"].node.editable, "lo añade la placa bajo el i2c del SoC"
    assert fichas["leds"].node.editable, "y esto lo declara ella entera"
    raiz = [item for item in fichas.values() if item.node.is_root][0]
    assert not raiz.node.editable, "la ficha central es el documento, no un nodo"

    # Los controladores del SoC se dibujan como bloques dentro de la ficha
    # central, y un bloque no ofrece borrar en ningún caso.
    chips = [i for i in graph.scene().items() if isinstance(i, _BlockChip)]
    assert chips and not any(chip.node.editable for chip in chips)


def test_borrar_un_nodo_de_la_placa_lo_quita_de_su_fuente(
    window, tmp_path, monkeypatch
):
    """Y no toca ni el bloque del SoC que lo alojaba ni lo que hay al lado."""
    from PySide6.QtWidgets import QMessageBox
    from kernelgrove.gui.widgets.tree_graph import _NodeItem

    graph = _abrir_placa(window, tmp_path)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)

    rtc = [
        item
        for item in graph.scene().items()
        if isinstance(item, _NodeItem) and item.node.label == "rtc@68"
    ][0]
    rtc.setSelected(True)
    assert graph.remove_selected() == 1

    texto = window.editor_tab.current.editor.toPlainText()
    assert "rtc@68" not in texto
    assert "&i2c0 {" in texto, "el nodo del SoC que lo alojaba sigue reabierto"
    assert "leds {" in texto and "led-0 {" in texto, "y lo de al lado, intacto"

    # Se queda como cambio sin guardar: el fichero en disco no se ha tocado.
    assert "rtc@68" in (tmp_path / "board.dts").read_text(encoding="utf-8")
    # Y es una edición del documento, así que se deshace como cualquier otra.
    window.editor_tab.current.editor.undo()
    assert "rtc@68" in window.editor_tab.current.editor.toPlainText()


def test_del_dtsi_de_un_soc_abierto_solo_no_se_borra_nada(window):
    """Sin nada incluido, el documento *es* el SoC: todo lo suyo es del SoC."""
    from kernelgrove.gui.widgets.tree_graph import _NodeItem

    window.editor_tab.open_source(
        title="zynqmp.dtsi",
        text=FIXTURE.read_text(encoding="utf-8").replace(
            'status = "disabled"', 'status = "okay"'
        ),
        source_key="xilinx/zynqmp.dtsi",
    )
    window.editor_tab.analyze()
    graph = window.visualizer_tab.graph
    graph._root.collapsed = False
    graph.redraw()

    fichas = [i for i in graph.scene().items() if isinstance(i, _NodeItem)]
    assert fichas, "algo se dibuja"
    assert not any(item.node.editable for item in fichas)


def _textos_de_menu(window):
    """Los textos de todas las acciones de la barra de menús."""
    from PySide6.QtWidgets import QMenu

    return [
        a.text()
        for menu in window.menu_bar.findChildren(QMenu)
        for a in menu.actions()
    ]


def test_en_un_checkout_se_monta_tambien_lo_experimental(window):
    """Sin `sys.frozen`, generar desde el grafo está encendido.

    `isHidden` y no `isVisible`: la ventana de las pruebas no se llega a
    mostrar, y ahí todo es invisible por herencia; escondido a propósito
    solo lo está lo que alguien escondió.
    """
    from kernelgrove.gui.main_window import SECTION_CONNECTIONS

    assert window._experimental
    assert not window.activity_bar._group.button(SECTION_CONNECTIONS).isHidden()
    assert window.visualizer_tab.graph._editable
    abiertos = []
    window.visualizer_tab.graph.socActivated.connect(lambda: abiertos.append(1))
    window.visualizer_tab.graph.request_soc_properties()
    assert abiertos == [1]

    textos = _textos_de_menu(window)
    assert [t for t in textos if "isconnect" in t]
    assert [t for t in textos if "Licenses" in t]


def test_una_release_solo_monta_lo_estable(app, monkeypatch):
    """Ver el grafo sí; generar desde él (sección, paleta, panel del SoC), no.

    Se fuerza con `sys.frozen`, que es lo que pone PyInstaller, y no con la
    variable: así se prueba la costura de verdad.
    """
    import sys

    from kernelgrove.gui.main_window import (
        SECTION_CONNECTIONS,
        SECTION_OVERLAY,
        MainWindow,
    )

    monkeypatch.delenv("KERNELGROVE_EXPERIMENTAL", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    window = MainWindow(db_path=DB_PATH, dtsi_folder=Path.cwd())
    try:
        assert not window._experimental
        assert window.activity_bar._group.button(SECTION_CONNECTIONS).isHidden()
        textos = _textos_de_menu(window)
        assert not [t for t in textos if "list" in t]
        assert not [t for t in textos if "isconnect" in t]

        # La ventana de nodos, solo para mirar…
        assert window.visualizer_tab.palette.isHidden()
        assert not window.visualizer_tab.graph._editable
        abiertos = []
        window.visualizer_tab.graph.socActivated.connect(lambda: abiertos.append(1))
        window.visualizer_tab.graph.request_soc_properties()
        assert abiertos == [], "el panel del SoC escribe en el fuente"

        # …y lo estable, intacto.
        assert not window.activity_bar._group.button(SECTION_OVERLAY).isHidden()
        assert window.editor_tab.isEnabled()
    finally:
        window.stop_background_work()
        window.deleteLater()


def test_la_variable_manda_sobre_la_costura(monkeypatch):
    """`KERNELGROVE_EXPERIMENTAL` enciende en una release y apaga en un checkout."""
    import sys

    from kernelgrove.gui import features

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("KERNELGROVE_EXPERIMENTAL", "1")
    assert features.experimental()
    monkeypatch.delattr(sys, "frozen")
    monkeypatch.setenv("KERNELGROVE_EXPERIMENTAL", "0")
    assert not features.experimental()


def test_la_franja_dice_que_fichero_es_y_como_termina_sus_lineas(window, app):
    """Decía «DTS · UTF-8» pasara lo que pasara, incluso con un `.json`.

    Y no decía nada del fin de línea, que es lo que hay que poder cambiar en
    un proyecto compartido entre Windows y Linux.
    """
    from kernelgrove.gui import file_io

    editor = window.editor_tab
    assert window.language_label.isHidden(), "sin fichero no hay nada que describir"

    editor.open_source("zynqmp.dtsi", "/ { };\n", source_key="a")
    app.processEvents()
    assert window.language_label.text() == "DTS · UTF-8"
    assert window.newline_button.text() == "LF"

    editor.open_source("cosas.json", '{"a": 1}\r\n', source_key="b")
    app.processEvents()
    assert window.language_label.text() == "JSON · UTF-8"
    assert window.newline_button.text() == "CRLF", "el fichero venía de Windows"

    # Cambiarlo no toca una letra, pero sí cambia el fichero que se escribe.
    documento = editor.current
    assert not documento.is_dirty
    window._toggle_newline()
    app.processEvents()
    assert window.newline_button.text() == "LF"
    assert documento.is_dirty, "cambiar el terminador es un cambio sin guardar"
    assert documento.newline == file_io.LF


def test_guardar_respeta_el_fin_de_linea_elegido(window, app, tmp_path):
    """Se escribe con el terminador del indicador, no con el del sistema."""
    from kernelgrove.gui import file_io

    destino = tmp_path / "board.dts"
    window.editor_tab.open_source("board.dts", "/ { };\n", source_key=str(destino))
    app.processEvents()
    documento = window.editor_tab.current
    documento.disk_path = destino

    documento.newline = file_io.CRLF
    window.editor_tab.save_file()
    assert destino.read_bytes() == b"/ { };\r\n"

    documento.newline = file_io.LF
    window.editor_tab.save_file()
    assert destino.read_bytes() == b"/ { };\n"


def test_la_franja_no_lleva_el_recuento_de_la_base(window):
    """Es un dato del arranque, no de lo que se está editando.

    No cambia en toda la sesión y no se actúa sobre él; vive en «Acerca de».
    """
    assert not hasattr(window, "database_label")


def test_las_licencias_se_leen_con_tipografia_de_documento(app):
    """La licencia del proyecto primero, y con serifa: es un documento."""
    from kernelgrove.gui.widgets.legal_dialog import LegalDialog, licenses_text

    texto = licenses_text()
    assert "Apache License, Version 2.0" in texto
    assert "could not be read" not in texto, "LICENSES.md viaja con el paquete"

    dialogo = LegalDialog(text=texto, title="Licenses")
    dialogo.show()
    app.processEvents()
    fuente = dialogo._view.font()
    assert fuente.family() != "Inter"
    assert fuente.pointSizeF() < app.font().pointSizeF()
    dialogo.deleteLater()


def test_acerca_de_dice_version_licencia_y_con_que_se_compila(window):
    """Ni una palabra de la base de datos, y sí de las herramientas.

    Cuál es la base, dónde está y qué trae dentro no se enseña en ninguna
    parte. Lo que sí hace falta
    es con qué cuenta esta máquina para compilar, que es lo primero que se
    mira cuando «Compilar» no funciona.
    """
    from kernelgrove import __version__
    from kernelgrove.gui import messages

    herramientas = window.service.toolchain()
    texto = messages.about_text(
        version=__version__,
        dtc=herramientas.dtc or messages.tool_not_found(),
        cpp=herramientas.cpp or messages.tool_not_found(),
        dtschema=window.service.dtschema_version() or "unknown",
    )

    assert "KernelGrove - Device Tree Studio" in texto
    assert __version__ in texto
    assert "Apache License 2.0" in texto
    for esperado in ("dtc", "cpp", "dt-schema"):
        assert esperado in texto, esperado

    for prohibido in ("Database", "database", "SoCs", "boards", "sources"):
        assert prohibido not in texto, prohibido


def test_el_panel_de_carpetas_esconde_git_y_marca_el_anidamiento(window, app, tmp_path):
    """`.git` fuera, el resto de lo oculto dentro, y guías de sangrado.

    Era difícil ver de qué carpeta colgaba cada fichero: 12 px de sangrado,
    de los que la flechita se comía casi todos.
    """
    from PySide6.QtWidgets import QStyleOptionViewItem

    from kernelgrove.gui.widgets.file_explorer import _HIDDEN_NAMES, _INDENT

    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("x\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "board.dts").write_text("/ { };\n")

    panel = window.explorer_panel
    panel.set_root(tmp_path)
    for _ in range(40):
        app.processEvents()

    modelo = panel.tree.model()
    raiz = panel.tree.rootIndex()
    filas = {
        modelo.fileName(modelo.index(fila, 0, raiz)): panel.tree.isRowHidden(fila, raiz)
        for fila in range(modelo.rowCount(raiz))
    }
    assert filas.get(".git") is True, "`.git` son miles de ficheros que no se editan"
    assert filas.get(".gitignore") is False, "lo demás oculto sí es del proyecto"
    assert ".git" in _HIDDEN_NAMES

    assert panel.tree.indentation() == _INDENT >= 16

    # El galón de plegado va en el hueco del icono de la fila, no en la
    # banda de ramas que `QTreeView` reserva a su izquierda: allí quedaba un
    # sangrado entero por delante del nombre, leyéndose como una columna
    # aparte, y además subía el nombre de la carpeta al sitio del icono de
    # los ficheros. Así los dos nombres caen en la misma vertical.
    assert not panel.tree.rootIsDecorated()
    opciones = {}
    for nombre in ("sub", ".gitignore"):
        indice = modelo.index(str(tmp_path / nombre))
        opcion = QStyleOptionViewItem()
        opcion.initFrom(panel.tree)
        opcion.rect = panel.tree.visualRect(indice)
        panel._git_delegate.initStyleOption(opcion, indice)
        opciones[nombre] = opcion
    assert not opciones["sub"].icon.isNull(), "la carpeta se quedó sin galón"
    assert (
        opciones["sub"].decorationSize == opciones[".gitignore"].decorationSize
    ), "el galón y el icono de fichero tienen que ocupar el mismo hueco"


def test_el_panel_de_carpetas_selecciona_varios_y_los_borra_de_una_vez(
    window, app, tmp_path, monkeypatch
):
    """Marcar seis y pulsar Supr es una operación, no seis preguntas."""
    from PySide6.QtCore import QItemSelectionModel
    from PySide6.QtWidgets import QAbstractItemView, QMessageBox

    from kernelgrove.gui.widgets import file_explorer

    for nombre in ("a.dts", "b.dts", "c.dts"):
        (tmp_path / nombre).write_text("/ { };\n")

    panel = window.explorer_panel
    panel.set_root(tmp_path)
    for _ in range(40):
        app.processEvents()

    assert panel.tree.selectionMode() == QAbstractItemView.ExtendedSelection

    modelo = panel.tree.model()
    raiz = panel.tree.rootIndex()
    for fila in range(modelo.rowCount(raiz)):
        panel.tree.selectionModel().select(
            modelo.index(fila, 0, raiz),
            QItemSelectionModel.Select | QItemSelectionModel.Rows,
        )
    assert len(panel._selected_paths()) == 3

    preguntas = []
    monkeypatch.setattr(
        file_explorer.QMessageBox,
        "question",
        lambda *args, **kwargs: preguntas.append(args[2]) or QMessageBox.Yes,
    )
    panel._delete_selection()
    assert len(preguntas) == 1, "una pregunta para las tres, no tres"
    assert not list(tmp_path.glob("*.dts"))


def test_el_inspector_se_ensancha_sin_ensanchar_la_ventana(window, app):
    """No se podía: el mínimo del centro dejaba al dock un techo de ~500 px.

    Lo ponía la franja de filtros del panel de abajo, que con sus dos
    pestañas, tres casillas, contador y botones sumaba 653 px de mínimo —
    y `QMainWindow` reparte a los docks lo que sobra del centro.
    """
    from PySide6.QtCore import Qt

    window.resize(1400, 900)
    window.show()
    app.processEvents()

    assert window.centralWidget().minimumSizeHint().width() < 300, (
        "el centro no puede fijar el ancho de la aplicación"
    )
    # Con margen de un par de píxeles: los tiradores de los separadores
    # también ocupan, y lo que se comprueba es que el dock **llega**, no que
    # Qt reparta al píxel.
    for pedido in (500, 700, 900):
        window.resizeDocks([window.inspector_dock], [pedido], Qt.Horizontal)
        app.processEvents()
        assert abs(window.inspector_dock.width() - pedido) <= 4, (
            f"pedidos {pedido}, quedan {window.inspector_dock.width()}"
        )


def test_abrir_un_fichero_respeta_el_modo_en_que_se_esta_mirando(
    window, app, tmp_path
):
    """Quien está en el grafo abre el fichero en el grafo, no en el texto."""
    from kernelgrove.gui.main_window import TAB_EDITOR, TAB_VISUALIZER

    fichero = tmp_path / "board.dts"
    fichero.write_text("/ { model = \"x\"; };\n")

    window.show_view(TAB_VISUALIZER)
    app.processEvents()
    window._open_explorer_file(str(fichero))
    app.processEvents()
    assert window.tabs.currentIndex() == TAB_VISUALIZER

    window.show_view(TAB_EDITOR)
    app.processEvents()
    window._open_explorer_file(str(fichero))
    app.processEvents()
    assert window.tabs.currentIndex() == TAB_EDITOR


def test_el_panel_de_versiones_marca_en_cual_se_esta(app, tmp_path, monkeypatch):
    """Moverse a una versión anterior tiene que verse, y tener salida.

    Antes no había forma de estar en otra que la última, así que tampoco
    había nada que enseñar; con `checkout` sí, y sin marca no se sabe dónde
    se está ni por qué guardar deja de mover la rama.
    """
    import subprocess

    from PySide6.QtWidgets import QInputDialog

    from kernelgrove.gui.widgets.git_panel import (
        _BRANCHES_ROLE,
        _CURRENT_ROLE,
        _ON_BRANCH_ROLE,
        GitPanel,
    )

    def git(*args):
        subprocess.run(
            ["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True
        )

    git("init", "-b", "main")
    git("config", "user.email", "a@b.c")
    git("config", "user.name", "T")
    for texto, mensaje in (("1\n", "uno"), ("2\n", "dos"), ("3\n", "tres")):
        (tmp_path / "board.dts").write_text(texto)
        git("add", ".")
        git("commit", "-m", mensaje)

    panel = GitPanel()
    panel.set_root(tmp_path)
    panel.show()
    panel.refresh()

    def filas():
        return [panel._versions.item(i) for i in range(panel._versions.count())]

    # Solo el mensaje: el sha ya no va delante, va en el aviso de la fila.
    assert [item.text() for item in filas()] == ["tres", "dos", "uno"]
    assert panel._repo.versions()[0].short in filas()[0].toolTip()

    # En la punta: marcada la última, y ninguna salida que ofrecer. La marca
    # es un dato de la fila -lo pinta `_VersionGraphDelegate` como el nodo
    # del grafo-, no un carácter delante del texto.
    assert filas()[0].data(_CURRENT_ROLE)
    assert panel._versions.item(0).font().bold()
    assert panel.branch_name() == "main"
    # La rama va **sobre el grafo**, como en Git Graph: es una propiedad del
    # commit al que apunta, no un dato aparte.
    assert filas()[0].data(_BRANCHES_ROLE) == ("main",)
    assert filas()[0].data(_ON_BRANCH_ROLE) == "main", "y esa es en la que se está"

    # Fuera de la rama, **dos veces**: es el caso que dejaba sin salida al
    # «volver a la rama de la que saliste» que había antes, porque al
    # segundo salto `@{-1}` ya apunta a un sha suelto y git no sabe darle
    # nombre. La lista de ramas no depende del camino recorrido.
    primera = panel._repo.versions()[-1]
    panel._repo.checkout(panel._repo.versions()[1].sha)
    panel._repo.checkout(primera.sha)
    panel._painted = None
    panel.refresh()

    marcadas = [item for item in filas() if item.data(_CURRENT_ROLE)]
    assert len(marcadas) == 1 and marcadas[0].text() == primera.message
    assert len(filas()) == 3, "se sigue viendo todo, no solo lo anterior"
    assert primera.short in panel.branch_name(), "la franja dice dónde se está"
    # La etiqueta de `main` sigue en su commit —es donde está la rama— pero
    # ninguna se dibuja como «puesta»: aquí no se está en ninguna.
    assert filas()[0].data(_BRANCHES_ROLE) == ("main",)
    assert all(fila.data(_ON_BRANCH_ROLE) == "" for fila in filas())

    # Y se vuelve haciendo checkout de la etiqueta, desde su propio commit.
    panel._checkout_branch("main")
    assert panel.branch_name() == "main"
    assert filas()[0].data(_ON_BRANCH_ROLE) == "main"

    # Abrir una rama en una versión antigua es lo que convierte «mirarla» en
    # un sitio donde trabajar: fuera de toda rama, lo que se guarde se pierde
    # al volver.
    monkeypatch.setattr(
        QInputDialog, "getText", lambda *a, **k: ("experimento", True)
    )
    panel._branch_from(filas()[-1])
    assert panel.branch_name() == "experimento"
    # Y la rama nueva sale como etiqueta en su commit, que es donde está.
    assert "experimento" in (filas()[-1].data(_BRANCHES_ROLE) or ())
    panel.deleteLater()


def test_ctrl_clic_en_una_referencia_lleva_a_donde_se_declara(window, app):
    """«Ir a la definición» de un `&label`, dentro del mismo fichero.

    La referencia se lee del texto y no del árbol: aquí está dentro de un
    valor (`interrupt-affinity = <&cpu0>`), que es donde el parser no la
    registra como nada, y es justo el sitio donde hace más falta.
    """
    texto = FIXTURE.read_text(encoding="utf-8")
    window.editor_tab.open_source(
        title="zynqmp.dtsi", text=texto, source_key="xilinx/zynqmp.dtsi"
    )
    window.editor_tab.analyze()
    app.processEvents()

    lineas = texto.splitlines()
    def _linea_con(aguja: str) -> int:
        return next(i for i, linea in enumerate(lineas, 1) if aguja in linea)

    uso = _linea_con("<&cpu0>")
    declaracion = _linea_con("cpu0: cpu@0 {")

    editor = window.editor_tab.current.editor
    columna = lineas[uso - 1].index("&cpu0") + 1
    editor.ctrlLineClicked.emit(uso, columna)
    app.processEvents()

    assert window.editor_tab.current.editor.textCursor().blockNumber() + 1 == (
        declaracion
    )


def test_ctrl_clic_en_una_referencia_abre_el_fichero_que_la_declara(window, app):
    """Y si el nodo lo trae un `#include`, se abre ese fichero.

    Es el caso de una placa: `&cpu0` no tiene ninguna línea en el documento
    abierto, vive en el `.dtsi` del SoC. Sin `source_key` en cada nodo del
    árbol fusionado no habría forma de saber cuál es.
    """
    placa = '#include "zynqmp.dtsi"\n\n/ {\n    model = "placa";\n};\n\n&cpu0 {\n};\n'
    window.editor_tab.open_source(
        title="placa.dts", text=placa, source_key="placa.dts"
    )
    window.editor_tab.analyze()
    app.processEvents()

    editor = window.editor_tab.current.editor
    editor.ctrlLineClicked.emit(7, 2)
    app.processEvents()

    # Cuál de las copias del `.dtsi` resuelva la base de datos da igual; lo
    # que se comprueba es que se ha abierto otro fichero y no la placa.
    activo = window.editor_tab.current
    assert activo.source_key != "placa.dts"
    assert activo.source_key.endswith("zynqmp.dtsi")
    assert "cpu0: cpu@0 {" in (
        activo.editor.document()
        .findBlockByNumber(activo.editor.textCursor().blockNumber())
        .text()
    )
