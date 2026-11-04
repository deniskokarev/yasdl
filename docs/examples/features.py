"""Whole-package simulation, a physical jack with NC, and compound output-device examples.

`python -m docs.examples.render` renders them with the netlist and SPICE round trips and ERC.
"""

from yasdl import Atom, Block, NC, POT, R, V
from yasdl import std
from yasdl.kicad_lib import JELLYBEAN_MODEL
from yasdl.parts import D1N4148, dual_opamp, Q2N3904, Q2N3906

# The bundled ideal dual op-amp model: whole-device subcircuit in the standard dual pinout.
IDEAL_DUAL_LIB = str(JELLYBEAN_MODEL.parent / "yasdl.lib")
IDEAL_DUAL = dual_opamp(
    "IDEAL_DUAL",
    model="yasdl_ideal_opamp_dual",
    library=IDEAL_DUAL_LIB,
    model_pins=["A.+", "A.-", "A.out", "B.+", "B.-", "B.out", "V+", "V-"],
)

# A dual op-amp package: unit A in a follower, unit B in a gain-of-3 stage, the power unit at
# the top level. One KiCad reference (U1A, U1B, U1C), one whole-device SPICE element.
CHIP = IDEAL_DUAL(name="UA")
DUAL_OPAMP = Block(
    "DualOpamp",
    """
               [VCC]
                 │
{in}──BUF──AMP┐  PW
              │  │
            {out}[VEE]
""",
    BUF=std.FOLLOWER.bind(U1=CHIP.unit("A")),
    AMP=std.NONINVERTING.bind(RG=R("10k"), RF=R("20k"), U1=CHIP.unit("B")),
    PW=CHIP.power(),
)

# A volume pot (audio taper) after a non-simulated input jack whose ring is not connected.
VOLUME = Block(
    "Volume",
    """
J1J1{s}─────[GND]
J1J1{r}──X1
J1J1{t}──────┐
             │
            {cw}
             RV{w}──{out}
            {ccw}
             │
           [GND]
""",
    J1=Atom("Connector_Audio:AudioJack3", "IN", sim=False,
            footprint="Connector_Audio:Jack_6.35mm_Neutrik_NJ3FD-V_Vertical"),
    X1=NC(),
    RV=POT("10k", rotation=0.7, taper="log"),
)

# A standard Sziklai push-pull stage with two-device output arrays and derived parts.
PUSH_PULL = std.push_pull(
    "sziklai",
    std.sziklai(Q2N3904(), std.parallel(Q2N3906(), 2, name="ArrP2"), name="SzN"),
    std.sziklai(Q2N3906(), std.parallel(Q2N3904(), 2, name="ArrN2"), name="SzP"),
    diode=D1N4148(),
    name="PushPullSziklai",
)

ALL = {
    "DUAL_OPAMP": DUAL_OPAMP,
    "VOLUME": VOLUME,
    "PUSH_PULL": PUSH_PULL,
}
SPICE_LIBS = (str(JELLYBEAN_MODEL),)
