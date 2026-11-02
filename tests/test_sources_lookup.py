"""Búsqueda de un fuente por el final de su ruta (`find_by_suffix`).

Es lo que resuelve cada `#include` en cada análisis del editor, y pasó de un
`LIKE '%/…'` —que no puede usar índice y recorría las 7 512 filas de
`sources`, 3,58 ms por llamada— a filtrar por nombre de fichero, que sí usa
`idx_sources_name` (0,02 ms). Lo que se comprueba aquí es que la respuesta
sigue siendo exactamente la misma, incluido el desempate por ruta más corta.
"""

from __future__ import annotations

import sqlite3
import zlib
from pathlib import Path

import pytest

from kernelgrove.api.sources_database import SourcesDatabase

FILES = {
    "kernel/linux/include/dt-bindings/gpio/gpio.h": "#define GPIO_ACTIVE_HIGH 0",
    "vendor/dt-bindings/gpio/gpio.h": "cabecera de otro vendedor, ruta más larga",
    "xilinx/zynqmp.dtsi": "/ { model = \"zynqmp\"; };",
    "gpio.h": "cabecera suelta en la raíz",
}


@pytest.fixture
def db(tmp_path: Path) -> SourcesDatabase:
    """Base mínima con la tabla `sources` y su índice por nombre."""
    path = tmp_path / "bindings.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE sources (path TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL, "
        "kind TEXT NOT NULL, source BLOB NOT NULL)"
    )
    conn.execute("CREATE INDEX idx_sources_name ON sources(name)")
    for file_path, text in FILES.items():
        conn.execute(
            "INSERT INTO sources (path, name, kind, source) VALUES (?, ?, ?, ?)",
            (
                file_path,
                file_path.rsplit("/", 1)[-1],
                "header" if file_path.endswith(".h") else "devicetree",
                zlib.compress(text.encode("utf-8")),
            ),
        )
    conn.commit()
    conn.close()
    return SourcesDatabase(path)


def test_encuentra_por_sufijo_de_ruta(db: SourcesDatabase):
    """`dt-bindings/gpio/gpio.h` localiza la cabecera aunque la ruta sea más larga."""
    found = db.find_by_suffix("dt-bindings/gpio/gpio.h")

    assert found is not None
    assert found.path == "vendor/dt-bindings/gpio/gpio.h"
    assert "otro vendedor" in found.text


def test_gana_la_ruta_mas_corta(db: SourcesDatabase):
    """Con varias candidatas se queda la más corta, como el viejo ORDER BY."""
    assert db.find_by_suffix("gpio/gpio.h").path == "vendor/dt-bindings/gpio/gpio.h"
    assert db.find_by_suffix("gpio.h").path == "gpio.h"


def test_la_ruta_exacta_tambien_vale(db: SourcesDatabase):
    """Una ruta completa se encuentra igual que un sufijo."""
    exact = "kernel/linux/include/dt-bindings/gpio/gpio.h"

    assert db.find_by_suffix(exact).path == exact


def test_normaliza_barras_y_prefijo_relativo(db: SourcesDatabase):
    """`./`, y las barras de Windows, no impiden encontrar el fichero."""
    assert db.find_by_suffix("./xilinx/zynqmp.dtsi").path == "xilinx/zynqmp.dtsi"
    assert db.find_by_suffix("xilinx\\zynqmp.dtsi").path == "xilinx/zynqmp.dtsi"


def test_un_nombre_que_no_esta_no_se_inventa(db: SourcesDatabase):
    """Sin coincidencia se devuelve None, no lo más parecido."""
    assert db.find_by_suffix("dt-bindings/clock/inventado.h") is None
    # Mismo nombre de fichero pero otro directorio: no es un sufijo válido.
    assert db.find_by_suffix("otro/sitio/gpio.h") is None


def test_sin_tabla_no_falla(tmp_path: Path):
    """Una base sin `sources` (ingesta a medias) devuelve None en vez de romper."""
    empty = tmp_path / "vacia.db"
    sqlite3.connect(empty).close()

    assert SourcesDatabase(empty).find_by_suffix("gpio.h") is None


# ----------------------------------------------------------------------
# Qué fichero declara un nodo (`find_declaring_include`)
# ----------------------------------------------------------------------
# Lo pide "ver en el editor DTS" del grafo: el árbol que se dibuja está
# fusionado, así que la línea de un nodo traído de un `.dtsi` cuenta sobre
# *ese* fichero. Saltar a ella sobre el documento abierto lleva a una línea
# cualquiera, o a ninguna si es más corto.

CADENA = {
    "board.dts": '#include "soc.dtsi"\n/ {\n    model = "placa";\n};\n',
    # El SoC incluye a su vez otro fichero, y el nodo que interesa lo declara
    # ese de más abajo: es lo que obliga a mirar el árbol propio de cada
    # inclusión en vez del ya fusionado.
    "soc.dtsi": '#include "sub.dtsi"\n/ {\n    axi {\n        uart@1 {\n'
    '            compatible = "a,b";\n        };\n    };\n};\n',
    "sub.dtsi": '/ {\n    axi {\n        i2c@ff030000 {\n'
    '            compatible = "c,d";\n        };\n    };\n};\n',
}


@pytest.fixture
def cadena(tmp_path: Path) -> SourcesDatabase:
    """Base con una cadena `board.dts` -> `soc.dtsi` -> `sub.dtsi`."""
    path = tmp_path / "cadena.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE sources (path TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL, "
        "kind TEXT NOT NULL, source BLOB NOT NULL)"
    )
    conn.execute("CREATE INDEX idx_sources_name ON sources(name)")
    for file_path, text in CADENA.items():
        conn.execute(
            "INSERT INTO sources (path, name, kind, source) VALUES (?, ?, ?, ?)",
            (file_path, file_path, "devicetree", zlib.compress(text.encode("utf-8"))),
        )
    conn.commit()
    conn.close()
    return SourcesDatabase(path)


def test_dice_que_fichero_declara_cada_nodo(cadena: SourcesDatabase):
    """El fichero que lo escribe, y su línea dentro de él."""
    from kernelgrove.api.includes import IncludeResolver
    from kernelgrove.dts_engine.parser import parse_dts_source

    resolver = IncludeResolver(cadena)
    result = parse_dts_source(CADENA["board.dts"])

    encontrado = resolver.find_declaring_include(
        result.includes, "board.dts", "axi/uart@1"
    )
    assert encontrado is not None
    include, line = encontrado
    assert include.source.path == "soc.dtsi"
    assert CADENA["soc.dtsi"].splitlines()[line - 1].strip() == "uart@1 {"


def test_un_nodo_de_un_include_anidado_se_atribuye_a_su_fichero(
    cadena: SourcesDatabase,
):
    """No al primero de la cadena, cuya línea ahí no significa nada.

    Es la razón de mirar el árbol **propio** de cada inclusión y no el que
    devuelve la caché, que ya viene con lo anidado fusionado dentro.
    """
    from kernelgrove.api.includes import IncludeResolver
    from kernelgrove.dts_engine.parser import parse_dts_source

    resolver = IncludeResolver(cadena)
    result = parse_dts_source(CADENA["board.dts"])

    include, line = resolver.find_declaring_include(
        result.includes, "board.dts", "axi/i2c@ff030000"
    )
    assert include.source.path == "sub.dtsi"
    assert CADENA["sub.dtsi"].splitlines()[line - 1].strip() == "i2c@ff030000 {"


def test_un_nodo_que_no_declara_nadie_no_se_inventa(cadena: SourcesDatabase):
    """Sin coincidencia, None: mejor decirlo que saltar a una línea cualquiera."""
    from kernelgrove.api.includes import IncludeResolver
    from kernelgrove.dts_engine.parser import parse_dts_source

    resolver = IncludeResolver(cadena)
    result = parse_dts_source(CADENA["board.dts"])

    assert (
        resolver.find_declaring_include(result.includes, "board.dts", "axi/spi@9")
        is None
    )
