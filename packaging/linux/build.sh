#!/usr/bin/env bash
# Construye el ejecutable de KernelGrove para Linux (--onedir) con PyInstaller.
#
# No incluye `bindings.db` ni `db_manager` — ver `kernelgrove.spec` y
# `packaging/linux/README.md` para el porqué. El resultado queda en
# `dist/kernelgrove/`.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

if ! python -c "import PyInstaller" >/dev/null 2>&1; then
    echo "PyInstaller no está instalado. Instálalo con:"
    echo "  pip install -e '.[packaging]'"
    exit 1
fi

pyinstaller packaging/linux/kernelgrove.spec \
    --distpath dist \
    --workpath build \
    --noconfirm

echo
echo "Construido en dist/kernelgrove/. Probar con:"
echo "  KERNELGROVE_DB_PATH=/ruta/a/bindings.db dist/kernelgrove/kernelgrove"
