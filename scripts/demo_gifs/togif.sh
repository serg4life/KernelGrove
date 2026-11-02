#!/bin/bash
# togif.sh <escena> [ancho] [retardo-en-centesimas] [colores]
#
# Envoltorio de `togif.py`, que es donde esta el montaje. Lo unico que hace
# aqui es buscar un Python que tenga Pillow: el entorno virtual del proyecto
# no lo lleva -no es dependencia de la aplicacion, solo de esta herramienta-,
# asi que con el entorno activado `python3` es justo el que no sirve.
#
# El montaje era `convert -layers OptimizeFrame` de ImageMagick y ya no lo es:
# `convert` carga todos los fotogramas antes de escribir nada y la politica
# del sistema le corta la cache en 2 GiB, unos 600 fotogramas de 1280x800 —
# menos de lo que dura la escena `tour`. Ver la cabecera de `togif.py`.
set -e
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for candidate in "${PYTHON:-}" python3 /usr/bin/python3 python; do
    [ -n "$candidate" ] || continue
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c "import PIL" >/dev/null 2>&1; then
        exec "$candidate" "$here/togif.py" "$@"
    fi
done

echo "togif: hace falta Pillow (pip install pillow) en algun Python del sistema" >&2
exit 1
