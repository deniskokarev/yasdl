# yasdl — yet another schematic definition language

yasdl describes a circuit as **ASCII drawings of rectangular blocks** and turns them into a
**KiCad 9 schematic** and a **SPICE netlist**. The goal is a schematic that is readable by
construction.

- **2D, rectangular.** Each block is a small drawing: components are rectangles, wires are
  ASCII art. What you draw is the circuit's topology and its picture at the same time, so the
  output is planar and aligned without any automatic placement or routing.
- **Composition.** Blocks contain other blocks. A block fits a placeholder when its pins line up
  with the placeholder's wires: same count and order on each side, matching pin names. yasdl
  rotates or mirrors it automatically to make it fit. Large designs are built from small,
  separately readable blocks.
- **Layout.** Widths and heights are adjusted automatically by stretching wires. Symbols keep
  their size; nothing has to be positioned by hand.
- **Export.** KiCad schematics that pass ERC with no errors or warnings, and SPICE
  (sub)circuits for ngspice, both from the same object.

Netlist-first tools like [SKiDL](https://github.com/devbisme/skidl) compose circuits too, but
they treat a schematic as a graph and leave the drawing to an automatic placer and router.
That ignores the 2D nature of a schematic: medium to large designs can't be laid out
properly. yasdl keeps the 2D arrangement in the source.

```python
from yasdl import Block, C, OPAMP, R

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
              │    [VEE]      │
              │      │        │
    {in}──IN──┴──────U1U1U1   │
                     U1U1U1───┴──{out}
              ┌─────+U1U1U1
              │      │
            [GND]  [VCC]
""", U1=OPAMP())

amp = INV_AMP.bind(IN=SERIES, FB=PARALLEL)   # sub-circuits plugged into the IN and FB holes
```

![inverting amplifier](docs/examples/InvAmp.png)

Full reference: [SPEC.md](SPEC.md).

## 1. Concepts

- **Block**: a rectangular canvas of characters. Its `W x H` cells are the text columns and
  rows. A block is a component that other blocks can use.
- **Component**: a rectangle of the canvas holding a name (`U1U1U1`, `NPN`, `FB`). Every
  component is **unbound** until a block binding gives it a value.
- **Binding**: `Block(name, canvas, U1=OPAMP(), ...)` or `.bind(...)`. A component can be
  bound to
  - an **atom**: a KiCad library symbol, rigid;
  - another **block**: a sub-circuit, stretchable.
- **Unbound components** are the block's open interface (the "holes"). They are bound later
  with `block.bind(...)`. A block can only be rendered or netlisted when everything is bound.
- **Ports**: the wires that leave the canvas edge are the block's external pins.

## 2. Canvas syntax

| Element | Looks like | Meaning |
|---|---|---|
| component | `R1`, or `U1U1U1` repeated over a rectangle | a placeholder; its name is the repeated word |
| wire | `─ │ ┌ ┐ └ ┘` (or `-` `\|`) | connections, drawn as ASCII art |
| junction | `├ ┤ ┬ ┴ ┼` | wires fork; `┼` always connects |
| crossing | `───│───` | wires cross without connecting (the middle character is on top) |
| net label | `[VCC]`, `[GND]` | names a net; same name, same net, without drawing the wire. Power names draw as power symbols |
| port | `{in}`, `{out}` on the canvas edge | a named external pin of the block |
| pin label | `[b]`, `+`, `>`, `v` touching a component | which pin of the part this wire is; arrows also fix its orientation |

Components must not touch each other; keep at least one cell between them. Wires can fork,
cross and overlap freely. Buses (bundles of wires) are specified and will be supported later.

Reading the inverting amplifier above:
- `IN` and `FB` are **holes**: unbound components with one wire on each side. Any 2-terminal
  part or sub-circuit fits; here the `SERIES` and `PARALLEL` blocks.
- `U1U1U1` (3 rows) is the op-amp. Its two inputs are on the left: the inverting input on top,
  joined to `IN` and `FB` by the `┴` junction. The `+` next to the lower input marks the
  non-inverting input; it tells yasdl to flip the op-amp symbol so `−` is on top.
- The output leaves on the right through the `┴` that also closes the feedback loop over `FB`.
- `[VEE]` above and `[VCC]` below are the supply pins; `[GND]` grounds the `+` input. They
  become KiCad power symbols, and `GND` is SPICE node 0.
- `{in}` and `{out}` are the block's ports.

## 3. Binding

A `Block` works like a C++ template: its canvas is a fixed arrangement of wires around
**placeholders**, and you fill the placeholders later, loosely, with whatever matches. The
ASCII drawing is wires plus holes. **Binding** inserts a component (a KiCad symbol) or a whole
sub-circuit (another block) into a hole, as long as its pins line up with the hole's wires. The
same template serves many circuits:

```python
gain10 = INV_AMP.bind(IN=R("10k"), FB=R("100k"))
integrator = INV_AMP.bind(IN=R("10k"), FB=C("10n"))
filtered = INV_AMP.bind(IN=SERIES, FB=PARALLEL)
```

## 4. Layout

To produce a presentable schematic, the block's wires are stretched automatically so that each
inner block or symbol gets enough room, and connected pins stay aligned. Everything is drawn on
a single KiCad sheet; hierarchical sheets will come later.

## 5. Export

- **KiCad 9**: a `.kicad_sch` (plus project files) and an SVG. Every export passes
  `kicad-cli sch erc` with no errors or warnings; the helpers ERC needs (power flags, test
  points on open ports) are added automatically. A round trip checks that KiCad reads back
  exactly the netlist yasdl generated.
- **SPICE**: `spice_netlist(block, subckt="name")` writes an ngspice (sub)circuit from the same
  design. For simulatable designs, KiCad's own SPICE export is checked against it too.

```python
from yasdl import spice_netlist
from yasdl.kicad_export import render

render(amp, "out")                                   # out/InvAmp.kicad_sch + .svg, with checks
print(spice_netlist(PARALLEL, subckt="parallel"))
```

## 6. Skill

`skills/yasdl-circuit-design/SKILL.md` teaches AI coding agents to design circuits in yasdl. It
covers hierarchical design (small blocks, composed by yasdl), the canvas cheat sheet, a style
guide and common errors. Install it with
`ln -s ~/work/yasdl/skills/yasdl-circuit-design ~/.claude/skills/`; it triggers on circuit
design tasks.

## 7. Examples

| Example | Code | |
|---|---|---|
| Series, parallel, R + (R ∥ R) | [examples/blocks.py](examples/blocks.py) | ![](docs/examples/SeriesParallel.png) |
| Darlington pair (fits wherever an NPN is drawn) | [examples/blocks.py](examples/blocks.py) | ![](docs/examples/Darlington.png) |
| Inverting op-amp with sub-circuits bound into its holes | [examples/blocks.py](examples/blocks.py) | ![](docs/examples/InvAmp.png) |
| PARALLEL bound into a vertical slot (turned automatically) | [examples/blocks.py](examples/blocks.py) | ![](docs/examples/Shunt.png) |
| 2 kHz sine generator, composed from small blocks | [examples/sgen.py](examples/sgen.py) | ![](docs/examples/SGen.png) |
