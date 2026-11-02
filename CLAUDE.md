# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

KernelGrove ("Device Tree Studio") is a visual editor and generator for Linux Device Trees. Rather than editing DTS text directly, the goal is a semantic engine that answers questions like "which properties are mandatory for this compatible?" and "which bindings apply to this node?", backed by a database built from the kernel's own binding schemas. The PySide6 GUI is a front-end on top of that engine.

It is open source under the Apache License 2.0 (`LICENSE`, `NOTICE`) and ships as a public beta (1.0b3, `.deb` + Windows installer). Contribution rules — DCO sign-off, tests, translations — are in [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Where each thing is documented

This file is the index: commands, the shape of the codebase, the traps, and the rules that bind every edit. The detail lives next door, and **the detail is where a change of that area has to be checked**:

| Area | Document |
|---|---|
| Ingestion — `db_manager/`, the DB tables, bus inference, `schemas.since` | [`docs/ARCH-INGESTION.md`](docs/ARCH-INGESTION.md) |
| Semantic engine — parser, the six check layers, corpus numbers | [`docs/ARCH-ENGINE.md`](docs/ARCH-ENGINE.md) |
| Overlays and the build (check-then-compile, BUILD TOOLS) | [`docs/ARCH-OVERLAYS-BUILD.md`](docs/ARCH-OVERLAYS-BUILD.md) |
| API facade, `dt_model`, database distribution and include resolution | [`docs/ARCH-API-MODEL-DB.md`](docs/ARCH-API-MODEL-DB.md) |
| GUI — activity bar, editor, graph, catalogue, git panel, skins | [`docs/ARCH-GUI.md`](docs/ARCH-GUI.md) |
| Third-party notices shown in Help → Licenses | [`src/kernelgrove/gui/LICENSES.md`](src/kernelgrove/gui/LICENSES.md) |
| How to contribute | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| Check-layer order and rationale | [`docs/SEMANTIC-ENGINE-FLOW.md`](docs/SEMANTIC-ENGINE-FLOW.md) |
| dt-schema integration | [`docs/DT-SCHEMA-INTEGRATION.md`](docs/DT-SCHEMA-INTEGRATION.md) |
| Packaging | `packaging/linux/README.md`, `packaging/windows/README.md` |
| Release prerequisites and checklist | [`docs/RELEASING.md`](docs/RELEASING.md) |

## Commands

Work inside the virtualenv (`source .venv/bin/activate`); the package is installed editable.

- **Run the GUI app:** `python -m kernelgrove` (equivalently `python -m kernelgrove.main`). Falls back to a message if `PySide6` is missing (`pip install PySide6`) or, on Linux/X11, if the system lib `libxcb-cursor0` is missing (`sudo apt install libxcb-cursor0`) — Qt ≥6.5 needs it for the `xcb` platform plugin and otherwise aborts the process (SIGABRT) instead of raising a catchable exception, so `main.py` checks for it upfront via `_missing_xcb_runtime_deps()`.
- **Build the bindings database** from kernel YAML schemas into `database/bindings.db`:
  `python -m kernelgrove.db_manager.main --root kernel/linux/Documentation/devicetree/bindings`
  Flags: `--root`, `--sqlite`, `--table` (`bindings`, `devicetrees`, `socs`, `boards`, `sources`, `schemas`, `macros` or `kernel`), `--reset`, `--include-root`, `--kernel-repo`. There is no `--json`: the dumps it wrote (`bindings.json` + `socs.json` + `boards.json`, 115 MB rewritten on every build) were read by nothing. `devicetrees` fills `socs` **and** `boards` in one walk — they come from the same `.dts`/`.dtsi` files and only `classify_devicetree` tells them apart, so `--table socs` followed by `--table boards` parses the whole tree twice (~150 s each) to throw away what the other pass kept. `macros` (layer-3 macro index, see below) reads macro *names* from the already-populated `sources` table instead of `--root`, so run it after `sources`; `--include-root` (default `kernel/linux/include`) is the `cpp -I` root it uses to additionally resolve each macro's *value* — pass `--include-root ''` to skip value resolution (or it degrades to names-only automatically when no `cpp`/`gcc`/`cc` is on PATH).
- **Date the bindings** with the kernel release each one first shipped in: `--table kernel` (~8 s). It reads no files — it walks the *history* of the checkout named by `--kernel-repo` (default `kernel/linux`) and fills `schemas.since`. See the `schemas.since` note below.
- **Build every table at once:** `scripts/build_database.sh` (bindings and processed schemas from the kernel YAML, socs/boards/sources/macros from `.dts`/`.dtsi`/`dt-bindings/*.h` files; `--bindings-root`, `--socs-root`, `--sqlite` override the defaults).
- **Install the ingestion extra** before building: `pip install -e '.[ingest]'` — pulls in `dtschema` and `pyyaml`, which the ingestion needs (see `docs/DT-SCHEMA-INTEGRATION.md`). Both are *build-time* dependencies only: the installed app reads the already-processed schemas from the DB and never imports either. Without `dtschema` the `bindings` ingestion still works (degraded, no `$ref` resolution) and the `schemas` step warns and skips.
- **Package it for Linux:** `bash packaging/linux/build.sh` (PyInstaller `--onedir` into `dist/kernelgrove/`) and then `bash packaging/linux/build_deb.sh` (a `.deb` into `dist/`, installable with `sudo apt install ./dist/kernelgrove_*.deb`). The package declares `Recommends: device-tree-compiler, cpp` — `apt` installs them by default so compiling works out of the box, and `Recommends` rather than `Depends` because everything else works without them and `api/toolchain.py` already detects and explains their absence. They are never bundled or downloaded: they are distro packages with their own security updates. It also declares `Conflicts`/`Replaces: dtstudio`, the name the program had until 1.0b2: without that pair `apt` treats the two as unrelated packages and leaves both installed, each in its own `/opt` and each with its own menu entry. See `packaging/linux/README.md`.
- **Where the releases live:** in this same repo, `serg4life/kernelgrove`. Each `v*` release carries `manifest.json`, the `.deb` (`scripts/publish_release.sh`) and the Windows installer (attached by `.github/workflows/windows.yml` when the tag is pushed); the database has its own pinned `db-vN` prerelease (`scripts/publish_database.sh`), and `tools-v1` holds `dtc` and `cpp` for the Windows installer's optional component. `KERNELGROVE_RELEASE_REPO` overrides the repo in the three scripts. Versions 1.0b1–1.0b3 read their manifest from the old `serg4life/kernelgrove-releases` repo, so **that repo must stay (archived), not be deleted**, or those installs lose their database download.
- **Package it for Windows:** `packaging\windows\build.ps1` (PyInstaller `--onedir` into `dist\kernelgrove\`) and then `packaging\windows\build_installer.ps1` (an Inno Setup per-user installer into `dist\`). On a Windows machine — PyInstaller does not cross-compile. The one thing that is not a copy of the Linux path is **`dtc` and `cpp`**: on Linux they are distro packages and the `.deb` only recommends them, but Windows has no official `dtc` at all and the preprocessor only ships inside multi-hundred-megabyte installers, so the installer offers an optional component that downloads them from static hosting with a `sha256` — the same shape as the database, no API behind it — unpacks them with the `tar.exe` Windows has carried since 1803, and leaves them in `{app}\tools`, which `toolchain._bundled_tools_dir` looks in **without touching the `PATH`** (a global change for one program, and one that would not reach an already-running process anyway). The URLs are empty in the repo and injected at compile time; while they are, the component is not compiled in and the installer ships without it. `console=False` is what forced `creationflags=NO_WINDOW` onto every `subprocess.run` in `toolchain.py` and `compile_overlay.py`: with no console of its own, each one opens a black window. See `packaging/windows/README.md`.
- **Build the translations** after changing any user-facing string: `scripts/build_translations.sh` (re-extracts into every `.ts` and compiles the `.qm`). `--add <lang>` starts a new language. See the language rules at the end of this file.
- **Lint:** `ruff check .` (config in `pyproject.toml`: rules `E,W,F,N`, line length 88, Black-compatible). `src/kernelgrove/gui/**` ignores `N802`/`N815` because Qt's overridable API is camelCase.
- **Tests:** `pytest`, or a single file. ~30 files under `tests/`, one per area, named after what they hold (`test_spec_checks` layer 1, `test_binding_checks` layer 5, `test_generic_checks` layer 2, `test_macro_checks` layer 3, `test_overlay_checks` layer 6, `test_gui_smoke` the window, `test_theme_contrast` the skins, and so on) — read the directory rather than a list here, which goes stale on every commit. Some skip without their prerequisite: the schema and GUI ones need `database/bindings.db`, `test_git_repo` needs `git`, the compiling half of `test_build` needs `dtc`/`cpp`. CI is `.github/workflows/ci.yml`. `tests/conftest.py` points `XDG_CONFIG_HOME` at a temp dir before Qt loads: several tests change skin, mode and language, and `QSettings` was writing them into the real `~/.config/KernelGrove/…conf` — running the suite changed the theme of the developer's own app, and the tests then read back whatever the machine happened to hold.
- **Corpus check** (the kernel `.dts`/`.dtsi` treated as a ground truth for false positives): `python scripts/check_corpus.py` — `--limit N` for a sample, `--code <diagnostic-code>` to isolate one rule, `--syntax` for the parser's diagnostics instead of the semantic ones, `--schema` for the **deferred pass** (layer-5 values and all of layer 2), which the app runs in a background thread and therefore is measured separately.

Requires Python ≥3.11. Runtime deps are declared in `pyproject.toml`: `PySide6` (GUI) and `jsonschema>=4.18` (validating values against the stored schemas — 4.18 is the first version with `referencing`, which is how `$ref`s resolve without touching the disk). `dtschema` and `pyyaml` live in the optional `ingest` extra because they are only needed to *build* the database — nothing under `api`/`gui`/`dts_engine` imports `yaml`, checked directly, which is why `pyyaml` moved out of the base dependencies.

Headless environments (CI, containers without a display) can drive the GUI with `QT_QPA_PLATFORM=offscreen`.

**Releases only carry what is polished.** `gui/features.experimental()` is the one switch: on in a source checkout, off in a packaged build (`sys.frozen`), and `KERNELGROVE_EXPERIMENTAL=1`/`0` overrides it either way. Today it gates *generating* from the graph — the Connections section, the device palette, editing the tree from the graph, the SoC panel and *Disconnect device* (`MainWindow._hidden_sections`, `VisualizerTab.set_editable`); *viewing* the graph is stable. A new feature that is not ready asks `experimental()` where it is mounted, and loses the question when it is.

## Architecture in one page

Two pipelines share the internal model and the SQLite database.

1. **Ingestion (offline).** `db_manager/` turns the kernel's `Documentation/devicetree/bindings/*.yaml` and its `.dts`/`.dtsi`/`dt-bindings/*.h` into `database/bindings.db`. Build-time only — see [`docs/ARCH-INGESTION.md`](docs/ARCH-INGESTION.md).
2. **Editor/generator (interactive).** A source is opened in the editor and parsed; the semantic engine validates it; the GUI derives the graph and the connection list from the document being edited.

**The dependency direction is the one rule that must not bend:**

- `dt_model/` — Qt-free dataclasses, the common language. Depends on nothing.
- `dts_engine/` — parser and checks. Depends on `dt_model` and nothing else; the DB is **injected**, never imported. Never make it depend on `db_manager` or `api`.
- `api/` — the facade over the DB and the engine. Must not import Qt.
- `gui/` — imports from `kernelgrove.api` and nothing else (the model types are re-exported from `api/__init__.py` for that reason).
- `db_manager/` imports `dts_engine.parser` for the socs ingestion; that direction is intentional.

`tests/test_architecture.py` checks these instead of trusting them.

**The checks are layered** (order fixed by [`docs/SEMANTIC-ENGINE-FLOW.md`](docs/SEMANTIC-ENGINE-FLOW.md)): (1) Device Tree specification, (2) generic bindings, (3) `dt-bindings/*.h` constants, (4) kernel drivers — not implemented, (5) the specific binding, (6) overlay targets. A layer only speaks about what its source states and never contradicts an earlier one; when it cannot be sure it stays quiet. `checks/pipeline.run_checks` is the single entry point. Full rules in [`docs/ARCH-ENGINE.md`](docs/ARCH-ENGINE.md).

**The database is self-contained** — the `kernel/` checkout is a build-time input that does not exist on a user's machine. Never add runtime code that reads from it. See [`docs/ARCH-API-MODEL-DB.md`](docs/ARCH-API-MODEL-DB.md).

## Repo state / gotchas

The package was renamed to `kernelgrove` (from earlier `dtgen` / `yaml_bindings`) and internally reorganized. What is still stale:

- **`docs/DATABASE-METHODOLOGY.md` and `docs/INTERNAL-MODEL.md` describe the old prototype** (module names `dtgen`, `yaml_bindings`, run commands like `python3 -m dtgen.app`). Useful for intent, outdated in every path and command.
- **`docs/` is also the Obsidian vault** for this project's standalone documentation (opened directly as a vault; `.obsidian/` is gitignored, it's local state). `README.md` and `CLAUDE.md` stay at the repo root (GitHub landing page / Claude Code project instructions read from a fixed path), and `packaging/*/README.md` stay next to the build script they document; everything else that's pure documentation belongs in the vault.
- `iter_devicetree_files` recurses, so pointing `--socs-root` at the repo root also ingests the ~2700 `.dtsi` files inside the `kernel/` checkout — that is intentional, and is why the `socs` table holds ~900 rows.
- **The REST-style HTTP API does not exist.** `api/service.py` is the in-process facade, which is a different thing.
- Bus coverage is uneven because it is inferred, not declared: `parent_bus` currently resolves to i2c (~325), spi (~264), mdio (10), usb (4), mmc (3), pci (1), everything else `platform`. A controller whose bus has no devices shows an empty dropdown — that is missing inference, not a UI bug.
- The kernel corpus is **not** ground truth for layer 5 the way it is for layer 1: the kernel does not fully validate against its own bindings (`make dtbs_check` on a clean tree produces thousands of warnings). Spot-check each new group by hand.
- The remaining DB-schema traps (ranked compatible resolution, generic compatibles, `relative_key` and symlinks, dropped columns, `ensure_column`) are in [`docs/ARCH-INGESTION.md`](docs/ARCH-INGESTION.md) and [`docs/ARCH-API-MODEL-DB.md`](docs/ARCH-API-MODEL-DB.md). Read them before touching ingestion.

## Language rules

Comments and docs are written in Spanish; match that when editing existing files.

**Diagnostic text is not a comment — it is English, like every other user-facing string.** The engine's messages and hints (`dts_engine/checks/**`, `parser.py`) and the strings `api/` composes for a dialog or the OUTPUT strip (`service.database_health`, `compile_overlay`, `toolchain.install_hint`) were written in Spanish, so an English session showed its own window in English and its diagnostics in Spanish — which is what the log made obvious. They are now English at the source. `checks/bindings/lookup.translate_message` and its `_MESSAGE_REPLACEMENTS` table are **gone**: they existed only to turn `jsonschema`'s own English into Spanish, and with English as the source language that is exactly the text wanted.

The ceiling is deliberate and worth knowing: **these strings cannot be translated.** `dts_engine` depends on nothing beyond `dt_model` and `api` must not import Qt, so there is no `tr()` to wrap them in, and they never reach the `.ts` catalogue. Translating them would mean the engine emitting a code plus its parameters instead of a formatted string, and the GUI composing the sentence — a real change, not a wrapper. Until then a Spanish session reads its diagnostics in English, which is the way round that matches the source language.

**User-facing strings are a different matter: they are written in English and wrapped for translation.** The main market is English-speaking, so English is the *source* language — what's literally in the code, and what shows when no translation is loaded. Any other language is a compiled `.qm` under `src/kernelgrove/gui/translations/`; Spanish is the first one and is complete. So: comments and docstrings in Spanish, anything the user reads in English inside `self.tr("…")` (or `QCoreApplication.translate("<context>", "…")` in a module with no `QObject` to hang `tr()` on, as in `gui/messages.py` and `widgets/tree_graph.py`).

- **No f-strings inside `tr()`** — `lupdate` extracts by *reading the code*, so it cannot see an interpolated string, and at runtime the lookup would fail anyway. Use named fields and `.format()`: `self.tr("Saved to {path}").format(path=path)`. Same reason there is no short wrapper around `QCoreApplication.translate`: after any indirection the strings stop being extracted.
- **No translated constants at module level** — there is no `QApplication` yet when the module is imported, so the text would be frozen in English. That's why `gui/messages.py` exposes `title_*()` functions instead of `TITLE_*` constants, and why `tree_model.COLUMN_HEADER_KEYS` is translated in `headerData` rather than in the list itself.
- After touching any user-facing text, run `scripts/build_translations.sh`: it re-extracts into every `.ts` (keeping what's already translated) and recompiles the `.qm`. `tests/test_translations.py` fails if something is left untranslated, if a `.qm` is out of sync with its `.ts`, or if a translation loses a `{field}` — which would blow up `.format()` at the moment the message is needed. Add a language with `scripts/build_translations.sh --add pt_BR`, then translate it with `pyside6-linguist`.
- **View → Appearance** picks light/dark/system (`SETTING_THEME` in `QSettings`, applied live); `gui/translations.py` picks the language: `KERNELGROVE_LANG` first (that's how the tests force one), then what the user chose in **View → Language** (kept in `QSettings`), then the system locale, then English. It also loads Qt's own `qtbase_<lang>.qm`, which is where the standard dialog buttons ("Save"/"Discard"/"Cancel") and the file dialog get their text — without it a translated window would show its own strings in one language and Qt's in another.
- **Switching language is live, and that is what every widget has to keep working.** Installing a translator makes Qt deliver `QEvent.LanguageChange` to *every* widget (verified: hidden ones and never-shown windows too), so a widget only has to answer it: mix in `translations.Retranslates` and implement `retranslate()`, re-setting there whatever text the constructor set. The pattern is: construct the widget with no text, call `self.retranslate()` at the end of `__init__`, and let the same method serve both cases. **A new widget that forgets this stays in the previous language** — `tests/test_gui_smoke.py::test_cambiar_de_idioma_repinta_la_ventana_sin_reiniciar` walks the whole window and fails when a zone doesn't change.
- What is **not** a widget never gets the event and must be refreshed by hand from `MainWindow.retranslate`: the menus (rebuilt from scratch — and their `QAction`s are parented to their menu, or the old ones survive and Qt reports an ambiguous shortcut), `PeripheralTreeModel` (a `headerDataChanged`/`layoutChanged` is enough), the `ActivityBar` sections (it doesn't know its own texts), and the graph's `QGraphicsItem`s — `VisualizerTab.retranslate` redraws the graph for that reason. Dynamic text that was built once (the status bar, the SoC header, the diagnostics summary) has to be recomposed too, which is why each of those lives in a method that can be called again.
