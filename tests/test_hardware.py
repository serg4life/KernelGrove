"""Qué hardware se saca de un device tree, y qué se hereda de sus includes."""

from kernelgrove.db_manager.main import inherit_from_includes
from kernelgrove.dt_model.hardware import extract_hardware
from kernelgrove.dts_engine.parser import parse_dts_source


def _root(text: str):
    """Árbol raíz de un fuente, para no repetir el parseo en cada prueba."""
    return parse_dts_source(text).root


def test_un_soc_declara_su_arquitectura_y_sus_nucleos():
    """Los cpus están en el árbol; no hay que adivinarlos de ningún sitio."""
    hardware = extract_hardware(
        _root(
            """
            / {
                cpus {
                    cpu0: cpu@0 {
                        compatible = "arm,cortex-a9";
                        clock-frequency = <666666687>;
                    };
                    cpu1: cpu@1 { compatible = "arm,cortex-a9"; };
                };
            };
            """
        )
    )
    assert hardware["arch"] == "arm,cortex-a9"
    assert hardware["cores"] == 2
    assert hardware["clock"] == 666666687


def test_la_ram_sale_de_los_tamanos_del_nodo_memory():
    """El `reg` va en pares dirección/tamaño: la RAM son las celdas impares."""
    hardware = extract_hardware(
        _root(
            """
            / {
                model = "Xilinx ZC702 board";
                memory@0 { device_type = "memory"; reg = <0x0 0x40000000>; };
            };
            """
        )
    )
    assert hardware["ram"] == 0x40000000
    assert hardware["model"] == "Xilinx ZC702 board"


def test_lo_que_no_esta_escrito_se_queda_vacio():
    """Ni un cero ni un valor plausible: no saberlo se dice no diciéndolo."""
    hardware = extract_hardware(_root("/ { chosen { }; };"))
    assert hardware == {
        "arch": None,
        "cores": None,
        "ram": None,
        "clock": None,
        "model": None,
    }


def test_una_ram_ridicula_se_descarta():
    """Un `#address-cells = <2>` parte los números y saldrían 4 KB de RAM.

    Sin resolver las celdas no hay forma de distinguir un árbol de 64 bits,
    así que se descarta cualquier total que no llegue a un mega: mejor no
    decir nada que decir una barbaridad.
    """
    hardware = extract_hardware(
        _root("/ { memory@0 { reg = <0x0 0x1000>; }; };")
    )
    assert hardware["ram"] is None


def test_una_board_hereda_del_soc_que_incluye():
    """Sus cpus están en el `.dtsi` del SoC, no en su propio fichero.

    Y solo hereda lo que le falta: su propia RAM y su propio reloj mandan
    sobre los del SoC, que es lo genérico de los dos.
    """
    catalogo = {
        "board.dts": {
            "includes": ["intermedio.dtsi"],
            "hardware": {},
        },
        "intermedio.dtsi": {"includes": ["soc.dtsi"], "hardware": {}},
        "soc.dtsi": {
            "includes": [],
            "hardware": {"arch": "arm,cortex-a9", "cores": 2, "clock": 650_000_000},
        },
    }
    record = {"_file_name": "board.dts", "ram": 1 << 30, "clock": 800_000_000}
    inherit_from_includes(record, catalogo)

    assert record["arch"] == "arm,cortex-a9", "se sigue la cadena de includes"
    assert record["cores"] == 2
    assert record["clock"] == 800_000_000, "lo suyo manda sobre lo heredado"
    assert record["ram"] == 1 << 30


def test_un_include_que_no_existe_no_rompe_la_herencia():
    """La cadena se sigue por nombre de fichero y puede apuntar a nada."""
    record = {"_file_name": "board.dts"}
    inherit_from_includes(
        record, {"board.dts": {"includes": ["falta.dtsi"], "hardware": {}}}
    )
    assert record.get("arch") is None
