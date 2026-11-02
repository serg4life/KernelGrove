#!/usr/bin/env bash
# Escribe el cuerpo de una release de GitHub: el changelog de esa versión y la
# tabla de assets con su SHA-256.
#
#   bash scripts/release_notes.sh [tag]
#
# Los hashes no se calculan aquí: GitHub ya publica el `digest` de cada asset,
# así que la tabla sale de la propia release y sirve igual para el `.exe`, que
# se sube aparte desde la CI de Windows. Vuelve a correrlo cada vez que subas
# un asset — es idempotente y reescribe el cuerpo entero.
set -euo pipefail
cd "$(dirname "$0")/.."

# Las releases viven en el mismo repositorio que el código. Las versiones
# 1.0b1–1.0b3 leían su manifiesto de `serg4life/kernelgrove-releases`, que se
# conserva archivado para que esas copias sigan pudiendo bajar su base.
REPO="${KERNELGROVE_RELEASE_REPO:-serg4life/kernelgrove}"
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)
TAG="${1:-v$VERSION}"

# La sección `## <tag>` de CHANGELOG.md, sin su encabezado.
NOTAS=$(awk -v t="## $TAG" '$0 == t {en=1; next} /^## / {en=0} en' CHANGELOG.md | awk 'NF{p=1} p')
[ -n "$NOTAS" ] || { echo "CHANGELOG.md no tiene sección '## $TAG'." >&2; exit 1; }

ASSETS=$(gh api "repos/$REPO/releases/tags/$TAG" \
    -q '.assets[] | select(.digest) | "| `" + .name + "` | `" + (.digest | sub("^sha256:"; "")) + "` |"' \
    | sort)
[ -n "$ASSETS" ] || { echo "La release $TAG no tiene assets con digest." >&2; exit 1; }

gh release edit "$TAG" --repo "$REPO" -t "$TAG" -F - <<BODY
$NOTAS

## Assets

| Asset | SHA-256 |
|---|---|
$ASSETS
BODY
