#!/usr/bin/env bash
# Empaqueta en un `.deb` el `dist/kernelgrove/` que deja `build.sh`.
#
# Sin paso de compilación: solo metadatos, el `.desktop` y el icono, que es
# lo que convierte un directorio suelto en algo que aparece en el menú de
# aplicaciones y que `apt remove` se lleva limpio.
#
# Con `dpkg-deb` y no con `fpm` (que es lo que apuntaba el plan): `fpm` es
# una gema de Ruby que habría que instalar, y `dpkg-deb` viene en cualquier
# Debian/Ubuntu — que es exactamente donde se construye un `.deb`.
#
# Un `.deb` por arquitectura, porque empaqueta un `dist/` que PyInstaller
# construyó para la máquina donde se lanzó (no hay cross-compiling).
#
# Uso:
#   bash packaging/linux/build.sh        # primero el ejecutable
#   bash packaging/linux/build_deb.sh    # y luego el paquete
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

dist_dir="dist/kernelgrove"
if [[ ! -x "$dist_dir/kernelgrove" ]]; then
    echo "No hay ejecutable en $dist_dir. Constrúyelo antes con:"
    echo "  bash packaging/linux/build.sh"
    exit 1
fi

version="$(grep -m1 '^version = ' pyproject.toml | cut -d'"' -f2)"
# PEP 440 pega la prerelease a la versión (`1.0b1`), y para `dpkg` eso ordena
# por ENCIMA de `1.0`: quien instalase la beta no vería nunca la final como
# actualización. El `~` de Debian ordena justo al revés, por debajo.
deb_version="$(printf '%s' "$version" | sed -E 's/(a|b|rc)([0-9]+)$/~\1\2/')"
arch="$(dpkg --print-architecture)"
# El correo del mantenedor va en el paquete y lo lee `apt`.
maintainer="${KERNELGROVE_DEB_MAINTAINER:-KernelGrove <serg4life@duck.com>}"

staging="build/deb/kernelgrove_${deb_version}_${arch}"
rm -rf "$staging"
mkdir -p "$staging/DEBIAN" \
         "$staging/opt/kernelgrove" \
         "$staging/usr/bin" \
         "$staging/usr/share/applications" \
         "$staging/usr/share/doc/kernelgrove" \
         "$staging/usr/share/icons/hicolor/scalable/apps"

# El programa entero en /opt: es un bundle de PyInstaller con sus `.so` al
# lado, no un conjunto de ficheros que repartir por /usr según el FHS.
cp -a "$dist_dir/." "$staging/opt/kernelgrove/"
ln -s /opt/kernelgrove/kernelgrove "$staging/usr/bin/kernelgrove"

# La licencia donde la política de Debian espera encontrarla, con el
# `NOTICE` delante: Apache-2.0 obliga a que los dos viajen con el paquete.
{
    echo "KernelGrove — https://github.com/serg4life/kernelgrove"
    echo "License: Apache-2.0"
    echo
    cat NOTICE
    echo
    cat LICENSE
} > "$staging/usr/share/doc/kernelgrove/copyright"

cp packaging/linux/kernelgrove.desktop "$staging/usr/share/applications/"
# El mismo símbolo que usa la aplicación para su ventana; el nombre del
# fichero es el `Icon=` del `.desktop`.
cp src/kernelgrove/gui/brand/logo-icon.svg \
   "$staging/usr/share/icons/hicolor/scalable/apps/kernelgrove.svg"

# Nada escribible por el grupo dentro del paquete: `dpkg-deb` conserva los
# permisos que traiga el staging, y el umask del que construye no tiene por
# qué ser el de un paquete publicable.
chmod -R go-w "$staging"

# Tamaño instalado en KiB, que es lo que `apt` enseña antes de instalar.
installed_size="$(du -ks "$staging" | cut -f1)"

cat > "$staging/DEBIAN/control" <<CONTROL
Package: kernelgrove
Version: $deb_version
Section: devel
Priority: optional
Architecture: $arch
Maintainer: $maintainer
Installed-Size: $installed_size
Depends: libxcb-cursor0
Recommends: device-tree-compiler, cpp
Conflicts: dtstudio
Replaces: dtstudio
Description: Device Tree Studio - visual editor for Linux Device Trees
 KernelGrove edits and generates Linux Device Trees against the kernel's own
 binding schemas: which properties a compatible requires, which bindings
 apply to a node, and what an overlay is allowed to change.
 .
 The bindings database is distributed separately from the program: drop it
 in ~/.kernelgrove/bindings.db or point KERNELGROVE_DB_PATH at it.
 .
 Compiling and decompiling overlays needs device-tree-compiler and cpp.
 They are Recommends and not Depends because everything else works without
 them: the program detects what is installed and says so.
CONTROL

# --root-owner-group evita que el paquete se lleve el uid del que construye:
# sin eso, todo quedaría instalado como el usuario del build.
dpkg-deb --build --root-owner-group "$staging" "dist/kernelgrove_${deb_version}_${arch}.deb"

echo
echo "Construido dist/kernelgrove_${deb_version}_${arch}.deb. Instalar con:"
echo "  sudo apt install ./dist/kernelgrove_${deb_version}_${arch}.deb"
