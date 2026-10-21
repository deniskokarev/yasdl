"""Directional pin labels: < > ^ v (spec 2.5). Arrows show conventional current and rotate
and mirror with the part; each arrow names one pin."""

import pytest

from yasdl import NPN, R, Atom, Block, D, YasdlError, netlist
from yasdl.canvas import Canvas, CanvasError


def net_of(nets, pin):
    return next(set(p) for p in nets.values() if pin in p)


# --- diode -------------------------------------------------------------------------------
def test_diode_arrow_puts_anode_first():
    blk = Block("D", "{a}──>D1──{k}", D1=D("1N4148"))
    # anode (pin 2) left; 180 deg and a left/right mirror draw the same diode (mirror chosen)
    assert {att.side: pin for att, pin in blk.bound["D1"].pin_map} == {"W": "2", "E": "1"}
    assert net_of(netlist(blk), "D1.2") == {"D1.2"} and netlist(blk)["a"] == ["D1.2"]


def test_diode_library_orientation():
    blk = Block("D", "{k}──D1<──{a}", D1=D("1N4148"))  # < enters the anode from the right
    assert (blk.bound["D1"].rot, blk.bound["D1"].mirror) == (0, None)
    assert netlist(blk)["a"] == ["D1.2"]


@pytest.mark.parametrize("canvas", ["{a}──D1>──{k}",   # only the anode has an arrow
                                    "{a}──<D1──{k}"])  # < leaving on the left: no such pin
def test_diode_arrow_mismatch(canvas):
    with pytest.raises(YasdlError, match="does not fit"):
        Block("D", canvas, D1=D("1N4148"))


@pytest.mark.parametrize("v", ["v", "V"])
def test_diode_vertical(v):
    blk = Block("D", f"""
        {{a}}
         │
         {v}
         D1
         │
        {{k}}
    """, D1=D("1N4148"))
    assert {att.side: pin for att, pin in blk.bound["D1"].pin_map} == {"N": "2", "S": "1"}


# --- placement rules ------------------------------------------------------------------------
@pytest.mark.parametrize("canvas,msg", [
    ("{a}──^D1──{k}", "above or below"),                   # ^ beside a component
    (" │\n <\n D1\n │", "left or right"),                  # < above a component
    ("──R1──v──", "must touch"),                           # arrows are pin labels only
])
def test_arrow_placement(canvas, msg):
    with pytest.raises(CanvasError, match=msg):
        Canvas(canvas)


def test_arrow_axis_on_block_ports():
    with pytest.raises(YasdlError, match="arrow alias"):
        Block("B", "{^}──R1──{b}", R1=R())
    with pytest.raises(YasdlError, match="arrow alias"):
        Block("B", "{<}\n │\n R1\n │\n{b}", R1=R())


def test_atom_arrow_rules():
    with pytest.raises(YasdlError, match="only one pin"):
        Atom("Device:D", arrows={"1": "<", "2": "<"})
    with pytest.raises(YasdlError, match="along the pin"):
        Block("D", "{a}──D1──{k}", D1=Atom("Device:D", arrows={"2": "^"}))
    with pytest.raises(YasdlError, match="does not fit"):
        Block("R", "{a}──>R1──{b}", R1=R())  # a resistor declares no arrows


def test_glued_v_hint():
    with pytest.raises(YasdlError, match="glued"):
        Block("D", "{a}──vD1──{k}", D1=D("1N4148"))


# --- BJT (current arrows: base in, emitter out) ----------------------------------------------
def test_npn_regular():
    blk = Block("CE", """
           │
        ──>Q1Q1
           Q1Q1
           Q1Q1
           v
           │
    """, Q1=NPN("2N3904"))
    b = blk.bound["Q1"]
    assert (b.rot, b.mirror) == (0, None)
    assert {att.side: pin for att, pin in b.pin_map} == {"W": "B", "N": "C", "S": "E"}


def test_npn_common_base():
    blk = Block("CB", """
        ──<Q2Q2──
           Q2Q2
           Q2Q2
           ^
           │
    """, Q2=NPN("2N3904"))  # emitter current leaves left, base current enters from below
    assert {att.side: pin for att, pin in blk.bound["Q2"].pin_map} == {"W": "E", "E": "C", "S": "B"}
    with pytest.raises(YasdlError, match="does not fit"):  # signal-flow arrows don't rotate to this
        Block("CB", "──>Q2Q2>──\n   Q2Q2\n   Q2Q2\n   ^\n   │", Q2=NPN("2N3904"))


# --- blocks: arrow aliases, mirror-agnostic pairs, directional blocks --------------------------
TWO_R = Block("TwoR", "{<}──R1──R2──{>}", R1=R("1k"), R2=R("2k"))  # arrows point outward


def test_mirror_agnostic_pair():
    plain = Block("H", "{a}──<RX>──{b}", RX=TWO_R)
    flipped = Block("H", "{a}──<RX>──{b}", RX=TWO_R.mirrored("y"))  # also fits the labels
    assert netlist(plain)["a"] == ["RX.R1.1"] and netlist(flipped)["a"] == ["RX.R2.2"]


def test_inward_pair():
    inward = Block("In", "{>}──R1──{<}", R1=R("1k"))
    Block("H", "{a}──>RX<──{b}", RX=inward)


def test_directional_block():
    diode = Block("Dio", "{>}──D1──{k}", D1=D("1N4148").mirrored("y"))  # anode on the W port
    assert diode.port(">").side == "W" and diode.ports[diode.ports.index(diode.port(">"))].name is None
    fwd = Block("H", "{a}──>DX──{b}", DX=diode)
    assert (fwd.bound["DX"].rot, fwd.bound["DX"].mirror) == (0, None)
    rev = Block("H", "{a}──DX<──{b}", DX=diode)  # < enters from the right: anode port on the E side
    assert (rev.bound["DX"].rot, rev.bound["DX"].mirror) == (180, "x")
    with pytest.raises(YasdlError, match="does not fit"):
        Block("H", "{a}──DX>──{b}", DX=diode)


def test_duplicate_arrow_aliases_rejected():
    with pytest.raises(YasdlError, match="two ports"):
        Block("B", "{>}──R1──{>}", R1=R())
