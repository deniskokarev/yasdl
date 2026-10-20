"""Example blocks. `python -m examples.blocks` prints netlists; see examples/render.py for KiCad."""

from yasdl import GND, NPN, OPAMP, R, Block, netlist

SERIES = Block("Series", """
    ──R1──R2──
""", R1=R("1k"), R2=R("2k"))

PARALLEL = Block("Parallel", """
    ──┬──R1──┬──
      │      │
      └──R2──┘
""", R1=R("10k"), R2=R("10k"))

# A resistor sub-circuit bound into a component: R1 in series with the PARALLEL block.
SERIES_PARALLEL = Block("SeriesParallel", """
    ──R1──P──
""", R1=R("1k"), P=PARALLEL)

# Darlington pair. Ports: C on top, B on the left, E at the bottom: the same drawn signature
# as a single NPN, so it can be bound wherever an NPN is drawn.
DARLINGTON = Block("Darlington", """
            │
        ┌───┴───┐
        │       │
        Q1      Q2
    ────Q1   ┌──Q2
        Q1   │  Q2
        │    │  │
        └────┘  │
""", Q1=NPN(), Q2=NPN())

# Inverting amplifier: IN and FB are unbound here, so they are the block's open interface.
# The '+' pin shortcut fixes the op-amp orientation (non-inverting input at the bottom),
# which mirrors the symbol and puts V- on top.
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

# Resistor sub-circuits bound into the amplifier's IN and FB components.
INV_AMP_RESISTORS = INV_AMP.bind(IN=SERIES, FB=PARALLEL)

# The horizontal PARALLEL block bound into a vertical slot. Orientation is resolved at binding:
# the drawing forces a quarter turn, and reading order picks the one that keeps PARALLEL's
# left port on top (spec 3.2). `P=PARALLEL.oriented(90)` would put it at the bottom instead.
SHUNT = Block("Shunt", """
    ──R1──┬──
          │
          P
          │
         GND
""", R1=R("1k"), P=PARALLEL, GND=GND())

ALL = {"SERIES": SERIES, "PARALLEL": PARALLEL, "SERIES_PARALLEL": SERIES_PARALLEL,
       "DARLINGTON": DARLINGTON, "INV_AMP_RESISTORS": INV_AMP_RESISTORS, "SHUNT": SHUNT}

if __name__ == "__main__":
    for title, blk in ALL.items():
        print(f"== {title}: {blk}")
        for b in blk.bound.values():
            if b.rot or b.mirror:
                print(f"   {b.name}: rot={b.rot} mirror={b.mirror}")
        for net, pins in netlist(blk).items():
            print(f"   {net:12s} {' '.join(pins)}")
