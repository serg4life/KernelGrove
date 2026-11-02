"""El estado que dejó el nombre anterior se recoge, y solo una vez.

La aplicación se llamaba DTstudio. Cambiarle el nombre no puede costarle al
usuario lo que ya tenía configurado, así que esto comprueba
las tres piezas que `kernelgrove.legacy` trae: el directorio de estado, las
variables de entorno y los ajustes de Qt.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QSettings

from kernelgrove import legacy


def test_el_directorio_de_estado_se_mueve(tmp_path, monkeypatch):
    """Se mueve, no se copia: el estado no puede quedar en dos sitios."""
    viejo = tmp_path / ".dtstudio"
    viejo.mkdir()
    (viejo / "estado.json").write_text("CLAVE")
    nuevo = tmp_path / ".kernelgrove"
    monkeypatch.setattr(legacy, "_DIR_VIEJO", viejo)
    monkeypatch.setattr(legacy, "_DIR_NUEVO", nuevo)

    legacy.migrate_state()

    assert (nuevo / "estado.json").read_text() == "CLAVE"
    assert not viejo.exists()


def test_con_estado_nuevo_no_se_toca_el_viejo(tmp_path, monkeypatch):
    """Con las dos versiones presentes manda la nueva, que es la que se usa."""
    viejo = tmp_path / ".dtstudio"
    viejo.mkdir()
    (viejo / "estado.json").write_text("VIEJA")
    nuevo = tmp_path / ".kernelgrove"
    nuevo.mkdir()
    (nuevo / "estado.json").write_text("NUEVA")
    monkeypatch.setattr(legacy, "_DIR_VIEJO", viejo)
    monkeypatch.setattr(legacy, "_DIR_NUEVO", nuevo)

    legacy.migrate_state()

    assert (nuevo / "estado.json").read_text() == "NUEVA"
    assert (viejo / "estado.json").read_text() == "VIEJA"


def test_las_variables_viejas_valen_como_las_nuevas(monkeypatch):
    """Un alias por prefijo, no uno por variable: son una docena y crecen."""
    monkeypatch.setenv("DTSTUDIO_DB_PATH", "/tmp/vieja.db")
    monkeypatch.delenv("KERNELGROVE_DB_PATH", raising=False)

    legacy.alias_env()

    assert os.environ["KERNELGROVE_DB_PATH"] == "/tmp/vieja.db"


def test_la_variable_nueva_gana_a_la_vieja(monkeypatch):
    """Quien ha puesto las dos está diciendo cuál quiere."""
    monkeypatch.setenv("DTSTUDIO_DB_PATH", "/tmp/vieja.db")
    monkeypatch.setenv("KERNELGROVE_DB_PATH", "/tmp/nueva.db")

    legacy.alias_env()

    assert os.environ["KERNELGROVE_DB_PATH"] == "/tmp/nueva.db"


def test_los_ajustes_de_qt_se_traen_si_no_hay_nuevos(tmp_path, monkeypatch):
    """Y no se tocan si ya hay algo escrito con el nombre nuevo.

    Con `setPath` a un temporal, como el resto de las pruebas que escriben
    ajustes: la configuración del usuario no se toca.
    """
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    monkeypatch.setattr(legacy, "_DIR_VIEJO", tmp_path / "no-existe")
    monkeypatch.setattr(legacy, "_DIR_NUEVO", tmp_path / "tampoco")

    from kernelgrove.main import SETTINGS_APP, SETTINGS_ORG

    # Otras pruebas de la misma sesión ya han escrito ajustes con el nombre
    # nuevo —comparten el `XDG_CONFIG_HOME` temporal de `conftest`— y con
    # algo escrito la migración no hace nada, que es justo lo correcto. Se
    # vacía para preguntar lo que esta prueba pregunta.
    QSettings(SETTINGS_ORG, SETTINGS_APP).clear()

    viejos = QSettings(*legacy._QT_VIEJO)
    viejos.setValue("db/path", "/tmp/elegida.db")
    viejos.sync()

    legacy.migrate_state()

    assert QSettings(SETTINGS_ORG, SETTINGS_APP).value("db/path") == "/tmp/elegida.db"

    # Y con algo escrito con el nombre nuevo, no se toca.
    QSettings(SETTINGS_ORG, SETTINGS_APP).setValue("db/path", "/tmp/actual.db")
    legacy.migrate_state()
    assert QSettings(SETTINGS_ORG, SETTINGS_APP).value("db/path") == "/tmp/actual.db"
