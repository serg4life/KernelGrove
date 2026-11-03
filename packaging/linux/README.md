# Packaging on Linux

## Build

```
pip install -e '.[packaging]'      # PyInstaller
bash packaging/linux/build.sh
```

The result lands in `dist/kernelgrove/` — a directory with the `kernelgrove`
executable and its libraries alongside (`--onedir`, not `--onefile`; see why in
`kernelgrove.spec`). To try it:

```
KERNELGROVE_DB_PATH=/path/to/bindings.db dist/kernelgrove/kernelgrove
```

## Install (`.deb`)

```
bash packaging/linux/build_deb.sh
sudo apt install ./dist/kernelgrove_<version>_<arch>.deb
```

It packages the `dist/kernelgrove/` that was just built — compiling nothing,
only metadata, the `.desktop` and the icon, which is what turns it into
something that shows up in the applications menu and that `apt remove` cleans
up completely. With `dpkg-deb` and not `fpm` (which is what `docs/ROADMAP.md`
had noted): `fpm` is a Ruby gem that would have to be installed, and
`dpkg-deb` ships with every Debian/Ubuntu, which is exactly where a `.deb` is
built.

What it installs:

| Path | What |
|---|---|
| `/opt/kernelgrove/` | the whole PyInstaller bundle |
| `/usr/bin/kernelgrove` | a link to the executable |
| `/usr/share/applications/kernelgrove.desktop` | the menu launcher |
| `/usr/share/icons/hicolor/scalable/apps/kernelgrove.svg` | the brand mark |

**The window icon comes from this entry, not from the application.** GNOME
does not use the icon the window carries (`_NET_WM_ICON`, which Qt does fill
from `app.setWindowIcon`): it associates the window with a `.desktop` through
the identifier it declares (`QApplication.setDesktopFileName`, «kernelgrove»)
and takes the icon from there. Without the entry installed, what shows is the
theme's `application-x-executable` — in Yaru, a gear. That is why the file
name (`kernelgrove.desktop`), the `Icon=` (`kernelgrove`, which resolves
against `hicolor`) and the application identifier have to match: change one
and you have to change all three. To run from the repository,
`scripts/install_desktop_entry.sh` installs the equivalent into `~/.local`
without sudo.

It declares `Depends: libxcb-cursor0` — the system library Qt ≥6.5 needs for
the `xcb` plugin and that the application checks for by hand at start-up
(`main._missing_xcb_runtime_deps`); as a package dependency, that check never
gets to be needed.

And `Recommends: device-tree-compiler, cpp`, the two tools overlays are
compiled and decompiled with (`api/toolchain.py`). In `Recommends` and not in
`Depends` on purpose: `apt` installs them by default, so compiling works right
after installing, but everything else works without them and the program
already detects which ones are there and explains whichever is missing. They
are never bundled or downloaded — they are distribution packages, with their
own security updates, and bringing them inside would mean taking on patching
them.

One `.deb` per architecture: it packages a `dist/` that PyInstaller built for
the machine it was run on.

**The database does not go inside** (see below). Installed in `/opt`, which
belongs to root, keeping it next to the executable would require `sudo` for a
file that belongs to the user, so `main._default_db_path` also looks for it in
`~/.kernelgrove/bindings.db`. When something goes wrong there, the
application says so **in a dialog**: launched from the menu there is no
terminal to read a console message in, and clicking the icon seemed to do
nothing.

Before publishing, check the maintainer address
(`KERNELGROVE_DEB_MAINTAINER`). The package's `copyright` is the repository's
`NOTICE` and `LICENSE`, which Apache-2.0 requires in any redistribution.

## What it does NOT carry, and why

- **`bindings.db`**: the database is an artifact independent of the software
  (which also shapes how the Linux-kernel-derived content it holds is treated
  — GPL-2.0 and BSD-2-Clause mixed, depending on the file). By default the
  executable looks for it next to itself, or wherever `KERNELGROVE_DB_PATH`
  says — the build itself never generates nor includes it.
- **`kernelgrove.db_manager`** (the ingestion tool) **nor `dtschema`/`pyyaml`**:
  explicitly excluded in `kernelgrove.spec` (`excludes=[...]`), and it has
  already been verified that no real import reaches them from `gui`/`api`/
  `dts_engine` — the exclusion is belt and braces, not the only barrier.

## Qt LGPL compliance

PySide6/Qt is distributed under LGPLv3, among other options. `--onedir` leaves
its libraries as loose `.so` files in `dist/kernelgrove/_internal/`, not
compressed inside a single binary — that way a user can replace them, which
is LGPL's condition for shipping it inside an application under a different
licence. Do not switch to `--onefile` without reviewing that condition again.

## Other platforms

This directory is Linux x86_64 only — PyInstaller does not cross-compile. For
ARM64, Windows and their installers, see the plan in `docs/ROADMAP.md`.

## Pending (not implemented in this pass)

- **AppImage**: wrap `dist/kernelgrove/` with `linuxdeploy` +
  `linuxdeploy-plugin-qt` for a single executable file with no installation.
  Not included here because it requires downloading those tools and could not
  be validated in this environment — the `--onedir` above is already a working
  Linux build, the AppImage is only a distribution wrapper on top.
- **Signing/notarization**: does not apply on Linux the way it does on
  Windows, but publishing SHA256 sums for each release is worthwhile.
- **CI**: automate this script in GitHub Actions (`ubuntu-latest`) on each
  tag, so as not to depend on one particular machine.
