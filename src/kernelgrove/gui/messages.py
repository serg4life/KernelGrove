"""Textos de los cuadros de diálogo (avisos, errores, confirmaciones).

Un widget no debe llevar un mensaje de usuario incrustado en la llamada a
`QMessageBox`/`QLabel` — se define aquí, con nombre, y se importa donde haga
falta. Los títulos que se repiten (p. ej. "No se pudo guardar", que antes
estaba duplicado literalmente en `main_window.py` y `editor_tab.py`) quedan
en un único sitio en vez de copiados en cada uno. Los mensajes que necesitan
un dato del momento (un nombre de fichero, la excepción...) son funciones, no
plantillas con `.format()` sueltas por el código.

**El texto está en inglés y pasa por `QCoreApplication.translate`**, que es
el equivalente de `self.tr()` para un módulo sin clases: aquí no hay ningún
`QObject` del que colgar el método. El contexto (`"messages"`, el primer
argumento) se escribe a mano en cada llamada y no a través de un envoltorio
más corto porque `lupdate` extrae las cadenas **leyendo el código**: tras
cualquier indirección deja de verlas, y una cadena que no se extrae no se
puede traducir. Ver `gui/translations.py`.

Ni los títulos ni los mensajes fijos pueden ser constantes de módulo: al
importarse esto todavía no hay `QApplication` ni idioma cargado, así que la
traducción tiene que resolverse en el momento de pedir el texto. De ahí que
sean funciones `title_*()` y no constantes `TITLE_*`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication


# ----------------------------------------------------------------------
# Títulos (se repiten entre varios diálogos)
# ----------------------------------------------------------------------
def title_source_not_available() -> str:
    """Título: el fuente elegido no está en la base de datos."""
    return QCoreApplication.translate("messages", "Source not available")


def title_file_open_error() -> str:
    """Título: no se ha podido abrir un fichero del disco."""
    return QCoreApplication.translate("messages", "Could not open file")


def title_file_not_text() -> str:
    """Título: el fichero no se puede abrir como texto."""
    return QCoreApplication.translate("messages", "Cannot open in the editor")


def title_file_save_error() -> str:
    """Título: no se ha podido escribir un fichero."""
    return QCoreApplication.translate("messages", "Could not save")


def title_unsaved_changes() -> str:
    """Título: hay cambios sin guardar que se van a perder."""
    return QCoreApplication.translate("messages", "Unsaved changes")


def title_include_not_found() -> str:
    """Título: una inclusión que no se ha podido resolver."""
    return QCoreApplication.translate("messages", "Include not found")


def title_compile() -> str:
    """Título: algo que decir sobre compilar o descompilar un árbol."""
    return QCoreApplication.translate("messages", "Device tree compiler")


def title_licenses() -> str:
    """Título de la ventana de licencias."""
    return QCoreApplication.translate("messages", "Licenses")


def title_database_catalogue() -> str:
    """Título de la ventana del catálogo de la base."""
    return QCoreApplication.translate("messages", "Hardware catalogue")


def title_database() -> str:
    """Título: algo que contar sobre la base de datos abierta."""
    return QCoreApplication.translate("messages", "Database")


def title_about() -> str:
    """Título de la ficha «Acerca de»."""
    return QCoreApplication.translate("messages", "About KernelGrove")


# ----------------------------------------------------------------------
# Mensajes con datos del momento (nombre de fichero, excepción...)
# ----------------------------------------------------------------------
def source_not_available(name: str) -> str:
    """SoC/board elegido en el desplegable sin fuente en la base de datos."""
    return QCoreApplication.translate(
        "messages",
        "The device tree for «{name}» is not stored in the database. "
        "Rebuild it with scripts/build_database.sh.",
    ).format(name=name)


def unsaved_changes(title: str) -> str:
    """Antes de cerrar una pestaña (o toda la sesión) con cambios sin guardar."""
    return QCoreApplication.translate(
        "messages", "«{title}» has unsaved changes. What do you want to do?"
    ).format(title=title)


def include_not_found(target: str) -> str:
    """Ctrl+clic en un include que no se resolvió ni en disco ni en la base."""
    return QCoreApplication.translate(
        "messages",
        "«{target}» was not found next to the file on disk nor in the "
        "database, so its contents cannot be opened.",
    ).format(target=target)


def file_error(exc: Exception) -> str:
    """Texto de un error de E/S (abrir o guardar), tal como lo da el sistema."""
    return str(exc)


def file_too_large(path: Path, size: int, limit: int) -> str:
    """El panel de carpetas ya no filtra por extensión: un `.db` o una imagen
    del kernel se pueden colar, y cargarlos enteros como texto puede colgar
    el editor en vez de simplemente fallar.
    """
    return QCoreApplication.translate(
        "messages",
        "«{name}» is {size}, more than the {limit} the editor opens as text.\n"
        "That is not a reasonable size for a device tree — open it with "
        "another tool if you need to.",
    ).format(name=path.name, size=_human_size(size), limit=_human_size(limit))


def file_looks_binary(path: Path) -> str:
    """Mismo motivo que `file_too_large`: un binario abierto como texto."""
    return QCoreApplication.translate(
        "messages", "«{name}» does not look like a text file."
    ).format(name=path.name)


def _human_size(size: int) -> str:
    """Tamaño legible (KiB/MiB), para los avisos de fichero demasiado grande."""
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GiB"


def tool_not_found() -> str:
    """Lo que dice «Acerca de» de una herramienta que no está instalada."""
    return QCoreApplication.translate("messages", "not found")


def tool_with_symbols(version: str) -> str:
    """Un `dtc` que acepta `-@`, el flag que exporta `__symbols__`.

    Es lo único no evidente de la herramienta y lo que decide si un overlay
    que apunta por etiqueta podrá resolverse, así que se dice aquí y no se
    deja para el momento en que falla una compilación.
    """
    return QCoreApplication.translate("messages", "{version} (supports -@)").format(
        version=version
    )


def about_text(
    version: str,
    dtc: str,
    cpp: str,
    dtschema: str,
) -> str:
    """Ficha de «Acerca de»: qué versión se usa y con qué se compila.

    Lo que interesa es con qué herramientas externas cuenta esta máquina,
    porque de eso depende que «Compilar» funcione y es lo primero que hay
    que mirar cuando no lo hace.
    """
    return QCoreApplication.translate(
        "messages",
        "<b>KernelGrove - Device Tree Studio</b> v{version}<br>"
        "Free software under the Apache License 2.0 · "
        "<a href='https://github.com/serg4life/kernelgrove'>"
        "github.com/serg4life/kernelgrove</a><br><br>"
        "<b>Toolchain</b><br>"
        "dtc · {dtc}<br>"
        "cpp · {cpp}<br>"
        "dt-schema · {dtschema}",
    ).format(
        version=version,
        dtc=dtc,
        cpp=cpp,
        dtschema=dtschema,
    )


def empty_editor_hint() -> str:
    """Qué hacer cuando no hay ningún fichero abierto todavía."""
    return QCoreApplication.translate(
        "messages",
        "No device tree open.\n\n"
        "· «Open folder…» (Ctrl+O) and browse the panel on the left\n"
        "· Or look for a SoC or a board in the catalogue:",
    )

