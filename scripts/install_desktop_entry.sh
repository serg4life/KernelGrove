#!/usr/bin/env bash
# Registra el checkout en el escritorio, para que la ventana salga con su
# icono en vez de con la rueda genérica.
#
# GNOME no usa el icono que la ventana lleva dentro (`_NET_WM_ICON`): asocia
# la ventana a una entrada `.desktop` por su identificador de aplicación
# (`QApplication.setDesktopFileName`, «kernelgrove») y de ahí saca el icono. Sin
# esa entrada instalada no hay de dónde sacarlo, y lo que se ve es el
# `application-x-executable` del tema —en Yaru, un engranaje—.
#
# El `.deb` ya instala esa entrada en el sistema; esto es su equivalente para
# quien ejecuta desde el repositorio, en `~/.local` y sin sudo.
#
# Uso:
#   bash scripts/install_desktop_entry.sh            # instala
#   bash scripts/install_desktop_entry.sh --remove   # desinstala
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
apps_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
icons_dir="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
entry="$apps_dir/kernelgrove.desktop"
icon="$icons_dir/kernelgrove.svg"

if [[ "${1:-}" == "--remove" ]]; then
    rm -f "$entry" "$icon"
    update-desktop-database -q "$apps_dir" 2>/dev/null || true
    echo "Desinstalado $entry"
    exit 0
fi

mkdir -p "$apps_dir" "$icons_dir"
cp "$repo_root/src/kernelgrove/gui/brand/logo-icon.svg" "$icon"

# El intérprete del venv si lo hay, para que el lanzador funcione sin tener
# que activarlo antes; si no, el `python` del PATH.
python_bin="$repo_root/.venv/bin/python"
[[ -x "$python_bin" ]] || python_bin="$(command -v python3 || command -v python)"

# Copia del `.desktop` que instala el `.deb`, con el `Exec` del checkout: así
# lo que se registra en desarrollo y lo que se distribuye no se separan.
sed -e "s|^Exec=.*|Exec=$python_bin -m kernelgrove|" \
    -e "s|^Icon=.*|Icon=kernelgrove|" \
    "$repo_root/packaging/linux/kernelgrove.desktop" > "$entry"
chmod 644 "$entry"

update-desktop-database -q "$apps_dir" 2>/dev/null || true
gtk-update-icon-cache -q -f -t "${icons_dir%/scalable/apps}" 2>/dev/null || true

echo "Instalado $entry"
echo "Si la ventana ya estaba abierta, ciérrala y vuelve a lanzarla."
