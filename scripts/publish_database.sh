#!/usr/bin/env bash
# Publica la base de datos en una release propia, `db-vN`.
#
#   bash scripts/publish_database.sh db-v2
#
# La base no cambia de una versión del programa a la siguiente —las tres
# primeras betas subieron el mismo fichero byte a byte—, así que no viaja con
# ellas: va aparte, con su propio ritmo. Cada release de la aplicación lleva
# solo un `manifest.json` que apunta aquí, que es lo que la aplicación lee.
#
# El tag se queda quieto: una base reconstruida va a `db-v(N+1)`, para que una
# versión ya publicada siga apuntando a la base contra la que se probó. Y va
# marcada *prerelease* porque GitHub da por «latest» la release más reciente
# por fecha, y ahí tiene que seguir estando la aplicación: las copias ya
# instaladas leen su manifiesto de `releases/latest/download/manifest.json`.
set -euo pipefail
cd "$(dirname "$0")/.."

# Las releases viven en el mismo repositorio que el código. Las versiones
# 1.0b1–1.0b3 leían su manifiesto de `serg4life/kernelgrove-releases`, que se
# conserva archivado para que esas copias sigan pudiendo bajar su base.
REPO="${KERNELGROVE_RELEASE_REPO:-serg4life/kernelgrove}"
TAG="${1:-}"
DB=database/bindings.db

[ -n "$TAG" ] || { echo "Uso: $0 <tag>   (por ejemplo db-v2)" >&2; exit 1; }
[ -f "$DB" ]  || { echo "Falta $DB — corre scripts/build_database.sh." >&2; exit 1; }
! gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1 \
    || { echo "$TAG ya existe: una base publicada no se reescribe, usa el siguiente número." >&2; exit 1; }

gh release create "$TAG" --repo "$REPO" --prerelease -t "Bindings database ${TAG#db-}" \
    --notes "The bindings database, published on its own so that an application release does not have to carry a copy of it. KernelGrove downloads it on first run, reading the \`manifest.json\` of the application release and checking its \`sha256\`.

This tag is pinned. A rebuilt database goes to the next number, so that an already published application release keeps pointing at the database it was tested against.

The kernel files stored in the database keep their own licences (GPL-2.0 and dual GPL/MIT/BSD variants). See [LICENSES.md](https://github.com/$REPO/blob/main/src/kernelgrove/gui/LICENSES.md)." \
    "$DB"

echo "Publicada. Apunta ahí la aplicación: DB_TAG=$TAG en scripts/publish_release.sh"
