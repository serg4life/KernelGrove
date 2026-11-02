from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from kernelgrove.db_manager.schemas import top_level_compatibles
from kernelgrove.dt_model.hardware import extract_hardware
from kernelgrove.dt_model.model import DeviceTreeNode, is_valid_compatible

_CPU_NODE_NAME = re.compile(r"^cpu(@.*)?$")


def _has_cpu_cores(root: DeviceTreeNode) -> bool:
    """Indica si `root` declara `/cpus` con al menos un hijo `cpu@...`.

    Es la señal de que este árbol define un SoC (el cluster de CPUs), a
    diferencia de un fragmento de periférico (PMIC, panel...) que también
    vive en un `.dtsi` pero no lo declara.
    """
    cpus_node = root.find_child("cpus")
    if cpus_node is None:
        return False
    return any(_CPU_NODE_NAME.match(child.name) for child in cpus_node.children)


def classify_devicetree(text: str, root: DeviceTreeNode) -> Optional[str]:
    """Clasifica un `.dts`/`.dtsi` ya parseado como 'soc', 'board' o None.

    - 'soc': el árbol declara `/cpus/cpu@...` propio. Se comprueba antes que
      "/dts-v1/;" porque un SoC repartido en varios ficheros puede tener el
      `/dts-v1/;` en el `.dts` que lo incluye y `/cpus` en el `.dtsi` incluido.
    - 'board': no declara `cpus` propio (lo hereda de su SoC vía `#include`,
      que este parser no resuelve) pero es un documento completo
      ("/dts-v1/;"), es decir, una board o descripción de hardware
      compilable por sí misma.
    - None: ni una cosa ni la otra (PMICs, paneles, overlays y demás
      fragmentos `.dtsi` que no son ni el SoC ni una board) — se descarta.

    Hueco conocido: una board "variante" que solo hace `#include` de otra
    `.dts` (p. ej. una versión "-emmc" de una board base) no declara ni
    `cpus` ni su propio `/dts-v1/;` — ambos los hereda del fichero incluido,
    que este parser no resuelve — así que cae aquí como None en lugar de
    'board'. Igual que el resto de resolución de includes en la ingesta,
    arreglarlo requeriría fusionar el árbol antes de clasificar.
    """
    if _has_cpu_cores(root):
        return "soc"
    if "/dts-v1/" in text:
        return "board"
    return None


def normalize_value(value: Any) -> List[str]:
    """Aplana un valor YAML arbitrario (str, list, dict o None) en lista de strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: List[str] = []
        for item in value:
            result.extend(normalize_value(item))
        return result
    if isinstance(value, dict):
        result: List[str] = []
        for item in value.values():
            result.extend(normalize_value(item))
        return result
    return []


def parse_compatible(property_node: Any) -> List[str]:
    """Extrae los valores posibles de `compatible` de un nodo de schema YAML.

    Recorre recursivamente las formas habituales en los bindings del kernel
    (`const`, `enum`, `oneOf`, `anyOf`, `items`, `contains`, `properties`)
    hasta reducirlas a una lista plana de strings de compatible.
    """
    if property_node is None:
        return []
    if isinstance(property_node, dict):
        if "const" in property_node:
            return normalize_value(property_node["const"])
        if "enum" in property_node:
            return normalize_value(property_node["enum"])
        if "oneOf" in property_node:
            result: List[str] = []
            for item in property_node["oneOf"] or []:
                result.extend(parse_compatible(item))
            return result
        if "anyOf" in property_node:
            result = []
            for item in property_node["anyOf"] or []:
                result.extend(parse_compatible(item))
            return result
        if "items" in property_node:
            return parse_compatible(property_node["items"])
        if "contains" in property_node:
            return parse_compatible(property_node["contains"])
        if "properties" in property_node:
            return parse_compatible(property_node["properties"])
        return normalize_value(property_node)
    if isinstance(property_node, list):
        result: List[str] = []
        for item in property_node:
            result.extend(parse_compatible(item))
        return result
    if isinstance(property_node, str):
        return [property_node]
    return []


def extract_vendor(compatible: List[str]) -> str | None:
    """Deriva el vendor a partir del primer compatible (prefijo antes de la coma)."""
    if not compatible:
        return None
    first_compatible = compatible[0]
    if "," in first_compatible:
        return first_compatible.split(",", 1)[0]
    return first_compatible


def relative_key(path: Path, root: Path) -> str:
    """Ruta de `path` relativa a la raíz de ingesta, en formato POSIX.

    Es la clave con la que se guardan y se buscan los fuentes: relativa y con
    separadores «/» para que la base de datos sea portable entre máquinas.

    Normaliza con `os.path.abspath`, no con `Path.resolve()`: este último
    también sigue symlinks, y varias cabeceras `dt-bindings/*.h` lo son
    (`linux-event-codes.h` -> `../../uapi/linux/input-event-codes.h`). Con
    `resolve()` la clave guardada era la del objetivo del enlace, no la del
    propio fichero, así que ningún `#include
    <dt-bindings/input/linux-event-codes.h>` la encontraba nunca.
    """
    try:
        abs_path = Path(os.path.abspath(path))
        abs_root = Path(os.path.abspath(root))
        return abs_path.relative_to(abs_root).as_posix()
    except ValueError:
        return path.name


def build_record_sources(path: Path, root: Path) -> Dict[str, Any]:
    """Construye el registro de un fuente para la tabla `sources`.

    Guarda el texto tal cual: la aplicación instalada no tiene el kernel
    clonado, así que el editor solo puede abrir estos ficheros si su contenido
    viaja dentro de la base de datos.
    """
    suffix = path.suffix.lower().lstrip(".")
    return {
        "path": relative_key(path, root),
        "name": path.name,
        "kind": "header" if suffix == "h" else suffix,
        "text": path.read_text(encoding="utf-8", errors="replace"),
    }


def build_record_devicetree(path: Path, doc: DeviceTreeNode) -> Dict[str, Any]:
    """Construye el registro de un SoC o board a partir de su árbol ya parseado.

    Común a las tablas `socs` y `boards`: ambas guardan la misma forma de
    registro, solo cambia qué ficheros se clasifican para cada una (ver
    `classify_devicetree`). A diferencia de `build_record_bindings`, `doc` no
    es un dict YAML sino el `DeviceTreeNode` raíz, del que se saca la
    **identidad** —compatible y vendor del nodo raíz, y `name` del nombre de
    fichero— y **qué hardware describe** (`extract_hardware`: arquitectura,
    núcleos, RAM, reloj y modelo). El árbol no se serializa: el
    contenido del device tree ya vive
    en `sources`, y volver a guardarlo aquí eran 48 MB de un dato que se
    obtiene parseando ese fuente.
    """
    compatible = [item for item in doc.compatible if is_valid_compatible(item)]
    primary_compatible = compatible[0] if compatible else ""
    vendor = extract_vendor(compatible)

    return {
        "file_path": str(path),
        "name": path.stem,
        "compatible": compatible,
        "primary_compatible": primary_compatible,
        "vendor": vendor,
        **extract_hardware(doc),
    }


def build_record_bindings(path: Path, doc: Dict[str, Any]) -> Dict[str, Any]:
    """Construye el registro de un binding a partir de su YAML ya parseado.

    Extrae compatibles, vendor primario, título y descripción, y conserva
    el documento original en `raw` para su posterior serialización.

    Solo cuentan los compatibles que el binding declara para su propio nodo
    (`schemas.top_level_compatibles`). Un YAML que no declare ninguno no
    describe ningún dispositivo —son los schemas de propiedades comunes,
    `rtc.yaml` o `riscv/extensions.yaml`— y sale de aquí con
    `primary_compatible` vacío, que es la señal para que `storage` no lo
    registre como binding. Los compatibles de sus subnodos se registran en
    la tabla `schema_compatibles` durante la ingesta de schemas.
    """
    compatible = [
        item for item in top_level_compatibles(doc) if is_valid_compatible(item)
    ]
    primary_compatible = compatible[0] if compatible else ""
    vendor = extract_vendor(compatible)

    return {
        "file_path": str(path),
        "title": doc.get("title"),
        "description": doc.get("description"),
        "compatible": compatible,
        "primary_compatible": primary_compatible,
        "vendor": vendor,
        "raw": doc,
    }
