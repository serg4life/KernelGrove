# Demo GIFs

One GIF per feature, recorded **from the real application**: `MainWindow` is
built with `QT_QPA_PLATFORM=offscreen`, driven step by step, and each step is
saved with `QWidget.grab()`. There are no mock-ups and no retouched
screenshots; what you see is what the program does against
`database/bindings.db`.

## Recording

```bash
source .venv/bin/activate
cd scripts/demo_gifs
python scenes.py editor          # one scene -> PNG frames
bash togif.sh editor             # those frames -> out/editor.gif
```

All of them at once:

```bash
for s in editor inspector graph catalogue completion overlay build connect git themes tour; do
    python scenes.py "$s" && bash togif.sh "$s"
done
```

The output goes to `$TMPDIR/kernelgrove-gifs` (`KERNELGROVE_GIF_DIR` changes
it), never into the repository: it is thousands of PNGs. Finished GIFs are
copied by hand to wherever they are needed (the README's is
`docs/kernelgrove-demo.gif`).

It needs `database/bindings.db`, the `kernel/` checkout (where the working
copy comes from) and **Pillow** in some system Python (`pip install pillow`) —
not in the project's virtual environment, which does not carry it: it is not a
dependency of the application. The `build` and `connect` scenes also need
`dtc`/`cpp`; `git` needs `git`.

## How it is put together

- `rec.py` — the recorder. It pins the environment (English, settings in a
  separate `XDG_CONFIG_HOME` so the user's own are not touched), builds the
  window at 1280x800 and offers `shot()`/`hold()`, the drawn pointer
  (`point*`) and the shortcuts for opening a folder and a file. `shot()`
  pastes the floating windows on top —the catalogue, a property's card, the
  autocompletion popup— which in Qt are separate windows and would not show up
  in the main window's `grab()`.
- **The pointer and the camera, for the scenes meant to be watched in full.**
  `point*` places the pointer in one go, which is what works for a single
  screenshot; in a GIF, a cursor that turns up somewhere else between two
  frames cannot be followed by eye. `move*` (`move_to`, `move`, `move_at`,
  `move_item`) travels the path drawing one frame per step, with smooth
  acceleration and braking, and `click()` marks the press with an expanding
  ring —without it, nothing between the frame before and the frame after says
  a click happened, and the screen change looks spontaneous.
  `zoom_to`/`zoom_widget`/`zoom_out` bring the camera closer **by cropping the
  already-composed frame**: the application never notices, the window still
  measures 1280x800 and nothing is relaid out. That is what makes the
  Inspector card or the autocompletion popup readable at 960 px, which would
  otherwise be six-pixel text. The pointer is drawn *after* framing, so it
  keeps its size instead of coming out scaled and blurry.
- `scenes.py` — one script per feature, decorated with `@scene()`. The
  working copy (`ensure_workspace`) is the device trees of
  `kernel/linux/arch/arm64/boot/dts/xilinx` copied into a temporary git
  repository: compiling leaves a `.dtb` next to the source and the overlay
  wizard writes into the open folder, and neither of those can happen inside
  the kernel checkout.
- `togif.py` (and `togif.sh`, which only finds a Python with Pillow and hands
  it over) — the assembly: 960 px, 10 cs per frame and a single palette for
  the whole scene, taken from a spread-out sample. It used to be ImageMagick's
  `convert -layers OptimizeFrame` and no longer is, for two reasons. One:
  `convert` loads **every** frame before writing anything and the system
  policy caps its cache at 2 GiB, about 600 frames at 1280x800 — less than
  `tour` lasts. And two: Pillow does right what `OptimizePlus` did wrong —when
  it finds two identical frames in a row it **adds** the second one's
  duration to the first instead of merging them and losing its time, which is
  exactly what `hold()` needs (a pause is recorded by repeating the same
  frame)— and on top of that it writes each frame cropped to the area that
  changes. In `tour`, 953 frames end up as 454 stored ones with the 95 s
  intact.

## The scenes

| Scene | What it shows |
|---|---|
| `editor` | Opening a real SoC and the semantic engine's diagnostics; clicking one jumps to its line. |
| `inspector` | The Inspector: what the binding says about the node under the cursor, and a property's card. |
| `graph` | The same tree as a graph, expandable and navigable. |
| `catalogue` | The catalogue: SoCs and boards, and the kernel's bindings, searchable. |
| `completion` | Autocompletion drawn from the node's binding, not from a fixed list. |
| `overlay` | The overlay wizard: pick the node, mark what changes, generate the `.dtso`. |
| `build` | Check and compile: overlays are validated against the database before `dtc` is called. |
| `connect` | Hanging a chip off a bus from the palette. |
| `git` | Version control of the open folder, with the editor's gutter marking what was touched. |
| `themes` | The five skins, the two modes and the language, switched live. |
| `tour` | The long walkthrough, on a single node: open a board (zcu102) from the catalogue, click a warning to go to its line, read that node's Inspector, use autocompletion to add a property the node did not have, and view the document as a graph. The pointer moves and the camera zooms in on what needs reading. |
