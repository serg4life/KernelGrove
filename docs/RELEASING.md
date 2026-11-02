# Releasing KernelGrove

What you need installed, and in which order to use it, to produce and publish
a KernelGrove release. The packaging details — why `--onedir`, what goes into
the `.deb`, how the Windows installer handles `dtc`/`cpp` — are in
[`packaging/linux/README.md`](../packaging/linux/README.md) and
[`packaging/windows/README.md`](../packaging/windows/README.md); this page is
the list of prerequisites and the sequence.

## What a release is made of

Everything is published as GitHub releases of this repository:

| Release | Contents | Built on | Published by |
|---|---|---|---|
| `vX.Y…` (one per version) | `kernelgrove_amd64.deb`, `kernelgrove-<version>-win64-setup.exe`, `manifest.json`, SHA-256 table | Linux x86_64 + Windows x64 | `scripts/publish_release.sh` (Linux side), `.github/workflows/windows.yml` (installer) |
| `db-vN` (prerelease, pinned) | `bindings.db` | Any Linux machine with the kernel checkout | `scripts/publish_database.sh` |
| `tools-v1` (prerelease, pinned) | `dtc` and `clang` for Windows, plus the `dtc` source tarball | Prepared by hand, once | `gh release create tools-v1 --prerelease …` |

The installed app reads `releases/latest/download/manifest.json` to find the
database, so **the latest release must always be a `v*` one that already
carries its `manifest.json`**. That is why `db-vN` and `tools-v1` are
prereleases (GitHub never makes a prerelease "latest"), and why the Windows
workflow, when it gets to a tag first, creates its release as a **draft**:
`publish_release.sh` publishes it once the manifest is uploaded.

## Prerequisites

### Common to every step

| Tool | Version | Why |
|---|---|---|
| Python | ≥ 3.11 (CI uses 3.11) | Everything is Python |
| git | any recent | Cloning, tagging; the database build also reads kernel tags |
| A virtualenv with the project | `pip install -e .` | Run from the repo root |
| bash | — | All the `scripts/*.sh` (on Windows, Git Bash is enough for the publishing scripts) |

### 1. The bindings database (`db-vN`)

Only needed when the database changes; most app releases reuse the current
`db-vN`.

| Requirement | Notes |
|---|---|
| Linux (or WSL) | `scripts/build_database.sh` is bash |
| `pip install -e '.[ingest]'` | Pulls `dtschema ≥ 2023.9` and `pyyaml ≥ 6.0`. Without `dtschema` the `schemas` table is skipped and layer 5 of the engine has nothing to check against — never publish a database built that way |
| Linux kernel checkout **with its release tags** at `kernel/linux` | `git clone --filter=blob:none https://github.com/torvalds/linux.git kernel/linux` keeps every commit, tree and tag but downloads file contents only for the checked-out version. **Not `--depth 1`**: the `kernel` step dates each binding by reading the tree of every release tag, and a shallow clone has none, so `schemas.since` would be left empty |
| `cpp` (or `gcc`/`cc`) on `PATH` | Resolves the value of each `dt-bindings/*.h` macro. Without it the `macros` table degrades to names only |
| Disk and time | The resulting `bindings.db` is ~80 MB; the `.dts`/`.dtsi` walk alone takes a few minutes |

Check out the kernel release the database should describe, then:

```bash
scripts/build_database.sh
python scripts/check_corpus.py --limit 200   # sanity check against the kernel tree
bash scripts/publish_database.sh db-vN       # next unused number; published databases are never rewritten
```

Then set `DB_TAG=db-vN` in `scripts/publish_release.sh`: it is the database
the next app release will point at.

### 2. The Linux package (`.deb`)

| Requirement | Notes |
|---|---|
| Linux **x86_64** | PyInstaller does not cross-compile: the bundle matches the machine it is built on. An ARM64 package needs an ARM64 machine |
| `pip install -e '.[packaging]'` | PyInstaller ≥ 6.0 |
| `dpkg-deb` | Ships with Debian/Ubuntu (`dpkg` package) |
| `libxcb-cursor0` | Only to run and smoke-test the bundle (Qt ≥ 6.5 needs it for X11) |
| `scripts/build_translations.sh` up to date | The `.qm` files travel inside the bundle; `pytest` fails if they are stale |

```bash
bash packaging/linux/build.sh       # → dist/kernelgrove/
bash packaging/linux/build_deb.sh   # → dist/kernelgrove_<debian-version>_amd64.deb
```

`KERNELGROVE_DEB_MAINTAINER` overrides the `Maintainer:` field.

### 3. The Windows installer (`.exe`)

Built by `.github/workflows/windows.yml` on every `v*` tag, which attaches it
to the release. To build it by hand you need:

| Requirement | Notes |
|---|---|
| Windows 10 1803+ x64 | PyInstaller does not cross-compile; 1803 is the first with the `tar.exe` the installer uses for the optional tools |
| Python ≥ 3.11 and `pip install -e '.[packaging]'` | Same as Linux |
| Inno Setup ≥ 6.1 | `winget install --id JRSoftware.InnoSetup` (preinstalled on GitHub's `windows-latest`) |

```powershell
.\packaging\windows\build.ps1             # → dist\kernelgrove\
.\packaging\windows\build_installer.ps1   # → dist\kernelgrove-<version>-win64-setup.exe
```

**Optional compilation tools.** The installer only offers the *Compilation
tools* component when these four variables are set at build time (in CI they
come from repository secrets with the same names):

| Variable / secret | Value |
|---|---|
| `KERNELGROVE_TOOLS_DTC_URL` | `https://github.com/serg4life/kernelgrove/releases/download/tools-v1/<dtc zip>` |
| `KERNELGROVE_TOOLS_DTC_SHA256` | SHA-256 of that zip |
| `KERNELGROVE_TOOLS_CPP_URL` | `…/tools-v1/<clang zip>` |
| `KERNELGROVE_TOOLS_CPP_SHA256` | SHA-256 of that zip |

Without them the installer is built anyway, just without the component.
The zips are prepared once and published to `tools-v1`: each one holds the
executable (`dtc.exe`, `clang.exe`) **and its license file** (`COPYING`,
`LICENSE.txt`) at its root, and because `dtc` is GPL-2.0 the release must also
carry the exact source tarball of that build.

### 4. Publishing

| Requirement | Notes |
|---|---|
| [GitHub CLI](https://cli.github.com/) (`gh`) | Authenticated (`gh auth login`) as someone with write access to the repository |
| The repository **public** | Release assets of a private repository cannot be downloaded anonymously, so the app could not fetch the manifest or the database |
| `KERNELGROVE_RELEASE_REPO` (optional) | Overrides `serg4life/kernelgrove` in the three publishing scripts — for forks, or a test repository |
| Workflow permissions | `windows.yml` declares `contents: write` to attach the installer; no extra secret is needed for that |

## Release checklist

1. Bump the version in **both** `pyproject.toml` and
   `src/kernelgrove/__init__.py` (`tests/test_version.py` fails if they
   differ). PEP 440 form: `1.0b4`, `1.0`.
2. Move the *Unreleased* notes in `CHANGELOG.md` under a `## v<version>`
   heading — `release_notes.sh` copies exactly that section into the release.
3. `scripts/build_translations.sh`, `ruff check .`, and `pytest` with the
   database present (without it the GUI tests are skipped, not run).
4. If the database changed: step 1 above, and update `DB_TAG`.
5. Commit, then build the `.deb` (step 2).
6. Tag and push: `git tag v<version> && git push origin v<version>`. CI builds
   the Windows installer and attaches it to the release, creating it as a
   draft if it does not exist yet.
7. `bash scripts/publish_release.sh` — uploads the `.deb` and `manifest.json`
   (creating the release if CI has not), publishes it as latest, and writes
   the notes.
8. Once the Windows job has finished, run `bash scripts/release_notes.sh` again
   so the SHA-256 table includes the installer. It reads the release through
   the API, which does not see drafts, so run it only after step 7.
9. Install the `.deb` on a clean machine and check that the database downloads
   on first run.

Packaged builds only enable what is stable: features still behind
`gui/features.experimental()` stay off unless `KERNELGROVE_EXPERIMENTAL=1` is
set. Check with that variable unset before tagging.
