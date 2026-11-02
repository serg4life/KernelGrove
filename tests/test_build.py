"""Construir un árbol con sus overlays: comprobar primero, compilar después.

Con `dtc` y `cpp` de verdad —se salta si no están—: lo que se prueba es que
el `.dts` se compila **con sus inclusiones** (que es lo que se rompe si el
fuente se copia a un temporal) y que un overlay que apunta a un nodo que no
existe en la base para la compilación en vez de producir un `.dtbo` que solo
falla al aplicarlo en la placa.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kernelgrove.api import KernelGroveService
from kernelgrove.api.toolchain import detect_toolchain

DB_PATH = Path(__file__).resolve().parents[1] / "database" / "bindings.db"

pytestmark = [
    pytest.mark.skipif(not DB_PATH.exists(), reason="hace falta database/bindings.db"),
    pytest.mark.skipif(
        not detect_toolchain().can_compile, reason="hacen falta dtc y cpp"
    ),
]

BASE = """/dts-v1/;

#include "pieces.dtsi"

/ {
    model = "Test board";
    compatible = "test,board";

    i2c0: i2c@1000 {
        #address-cells = <1>;
        #size-cells = <0>;
        status = "disabled";
    };
};
"""

PIECES = """/ {
    chosen { bootargs = "console=ttyS0"; };
};
"""

BUENO = """/dts-v1/;
/plugin/;

&i2c0 {
    status = "okay";
};
"""

ROTO = """/dts-v1/;
/plugin/;

&no_existe {
    status = "okay";
};
"""


@pytest.fixture
def proyecto(tmp_path):
    """Una carpeta con su árbol, la inclusión que necesita y dos overlays."""
    (tmp_path / "board.dts").write_text(BASE, encoding="utf-8")
    (tmp_path / "pieces.dtsi").write_text(PIECES, encoding="utf-8")
    (tmp_path / "bueno.dtso").write_text(BUENO, encoding="utf-8")
    (tmp_path / "roto.dtso").write_text(ROTO, encoding="utf-8")
    return tmp_path


@pytest.fixture
def service():
    return KernelGroveService(DB_PATH)


def _base_de(service, dts: Path):
    """El árbol fusionado del `.dts`, como lo resuelve la ventana."""
    result, _ = service.analyze_source(
        dts.read_text(encoding="utf-8"), fragment=True, base_path=str(dts)
    )
    merged, _ = service.build_visual_tree(result, str(dts))
    return merged


def test_el_arbol_y_sus_overlays_se_compilan(proyecto, service):
    """Un `.dts` con un `#include` de al lado, más el overlay que sí encaja."""
    dts = proyecto / "board.dts"
    overlay = proyecto / "bueno.dtso"

    outcome = service.build_device_tree(dts, [overlay], _base_de(service, dts))

    assert outcome.ok, [step.messages for step in outcome.steps if not step.ok]
    assert (proyecto / "board.dtb").is_file(), "el include de al lado se resolvió"
    assert (proyecto / "bueno.dtbo").is_file()
    # La orden con la que se llamó a cada herramienta queda en el registro.
    ordenes = [
        line
        for step in outcome.steps
        for message in step.messages
        for line in message.splitlines()
        if line.startswith("$ ")
    ]
    assert any("cpp" in o or "gcc" in o for o in ordenes)
    assert any("dtc" in o for o in ordenes)


def test_un_overlay_que_no_pasa_los_checks_para_la_compilacion(proyecto, service):
    """Compilar antes de comprobar deja el fallo para la placa."""
    dts = proyecto / "board.dts"
    roto = proyecto / "roto.dtso"

    outcome = service.build_device_tree(dts, [roto], _base_de(service, dts))

    assert not outcome.ok
    assert [step.kind for step in outcome.steps] == ["check"], "no se llegó a compilar"
    assert outcome.steps[0].errors, "la capa 6 dice que el objetivo no existe"
    assert not (proyecto / "board.dtb").exists()
    assert not (proyecto / "roto.dtbo").exists()


def test_un_include_que_solo_esta_en_la_base_tambien_se_compila(service, tmp_path):
    """Lo que el motor resuelve tiene que compilar, o el análisis miente.

    Un `.dts` del proyecto que incluye un `.dtsi` que no está en su carpeta
    pero sí en la base: el motor lo resuelve por ahí —lo fusiona, completa
    dentro de él y lo valida—, y `cpp` solo sabe leer ficheros. Sin
    escribirlo, el árbol se analiza sin una queja y falla al compilar con
    «No such file or directory» justo en esa inclusión.
    """
    clave = "kernel/linux/arch/arm64/boot/dts/xilinx/zynqmp.dtsi"
    if service.read_source(clave) is None:
        pytest.skip("esta base no trae ese SoC")

    dts = tmp_path / "mi-placa.dts"
    dts.write_text(
        '/dts-v1/;\n#include "zynqmp.dtsi"\n\n'
        '/ { model = "Mi placa"; compatible = "yo,mi-placa", "xlnx,zynqmp"; };\n',
        encoding="utf-8",
    )
    # El motor sí lo encuentra: es justo lo que hace que el fallo sorprenda.
    result, _ = service.analyze_source(
        dts.read_text(encoding="utf-8"), base_path=str(dts)
    )
    merged, _ = service.build_visual_tree(result, str(dts))
    assert merged.children, "el motor no resolvió la inclusión; la prueba no dice nada"

    outcome = service.build_device_tree(dts, [], merged)

    assert outcome.ok, [step.messages for step in outcome.steps if not step.ok]
    assert (tmp_path / "mi-placa.dtb").is_file()
    # Y no se ha escrito nada en la carpeta del usuario: el `.dtsi` de la
    # base va al temporal de la compilación, no a su proyecto.
    assert not (tmp_path / "zynqmp.dtsi").exists()


def test_un_arbol_del_catalogo_se_saca_de_la_base_con_sus_inclusiones(
    service, tmp_path
):
    """Compilar un árbol de la base obliga a deshacer lo que la base hace.

    Los fuentes viven dentro de `bindings.db` y `cpp` solo sabe leer
    ficheros, así que se escriben —cada uno en su ruta relativa, porque un
    `#include "vecino.dtsi"` se resuelve junto al fichero que incluye—.
    """
    key = "kernel/linux/arch/arm64/boot/dts/xilinx/zynqmp-zcu102-rev1.0.dts"
    if service.read_source(key) is None:
        pytest.skip("esta base no trae ese árbol")

    principal = service.materialize_source(key, tmp_path)

    assert principal is not None and principal.is_file()
    escritos = {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*.dts*")}
    assert key in escritos
    # Y sus inclusiones, en la misma ruta relativa que tienen en la base.
    assert any(nombre.endswith("zynqmp.dtsi") for nombre in escritos), escritos
