"""Comprobaciones del control de versiones (`api/git_repo.py`).

Se trabaja contra un repositorio de git de verdad creado en un directorio
temporal: lo único no trivial de este módulo es el parseo de la salida de
`git status --porcelain -z` y de `git log --format=…`, y eso solo se puede
comprobar contra el git instalado.
"""

from __future__ import annotations

import subprocess

import pytest

from kernelgrove.api import git_repo

pytestmark = pytest.mark.skipif(
    not git_repo.git_available(), reason="no hay git instalado"
)


@pytest.fixture()
def repo(tmp_path):
    """Repositorio con una versión guardada y un fichero de device tree."""
    created = git_repo.init_repo(tmp_path)
    # Identidad local: la global puede no existir en una máquina de CI.
    for key, value in (("user.name", "Test"), ("user.email", "test@example.com")):
        subprocess.run(["git", "config", key, value], cwd=tmp_path, check=True)
    (tmp_path / "board.dts").write_text("/dts-v1/;\n/ {\n};\n", encoding="utf-8")
    created.stage_all()
    created.save_version("Initial version")
    return created


def test_un_repositorio_recien_creado_no_tiene_versiones(tmp_path):
    created = git_repo.init_repo(tmp_path)
    assert created.has_commits() is False
    assert created.versions() == []


def test_find_repo_devuelve_none_fuera_de_un_repositorio(tmp_path):
    fuera = tmp_path / "suelta"
    fuera.mkdir()
    assert git_repo.find_repo(fuera) is None


def test_find_repo_encuentra_la_raiz_desde_una_subcarpeta(repo):
    dentro = repo.root / "arch" / "arm"
    dentro.mkdir(parents=True)
    encontrado = git_repo.find_repo(dentro)
    assert encontrado is not None
    assert encontrado.root.resolve() == repo.root.resolve()


def test_una_version_se_nombra_con_su_sha_no_con_un_numero(repo):
    """Los «v1, v2…» se los inventaba la interfaz y no coincidían con git."""
    versiones = repo.versions()
    assert [v.message for v in versiones] == ["Initial version"]
    assert versiones[0].short and versiones[0].sha.startswith(versiones[0].short)


def test_un_fichero_modificado_aparece_como_cambio_sin_preparar(repo):
    (repo.root / "board.dts").write_text(
        '/dts-v1/;\n/ {\n\tmodel = "Placa";\n};\n', encoding="utf-8"
    )
    status = repo.status()
    assert status.staged == []
    assert status.unstaged == [git_repo.FileChange(path="board.dts", status="M")]
    assert 'model = "Placa"' in repo.working_diff("board.dts")


def test_un_fichero_nuevo_se_ve_entero_como_anadido(repo):
    (repo.root / "soc.dtsi").write_text("/ {\n};\n", encoding="utf-8")
    assert repo.status().unstaged == [
        git_repo.FileChange(path="soc.dtsi", status="?", untracked=True)
    ]
    # Sin seguimiento todavía: el diff se saca contra /dev/null.
    assert "+/ {" in repo.working_diff("soc.dtsi")


def test_preparar_un_fichero_lo_cambia_de_grupo(repo):
    (repo.root / "board.dts").write_text("/dts-v1/;\n", encoding="utf-8")
    (repo.root / "soc.dtsi").write_text("/ {\n};\n", encoding="utf-8")

    repo.stage(["board.dts"])

    status = repo.status()
    assert [change.path for change in status.staged] == ["board.dts"]
    # El otro se queda donde estaba: preparar es fichero a fichero.
    assert [change.path for change in status.unstaged] == ["soc.dtsi"]


def test_lo_preparado_y_lo_no_preparado_tienen_diffs_distintos(repo):
    board = repo.root / "board.dts"
    board.write_text("/dts-v1/;\n// preparado\n", encoding="utf-8")
    repo.stage(["board.dts"])
    board.write_text("/dts-v1/;\n// preparado\n// suelto\n", encoding="utf-8")

    assert "+// preparado" in repo.working_diff("board.dts", staged=True)
    assert "+// suelto" in repo.working_diff("board.dts")
    assert "+// suelto" not in repo.working_diff("board.dts", staged=True)


def test_sacar_de_preparado_no_toca_el_disco(repo):
    board = repo.root / "board.dts"
    board.write_text("/dts-v1/;\n// cambio\n", encoding="utf-8")
    repo.stage(["board.dts"])

    repo.unstage(["board.dts"])

    assert repo.status().staged == []
    assert [change.path for change in repo.status().unstaged] == ["board.dts"]
    assert "// cambio" in board.read_text(encoding="utf-8")


def test_descartar_deshace_solo_los_ficheros_elegidos(repo):
    original = (repo.root / "board.dts").read_text(encoding="utf-8")
    (repo.root / "board.dts").write_text("roto\n", encoding="utf-8")
    (repo.root / "otro.dtsi").write_text("/ {\n};\n", encoding="utf-8")
    repo.stage(["otro.dtsi"])
    repo.save_version("Otro fichero")
    (repo.root / "otro.dtsi").write_text("tambien roto\n", encoding="utf-8")

    repo.discard([git_repo.FileChange(path="board.dts", status="M")])

    assert (repo.root / "board.dts").read_text(encoding="utf-8") == original
    # El que no se eligió sigue como estaba, roto.
    assert (repo.root / "otro.dtsi").read_text(encoding="utf-8") == "tambien roto\n"


def test_descartar_un_fichero_nuevo_lo_borra(repo):
    nuevo = repo.root / "sobra.dtsi"
    nuevo.write_text("/ {\n};\n", encoding="utf-8")

    repo.discard(
        [git_repo.FileChange(path="sobra.dtsi", status="?", untracked=True)]
    )

    assert not nuevo.exists()


def test_solo_se_guarda_lo_preparado(repo):
    (repo.root / "board.dts").write_text("/dts-v1/;\n", encoding="utf-8")
    (repo.root / "fuera.dtsi").write_text("/ {\n};\n", encoding="utf-8")
    repo.stage(["board.dts"])

    repo.save_version("Peripheral added")

    status = repo.status()
    assert status.staged == []
    # Lo que no se preparó sigue esperando fuera de la versión.
    assert [change.path for change in status.unstaged] == ["fuera.dtsi"]


def test_guardar_una_version_vacia_la_lista_de_cambios(repo):
    (repo.root / "board.dts").write_text("/dts-v1/;\n", encoding="utf-8")
    repo.stage_all()
    repo.save_version("Peripheral added")
    assert repo.status().is_empty()
    assert [v.message for v in repo.versions()] == [
        "Peripheral added",
        "Initial version",
    ]


def test_el_historial_se_puede_filtrar_por_fichero(repo):
    (repo.root / "otro.dtsi").write_text("/ {\n};\n", encoding="utf-8")
    repo.stage_all()
    repo.save_version("Otro fichero")
    assert [v.message for v in repo.versions(path="otro.dtsi")] == ["Otro fichero"]


def test_checkout_lleva_a_una_version_y_deja_ver_que_se_esta_fuera_de_la_rama(repo):
    """Es el `checkout` de git, con lo bueno y lo raro: HEAD desprendido.

    Lo que antes había aquí era un `checkout <sha> -- .`, que solo devolvía
    el contenido para no dejar a nadie fuera de la rama. La objeción era
    buena y la respuesta no: lo que hacía falta era **enseñar dónde se está**
    (`HeadState.detached`) y por dónde se vuelve: las ramas que apuntan a
    cada versión (`Version.branches`), que el panel dibuja como etiqueta
    sobre el grafo.
    """
    original = (repo.root / "board.dts").read_text(encoding="utf-8")
    rama = repo.branch()
    (repo.root / "board.dts").write_text("roto\n", encoding="utf-8")
    repo.stage_all()
    repo.save_version("Cambio a deshacer")
    primera = repo.versions()[-1]

    assert not repo.head().detached

    repo.checkout(primera.sha)

    assert (repo.root / "board.dts").read_text(encoding="utf-8") == original
    estado = repo.head()
    assert estado.detached, "hay que poder ver que ya no se está en una rama"
    assert estado.sha == primera.sha
    assert not estado.branch

    # Y desde ahí se sigue viendo todo el historial: `git log` cuenta desde
    # HEAD, así que sin esto la lista se quedaba en esta versión y sus
    # antepasadas — justo cuando hace falta ver las de después para volver.
    assert len(repo.versions()) >= 2

    # La salida es la etiqueta de la rama sobre su propio commit, y **no
    # depende del camino**: mirar una segunda versión estando ya fuera de la
    # rama era lo que dejaba sin salida al `@{-1}` que había antes —al
    # segundo salto ya apunta a un sha suelto, git no sabe darle nombre y
    # devolvía vacío.
    repo.checkout(repo.versions()[-1].sha)
    assert repo.head().detached
    assert any(rama in version.branches for version in repo.versions())

    repo.checkout(rama)
    assert repo.head().branch == rama
    assert not repo.head().detached


def test_un_comando_que_falla_lanza_giterror(repo):
    with pytest.raises(git_repo.GitError):
        repo.version_diff("no-existe-este-sha")


def test_reset_devuelve_la_rama_a_una_version_anterior(repo):
    """Lo que se pierde es la historia posterior, no el trabajo."""
    (repo.root / "board.dts").write_text("cambiado\n", encoding="utf-8")
    repo.stage_all()
    repo.save_version("Cambio a tirar")
    primera = repo.versions()[-1]

    repo.reset(primera.sha)

    assert [v.message for v in repo.versions()] == ["Initial version"]
    # Los ficheros siguen como estaban: el cambio vuelve a ser un cambio
    # sin guardar, no algo perdido.
    assert (repo.root / "board.dts").read_text(encoding="utf-8") == "cambiado\n"
    assert not repo.status().is_empty()


def test_reset_hard_se_lleva_tambien_los_ficheros(repo):
    """La otra mitad de la promesa: con `hard` no queda nada que rehacer."""
    original = (repo.root / "board.dts").read_text(encoding="utf-8")
    (repo.root / "board.dts").write_text("cambiado\n", encoding="utf-8")
    repo.stage_all()
    repo.save_version("Cambio a tirar")
    primera = repo.versions()[-1]

    repo.reset(primera.sha, hard=True)

    assert [v.message for v in repo.versions()] == ["Initial version"]
    assert (repo.root / "board.dts").read_text(encoding="utf-8") == original
    assert repo.status().is_empty()


def test_lo_editado_y_sin_preparar_se_sabe_linea_a_linea(repo):
    """Es lo que el editor pinta en su margen, y se mide contra el texto vivo.

    Contra el texto que hay escrito, no contra el fichero del disco: mientras
    se escribe el disco va por detrás de lo que se está viendo.
    """
    preparado = repo.file_in_index("board.dts")
    assert preparado is not None

    escrito = preparado.replace("/dts-v1/;", "/dts-v2/;") + "// nueva\n"
    cambios = git_repo.changed_lines(preparado, escrito)

    assert cambios.modified, "la primera línea ha cambiado"
    assert cambios.added, "la última línea es nueva"
    assert not cambios.deleted

    # Un fichero que no está en el índice no tiene contra qué medirse.
    assert repo.file_in_index("no-existe.dts") is None
    assert git_repo.changed_lines(None, "a\nb\n").added == {1, 2}


def test_preparar_un_cambio_lo_saca_del_margen(repo):
    """Criterio de VS Code: la referencia del margen es el índice, no HEAD.

    Preparado ya está descrito en la lista de cambios como «lo que va en la
    próxima versión»; seguir marcándolo en el editor lo diría dos veces.
    """
    fichero = repo.root / "board.dts"
    escrito = fichero.read_text(encoding="utf-8").replace("/dts-v1/;", "/dts-v2/;")
    fichero.write_text(escrito, encoding="utf-8")

    assert git_repo.changed_lines(repo.file_in_index("board.dts"), escrito).modified

    repo.stage(["board.dts"])

    cambios = git_repo.changed_lines(repo.file_in_index("board.dts"), escrito)
    assert cambios.is_empty(), "preparado deja de marcarse"
