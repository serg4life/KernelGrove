from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml


def load_yaml_document(path: Path) -> Optional[Dict[str, Any]]:
    """Carga un fichero YAML (incluye multi-documento) y devuelve el primer dict útil.

    Si el fichero contiene varios documentos YAML separados por `---`, se
    devuelve el primero que sea un `dict`. Devuelve None si el fichero está
    vacío o no contiene ningún documento tipo dict.

    Lanza RuntimeError si el YAML no se puede parsear.
    """
    try:
        with path.open("r", encoding="utf-8") as stream:
            docs = list(yaml.safe_load_all(stream))
    except yaml.YAMLError as exc:
        raise RuntimeError(f"Error leyendo YAML en {path}: {exc}") from exc

    if not docs:
        return None
    if len(docs) == 1:
        return docs[0]

    for doc in docs:
        if isinstance(doc, dict):
            return doc
    return None
