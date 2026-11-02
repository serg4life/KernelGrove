"""Carga del idioma de la interfaz.

El idioma **fuente** de la aplicación es el inglés: es lo que está escrito en
el código, dentro de `tr()`, y por tanto lo que se ve si no hay traducción
que cargar. El mercado principal es angloparlante, así que ese caso —el más
probable— no puede depender de que un fichero `.qm` esté presente.

Los demás idiomas son ficheros `.qm` compilados que viven en
`gui/translations/` (ver `scripts/build_translations.sh`). Añadir uno nuevo
es añadir su fichero: aquí no hay ninguna lista de idiomas que mantener.

Qué idioma se carga, por orden:

1. La variable de entorno `KERNELGROVE_LANG` (`es`, `en`, `pt_BR`…), que es cómo se
   fuerza uno concreto para una ejecución suelta sin tocar nada — y cómo lo
   piden las pruebas.
2. El que el usuario haya elegido en «Ver → Idioma», que `MainWindow` guarda
   en `QSettings` y `run_app` pasa aquí como `preferred`.
3. El del sistema (`QLocale.system()`), con sus idiomas de respaldo.
4. Inglés, o sea el texto tal cual está en el código.

Se carga además la traducción del propio Qt (`qtbase_<idioma>.qm`), que es de
donde salen los botones de los diálogos estándar —«Guardar», «Descartar»,
«Cancelar»— y el diálogo de ficheros: sin ella, una interfaz traducida
enseñaría sus propios textos en un idioma y los de Qt en inglés.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QLibraryInfo,
    QLocale,
    QTranslator,
)


class Retranslates:
    """Mezcla para un widget que tiene que rehacer sus textos al cambiar de idioma.

    Qt manda `QEvent.LanguageChange` a **todos** los widgets —comprobado:
    también a los ocultos y a las ventanas que aún no se han mostrado— en
    cuanto se instala o se quita un traductor. Lo único que hace falta es
    responderle, y eso es siempre lo mismo, así que vive aquí en vez de
    repetido en cada clase.

    Quien la use implementa `retranslate()` y vuelve a fijar ahí los textos
    que puso al construirse. Ojo con lo que **no** es un widget: los modelos
    (`PeripheralTreeModel`) y los items del grafo no reciben el evento, y hay
    que refrescarlos a mano desde quien los tenga.
    """

    def retranslate(self) -> None:
        """Vuelve a fijar los textos de este widget en el idioma activo."""

    def changeEvent(self, event) -> None:  # noqa: N802 - override de Qt
        """Rehace los textos cuando cambia el idioma de la aplicación."""
        if event.type() == QEvent.LanguageChange:
            self.retranslate()
        super().changeEvent(event)

# Idioma en el que están escritas las cadenas del código.
SOURCE_LANGUAGE = "en"

TRANSLATIONS_DIR = Path(__file__).resolve().parent / "translations"

# Los traductores se guardan aquí porque Qt **no** se queda con una
# referencia propia: uno recogido por el recolector de basura deja de
# traducir, y el síntoma es una ventana medio en cada idioma.
_installed: List[QTranslator] = []

# Idioma que resolvió la última llamada a `install_translations`. No es
# derivable del sistema ni de los ajustes —la cadena de respaldo puede acabar
# en inglés porque no hubiera `.qm`—, y hay quien necesita saber en qué
# idioma acabó la ventana.
_current: str = SOURCE_LANGUAGE


def current_language() -> str:
    """Idioma en el que se está enseñando la aplicación."""
    return _current


def available_languages() -> List[str]:
    """Idiomas con traducción compilada, además del inglés de origen."""
    if not TRANSLATIONS_DIR.is_dir():
        return [SOURCE_LANGUAGE]
    found = sorted(
        path.stem.removeprefix("kernelgrove_")
        for path in TRANSLATIONS_DIR.glob("kernelgrove_*.qm")
    )
    return [SOURCE_LANGUAGE] + [name for name in found if name != SOURCE_LANGUAGE]


def language_name(code: str) -> str:
    """Nombre del idioma en su propio idioma: «English», «Español».

    Se lo pregunta a Qt en vez de mantener una tabla: un idioma nuevo es un
    fichero `.qm` y nada más, y una tabla de nombres sería justo lo que
    alguien olvidaría actualizar.

    Se recorta lo que Qt añade de la región cuando la hay —devuelve
    «American English» y «español de España», porque `es` resuelve a `es_ES`
    y `en` a `en_US`—, salvo que el propio código pida una región concreta
    (`pt_BR`), que es cuando distinguir «Português (Brasil)» de «Português»
    sí dice algo.
    """
    locale = QLocale(code)
    name = locale.nativeLanguageName()
    if not name:
        return code

    if "_" in code:
        territory = locale.nativeTerritoryName()
        base = name.split(" de ")[0].split(" (")[0]
        return f"{_capitalized(base)} ({territory})" if territory else name

    # Sin región en el código: «español de España» → «Español», «American
    # English» → «English». Lo segundo no lleva preposición, así que se
    # quita comparando con el nombre general del idioma.
    general = QLocale.languageToString(locale.language())
    for separator in (" de ", " ("):
        if separator in name:
            return _capitalized(name.split(separator)[0])
    if name.endswith(general) and name != general:
        return general
    return _capitalized(name)


def _capitalized(name: str) -> str:
    """Primera letra en mayúscula, que es como se lista un idioma."""
    return name[:1].upper() + name[1:]


def install_translations(
    app: QCoreApplication, preferred: Optional[str] = None
) -> str:
    """Instala la traducción que toque y devuelve el idioma resultante.

    `preferred` es el idioma que el usuario haya elegido en el menú; `None`
    o la cadena vacía significan "el del sistema".

    Se puede llamar en caliente: primero se retiran los traductores que
    hubiera —sin eso, volver al inglés dejaría el anterior traduciendo— y
    quitarlos o ponerlos ya hace que Qt reparta `LanguageChange` por todos
    los widgets, que es lo que dispara `Retranslates.retranslate`.
    """
    global _current

    _remove_installed(app)
    _current = SOURCE_LANGUAGE
    for language in _candidate_languages(preferred):
        if language.startswith(SOURCE_LANGUAGE):
            break
        if _install_for(app, language):
            _current = language
            return language
    return SOURCE_LANGUAGE


def _remove_installed(app: QCoreApplication) -> None:
    """Retira los traductores que instaló una llamada anterior."""
    while _installed:
        app.removeTranslator(_installed.pop())


def _candidate_languages(preferred: Optional[str] = None) -> List[str]:
    """Idiomas a probar, del más específico al más general.

    De `es_ES` salen `es_ES` y `es`: una traducción general sirve cuando no
    hay una específica de país, que es el caso habitual.

    `KERNELGROVE_LANG` gana a la preferencia guardada a propósito: es un ajuste de
    una ejecución concreta (una prueba, un arranque desde consola para ver
    cómo queda otro idioma) y tiene que poder saltarse lo que haya elegido
    el usuario sin cambiárselo.
    """
    requested = os.environ.get("KERNELGROVE_LANG") or preferred
    names = [requested] if requested else list(QLocale.system().uiLanguages())

    candidates: List[str] = []
    for name in names:
        if not name:
            continue
        normalized = name.replace("-", "_")
        for candidate in (normalized, normalized.split("_")[0]):
            if candidate not in candidates:
                candidates.append(candidate)
    return candidates


def _install_for(app: QCoreApplication, language: str) -> bool:
    """Instala la traducción de la aplicación y la de Qt para un idioma."""
    translator = _load(f"kernelgrove_{language}", TRANSLATIONS_DIR)
    if translator is None:
        return False

    app.installTranslator(translator)
    _installed.append(translator)

    # La de Qt es opcional: que falte solo deja los botones de los diálogos
    # estándar en inglés, no justifica renunciar a traducir la aplicación.
    qt_translator = _load(
        f"qtbase_{language}",
        Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)),
    )
    if qt_translator is not None:
        app.installTranslator(qt_translator)
        _installed.append(qt_translator)
    return True


def _load(name: str, directory: Path) -> Optional[QTranslator]:
    """Carga un `.qm` por nombre, o `None` si no está en ese directorio."""
    translator = QTranslator()
    if translator.load(name, str(directory)):
        return translator
    return None
