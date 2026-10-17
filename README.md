# yasdl — yet another schematic definition language

yasdl describes circuits as **nested rectangular blocks of cells**, not as nets of pins.
The layout is part of the definition, so the schematic it produces is readable by
construction: wires never cross, and ports and wires stay horizontally and vertically
aligned when blocks stretch.

It targets machine-generated circuits (benchmark and synthesis tasks) that a human has to
check by eye, with KiCad schematics as the output format.

## Why not SKiDL

SKiDL (and netlist-first tools generally) describe connectivity and leave the drawing to
an automatic placer and router. The result is correct but usually hard to read. yasdl
inverts that: you describe the 2D arrangement, and connectivity follows from which cell
edges touch.

## The model

### Cells and blocks

- A **block** is a rectangle of **W x H cells**, written as H rows of W cells.
- A **cell** holds one of:
  - an **atom**: a KiCad symbol (R, C, L, NPN, op-amp, power symbols, ...) or a wire glyph;
  - another **block**;
  - a **hole**: a placeholder for a block or atom supplied later;
  - nothing (`.`).
- An atom can **span** a rectangle of cells (the op-amp spans 3 rows: `-`, `out`, `+`).
- Every connection sits at the **midpoint of a cell edge**, at most **one per cell side**.
  Two neighbouring cells must agree on their shared edge: both connect or neither does.
  A connection that runs into a cell that doesn't take it is an error (dangling).

### Wires

There is one glyph for every set of 2 or more sides, 11 in total:

| sides | glyphs |
|---|---|
| 2 (straight, elbows) | `─` `│` `┌` `┐` `└` `┘` |
| 3 (tees) | `├` `┤` `┬` `┴` |
| 4 | `┼` (always a junction: designs are planar, nothing crosses) |

Tees and the cross get a junction dot in KiCad. A parallel connection is a tee plus an
elbow; an empty middle row between branches shrinks to zero height, so no dedicated
"fork" glyph is needed.

### Ports are inferred

A block's **outer ports** are the connections on its boundary. A port is identified by its
side and its index along that side (row from the top for W/E, column from the left for
N/S). Nothing else declares them.

### Holes and `export`

A **hole** is an inner interface cell, `Hole(name, n)`, that accepts any element with `n`
ports. A block with holes is a template:

- `block.fill(IN=R("10k"), FB=Parallel(R("100k"), C("10n")))` fills holes;
- a parent that places a block with unfilled holes must **export** them
  (`export=["A2.IN", "A2.FB"]`); they become the parent's holes, filled later by dotted
  path (`.fill({"A2.IN": R()})`);
- a top-level design must have no holes left.

### Automatic rotation

Single-cell elements (atoms, blocks, holes) are rotated (90° steps, plus top/bottom mirror)
to match their neighbours. A resistor between two vertical wires stands up; the same
resistor in a row lies down. A horizontal 2-port block fills a vertical 2-port hole by
rotating. When the neighbours don't decide, the element takes the orientation that connects
to the most neighbours, then the symbol's library orientation. Orientation can be fixed by
hand (`R().rot()`, `OPAMP().flip()`); this matters for polarised and multi-input parts, and
the op-amp's inputs can't be told apart by sides alone.

### Single-cell rule

An element in a single cell has at most one port per side. Anything with 2+ ports on a side
(op-amp inputs, a block with two W ports) must span that many rows or columns.

## Layout (planned)

Gridbag-like: a cell is as large as its content, rows and columns stretch to their
largest cell, and stretching propagates up and down the hierarchy. Stretch goes into wires
(leads lengthen), never into symbols.

Ports are generally not at a cell's centre: in the inverting amplifier the input is on the
`-` row and the output on the middle row. So alignment is solved as a **system of difference
constraints**:
- track boundaries and each element's offset inside its cell are the variables;
- containment and minimum sizes give inequalities;
- touching ports give equalities;
- multi-pin symbols are rigid (op-amp pins are fixed 2.54 mm apart).

The smallest solution is a longest-path computation (Bellman-Ford). A positive cycle means
the layout is infeasible, e.g. a rigid op-amp whose rows are forced apart by taller content
in another column. That's reported as an error naming the conflicting cells.

## Output (planned)

- `.kicad_sch` for KiCad 9: library symbols, wires, junctions, power symbols.
- Check: render with `kicad-cli sch export svg`, export the netlist back with
  `kicad-cli sch export netlist`, and compare it with `yasdl.netlist()`. A schematic only
  counts as correct if the picture is provably the same circuit as the netlist.
- SPICE netlist from the same object, for simulation-based grading.

## Example

```python
from yasdl import Block, Hole, OPAMP, GND, R, C, Parallel, netlist

INV_AMP = Block("InvAmp", """
    .   ┌  FB  ┐  .
    IN  ┴  U1  │  .
    .   .  U1  ┴  ─
    .   ┌  U1  .  .
    .   GND .  .  .
""", IN=Hole("IN", 2), FB=Hole("FB", 2), U1=OPAMP().flip(), GND=GND())

lossy_integrator = INV_AMP.fill(IN=R("10k"), FB=Parallel(R("100k"), C("10n")))
print(netlist(lossy_integrator))
```

The grid text is the schematic sketch. More in `examples/blocks.py`:
- series, parallel and series-parallel resistors
- Darlington pair (same W/N/S signature as an NPN, so it can replace one)
- common-emitter amplifier with collector-to-base feedback and a transistor hole
- inverting op-amp with input and feedback holes
- a two-stage chain with re-exported holes

## Status

| Part | State |
|---|---|
| Grid parsing, spans, holes, fill/export | done |
| Port inference, edge (dangling) checks, auto-rotation | done |
| Flat netlist | done |
| Geometry / constraint layout | planned |
| KiCad export + round-trip check | planned |
| SPICE export | planned |

## Open questions

- **Planarity escape hatch.** Some circuits are non-planar, and long feedback loops across
  stages are awkward on a grid. Net labels (a 1-port atom carrying a net name) would break
  the "no hidden connections" rule on purpose. Allow them, and where?
- **Op-amp supply pins.** They are not grid ports yet. Options: hide them (implicit ±V
  nets) or draw power symbols inside the op-amp's own cell area.
- **Named ports.** Ports are `W1`, `E2`, ...; aliases like `in`/`out` would help.
- **Polarised fills.** When a hole accepts a part by rotation, which of the two fitting
  rotations is right for a diode or electrolytic? Probably a declared port order on the hole.
