"""Example composite blocks. Run `python -m examples.blocks` to print their netlists."""

from yasdl import (C, GND, NPN, OPAMP, R, VCC, Block, Hole, Parallel, Series, netlist)

# Series and parallel resistors. Atoms rotate themselves to match their neighbours:
# R's library orientation is vertical, here it becomes horizontal.
SERIES2 = Block("Series2", "R1 R2", R1=R("1k"), R2=R("2k"))

PARALLEL2 = Block("Parallel2", """
    ┬ R1 ┬
    └ R2 ┘
""", R1=R("1k"), R2=R("1k"))

# A 2-row sub-block in one cell of a 1-row block: R1's row stretches to the
# sub-block's height and the sub-block's port row aligns with R1.
SERIES_PARALLEL = Block("SeriesParallel", "R1 P", R1=R("1k"), P=PARALLEL2)

# Darlington pair. Outer ports: B on W, C on N, E on S: the same signature as a single
# NPN, so it can fill any hole an NPN fits.
DARLINGTON = Block("Darlington", """
    ┌  ┤
    Q1 │
    └  Q2
""", Q1=NPN(), Q2=NPN())

# Common-emitter amplifier with collector-to-base negative feedback (RF).
# The transistor is a 3-port hole: fill it with an NPN or a Darlington.
CE_AMP = Block("CEAmp", """
    .   .  .   VCC .
    .   .  .   RC  .
    .   ┌  RF  ┼   ─
    CIN ┴  ─   Q   .
    .   .  .   GND .
""", VCC=VCC(), RC=R("4.7k"), RF=R("100k"), CIN=C("1u"), Q=Hole("Q", 3), GND=GND())

# Inverting op-amp amplifier with input and feedback holes. The op-amp spans 3 rows
# (- , out, +) and is mirrored so the inverting input is on top, under the feedback path.
INV_AMP = Block("InvAmp", """
    .   ┌  FB  ┐  .
    IN  ┴  U1  │  .
    .   .  U1  ┴  ─
    .   ┌  U1  .  .
    .   GND .  .  .
""", IN=Hole("IN", 2), FB=Hole("FB", 2), U1=OPAMP().flip(), GND=GND())

# Fills.
CE_NPN = CE_AMP.fill(Q=NPN())
CE_DARLINGTON = CE_AMP.fill(Q=DARLINGTON)
INV_GAIN10 = INV_AMP.fill(IN=R("10k"), FB=R("100k"))
LOSSY_INTEGRATOR = INV_AMP.fill(IN=R("10k"), FB=Parallel(R("100k"), C("10n")))

# Two inverting stages in a row; the second stage's holes are re-exported.
TWO_STAGE = Block("TwoStage", "A1 A2", export=["A2.IN", "A2.FB"],
                  A1=INV_GAIN10, A2=INV_AMP)
TWO_STAGE_FILLED = TWO_STAGE.fill({"A2.IN": R("10k"), "A2.FB": Series(R("47k"), R("53k"))})

ALL = {
    "SERIES2": SERIES2, "PARALLEL2": PARALLEL2, "SERIES_PARALLEL": SERIES_PARALLEL,
    "DARLINGTON": DARLINGTON, "CE_NPN": CE_NPN, "CE_DARLINGTON": CE_DARLINGTON,
    "INV_GAIN10": INV_GAIN10, "LOSSY_INTEGRATOR": LOSSY_INTEGRATOR,
    "TWO_STAGE_FILLED": TWO_STAGE_FILLED,
}

if __name__ == "__main__":
    for title, blk in ALL.items():
        print(f"== {title}: {blk}")
        for net, pins in netlist(blk).items():
            print(f"   {net:22s} {' '.join(pins)}")
