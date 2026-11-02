"""Desde qué versión del kernel existe cada binding.

Ver `db_manager/kernel_versions.py`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kernelgrove.db_manager.kernel_versions import (
    binding_key,
    first_release_by_binding,
    git_available,
    release_tags,
    version_label,
)


def test_la_clave_ignora_la_extension():
    """Los bindings pasaron de `.txt` a `.yaml` borrando uno y creando otro.

    Mirando solo el `.yaml`, un binding de 2013 diría que existe desde la
    v5.x, que es cuando alguien lo convirtió. Sin extensión son el mismo.
    """
    esperada = "serial/pl011"
    for ruta in (
        "serial/pl011.yaml",
        "serial/pl011.txt",
        "Documentation/devicetree/bindings/serial/pl011.yaml",
    ):
        assert binding_key(ruta) == esperada


def test_sin_repositorio_no_es_un_error(tmp_path):
    """No tener la historia deja la columna vacía, no rompe la ingesta."""
    assert first_release_by_binding(tmp_path / "no-existe") == {}


def test_la_etiqueta_se_enseña_sin_la_uve():
    """`v6.6` se lee «6.6»; la uve es de git, no de la versión."""
    assert version_label("v6.6") == "6.6"
    assert version_label("6.6") == "6.6"


def test_las_releases_van_en_orden_de_version(tmp_path):
    """v6.9 antes que v6.10: ordenar como texto las pone al revés.

    Y las `-rc` no son releases publicadas, así que no cuentan: un binding
    que aparece en la v6.10-rc1 se publica en la v6.10.
    """
    if not git_available():
        pytest.skip("git no está instalado")
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True)

    git("init", "-q")
    for name, valor in (("user.email", "t@t"), ("user.name", "t")):
        git("config", name, valor)
    destino = repo / "Documentation" / "devicetree" / "bindings" / "i2c"
    destino.mkdir(parents=True)
    (destino / "uno.yaml").write_text("x", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "uno")
    for tag in ("v6.10", "v6.9", "v6.10-rc1", "v2.6.11"):
        git("tag", tag)

    assert release_tags(repo) == ["v2.6.11", "v6.9", "v6.10"]
    assert first_release_by_binding(repo) == {"i2c/uno": "v2.6.11"}


def test_un_binding_del_kernel_sale_fechado():
    """Contra el checkout de verdad, si está: es la fuente del dato."""
    repo = Path(__file__).resolve().parents[1] / "kernel" / "linux"
    if not git_available() or not (repo / ".git").exists():
        pytest.skip("hace falta el checkout del kernel con su historia")
    since = first_release_by_binding(repo)
    assert since, "el checkout tiene etiquetas"
    # `pl011.txt` es de 2013 y se convirtió a YAML mucho después: es el caso
    # que la clave sin extensión existe para no estropear.
    assert since.get("serial/pl011") == "v3.10"
