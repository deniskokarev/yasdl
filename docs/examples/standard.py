"""Reusable circuits and parts: python -m docs.examples.standard [output-directory].

Renders every example with the netlist and SPICE round trips and ERC.
"""

from pathlib import Path
import sys

from yasdl import Atom, Block, NC, Package, Pot, Q2N3904, R, standard
from yasdl.circuits import (
    BandPass,
    CurrentMirror,
    CurrentSink,
    Darlington,
    DifferentialPair,
    Differentiator,
    Follower,
    FollowerPushPull,
    HighPass,
    Integrator,
    Inverting,
    LongTailedPair,
    LowPass,
    NonInverting,
    PushPull,
    SallenKey,
    Sziklai,
)
from yasdl.kicad_export import render


def dual_opamp():
    """One TL072-pinout package: unit A amplifies, unit B buffers, unit C is the supply."""
    chip = Package("TL072")
    power = Block("Power", "[VCC]\n  │\n  PC\n  │\n[VEE]", PC=chip.unit("C"))
    return Block(
        "DualOpamp",
        """
{in}──GAIN──BUF──{out}

PW
""",
        GAIN=NonInverting(opamp=chip.unit("A")),
        BUF=Follower(opamp=chip.unit("B")),
        PW=power,
    )


def connector_and_volume():
    """A physical input connector (not simulated) feeding a volume pot."""
    jack = Atom(
        "Connector_Generic:Conn_01x02",
        sim=False,
        footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
    )
    return Block(
        "ConnectorVolume",
        """
[Input]──J1      [Input]─{cw}VR{ccw}─[GND]
[GND]────J1             {wiper}
                           │
                         {out}
""",
        J1=jack,
        VR=Pot("100k", position=0.25),
    )


def spare_terminals():
    """Three independent no-connect wire ends: a spare transistor's base and collector,
    and one resistor end."""
    return Block(
        "Spares",
        """
      NC2
       │
NC1───Q1Q1
      Q1Q1
       │
     [GND]

NC3─R1─{out}
""",
        NC1=NC(),
        NC2=NC(),
        NC3=NC(),
        Q1=Q2N3904(),
        R1=R("10k"),
    )


def examples():
    result = {
        "DarlingtonN": Darlington(),
        "DarlingtonP": Darlington(pnp=True),
        "DarlingtonPlain": Darlington(turnoff=None),
        "SziklaiN": Sziklai(),
        "SziklaiP": Sziklai(pnp=True),
        "Mirror": CurrentMirror(),
        "DegeneratedMirror": CurrentMirror(degeneration="100"),
        "RailMirror": CurrentMirror(rail="VEE"),
        "CurrentSink": CurrentSink(),
        "DifferentialResistor": DifferentialPair(),
        "DifferentialActive": DifferentialPair(tail="active"),
        "LongTailedPair": LongTailedPair(),
        "LongTailedPairDegenerated": LongTailedPair(degeneration="100"),
        "LowPass": LowPass(),
        "HighPass": HighPass(),
        "BandPass": BandPass(),
        "SallenKey": SallenKey(),
        "Follower": Follower(),
        "NonInverting": NonInverting(),
        "Inverting": Inverting(),
        "Integrator": Integrator(),
        "Differentiator": Differentiator(),
        "DualOpamp": dual_opamp(),
        "ConnectorVolume": connector_and_volume(),
        "Spares": spare_terminals(),
        "StandardBias": standard.bias_string(2),
    }
    for variant in ("bjt", "darlington", "sziklai"):
        result["PushPull_" + variant] = PushPull(variant=variant)
        result["FollowerPushPull_" + variant] = FollowerPushPull(variant=variant)
    result["PushPull_darlington_x4"] = PushPull(variant="darlington", parallel=4)
    return result


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("out/standard")
    for stem, block in examples().items():
        info = render(block, out, export_name=stem, spice=True)
        assert info["roundtrip_ok"] and info["spice_ok"] and info["erc"] == [], info
        print(stem, info["schematic"], "crossings:", block.crossing_count)
