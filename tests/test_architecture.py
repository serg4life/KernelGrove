"""Las reglas de dependencia entre capas, comprobadas en vez de confiadas.

Son la decisión de diseño que sostiene el resto del proyecto —el motor
semántico no conoce la base de datos, la interfaz solo conoce la API— y hasta
ahora solo estaban escritas en CLAUDE.md. Un import de más las rompe en
silencio y no se nota hasta que algo circular explota o hasta que los tests
del motor empiezan a necesitar SQLite.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator, List, Tuple

SRC = Path(__file__).resolve().parents[1] / "src" / "kernelgrove"


def _imported_modules(path: Path) -> Iterator[str]:
    """Módulos `kernelgrove.*` que importa un fichero, sean `import` o `from`."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("kernelgrove"):
                    yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("kernelgrove"):
                yield node.module


def _offending_imports(package: str, forbidden: Tuple[str, ...]) -> List[str]:
    """Imports prohibidos dentro de `package`, como "fichero -> módulo"."""
    found: List[str] = []
    for path in (SRC / package).rglob("*.py"):
        for module in _imported_modules(path):
            if module.startswith(forbidden):
                found.append(f"{path.relative_to(SRC)} -> {module}")
    return found


def test_la_gui_solo_depende_de_la_api():
    """`gui/` no puede tocar la base de datos ni el motor directamente.

    Los tipos del modelo se reexportan desde `api/__init__.py` justo para
    que la interfaz no tenga que importar `dt_model`.
    """
    assert (
        _offending_imports(
            "gui",
            (
                "kernelgrove.db_manager",
                "kernelgrove.dt_model",
                "kernelgrove.dts_engine",
            ),
        )
        == []
    )


def test_el_motor_semantico_no_depende_de_la_base():
    """`dts_engine/` recibe la base inyectada; nunca la importa.

    Es lo que permite que sus pruebas corran sin SQLite y que la ingesta lo
    reutilice: la dirección contraria (`db_manager` importa el parser) sí es
    intencionada.
    """
    assert (
        _offending_imports(
            "dts_engine", ("kernelgrove.api", "kernelgrove.db_manager")
        )
        == []
    )


def test_la_api_no_depende_de_la_ingesta():
    """`api/` es solo lectura; construir la base es cosa de `db_manager`.

    La excepción es `kernelgrove.db_schema`, el número de versión que comparten
    los dos lados y que no importa nada a su vez.
    """
    assert (
        _offending_imports("api", ("kernelgrove.db_manager", "kernelgrove.gui")) == []
    )
