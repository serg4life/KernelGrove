"""El idioma de la interfaz: que se cargue, y que esté completo.

El inglés es el idioma **fuente** —lo que está escrito en el código— y por
tanto no puede fallar: si no hay `.qm`, se ve inglés. Lo que sí puede
romperse en silencio es un idioma traducido: basta con añadir un texto nuevo
y no volver a pasar `scripts/build_translations.sh` para que la ventana
aparezca medio en cada idioma. De eso avisa este fichero.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="las traducciones son de la GUI")

from kernelgrove.gui import translations  # noqa: E402

TS_FILES = sorted(translations.TRANSLATIONS_DIR.glob("kernelgrove_*.ts"))


def test_hay_al_menos_un_idioma_ademas_del_ingles():
    """El español es la traducción de referencia; sin ella no hay nada que probar."""
    assert translations.SOURCE_LANGUAGE == "en"
    assert "es" in translations.available_languages()


@pytest.mark.parametrize("ts_path", TS_FILES, ids=lambda p: p.stem)
def test_ninguna_cadena_se_queda_sin_traducir(ts_path: Path):
    """Un texto nuevo sin traducir deja la ventana en dos idiomas a la vez.

    `lupdate` marca así lo que ha añadido (`type="unfinished"`), de modo que
    esto falla justo cuando alguien toca un texto y no vuelve a pasar
    `scripts/build_translations.sh`.
    """
    pending = []
    for context in ET.parse(ts_path).getroot():
        for message in context.findall("message"):
            translation = message.find("translation")
            if translation is not None and translation.get("type") == "unfinished":
                pending.append(message.findtext("source"))

    assert pending == [], (
        f"{ts_path.name}: {len(pending)} cadenas sin traducir, la primera "
        f"{pending[0]!r}. Pasa scripts/build_translations.sh y tradúcelas."
    )


@pytest.mark.parametrize("ts_path", TS_FILES, ids=lambda p: p.stem)
def test_cada_traduccion_esta_compilada_y_al_dia(ts_path: Path):
    """El `.qm` es lo que carga la aplicación; el `.ts` solo se edita.

    Se compara el contenido, no la fecha de los ficheros: git no conserva
    las fechas de modificación, así que en un checkout limpio —el de CI, sin
    ir más lejos— comparar `mtime` daría un resultado al azar.
    """
    from PySide6.QtCore import QTranslator

    qm_path = ts_path.with_suffix(".qm")
    assert qm_path.exists(), f"falta {qm_path.name}: pasa scripts/build_translations.sh"

    translator = QTranslator()
    assert translator.load(str(qm_path)), f"{qm_path.name} no se puede cargar"

    stale = []
    for context in ET.parse(ts_path).getroot():
        name = context.findtext("name")
        for message in context.findall("message"):
            source = message.findtext("source")
            expected = message.findtext("translation") or ""
            if expected and translator.translate(name, source) != expected:
                stale.append(f"[{name}] {source!r}")

    assert stale == [], (
        f"{qm_path.name} no coincide con {ts_path.name} en {len(stale)} cadenas "
        f"(la primera, {stale[0]}). Pasa scripts/build_translations.sh."
    )


@pytest.mark.parametrize("ts_path", TS_FILES, ids=lambda p: p.stem)
def test_los_huecos_del_texto_sobreviven_a_la_traduccion(ts_path: Path):
    """Una traducción tiene que llevar los mismos `{campos}` que el original.

    Si a la traducción le falta uno, el `.format()` del código no lo
    sustituye; si lleva uno de más, `format()` lanza `KeyError` y el mensaje
    revienta justo cuando hacía falta enseñarlo.
    """
    import re

    fields = re.compile(r"\{(\w+)\}")
    problems = []
    for context in ET.parse(ts_path).getroot():
        for message in context.findall("message"):
            source = message.findtext("source") or ""
            translated = message.findtext("translation") or ""
            if not translated:
                continue
            if set(fields.findall(source)) != set(fields.findall(translated)):
                problems.append(source)

    assert problems == [], f"{ts_path.name}: huecos distintos en {problems}"


def test_el_nombre_de_cada_idioma_sale_en_su_propio_idioma():
    """Lo que se lee en el menú, sin el «de España» que Qt añade por la región."""
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])

    assert translations.language_name("es") == "Español"
    assert translations.language_name("en") == "English"
    # Con región explícita sí se conserva: distinguirla es justo el motivo
    # de escribir `pt_BR` en vez de `pt`.
    assert translations.language_name("pt_BR").startswith("Português (")
    # Un código que Qt no conoce se muestra tal cual, sin reventar.
    assert translations.language_name("xx") == "xx"


def test_el_idioma_elegido_se_guarda_y_manda_al_siguiente_arranque(tmp_path):
    """El idioma elegido se recuerda para la sesión siguiente.

    Cambiarlo se aplica en caliente (ver `test_gui_smoke`), pero además tiene
    que sobrevivir a cerrar la aplicación: `MainWindow._set_language` lo
    escribe en `QSettings` y `run_app` se lo pasa a `install_translations` en
    el arranque siguiente. Esto comprueba esa segunda mitad.
    """
    from PySide6.QtCore import QCoreApplication, QSettings
    from PySide6.QtWidgets import QApplication

    from kernelgrove.gui.main_window import SETTING_LANGUAGE

    app = QApplication.instance() or QApplication([])
    # Ajustes propios de la prueba: no se toca la configuración del usuario.
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    settings = QSettings(
        QSettings.IniFormat, QSettings.UserScope, "KernelGrove", "test"
    )

    settings.setValue(SETTING_LANGUAGE, "es")
    previous = os.environ.pop("KERNELGROVE_LANG", None)
    try:
        stored = settings.value(SETTING_LANGUAGE)
        assert translations.install_translations(app, stored) == "es"
        assert QCoreApplication.translate("messages", "Database") == "Base de datos"
    finally:
        if previous is not None:
            os.environ["KERNELGROVE_LANG"] = previous


def test_el_idioma_pedido_es_el_que_se_carga():
    """`KERNELGROVE_LANG` manda sobre el idioma del sistema, y traduce de verdad."""
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    previous = os.environ.get("KERNELGROVE_LANG")
    os.environ["KERNELGROVE_LANG"] = "es"
    try:
        assert translations.install_translations(app) == "es"
        assert (
            QCoreApplication.translate("messages", "Unsaved changes")
            == "Cambios sin guardar"
        )
    finally:
        if previous is None:
            os.environ.pop("KERNELGROVE_LANG", None)
        else:
            os.environ["KERNELGROVE_LANG"] = previous
