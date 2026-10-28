---
name: yasdl-circuit-design
description: |
  Design electronic circuits with yasdl (ASCII-canvas schematic language, installed at $YASDL_PATH) so the
  result is both functional (SPICE netlist, simulated in ngspice) and a clean, planar,
  ERC-passing KiCad 9 schematic. Use it whenever a task asks to design, build, draw or fix a
  circuit or SPICE (sub)circuit: analog stages, oscillators, filters, amplifiers, regulators,
  transistor/op-amp/diode networks, "make a .lib / .subckt / netlist", "draw a schematic",
  "KiCad schematic", or an EE design task with ngspice (e.g. "create a subcircuit named X
  with pins ..."). Start in yasdl instead of hand-writing a netlist.
---

# Designing circuits with yasdl

yasdl turns ASCII drawings of rectangular blocks into a flat netlist, a SPICE `.subckt` and a
laid-out KiCad schematic, all from one object. The drawing is the circuit, so a readable sketch
gives a readable schematic.

## Think hierarchically: small blocks, yasdl composes

**Never draw a large circuit as one canvas.** Decompose it into functional stages, draw each
stage as its own small block (roughly ≤ 40 x 20 characters, a handful of parts), and compose
them in a tiny top-level block where each stage is just a short name:

```
{vp}───┬────────────┐
       │            │
       OSC──────────AMP──{out}        top level: two components and the supply rail
                    │
                   {vm}
```

- You only ever reason about one small canvas at a time: its parts, its wires, its ports.
  Test each block with `netlist()`, `spice_netlist()` and `render()` when it contains
  every unit of each package it uses. Test a partial-package block inside its complete
  containing design.
- yasdl does the composition. It lays out every level (grid-bag, wires stretch, symbols
  never do) and nests the sub-drawings. **Composition adds no crossings**: blocks are
  rectangles meeting only through ports, so the result has exactly the crossings you drew
  (none, for most circuits; a few topologies such as parallel transistor arrays need some).
- Blocks are reusable. A sub-block fits any component drawn with the same number of wires per
  side; yasdl turns it to fit (see Orientation).
- **The interface is the design decision.** Put each port on the side where its neighbour
  will be: supplies on **N** (so one rail can run across the top), inputs **W**, outputs
  **E**, negative supply or ground returns on **S**. Mismatched port sides still work (yasdl
  adds jogs) but look worse. Example: an oscillator with its `vp` on the left forced a loop
  over the whole drawing; moving `{vp}` to its top edge gave one clean rail.
- Typical stages: bias network, gain stage, feedback or filter network (RC ladder, Sallen-Key
  section), buffer or output stage, supply decoupling. Split where a single wire (or a
  coupling capacitor) joins two stages; that node becomes the port.

`$YASDL_PATH/docs/examples/sgen.py` is the reference: PHASE_SHIFT (RC ladder) inside
OSCILLATOR (gain stage), then OUTPUT_AMP (from the coupling capacitor on), composed by SGEN.
More examples in `$YASDL_PATH/docs/examples/blocks.py`. The full spec is
`$YASDL_PATH/docs/SPEC.md` (overview: `$YASDL_PATH/README.md`); read the parts you need.

## Setup

```bash
export PYTHONPATH=$YASDL_PATH:$PYTHONPATH    # stdlib-only package, no install needed
# Prefix install: ~/KiCad9. macOS also accepts the directory containing KiCad.app.
export YASDL_KICAD=/Applications/KiCad         # omit when KiCad is at ~/KiCad9
python -c "import yasdl"                      # ngspice on PATH
```

If yasdl isn't reachable (for example inside a task container), copy the `yasdl/` package
directory next to your script (Python stdlib only). Standard components use KiCad symbol-library
data; rendering also uses the KiCad CLI. Whatever the task asks for (e.g. `/app/x.lib`) stays the deliverable. Generate it with
`spice_netlist()` and keep the yasdl source next to it.

## Workflow

1. **Spec**: list ports (name, order), supplies, ground, loads, targets (gain, frequency, Zout,
   power), and allowed parts and models.
2. **Topology and hierarchy**: pick a known architecture and split it into stages. Write down
   each block's interface first: port names and the side each goes on (N supplies, W in,
   E out, S returns). The top block is just the stages wired port to port.
3. **Sketch each block bottom-up** (rules below), smallest first. Check each one alone
   (`netlist`, `spice_netlist`, `render`) before using it in a parent; package-unit blocks
   are checked in a parent containing the complete package. Use `Sketch` for anything
   wider than about 30 columns.
4. **Bind** atoms and sub-blocks. Let yasdl orient them; add pin labels where pin order
   matters (rules below).
5. **Check structure**: `netlist(block)` and `print(spice_netlist(block, subckt=...))`. Read it
   against your design: every node, every part.
6. **Simulate** in ngspice with a testbench (supplies, load, `.tran`/`.ac`/`.op`). Iterate on
   values in the bindings; the drawing rarely changes. **NGSPICE EXIT CODE 0 DOES NOT
   GUARANTEE SUCCESSFUL ANALYSES OR MEASUREMENTS**: read the log (`DC solution failed`,
   `timestep too small`, a `.meas` that reports `failed` or is missing) and check every
   measured value before you claim a result. With a reactive load (speaker model), measure
   power in the resistive part, not `V²/R` at the terminals.
7. **Render and verify**:
   `render(block, "out", spice_libs=(models,), spice=True)`. It must report:
   - `roundtrip_ok`: KiCad's netlist equals yasdl's;
   - `erc == []`: KiCad ERC clean, errors and warnings;
   - `spice_ok`: KiCad's SPICE export equals yasdl's.

   The exporter selects the smallest fitting landscape ISO page and keeps port labels inside
   the cropped SVG. Inspect the SVG in a browser or the schematic in KiCad. If your viewer
   requires PNG, use an optional SVG-to-PNG converter. Fix ugliness in the canvas.
8. **Deliver**: the SPICE file the task asks for, plus `.kicad_sch`, `.svg` and the yasdl
   source. Include `.png` when requested or needed by the image viewer.

## Canvas rules (cheat sheet)

| Thing | Syntax | Notes |
|---|---|---|
| empty | space | `.` is reserved (an error) |
| component | rectangle of one repeated word: `R1`, `Q1Q1` x 3 rows | name = minimal period: `U1U1` → `U1`, but **`CC` → `C`, `RR` → `R`**, so avoid names that are one repeated letter |
| wire | `─ │ ┌ ┐ └ ┘` | ASCII `-` and `\|` also work |
| junction | `├ ┤ ┬ ┴ ┼` | `┼` is always a junction (dot) |
| crossing | straight wire with perpendicular wires on both sides: `─│─` | the middle character is the wire on top; no connection |
| port | `{name}` on the canvas edge, wire going inward | aliases: `{c, collector}`, `{>, A, Anode}`; names are letters/digits/_ or `+ < > ^ v`; or a bare wire leaving the canvas (`W0`, ...) |
| pin label | `{b}Q1Q1`: label touching a component edge | names the pin; orients the part, or checks an explicit orientation |
| pin shortcut | `+` touching a component | e.g. op-amp non-inverting input |
| arrow pin label | `>D1` (beside), `v` above/below | conventional current; rotates with the part and picks its orientation: `──>D1──` anode left; NPN base `>`, emitter `v`. One arrow per pin; `<`/`>` only beside, `^`/`v` only above/below |
| global net | `[Signal]`, `[VCC]` | uppercase initial connects across blocks; registered powers such as `+5V` are exceptions and draw as power symbols; `GND` = SPICE node 0. Reserved powers require exact spelling and cannot be port aliases |
| local net | `[signal]`, `[_bias]` | lowercase or `_` initial; scope stays inside the block even with only one wire |
| no-connect | a component bound to `NC()`, e.g. `──X1` | each wire into it ends in a KiCad no-connect marker; any number of wires (`X2X2` under two pins); each must reach exactly one device pin |

Hard rules, all enforced with precise errors:
- **Gap rule**: components never touch. Keep at least one cell, empty or wire, between them.
- Wires must meet: a wire pointing at an empty cell is dangling. A wire ending on a straight
  wire needs a tee.
- A component's pin count per side must match the bound part exactly. An op-amp with supply
  pins needs wires on its top and bottom, e.g. to `[VCC]`/`[VEE]`.
- Pins on a side map in order: W/E top to bottom, N/S left to right.
- A brace touching one component names its pin; otherwise it declares an interface on the
  canvas edge. A pin label needs one wire opposite the component and must not touch two
  components. Vertically, any character of the brace may touch the part and any column may
  carry the wire. Square brackets name nets and need a wire between the label and component.
- Net names cannot start with digits. The name determines scope regardless of the number of
  wires; different nets still cannot differ only in case because SPICE ignores case.
- Prefer lowercase pin/interface names as a convention. Uppercase names still match;
  numeric pins/interfaces need braces (`{1}`). Bare letters and digits remain component
  names, so `─1U1─` names component `1U1` rather than pin 1 of U1.

## Orientation: let yasdl do it, label pins where order matters

yasdl rotates and mirrors every atom and sub-block to fit the wires drawn around it. **Don't
orient parts by hand.** Draw the wires where you want the pins and say which pin is which with
labels; the labels choose the orientation.

- **Pin order doesn't matter** (resistors, capacitors, inductors, symmetric networks): no
  labels. `──R1──` and a vertical `R1` just work.
- **2-terminal directional parts** (diodes, polarised caps, directional sub-blocks): one label
  is enough. `──>D1──` puts the anode left; `+` marks a polarised cap's positive pin.
- **3+ pin parts** (transistors, op-amps, sub-blocks with several ports): label **two pins on
  different sides** whenever one label leaves a choice. For example, `{b}` alone on an NPN still
  allows a top/bottom mirror that swaps collector and emitter; `{b}` plus `v` under the
  emitter fixes it. Arrows: NPN base `>`, emitter `v`; PNP base `<`, emitter `^`.
- The op-amp (`Simulation_SPICE:OPAMP`) has + above −, output right, **V+ on top, V− at the
  bottom**. A `+` on its lower input flips it so − is on top, as in inverting stages, **and
  the flip moves the supply pins too**: `[VCC]` drawn above then reaches V−. Either wrap it,
  `std.powered(opamp)` (a three-port block with V+ on `[VCC]` and V− on `[VEE]` inside; any
  rotation carries the supplies along; fits every op-amp hole), or label `{V+}` above and
  `{V-}` below so a wrong flip fails at binding.
- Give directional sub-block inputs an arrow alias (`{in, >}`); `PS<` puts that input on
  the right. Named ports also accept brace labels: `PS{in}` names the `in` port on that
  side.
- If two orientations still fit, yasdl picks one deterministically: reading order, then the
  fewest axis flips, then orientation order. That's fine when the choice doesn't matter electrically; when it
  does, add a label. Explicit `.rotated()`/`.mirrored()` exist as a last resort.

## Making it look good

- **Signal flows left to right**: input port W, output port E.
- **Supplies at the top, ground at the bottom**: a `{vp}` rail across the top row, or
  `[VCC]`/`[VEE]`; `[GND]` labels under each grounded leg instead of wiring to one ground.
- **One stage per sub-block** (see "Think hierarchically"). Repeated or self-contained
  networks (RC ladders, dividers, bias networks, filters) become sub-blocks and are reused.
  The top level stays a few lines long.
- **Feedback** runs above (or below) the stage it wraps, in its own row. Long returns hug the
  canvas edge (column 3 in `sgen.py`).
- **Align**: the parts of one chain share a row; a component's vertical legs share its
  column. The layout stretches wires, never symbols. Rows and columns cost nothing.
- **Avoid crossings.** Prefer re-routing or a global net label. Crossings are legal, though.
- **Name ports** with `{}` labels and put them where they belong physically (power on N).
  `spice_netlist` orders subcircuit pins in DIP order (W top→bottom, S, E bottom→top, N), which
  rarely matches a task's required order once power is on top. Pass the task's order:
  `spice_netlist(top, subckt="x", port_order=["vp", "vm", "out"])`. Don't move ports to fix
  pin order.
- An external `{VP}` port may feed an internal `[VCC]` power rail. Subcircuit export
  preserves the formal `VP` name; flat KiCad/SPICE export keeps `VCC`. Aliases on the same
  electrical net are rendered as annotations instead of conflicting KiCad net labels.
- Crossings directly beside a component or label are supported. Keep the intended straight
  wire glyph and do not replace it with a junction to make an export pass.
- Keep inter-stage signals on drawn wires and explicit block ports. Use power globals freely;
  reserve global signal labels for a small number of genuinely shared signals.
- Leave a blank row or column where wide parts (sub-blocks, labels) need room. The layout
  separates overlapping shapes, but tight canvases look cramped.

## API

```python
from yasdl import (Block, Sketch, R, C, L, D, NPN, PNP, OPAMP, OPAMP_IDEAL, V, I, GND, VCC, VEE, C_POL,
                   POT, NC, Atom, netlist, spice_netlist, register_power_net, SpiceModel)
from yasdl import std                                   # standard reusable blocks
from yasdl.parts import Q2N3904, Q2N3906, BD139, BD140, D1N4148, AtomNPN, Package, dual_opamp
from yasdl.kicad_export import render
from yasdl.kicad_lib import JELLYBEAN_MODEL             # 2N3904, 2N3906, 1N4148 models

STAGE = Block("Stage", canvas_text, R1=R("10k"), Q1=NPN("2N3904"), SUB=OTHER)
STAGE.unbound                     # components without a binding = open interface
TOP = TEMPLATE.bind(IN=R("1k"))   # bind later
STAGE.ports                       # Port(side, index, name, dip, aliases)
STAGE.port("vp")                  # lookup by alias, "W0" or "D2"
netlist(STAGE)                    # {net: ["path.pin", ...]}
spice_netlist(STAGE, subckt="name", port_order=["vp", "vm", "out"], includes=("models.lib",))
render(STAGE, "out", spice_libs=("models.lib",), spice=True)  # .kicad_sch + .svg + checks
render(STAGE, "out", references="names", values=False)  # refs = yasdl names, values hidden
render(HALF.bind(Q1=NPN("2N3904")), "out", export_name="HalfN")  # file stem != block name
STAGE.to_dict()                   # JSON view for debugging
Block(..., port_attrs={"W0": {"aliases": ["input"]}})
```

- Atom values are SPICE values (`"4.7k"`, `"100n"`). **USE MEG FOR MEGA; USE lowercase m FOR
  MILLI**: `R("1Meg")`, never `R("1M")` (KiCad reads mega, ngspice milli); write `4.7k`, not
  `4k7`. Direct SPICE generation rejects ambiguous passive values; rendering reports the actual export mismatch. Transistors and
  diodes take the model name as their value (`NPN("2N3904")`, `D("1N4148")`). Models come
  from `includes`/`spice_libs`.
- **Real parts**: prefer the verified descriptors in `yasdl.parts` (`Q2N3904`, `Q2N3906`,
  `BD139`, `BD140`, `D1N4148`): generic KiCad shapes with the datasheet pin numbers, footprint
  and model library, so the schematic has correct physical pins. New parts:
  `AtomNPN("BC547", pins={"C": 1, "B": 2, "E": 3}, library=...)`, `AtomPNP`, `AtomDiode`,
  `AtomOpamp5(name, pins={"+":3,"-":2,"out":6,"V+":7,"V-":4}, model=, library=, model_pins=)`.
  Check the pin map against the datasheet yourself; neither yasdl nor SPICE can.
- **Dual op-amps** are one package: `chip = Package(dual_opamp("TL072", "TL072", lib), "U1")`;
  bind `chip.unit("A")` and `chip.unit("B")` into op-amp holes (any blocks) and
  `chip.power()` (V+ top, V− bottom, between `[VCC]` and `[VEE]`) once. Every unit must be
  placed; tie an unused amplifier as a grounded follower.
- **Unused pins**: draw a wire to a component bound to `NC()` (`──X1`). Never leave a pin
  undrawn (binding fails) and never NC a net with two pins (error).
- **Non-simulated parts** (jacks, speaker terminals, connectors): `Atom(lib_id, value,
  sim=False)`; they stay in the schematic and BOM and leave SPICE.
- **Potentiometer**: `POT("10k", position=0.3, taper="log")`; pins `{ccw}` (1), `{w}` wiper
  (2), `{cw}` (3); position 0 = fully counterclockwise; input on `cw`, `ccw` to ground means
  clockwise is louder. Each pot keeps its setting as SPICE instance parameters.
- A subcircuit that uses `[VCC]`/`[VEE]` without supply ports gets a `.global VCC VEE` card;
  drive those nets by name in the testbench, or expose `{vp}`/`{vn}` ports instead.
- `includes` adds top-level `.include` cards. For a component-only library whose verifier
  supplies approved models, omit `includes`; pass model files to `render(spice_libs=...)`
  and include them in your simulation testbench instead.
- `OPAMP_IDEAL()`: ideal op-amp **without supply pins** (3 pins: `+` above `-`, output E),
  simulated by the bundled `yasdl_ideal_opamp` model, auto-included by `spice_netlist`. Use it
  for transfer-function work; no `[VCC]`/`[VEE]` wires. A `+` on its lower input flips it.
- `V("dc 0 ac 1")`, `I("1m")`: independent sources; the value is the SPICE source spec. `+`
  marks V's positive pin; `v`/`^` beside I's output pin gives the current direction.
- Parts without a default SPICE mapping (the 5-pin `OPAMP()`) need `Atom(..., spice=SpiceModel(...))`,
  e.g. a behavioural subcircuit `SpiceModel("X", pins=(...), model="myopamp")`.

## Standard blocks (`yasdl.std`): reuse before you draw

| Need | Block |
|---|---|
| five-pin op-amp in any op-amp hole | `std.powered(opamp)` |
| buffer / gain stages | `std.follower(U)`, `std.noninverting(rf, rg, U)`, `std.inverting(ri, rf, U)` |
| filters | `std.rc_lowpass`, `std.rc_highpass`, `std.sallen_key_lowpass`, `std.sallen_key_highpass` |
| compound transistors (`{c}` N, `{b}` W, `{e}` S) | `std.darlington`, `std.sziklai`, `std.parallel(q, n, re)` |
| mirrors, differential pairs | `std.mirror`, `std.wilson`, `std.diff_pair`, `std.diff_active` |
| class-AB output stage | `std.push_pull_buffer(kind, upper, lower)` or `std.push_pull_vas(kind, npn, pnp, rb=)`, kind `bjt`/`darlington`/`sziklai` (bias string sized for the kind) |
| adjustable output bias | `std.push_pull(qn=..., qp=..., bias=std.vbe_multiplier(q, r1, r2))`: V = Vbe (1 + r1/r2), for when no whole number of diodes gives the wanted quiescent current |

They are verified (KiCad round trips and ngspice characterisation). Bind your own parts into
them; for a PNP-equivalent compound, bind PNPs and let the host's `{e}` label orient it.

Sallen-Key arguments put the shunt-to-ground component before feedback: low-pass
`(r1, r2, c_shunt, c_feedback, U)`, high-pass `(c1, c2, r_shunt, r_feedback, U)`.
The center-driven `push_pull_buffer` accepts already-composed output halves; the
bottom-driven `push_pull_vas` constructs halves or accepts `qn`/`qp` and `bias`.
Supply all package units once; check a partial-package block inside its containing design.
`POT(rotation=...)` and `POT(position=...)` both describe shaft rotation; `pot_position`
returns electrical track position. `Sketch.crossing_count` counts deliberate crossings;
`Sketch.crossings` exposes their coordinates. Full callable details: `docs/API.md`.

## Sketch for wide canvases

Counting columns by hand is the most common source of errors (a row shifted by one column).
For anything with more than a few rows, build the canvas with `Sketch`:

```python
s = Sketch()
s.text(0, 0, "{in}").hline(0, 4, 7).text(0, 8, "R1").hline(0, 10, 13)
s.hline(0, 15, 18).text(0, 19, "{out}")
s.vline(14, 1, 1).text(2, 14, "C1")
s.junction(0, 14)                          # ┬: explicit, in the empty cell the wires meet
s.wire([(3, 14), (4, 14), (4, 8)])         # a route; the elbow ┘ is generated
s.text(4, 3, "[GND]")                      # (ports must stay on the canvas edge)
LPF = Block("LPF", s.render(), R1=R("1k"), C1=C("100n"))
# s.hline(r, c0, c1, cross=1) would declare one deliberate crossing
```

- Operations never overwrite anything (not even the same glyph) and are atomic: an error
  leaves the canvas unchanged and names the cell and what is there.
- Crossings: only straight-over-straight at 90°, both wires continuing; declare the count
  with `cross=N` (default 0). Minimise them.
- A wire may not end against another wire's side: leave that cell empty, then
  `junction(r, c)` (or `text(r, c, "├")` when the junction touches parts).
- `wire()` end points may sit on a label/component cell to attach to it:
  `wire([(4, 18), (4, 17), (7, 17)])` from `{b}` at (4, 18) draws `┌` at (4, 17).

Plan coordinates first: columns for vertical legs, rows for horizontal chains; loop over
repeated parts. Print `s.render()` and read it before binding.

## Common errors

| Error | Fix |
|---|---|
| `binding 'CC' has no component` | the name collapsed by KMP (`CC` → `C`); rename (`CK`, `C1`) |
| `dangling wire` | the wire points at empty space; extend it, or end it on a label or port |
| `use a tee glyph` | a wire ends on a straight wire; replace that cell with `├ ┤ ┬ ┴` |
| `does not fit its drawing` | drawn pins per side ≠ part's pins; add or remove wires, or orient |
| `must cover a rectangle` / `identical` | the component touches another or is ragged; keep the gap |
| `{x} must sit on the block edge` | brace labels only on the outer edge, opposite their wire |
| `port alias 'GND' is reserved` | ground and supplies are global nets, not pins: wire to `[GND]`/`[VCC]` inside the block, and give a separate return pin another name (`{gnd_ret}`) |
| `names two different nets` | one name was used for two nets (labels, port aliases, globals, ignoring case); rename one |
| `port ... is on the global ground` (SPICE) | ground is implicit in SPICE; don't give the block a ground port |
| `... is meant to be the same component, a row is shifted` / `ragged` rows listed | a row is off by one column; the caret marks it; use `Sketch` |
| `value '1M' means 1e+06 to KiCad but 0.001 to ngspice` | write `1Meg` (or `1m`), `4.7k` instead of `4k7` |
| `does not fit its drawing` with an orientation list | each listed orientation names the label it contradicts; fix the label or the wires |
| `NC ... must end a net with exactly one device pin` | the NC wire reaches several pins (or a global/port); NC marks one unused pin |
| `package U1: units [...] are not bound` | bind every unit once, power unit included |
| `SPICE model '...' is not defined in spice_libs` | pass the model file in `render(spice_libs=...)` |
| `YasdlDependencyError: ... needs kicad-cli` | install KiCad 9 or set `YASDL_KICAD` |
| `already holds ...` (Sketch) | the cell is taken; route elsewhere, or declare a clean crossing with `cross=` |
| ERC violations | shouldn't happen (helpers are automatic); report them as a yasdl bug |
