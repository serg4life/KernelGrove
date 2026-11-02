#!/usr/bin/env bash
# Extrae las cadenas de la interfaz y compila las traducciones.
#
# El idioma fuente es el inglés: es lo que está escrito dentro de `tr()` en el
# código, y lo que se ve si no hay traducción. Cada idioma adicional es un
# `src/kernelgrove/gui/translations/kernelgrove_<idioma>.ts` que se traduce con Qt
# Linguist (`pyside6-linguist`) y se compila a `.qm`, que es lo que carga la
# aplicación.
#
# Uso:
#   scripts/build_translations.sh              # actualiza los .ts y compila
#   scripts/build_translations.sh --add pt_BR  # empieza un idioma nuevo
#
# Después de tocar cualquier texto de la interfaz hay que volver a pasarlo:
# `lupdate` añade las cadenas nuevas a cada `.ts` sin borrar lo ya traducido.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

TRANSLATIONS_DIR="src/kernelgrove/gui/translations"

if [[ -d ".venv" ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

if [[ "${1:-}" == "--add" ]]; then
    LANGUAGE="${2:?falta el idioma, p. ej. --add pt_BR}"
    NEW_TS="$TRANSLATIONS_DIR/kernelgrove_$LANGUAGE.ts"
    if [[ -f "$NEW_TS" ]]; then
        echo "$NEW_TS ya existe" >&2
        exit 1
    fi
    # Un .ts vacío: lupdate lo rellena con las cadenas del código, todas sin
    # traducir, listo para abrirlo en Linguist.
    printf '<?xml version="1.0" encoding="utf-8"?>\n<TS version="2.1" language="%s"></TS>\n' \
        "$LANGUAGE" > "$NEW_TS"
    echo "Creado $NEW_TS"
fi

mkdir -p "$TRANSLATIONS_DIR"
mapfile -t SOURCES < <(find src/kernelgrove -name '*.py' | sort)

echo "== Extrayendo cadenas =="
for ts in "$TRANSLATIONS_DIR"/kernelgrove_*.ts; do
    [[ -e "$ts" ]] || continue
    # `-no-obsolete` descarta lo que ya no está en el código, para que el
    # fichero no acumule textos de versiones anteriores.
    pyside6-lupdate "${SOURCES[@]}" -ts "$ts" -no-obsolete
done

echo
echo "== Compilando =="
for ts in "$TRANSLATIONS_DIR"/kernelgrove_*.ts; do
    [[ -e "$ts" ]] || continue
    pyside6-lrelease "$ts" -qm "${ts%.ts}.qm"
done

echo
echo "Listo. Traduce con: pyside6-linguist $TRANSLATIONS_DIR/kernelgrove_<idioma>.ts"
