# Semantic engine check flow

This document fixes **in what order** KernelGrove validates a device tree and
**where each rule comes from**. The goal is not to invent rules of our own:
every warning the editor shows has to be traceable to an external source (the
specification, a binding, a header or the kernel code).

The previous engine mixed levels: it queried the bindings database before it
had even checked whether the file followed the language's syntax. Its rules
have each been reimplemented in their own layer (see [«What is left of the old
engine»](#what-is-left-of-the-old-engine)) and the module that held them,
`dts_engine/semantic_old.py`, no longer exists.

## The order, and why it is that one

```
     .dts/.dtsi text
            |
            v
   [0] parser (syntax)            braces, «;», node headers
            |
            v
   [1] DT specification           language rules, they ALWAYS apply        <-- implemented
            |
            v
   [2] Generic bindings           device classes and common buses          <-- implemented
            |
            v
   [3] dt-bindings/*.h            constants: what the numbers mean         <-- partial (existence and value)
            |
            v
   [4] Kernel drivers             what the code actually requires
            |
            v
   [5] Specific bindings          the binding of the concrete «compatible» <-- partial
```

Layers 1, 5 and the cheap part of 2 run on every analysis; what the schema
itself validates (the values of layer 5 and all of layer 2) goes in a second
pass, `run_schema_checks`, which the GUI runs in a background thread. It is
the difference between microseconds per node and milliseconds.

The golden rule is that **a layer never contradicts the previous one**, and
that a layer only speaks about what its source states. If a check needs
something that has not been resolved yet (an unexpanded macro, an unmerged
include), it stays quiet instead of inventing an error.

The order goes from the universal to the particular:

| Layer | Source of truth | Scope | Status |
|-------|-----------------|-------|--------|
| 1 | Devicetree Specification v0.4 | Every device tree, no exceptions | **Implemented** |
| 2 | Generic bindings (the dt-schema schemas with `select`: chapter 4 of the specification and the kernel's common bindings) | Device classes and buses | **Implemented** |
| 3 | `dt-bindings/*.h` headers | Property values | **Partial** (existence, and value if `cpp` was available at ingestion) |
| 4 | Kernel drivers (`drivers/**`) | What the code actually reads | Pending |
| 5 | The `compatible`'s binding, processed by dt-schema (`Documentation/devicetree/bindings/**`) | One concrete device | **Partial** |

### Layer 1 — Device Tree specification *(implemented)*

Source: <https://github.com/devicetree-org/devicetree-specification>
(Devicetree Specification v0.4, chapters 2, 3 and 6).

It is the only layer that can state something about *any* device tree,
whether it comes from the kernel, from a vendor or from the editor itself. It
checks names, value types of the standard properties, addressing and document
structure. It is detailed further down.

### Layer 2 — Generic bindings *(implemented)*

Code: `src/kernelgrove/dts_engine/checks/generic/`.

Chapter 4 of the specification itself already defines generic bindings
(serial class, network class, `simple-bus`, Open PIC controllers), and the
kernel adds its own: `i2c-controller.yaml`, `gpio.yaml`, `pinctrl.yaml`,
`regulator.yaml`, `property-units.yaml`…

**Which ones, exactly**: the ones dt-schema marks with `select`. A normal
binding is looked up by its `compatible`; a generic one is tried against
*every* node and its `select` decides whether it applies. In the kernel there
are 228 of them out of 5 663, and they hold what applies to a *class*: that a
GPIO controller declares `#gpio-cells`, that an I2C bus does not go above
5 MHz, that a property ending in `-microvolt` is an integer, or that
`pinctrl-names` comes with its `pinctrl-0`.

The vendor-prefix registry (`vendor-prefixes.yaml`) is checked here as well:
a `doesnotexist,property` is usually a typo. It sits outside the loop because
its 966 patterns took 86 % of the layer's time, and the answer depends only on
the name, so it is resolved with one regular expression and memoised.

**It runs in the deferred pass.** `run_schema_checks` gathers everything that
consists of handing a whole node to a JSON Schema validator —this entire layer
(≈10 ms per node) and the values of layer 5 (≈2.6 ms)— because neither fits in
every keystroke. The GUI launches it in a background thread after each
analysis and adds its warnings as they arrive (`SchemaChecksWorker`). When the
two layers say the same thing about the same property —the Cadence binding
caps `clock-frequency` at 400 kHz and the I2C class at 5 MHz— the first one is
kept, which is the concrete binding's (`KernelGroveService.merge_deferred`).

| Code | Severity | What it checks |
|------|----------|----------------|
| `generic-missing-property` | ERROR | the class requires a property that is not there (dependencies included: `gpio-controller` requires `#gpio-cells`) |
| `generic-property-value` | WARNING | the value breaks what the class declares |
| `generic-vendor-prefix` | WARNING | a property's vendor prefix is not registered |

What does **not** come back here is the old engine's bus check
(`_check_placement`): dt-schema does not say which bus a device hangs from
(there is no `i2c-peripheral-props.yaml`), so that still comes from the
ingestion's own inference.

### Layer 3 — `dt-bindings/*.h` headers *(partial: existence and value)*

Code: `dts_engine/checks/macros.py`. Ingestion: `db_manager/macros.py`
(`--table macros`, names derived from `sources`, values from `cpp` against the
checkout).

Values in real device trees are not numbers but macros (`GIC_SPI`,
`IRQ_TYPE_LEVEL_HIGH`, `RK3399_CLK_...`), and this layer has two levels:

**Existence**, always available: if `GPIO_HIGH` appears in a value, is that
macro defined anywhere? The ingestion indexes every `dt-bindings/*.h` header
with one `#\s*define NAME` per line (`header_macros` table, no preprocessor),
including the transitive closure of whatever that header includes in turn (the
graph is tiny, 24 edges in the whole tree). At analysis time, `api/service.py`
works out which macros the document sees through its own cascading `#include`s
(`IncludeResolver.macro_names`) and hands it to the engine as `local_macros`,
just like `merged_root` for include merging — the engine does not touch the
database.

Two severities, depending on the strength of the evidence:

| Code | Severity | What it checks |
|------|----------|----------------|
| `macro-missing-include` | WARNING | the name exists in some known `dt-bindings/*.h` header, but not among the ones this document includes — probably a missing `#include` |
| `macro-unknown` | INFO | the name does not exist in any known `dt-bindings/*.h` header (it could be a driver-local macro, outside `dt-bindings/`) |

It is a cheap check (dictionary lookups, no `jsonschema`), so it runs in
`run_checks`, not in the deferred pass.

**Value**, only if the database was built with `cpp` available: the ingestion
asks `cpp` to expand every macro in the real context of its header —a single
invocation per header, with all its names behind a marker that survives `cpp`
reordering lines— and whatever is left, if it is an expression of only numbers
and operators, is evaluated with a minimal, restricted interpreter
(`db_manager/macros.evaluate_c_int_expr`). A function-like macro with no
arguments (`GIC_CPU_MASK_RAW`) does not expand without parentheses and is left
without a value, although it stays in the existence index. `cpp` runs **only
at ingestion**, against the kernel checkout — never at analysis time and never
on user text, the same discipline as the rest of the database.

The resolved value is used in `checks/bindings/instance.py`: a cell that is
not a numeric literal is looked up in `ctx.local_macro_values`
(`IncludeResolver.macro_values`, same cascade as `macro_names` but only
computed in the deferred pass, the only one that needs values) before it is
given up as uncodable. With this, properties like
`hisilicon,fixed-mode = <SOME_MACRO>;` get validated against their binding's
`enum` instead of staying invisible — but **not** everything carrying a macro
benefits: `interrupts` is still not encoded even when its type cell resolves,
because its matrix shape depends on the controller's `#interrupt-cells`
(layer 4), a different limitation that predates this one.

### Layer 4 — Kernel drivers *(pending)*

A binding describes what *should* be; the driver is what actually gets read.
`of_property_read_*`, `of_device_id`, the `of_match_table`s… make it possible
to detect properties the binding does not document, default values, and
compatibles that exist in the code but not in `Documentation/`.

It is the most expensive layer (it means analysing C) and the last one to
contribute hard rules: it serves mostly to explain *why* something is needed.

### Layer 5 — Specific bindings *(partial)*

Code: `src/kernelgrove/dts_engine/checks/bindings/`. Details of the dt-schema
integration in [`DT-SCHEMA-INTEGRATION.md`](DT-SCHEMA-INTEGRATION.md).

The binding of the concrete `compatible`: its `required`, its allowed
properties, its values and its mandatory child nodes. It is the most precise
and the most fragile, and that is why it goes last: it only applies to a node
whose compatible has been resolved **exactly**, including the node inside the
schema it corresponds to (a `ti,twl4030-pwm` is validated against the MFD's
subnode, not against the MFD).

The source is not the raw YAML but the schema already processed by dt-schema
during ingestion, with the `allOf`/`$ref` inheritance resolved: without it,
1 988 `required` entries in the kernel —`reg` in 221 bindings among them—
would be invisible.

| Code | Severity | What it checks |
|------|----------|----------------|
| `binding-missing-property` | ERROR | a property the binding requires is missing |
| `binding-missing-node` | ERROR | a subnode the binding requires is missing |
| `binding-unknown-property` | WARNING / INFO | the binding, being closed (`additionalProperties: false`), does not allow that property |
| `binding-property-value` | WARNING | the value is not in the `enum`/`const` or falls outside `minimum`/`maximum` |
| `binding-rejected-compatible` | WARNING | the compatible is listed in `incomplete-devices.yaml` |
| `binding-unknown-compatible` | INFO | no YAML binding documents it, so nothing else can be checked |
| `binding-newer-than-kernel` | WARNING | the binding is documented in a release later than the target kernel |

`binding-newer-than-kernel` is the only rule that needs a piece of data found
in no device tree: which kernel you are working against. The user supplies it
from the status bar (`KernelGroveService.kernel_target`) and without it the
rule stays quiet. It compares against `schemas.since`, the first release whose
tree ships the binding file, and that is why it talks about when something was
**documented**: a compatible may have existed earlier in a `.txt` binding
under another name.

Values are checked by handing the whole node to the binding's schema, as
`dt-validate` does, and **in the deferred pass** together with layer 2:
`checks/bindings/instance.py` translates each property into the shape the
schema expects (a `uint32` is an integer, a `uint32-matrix` a list of lists)
and `jsonschema` does the rest. **Whatever cannot be translated with
certainty is left out** and nobody talks about it: values with
`dt-bindings/*.h` macros (layer 3), `&label` references —how many cells each
one takes is decided by the node it points to— and matrices whose row size
depends on another node, such as `interrupts` and its `#interrupt-cells`. The
exception is `reg`, whose rows come from the parent's
`#address-cells`/`#size-cells`.

Only **value** problems are counted from the schema's result: `required` and
`additionalProperties` are covered by our own rules, which know how to look at
the merged tree and downgrade the warning when it is not conclusive. The
schema's conditional branches (`if/then`, `oneOf`) are walked only to learn
which properties *may* be valid, never to require anything.

## Layer 1 in detail

Code: `src/kernelgrove/dts_engine/checks/spec/`, one module per block of the
specification.

| Module | Sections | What it checks |
|--------|----------|----------------|
| `naming.py` | §2.2.1, §2.2.3.1, §6.2, §6.3 | node-name and unit-address (character set, length, starting with a letter), property names, labels, node/property clashes, properties before child nodes |
| `properties.py` | §2.3, §2.4, §3.2 | value type of the standard properties (`<empty>`, `<u32>`, `<string>`, `<stringlist>`), allowed values of `status` and `chassis-type`, `compatible` format, deprecated properties, interrupt rules |
| `addressing.py` | §2.2.1, §2.3.5, §2.3.6 | `reg` against `unit-address`, number of `reg` cells, `#address-cells`/`#size-cells` on nodes with addressed children |
| `structure.py` | §3.1-§3.8, §6.4 | mandatory properties of the root, `/cpus` and `/memory`, `/aliases` names, `cpu` nodes, `/dts-v1/;` |

`values.py` and `context.py` no longer live in `spec/` but one level up, in
`checks/`, because every layer shares them:

| Module | What it provides |
|--------|------------------|
| `checks/values.py` | reading a DTS value (strings, cells, bytestrings, references) and detecting what cannot be resolved yet (§6.3) |
| `checks/context.py` | shared state: own and merged tree, the line of each property, resolution of `&label { … }` reopenings, and the policy for when something can be said to be missing |

### From the specification to the severity

| The specification says | Severity | Example |
|------------------------|----------|---------|
| «shall» / «must» | ERROR | `status = "enabled"` is not an allowed value (§2.3.4) |
| «should» / «recommended» | WARNING | a `compatible` with capitals or underscores (§2.3.1) |
| deprecated | WARNING / INFO | `name` (§2.3.11), `device_type` outside cpu and memory (§2.3.12) |
| a limit nobody enforces | INFO | the 31 characters of names and labels: it is the rule, but neither dtc nor the kernel follow it |

### When the engine can say something is «missing»

Stating an absence requires seeing the whole tree, and the file being edited
hardly ever contains it: a board inherits `/cpus`, `/memory` and half a dozen
mandatory properties from the `.dtsi` it includes.

**The first thing is to look at the right tree.** Before checking anything,
`KernelGroveService.analyze_source` merges a copy of the tree with the content
of its includes —the same thing the visualizer does, resolving them against
the database's `sources` table— and hands it to the checks as `merged_root`.
Whether a node or a property is present is asked there
(`SpecContext.effective_properties` / `effective_children`); **the warning's
line always comes from the document's tree**, the only one whose lines match
the text the user has in front of them.

With that, there are two kinds of requirement:

- **Of the whole document** (`model` and `compatible` at the root, `/cpus`,
  `/memory`, `/dts-v1/;`): they only mean something in a complete device tree
  seen in full, so they are not checked in a `.dtsi` nor in a file whose
  includes could not be merged (`SpecContext.is_complete_document`).
- **Of a concrete node** (a `cpu` without `reg`, a `memory` without
  `device_type`, an interrupt controller without `#interrupt-cells`): the node
  is written in this file, so the check always applies.

When the check applies but cannot be conclusive —the document is a fragment,
some include was not found, or the node is only reopened here with
`&label { … }`— the diagnostic **is downgraded one step** (error → warning,
warning → info) and the reason is explained in the hint, instead of staying
quiet. `SpecContext.report(..., missing=True)` decides that, in a single
place.

The previous version of this layer silenced the checks as soon as the
document had an `#include`, which is the normal case: deleting `model` from
the root or `reg` from a `cpu` produced nothing. The honest rule is not to go
quiet, it is to look at the complete tree and, if that is not possible, say so
with a lower severity.

### What layer 1 deliberately does NOT check

- **Nothing that depends on an unexpanded macro.** That is layer 3.
- **Nothing bus-specific.** Whether a PCI device's unit-address is `dev,fn` or
  whether an SPI chip select is below `#cs-lines` is defined by the bus
  binding (layer 2). That is why `_parse_unit_address` only compares
  unit-addresses that are pure hexadecimal.
- **Nothing device-specific.** Which properties an `atmel,24c02` needs is
  layer 5.
- **Reference consistency.** Resolving `&label` against the tree and
  following `interrupt-parent` requires merging includes first; today the
  parser leaves `&label { … }` reopenings as loose pseudo-nodes.
- **Nothing based on indentation**: DTS has no indentation rules (see
  `CLAUDE.md`).

### Verification against the kernel

Every new rule is checked against the 6347 `.dts`/`.dtsi` files in the
checkout (`kernel/linux/arch/**`), which are taken as correct: if a rule fires
massively, either the rule is badly framed or it has to be downgraded.

The measurement that counts is the one along the path the application uses
(`--db`, with includes merged); without a database nothing resolves and the
figures are only good for comparing with each other.

Current status with `--db`: **10 986 diagnostics in 6347 files** (1.7 per
file), and **3464 files with no diagnostic at all**. By severity: 397 ERROR,
4940 WARNING and 5649 INFO. The ERRORs appear in 156 files and have been
reviewed group by group:

| No. | Diagnostic | Verified |
|-----|------------|----------|
| 231 | alias with `_`, capitals or commas (§3.3) | 27 files, mostly powerpc and layerscape |
| 90 | `/cpus` missing (§3.1) | old ARM and MIPS boards that declare no CPUs in any of their files |
| 35 | the root does not declare `model`/`compatible` (§3.2) | e.g. `mips/…/octeon_3xxx.dts`, which has neither |
| 17 | `memory` node without `device_type` (§3.4) | real |
| 16 | `interrupt-map` without `#interrupt-cells`/`#address-cells` (§2.4.3) | 6 powerpc files |
| 4 | malformed alias, `/cpus` without cells, node repeating a property's name | real |

The most frequent warnings —unit-address not matching `reg`, unit-address
without `reg`, compatibles with capitals or underscores— are real deviations
too, the same ones `dtc` reports.

It is measured with:

```sh
python scripts/check_corpus.py --db                # like the application
python scripts/check_corpus.py --db --limit 400    # quick sample
python scripts/check_corpus.py --code spec-reg-mismatch --examples 20
python scripts/check_corpus.py --syntax            # parser diagnostics
```

The false alarms it already took effort to remove once, and which need
watching when touching rules:

- names and labels generated by C macros (`DIE_NODE(pmgr)`,
  `EFUSE(10, 27)`);
- the `\` continuation backslash inside a value;
- `stdout-path = &uart0`: a reference where a path is expected (§6.3);
- `/dts-v1/;` written in a `.dtsi` the board includes —the marker counts
  wherever it is, because `dtc` sees the text of every file pasted together,
  so it is searched for inside the includes too
  (`IncludeResolver.text_in_includes`);
- `&label { … }` reopenings, which the parser hangs from the root and which
  are not children declared in the node's body;
- a file that reopens one of its own nodes (`soc { … }; soc { … };`): the
  parser merges both occurrences into a single node, as `dtc` does. When it
  created two identical siblings, include merging only reached one of them
  and the other appeared not to declare `#address-cells`.

## What is left of the old engine

`dts_engine/semantic_old.py` has been deleted. It was kept while layers 2 and
5 were being rebuilt, as a reference of what had to be recovered; today every
rule lives in its layer and nothing instantiated the module:

| Old rule | Where it is today |
|----------|-------------------|
| `_check_placement` (node hanging from the wrong bus) | It does not come back as it was: dt-schema does not say which bus a device hangs from, so that still comes from the ingestion's inference (see layer 2) |
| `_check_required` (mandatory properties and child nodes) | Layer 5, `checks/bindings/rules.py` (`binding-missing-property`, `binding-missing-node`) |
| Unknown `compatible` warning | Layer 5, `binding-unknown-compatible` |
| `BindingSpec` / `BindingLookup` (contract with the database) | `checks/bindings/lookup.py`, which talks about schemas already processed by dt-schema instead of the raw YAML |
| `parser.py`'s `check_compatible_format` | Layer 1 (§2.3.1) |

Of that reimplementation, the two things that had to be kept no matter what
are still standing: **exact** resolution of the compatible, and treating
`.dtsi` files as fragments.
