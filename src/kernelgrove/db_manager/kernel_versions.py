"""Desde qué versión del kernel existe cada binding.

Es un dato que no está escrito en ninguna parte del propio binding: está en
la historia del repositorio. Y la pregunta que se responde aquí es «desde
qué release aparece este fichero», que es lo mismo que «desde cuándo el
kernel lo trae».

**Se pregunta por etiquetas, no por historia.** Lo directo —`git log
--diff-filter=A -- <fichero>` por cada uno de los 5 663 bindings— recorre
1,3 millones de commits una vez por fichero y no termina; leer el árbol de
cada release (`git ls-tree`) y quedarse con la primera en la que aparece
cada ruta son 112 lecturas de árbol y tarda ocho segundos. Es además más
honesto: lo que interesa es en qué versión *se publicó*, no en qué commit
se escribió.

**La extensión se ignora al comparar.** Los bindings se convirtieron en
masa de `.txt` a `.yaml` entre 2018 y 2021, y esa conversión borra un
fichero y añade otro: mirando solo el `.yaml`, media docena de bindings de
2013 dirían que existen desde la v5.x. Sin extensión, `serial/pl011.txt` y
`serial/pl011.yaml` son el mismo binding y la respuesta es la v3.10, que es
la verdadera.

Solo se ejecuta en la ingesta, contra el checkout del kernel: la aplicación
instalada lee la columna ya calculada y no sabe nada de git.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List

# Etiqueta de una release: `v6.6`, `v2.6.11`. Se dejan fuera las `-rc`, que
# no son versiones publicadas, y las etiquetas raras que el repo arrastra
# (`v2.6.11-tree`, `v2.6.13-dontuse`).
_RELEASE_TAG = re.compile(r"^v\d+(\.\d+)*$")

# Prefijo bajo el que viven los bindings dentro del árbol del kernel.
BINDINGS_PREFIX = "Documentation/devicetree/bindings/"


def git_available() -> bool:
    """Si hay un `git` con el que preguntar."""
    return shutil.which("git") is not None


def _run(repo: Path, *args: str) -> str:
    """Ejecuta git en el repositorio y devuelve su salida, o cadena vacía."""
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return done.stdout if done.returncode == 0 else ""


def _version_key(tag: str) -> tuple:
    """Orden natural de una etiqueta: v2.6.11 antes que v3.0, y v6.9 que v6.10."""
    return tuple(int(number) for number in re.findall(r"\d+", tag))


def release_tags(repo: Path) -> List[str]:
    """Las releases del repositorio, de la más antigua a la más nueva."""
    tags = [
        tag
        for tag in _run(repo, "tag", "--list", "v*").split()
        if _RELEASE_TAG.match(tag)
    ]
    tags.sort(key=_version_key)
    return tags


def binding_key(path: str) -> str:
    """Ruta del binding relativa a `bindings/` y sin extensión.

    Vale igual para una ruta del árbol del kernel y para la que guarda
    `schemas.path`, que ya es relativa: el corte por el prefijo no hace nada
    cuando no está.
    """
    relative = path.split(BINDINGS_PREFIX, 1)[-1]
    return re.sub(r"\.(yaml|yml|txt)$", "", relative)


def first_release_by_binding(repo: Path) -> Dict[str, str]:
    """Primera release en la que aparece cada binding, por su ruta sin extensión.

    Devuelve un diccionario vacío si no hay git, si `repo` no es un
    repositorio o si no tiene etiquetas: no tener la historia no es un error,
    solo significa que esta columna se queda sin rellenar.
    """
    if not git_available() or not Path(repo).is_dir():
        return {}
    since: Dict[str, str] = {}
    for tag in release_tags(repo):
        listado = _run(repo, "ls-tree", "-r", "--name-only", tag, "--", BINDINGS_PREFIX)
        for line in listado.splitlines():
            since.setdefault(binding_key(line), tag)
    return since


def version_label(tag: str) -> str:
    """Cómo se enseña una etiqueta: «6.6», sin la «v»."""
    return tag[1:] if tag.startswith("v") else tag
