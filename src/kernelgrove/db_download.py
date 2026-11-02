"""Descarga de la base de datos desde donde esté publicada.

La base no viaja con el programa (ver `packaging/linux/README.md`): es un
artefacto aparte, con su propio ritmo de versiones y su propia licencia. Lo
que hace este módulo es traerla la primera vez que se arranca sin ella.

**Hosting estático, no una API.** Lo que hay al otro lado son dos ficheros
que no hacen nada: un `manifest.json` que dice qué versión hay y dónde, y la
base. No hace falta servidor —vale un bucket, o las *releases* de GitHub— y
por eso la URL es un ajuste (`KERNELGROVE_DB_MANIFEST`) y no un servicio: quien
tenga su propia base construida con `db_manager` publica su manifiesto y
apunta ahí.

**Se comprueba el `sha256`.** Son ~68 MB por una red cualquiera; una
descarga a medias no se distingue de una completa por el tamaño, y una base
truncada falla mucho más tarde y de forma mucho más confusa que aquí. Se
escribe a un `.part` y se renombra al final, que es lo que evita dejar media
base en el sitio de la buena si se corta la conexión.

Sin Qt: aquí no hay ventanas. Quien llama decide cómo enseñar el progreso y
qué hacer con un error (ver `gui/app.ensure_database`).
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

# De dónde se saca qué base hay publicada. Hosting estático y no una API
# —un `manifest.json` que dice qué versión hay y dónde—, así que quien tenga
# su propia base construida con `db_manager` publica su manifiesto y apunta
# aquí con `KERNELGROVE_DB_MANIFEST`. Si no se puede llegar, la descarga
# falla con un mensaje legible y queda la salida de siempre: dar una local.
# Las releases están en el propio repositorio del código; hasta la 1.0b3
# estaban en `kernelgrove-releases`, que sigue sirviendo a esas versiones.
MANIFEST_URL = os.environ.get(
    "KERNELGROVE_DB_MANIFEST",
    "https://github.com/serg4life/kernelgrove"
    "/releases/latest/download/manifest.json",
)

# Cuánto se espera a que el servidor conteste. Corto: si no está, lo que
# interesa es llegar cuanto antes a «no he podido, dame una tú».
TIMEOUT_S = 20

# Trozo de lectura. 1 MiB: bastante para que el `sha256` y el disco no vayan
# a golpes, y poco para que la barra se mueva en una conexión lenta.
_CHUNK = 1024 * 1024


class DatabaseDownloadError(RuntimeError):
    """No se ha podido traer la base, y el mensaje dice por qué."""


class Manifest:
    """Lo que el servidor dice que hay publicado."""

    def __init__(self, data: dict):
        """Lee el manifiesto, exigiendo lo que de verdad hace falta."""
        self.version = str(data.get("version", "")).strip()
        self.url = str(data.get("url", "")).strip()
        self.sha256 = str(data.get("sha256", "")).strip().lower()
        self.bytes = int(data.get("bytes", 0) or 0)
        if not self.url:
            raise DatabaseDownloadError(
                "The database manifest does not say where the file is."
            )


def fetch_manifest(url: str = "") -> Manifest:
    """Pregunta qué base hay publicada."""
    url = url or MANIFEST_URL
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError) as error:
        raise DatabaseDownloadError(
            f"The database could not be reached at {url}: {_reason(error)}"
        ) from error
    except (ValueError, json.JSONDecodeError) as error:
        raise DatabaseDownloadError(
            f"What {url} answered is not a database manifest."
        ) from error
    if not isinstance(data, dict):
        raise DatabaseDownloadError(f"What {url} answered is not a database manifest.")
    return Manifest(data)


def download(
    manifest: Manifest,
    destination: Path,
    progress: Optional[Callable[[int, int], bool]] = None,
) -> Path:
    """Trae la base a `destination` y devuelve dónde ha quedado.

    `progress(leidos, total)` se llama mientras se descarga y devuelve si
    hay que seguir: es lo que permite cancelar. `total` es 0 cuando el
    servidor no dice cuánto ocupa, y entonces la barra de quien llame tiene
    que ser indeterminada en vez de mentir con un porcentaje.
    """
    destination = Path(destination).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    # A un fichero aparte y se renombra al final: si se corta la conexión,
    # lo que queda a medias no ocupa el sitio de la base buena.
    partial = destination.with_suffix(destination.suffix + ".part")

    digest = hashlib.sha256()
    leidos = 0
    try:
        with urllib.request.urlopen(manifest.url, timeout=TIMEOUT_S) as response:
            total = manifest.bytes or int(response.headers.get("Content-Length") or 0)
            with partial.open("wb") as handle:
                while True:
                    trozo = response.read(_CHUNK)
                    if not trozo:
                        break
                    handle.write(trozo)
                    digest.update(trozo)
                    leidos += len(trozo)
                    if progress is not None and not progress(leidos, total):
                        raise DatabaseDownloadError("The download was cancelled.")
    except DatabaseDownloadError:
        partial.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, OSError) as error:
        partial.unlink(missing_ok=True)
        raise DatabaseDownloadError(
            f"The database could not be downloaded: {_reason(error)}"
        ) from error

    if manifest.sha256 and digest.hexdigest() != manifest.sha256:
        partial.unlink(missing_ok=True)
        raise DatabaseDownloadError(
            "The downloaded database is corrupt (its checksum does not match). "
            "Try again."
        )

    partial.replace(destination)
    return destination


def _reason(error: Exception) -> str:
    """El motivo en una línea, que es lo que cabe en un cuadro de diálogo."""
    reason = getattr(error, "reason", None)
    return str(reason or error) or error.__class__.__name__
