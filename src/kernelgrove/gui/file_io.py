"""Lectura de ficheros del disco para el editor, sin nada de Qt.

Vivía dentro de `MainWindow`, que ya orquesta bastante: aquí no hay ventanas
ni diálogos, solo "dame el texto de este fichero, o dime por qué no puedo".
Quien llama decide cómo enseñar el motivo (un `QMessageBox`, la barra de
estado, un log).

El panel de carpetas no filtra por extensión a propósito (ver
`widgets/file_explorer.py`), así que por aquí puede pasar cualquier cosa: un
`.db` de SQLite, una imagen de kernel, un binario. Cargar cualquiera de esos
entero como texto puede colgar la aplicación —una única "línea" de varios MB
satura tanto al resaltador de sintaxis como al propio `QPlainTextEdit`— en
vez de fallar con un aviso legible, así que se comprueba antes de leer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

# 5 MiB: muy por encima de cualquier `.dts`/`.dtsi` real (el mayor del kernel
# no llega a 200 KB), y muy por debajo de lo que tarda en notarse al abrirlo.
MAX_TEXT_FILE_SIZE = 5 * 1024 * 1024
BINARY_SNIFF_SIZE = 8192


class FileTooLargeError(Exception):
    """El fichero supera `MAX_TEXT_FILE_SIZE`."""

    def __init__(self, path: Path, size: int, limit: int):
        """Guarda qué fichero era y cuánto se pasaba del límite."""
        super().__init__(f"{path} ({size} bytes) is over the limit of {limit}")
        self.path = path
        self.size = size
        self.limit = limit


class FileLooksBinaryError(Exception):
    """El fichero no parece texto (lleva bytes NUL en su cabecera)."""

    def __init__(self, path: Path):
        """Guarda qué fichero se ha descartado."""
        super().__init__(f"{path} does not look like a text file")
        self.path = path


# ----------------------------------------------------------------------
# Qué es el fichero y cómo termina sus líneas
# ----------------------------------------------------------------------
# Lo que la franja de abajo dice del documento abierto. Va aquí y no en el
# editor porque se deduce del **fichero**, no de lo que se esté haciendo con
# él, y porque este módulo ya es "lo que sé de un fichero antes de abrirlo".
LF = "\n"
CRLF = "\r\n"

_LANGUAGES = {
    ".dts": "DTS",
    ".dtsi": "DTS",
    ".dtso": "DTS overlay",
    ".dtb": "DTB",
    ".dtbo": "DTBO",
    ".h": "C header",
    ".c": "C",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".md": "Markdown",
    ".txt": "Plain text",
    ".diff": "Diff",
    ".patch": "Diff",
    ".py": "Python",
    ".sh": "Shell",
    ".toml": "TOML",
    ".cfg": "INI",
    ".ini": "INI",
    ".xml": "XML",
    ".log": "Log",
}


def language_of(title: str) -> str:
    """Qué clase de fichero es, por su extensión.

    La franja decía «DTS» siempre, incluso con un `.json` delante, que es lo
    mismo que no decir nada. Por extensión y no adivinando por el contenido:
    el editor abre lo que le echen (el panel de carpetas no filtra), y la
    extensión es lo que el usuario ve en la pestaña — si las dos cosas no
    coincidieran, la franja estaría contradiciendo al nombre del fichero.
    """
    suffix = Path(title).suffix.lower()
    if suffix in _LANGUAGES:
        return _LANGUAGES[suffix]
    return suffix.lstrip(".").upper() or "Plain text"


def detect_newline(text: str) -> str:
    """`CRLF` si el fichero venía de Windows, `LF` si no.

    Basta con encontrar uno: un fichero mezclado es un fichero roto, y
    guardarlo entero con un único terminador —el que diga el indicador— es
    justamente lo que arregla ese caso.
    """
    return CRLF if CRLF in text else LF


def normalize_newlines(text: str) -> str:
    """Deja el texto en `\n`, que es lo único que el editor maneja dentro.

    Un `\r` suelto dentro de un `QPlainTextEdit` se ve como un carácter de
    control en mitad de la línea. Se quita al abrir y se vuelve a poner al
    guardar (`apply_newlines`), así que el fichero conserva el suyo.
    """
    return text.replace(CRLF, LF).replace("\r", LF)


def apply_newlines(text: str, newline: str) -> str:
    """Pone el terminador elegido antes de escribir a disco."""
    plano = normalize_newlines(text)
    return plano if newline == LF else plano.replace(LF, newline)


def looks_binary(sample: bytes) -> bool:
    """Heurística de git: un NUL en los primeros bytes ya delata un binario.

    Un texto real (DTS, YAML, lo que sea) no lleva bytes NUL; un `.db` de
    SQLite, en cambio, empieza literalmente por `SQLite format 3\\0`, y una
    imagen de kernel o cualquier binario compilado está llena de ellos. Es la
    misma comprobación que usa `git` para decidir si un fichero es de texto.
    """
    return b"\x00" in sample


def read_text_file(
    path: Path, max_size: int = MAX_TEXT_FILE_SIZE
) -> Tuple[Optional[str], Optional[Exception]]:
    """Lee `path` como texto UTF-8, o devuelve el motivo por el que no.

    Devuelve `(texto, None)` o `(None, error)`. El error es un `OSError` del
    sistema, un `FileTooLargeError` o un `FileLooksBinaryError`; nunca se
    propaga, para que el llamante lo traduzca a su manera a un mensaje.

    Las dos comprobaciones previas van en este orden porque la primera es
    gratis (ya viene del `stat`) y la segunda solo hace falta si la primera
    no ha descartado nada.
    """
    try:
        size = path.stat().st_size
    except OSError as exc:
        return None, exc

    if size > max_size:
        return None, FileTooLargeError(path, size, max_size)

    try:
        with path.open("rb") as handle:
            sample = handle.read(BINARY_SNIFF_SIZE)
    except OSError as exc:
        return None, exc

    if looks_binary(sample):
        return None, FileLooksBinaryError(path)

    try:
        return path.read_text(encoding="utf-8", errors="replace"), None
    except OSError as exc:
        return None, exc
