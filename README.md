# yasdl — yet another schematic definition language

yasdl describes a circuit as an **ASCII drawing of rectangular blocks**. The drawing is both
the netlist and the layout: yasdl turns it into a readable KiCad 9 schematic by stretching
wires (never symbols) to keep everything aligned, the way Java's GridBagLayout stretches cells.

```python
from yasdl import Block, OPAMP, GND, R

SERIES = Block("Series", """
    ──R1──R2──
""", R1=R("1k"), R2=R("2k"))

PARALLEL = Block("Parallel", """
    ──┬──R1──┬──
      │      │
      └──R2──┘
""", R1=R("10k"), R2=R("10k"))

INV_AMP = Block("InvAmp", """
          ┌──────FB───────┐
          │               │
          │    <VEE>      │
          │      │        │
    ──IN──┴──────U1U1U1   │
                 U1U1U1───┴──
          ┌─────+U1U1U1
          │      │
         GND   <VCC>
""", U1=OPAMP(), GND=GND())

amp = INV_AMP.bind(IN=SERIES, FB=PARALLEL)   # sub-circuits bound into components
```

![inverting amplifier](docs/examples/InvAmp.png)

It targets machine-generated circuits (benchmark and synthesis tasks) that a person has to
check by eye. SKiDL and other netlist-first tools leave the drawing to an automatic placer;
yasdl inverts that.

---

## 1. Concepts

- **Block**: a rectangular canvas of characters. Its `W x H` cells are the text columns and
  rows. A block is a component that other blocks can use.
- **Component**: a rectangle of the canvas holding a name (`U1U1U1`, `NPN`, `FB`). Every
  component is **unbound** until a block binding gives it a value.
- **Binding**: `Block(name, canvas, U1=OPAMP(), ...)` or `.bind(...)`. A component can be
  bound to
  - an **atom**: a KiCad library symbol, rigid, can be rotated or mirrored;
  - another **block**: a sub-circuit, stretchable.
- **Unbound components** are the block's open interface (the "holes"). They are bound later
  with `block.bind(...)`. A block can only be rendered or netlisted when everything is bound.
- **Ports**: the wires that leave the canvas edge are the block's external pins.

## 2. Canvas syntax

### 2.1 Characters

| Class | Characters | Notes |
|---|---|---|
| empty | space, `.` | `.` is a visual aiming aid only |
| component | `A-Z a-z 0-9 _` | see 2.2 |
| single wire | `─ -` `│ \|` `┌ ┐ └ ┘` `├ ┤ ┬ ┴` `┼` | ASCII `-` `\|` equal `─` `│` |
| bus | `═ ║ ╔ ╗ ╚ ╝`, taps `╟ ╢ ╤ ╧` | section 2.6 (specified, not implemented yet) |
| label | `<text>` on one row | net label or pin label, 2.4–2.5 |
| pin shortcut | `+` | a one-character pin label |

Any other character is an error. Whatever isn't explicitly allowed below is forbidden.

### 2.2 Components

- A component is a **rectangle of component characters** whose rows are all the same
  string.
- Its name is that string's **minimal period**, computed with the KMP failure function:
  `U1U1U1` → `U1`, `RRRR` → `R`. If no period divides the string evenly, the whole string is
  the name: `NPN` → `NPN`, `U1U1U` → `U1U1U`.
- Names are **local to the block**: `U1` in two blocks are two components.
- **Gap rule**: components never touch. Touching characters merge into one rectangle, or fail
  if the result isn't one. Keep at least one empty or wire cell between components. The gap
  is also where the layout puts its wire adapters (section 4).
- A component's on-canvas size says nothing about its real size; binding decides that, and
  the layout stretches around it.

### 2.3 Single wires

- Every wire character has **arms** toward its neighbours: `─` has E and W, `┬` has E, S
  and W, `┼` has all four. Each arm must meet one of:
  - a wire that continues it;
  - a label;
  - a component edge (making a pin attachment);
  - the canvas edge (making a port).
  
  An arm pointing at an empty cell is a **dangling wire**, an error.
- `┼` is always a **junction**. Tees `├ ┤ ┬ ┴` are the only other junctions, and they get a
  dot in KiCad.
- **Crossing** (no connection): a straight wire with perpendicular wires arriving on both
  sides. The character drawn is the wire on top; the other passes under.
  ```
     │              │
  ───│───   or   ───────     (vertical on top / horizontal on top)
     │              │
  ```
- A wire that ends on a straight wire from one side only (an implied T) is an error; use a
  tee.

### 2.4 Net labels (implicit wires)

- `<name>` touching a wire names its net. **All labels with the same text in a block are the
  same net**, connected without drawing the wire. This is the escape hatch for non-planar
  circuits and long loops (`<VCC>`, `<VEE>` above).
- A label can sit at the end of a wire (a net port) or inline in it (`──<x>──`).
- Horizontal wires enter a label only at its `<` or `>` end. Vertical wires pass through one
  column inside the label.
- A label must not touch a component edge, or it becomes a pin label (2.5).
- When a sub-block is drawn into a parent, its net labels stay block-scoped. In the flat
  KiCad output they are prefixed with the instance path (`FB.x`).

### 2.5 Pins

- A pin **attachment** is a wire arm, or a pin label, that touches a component edge.
- Pins on a side are ordered: **W and E sides top to bottom, N and S sides left to right**.
- **Pin labels**: a label touching a component edge names the pin, matched case-insensitively
  against the symbol's pin name or number. `<c>` and `<b>` are enough to orient a transistor.
  A pin label must have a wire on its other side. Pin labels never name nets.
  ```
   │
  <c>
  Q1Q1          collector on top, base on the right: the NPN is mirrored
  Q1Q1<b>─
  Q1Q1
   │
  ```
- `+` is a one-character pin label (`──+C1──`, or `+` on the op-amp's non-inverting input
  above). Atoms can declare aliases, e.g. `C_POL` maps `+` to pin 1. Only `+` is reserved so
  far.

### 2.6 Buses (specified, not implemented)

- `═ ║` with elbows `╔ ╗ ╚ ╝` carry an **ordered, parallel bundle** of 1 or more wires. A
  single wire may be drawn as a bus.
- **Order is travel-relative and invariant.** Walking along a bus, its wires are ordered
  from the walker's left to right; elbows don't change that. At a component side, this
  becomes the side's pin order (2.5): a bus leaving an E side heading east has its first
  wire at the top. So `U1.E[i]` connects to `U3.W[j]` by position, and the drawing alone
  defines the mapping. Mirroring a component reverses its side order, and so changes the
  netlist; there are no implicit crossing adapters.
- **Width inference**: a component side's pin list is the concatenation of the buses and
  wires attached to it, in order. Widths propagate from bound components. When every bus on
  a side but one is known, the last one is inferred. An undetermined width is an error.
- **Taps**: only single-wire taps, `╟ ╢ ╤ ╧`, each followed by a label that selects the wire
  by name or 1-based number (`╟──<3>──`, `╟──<MISO>──`). Tapping a wire the bus doesn't carry
  is an error. Taps take wires out of a bus; they never add them.
- **Crossings**: bus over bus at 90° only, drawn like single-wire crossings (2.3). There is
  no bus-to-bus junction (`╬`) or bus tee (`╠`). Wire/bus crossings, junctions and other
  shapes are forbidden.
- **Ports**: buses reaching the canvas edge are ports. Their wires appear in the side's pin
  list in order, named by the bus's net labels (`<a>═══` gives `a.pins`).
- **KiCad**: drawn as individual parallel wires. (Open: use KiCad buses above some width.)

### 2.7 Ports (block interface)

- A wire arm leaving the canvas is a port on that side, ordered as in 2.5.
- A port's name is the net label on its net, if there is one; otherwise it is `W0`, `E1`, ...
- A component sitting on the canvas edge exports nothing. Ports must be drawn as wires.

## 3. Binding

### 3.1 Signature

A component can only be bound to something with **exactly the drawn number of pins on each
side**:
- an atom whose symbol has a pin where the drawing has none can't be bound;
- a block whose W side has two ports can't go into a component drawn with one W wire;
- a 3-port Darlington fits anywhere an NPN is drawn, because both have one pin on the top,
  left and bottom.

Pins map to attachments **by position along each side**.

### 3.2 Orientation of atoms

Atoms are drawn in their KiCad library orientation unless one of these applies, in order:
1. explicit `Atom(...).oriented(rot, mirror)` (rot in degrees counterclockwise, mirror
   `"x"`: top/bottom, `"y"`: left/right);
2. pin labels: the orientation must be the only one consistent with them, otherwise it's an
   error ("label another pin");
3. the library orientation, if it fits the drawing;
4. symmetric parts (R, C, L): whichever rotation the drawn sides force, e.g. a resistor
   between W and E wires lies down.

Nothing else is rotated automatically. Inconsistent labels, like `<e>` where only C or B
could go, are errors.

*(Corner markers like `*` for pin 1 were considered and dropped: they break the KMP naming
and `.` already means empty. Pin labels give the same information.)*

### 3.3 Sub-blocks

A block bound into a component maps its ports, per side and in order, to the component's
attachments. Sub-blocks aren't rotatable yet.

## 4. Layout

- **Grid-bag.** Every canvas row r gets a centreline `y[r]`, every column c a centreline
  `x[c]`, every component an origin. Rows and columns stretch to their contents, and
  stretching propagates through nested blocks: a bound sub-block is laid out first, then
  placed as a rigid shape.
- **Only wires stretch.** KiCad symbols are rigid. They can be rotated or mirrored but not
  scaled. Horizontal wires stretch along X, vertical wires along Y.
- **X and Y are independent** systems of difference constraints, solved by longest path
  (Bellman-Ford):
  - rows and columns are strictly ordered;
  - consecutive items in a column (for Y) or row (for X) keep a clearance;
  - a component's first pin on a side lies exactly on its wire's line; further pins are
    aligned greedily while that stays feasible.
- **Ladder adapters.** A pin that can't be aligned is reached by a jog in the gap next to the
  component, one track per jogging pin. The tracks are ordered so that no two wires cross
  (river routing). Each jog widens the component's extent by one track (2.54 mm) on that side.
  X and Y iterate until the set of jogs stops changing.
  ```
      |                  |            | |          (pins 1-4 shifted individually,
      └-┐                |            | |           order preserved, no crossings)
        | ┌--------------┘            | |
        | | ┌-------------------------┘ |
        | | | ┌-------------------------┘
        | | | |
  +-----1-2-3-4------+
  ```
- **Text space**: reference and value fields are reserved in each atom's extent.
- **Grid**: every coordinate is a multiple of 1.27 mm (KiCad's default grid).

## 5. KiCad output

- One flat sheet. Symbols are copied from KiCad 9's libraries into `lib_symbols`. References
  are annotated (`R1`, `Q2`, `#PWR001`), and each symbol carries a `yasdl_path` field with its
  hierarchical name (`FB.R1`).
- Wires, junction dots, net labels, and labels for the top block's ports.
- **Round-trip check.** `kicad-cli sch export netlist` on the generated file must reproduce
  `yasdl.netlist()` exactly, compared as sets of pins per net with power symbols excluded. A
  rendering only counts if it passes.
- `kicad-cli sch export svg`, cropped to the drawing.

## 6. Examples

`examples/blocks.py` (rendered by `python -m examples.render`, images in `docs/examples/`):

| Example | |
|---|---|
| Series, parallel, R + (R ∥ R) | ![](docs/examples/SeriesParallel.png) |
| Darlington pair (same drawn signature as an NPN) | ![](docs/examples/Darlington.png) |
| Inverting op-amp, series input and parallel feedback bound as sub-blocks | ![](docs/examples/InvAmp.png) |

## 7. Status

| Part | State |
|---|---|
| Canvas: components, KMP names, wires, crossings, labels, pin labels, `+`, ports | done |
| Binding: signatures, orientation rules, sub-blocks, flat netlist | done |
| Grid-bag layout with greedy alignment and ladder adapters | done |
| KiCad 9 export, round-trip check, SVG | done |
| Buses | specified, not implemented |
| Sub-block rotation, hierarchical sheets, SPICE export | not started |

## 8. Open questions

- Bus crossings: should "which bus is on top" carry meaning (like PCB layers), or is it
  only how it's drawn?
- KiCad buses vs parallel wires: switch above some width (5?).
- Global pin numbering for block ports, e.g. DIP-style counterclockwise from top-left, in
  addition to side/index.
- Rotating and mirroring sub-blocks, and what happens to their bus order.
- Flat output vs one hierarchical KiCad sheet per sub-block.
- Label text width is estimated (1.27 mm per character), not measured.
