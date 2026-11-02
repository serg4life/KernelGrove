"""El ciclo del asistente de overlays, movido desde la interfaz.

Señalar el nodo objetivo, marcar propiedades, colgarle un nodo nuevo,
cambiar de nodo apuntado desde el preview y generar el fuente — y que el
documento resultante sepa cuál es su base, que es lo que hace que el motor
semántico no esté mudo dentro de un overlay.

Necesita `database/bindings.db` porque el asistente pregunta al binding qué
propiedades admite cada nodo; sin ella se salta.
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

pytest.importorskip("PySide6", reason="el asistente es de la GUI")


@pytest.fixture(scope="module")
def app():
    """Un único `QApplication` para todo el módulo."""
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytest.fixture
def base_tree(app):
    """Árbol de la base, fusionado, tal como lo ve la ventana."""
    from kernelgrove.api import KernelGroveService

    service = KernelGroveService(DB_PATH)
    result, _ = service.analyze_source(
        FIXTURE.read_text(encoding="utf-8"),
        fragment=True,
        base_path="xilinx/zynqmp.dtsi",
    )
    merged, _ = service.build_visual_tree(result, "xilinx/zynqmp.dtsi")
    return service, merged


@pytest.fixture
def tab(base_tree):
    """Vista de overlays con la base ya cargada y sin borrador."""
    from kernelgrove.gui.tabs.overlay_tab import OverlayTab

    service, merged = base_tree
    widget = OverlayTab(service)
    widget.set_base(merged)
    yield widget
    widget.deleteLater()


def _node(merged, label: str):
    """Nodo del árbol fusionado con esa etiqueta."""
    for node in merged.iter_tree():
        if node.label == label:
            return node
    raise AssertionError(f"no hay ningún nodo etiquetado {label!r}")


def _check(tree, name: str, value: str = "") -> None:
    """Marca una propiedad de una de las dos listas y le pone valor."""
    from PySide6.QtCore import Qt

    for index in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(index)
        if item.text(0) == name:
            item.setCheckState(0, Qt.Checked)
            if value:
                item.setText(1, value)
            return
    raise AssertionError(f"la propiedad {name!r} no está en la lista")


def _names(tree) -> list:
    """Nombres de las propiedades listadas, sin la fila de «aquí no hay nada»."""
    from PySide6.QtCore import Qt

    return [
        tree.topLevelItem(i).text(0)
        for i in range(tree.topLevelItemCount())
        if tree.topLevelItem(i).flags() != Qt.NoItemFlags
    ]


def test_el_objetivo_se_escribe_por_su_etiqueta(tab, base_tree):
    """Es lo que decide a qué apunta el fragmento."""
    _, merged = base_tree

    assert tab.start_draft(_node(merged, "i2c0"))
    assert tab.has_draft
    assert tab.reference_label.text() == "&i2c0"


def test_las_propiedades_se_separan_en_las_que_tiene_y_las_que_admite(
    tab, base_tree
):
    """Es la distinción entre sobrescribir y añadir, que es lo que se elige."""
    _, merged = base_tree
    tab.start_draft(_node(merged, "i2c0"))

    presentes = _names(tab.existing)
    admitidas = _names(tab.available)

    assert "compatible" in presentes, "el nodo de la base ya lo tiene"
    assert "status" in presentes
    assert admitidas, "su binding admite más de las que tiene"
    assert not set(presentes) & set(admitidas), "una propiedad está en una lista"


def test_marcar_una_propiedad_se_ve_en_el_preview(tab, base_tree, qt_signal):
    """El preview es el borrador ya escrito: no hay nada más que mirar."""
    _, merged = base_tree
    tab.start_draft(_node(merged, "i2c0"))

    borradores = qt_signal(tab.draftChanged)
    _check(tab.existing, "status", "okay")

    fuente = borradores[-1][0]
    assert "&i2c0 {" in fuente
    assert '    status = "okay";' in fuente


def test_generar_produce_un_overlay_valido_con_el_destino_correcto(
    tab, base_tree, qt_signal
):
    """El fuente sale con su cabecera, su destino y el valor bien envuelto."""
    _, merged = base_tree
    tab.start_draft(_node(merged, "i2c0"))
    _check(tab.existing, "status", "okay")

    fuentes = qt_signal(tab.overlayGenerated)
    tab.generate()

    assert len(fuentes) == 1
    fuente, destino = fuentes[0]
    assert destino == "i2c0", "el nombre del nodo bautiza el fichero"
    assert "/plugin/;" in fuente
    assert "&i2c0 {" in fuente
    assert '    status = "okay";' in fuente
    assert not tab.has_draft, "generar cierra el borrador"


def test_un_overlay_vacio_no_se_genera(tab, base_tree, qt_signal):
    """Un fragmento sin cambios no es un fichero que merezca escribirse."""
    _, merged = base_tree
    tab.start_draft(_node(merged, "i2c0"))

    fuentes = qt_signal(tab.overlayGenerated)
    tab.generate()

    assert fuentes == []
    assert tab.has_draft


def test_un_nodo_nuevo_se_escribe_con_su_compatible(tab, base_tree, qt_signal):
    """Solo el compatible: lo que falte lo dirá el motor, no el andamio.

    Escribir `reg = ;` porque el binding lo exige produce un fichero que ni
    siquiera parsea, y rellenarlo con un valor inventado es peor.
    """
    _, merged = base_tree
    tab.start_draft(_node(merged, "i2c0"))

    borradores = qt_signal(tab.draftChanged)
    tab.add_node("dallas,ds1307", "rtc@68")

    fuente = borradores[-1][0]
    assert "    rtc@68 {" in fuente
    assert '        compatible = "dallas,ds1307";' in fuente
    assert "= ;" not in fuente


def test_una_propiedad_que_no_es_marca_se_escribe_con_valor(tab, base_tree):
    """Sin `=` solo son válidas las marcas; el resto sería DTS mal formado.

    El valor es de relleno a propósito —lo real no se puede adivinar— pero
    se ve en la lista y se puede corregir en el preview, que para eso se
    edita.
    """
    _, merged = base_tree
    tab.start_draft(_node(merged, "i2c0"))

    _check(tab.available, "label")            # string-array
    _check(tab.available, "i2c-analog-filter")  # flag

    fuente = tab._preview_text
    assert '    label = "";' in fuente
    assert "    i2c-analog-filter;" in fuente, "una marca no lleva valor"


def test_un_enum_arranca_por_uno_de_sus_valores(tab, base_tree):
    """Si el binding enumera lo que admite, el relleno sale de ahí."""
    _, merged = base_tree
    tab.start_draft(_node(merged, "i2c0"))

    _check(tab.available, "clock-name")

    # `clock-name` declara sus valores; el relleno es uno de ellos, no `""`.
    assert '    clock-name = "";' not in tab._preview_text
    assert "    clock-name = " in tab._preview_text


def test_editar_el_texto_a_mano_manda_sobre_lo_marcado(tab, base_tree):
    """Es la misma regla del editor —el fuente es el modelo— un paso antes."""
    _, merged = base_tree
    tab.start_draft(_node(merged, "i2c0"))
    _check(tab.available, "label")

    a_mano = tab._preview_text.replace('label = "";', 'label = "bus trasero";')
    tab.set_source(a_mano)

    assert [(e.name, e.value) for e in tab._fragment.properties] == [
        ("label", '"bus trasero"')
    ]
    # Y marcar otra cosa después no se lleva por delante lo escrito.
    _check(tab.available, "i2c-analog-filter")
    assert '    label = "bus trasero";' in tab._preview_text


def test_un_include_escrito_a_mano_sobrevive_a_regenerar(tab, base_tree):
    """Regenerar recompone el fichero entero: sin esto, desaparecería."""
    _, merged = base_tree
    tab.start_draft(_node(merged, "i2c0"))
    _check(tab.available, "label")

    a_mano = tab._preview_text.replace(
        "/plugin/;", "/plugin/;\n\n#include <dt-bindings/gpio/gpio.h>"
    )
    tab.set_source(a_mano)
    _check(tab.available, "i2c-analog-filter")

    assert "#include <dt-bindings/gpio/gpio.h>" in tab._preview_text


def test_un_texto_sin_fragmento_no_vacia_el_borrador(tab, base_tree):
    """Se escribe carácter a carácter, y a mitad no hay overlay que leer.

    Mientras el `&objetivo {` no esté escrito no hay fragmento del que sacar
    nada; vaciar entonces las listas sería perder lo marcado por teclear.
    """
    _, merged = base_tree
    tab.start_draft(_node(merged, "i2c0"))
    _check(tab.available, "label")
    antes = tab._preview_text

    tab.set_source("/dts-v1/;\n/plugin/;\n")

    assert tab.has_draft
    assert tab._preview_text == antes
    assert [e.name for e in tab._fragment.properties] == ["label"]


def test_anadir_un_nodo_pasa_a_apuntarlo(tab, base_tree):
    """Lo siguiente que se hace con un nodo recién añadido es rellenarlo."""
    _, merged = base_tree
    tab.start_draft(_node(merged, "i2c0"))
    tab.add_node("dallas,ds1307", "rtc@68")

    assert tab.reference_label.text() == "&i2c0 / rtc@68"
    assert tab.compatible_label.text() == "dallas,ds1307"
    # Un nodo que todavía no existe en la base no tiene nada «de antes».
    assert _names(tab.existing) == []
    assert "compatible" in _names(tab.available)


def test_senalar_un_nodo_del_preview_cambia_de_referencia(tab, base_tree):
    """Es la navegación del asistente: el texto es el índice de nodos."""
    _, merged = base_tree
    tab.start_draft(_node(merged, "i2c0"))
    tab.add_node("dallas,ds1307", "rtc@68")
    fuente = tab._preview_text

    linea_objetivo = fuente.splitlines().index("&i2c0 {") + 1
    tab.select_line(linea_objetivo)

    assert tab.reference_label.text() == "&i2c0"
    assert "status" in _names(tab.existing), "vuelven las del nodo de la base"

    linea_hijo = next(
        numero
        for numero, texto in enumerate(fuente.splitlines(), start=1)
        if texto.strip() == "rtc@68 {"
    )
    tab.select_line(linea_hijo)

    assert tab.reference_label.text() == "&i2c0 / rtc@68"


def test_lo_marcado_en_cada_nodo_se_conserva_al_ir_y_volver(tab, base_tree):
    """El borrador es el estado; las listas solo lo enseñan."""
    from PySide6.QtCore import Qt

    _, merged = base_tree
    tab.start_draft(_node(merged, "i2c0"))
    _check(tab.existing, "status", "okay")
    tab.add_node("dallas,ds1307", "rtc@68")

    fuente = tab._preview_text
    tab.select_line(fuente.splitlines().index("&i2c0 {") + 1)

    marcadas = {
        tab.existing.topLevelItem(i).text(0)
        for i in range(tab.existing.topLevelItemCount())
        if tab.existing.topLevelItem(i).checkState(0) == Qt.Checked
    }
    assert marcadas == {"status"}


def test_un_nodo_sin_etiqueta_ni_ruta_no_puede_ser_objetivo(tab):
    """No hay forma de escribirlo, así que se rechaza en vez de inventarlo."""
    from kernelgrove.api import DeviceTreeNode

    assert not tab.start_draft(DeviceTreeNode(name=""))
    assert not tab.has_draft


def test_el_overlay_generado_se_valida_contra_su_base(base_tree, tab, qt_signal):
    """La capa 1 habla sola; lo que la base desbloquea es el binding.

    Que a `rtc@68` le falte `reg` lo ve la capa 1 sin ayuda: está escrito en
    el propio overlay. Lo que **solo** se puede saber con la base es a qué
    dispositivo corresponde un `&i2c0`, porque su `compatible` está en otro
    fichero — y de ahí cuelgan el autocompletado y la capa 5.
    """
    service, merged = base_tree
    tab.start_draft(_node(merged, "i2c0"))
    _check(tab.existing, "status", "okay")

    fuentes = qt_signal(tab.overlayGenerated)
    tab.generate()
    fuente, _destino = fuentes[0]

    # El cursor, dentro del bloque `&i2c0 { … }`.
    posicion = fuente.index('status = "okay"')

    con_base = service.completion_context(fuente, posicion, overlay_base=merged)
    sin_base = service.completion_context(fuente, posicion)

    assert con_base.compatible == "cdns,i2c-r1p14"
    assert sin_base.compatible is None
    assert service.suggest_properties(con_base.compatible)


def test_un_destino_inventado_lo_caza_la_capa_6(base_tree):
    """La comprobación del asistente: contra la base, un `&noexiste` no existe."""
    service, merged = base_tree
    overlay = '/dts-v1/;\n/plugin/;\n&noexiste { status = "okay"; };\n'

    _, diagnostics = service.analyze_source(
        overlay, fragment=True, overlay_base=merged, overlay_checks=True
    )

    assert any(d.code.value == "overlay-target-not-found" for d in diagnostics)


def test_la_capa_6_no_se_ejecuta_si_no_se_pide(base_tree):
    """No es algo que pase de fondo mientras se escribe: se pide.

    La base sigue llegando —hace falta para el árbol fusionado y para el
    autocompletado dentro del overlay— pero el veredicto de la capa 6 es del
    asistente, que sabe contra qué base compara y lo dice.
    """
    service, merged = base_tree
    overlay = '/dts-v1/;\n/plugin/;\n&noexiste { status = "okay"; };\n'

    _, diagnostics = service.analyze_source(
        overlay, fragment=True, overlay_base=merged
    )

    assert not any(d.code.value.startswith("overlay-") for d in diagnostics)


def test_las_listas_de_propiedades_no_se_escriben(tab, base_tree):
    """Aquí se marca qué entra; escribir se escribe en el preview.

    Y el nombre no es de nadie: lo pone el binding, renombrarlo no significa
    nada.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractItemView

    _, merged = base_tree
    tab.start_draft(_node(merged, "i2c0"))

    for lista in (tab.existing, tab.available):
        assert lista.editTriggers() == QAbstractItemView.NoEditTriggers
        item = lista.topLevelItem(0)
        assert not item.flags() & Qt.ItemIsEditable


# ----------------------------------------------------------------------
# Listado de overlays de la carpeta
# ----------------------------------------------------------------------
OVERLAY_OK = '/dts-v1/;\n/plugin/;\n\n&i2c0 {\n\tstatus = "okay";\n};\n'
OVERLAY_ROTO = '/dts-v1/;\n/plugin/;\n\n&no_existe {\n\tstatus = "okay";\n};\n'


@pytest.fixture
def carpeta(tmp_path):
    """Carpeta con dos overlays: uno que cuadra con la base y otro que no."""
    (tmp_path / "bueno.dtso").write_text(OVERLAY_OK, encoding="utf-8")
    (tmp_path / "roto.dtso").write_text(OVERLAY_ROTO, encoding="utf-8")
    (tmp_path / "no-es-overlay.txt").write_text("nada", encoding="utf-8")
    return tmp_path


def _filas(lista) -> dict:
    """Fichero -> (objetivos, base, veredicto) de la tabla del listado.

    Los objetivos no tienen columna propia -se comía el ancho del panel-,
    así que salen del aviso de la fila, que es donde se leen ahora. Por las
    columnas y no por su número: la primera es el interruptor de si el
    overlay entra en la compilación.
    """
    from kernelgrove.gui.widgets.overlay_list import (
        COLUMN_BASE,
        COLUMN_FILE,
        COLUMN_STATUS,
    )

    tabla = lista.table
    return {
        tabla.topLevelItem(i).text(COLUMN_FILE): (
            tabla.topLevelItem(i).toolTip(COLUMN_FILE),
            tabla.topLevelItem(i).text(COLUMN_BASE),
            tabla.topLevelItem(i).text(COLUMN_STATUS),
        )
        for i in range(tabla.topLevelItemCount())
    }


def test_el_listado_comprueba_cada_overlay_contra_la_base(base_tree, carpeta):
    """Un objetivo que no existe en la base es EL fallo de un overlay."""
    from kernelgrove.gui.widgets.overlay_list import OverlayList

    service, merged = base_tree
    lista = OverlayList(service)
    lista.set_context(carpeta, merged)

    filas = _filas(lista)
    assert set(filas) == {"bueno.dtso", "roto.dtso"}, "solo los .dtso"
    assert filas["bueno.dtso"][0] == "&i2c0"
    assert filas["bueno.dtso"][2] == "passed"
    assert "&no_existe" in filas["roto.dtso"][0]
    assert "1" in filas["roto.dtso"][2], "el objetivo no está en la base"
    lista.deleteLater()


def test_sin_base_el_listado_no_da_veredicto(base_tree, carpeta):
    """Misma regla que la capa 6: sin base contra la que mirar, no se afirma."""
    from kernelgrove.gui.widgets.overlay_list import OverlayList

    service, _ = base_tree
    lista = OverlayList(service)
    lista.set_context(carpeta, None)

    filas = _filas(lista)
    assert len(filas) == 2
    for _objetivos, _base, veredicto in filas.values():
        assert "base" in veredicto.lower(), veredicto
    lista.deleteLater()


def test_validar_escribe_en_el_registro_aunque_pase(base_tree, carpeta, qt_signal):
    """«No ha pasado nada» y «no se ha comprobado nada» se parecen demasiado."""
    from kernelgrove.gui.widgets.overlay_list import OverlayList

    service, merged = base_tree
    lista = OverlayList(service)
    informes = qt_signal(lista.reportReady)
    lista.set_base_resolver(lambda _key: merged)
    lista.set_context(carpeta, merged)

    lista.validate(str(carpeta / "bueno.dtso"), None)

    registro = "".join(informes)
    assert "bueno.dtso" in registro
    assert "layer 6" in registro, "hay que ver que la capa 6 se ha ejecutado"
    assert "passed" in registro
    lista.deleteLater()


def test_volver_a_comprobar_cuenta_lo_mismo_que_validar(base_tree, carpeta, qt_signal):
    """Un botón que relista sin decir nada parece un botón roto.

    Y con el mismo detalle que «Validate…»: lo único que las distingue es
    contra qué base se comprueba, no cuánto se cuenta después.
    """
    from kernelgrove.gui.widgets.overlay_list import OverlayList

    service, merged = base_tree
    lista = OverlayList(service)
    informes = qt_signal(lista.reportReady)
    lista.set_base_resolver(lambda _key: merged)
    lista.set_context(carpeta, merged)

    lista.recheck()

    registro = "".join(informes)
    assert registro, "«Check again» tiene que responder algo"
    assert "bueno.dtso" in registro and "roto.dtso" in registro
    assert "layer 6" in registro, "el mismo detalle que validar"
    assert "NOT FOUND" in registro

    # Y en columnas: cada línea de un nivel empieza donde las demás, con su
    # glifo, en vez de arrancar dos caracteres antes cuando no lleva.
    niveles = {
        len(linea) - len(linea.lstrip(" "))
        for linea in registro.splitlines()
        if linea.startswith(" ")
    }
    for linea in registro.splitlines():
        sangria = len(linea) - len(linea.lstrip(" "))
        if sangria in niveles:
            assert linea[sangria] in "·✓✗!", linea
    lista.deleteLater()


def test_validar_detalla_lo_que_falla(base_tree, carpeta, qt_signal):
    """Y cuando no pasa, el registro dice qué objetivo no existe."""
    from kernelgrove.gui.widgets.overlay_list import OverlayList

    service, merged = base_tree
    lista = OverlayList(service)
    informes = qt_signal(lista.reportReady)
    lista.set_base_resolver(lambda _key: merged)
    lista.set_context(carpeta, merged)

    lista.validate(str(carpeta / "roto.dtso"), None)

    registro = "".join(informes)
    assert "&no_existe" in registro
    assert "NOT FOUND" in registro
    lista.deleteLater()



def test_validar_varios_a_la_vez_pregunta_la_base_una_sola_vez(
    base_tree, carpeta, qt_signal
):
    """Un proyecto tiene varios overlays de la misma placa.

    Contestar la misma pregunta una vez por fichero no es elegir, es un
    peaje: la selección entera se comprueba contra la base elegida.
    """
    from kernelgrove.gui.widgets.overlay_list import OverlayList

    service, merged = base_tree
    lista = OverlayList(service)
    informes = qt_signal(lista.reportReady)
    lista.set_base_resolver(lambda _key: merged)
    lista.set_context(carpeta, None)

    lista.validate(
        [str(carpeta / "bueno.dtso"), str(carpeta / "roto.dtso")],
        "xilinx/zynqmp.dtsi",
    )

    filas = _filas(lista)
    assert filas["bueno.dtso"][2] == "passed"
    assert "1" in filas["roto.dtso"][2], "el objetivo no está en la base"
    registro = "".join(informes)
    assert "bueno.dtso" in registro and "roto.dtso" in registro
    lista.deleteLater()


def test_sin_seleccion_validar_los_comprueba_todos(base_tree, carpeta):
    """Pulsar «Validate» sin haber elegido nada quiere decir «todos»."""
    from kernelgrove.gui.widgets.overlay_list import OverlayList

    service, merged = base_tree
    pedidos = []
    lista = OverlayList(service)
    lista.validateRequested.connect(pedidos.append)
    lista.set_context(carpeta, merged)
    lista.table.clearSelection()

    lista._on_validate_clicked()

    assert len(pedidos) == 1
    assert {Path(p).name for p in pedidos[0]} == {"bueno.dtso", "roto.dtso"}
    lista.deleteLater()
