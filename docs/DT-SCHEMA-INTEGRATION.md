# dt-schema integration

What [dt-schema](https://github.com/devicetree-org/dt-schema) brings to
KernelGrove, what has been integrated, **what has not**, and what is still
pending. dt-schema is the reference implementation the kernel uses to validate
its own bindings (`make dt_binding_check`), so using it avoids reimplementing
the schema composition rules.

## Summary

| | Before | Now |
|---|---|---|
| Compatible extraction | our own walk over the YAML | `dtschema.extract_node_compatibles` |
| Registered compatibles | 26 603, of which **1 161 were not compatibles** | 25 458 in `binding_compatibles` and 26 460 in `schema_compatibles`, each with its schema and its node (753 belong to subnodes) |
| Bogus `bindings` rows | 62 (`iface`, `host`, `pcie`, `gpio30`…) | 0 |
| A binding's properties | the ones the YAML lists | the ones it lists **plus the ones it inherits** (+18.9 on average) |
| `required` | those of the raw YAML | those of the YAML **and its `$ref`s** (1 988 entries that used to be invisible) |
| Property types | — | 4 761 by name + 84 by pattern |
| Validation against bindings | — | layers 2 and 5 of the semantic engine |
| Value validation | — | the schema itself, with `jsonschema` |
| Autocompletion | — | a list in the editor, with a value template |
| An MFD's subdevices | — | their own dropdown in the generator |

Figures measured on kernel 7.2-rc5 with dtschema 2026.6.

## What the ingestion does

`scripts/build_database.sh` adds a step, `--table schemas`, that processes
every YAML under `Documentation/devicetree/bindings` with dt-schema (about
90 s) and stores the result in the database. It is the same thing
`dt-mk-schema -j` does, with the *fixups* applied: shorthand notation
expanded, types and dimensions normalised, and implicit properties (`status`,
`phandle`, `pinctrl-*`) added.

New tables:

| Table | Content |
|-------|---------|
| `schemas` | the 5 663 processed schemas, indexed by `$id`, with the original YAML alongside (`raw`) because the fixups delete `description` and `examples` |
| `schema_compatibles` | the 26 460 declared compatibles: which schema declares them, **in which of its nodes** (`node_path`) and **at what position** in the list, including the 753 from subnodes and those declared through `select` |
| `schema_meta` | the dtschema version used and the property-type map |

In addition, `bindings.schema_id` links each binding to its schema.

Cost: **+17 MB** on the database, which goes from 87 to 104 MB (3.3 MB of
schemas and 5.0 MB of raw YAML, both compressed, plus the indexes), and
~100 s of ingestion.

**The dependency is build-time only.** `dtschema` is declared in
`pyproject.toml` as the `ingest` extra (`pip install -e '.[ingest]'`); the
installed application never imports it: it reads the already-processed
schemas from the database. Without `dtschema` installed the bindings
ingestion still works and the `schemas` step warns and is skipped.

## What the application does with them

### Resolving a compatible

`api/binding_schemas.BindingSchemaLookup` answers «what does the binding say
about this node». The real work is following the inheritance: a binding does
not list its properties, it references the schemas of its device class and of
its bus with `allOf`/`$ref`. Cadence's I2C controller declares 14 properties
and inherits up to 48, with `#address-cells`/`#size-cells` fixed at 1 and 0.

Rules the resolution follows:

- **Exact**: `schema_compatibles` with the `node_path`, so that
  `ti,twl4030-pwm` is validated against the MFD's subnode and not against the
  whole MFD.
- **Conditional branches only in the permissive direction**: what an
  `if/then`, a `oneOf` or an `anyOf` declares counts as an *allowed* property
  but never as a *required* one. That is what keeps the layer from being
  stricter than the binding.
- **Generic compatibles discarded**: `simple-bus`, `simple-mfd`, `syscon` and
  `arm,primecell` do not identify a device when the schema declares some other
  one. The first three are dtschema's own criterion; `arm,primecell` was added
  because 32 different bindings declare it (no other repeated compatible goes
  above six) and resolving by it led to validating a UART against a CoreSight
  schema.
- **Ties broken by identity, not alphabetically.** When several schemas
  declare the same compatible, the winner is, in this order: the binding that
  *is named* like the compatible (`panel-lvds` → `panel-lvds.yaml`, and not
  the first of the six concrete panels that declare it after their own), the
  one that declares it in first position of the list, and the one that
  describes it as its own node and not as a subnode. Without this, a generic
  LVDS display was validated against an Advantech panel's binding and
  inherited its exact dimensions (`width-mm = 223`) as mandatory values.

### Layer 5 of the semantic engine

`dts_engine/checks/bindings/` (see `SEMANTIC-ENGINE-FLOW.md`). The engine
does not know the database: it receives a `SchemaLookup` injected by
`api/service.py`. The rules:

| Code | Severity | What it says |
|------|----------|--------------|
| `binding-missing-property` | ERROR | the binding requires a property that is not there |
| `binding-missing-node` | ERROR | the binding requires a subnode that is not there |
| `binding-unknown-property` | WARNING / INFO | the binding —a closed one— does not allow that property |
| `binding-property-value` | WARNING | the value is not in the `enum`/`const` or is out of range |
| `binding-rejected-compatible` | WARNING | the compatible is in `incomplete-devices.yaml`, the kernel's list of rejected compatibles |
| `binding-unknown-compatible` | INFO | no YAML binding documents that compatible |

The same caution as layer 1: values with unresolved macros (layer 3) are not
judged, a `disabled` node does not have to meet its requirements —just as
`dt-validate` does— and whatever cannot be stated is downgraded in severity,
with the reason given in the diagnostic's hint. A reopening (`&gpio1 { … }`)
in a `.dtsi` is never said to be missing anything: only a piece of the node is
being seen.

The engine does not interpret values: **it hands them to the schema**.
`checks/bindings/instance.py` translates the node into the instance a JSON
Schema expects —a `uint32` is an integer, a `uint32-matrix` a list of lists,
`reg` is split into rows according to the parent's
`#address-cells`/`#size-cells`— and `jsonschema` validates it. Whatever cannot
be translated with certainty is left out and nobody talks about it:
`dt-bindings/*.h` macros, `&label` references (their cells are decided by the
node they point to) and matrices like `interrupts`, whose row size depends on
its controller's `#interrupt-cells`.

Only **value** problems are counted from the schema's result —`enum`,
`const`, `type`, `maxItems`, ranges— and one per property: `required` and
`additionalProperties` are already covered by the rules above, which know how
to look at the merged tree.

### Layer 2 of the semantic engine

`dts_engine/checks/generic/`, with the schemas dt-schema marks with `select`:
the ones applied by the node's shape and not by its compatible (228 of
5 663). That is where what applies to a *class* of device lives:

| Code | Severity | What it says |
|------|----------|--------------|
| `generic-missing-property` | ERROR | the class requires a property: `gpio-controller` requires `#gpio-cells`, `pinctrl-names` requires `pinctrl-0` |
| `generic-property-value` | WARNING | the value breaks the class: an I2C bus does not go above 5 MHz |
| `generic-vendor-prefix` | WARNING | a property's vendor prefix is not in the kernel's registry |

It runs **separately**, in the deferred pass (`run_schema_checks`), together
with the layer 5 values: both consist of handing the node to a JSON Schema
validator and both cost milliseconds per node, so the GUI launches them in a
background thread (`SchemaChecksWorker`) after each analysis and adds their
warnings as they arrive. If the two layers say the same thing about the same
property, the concrete binding's one is kept
(`KernelGroveService.merge_deferred`).

Measured on a board `.dts`: the analysis that runs on every keystroke takes
17 ms and the deferred pass 432 ms; on `zynqmp.dtsi`, with 330 nodes, 155 ms
and 2.4 s.

The prefix registry (`vendor-prefixes.yaml`) sits outside that loop: its 966
patterns took 86 % of the layer's time and the answer depends only on the
property name, so it is resolved with one regular expression and memoised.

### Autocompletion

The list pops up by itself when typing inside a node whose `compatible` is
known (and always with `Ctrl+Space`). Accepting a property inserts it with the
skeleton of its value according to its type, with the cursor inside:

```
clock-frequency   →   clock-frequency = <|>;
clock-names       →   clock-names = "|";
gpio-controller   →   gpio-controller;|
ports             →   ports {|};
```

And if the property has enumerated values, a second list with them appears
afterwards. Properties already written in the node are not offered, except
the one on the line being edited.

Which node it is gets worked out **from the text** (`api/completion.py`), not
from the tree: while typing, the last analysis lags behind. The walk is local
—backwards to the brace that opens the node— so it costs as much as the node
is long. If the node is a reopening (`&uart0 { … }`), the compatible is looked
up through the label in the merged tree.

The data side lives in `KernelGroveService`:

```python
svc.completion_context(text, position, base_path)  # node and compatible at the cursor
svc.suggest_properties("nxp,pcf8563")   # properties with type, whether required,
                                        # description, allowed values and origin
svc.suggest_compatibles("nxp,pcf85")    # documented compatibles by prefix
svc.is_documented_compatible("acme,x")  # does any binding describe it?
```

Descriptions come from the original YAML stored in `schemas.raw`; types, from
dt-schema's map (`uint32`, `string-array`, `phandle-array`…).

### Subdevices in the generator

An MFD like `ti,twl4030` describes in its own binding the functions it
carries inside (`ti,twl4030-pwm`, `-gpio`, `-keypad`, `-audio`: 20 in all).
They hang from no bus, so they did not show up through `parent_bus`. Now,
when a device with declared subnodes is connected, its slot offers a dropdown
with them (`PeripheralSlot.subdevice_parent`,
`KernelGroveService.list_subdevices`). It goes in a separate field and not in
`child_bus` on purpose: `child_bus` is a real bus name, and the visualizer's
colours and `CONTROLLER_LIST` depend on it.

## What dt-schema does NOT do (and why we still do it ourselves)

- **It does not infer buses.** There is no `i2c-peripheral-props.yaml`: I2C
  device bindings reference nothing that says they are I2C. Only SPI has a
  peripheral-properties schema (237 bindings reference it).
  `parent_bus`/`child_bus` still come from `storage.infer_parent_child_bus`
  and from each binding's examples.
- **It does not parse DTS.** Its input is a DTB unflattened with `pylibfdt`.
  The parser in `dts_engine/parser.py` is still the only text input.
- **It does not keep the documentation.** The fixups delete `description` and
  `examples`; that is why the raw YAML is stored too.
- **It does not validate the `role`** nor any other notion specific to
  KernelGrove.

## What is still pending

The eight pending items from the first integration are done. What is left is
of another scale, and none of the three depends on dt-schema:

1. **Layer 3: expanding the `dt-bindings/*.h` macros.** It is the ceiling for
   everything else. As long as an `interrupts = <GIC_SPI 42 IRQ_TYPE_LEVEL_HIGH>`
   does not resolve to numbers, its value is not encoded and therefore not
   validated —and those are most of the interesting values of a real device
   tree. The text of the 7 500 headers is already in the `sources` table:
   what is missing is the `#define` evaluator (including the arithmetic of
   macros with arguments).
2. **Resolving phandles.** How many cells each reference of a
   `clocks = <&clk 3>` takes is given by the `#clock-cells` of the node it
   points to, so it needs the merged tree with its labels resolved —which
   already exists— and a step that annotates each reference with its size.
   With that, `gpios`, `clocks`, `dmas`, `interrupts-extended` and everything
   else left out today come into validation.
3. **Integer width (`typeSize`).** dt-schema tells `uint32` from `uint64` by
   the actual size of the value in the binary. From the text every cell is 32
   bits and there is no way to know how many make up a 64-bit value, so that
   keyword is ignored. It would be solved together with the above.

And two minor things, noted so they are not lost:

- The skeleton autocompletion inserts comes from the property's type, and
  when dt-schema cannot pin it down (`wakeup-source` appears as `flag` in some
  bindings and as `phandle-array` in another) the most common form is offered,
  `= <>;`, which will sometimes need fixing by hand.
- The generator offers the subnodes the device's binding declares, but not
  those it declares *by pattern* (`^dsi@[0-9a-f]+$`): there are 91, and a
  decision would be needed on which node name to propose.

## What comes out over the whole kernel

`scripts/check_corpus.py` over the kernel's 6 347 `.dts`/`.dtsi` files, which
is the project's false-positive measurement. The two passes are measured
separately because the application also runs them separately.

**On every analysis** (`--db`): 17 915 diagnostics, 2.8 per file.

| Layer | Total | ERROR | WARNING | INFO |
|-------|-------|-------|---------|------|
| 1 (specification) | 9 161 | 391 | 4 690 | 4 080 |
| 5 (binding rules) | 8 754 | 562 | 3 049 | 5 143 |

Of layer 5, 4 930 are `binding-unknown-compatible` (INFO): the kernel keeps
around a thousand bindings in the old `.txt` format that never moved to YAML,
and nothing else can be checked for those nodes. That is what the warning
says.

Layer 1 has kept going down as the merged view of the tree improves: 10 986
before the integration, 10 079 after folding the `&label { … }` reopenings,
and 9 161 now that an `#include` written inside a node is merged inside that
node. Its errors have stayed at 391 all along.

**In the deferred pass** (`--db --schema`): 1 167 diagnostics, 0.18 per file.
It is the most precise part of the engine, and also the one that took the
most tuning: the first version produced 934 value warnings in 400 files,
almost all of them from our own encoding mistakes (see below).

| Code | Total | ERROR | WARNING |
|------|-------|-------|---------|
| `binding-property-value` | 509 | | 509 |
| `generic-missing-property` | 624 | 216 | 408 |
| `generic-property-value` | 30 | | 30 |
| `generic-vendor-prefix` | 4 | | 4 |

**The kernel corpus is not absolute truth for these layers**, unlike layer 1.
The kernel does not validate cleanly against its own bindings —
`make dtbs_check` produces thousands of warnings — so every group has to be
looked at by hand. Among the verified ones: `arm,pl080` in `spear3xx.dtsi`
has neither `#dma-cells` nor `clocks`, `ti,tfp410` in `dove-sbc-a510.dts`
lacks the `ports` node, `st,stmpe-ts` on the SPEAr boards uses the old `ts,`
prefix instead of `st,`, and the `qcom,ci-hdrc` in `qcom-msm8960.dtsi`
declares `clock-names` in the opposite order to the one its binding fixes. All
four are real violations that `dt_binding_check` reports too.

**What measuring taught.** Four bugs of our own only came out when running
the corpus, and none would have been seen testing by hand:

- Without `compatible` in the instance, every `if/then` in the schemas was
  satisfied: in JSON Schema, a `properties` over something that is not there
  counts as valid. A `qcom,geni-i2c` ended up requiring another variant's
  `clock-names`. 934 → 48 value warnings in 400 files.
- `reg` cells were taken from the *written* parent, which in a
  `&usb_dwc3_0 { … }` reopening is the root, not the bus the node actually
  lives on.
- 64-bit values are written as two 32-bit cells and the schema expects them
  as a single number.
- Validating a subnode with its loose piece of schema broke its local `$ref`s
  (`#/$defs/…`), which point into the whole document. That one crashed the
  analysis with an exception rather than producing a false positive.

## Checking the integration

```bash
pip install -e '.[ingest]'            # dtschema, only to build the database
scripts/build_database.sh             # includes the «schemas» step
python -m pytest tests
python scripts/check_corpus.py --db            # what runs on every analysis
python scripts/check_corpus.py --db --schema   # the deferred pass
```

The engine tests use a fake `SchemaLookup`, so they do not need the database;
the `api` ones (`test_binding_schemas.py`) do, and skip themselves when it is
not there.
