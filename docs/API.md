# Python API

Python 3.12 or later is required. Library code uses stdlib only. KiCad 9 with standard
symbol libraries is needed when binding standard parts and exporting schematics;
ngspice is needed for simulations. `YASDL_KICAD` selects a KiCad installation root.

## Drawings and binding

`Block(name, canvas, port_attrs=None, **bindings)` parses a rectangular ASCII drawing.
Bindings are `Atom`, child `Block`, package-unit views or `NC()`. `block.bind(**more)`
returns a bound copy; `block.port(alias)` resolves ports and aliases. `.rotated(degrees)`
and `.mirrored(axis)` constrain orientation. Pin labels constrain every candidate
orientation. `netlist(block)` returns `{net: ["instance.path.pin", ...]}`;
`block.to_dict()` exposes bindings, resolved pin maps and hierarchy.
`block.renamed(name)` preserves the circuit, aliases and physical unit membership.

`Atom(lib_id, value="", ..., spice=None, sim=True, footprint="", datasheet="", unit=1)`
describes one symbol. `sim=False` preserves its physical schematic/BOM/netlist membership
and excludes simulation. A reusable descriptor is callable to make an instance, with
optional `value`, `model` and `library` overrides. `R/C/L`, `D/NPN/PNP`, `V/I`,
`C_POL`, `GND/VCC/VEE` are standard convenience constructors.

`NC()` is an independent marker for every attachment to its rectangle. Each marked net
must reach one device pin and no other marker, global, external port or local label.
Composed markers preserve wires and isolated model terminals.

## Sketch

`Sketch().text(row,col,text).box(row,col,name,rows=1)` places text/components.
`hline(row,c0,c1,ch="─",cross=0)` and `vline(col,r0,r1,ch="│",cross=0)` draw straight wires.
`wire([(row,col),...],cross=0)` draws a complete orthogonal route and generates elbows.
`junction(row,col)` infers arms from neighbouring wires;
`junction(row,col,"NES")` declares a three-arm junction before its connecting wires.
`.render()` returns the canvas. Operations validate before writing; failure is atomic.
Only clean perpendicular crossings are allowed, with the exact `cross` count declared.
`.crossing_count` is an integer; `.crossing_cells` is the coordinate set and `.crossings`
an immutable snapshot supporting count equality with an integer.

## Parts and packages

Generic factories live in `yasdl.parts` and are also exported at the package root:

| Constructor | Physical roles |
|---|---|
| `AtomNPN/AtomPNP(name,pins,model=None,library=None,footprint="",datasheet="",value=None)` | C, B, E; SPICE order C/B/E |
| `AtomDiode(name,pins=None,model=None,library=None,footprint="",datasheet="")` | K, A; default K1/A2 |
| `AtomOpamp5(name,pins,model=None,library=None,model_pins=("+","-","V+","V-","out"),footprint="",datasheet="")` | +, -, out, V+, V- |
| `AtomOpamp3(name,pins=None,model=None,library=None,model_pins=("+","-","out"),footprint="",datasheet="",value=None)` | +, -, out; default 1/2/3 |

Maps are complete and use distinct physical pins. BJT role keys are case insensitive.
`model_pins` separately gives the model's node order; it must list every role once.
Metadata survives export. Definitions with different physical maps need different names.
Verify numbering independently against the exact device/package datasheet or KiCad symbol.
Standard descriptors: `Q2N3904/Q2N3906`, `BD139/BD140`, `D1N4148`, `IDEAL_DUAL`.

`OpampPackage(name,units,power,model=None,library=None,model_pins=...,scope="unit",footprint="",datasheet="")`
describes two or four channels on `Device:Opamp_Dual/Quad`. `units` maps channel letters to
{+, -, out}; `power` maps {V+, V-}. `Package(descriptor,name=None)` or `descriptor(name=None)`
creates one chip. `.unit("A")`, `.unit("B")`, etc. and `.power()` bind separately.
All units must be placed once. Default names derive from the first unit path; explicit
names must be unique. `PackageType(lib_id,value="",spice=None,footprint="",datasheet="",sim=True)`
describes an installed multi-unit root symbol directly. It accepts a complete whole-device
X mapping over all physical pins, or `sim=False`. Its unit views accept letters (case
insensitive) and integer unit numbers; `.power()` finds a unique nonempty power-only unit.
`Package(lib_id,...)` is a convenient direct form. Package value, footprint, datasheet,
simulation flag and whole-device model may be overridden when instantiating a descriptor.

`dual_opamp(name,model=None,library=None,model_pins=...,datasheet="")` supplies DIP-8
numbering. With single-channel role order it generates a whole-package wrapper. A full
role order such as `("A.out","A.-","A.+","V-","B.+","B.-","B.out","V+")`
selects a whole-device model. `scope="package"` on an explicit descriptor uses physical
pin names as its model order. One chip exports one SPICE element and one physical reference.

`POT(value="10k",position=0.5,taper="lin",rotation=None)` uses pin 1 CCW, 2 wiper, 3 CW.
Position/rotation runs from 0 CCW to 1 CW. Tapers: lin, log, rlog. Log mid rotation gives
10% electrical position; reverse log gives 90%. `position` emits POS and TAPER;
`rotation` precomputes POS. `pot_position(rotation,taper)` returns the electrical fraction.

## Standard circuits

Prefer lowercase construction functions for fully bound circuits; uppercase templates
such as `INVERTING`, `NONINVERTING`, `FOLLOWER`, `OPAMP_UNUSED`, `SALLEN_KEY`,
`RC_LOWPASS/HIGHPASS`, `DARLINGTON/SZIKLAI` support `.bind(...)`.

| Function | Parameters and interface |
|---|---|
| `powered(opamp,name=None)` / `powered_opamp` | Three signal ports; supplies internally on VCC/VEE |
| `follower(U=None)`, `noninverting(rf,rg,U=None)`, `inverting(ri,rf,U=None)` | Ideal opamp by default; in/out ports |
| `rc_lowpass(r,c)`, `rc_highpass(c,r)` | Grounded first-order filters |
| `sallen_key_lowpass(r1,r2,c_shunt,c_feedback,u=None,name=None)` | Ground shunt before output feedback |
| `sallen_key_highpass(c1,c2,r_shunt,r_feedback,u=None,name=None)` | Ground shunt before output feedback |
| `darlington(q1,q2=None,rx="1k",name=None)`, `sziklai(driver,output,rx="1k",name=None)` | c/base/e compound roles; shunt resistor |
| `parallel(device,n,re="1",name=None)` | 2–9 devices with emitter ballast; n−1 declared crossings |
| `diode_string(n,diode=None,name=None)`, `vbe_multiplier(q=None,r1="2.7k",r2="1k",name="VbeMultiplier")` | a/k bias interfaces |
| `mirror(q,kind=None,re="100",name=None)`, `wilson(q,name="Wilson")`, `wilson_mirror(q,kind="npn",name=None)` | Plain or explicitly polarized mirrors |
| `diff_pair(q,rc,tail)` / `diff_pair(q,kind="npn",rc="10k",re="100",rt="10k",name=None)` | General tail or polarized resistor-tail pair |
| `diff_active(q,load,tail,name="DiffActive")`, `diff_pair_mirror(q,load,kind="npn",re="100",rt="10k",name=None)` | External or internal mirror load |
| `push_pull_buffer(variant,upper,lower,diode=None,rt=None,rb=None,rq=None,re="0.22",name=None)` | Input at bias-string center; supplied compound halves |
| `push_pull_vas(kind="bjt",npn=None,pnp=None,diode=None,rb="2.2k",re="1",qn=None,qp=None,bias=None,name=None)` | Input at string bottom; automatic or explicit halves |

`push_pull` selects the VAS form when given qn/qp/bias or rb without rt/rq; otherwise
it selects the buffer form. These drive points need different external bias arrangements.
Use the explicit functions to choose deliberately. Models and default bias values are
starting points; transistor current, dissipation and thermal coupling need circuit-specific checks.

## SPICE and KiCad exports

`SpiceModel(prefix,pins,model=None,sim_pins=None,library=None,params=None)` keeps physical
numbering separate from model terminal order. `spice_netlist(block,subckt=None,port_order=None,includes=(),title=None)`
emits a flat deck or one subcircuit, with `.global` for unported supplies and implicit node 0 ground.
Every subcircuit port must appear once and represent a distinct nonground net. Model
libraries at absolute paths must exist; relative include references may be emitted before
the file is provided. Rendering resolves required resources.

**Use MEG for mega and lowercase m for milli.** Direct SPICE generation rejects ambiguous
passive values; rendering keeps them and reports export disagreement. Complete V/I source
specifications and X instance parameters are compared. Expressions and model definitions
are compared only to the extent described in [SPEC.md](SPEC.md); general semantic
equivalence and simulation are separate responsibilities.

`parse_spice(text,subckt=None)` reads top-level elements or a named body. `spice_partition(elements,rename,named=())`
builds terminal groups and values. `compare_spice(text_a,text_b,rename_a,rename_b,named=())`
returns `(ok,diff)`; the two-partition form returns a list of differences.

`render(block,out_dir,svg=True,spice_libs=(),spice=False,references="annotate",values=True,erc_helpers=True,export_name=None,bundle_models=True)`
writes a schematic, project and optional SVG. Filename stems are independent of block identity.
The result includes `schematic`, `roundtrip_ok`, `missing`, `extra`, `erc` and optionally
`svg`, `spice_ok`, `spice_diff`. Successful ERC is `[]`; disabling helpers leaves `erc=None`.
Models are bundled by default into project-relative resources. `to_kicad` returns the
schematic path and reference map; `export_kicad_spice`, `roundtrip`, `spice_roundtrip`,
`erc` and `kicad_sch.export_netlist_full` expose individual checks. SPICE export resolves
relative models from the schematic directory, including renamed schematic copies.

**Ngspice exit code 0 does not guarantee successful analyses or measurements.** Verify
log completion, settled windows, requested finite values and physically plausible results.
