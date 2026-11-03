# Packaging on Windows

## Build

```powershell
pip install -e '.[packaging]'      # PyInstaller
.\packaging\windows\build.ps1
```

The result lands in `dist\kernelgrove\` — the `kernelgrove.exe` executable
with its DLLs alongside (`--onedir`, not `--onefile`, for the same LGPL reason
as on Linux). To try it:

```powershell
$env:KERNELGROVE_DB_PATH='C:\path\to\bindings.db'; .\dist\kernelgrove\kernelgrove.exe
```

**On a Windows machine.** PyInstaller does not cross-compile: this cannot be
built from Linux. GitHub Actions' `windows-latest` will do.

## Installer

```powershell
.\packaging\windows\build_installer.ps1
```

It leaves `dist\kernelgrove-<version>-win64-setup.exe`. It needs Inno Setup
6.1 or later (`winget install --id JRSoftware.InnoSetup`) — 6.1 is the first
one with the download page used below.

Inno Setup rather than MSI/WiX: same result (Start menu, uninstaller, an entry
in «Installed apps») with a declarative script instead of a project.

It installs **per user**, without asking for administrator rights, into
`%LOCALAPPDATA%\Programs\KernelGrove`. That is one prompt fewer in front of
someone who just wants to try the program, and it avoids the problem that on
Linux forced the database to be looked for in `~` as well: installed under
Program Files, everything the program writes next to itself would need
privileges.

The installer does not ask anyone to accept a licence: Apache-2.0 does not
require it. It copies `LICENSE.txt` and `NOTICE.txt` next to the executable,
which is what the licence does require.

### Upgrading from DTstudio

The program was called DTstudio up to 1.0b2. The `AppId` **has not
changed**, and that is deliberate: it is what makes the new installer an
upgrade of the previous one and not a second product — a single entry in
«Installed apps», which is renamed KernelGrove, and a single uninstaller.

That leaves three things to handle by hand, because Inno only overwrites files
that have the same name:

- **The folder stays as it was** (`%LOCALAPPDATA%\Programs\DTstudio`).
  `UsePreviousAppDir` is left at its default on purpose: forcing
  `...\KernelGrove` would orphan the whole previous folder, some 300 MB nobody
  is going to delete. Hardly anyone reads the folder name; the uninstall
  entry's name, they do, and that one does change.
- **The Start menu group does not stay**: `UsePreviousGroup=no` forces a new
  one called KernelGrove, and `[InstallDelete]` removes the old one with its
  two shortcuts inside. That is what the user looks at.
- **The old executable is deleted** (`[InstallDelete]`: `dtstudio.exe` and
  `_internal\dtstudio`). Without that line it stayed next to the new one,
  launchable from its own shortcut, with its own copy of the package: two
  versions installed at once, and the old one looking for a `~/.dtstudio` the
  new one had already moved away.

The installer does not touch the user's data and does not need to:
`%USERPROFILE%\.dtstudio` and the Qt settings under `HKCU\Software\DTstudio`
are picked up by the program itself on start-up (`kernelgrove/legacy.py`).
The downloaded tools live in `{app}\tools`, which is the same folder as
always, so they stay where they were and the new executable finds them without
doing anything.

## `dtc` and `cpp`: why they are downloaded here

On Linux they are distribution packages and the `.deb` merely recommends them
(`Recommends`), because `apt` installs and updates them. Windows has no
equivalent:

- **`dtc`** has no official Windows distribution. The closest thing is the
  MSYS2 package (`mingw-w64-x86_64-dtc`), which comes as a `.pkg.tar.zst` and
  assumes MSYS2 is installed.
- **The preprocessor** only comes inside large installers (LLVM is around a
  gigabyte installed) or a full MinGW.

Asking that of someone who has just installed a device tree editor is losing
them. So the installer offers an optional component, **«Compilation tools»**,
that downloads them and leaves them in `{app}\tools`.

How it is put together, and why:

- **Static hosting, not an API** — same as the database
  (`kernelgrove/db_download.py`): a `.zip` attached to a GitHub *release* (or
  in a bucket) and its `sha256`. Nothing to keep running.
- **The `sha256` is checked**, which is what Inno itself does when it
  downloads. Half a download weighs the same as a whole one, and a truncated
  `dtc.exe` fails much later and much more confusingly than there.
- **It is downloaded before anything is installed** (in `wpReady`), so a
  network failure does not leave half a program in place.
- **It is unpacked with Windows' own `tar.exe`** (bsdtar, present since 1803,
  and it opens `.zip`). Putting a decompression library into the installer for
  two files would be a dependency for nothing. If it is not there, it says so
  and carries on: the rest stays installed.
- **The `PATH` is not touched.** It is a system-wide change for one particular
  program, and on top of that it would not reach an already-running process.
  Instead `api/toolchain._bundled_tools_dir` looks at the `tools\` next to the
  executable when it is packaged — two lines, and it works the same if someone
  copies their own binaries there by hand.
- **The uninstaller takes `{app}\tools` with it** (`[UninstallDelete]`):
  `[Files]` did not put it there, so it does not know about it on its own.
  `%USERPROFILE%\.kernelgrove` (the database and other user state) stays: it
  is user data.

Without the component, or if the download fails, nothing happens beyond not
being able to compile: the whole application —editing, validating, generating
overlays— is Python over the database, and `toolchain.install_hint()` explains
what is missing.

### What has to be published, and what has to be inside it

The URLs are **empty in the repository**. While they are, the component is not
even compiled in and the installer ships without it. They are injected at
build time.

They point at a GitHub *release*, the same static hosting the database
already uses (`kernelgrove/db_download.py`), with nothing to keep running:

```powershell
$base = 'https://github.com/serg4life/kernelgrove/releases/download/tools-v1'
$env:KERNELGROVE_TOOLS_DTC_URL    = "$base/dtc-1.7.0-win64.zip"
$env:KERNELGROVE_TOOLS_DTC_SHA256 = '<sha256 of the zip>'
$env:KERNELGROVE_TOOLS_CPP_URL    = "$base/clang-win64.zip"
$env:KERNELGROVE_TOOLS_CPP_SHA256 = '<sha256 of the zip>'
.\packaging\windows\build_installer.ps1
```

**With the fixed tag, not with `/releases/latest/download/`.** The database
does use `latest`, and it can because it sits behind a manifest stating the
current `sha256`; here the `sha256` is baked into the installer, so a moving
`latest` would break every installer already published at once. A separate
*release* for the tools (`tools-v1`) also avoids re-uploading the `.zip`s
every time a version of the program comes out.

Each `.zip` has to carry, **at its root** and with no intermediate folder:

- the executable (`dtc.exe`, `clang.exe`), because it is extracted as is into
  `{app}\tools`, and
- **its licence file** alongside (`COPYING` for dtc, `LICENSE.txt` for LLVM).
  Keeping the notices is an obligation under both licences, and this way it
  travels with the binary and leaves with it on uninstall.

For the preprocessor, LLVM's **`clang.exe`**: it is a single self-sufficient
file, whereas MinGW's `cpp.exe` needs its `cc1.exe` next to it. `toolchain.py`
already accepts it as a preprocessor (`CPP_CANDIDATES`) and
`compile_overlay._cpp_command` already adds the `-E` it needs.

**Licences.** What changes compared with Linux is not that they are
downloaded —that already happens with `apt`— but **which server the bits come
from**: there Debian serves them and Debian is the distributor; here we serve
them, so the obligation is ours. It is a checkbox, not a problem:

- `dtc` is **GPL-2.0-or-later**. Publish the tarball of the exact source of
  that build next to the `.zip`, link it from the downloads page, and put its
  `COPYING` inside the `.zip`.
- `clang`/LLVM is **Apache-2.0 with the LLVM exception**: shipping the notice
  (`LICENSE.txt` inside the `.zip`) is enough.

**The application is not affected**: KernelGrove launches them as separate
processes (`subprocess`), links nothing of theirs, and distributing them
together is mere aggregation. That is less of a commitment than the one
already taken on with Qt, which is LGPLv3 and does go inside the bundle. Both
are declared in «Help → Licenses» (`src/kernelgrove/gui/LICENSES.md`), in a
section of their own that states they are not part of the program.

## Code signing

Unsigned, both the `.exe` and the installer trigger SmartScreen («Windows
protected your PC»). A standard certificate (~100–400 USD/year) removes the
warning only after building up reputation; an EV one removes it from day one.
It can wait until there is real distribution to third parties (open-source
projects can apply for free signing, e.g. SignPath). If one is bought, sign
the inner `.exe` **and** the installer, with
`signtool sign /fd sha256 /tr <timestamp> …` as a step after each script.

## What it does NOT carry

The same as on Linux, and for the same reasons (see
`packaging/linux/README.md`): `bindings.db` (the application downloads it by
itself the first time it starts without one, to
`%USERPROFILE%\.kernelgrove\bindings.db`), `kernelgrove.db_manager`, and
`dtschema`/`pyyaml`. Before publishing, check the database manifest URL
(`kernelgrove/db_download.py`).

## The icon

`kernelgrove.ico` was generated from the brand mark
(`src/kernelgrove/gui/brand/logo-icon.svg`) with seven sizes inside (16…256),
which is what Windows asks for to look right in the taskbar and in Explorer:

```
python scripts/build_icon.py            # rasterizes the seven and calls convert
```

Each size is rasterized **separately** from the SVG with the same Qt that
draws the logo in the application, instead of shrinking a 256 PNG: at 16 px a
rescaled sprout blurs, and this way the stroke lands where it should. The
purple that comes out is the file's own (`#8b5cf6`), not the active skin's —
the taskbar does not say what colour its background is, and that one holds up
on both (4.2:1 on white, 4.4:1 on black).

Unlike Linux, here the window icon **does** come from the `.exe` (there is no
`.desktop` in between), so the `.spec`'s `icon=` is enough.

## Pending

- **CI**: `windows-latest` in a `release.yml` with a per-OS matrix, instead of
  manual builds — the same pending item as on Linux.
- **ARM64**: PyInstaller builds for the machine it runs on; it would need a
  Windows ARM64 runner and a separate installer.
