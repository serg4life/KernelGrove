# Changelog

Una sección por versión publicada, en inglés: `scripts/release_notes.sh` copia
la de la etiqueta que le pases al cuerpo de la release de GitHub, y debajo pega
la tabla de assets con sus SHA-256. Escribe aquí lo que cambia de una beta a la
siguiente y nada más — la tabla la genera el script.

## Unreleased

### Changed

- **Licensed under the Apache License 2.0.** The source is public. **Help →
  Licenses** shows the project's license and the third-party notices, and the
  installers ship `LICENSE` and `NOTICE`.
- Generating from the graph (the *Connections* section, the device palette,
  editing the tree from the graph, the SoC panel) is **experimental**: on when
  running from source, off in the packaged builds unless
  `KERNELGROVE_EXPERIMENTAL=1` is set. Viewing the graph is unchanged.

## v1.0b3

### Added

- **`/delete-node/` and `/delete-property/` are applied.** They were parsed and
  then ignored, so a board that deletes what its SoC `.dtsi` declares was still
  checked against a tree carrying nodes and properties the compiled binary does
  not have. 525 of the kernel's 6,347 `.dts`/`.dtsi` use them. The target can be
  a name, a label or a path, and it is resolved after the includes are merged —
  which is the real case: a board deleting from the `.dtsi` it includes.
- **Ctrl+click on a `&label` goes to where the node is declared**, in the same
  file or in the `.dtsi` an `#include` brings in — the same gesture that already
  opened includes, and it works on a reference inside a value
  (`clocks = <&clk 1>`), not just on a reopening header.

### Changed

- **DTstudio is now KernelGrove.** An existing install upgrades in place: the
  user's state and the Qt settings are picked up automatically, `apt` replaces
  the old package, and the Windows setup upgrades over it instead of installing
  a second program.

## v1.0b2

### Added

- **Windows x64 build.** A per-user installer, so it does not ask for
  administrator. Windows has no package manager to bring in `dtc` and a
  preprocessor the way `apt` does, so the setup offers them as an optional
  **Compilation tools** component; skip it and everything except compiling and
  decompiling still works.
- Third-party notices (Qt, the Inter font, `dtc`, `clang`).

### Fixed

- **On Windows the application exited on startup without saying anything** —
  clicking the icon did nothing, with no message anywhere. The check for a
  graphical session asked for `DISPLAY`/`WAYLAND_DISPLAY`, which only exist on
  X11 and Wayland, so it answered "no display" on every Windows machine; a
  freshly installed copy has no database yet, so it decided there was nobody to
  ask, wrote the error to a console that a windowed build never creates, and
  quit.
- **The installer did not follow the chosen language.** On a Spanish Windows the
  wizard came up entirely in Spanish with no way offered to change it. The
  language page is now always shown, and the optional component and the
  wizard's own messages follow it.

## v1.0b1

First public beta, Linux x86_64. A desktop editor for Linux Device Trees:
validation as you type against the kernel's own bindings, a node inspector
saying what each `compatible` requires, the tree drawn as a graph, a catalogue
of 3,600+ SoCs and boards and 25,000+ bindings, and an overlay assistant that
writes, validates and compiles `.dtso` files.
