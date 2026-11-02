"""`/delete-node/` y `/delete-property/`: lo que dtc quita del árbol.

525 de los 6 347 `.dts`/`.dtsi` del kernel usan estas directivas, y el parser
las descartaba en silencio: el árbol fusionado conservaba nodos y propiedades
que el binario compilado no tiene, así que las seis capas de comprobación
estaban juzgando un árbol que no existe.

El caso que importa no es el de un fichero suelto sino el de una placa que
incluye el `.dtsi` de su SoC y le quita lo que no lleva, de ahí que se
compruebe también a través del `IncludeResolver` con la cadena ya fusionada.
"""

from __future__ import annotations

import sqlite3
import zlib
from pathlib import Path

import pytest

from kernelgrove.api.includes import IncludeResolver
from kernelgrove.api.sources_database import SourcesDatabase
from kernelgrove.dt_model.model import (
    DeviceTreeNode,
    apply_deletions,
    resolve_label_overrides,
)
from kernelgrove.dts_engine.parser import parse_dts_source

SOC = """
/ {
    soc {
        i2c0: i2c@0 {
            compatible = "vendor,i2c";
            status = "disabled";
            rtc@68 { compatible = "dallas,ds1307"; };
            eeprom@50 { compatible = "atmel,24c02"; };
        };
        spi0: spi@1 { compatible = "vendor,spi"; };
    };
};
"""


def _arbol(text: str) -> DeviceTreeNode:
    """Árbol de un fuente suelto, con sus reaperturas y borrados aplicados."""
    result = parse_dts_source(text)
    resolve_label_overrides(result.root)
    apply_deletions(result.root, result.deletions)
    return result.root


def _buscar(root: DeviceTreeNode, name: str) -> DeviceTreeNode | None:
    for node in root.iter_tree():
        if node.name == name:
            return node
    return None


def test_borra_un_hijo_del_nodo_donde_esta_escrita():
    """`/delete-node/ rtc@68;` dentro del nodo quita ese hijo."""
    root = _arbol(SOC + "\n&i2c0 {\n    /delete-node/ rtc@68;\n};\n")

    assert _buscar(root, "rtc@68") is None
    assert _buscar(root, "eeprom@50") is not None


def test_borra_una_propiedad():
    """`/delete-property/ status;` la quita del nodo reabierto."""
    root = _arbol(SOC + '\n&i2c0 {\n    /delete-property/ status;\n};\n')

    i2c = _buscar(root, "i2c@0")
    assert i2c is not None
    assert "status" not in i2c.properties
    assert "compatible" in i2c.properties


def test_borra_un_nodo_por_su_etiqueta():
    """`/delete-node/ &spi0;` lo quita esté donde esté, no solo bajo la raíz."""
    root = _arbol(SOC + "\n/delete-node/ &spi0;\n")

    assert _buscar(root, "spi@1") is None
    assert _buscar(root, "i2c@0") is not None


def test_borra_por_ruta_completa():
    """La referencia `&{/ruta}` también sirve de objetivo."""
    root = _arbol(SOC + "\n/delete-node/ &{/soc/spi@1};\n")

    assert _buscar(root, "spi@1") is None


def test_un_objetivo_que_no_existe_no_rompe_nada():
    """Borrar lo que no está se ignora: es lo que ya dice la capa 1."""
    root = _arbol(SOC + "\n&i2c0 {\n    /delete-node/ noexiste@99;\n};\n")

    assert _buscar(root, "rtc@68") is not None


def test_las_directivas_no_se_registran_como_propiedades():
    """Ni `/delete-node/` ni `/delete-property/` son propiedades del nodo."""
    result = parse_dts_source(
        "/ { foo { bar; /delete-property/ bar; /delete-node/ baz; }; };"
    )
    foo = _buscar(result.root, "foo")

    assert foo is not None
    assert list(foo.properties) == ["bar"]
    assert [(d.kind, d.target) for d in result.deletions] == [
        ("property", "bar"),
        ("node", "baz"),
    ]


@pytest.fixture
def resolver(tmp_path: Path) -> IncludeResolver:
    """Resolutor sobre una base mínima que solo contiene el `.dtsi` del SoC."""
    path = tmp_path / "bindings.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE sources (path TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL, "
        "kind TEXT NOT NULL, source BLOB NOT NULL)"
    )
    conn.execute("CREATE INDEX idx_sources_name ON sources(name)")
    conn.execute(
        "INSERT INTO sources (path, name, kind, source) VALUES (?, ?, ?, ?)",
        ("vendor/soc.dtsi", "soc.dtsi", "devicetree", zlib.compress(SOC.encode())),
    )
    conn.commit()
    conn.close()
    return IncludeResolver(SourcesDatabase(path))


BOARD = """
#include "vendor/soc.dtsi"

/ {
    model = "placa de prueba";
};

&i2c0 {
    status = "okay";
    /delete-node/ eeprom@50;
};

/delete-node/ &spi0;
"""


def test_una_placa_borra_lo_que_trae_el_dtsi_de_su_soc(resolver: IncludeResolver):
    """El caso real: el objetivo no está en el fichero que escribe la directiva.

    Por eso los borrados se aplican al final, con los includes ya fusionados y
    las reaperturas `&label` ya plegadas; hacerlo antes no encontraría nada.
    """
    result = parse_dts_source(BOARD)
    merged = result.root.clone()
    resolver.resolve_tree(merged, result.includes, "board.dts")
    resolve_label_overrides(merged)
    apply_deletions(merged, result.deletions)

    assert _buscar(merged, "eeprom@50") is None
    assert _buscar(merged, "spi@1") is None
    # Lo que la placa no borra sigue ahí, y su reapertura se ha aplicado.
    rtc = _buscar(merged, "rtc@68")
    assert rtc is not None
    assert _buscar(merged, "i2c@0").properties["status"] == '"okay"'


def test_cada_nodo_sabe_de_que_fichero_viene(resolver: IncludeResolver):
    """`source_key` es lo que permite ir de un `&i2c0` a su declaración.

    Los nodos del documento abierto lo dejan a None, que es precisamente lo
    que los distingue de los que llegan por un `#include`.
    """
    result = parse_dts_source(BOARD)
    merged = result.root.clone()
    resolver.resolve_tree(merged, result.includes, "board.dts")
    resolve_label_overrides(merged)

    assert _buscar(merged, "i2c@0").source_key == "vendor/soc.dtsi"
    assert merged.source_key is None
