"""Que las herramientas que el instalador de Windows deja al lado se vean.

En Linux `dtc` y `cpp` los pone la distribución en el `PATH` y no hay nada
que probar. En Windows los descarga el instalador a un `tools\\` junto al
ejecutable (`packaging/windows/kernelgrove.iss`) y **no** toca el `PATH`, así
que si `toolchain` deja de mirar ahí, compilar deja de funcionar sin que
nada más lo note.
"""

from __future__ import annotations

import os
import sys

from kernelgrove.api import toolchain


def _falso_ejecutable(carpeta, nombre):
    """Crea algo que `shutil.which` acepte como programa instalado."""
    binario = carpeta / (f"{nombre}.exe" if os.name == "nt" else nombre)
    binario.write_text("")
    binario.chmod(0o755)
    return binario


def test_encuentra_lo_que_el_instalador_deja_junto_al_ejecutable(
    tmp_path, monkeypatch
):
    """Empaquetada, mira su propio `tools/`; en un checkout, no se lo inventa."""
    herramientas = tmp_path / "tools"
    herramientas.mkdir()
    dtc = _falso_ejecutable(herramientas, "dtc")
    # Un PATH donde no está, para que la única vía sea la del instalador.
    monkeypatch.setenv("PATH", str(tmp_path / "vacio"))
    monkeypatch.setattr(sys, "executable", str(tmp_path / "kernelgrove.exe"))

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert toolchain._first_on_path(("dtc",)) == str(dtc)

    monkeypatch.delattr(sys, "frozen", raising=False)
    assert toolchain._first_on_path(("dtc",)) is None
