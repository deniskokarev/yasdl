"""Example blocks. `python -m docs.examples.blocks` prints netlists; see examples/render.py for KiCad."""

from yasdl import Atom, Block, GND, NC, netlist, NPN, OPAMP, POT, R, std
from yasdl.parts import D1N4148, IDEAL_DUAL, Package, Q2N3904, Q2N3906

SERIES = Block(
    "Series",
    """
    ──R1──R2──
""",
    R1=R("1k"),
    R2=R("2k"),
)

PARALLEL = Block(
    "Parallel",
    """
    ──┬──R1──┬──
      │      │
      └──R2──┘
""",
    R1=R("10k"),
    R2=R("10k"),
)

# A resistor sub-circuit bound into a component: R1 in series with the PARALLEL block.
SERIES_PARALLEL = Block(
    "SeriesParallel",
    """
    ──R1──P──
""",
    R1=R("1k"),
    P=PARALLEL,
)

# Darlington pair. Ports: C on top, B on the left, E at the bottom: the same drawn signature
# as a single NPN, so it can be bound wherever an NPN is drawn.
DARLINGTON = Block(
    "Darlington",
    """
            │
        ┌───┴───┐
        │       │
        Q1      Q2
    ────Q1   ┌──Q2
        Q1   │  Q2
        │    │  │
        └────┘  │
""",
    Q1=NPN(),
    Q2=NPN(),
)

# Inverting amplifier: IN and FB are unbound here, so they are the block's open interface.
# The '+' pin shortcut fixes the op-amp orientation (non-inverting input at the bottom),
# which mirrors the symbol and puts V- on top.
INV_AMP = Block(
    "InvAmp",
    """
              ┌──────FB───────┐
              │               │
              │    [VEE]      │
              │      │        │
    {in}──IN──┴──────U1U1U1   │
                     U1U1U1───┴──{out}
              ┌─────+U1U1U1
              │      │
            [GND]  [VCC]
""",
    U1=OPAMP(),
)

# Resistor sub-circuits bound into the amplifier's IN and FB components.
INV_AMP_RESISTORS = INV_AMP.bind(IN=SERIES, FB=PARALLEL)

# The horizontal PARALLEL block bound into a vertical slot. Orientation is resolved at binding:
# the drawing forces a quarter turn, and reading order picks the one that keeps PARALLEL's
# left port on top (spec 3.2). `P=PARALLEL.oriented(90)` would put it at the bottom instead.
SHUNT = Block(
    "Shunt",
    """
    ──R1──┬──
          │
          P
          │
         GND
""",
    R1=R("1k"),
    P=PARALLEL,
    GND=GND(),
)

# A port may expose a named power rail without changing its formal interface name.
SUPPLY_ALIAS = Block(
    "SupplyAlias",
    """
    {VP}──┬──R1──{out}
          │
        [VCC]
""",
    R1=R("1k"),
)

# The crossing is directly between a power label and a resistor terminal.
CROSSING_SUPPLY = Block(
    "CrossingSupply",
    """
          [VCC]
    {a}─────│─────{b}
            R1
            │
          [GND]
""",
    R1=R("1k"),
)

# No-connect markers: the LM386's BYPASS (pin 7) and GAIN pins (1, 8) are unused. X1 and X2
# are NC() groups; their size comes from the drawing (spec 2.9). sim=False: no model here.
LM386_NC = Block(
    "LM386NC",
    """
       [VCC] X1
           │ │
{in}──────+U1U1U1──{out}
      ┌────U1U1U1
      │    U1U1U1
      │    │ │ │
    [GND]  │ X2X2
       [GND]
""",
    U1=Atom("Amplifier_Audio:LM386", "LM386", sim=False),
    X1=NC(),
    X2=NC(),
)

# A volume control: input on the clockwise end, ccw grounded, wiper out (spec 6.2).
VOLUME = Block(
    "Volume",
    """
   {in}──┐
         │
        {cw}
        VR1{w}──{out}
        {ccw}
         │
       [GND]
""",
    VR1=POT("10k", 0.5, "log"),
)

# One dual op-amp package whose units sit in two standard blocks (spec 6.3, 6.4).
_CHIP = Package(IDEAL_DUAL, "U1")
DUAL_OPAMP = Block(
    "DualOpamp",
    """
  [VCC]
     │
     PW
     │
  [VEE]

{in}──GA──IV──{out}
""",
    GA=std.noninverting("10k", "10k", _CHIP.unit("A")),
    IV=std.inverting("10k", "10k", _CHIP.unit("B")),
    PW=_CHIP.power(),
)

# Class-AB output stage from the standard library, with 2N3904/2N3906 and 1N4148 parts.
PUSH_PULL = std.push_pull("bjt", Q2N3904, Q2N3906, D1N4148, rb="2.2k", re="1")

# Three paralleled transistors with ballast resistors: two deliberate crossings.
PARALLEL_ARRAY = std.parallel(Q2N3904, 3, "1")

# Power output stage: Darlington pairs driving paralleled-device arrays, biased by a Vbe
# multiplier for adjustable class-AB bias.
PUSH_PULL_ARRAYS = std.push_pull(
    qn=std.darlington(Q2N3904, std.parallel(Q2N3904, 2, "1", name="ArrayN"), name="OutN"),
    qp=std.darlington(Q2N3906, std.parallel(Q2N3906, 2, "1", name="ArrayP"), name="OutP"),
    bias=std.vbe_multiplier(Q2N3904, "2.7k", "1k"), rb="2.2k", re="0.22",
    name="PushPullArrays",
)

ALL = {
    "SERIES": SERIES,
    "PARALLEL": PARALLEL,
    "SERIES_PARALLEL": SERIES_PARALLEL,
    "DARLINGTON": DARLINGTON,
    "INV_AMP_RESISTORS": INV_AMP_RESISTORS,
    "SHUNT": SHUNT,
    "SUPPLY_ALIAS": SUPPLY_ALIAS,
    "CROSSING_SUPPLY": CROSSING_SUPPLY,
    "LM386_NC": LM386_NC,
    "VOLUME": VOLUME,
    "DUAL_OPAMP": DUAL_OPAMP,
    "PUSH_PULL": PUSH_PULL,
    "PARALLEL_ARRAY": PARALLEL_ARRAY,
    "PUSH_PULL_ARRAYS": PUSH_PULL_ARRAYS,
}

if __name__ == "__main__":
    for title, blk in ALL.items():
        print(f"== {title}: {blk}")
        for b in blk.bound.values():
            if b.rot or b.mirror:
                print(f"   {b.name}: rot={b.rot} mirror={b.mirror}")
        for net, pins in netlist(blk).items():
            print(f"   {net:12s} {' '.join(pins)}")
