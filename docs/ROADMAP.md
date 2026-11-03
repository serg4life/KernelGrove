# Cross-platform packaging roadmap

What to build and in what order, so it does not have to be re-derived the next
time this is picked up. Steps 2, 3 and 4 are already done; what exists today
is described in `packaging/linux/README.md` and `packaging/windows/README.md`.

## Current state

The only artifact produced is `dist/kernelgrove/` via
`packaging/linux/build.sh` + `kernelgrove.spec` — a PyInstaller `--onedir`
directory, **Linux x86_64 only**, with no installer (the binary is run
directly). PyInstaller does not cross-compile: it packages what is installed on
the machine it runs on, so this result is good neither for Linux ARM64 nor for
Windows — each OS and architecture combination has to be built on/for
separately.

## Plan, in the order it is best tackled

1. **Linux ARM64** — low cost. The same `kernelgrove.spec`/`build.sh`,
   untouched, run on an ARM64 runner (GitHub Actions already offers a hosted
   `ubuntu-24.04-arm64`, with no infrastructure of our own to maintain).
   PySide6/jsonschema have arm64 wheels; `dtc`/`cpp` are still provided by
   the user, same as on x86_64. It only needs one more entry in the CI matrix.

2. **`.deb`** — **done**, `packaging/linux/build_deb.sh` (see
   `packaging/linux/README.md`). With `dpkg-deb` instead of `fpm`: `fpm` is a
   Ruby gem that would have to be installed and `dpkg-deb` is already on every
   Debian/Ubuntu. The `.desktop` and the icon, which were missing, now exist
   (`packaging/linux/kernelgrove.desktop` and the brand mark,
   `src/kernelgrove/gui/brand/logo-icon.svg`). It is still one `.deb` per
   architecture, because it packages the arch-specific `dist/`.

3. **Windows, `--onedir` build** — **done**, `packaging/windows/build.ps1`
   + `kernelgrove.spec` (see `packaging/windows/README.md`). Modelled on the
   Linux one plus the three things Windows adds: the `.ico` icon (generated
   from the brand mark, already in the repo), the `.exe`'s version metadata
   —read from `pyproject.toml`, not written by hand— and `console=False`.
   That last one forced a code change the plan had not foreseen: with no
   console, **every `subprocess.run` opens its own**, and `api/toolchain.py`
   probes `dtc`/`cpp` at start-up and when «About» is opened. Now the three
   `run`s in `toolchain.py` and the two in `compile_overlay.py` carry
   `creationflags=NO_WINDOW`, as `git_repo.py` already did. It still has to be
   built on a Windows machine (no cross-compiling) and it is still unsigned.

4. **`.exe` installer (Windows)** — **done**,
   `packaging/windows/kernelgrove.iss` + `build_installer.ps1`. Inno Setup as
   planned, per-user (`PrivilegesRequired=lowest`, no UAC). What the plan had
   not solved is **`dtc` and `cpp`**: on Linux they are distribution packages
   and the `.deb` merely recommends them, but on Windows `dtc` has no official
   distribution and the preprocessor only comes inside installers of hundreds
   of megabytes. It is solved with an optional component that downloads them
   from static hosting with a `sha256` —the same pattern as the database, with
   no API behind it—, unpacks them with the `tar.exe` Windows has shipped
   since 1803 and leaves them in `{app}\tools`, which
   `toolchain._bundled_tools_dir` looks at without touching the `PATH`. The
   URLs are empty in the repository and injected at compile time; while they
   are, the component does not exist and the installer ships anyway. A legal
   detail not to forget: `dtc` is GPL-2.0, and redistributing the binary
   requires offering the source.

## Pending / open decisions

- Windows code-signing certificate: yes/no, and EV or standard — postponed
  until there is a real distribution channel. Without it, both the `.exe` and
  the installer trigger SmartScreen.
- Where the Windows `.zip`s of `dtc` and the preprocessor are published, and
  with them the `dtc` source that GPL-2.0 requires offering.
- App icon: SVG (`src/kernelgrove/gui/brand/`) for Linux and already
  converted to `.ico` for Windows (`packaging/windows/kernelgrove.ico`, seven
  sizes; the command that generates it is in its README).
- AppImage and notarization are still out of scope, see
  `packaging/linux/README.md` § "Pending".
- Automate all of this in CI (`release.yml` with a per-OS/arch matrix) instead
  of manual builds — the same reasoning `packaging/linux/README.md` already
  notes for the Linux-only case.
