"""Standard blocks and parts: python -m docs.examples.standard [output-directory].

Renders every example with the netlist and SPICE round trips and ERC.
"""

from pathlib import Path
import sys

from yasdl import Atom, Block, D1N4148, NC, Package, Pot, Q2N3904, Q2N3906, R, std
from yasdl.kicad_export import render

N, P = Q2N3904, Q2N3906


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
        GAIN=std.noninverting("47k", "1k", chip.unit("A")),
        BUF=std.follower(chip.unit("B")),
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
    sink = std.current_sink(N, diode=D1N4148)
    result = {
        "DarlingtonN": std.darlington(N),
        "DarlingtonP": std.darlington(P),
        "DarlingtonPlain": std.darlington(N, rx=None),
        "SziklaiN": std.sziklai(N, P),
        "SziklaiP": std.sziklai(P, N),
        "Parallel3": std.parallel(N, 3),
        "Diodes2": std.diode_string(2, D1N4148),
        "VbeMultiplier": std.vbe_multiplier(N),
        "Mirror": std.mirror(N),
        "MirrorPNP": std.mirror(P, "pnp"),
        "DegeneratedMirror": std.mirror(N, re="100"),
        "Wilson": std.wilson(N),
        "CurrentSink": sink,
        "DiffPair": std.diff_pair(N),
        "DiffPairDegenerated": std.diff_pair(N, re="100"),
        "DiffPairCurrentSink": std.diff_pair(N, re="100", rt=sink),
        "DiffPairMirror": std.diff_pair_mirror(N, P),
        "LowPass": std.rc_lowpass("10k", "100n"),
        "HighPass": std.rc_highpass("100n", "10k"),
        "BandPass": std.rc_bandpass("1u", "10k", "10k", "10n"),
        "SallenKey": std.sallen_key_lowpass("10k", "10k", "10n", "20n"),
        "Follower": std.follower(),
        "NonInverting": std.noninverting("47k", "1k"),
        "Inverting": std.inverting("10k", "100k"),
        "Integrator": std.integrator("10k", "10n"),
        "Differentiator": std.differentiator("10n", "10k"),
        "DualOpamp": dual_opamp(),
        "ConnectorVolume": connector_and_volume(),
        "Spares": spare_terminals(),
    }
    for kind in ("bjt", "darlington", "sziklai"):
        result["PushPullCore_" + kind] = std.push_pull_core(kind, N, P, D1N4148)
        result["PushPullBuffer_" + kind] = std.push_pull(kind, N, P, D1N4148)
        result["PushPullVas_" + kind] = std.push_pull_vas(kind, N, P, D1N4148)
    result["PushPullCore_darlington_x4"] = std.push_pull_core(
        "darlington", N, P, D1N4148, n=4
    )
    return result


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("out/standard")
    for stem, block in examples().items():
        info = render(block, out, export_name=stem, spice=True)
        assert info["roundtrip_ok"] and info["spice_ok"] and info["erc"] == [], info
        print(stem, info["schematic"], "crossings:", block.crossing_count)
