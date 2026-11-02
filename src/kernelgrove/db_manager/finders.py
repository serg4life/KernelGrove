from pathlib import Path
from typing import Iterable


def iter_yaml_files(root: Path) -> Iterable[Path]:
    """Recorre `root` recursivamente y devuelve los ficheros con extensión .yaml/.yml"""
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".yaml", ".yml"}:
            yield path


def iter_source_files(root: Path) -> Iterable[Path]:
    """Recorre `root` y devuelve los fuentes que deben guardarse en la base.

    Incluye device trees (`.dts`, `.dtsi`) y **todas** las cabeceras `.h`
    que estos puedan incluir: las de `dt-bindings`, y también las que viven
    junto a los propios `.dts` (`xlnx-zynqmp-clk.h` al lado de
    `zynqmp-clk-ccf.dtsi`, por ejemplo). La aplicación instalada no tiene el
    kernel clonado, así que todo lo que el editor deba poder abrir —y todo
    lo que `cpp` necesite para compilar un árbol de la base— tiene que estar
    almacenado.

    Antes solo entraban las de `dt-bindings`, y con eso un `#include
    "vecino.h"` no se podía resolver: compilar esa placa desde la base
    fallaba con «No such file or directory» sobre un fichero que el kernel
    sí tiene. **No entra cualquier `.h`**: el kernel tiene 26 891 y solo
    1 241 están donde un device tree puede alcanzarlos —los 1 164 de
    `dt-bindings` y los 77 que viven dentro de un directorio `dts/`—; el
    resto son cabeceras de C que ningún `.dts` incluye.
    """
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in {".dts", ".dtsi"}:
            yield path
        elif suffix == ".h" and {"dt-bindings", "dts"} & set(path.parts):
            yield path


def iter_devicetree_files(root: Path) -> Iterable[Path]:
    """Recorre `root` recursivamente y devuelve ficheros `.dts`/`.dtsi`.

    Incluye ambas extensiones porque un SoC y una board se distinguen por el
    contenido del árbol (ver `records.classify_devicetree`), no por si el
    fichero es un include (`.dtsi`) o un documento completo (`.dts`): un SoC
    partido en varios ficheros puede tener su nodo `/cpus` en cualquiera de
    los dos.
    """
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".dts", ".dtsi"}:
            yield path
