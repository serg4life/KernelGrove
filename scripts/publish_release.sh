#!/usr/bin/env bash
# Publica una release de KernelGrove: los instaladores y el `manifest.json`.
#
#   bash packaging/linux/build.sh && bash packaging/linux/build_deb.sh
#   bash scripts/publish_release.sh [tag]
#
# El tag es `v$VERSION` salvo que le pases otro: la versión del paquete tiene
# que ser PEP 440 (`1.0b1`), y el tag que quieras enseñar en GitHub no.
#
# **La base no va aquí.** Vive en su propia release (`scripts/publish_database.sh`)
# porque no cambia de una versión a la siguiente: las tres primeras betas
# subieron el mismo fichero byte a byte, 82 MB cada vez. Lo que sí viaja con
# cada release es el `manifest.json`, que son 200 bytes y es el puntero: la
# aplicación lo lee de `releases/latest/download/manifest.json` —eso es lo que
# ya buscan las copias instaladas, así que no puede dejar de estar— y de ahí
# saca la URL y el `sha256` de la base. Ninguno de los dos se calcula en local:
# se leen del asset publicado, que es la copia que se va a descargar de verdad.
set -euo pipefail
cd "$(dirname "$0")/.."

# Las releases viven en el mismo repositorio que el código. Las versiones
# 1.0b1–1.0b3 leían su manifiesto de `serg4life/kernelgrove-releases`, que se
# conserva archivado para que esas copias sigan pudiendo bajar su base.
REPO="${KERNELGROVE_RELEASE_REPO:-serg4life/kernelgrove}"
# A qué base apunta esta versión. Se sube a mano al bumbearla, que es cuando
# hay que decidir contra qué base se ha probado lo que se publica.
DB_TAG=db-v1
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)
TAG="${1:-v$VERSION}"
# El nombre del `.deb` lleva la versión Debian (`1.0~b1`), no la de
# `pyproject.toml` (`1.0b1`): se coge el más reciente en vez de repetir aquí
# la traducción que hace `build_deb.sh`.
DEB="$(ls -t dist/kernelgrove_*_amd64.deb 2>/dev/null | head -1)"

[ -n "$DEB" ] || { echo "No hay ningún .deb en dist/ — construye el paquete primero." >&2; exit 1; }

# La base publicada, tal cual está: su digest lo da GitHub, así que el
# manifiesto describe el fichero que se va a bajar y no una copia local que
# podría no ser la misma.
DB_JSON=$(gh api "repos/$REPO/releases/tags/$DB_TAG" \
    -q '.assets[] | select(.name == "bindings.db") | (.digest | sub("^sha256:"; "")) + " " + (.size|tostring)')
[ -n "$DB_JSON" ] || { echo "$DB_TAG no tiene bindings.db — publícala con scripts/publish_database.sh." >&2; exit 1; }
read -r DB_SHA DB_BYTES <<<"$DB_JSON"

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
# Nombre de asset sin versión: así `releases/latest/download/kernelgrove_amd64.deb`
# es un enlace estable.
cp "$DEB" "$TMP/kernelgrove_amd64.deb"

cat > "$TMP/manifest.json" <<JSON
{
  "version": "${DB_TAG#db-}",
  "url": "https://github.com/$REPO/releases/download/$DB_TAG/bindings.db",
  "sha256": "$DB_SHA",
  "bytes": $DB_BYTES
}
JSON

if gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
    gh release upload "$TAG" --repo "$REPO" --clobber \
        "$TMP/kernelgrove_amd64.deb" "$TMP/manifest.json"
    # Si la creó la CI de Windows llega como borrador (ver `windows.yml`):
    # ahora que ya lleva el manifiesto se puede publicar y pasar a «latest».
    gh release edit "$TAG" --repo "$REPO" --draft=false --latest
else
    gh release create "$TAG" --repo "$REPO" -t "$TAG" \
        "$TMP/kernelgrove_amd64.deb" "$TMP/manifest.json"
fi

# El cuerpo se reescribe entero a partir del CHANGELOG y de los digests que
# publica GitHub, así que vuelve a correrlo tras subir el instalador de Windows.
bash scripts/release_notes.sh "$TAG"
