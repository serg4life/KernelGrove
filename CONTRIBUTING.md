# Contributing to KernelGrove

Thanks for wanting to help! Bug reports, binding false positives, translations,
docs and code are all welcome. This file explains how to set up the project,
what a pull request needs to be merged, and the few rules that keep the
codebase coherent.

By participating you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Reporting bugs and asking for features

Open an [issue](https://github.com/serg4life/kernelgrove/issues/new/choose)
using one of the templates. For a wrong diagnostic, the most useful thing you
can attach is the smallest `.dts`/`.dtsi` that reproduces it, the diagnostic
code and the KernelGrove version (shown in **Help → About**).

Please report security problems privately to **serg4life@duck.com** instead of
in a public issue.

## Development setup

Python ≥ 3.11 is required.

```bash
git clone https://github.com/serg4life/kernelgrove.git
cd kernelgrove
python -m venv .venv && source .venv/bin/activate
pip install -e '.[ingest]' pytest ruff
python -m kernelgrove
```

On Linux/X11 Qt also needs `libxcb-cursor0` (`sudo apt install
libxcb-cursor0`). Compiling device trees needs `dtc` and `cpp` on the `PATH`
(`sudo apt install device-tree-compiler cpp`).

### The bindings database

The app works on top of `database/bindings.db`, built from a Linux kernel
checkout. Either let the app download the published one on first run, or
build your own:

```bash
git clone --filter=blob:none https://github.com/torvalds/linux.git kernel/linux
scripts/build_database.sh
```

Not `--depth 1`: dating each binding needs the kernel's release tags. Everything
a release needs is listed in [`docs/RELEASING.md`](docs/RELEASING.md).

The GUI tests and some engine tests are skipped when the database is missing.

## Before opening a pull request

1. **Tests pass:** `pytest` (use `QT_QPA_PLATFORM=offscreen` on a machine
   without a display). Add a test for what you fix or add; tests live in
   `tests/`, one file per area.
2. **Lint is clean:** `ruff check .`
3. **Translations are rebuilt** if you touched any user-facing text:
   `scripts/build_translations.sh` (needs the PySide6 tools). See
   *Conventions* below.
4. **Every commit is signed off** (see *Developer Certificate of Origin*).
5. If the change is user-visible, add a line to `CHANGELOG.md` under
   *Unreleased*.

Keep pull requests focused: one fix or feature per PR is much easier to review
than a mix. For anything large, open an issue first so we can agree on the
approach.

## Conventions

- **Layering is enforced.** `dt_model` depends on nothing; `dts_engine` only on
  `dt_model` (the database is injected, never imported); `api` must not import
  Qt; `gui` only imports from `kernelgrove.api`. `tests/test_architecture.py`
  fails if a change breaks this. The architecture docs in `docs/ARCH-*.md`
  explain each area.
- **The semantic checks are layered** (spec → generic bindings →
  `dt-bindings` headers → specific binding → overlays). A check only reports
  what its source states, and stays quiet when it cannot be sure. Run
  `python scripts/check_corpus.py` against the kernel tree to make sure a new
  rule does not fire on valid upstream files.
- **User-facing strings are English and translatable:** wrap them in
  `self.tr("…")` (or `QCoreApplication.translate(...)`), never use f-strings
  inside `tr()` — use `.format()` with named fields — and don't build
  translated constants at module level. New widgets must handle live language
  switching (`translations.Retranslates`).
- **Diagnostics and messages from `dts_engine`/`api` are plain English
  strings** (those layers have no Qt to translate with).
- **Documentation is English**: `docs/`, READMEs, the changelog and workflow
  comments.
- **Comments and docstrings are mostly in Spanish**, which is how the codebase
  was written. Match the language of the file you are editing; English is fine
  in new files.
- **New features that are not polished yet ship as experimental**: ask
  `kernelgrove.gui.features.experimental()` where the feature is mounted. It is
  on when running from source and off in packaged releases;
  `KERNELGROVE_EXPERIMENTAL=1` turns it on in a release, `0` off in a checkout.
- Formatting follows Black (line length 88); `ruff` enforces `E,W,F,N`.

## Developer Certificate of Origin (DCO)

KernelGrove uses the [Developer Certificate of Origin](https://developercertificate.org/),
the same mechanism as the Linux kernel, instead of a CLA. By adding a
`Signed-off-by` line to a commit you certify that you wrote the change, or
otherwise have the right to submit it under the project's license
(Apache-2.0).

Sign off with `-s`:

```bash
git commit -s -m "Fix false positive on interrupts-extended"
```

which appends:

```
Signed-off-by: Your Name <you@example.com>
```

The name and email must match the commit author. A CI check rejects pull
requests with commits that are not signed off; to fix an existing branch run
`git rebase --signoff main` and force-push.

## Credit

Add yourself to [`AUTHORS`](AUTHORS) in your first pull request if you'd like
to be listed. All contributions are also visible in the git history and on the
[contributors page](https://github.com/serg4life/kernelgrove/graphs/contributors).

## License

By contributing, you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE), the same license as the project.
