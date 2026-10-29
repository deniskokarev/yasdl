# yasdl specification

The full language and tool reference. For an overview and a first example, see
[README.md](../README.md).

## 1. Concepts

- **Block**: a rectangular canvas of characters. Its `W x H` cells are the text columns and
  rows. A block is a component that other blocks can use.
- **Component**: a rectangle of the canvas holding a name (`U1U1U1`, `NPN`, `FB`). Every
  component is **unbound** until a block binding gives it a value.
- **Binding**: `Block(name, canvas, U1=OPAMP(), ...)` or `.bind(...)`. A component can be
  bound to
  - an **atom**: a KiCad library symbol, rigid, can be rotated or mirrored;
  - another **block**: a sub-circuit, stretchable;
  - `NC()`: no-connect markers on the drawn wires (2.9).
- **Unbound components** are the block's open interface (the "holes"). They are bound later
  with `block.bind(...)`. A block can only be rendered or netlisted when everything is bound.
- **Ports**: the wires that leave the canvas edge are the block's external pins.

## 2. Canvas syntax

### 2.1 Characters

| Class | Characters | Notes |
|---|---|---|
| empty | space | |
| reserved | `.` | reserved for future use; an error for now |
| component | `A-Z a-z 0-9 _` | see 2.2 |
| single wire | `─ -` `│ \|` `┌ ┐ └ ┘` `├ ┤ ┬ ┴` `┼` | ASCII `-` `\|` equal `─` `│` |
| bus | `═ ║ ╔ ╗ ╚ ╝`, taps `╟ ╢ ╤ ╧` | section 2.6 (specified, not implemented yet) |
| bracket label | `[text]` on one row | global or local net name (2.4) |
| arrows | `<` `>` `^`, and a lone `v`/`V` | reserved for directional pin labels (2.5) |
| brace label | `{text}` on one row | adjacent component pin (2.5), otherwise an interface on the block edge (2.7) |
| pin shortcut | `+` | a one-character pin label |

Any other character is an error. Whatever isn't explicitly allowed below is forbidden.

### 2.2 Components

- A component is a **rectangle of component characters** whose rows are all the same
  string.
- Its name is that string's **minimal period**, computed with the KMP failure function:
  `U1U1U1` → `U1`, `RRRR` → `R`. If no period divides the string evenly, the whole string is
  the name: `NPN` → `NPN`, `U1U1U` → `U1U1U`.
- Names are **local to the block**: `U1` in two blocks are two components.
- A binding whose name reduces to a drawn component's name (`CC=` for a drawn `CC`, named
  `C`) fails with a hint that says so. A ragged rectangle error lists each row's extent and
  points at the row that deviates; a duplicate name in an adjacent row is reported as a
  probable shifted row.
- A component can't be named `v` or `V` (or `vv`, `VVV`, which reduce to it): a lone `v` is the
  down-arrow pin label (2.5). `v` inside a longer name is fine (`v1v1v1` → `v1`, `VR1`).
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
- A crossing may sit directly beside a component or label. The renderer connects through
  it to the next real node or pin, without placing an electrical endpoint on the crossing.
- A wire that ends on a straight wire from one side only (an implied T) is an error; use a
  tee.

### 2.4 Bracket labels: nets

Square brackets always name nets. A net label needs at least one wire and must not directly
touch a component; insert a wire between a net label and a component. Use braces to name a
component pin (2.5).

| Name | Meaning |
|---|---|
| starts with `A-Z`, e.g. `[Signal]` | **global net**: the same name connects across every block and instance |
| starts with `a-z` or `_`, e.g. `[signal]`, `[_bias]` | **local net**: the same name connects within this block only |
| registered power name, e.g. `[+5V]`, `[-12V]` | **global net**, regardless of its initial character |
| starts with a digit, e.g. `[1]`, `[0]` | error; numeric names are permitted for brace pins/interfaces, not nets |

Scope depends on the name, not the number of wires. `──[Signal]──` is global, and a terminal
`──[signal]` is local. Every net label needs at least one wire. Registered power names must
still use their exact registered spelling (`[GND]`, not `[gnd]`).

Horizontal wires enter at the opening `[` or closing `]`. Vertical wires may enter at any
column occupied by the label, including either delimiter; two vertical wires through one
label must use the same column.

- **Power nets**: a global label whose name is in the power-net registry (`GND`, `GNDA`, `VCC`,
  `VEE`, `VDD`, `VSS`, `+5V`, `+3V3`, `+12V`, `-12V`; extend with
  `register_power_net("+15V", "power:+15V")`) is drawn as that KiCad power symbol. The symbol's
  pin faces the wire and its body points away; the layout reserves its real size. Electrically
  nothing changes: the net is still the global net, and `GND` is SPICE node 0. So
  ```
     │
   [GND]
  ```
  replaces placing `GND()` atoms one by one.
- In the flat KiCad output, local names are prefixed with the instance path (`FB.x`); global
  names are not.

### 2.5 Pins

Migration: replace old component pin labels such as `[b]` and `PS[in]` with `{b}` and
`PS{in}`. Square-bracket net labels such as `[GND]` keep their meaning.

- A pin **attachment** is a wire arm, a brace label, or a shortcut touching a component edge.
- Pins on a side are ordered: **W and E sides top to bottom, N and S sides left to right**.
- **Brace pin labels**: `{name}` adjacent to exactly one component edge names its pin. For
  atoms, it matches a KiCad pin name or number, case-insensitively; for sub-blocks, one of the
  port names or aliases (2.7). `{b}` and `{e}` on an NPN fix its base/emitter connections;
  `{1}` may identify a numbered pin. The label needs exactly one wire on the side opposite
  the component. It is an orientation constraint and never names a net.
- **Adjacency decides usage**, even at the canvas edge. A brace touching a component is a
  pin label; a brace touching no component is an interface declaration and must obey 2.7.
  These meanings do not depend on the spelling or case of the name.
- **Horizontal adjacency**: the opening `{` or closing `}` must immediately touch the
  component. The wire enters through the other delimiter.
- **Vertical adjacency**: any character of the brace label, including `{` and `}`, may be
  directly above or below the component. Any column of the label, including either brace,
  may carry the vertical wire. The wire column need not overlap the component: the label
  connects its wire to the nearest column shared by the label and the component. All wire
  segments remain orthogonal when laid out.
  ```
  {input}────{b}Q1Q1      the wire ends on Q1's base; {input} names the block interface (2.7)
                Q1Q1
  ```

Both vertical layouts are valid:

```
Q1Q1Q1          Q1
 {e}             {e}
  │                │
```

In the second layout, `{` touches the component and the wire enters through `}`. Above a
component the same rule applies. A label touching two components or two sides of one
component is an error, including `Q1{b}Q2` and:

```
Q1 Q2
 {e}
```

A brace after a wire bend is an interface if it does not touch the component:

```
   [VCC]
      │
     {c}
{b}─Q1
     └{e}
```

Here `{c}` names Q1's collector; `{b}` and `{e}` declare W0 and E0 interfaces. Removing the
bend leaves `{e}` with neither component adjacency nor a wire, which is an error. Pin labels
may contain a KiCad pin's literal name (for example `{-}`); comma-separated aliases are
interface declarations, not a list of component pins.

  ```
   │
  {c}
  Q1Q1          collector on top, base on the right: the NPN is mirrored
  Q1Q1{b}─
  Q1Q1
   │
  ```

- `+` is a one-character pin label (`──+C1──`, or `+` on the op-amp's non-inverting input
  above). Atoms can declare aliases, e.g. `C_POL` maps `+` to pin 1.

#### Directional pin labels: `<` `>` `^` `v`

The arrows are one-character pin labels that **rotate and mirror with the part**. `v` and
`V` are the same arrow; a `v` is an arrow only when no letter, digit or `_` touches it left or
right (`v1v1v1` is a component named `v1`), which is why no component may be named `v`.

- **Meaning: conventional current.** An arrow at a pin points the way current flows through
  that pin: into the part on an input, out on an output. Atoms declare arrows in their library
  orientation (`Atom(..., arrows={pin: arrow})`):
  - `D`: the anode, `<` (current enters it and points at the cathode);
  - `NPN`: base `>` (in), emitter `v` (out, like the symbol's own arrow);
  - `PNP`: base `<` (out), emitter `^` (in).
- **One pin per arrow.** On atoms and on block ports alike, an arrow names exactly one pin, so
  `{>}──…──{>}` is an error (two ports with one alias). Name other pins with braces (`{c}`).
- **Placement**: `<` and `>` only beside a component (W/E sides), `^` and `v` only above or below
  it (N/S). An arrow touching nothing, or on the wrong axis, is an error. This also keeps arrows
  from merging into names: `──vQ1` would be a component `vQ1`, and the error says so.
- **Matching**: when binding, an arrow label at a side fits a pin only if that pin's arrow,
  turned by the candidate orientation, points the same way (3.2). So arrows choose the
  orientation. Each drawing below is a separate example:
  ```
  ──>D1──        diode, anode on the left

  ──D1<──        diode, anode on the right (library orientation)

     │
     v           diode, anode on top
     D1
     │

  ──<Q2Q2──      NPN in common base: emitter current leaves on the left, base current
     Q2Q2        enters from below, collector on the right (no arrow)
     Q2Q2
     ^
     │
  ```
  Arrows that no orientation can produce are rejected. `──D1>──`: only the anode has an
  arrow, and it points into the part. `──>Q2Q2>──` is invalid for a more basic reason: two `>`
  would name two pins, and one arrow names one pin.
- **Block ports** take arrow aliases from `{<}`, `{>}`, `{^}`, `{v}`: `<`/`>` only on W/E ports,
  `^`/`v` only on N/S ports, so a rotation can never turn an arrow into a letter glued to a name.
  An arrow alias is never a port's display name.

**Mirror-agnostic pairs.** Arrows on opposite ports that point the same way relative to the
block (both outward `{<}──…──{>}`, or both inward `{>}──…──{<}`) still match after a
left/right mirror. Such a block fits either way round, with **no guarantee which port lands on
which side**:
```
TWO_R = Block("TwoR", "{<}──R1──R2──{>}", R1=R("1k"), R2=R("2k"))
Block("H", "{a}──<RX>──{b}", RX=TWO_R)                # a–R1 … R2–b
Block("H", "{a}──<RX>──{b}", RX=TWO_R.mirrored("y"))  # a–R2 … R1–b: the same labels fit
```
That's fine for parts that don't care (a resistor network, a fuse). When direction matters, give
the block one arrow (`{>}──D1──{k}`: `──>DX──` fits only one way) or name the ports
(`{a}`/`{k}` labels in the host). Arrows are optional: `──R1──` needs none.

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
  by name or 1-based number (`╟──[3]──`, `╟──[MISO]──`). Tapping a wire the bus doesn't carry
  is an error. Taps take wires out of a bus; they never add them.
- **Crossings**: at 90° only, never connecting, drawn like single-wire crossings (2.3), with
  the character on top shown in the middle. Allowed pairs: bus/bus and single wire/bus
  (either on top):
  ```
    ║            │
  ──║──   or   ═════      (bus over wire / wire over bus)
    ║            │
  ```
  There is no bus-to-bus junction (`╬`) or bus tee (`╠`). Other junctions and shapes are
  forbidden.
- **Ports**: buses reaching the canvas edge are ports. Their wires appear in the side's pin
  list in order, named by the bus's net labels (`[a]═══` gives `a.pins`).
- **KiCad**: drawn as individual parallel wires. (Open: use KiCad buses above some width.)

### 2.7 Ports (block interface)

- **Naming convention**: prefer lowercase initials for pin/interface names (`{input}`,
  `{b}`, `{collector}`). This is a convention, not a grammar rule: uppercase KiCad names
  remain valid and pin matching is case-insensitive. Numeric names such as `{1}` and `{2}`
  are allowed; ground `0` remains reserved as an interface name (2.8).
- **Numeric pins require braces**. Alphanumeric text outside labels belongs to component
  names: `─1U1─` contains the component `1U1`, not pin 1 of U1. Bare letter pin shorthand
  is not part of the grammar; use braces or the existing `+ < > ^ v` shortcuts.

- **Where**: a wire arm leaving the canvas, or a **brace label** `{name}` on the canvas edge.
  A brace label may list several aliases, comma-separated: `{c, collector}`,
  `{+, non_inv, noninverting, plus}`, `{>, A, Anode}`, `{<,>}`. Spaces around commas are
  ignored. The first alias that is a name (not `+` or an arrow) is the port's display name.
  The brace label has exactly one wire, going inward, and sits on the side opposite that wire
  (`{in}───` on the W edge, `───{out}` on the E edge, top/bottom rows for vertical wires).
  A brace touching a component is a pin label (2.5); an interface declaration anywhere
  else in the interior is an error.
- A component sitting on the canvas edge exports nothing. Ports must be drawn as wires.
- **Order and default names**: per side, ordered as in 2.5, named `W0`, `W1`, `N0`, ...
- **DIP number**: each port also gets a unique number `D0`, `D1`, ..., counting
  counterclockwise from the top of the W side: W top to bottom, S left to right, E bottom to
  top, N right to left (like the pins of a DIP package).
- **Aliases**, in priority order:
  1. the port's `{name}` label;
  2. programmatic aliases (below);
  3. **re-export**: if the port has neither, and its net reaches exactly one distinct pin name
     (an atom pin name other than `~`, or a sub-block port name), that name becomes the alias.
     The Darlington's ports become `B`, `C` and `E` this way, and a host can orient it with
     `{b}`/`{c}` labels. A re-exported name that collides with another port's name, or looks
     like a default name, is silently dropped.
- **Names**: aliases are letters, digits and `_`, or one of the shortcuts `+ < > ^ v`.
  No `-` or spaces (SPICE node names can't carry them). Net names additionally require the
  initial scope character from 2.4, except registered power nets (`-12V`, `+5V`). Pin labels
  stay free-form, because they match KiCad pin names such as the op-amp's `-`.
- **Uniqueness**: no two ports may share an alias (case-insensitive), within one `{}` list or
  across ports. `{<,>}──…──{>}` is an error. Aliases may not look like
  default names (`W0`, `D3`, ...) or use a reserved global name (`GND`, `VCC`, `0`, ...; 2.8).
  All are errors, whether from the drawing or from code.
- **Programmatic attributes**: `Block(name, canvas, port_attrs={key: {"aliases": [...]}}, ...)`.
  A key is a default name (`W0`), a DIP number (`D2`) or an existing alias. Only `aliases` is
  supported for now; direction and class (`in`, `out`, `inout`, `pwr`) are planned. Unknown
  keys and attributes are errors.
- `block.port(key)` looks a port up by any of its names.

### 2.8 Net naming

One rule: **every net name in a design is unambiguous, everywhere it ends up** (yasdl's
netlist, KiCad, SPICE). KiCad matches names case-sensitively and ngspice ignores case, so names
are compared case-insensitively.

Net names start with an uppercase ASCII letter for global scope, or a lowercase ASCII letter
or `_` for local scope (2.4). Registered power names are exceptions. Names may contain letters,
digits and `_` after the first character; leading digits are forbidden. Scope is distinct
from uniqueness: different nets may not differ only in case, because SPICE treats those names
as identical. For example, choose `[GlobalSig]` and `[local_sig]` rather than `[Sig]` and `[sig]`
for two different nets in one block.

1. **User-given names** (global labels, port aliases, local labels) must be unique across the
   design. Two different nets with one name are an error, never silently merged. That includes
   a top-level port alias equal to a global net used inside a sub-block.
2. **Global net names are reserved**: the power-net registry (`GND`, `VCC`, `VEE`, ...; 2.4) and
   `0`. Global nets are design-wide, and a block can't know which parents will use it, so these
   names are taken in every block:
   - no port alias (`{GND}`, `{0}`, `{vcc}`, or `port_attrs`) may use them;
   - labels must spell them exactly as registered (`[GND]`, not `[gnd]`); `[0]` is never
     allowed;
   - a label with a reserved name is always the global net, even inline (`──[GND]──`);
   - pin names like `GND` are never re-exported as port aliases.
3. Labels may not look like default port names (`W0`, `N1`, `D3`), and a block's labels may not
   reuse its port aliases.
4. **Derived names** (default port names `W0`, ...) get a `_2` suffix if they'd clash;
   **generated names** (`N1`, `N2`, ... for unnamed nets) skip every name already taken.
5. **SPICE**: the global `GND` net is node `0`. Every other net keeps its name, sanitised and kept
   unique ignoring case. A port wired to ground can't be a `.subckt` pin (SPICE ground is
   global), so `spice_netlist(subckt=...)` rejects it.

### 2.9 No-connect markers

`NC()` binds a component to no-connect markers. The drawn rectangle may have any number of
wires on any sides; the count comes from the drawing, so `X1=NC()` and `X2=NC()` need no
size:

```
       [VCC] X1           X1: one marker (LM386 BYPASS, pin 7)
           │ │
{in}──────+U1U1U1──{out}
      ┌────U1U1U1
      │    U1U1U1
      │    │ │ │
    [GND]  │ X2X2         X2: two markers (GAIN, pins 1 and 8)
       [GND]
```

- Each attachment ends its own wire with a KiCad `no_connect` at the wire's free end. Wires
  are kept as drawn; nets are never merged, split or pruned.
- Each terminated net must reach **exactly one device pin** in the flattened design, and
  must not be a global net, an external port of the design, or terminated twice. Anything
  else is an error naming the pins it reached. A child block's port may end at `NC()` when
  it reaches one inner pin; a port that fans out to several pins is an error.
- Markers have no reference, BOM entry, footprint, netlist pin or SPICE element. The pin
  keeps its isolated net, so a SPICE model terminal stays a distinct node.
- An NC component takes plain wires, not pin labels. No ERC test point or power flag is ever
  added to an NC-terminated net, and an NC net may not carry a local label.

## 3. Binding

### 3.1 Signature

A component can only be bound to something with **exactly the drawn number of pins on each
side**:
- an atom whose symbol has a pin where the drawing has none can't be bound;
- a block whose W side has two ports can't go into a component drawn with one W wire;
- a 3-port Darlington fits anywhere an NPN is drawn, because both have one pin on the top,
  left and bottom.

Pins map to attachments **by position along each side**.

### 3.2 Orientation

Orientation is decided **only at binding**. A canvas never rotates anything it contains; a
component is always drawn as it is. The same rules apply to atoms and sub-blocks. The 8
candidate orientations are rotations by 0/90/180/270° counterclockwise, each with or without a
top/bottom mirror (`"y"` is accepted and equals `"x"` plus 180°).

1. **Explicit**: `R().rotated(90)`, `PARALLEL.rotated(270)`, `OPAMP().mirrored("x")`,
   `LADDER.mirrored("y")`. These compose: `.rotated(90).mirrored("y")`. The low-level form is
   `.oriented(rot, mirror)`. The result must fit the drawing, or binding fails.
   `"y"` mirrors left/right and `"x"` top/bottom, as in KiCad. Internally `"y"` is stored as
   180° plus `"x"`; the JSON view shows it as `"y"`.
2. **Pin labels** (2.5): only orientations consistent with every label stay candidates. With
   an explicit orientation, labels are checked against it and a contradiction is an error, so
   a label is also a cheap assertion that documents the intent on the drawing. For
   atoms, labels match pin names or numbers; for sub-blocks, port names. If several
   remain, rule 3 chooses among them.
3. **Forced by the drawing**: the candidate must have exactly the drawn number of pins on
   every side (3.1). Among the candidates that fit:
   1. the one that best **keeps reading order** wins: pins on a start side (N, W) stay on a
      start side, pins on an end side (S, E) stay on an end side;
   2. then the one that **flips fewer axes**: a mirror flips one axis, a 180° turn or a
      quarter turn changes both. A sub-block's insides keep their up/down (or left/right)
      when only the other axis must change;
   3. then the order above (unrotated first).
   - The unrotated orientation always keeps reading order, so it wins whenever it fits.
   - A resistor (library: vertical) between W and E wires lies down with pin 1 on the left.
   - The horizontal PARALLEL block in a vertical slot turns so that its left port is on top
     (example `SHUNT`). `PARALLEL.oriented(90)` puts it at the bottom.

**Five-pin op-amps.** `Simulation_SPICE:OPAMP` (and op-amps built on it, 6.3) is drawn
canonically with `+` above `-` on the left, the output on the right, **V+ on top and V- at
the bottom**. A rotation or mirror moves every pin: a lone `+` on the lower input selects the
top/bottom mirror, which also puts V- on top, so `[VCC]` drawn above would reach V-. Use one
of:

- `std.powered(opamp)`: a three-port block (`+` above `-`, output E) with V+ on `[VCC]` and
  V- on `[VEE]` inside. Rotating or mirroring it carries the supply connections with it, so a
  host never reconstructs the rail mapping. It fits every three-terminal op-amp hole.
- label the supply attachments `{V+}` above and `{V-}` below. The labels assert where the
  pins must end up; a mirror that would swap them fails at binding, and the error lists every
  candidate orientation and the label it contradicts.

`[VCC]`/`[VEE]` name nets; brace labels constrain pins.

Inconsistent labels, like `{e}` where only C or B could go, are errors. When the electrical
direction matters but nothing in the drawing pins it down, e.g. a non-symmetric 2-port in a
vertical slot, rule 3 still decides, deterministically. Label a pin or orient explicitly if
the default isn't what you want.

*(Corner markers like `*` for pin 1 were considered and dropped: they break the KMP naming.
Pin labels give the same information.)*

### 3.3 Sub-blocks

A bound sub-block is oriented exactly like an atom (3.2). Its ports then map, per side and in
drawing order, to the component's attachments. In the layout, the sub-block's finished drawing
is rotated or mirrored as a whole, and the orientations of the symbols inside it are composed
with the block's.

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
- **Spilling shapes.** A bound shape is usually much larger than its few canvas characters.
  It can reach under items in other rows and columns. Boxes (components with their text, and
  net labels) that overlap are separated pairwise: in Y if their canvas rows are disjoint,
  otherwise in X. The overlap test uses the other axis's current solution, and these
  separations join the X/Y iteration.
- **Text space**: reference and value fields are reserved in each atom's extent.
- **Crossings**: composition adds none. A composed drawing has exactly the crossings drawn
  on its canvases: the parent's plus, per instance, its children's, recursively
  (`Block.crossing_count()`; `layout.wire_crossings(result)` counts them in the geometry).
  Crossings are legal where the topology needs them (a K3,3 such as a parallel transistor
  array); minimise them otherwise.
- **Grid**: every coordinate is a multiple of 1.27 mm (KiCad's default grid).

## 5. Internal representation

There are three layers, each derived from the one before:

| Layer | What it holds | Where |
|---|---|---|
| Source | canvas text + bindings | `Block(name, canvas, **bindings)` |
| Resolved block | components with rectangles, attachments and resolved bindings (orientation, pin↔wire map); local nets; ports | `Block.canvas`, `Block.bound`, `Block.to_dict()` |
| Layout | coordinates: symbols with orientation, wire segments, labels, ports, bbox | `layout.Result` |

`Block.to_dict()` exports the resolved block as JSON. Sub-block definitions are listed once
under `"blocks"` and referenced by name. Excerpt for `INV_AMP_RESISTORS`:

```json
{
  "name": "InvAmp",
  "size": {"cols": 25, "rows": 9},
  "canvas": ["      ┌──────FB───────┐", "...", "     GND   [VCC]"],
  "components": {
    "U1": {
      "rect": {"row": 4, "col": 13, "rows": 3, "cols": 6},
      "binding": {"atom": "Simulation_SPICE:OPAMP", "value": "", "rot": 0, "mirror": "x"},
      "attachments": {
        "N": [{"pos": 13, "net": "VEE", "pin": "4"}],
        "E": [{"pos": 5, "net": "E0", "pin": "5"}],
        "S": [{"pos": 13, "net": "VCC", "pin": "3"}],
        "W": [{"pos": 4, "net": "N1", "pin": "2"},
              {"pos": 6, "net": "GND", "label": "+", "pin": "1"}]
      }
    },
    "FB": {
      "rect": {"row": 0, "col": 13, "rows": 1, "cols": 2},
      "binding": {"block": "Parallel", "rot": 0, "mirror": null},
      "attachments": {"E": [{"pos": 0, "net": "E0", "pin": "E0"}],
                      "W": [{"pos": 0, "net": "N1", "pin": "W0"}]}
    }
  },
  "unbound": [],
  "ports": [{"side": "E", "index": 0, "dip": 1, "aliases": [], "net": "E0"},
            {"side": "W", "index": 0, "dip": 0, "aliases": [], "net": "W0"}],
  "nets": {
    "N1":  {"pins": ["FB.W0", "IN.E0", "U1.2"], "ports": [], "labels": []},
    "VEE": {"pins": ["U1.4"], "ports": [], "labels": [{"text": "VEE", "row": 2, "col": 11}]}
  },
  "blocks": {"Series": {"...": "..."}, "Parallel": {"...": "..."}}
}
```

- `pos` is the canvas row (W/E) or column (N/S) where the wire meets the component.
- `pin` is the atom's pin number or the sub-block's port name (its first alias, else its
  default name).
- Nets are **local**: sub-blocks are opaque, and their ports appear as `FB.W0`.
  `yasdl.netlist()` gives the flattened view.
- The source layer alone is enough to rebuild everything; the rest is a parsed view, for
  tools and debugging. (Open: should JSON be an input format too?)

## 6. Export

### 6.1 KiCad output

- One flat sheet on the smallest landscape ISO page from A4 through A0 that contains the
  complete drawing and port-label margin. Symbols are copied from KiCad 9's libraries into
  `lib_symbols`. References are annotated (`R1`, `Q2`, `#PWR001`), and each symbol carries a
  `yasdl_path` field with its hierarchical name (`FB.R1`).
- `to_kicad(..., references="names")` (also `render`) uses each component's yasdl name as its
  reference (`RI`, `Rint1`) instead of annotating `R1`, `R2`; when names repeat across
  sub-blocks it uses the flattened path (`A_RI`). `values=False` hides value fields (they stay
  in the file and the SPICE export), for symbolic drawings.
- Wires, junction dots, net labels, and labels for the top block's ports. Ports that alias an
  existing net name (e.g. `{VP}` connected to `[VCC]`, or two ports on one wire) retain their
  visible names as non-electrical text. Only the canonical name becomes an electrical label,
  avoiding KiCad's `multiple_net_names` warning without hiding or disabling ERC checks. The
  same holds for a child block's local label (`[bus]` drawn as `A1.bus`) whose net is joined
  through ports to a differently named net, such as a supply: the label carries the flattened
  net name and the drawn name stays beside it as text.
- **ERC-clean by construction.** Every exported schematic passes `kicad-cli sch erc` with no
  errors and no warnings. Nothing is required in the drawing; the export adds:
  - a `.kicad_pro` and a `sym-lib-table` next to the schematic, so the symbol libraries are
    found;
  - a **test point** (`Connector:TestPoint`, hidden fields, excluded from BOM and
    simulation) at each open port of the top block, so an interface net isn't a
    "label on a single pin";
  - a test point on each net label (`[Vref]`, `[x]`) whose net reaches a single pin, e.g. a
    block rendered on its own before its parent supplies the rest of a shared rail; KiCad
    would report `label_dangling`. The body points away from the label's wire;
  - a **power flag** (`power:PWR_FLAG`, hidden) on every net that has power-input pins but no
    power output, e.g. GND, VCC, VEE. It goes on a power symbol, else a global label, else a
    power pin, turned across the wire. Nets for this are rebuilt from the geometry, as KiCad
    does.

  `to_kicad(..., erc_helpers=False)` leaves them out. Helpers never appear in the round-trip
  comparison or in SPICE output.
- **Round-trip check.** `kicad-cli sch export netlist` on the generated file must reproduce
  `yasdl.netlist()` exactly, compared as sets of pins per net with power symbols excluded.
  Global nets (supplies, ground, global labels) must also keep their names: the same pin
  groups on a renamed supply fail. A rendering only counts if it passes.
- `kicad-cli sch export svg`, cropped to the drawing.
- `render(block, out_dir, export_name="DarlN")` chooses the file stem of the schematic,
  project and SVG; the default is `block.name`. The stem must be a plain file name (no
  directory parts, `..` or backslashes), else `ValueError`. The block, its bindings and its circuit are
  unchanged, so two bindings of one template render side by side:
  `render(upper, "out", export_name="DarlN")`, `render(lower, "out", export_name="DarlP")`.
- Footprint and Datasheet fields come from the atom (`Atom(..., footprint=, datasheet=)`, or
  a part descriptor, 6.3). Generic symbols have none, and the fields stay empty.
- `Atom(..., sim=False)`: a physical part with no simulation model (connector, jack,
  speaker terminal, mounting hole). It keeps its schematic symbol, connections, ERC and BOM
  membership, and is excluded from simulation (`exclude_from_sim`), from `spice_netlist` and
  from the SPICE comparison.

**KiCad installation.** `YASDL_KICAD` names a KiCad installation root. Without it, yasdl
uses the first of `~/KiCad9`, `/Applications/KiCad`, `/Applications/KiCad/KiCad.app`,
`/Applications/KiCad.app`, `/usr`, `/usr/local`, `/opt/kicad` and the prefix of a
`kicad-cli` found on `PATH` that has `kicad-cli` or the symbol libraries
(`kicad_lib.discover_kicad()` returns it). Prefix installations use `bin/kicad-cli` and
`share/kicad`; macOS installations may point at either the directory containing `KiCad.app`
or the app bundle. KiCad is checked when an operation needs it, never at import:
`kicad_lib.require_cli(operation)` returns the CLI and rejects one that reports a major
version other than 9.

**Dependency errors.** A missing `kicad-cli`, symbol directory, library, symbol or project
template, a failing kicad-cli run, or a missing SPICE model raises
`yasdl.kicad_lib.YasdlDependencyError` (exported as `yasdl.DependencyError`). The message
names the operation, the dependency, the resolved and searched paths and the remedy
(`YASDL_KICAD`, `spice_libs=`), and includes kicad-cli's own output. Subclasses keep the
usual exception types: a missing CLI (`KiCadNotFound`) and a missing library file
(`LibraryNotFound`) are `FileNotFoundError`s, a missing symbol (`SymbolNotFound`) is a
`KeyError`, a failing command is `KiCadCommandFailed`, and a missing model file in a SPICE
export is also a `YasdlError`. ERC that produces no report is an error, never a clean
result. With `render(..., spice=True)` every model-based part's model must be defined in its
`SpiceModel.library` or in `spice_libs`. `kicad_lib.run_cli(operation, args)` and
`run_cli(args, cwd=..., ok=(0,))` run kicad-cli with these errors.

### 6.2 SPICE export

`spice_netlist(block, subckt="name", port_order=None, includes=())` writes an ngspice netlist
from the flattened design:
- **Ports**: with `subckt`, the netlist is wrapped in `.subckt name <ports>`, ports in DIP
  order (2.7) unless `port_order` lists port names. Formal port aliases take precedence over
  internal global names in subcircuit exports: `{VP}` wired to `[VCC]` yields a `VP` pin and
  `VP` device nodes. Without `subckt`, a flat netlist is written and retains `VCC`.
  Ground remains implicit node `0`, never a subcircuit port. Two ports on one net can't both
  be subcircuit pins (ngspice silently miswires duplicate formal nodes), so that's an error.
- **Global nets in subcircuits**: ngspice makes every non-pin node of a `.subckt` local. Every
  global net the subcircuit uses that is not one of its pins (`[VCC]` with no `{vp}` port,
  also inside nested blocks) is declared with a `.global` card before the `.subckt`, so a
  testbench's `VCC` source reaches it. Ground is node `0` and needs none; flat netlists need
  none.
- **Nodes**: global nets keep their names exactly, including registered supplies such as
  `+12V` and `-12V`, so a testbench source of that name reaches them; `GND` becomes node `0`.
  Ports use their aliases; other nets are `n1`, `n2`, ... (sanitised, unique without case).
- **Values: USE MEG FOR MEGA; USE lowercase m FOR MILLI.** KiCad reads `1M` as mega, ngspice
  as milli; KiCad reads `4k7`/`2R2` as 4.7k/2.2, ngspice as 4k/2 (it ignores everything after
  the scale factor). Direct `spice_netlist` generation rejects R/C/L values that the two read differently. Rendering preserves the supplied value and reports the SPICE mismatch instead of rewriting it: write `1Meg`, `1m`, `4.7k`, `2.2`. Values both read alike
  (`100nF`, `2.2u`, expressions such as `{RVAL}`) pass through unchanged.
- **Elements**: each atom becomes one element named `<letter>_<path>` (`C_PS_C1`), through a
  `SpiceModel(prefix, pins, model, sim_pins, library, params)`: `prefix` is one of
  `R C L D Q M X V I`, `pins` lists symbol pin numbers in SPICE terminal order (nonempty,
  distinct), `params` is X-only and single-line. Two paths that sanitise to one element name
  (`A.B1` and `A_B1`) are an error. Defaults exist for
  `Device:R/C/L/D/Q_NPN/Q_PNP`. Model-based parts take the model name from the value
  (`NPN("2N3904")`). Other symbols need `Atom(..., spice=SpiceModel(...))`, or export fails
  with an error. Power symbols are global nets, not elements; `sim=False` parts and `NC()`
  markers are left out.
- **Instance parameters**: `SpiceModel(..., params="R=100k POS=0.25")` appends the
  parameters to the element line and writes them to KiCad's `Sim.Params`, so one subcircuit
  serves differently set instances (`POT()` below).
- **Bundled library** `yasdl` (`yasdl/lib/yasdl.kicad_sym`, models in `yasdl/lib/yasdl.lib`)
  holds symbols KiCad lacks. `OPAMP_IDEAL()` is `yasdl:OPAMP_IDEAL`: the op-amp triangle with
  only `+` (pin 1, above), `-` (pin 2) and the output (pin 3), no supply pins, so it needs no
  rail wires. It simulates as `yasdl_ideal_opamp`, a behavioural source
  `V(out) = 1e9 * (V(+) - V(-))`. `yasdl_ideal_opamp5` is the same with supply pins (linear,
  not clamped to the rails). `yasdl_dual_opamp` is a generic bounded dual (gain 1e6, output
  0.1 V inside the rails) used as the default whole-package model of `Package` (6.3). A
  `SpiceModel` may name its `library`; relative references can be emitted before the file
  exists, while rendering requires the resource. An absolute library or `includes=` path that
  does not exist is an error naming it. `spice_netlist` `.include`s each such library once
  (quoted when the path has spaces), and the KiCad export puts it in `Sim.Library`.
- **Sources**: `V(spec)` (`Simulation_SPICE:VDC`, `+` on pin 1, on top) and `I(spec)`
  (`Simulation_SPICE:IDC`) export as `V`/`I` elements whose value is the complete SPICE source
  specification (`"dc 0 ac 1 sin(0 1 1k)"`, `"pulse(...)"`). SPICE current flows from pin 1
  through the source to pin 2, i.e. out of pin 2, which carries the arrow `v`. In KiCad they
  carry a raw SPICE model (`Sim.Device=SPICE`, `Sim.Params type="V" model="<spec>"`), so
  kicad-cli exports the specification verbatim (its VDC default would write `DC dc 0 ac 1`).
- **Potentiometer**: `POT(value="10k", position=0.5, taper="lin")` is
  `Device:R_Potentiometer` with role aliases: pin 1 = `{ccw}` end (top in the library),
  pin 2 = wiper `{w}`/`{wiper}` (right), pin 3 = `{cw}` end (bottom), following the usual
  potentiometer terminal convention (clockwise rotation moves the wiper toward terminal 3).
  `position` is the shaft rotation from fully counterclockwise (0: wiper at ccw) to fully
  clockwise (1: wiper at cw). `taper`: `"lin"` (F = position), `"log"` (audio "A" taper,
  F = (81^position - 1)/80, 10 % at mid rotation) or `"rlog"` (reverse log, "C"), where F is
  the fraction of `value` between ccw and the wiper. A volume control takes its input on `cw`
  and grounds `ccw`, so clockwise is louder. It simulates as the bundled `yasdl_pot` with
  instance parameters `R=<value> POS=<position> TAPER=<0|1|2>`; each pot keeps its own
  setting through the round trip. `rotation=` is an equivalent shaft-position keyword; it
  precomputes the taper into POS, leaving TAPER at its default zero.
  `pot_position(rotation, taper)` returns that electrical fraction.
  `Pot(resistance="10k", *, position=0.5, taper="linear")` is the keyword form with the same
  pins and model; a linear setting is written as the electrical fraction `R=<value> P=<f>`
  (`log`/`rlog` emit POS/TAPER as POT does). Values must be positive SPICE numbers (use MEG),
  positions finite in 0..1. Each pot section has 1 µΩ in series so the ends stay finite. A
  real pot's lead numbering still needs checking against its datasheet.
- **KiCad simulation fields**: `to_kicad(..., spice_libs=(paths,))` adds `Sim.Library`,
  `Sim.Name`, `Sim.Pins` (and `Sim.Params`) to model-based parts whose model is defined in one
  of the libraries. `kicad-cli sch export netlist --format spice` then works on the schematic.
  ERC helpers are excluded from simulation.
- **SPICE parser**: `parse_spice(text)` reads the top-level R/C/L/D/Q/M, V/I and X elements
  as `(name, nodes, value)`, skipping comments, dot cards and subcircuit bodies;
  `parse_spice(text, "name")` reads that subcircuit body instead. Continuation lines are
  joined. Element kinds yasdl never exports (E, B, J, ...), duplicate names, malformed
  instances, a stray continuation and unbalanced `.subckt`/`.ends` are errors, so nothing
  escapes a comparison unnoticed. `spice.compare_spice(a, b, rename_a, rename_b, named=())`
  compares two texts and returns `(ok, difference)`; `compare_spice(partition_a,
  partition_b)` returns a list of differences.
- **SPICE round trip**: `render(..., spice=True)` compares KiCad's SPICE export of the
  schematic with yasdl's own netlist; `kicad_export.compare_spice(block, kicad_text,
  refmap)` compares any KiCad export text (e.g. a deliberately mutated one) the same way and
  returns `(ok, difference)`. Every top-level element must be present on both sides: an
  added KiCad element that belongs to no yasdl part fails, as does a deck the parser rejects
  or a KiCad export that fails (for example a model KiCad cannot load). Elements are compared
  by identity (the reference map; kicad-cli's `XU1` for a subcircuit reference `U1` maps
  back), terminal connectivity, the identity of ground and of every user-named net (globals,
  top-level ports and labels; compared without case, as ngspice does; KiCad's root-sheet
  prefix `/` is ignored), and value: the R/C/L number as ngspice reads it, the complete
  source specification, or the model with its instance parameters. `info["spice_diff"]`
  names missing/extra elements, differing values and differing nets.
  Scope and limits: parameter text is compared after case/whitespace normalisation, so
  reordered parameters compare unequal; `.param`, `.model`/`.subckt` definitions and
  `.include`s are not compared (`R={BASE}` with a changed `.param BASE` is not detected);
  equivalent spellings such as `DC 1` and `DC 1.0` compare unequal. This checks that the two
  exports describe the same circuit. It does not show that the circuit is the intended one,
  is biased correctly, or uses an accurate model.
- **Simulation results: NGSPICE EXIT CODE 0 DOES NOT GUARANTEE SUCCESSFUL ANALYSES OR
  MEASUREMENTS.** ngspice can exit 0 after a failed operating point or with a `.meas` whose
  window lies outside the simulated interval. Check the log and every requested measurement
  value before claiming a result. Testbenches (supplies, stimuli, loads, analyses and
  measurements) belong to the design task; yasdl does not provide one.

`yasdl/lib/jellybean.lib` bundles reusable 2N3904, 2N3906 and 1N4148 SPICE models;
`yasdl.kicad_lib.JELLYBEAN_MODEL` gives its path. The sine-generator example uses this library
for simulation. `tests/test_sine_generator.py` compares the generated netlist against
`tests/test_sine_generator.lib` and simulates both netlists. These fixtures are checked in;
the tests skip only when KiCad or ngspice is unavailable.

**Example: `docs/examples/sgen.py`**, a 2 kHz RC phase-shift oscillator plus
emitter-follower buffer, composed from small blocks:
- `PHASE_SHIFT`: the 3-section RC ladder;
- `OSCILLATOR`: the Q1 gain stage with the ladder as feedback;
- `OUTPUT_AMP`: from the coupling capacitor CK on, the Q2 emitter follower and AC-coupled
  output;
- `SGEN`: a 7-line top level wiring OSC → AMP, with the `{vp}` supply on top and `{vm}` at the
  bottom. The supply/output pin order (V+, V−, OUT) is given as `port_order=SGEN_PINS`.

Each canvas is small and stands alone (each renders ERC-clean); yasdl composes the final
planar schematic. Grounds are `[GND]` labels. The ladder's input is declared `{in, >}` and
drawn as `PS<` in the oscillator: the arrow puts its input on the right. Of the two fits (180°,
left/right mirror), the mirror flips fewer axes (3.2), so the shunt legs keep hanging down.
Both transistors label `{b}` and `{e}` explicitly, fixing their base/emitter connections
and preventing a top/bottom mirror from swapping collector and emitter.
The generated `.subckt sgen vp vm out` is structurally identical to the fixed test netlist.
In ngspice, both the yasdl netlist and KiCad's export of the generated schematic oscillate
at about 1967 Hz, matching the test circuit.

![sine generator](examples/generated/SGen.png)

### 6.3 Parts and packages (`yasdl.parts`)

Parts are built on KiCad's **generic** shapes with an explicit role -> physical pin map,
instead of loading device-specific symbols:

| Factory | Generic shape | Roles |
|---|---|---|
| `AtomNPN(name, pins, library=None, model=None, *, model_name=, footprint=, datasheet=, value=)` | `Device:Q_NPN` | `C B E` |
| `AtomPNP(...)` | `Device:Q_PNP` | `C B E` |
| `AtomDiode(name, pins={"K": 1, "A": 2}, library=None, model=None, ...)` | `Device:D` | `K A` |
| `AtomOpamp5(name, pins, library=None, model_name=None, model_order=None, *, model=, model_pins=, spice=, footprint=, datasheet=)` | `Simulation_SPICE:OPAMP` | `+ - out V+ V-` |
| `AtomOpamp3(name, pins, library=None, model_name=None, model_order=None, *, model=, model_pins=, spice=, ...)` | `yasdl:OPAMP_IDEAL` | `+ - out` |
| `OpampPackage(name, units, power, model=, library=, model_pins=, scope=)` | `Device:Opamp_Dual` (2 units) / `Device:Opamp_Quad` (4) | per unit `+ - out`; power `V+ V-` |

```python
q = AtomNPN("BD139", {"E": 1, "B": 3, "C": 2}, models, "BD139",
            footprint="Package_TO_SOT_THT:TO-126-3_Vertical", datasheet=url)
op = AtomOpamp5("TL071", {"inp": 3, "inn": 2, "out": 6, "V+": 7, "V-": 4},
                models, "TL071")             # model terminals in the order + - V+ V- out
```

- The map must name every role exactly once with distinct physical pins (positive numbers,
  or grid names such as `A1`). Role keys are case-insensitive; op-amp roles also accept
  `inp`, `inn`, `vp`, `vm`. Naming a role twice (`vp` and `V+`), a missing or unknown role,
  or a shared physical pin is an error.
- The factory derives an immutable definition `yasdl_parts:<name>`: the generic geometry and
  pin names with the physical numbers. Canvas labels keep using roles (`{b}`, `{e}`, `+`,
  `{out}`, `{V+}`, `{inp}`, `{vp}`; case-insensitive). The same map drives the KiCad pin
  numbers, arrows, the SPICE node order (`C B E` for a `Q` element, the model order for an
  `X`) and `Sim.Pins`. Registering a name again with a different pinout is an error; the
  generic base is never modified, cached KiCad symbols are read-only, and a derived
  definition's `symbol.sexp` is a fresh copy. The schematic embeds exactly the derived
  definitions it uses and writes them to a project-local `yasdl_parts.kicad_sym`
  (referenced through `${KIPRJMOD}`, merged with other renders in the same directory; a
  conflicting definition there is an error). Atom alias and arrow maps are read-only.
- **Metadata.** `footprint`/`datasheet` are the part's KiCad Footprint/Datasheet fields,
  written on every placed instance. Generic shapes carry none, so they stay empty unless
  supplied; descriptors that differ only in metadata share one symbol definition.
- **SPICE terminal order** is separate from the package pins. BJTs are always C, B, E.
  Op-amps take either `spice=SpiceModel("X", physical pins in model order, ...)` or
  `library` + `model_name` (alias `model`) with `model_order` (alias `model_pins`) listing
  the roles, or physical pins, in subcircuit terminal order; giving both forms is an error.
  When the library exists, `Sim.Pins` uses the subcircuit's node names, else terminal
  positions. Calling a descriptor (`Q2N3904()`, `BD139(model="2N3904")`) returns an
  instance, optionally with another value, model or library.
- **yasdl can't verify a pin map against a datasheet.** Neither can SPICE: a BJT `.model` has
  no lead numbers, so two wrong pinouts can give byte-identical decks
  (`Q_Q1 collector base emitter 2N3904`). Verify each descriptor against the datasheet or
  KiCad's symbol for the exact device and package, then reuse it. Verified standard
  descriptors: `Q2N3904`, `Q2N3906` (TO-92: 1 E, 2 B, 3 C; models in `jellybean.lib`),
  `BD139`, `BD140` (TO-126: 1 E, 2 C, 3 B; no bundled model), `D1N4148` (1 K, 2 A) and the
  DIP-8 dual op-amp pinout (A: out 1, - 2, + 3; B: + 5, - 6, out 7; V- 4, V+ 8; TL072,
  NE5532, LM358). `transistor("2N3904")` returns a standard transistor by name.
  `tests/test_parts.py` and `tests/test_enhancements.py` check the maps against the exact
  installed KiCad device symbols and datasheet tables, never against the factories.
- **Packages.** A `Package` is one physical device whose unit views bind separately:
  - `Package(descriptor, "U1")` or `descriptor(name="U1")` with an `OpampPackage` (2 or 4
    channels on the generic dual/quad shape) or a `PackageType` (an installed multi-unit
    root symbol, `Package("Library:Symbol")`, with a complete whole-device X mapping or
    `sim=False`). An omitted name uses the first placed unit path.
    `chip.unit("A")`, `chip.unit("B")`, ... are amplifier views (+ above -, output E) that
    fit any three-terminal op-amp hole; `chip.power()` is the supply unit (V+ on top, V-
    below). A `PackageType`'s unit views also accept integer unit numbers, case-insensitive
    letters and the power unit's letter.
  - `Package("TL072")`, `Package("LM358")`, `Package()` (LM358) or
    `Package(name, units={"A": {...}, "B": {...}}, power={"V+": .., "V-": ..})` describe a
    dual op-amp by role maps: views `A`, `B` and `C` (power; also `chip.power()`). LM358 and
    TL072 default to the DIP-8 map above (checked against the exact KiCad symbols); other
    devices need explicit maps. The whole-device model is `spice=SpiceModel("X", every
    physical pin in model order, ...)`, or `library` + `model_name` (+ `model_order`,
    physical pins; default A + - out, B + - out, V+, V-), or else the bundled generic
    `yasdl_dual_opamp`, a bounded behavioural model and **not** a vendor model. Each view's
    `.spice` shows that whole-device mapping. `AtomOpampPackage(name, units=, power=,
    spice=)` is the same constructor.
  - Caller maps are copied; a package is immutable once made. Every unit, including the
    power unit, must be bound exactly once in the design (KiCad reports unplaced units;
    terminate an unused amplifier, e.g. as a grounded follower, and use a second `Package`
    for a Block placed twice). Units may sit in different blocks. All units share one
    reference (`U1A`, `U1B`, `U1C`), footprint and BOM line, and keep `(reference, unit,
    physical pin)` through annotation and the round trips. Two packages may not share a name.
- **Package SPICE.** kicad-cli exports one element per reference, so a package simulates as
  one element over all its physical pins. With `scope="unit"` (default) `model` is a
  single-amplifier subcircuit whose nodes are `model_pins` (roles); yasdl generates
  `yasdl_pkg_<name>`, one instance per unit, inline in `spice_netlist` and in
  `yasdl_packages.lib` next to the schematic for KiCad. With `scope="package"` `model` is a
  whole-device subcircuit whose nodes are the physical pins listed in `model_pins`.
  `dual_opamp(name, model, library, model_pins=("A.out", "A.-", "A.+", "V-", "B.+", "B.-",
  "B.out", "V+"))` accepts a whole-package role order. `IDEAL_DUAL` uses the bundled
  `yasdl_ideal_opamp5`. Model libraries may also be supplied at render time (`spice_libs`).

### 6.4 Standard Blocks (`yasdl.std`)

Reusable sub-circuits with consistent interfaces, built from functions over literal canvases:

| Block | Interface |
|---|---|
| `powered(opamp5)` | `{inp,+}` W top, `{inn}` W bottom, `{out}` E; V+ on `[VCC]`, V- on `[VEE]` inside (3.2) |
| `follower(U)`, `noninverting(rf, rg, U)`, `inverting(ri, rf, U)` | `{in}` W, `{out}` E; `U` defaults to `OPAMP_IDEAL()` |
| `rc_lowpass(r, c)`, `rc_highpass(c, r)` | `{in}` W, `{out}` E, ground inside |
| `sallen_key_lowpass(r1, r2, c_shunt, c_feedback, U)`, `sallen_key_highpass(c1, c2, r_shunt, r_feedback, U)` | unity gain; `{in}` W, `{out}` E |
| `darlington(q1, q2)`, `sziklai(driver, output)`, `parallel(q, n, re)` | `{c}` N, `{b}` W, `{e}` S, like a transistor |
| `diode_string(n, d)`, `vbe_multiplier(q, r1, r2)` | `{a}` N, `{k}` S |
| `mirror(q)`, `wilson(q)` | `{in}` N left, `{out}` N right, `{com}` S |
| `diff_pair(q, rc, tail)` | `{o1} {vp} {o2}` N, `{inp}` W, `{inn}` E, `{vn}` S |
| `diff_active(q, load, tail)` | `{vp}` N, `{inp}` W, `{out}` and `{inn}` E, `{vn}` S |
| `push_pull_buffer(kind, upper, lower, rt=, rb=, rq=, re=)` / `push_pull_vas(kind, npn, pnp, rb=, re=, qn=, qp=, bias=)` | `{vp}` N, `{in}` W, `{out}` E, `{vn}` S |

Uppercase templates (`INVERTING`, `NONINVERTING`, `FOLLOWER`, `OPAMP_UNUSED`, `SALLEN_KEY`,
`RC_LOWPASS`, `RC_HIGHPASS`, `DARLINGTON`, `SZIKLAI`, `PUSH_PULL_VAS`, `PUSH_PULL_BUFFER[n]`)
expose the literal canvases for `.bind(...)` and inspection.

- Compound devices have collector, base and emitter roles. Darlington and Sziklai pairs
  include a base-emitter shunt resistor (`rx`, default 1k). The VAS stage's internally
  constructed compound devices use the compact circuit without that shunt.
- `diode_string(n)` repeats one literal diode cell per diode; `parallel(q, n)` (2–9
  devices) repeats one literal 8-column strip per device, the base bus crossing n−1 emitter
  legs (deliberate crossings, 7).
- Sallen-Key arguments name the shunt to ground before the feedback from the series
  junction to the output. For a unity-gain Butterworth low-pass with equal R, choose
  C_feedback = 2 C_shunt. For an equal-C high-pass, R_shunt = 2 R_feedback.
- `push_pull_buffer` places `{in}` at the center of the bias string and feeds both ends
  from the rails. `rt`/`rb` feed it; `rq` trims its bias. Diodes per side: bjt 1,
  Darlington 2, Sziklai 1. Its upper/lower arguments are already composed output devices.
- `push_pull_vas` places `{in}` at the bottom of the string (for a VAS collector) and
  feeds it through `rb` from `{vp}`. It constructs the chosen compound output devices,
  or accepts explicit `qn`/`qp`. Its total diode count is 2/4/2; `bias` replaces the string.
  `vbe_multiplier` provides V(a,k) = Vbe (1 + R1/R2), with R1 collector-base and R2 base-emitter.
- `push_pull` accepts both forms: `qn`/`qp`/`bias`, or `rb` without `rt`/`rq`, select the
  VAS form; otherwise it selects the center-driven form. Prefer the explicit entry points.
- `mirror(q)` is the plain mirror with `{com}` (also aliased `{vn}`); `mirror(q, kind="npn"|"pnp")`
  adds emitter degeneration and selects the corresponding rail. `wilson` is the plain
  Wilson; `wilson_mirror(q, kind=)` provides the polarity-specific version. `diff_pair(q, rc, tail)`
  takes any two-terminal tail; `diff_pair(q, kind=, rc=, re=, rt=)` uses a resistor tail and
  degeneration. `diff_pair_mirror` contains its own complementary mirror load.
- `tests/test_std.py` renders every block through KiCad and characterises it in ngspice:
  op-amp gains, filter corners, mirror ratios, differential gain, and for each push-pull
  variant the open-loop distortion with the matching bias string against one that is short
  by a stage.

### 6.5 Reusable circuits (`yasdl.circuits`, `yasdl.standard`)

`yasdl.circuits` holds small standard Blocks, each a literal canvas configured by keyword.
Compound devices share the roles c (N), b (W), e (S), so they fit wherever a transistor is
drawn; op-amp circuits take any three-terminal op-amp (`opamp=`, default `OPAMP_IDEAL()`).
Supplies are the global `VCC`/`VEE`, ground `GND`. Values are starting points; characterize
each stage with the intended supplies, load and models.

| Block | Ports | Notes |
|---|---|---|
| `Darlington(pnp=False, output=None, turnoff="220")` | c, b, e | two Vbe; `turnoff=None` omits RD; `output` replaces the output transistor |
| `Sziklai(pnp=False, output=None, turnoff="1k")` | c, b, e | complementary feedback pair, one Vbe; output device of opposite polarity |
| `BallastedDevice(pnp=False, resistance="1")` | c, b, e | transistor with emitter ballast |
| `ParallelDevices(device)` | c, b, e | two devices in parallel, one deliberate crossing; nest for 4, 8 |
| `DiodeString(count)` | a, k | series 1N4148s (one literal cell per diode) |
| `PushPull(variant="bjt", ballast="1", parallel=1)` | hi, lo, out | output stage driven at both ends of its bias string |
| `BiasString(count, resistance)` | in, upper, lower | resistor-fed diode bias |
| `FollowerPushPull(variant="bjt", ballast="1", bias_resistance="4.7k")` | in, out | self-biased unity-gain buffer |
| `CurrentMirror(pnp=False, degeneration=None, rail=None)` | ref, out, common | `rail="VEE"` puts the emitters on a global net instead of `common` |
| `CurrentSink(resistance="150")` | c, e | diode-referenced sink |
| `DifferentialPair(tail="resistor", degeneration="100")` | inp, inn, left, right | degenerated pair, resistor or active (`CurrentSink`) tail |
| `LongTailedPair(degeneration=None, tail="4.7k", collector="10k")` | inp, inn, outp, outn | resistor-loaded long-tailed pair |
| `LowPass`, `HighPass`, `BandPass` | in, out | RC sections |
| `SallenKey(resistance, capacitance, opamp=None)` | in, out | unity-gain low-pass |
| `PoweredOpamp(atom, positive="VCC", negative="VEE")` | inp (`+`), inn, out | five-pin op-amp with internal supply wiring |
| `Follower`, `NonInverting`, `Inverting`, `Integrator`, `Differentiator` | in, out | op-amp circuits |

- `variant` is `"bjt"`, `"darlington"` or `"sziklai"`. The complementary halves and their
  bias are designed together, not mirrored: Darlington outputs need two diode drops per half
  (four in `PushPull`), BJT and Sziklai outputs one, and a Sziklai's output device has the
  opposite polarity of its driver. `PushPull` takes its bias current from the enclosing
  driver; `FollowerPushPull` feeds it from the rails.
- With `degeneration=None`, mirrors and pairs have direct emitter wires: a different drawing,
  not a zero-ohm resistor.
- Practical integrators need DC feedback; filters are loaded by what they drive.

`yasdl.standard` provides positional, lowercase entry points to the same Blocks:
`darlington(pnp)` (plain, `turnoff=None`), `sziklai(pnp)`, `diode_string(count)`,
`bias_string(count, resistance)`, `push_pull(variant, ballast, bias_resistance)`
(`FollowerPushPull`), `powered_opamp(atom)`, `follower(opamp)`, `inverting(ri, rf, opamp)`,
`noninverting(rg, rf, opamp)`, `integrator(ri, cf, opamp)`, `rc_filter(kind, r, c)`,
`sallen_key(r, c, opamp)`, `current_mirror(degeneration)` (emitters on `VEE`) and
`differential_pair(degeneration, tail, collector)` (`LongTailedPair`). Note that
`yasdl.std` and `yasdl.standard` are separate families: `std.noninverting(rf, rg, U)` and
`standard.noninverting(rg, rf, opamp)` take their resistors in different orders, and
`std.push_pull` builds a driven stage while `standard.push_pull` builds a self-biased
follower. `docs/examples/standard.py` renders every circuit.

**Every standard topology is a literal ASCII canvas in the library source** (`std.py`,
`circuits.py`); parameterized families repeat small literal cells or strips. `Sketch`
(7) remains available for building new canvases.

### 6.6 Portable projects

`render`/`to_kicad(..., bundle_models=True)` (the default) copies every SPICE model library
the schematic references, with every file it reaches through `.include`/`.inc`, into
`<dir>/spice_models/` and writes project-relative `Sim.Library` paths
(`spice_models/jellybean.lib`). Include lines in the copies are rewritten to the copied
names. A copy keeps its file name unless the directory already holds a different file of
that name, which then gets a content-digest suffix, so equal parent files that include
different children stay distinct. A missing file raises `FileNotFoundError` naming it; an
include cycle raises `ValueError`. `resources.copy_model_resource(source, directory)` and
`spice.portable_model_library(source, directory)` expose the copier. Package wrappers
include the copies; yasdl's bundled symbol library is copied next to the schematic and
listed as `${KIPRJMOD}/yasdl.kicad_sym`. Relative model paths also resolve for a schematic
exported without its `.kicad_pro` (for example a renamed copy). A moved project still passes
ERC and exports SPICE. KiCad's own symbol libraries remain an installation dependency,
resolved where the project is opened. `bundle_models=False` keeps absolute paths.

## 7. Tooling

- The KiCad S-expression reader (`yasdl.sexp.parse`) raises `ValueError` with an
  unexpected-end message for empty input or an unterminated list, quoted string,
  or escape.
- `Sketch`: build canvases by coordinates instead of typing them by hand: `text`, `box`,
  `hline`, `vline`, `wire(points)`, `junction`, `render`. Methods return the Sketch.
  Every operation is validated as a whole before anything is written, and a failed
  operation (`SketchError`, a `ValueError`) leaves the canvas unchanged:
  - coordinates are nonnegative integers; text is one line; a box needs an alphanumeric
    name and a positive row count;
  - no overwriting: text, labels, components, wires, elbows, tees, junctions and crossings
    are never painted over, not even with the same glyph; spaces in `text` are transparent;
  - the one permitted overlap is a **clean 90-degree crossing**: a straight wire across a
    straight perpendicular wire, both continuing through the cell. The existing glyph stays
    on top and the nets stay separate. Each operation declares how many crossings it creates
    with `cross=N` (default 0); any other count is an error ("expected cross=N, found K")
    listing where they are. `sketch.crossing_count` is the running total;
    `sketch.crossings` is an immutable set of crossing coordinates (integer equality
    compares its count);
  - `wire([(r0, c0), (r1, c1), ...])` draws orthogonal segments with the corner glyphs
    generated, planned as one route (it may not reverse or revisit an end). A free end
    continues straight. An end point may anchor on a label, port or component cell, or on a
    junction arm pointing into the route; the anchor isn't drawn, the route attaches to it
    (`wire([(4, 18), (4, 17), (7, 17)])` from a `{b}` at (4, 18) draws `┌` at (4, 17));
  - a wire may not end against the side of another wire (an implied T). Junctions are
    explicit: leave the cell empty and call `junction(r, c)`, which picks `├ ┤ ┬ ┴ ┼` from
    the wires pointing at it, or `junction(r, c, "NES")` to declare its arms before the
    wires (or place the glyph with `text`).
  Errors name the operation, the collision cell, its content and the attempted drawing.
- **Crossing count.** `Block.crossing_count` is the block's own deliberate crossings plus,
  recursively, those of every child instance (an `int`; calling it returns the same
  number). Composition adds no crossings: the laid-out drawing has exactly this many wire
  crossings, with repeated, rotated or mirrored children.
- **Diagnostics**: canvas errors give the block, the canvas row/column (0-based, after
  removing leading blank lines and common indentation), the line and column within the
  canvas string, the original source `line:column`, the indentation offset, and an excerpt
  with a caret. A non-rectangular component lists each row's extent. Binding errors list the
  drawn attachments and their pin labels, then every orientation with the right pin counts,
  its candidate pins per side and the label it contradicts. A missing binding whose name has
  a shorter minimal period (`RR` reduces to `R`) says so. Keep authored canvases compact and
  scale through composition; rulers are never part of the art.
- `Block.to_dict()` lists each distinct sub-block definition once under `blocks`;
  differently bound blocks that share a name get keys `Name`, `Name_2`, ...
- **Agent skill** `skills/yasdl-circuit-design/SKILL.md`: the workflow, canvas cheat sheet,
  layout style guide and error fixes for EE-assistant agents.

## 8. Current constraints

- Output is a flat KiCad sheet; hierarchical sheets are not generated. Every unit of a
  physical package must be placed once; a block holding only part of a package is checked
  in the complete containing design.
- Op-amp packages support two or four channels with a separate power unit.
- KiCad symbols with `(extends)` need their root symbol or a generic factory.
- Bus syntax is specified in section 2.6; bus parsing/export is unavailable.
- Reference/value text spacing and overlap avoidance are approximate. Label widths are
  estimated from character counts. Inspect generated diagrams for readability.
- SPICE export comparison validates preserved descriptions; it does not compare `.param`
  values, model bodies or equivalent expressions. Simulation and measurements remain
  circuit-specific; no simulation runs automatically. Models do not establish physical lead
  numbers or ratings.

See [API.md](API.md) for the callable interfaces and parameter conventions.
