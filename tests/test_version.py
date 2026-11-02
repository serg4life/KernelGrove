"""La versión, escrita en dos sitios que no pueden separarse.

`pyproject.toml` es de donde la leen el `.deb` (`build_deb.sh`) y los dos
`.spec` de PyInstaller; `kernelgrove.__version__` es lo que enseñan la barra de
estado, «Acerca de» y el informe de errores. Tiene que ser un literal: en un
bundle no hay metadatos de paquete que preguntar, así que
`importlib.metadata` ahí devolvería nada. Con dos sitios, lo que queda es
comprobar que dicen lo mismo.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import kernelgrove


def test_la_version_es_la_misma_en_los_dos_sitios():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    declarada = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert kernelgrove.__version__ == declarada["project"]["version"]
