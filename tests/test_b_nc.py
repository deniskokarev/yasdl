"""P2: explicit no-connect marker groups, NC() (spec 2.9).

Each wire drawn to an NC group ends in its own KiCad no_connect cross; wires are never pruned
or merged, the marker is no netlist pin and no SPICE element, and it must end the wire of
exactly one otherwise unconnected device pin.
"""

import re

import pytest
from yasdl import Atom, Block, NC, netlist, OPAMP, POT, R, spice_netlist, V, YasdlError
from yasdl.canvas import Canvas
from yasdl.kicad_lib import KICAD_CLI

kicad = pytest.mark.skipif(not KICAD_CLI.exists(), reason="kicad-cli missing")
CONN4 = "Connector:Conn_01x04_Pin"

SINGLE = Block("NcSingle", "{a}──R1──X1", R1=R("1k"), X1=NC())

GROUP_EW = Block(
    "NcGroupEW",
    """
J1J1──────R1──{out}
J1J1──X1
J1J1──X1
J1J1──X1
""",
    J1=Atom(CONN4, "HDR4", sim=False),
    R1=R("1k"),
    X1=NC(),
)

GROUP_NS = Block(
    "NcGroupNS",
    """
X1X1X1 ┌──R1──{out}
│ │ │  │
J1J1J1J1
""",
    J1=Atom(CONN4, "HDR4", sim=False),
    R1=R("1k"),
    X1=NC(),
)


def test_group_size_comes_from_the_drawing():
    cv = Canvas("X1-U1-X2\nX1-U1-X2\nX1-U1-X2\n   U1----{only_usable}\n")
    counts = {n: {s: len(v) for s, v in c.attachments.items() if v} for n, c in cv.comps.items()}
    assert counts["X1"] == {"E": 3} and counts["X2"] == {"W": 3}
    assert counts["U1"] == {"W": 3, "E": 4}
    assert len(GROUP_EW.bound["X1"].pin_map) == 3
    assert len(GROUP_NS.bound["X1"].pin_map) == 3
    assert {att.side for att, _ in GROUP_NS.bound["X1"].pin_map} == {"S"}
    assert SINGLE.to_dict()["components"]["X1"]["binding"] == {"nc": 1}


def test_each_marked_pin_keeps_its_own_net():
    nets = netlist(GROUP_EW)
    singles = sorted(pins for pins in nets.values() if len(pins) == 1 and pins[0][0] == "J")
    assert singles == [["J1.2"], ["J1.3"], ["J1.4"]]
    assert sorted(nets["out"]) == ["R1.2"]
    assert not any("X1" in p for pins in nets.values() for p in pins)  # no marker pins
    nets = netlist(GROUP_NS)
    assert sorted(len(v) for v in nets.values()) == [1, 1, 1, 1, 2]


def test_marker_is_not_a_spice_element_but_the_pin_keeps_a_node():
    text = spice_netlist(SINGLE)
    assert re.search(r"^R_R1 a (\S+) 1k$", text, re.M)
    assert "X1" not in text
    wiper_nc = Block(
        "WiperNC",
        """
  ┌──────┐
  │     {ccw}
  +      RV──X1
  V1    {cw}
  │      │
[GND]  [GND]
""",
        V1=V("1"),
        RV=POT("10k"),
        X1=NC(),
    )
    line = next(x for x in spice_netlist(wiper_nc).splitlines() if x.startswith("X_RV"))
    wiper = line.split()[2]
    assert spice_netlist(wiper_nc).count(f" {wiper} ") == 1  # isolated model terminal


@pytest.mark.parametrize(
    "canvas, bindings, match",
    [
        ("{a}──R1──┬──R2──{b}\n         │\n         X1\n", {"R2": R()}, "several device pins"),
        ("{a}──R1──┬──[Shared]\n         │\n         X1\n", {}, "global net"),
        ("{a}──R1──┬──[local]\n         │\n         X1\n", {}, r"labelled \[local\]"),
        ("{a}──R1──┬──{b}\n         │\n         X1\n", {}, "block port"),
        ("{a}──R1──┬──X1\n         │\n         X2\n", {"X2": NC()}, "terminate the same net"),
        ("{a}──R1──{b}\n\nX1──CH", {"CH": Block("Stub", "{p}────[stub]")}, "no device pin"),
    ],
)
def test_invalid_nc_nets(canvas, bindings, match):
    block = Block("Bad", canvas, R1=R("1k"), X1=NC(), **bindings)
    with pytest.raises(YasdlError, match=match):
        netlist(block)


def test_pin_label_on_nc_is_rejected():
    with pytest.raises(YasdlError, match="NC markers have no pins"):
        Block("Bad", "{a}──R1──{x}X1", R1=R(), X1=NC())


# Hierarchy: a child port may end at NC when it resolves to one inner pin.
ONE_PIN = Block("OnePin", "{p}──R1──{q}", R1=R("1k"))
FAN_OUT = Block(
    "FanOut",
    """
{p}──┬──R1──┐
     │      │
     └──R2──┴──{q}
""",
    R1=R("1k"),
    R2=R("2k"),
)


def test_child_port_to_one_pin_may_be_nc():
    top = Block("Top", "{a}──CH──X1", CH=ONE_PIN, X1=NC())
    assert sorted(len(v) for v in netlist(top).values()) == [1, 1]


def test_child_port_fanning_out_is_reported_not_pruned():
    top = Block("Top", "X1──CH──{b}", CH=FAN_OUT, X1=NC())
    with pytest.raises(YasdlError, match=r"several device pins: CH\.R1\.1, CH\.R2\.1"):
        netlist(top)


def _no_connects(sch_path):
    from yasdl.sexp import find, find_all, parse

    root = parse(sch_path.read_text())
    marks = {(float(find(n, "at")[1]), float(find(n, "at")[2])) for n in find_all(root, "no_connect")}
    wires = [
        tuple((float(xy[1]), float(xy[2])) for xy in find_all(find(w, "pts"), "xy"))
        for w in find_all(root, "wire")
    ]
    return marks, wires


@pytest.mark.integration
@kicad
@pytest.mark.parametrize("block", [SINGLE, GROUP_EW, GROUP_NS], ids=lambda b: b.name)
def test_kicad_markers_at_wire_ends_pass_erc_and_round_trips(tmp_path, block):
    from yasdl.kicad_export import render

    info = render(block, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"], (info["missing"], info["extra"])
    assert info["erc"] == [], info["erc"]
    assert info["spice_ok"], info["spice_diff"]
    marks, wires = _no_connects(info["schematic"])
    assert len(marks) == len(block.bound["X1"].pin_map)
    ends = {p for w in wires for p in w}
    assert marks <= ends  # each cross sits on the free end of a wire stub


@pytest.mark.integration
@kicad
def test_hierarchical_nc_renders(tmp_path):
    from yasdl.kicad_export import render

    top = Block("TopNC", "{a}──CH──X1", CH=ONE_PIN, X1=NC())
    info = render(top, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"] and info["erc"] == [] and info["spice_ok"], info


@pytest.mark.integration
@kicad
@pytest.mark.parametrize(
    "canvas, orientation",
    [("G──{x}", (0, None)), ("{x}──G", (180, "x")), ("{x}\n │\n G", (90, None))],
    ids=["plain", "mirrored", "rotated"],  # (180, "x") is the left-right flip
)
def test_nc_inside_a_child_block_renders(tmp_path, canvas, orientation):
    """Markers drawn inside a sub-block reach the parent schematic, at the child's wire ends
    after the child's binding-time orientation (bug found by the bass-amp exercise: the
    child's markers were dropped, so KiCad reported pin_not_connected)."""
    from yasdl.kicad_export import render

    top = Block("NcNested", canvas, G=GROUP_EW)
    assert (top.bound["G"].rot, top.bound["G"].mirror) == orientation
    info = render(top, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"] and info["erc"] == [] and info["spice_ok"], info
    marks, wires = _no_connects(info["schematic"])
    assert len(marks) == 3
    assert marks <= {p for w in wires for p in w}


@pytest.mark.integration
@kicad
def test_unused_supply_pin_gets_no_power_flag(tmp_path):
    """A PWR_FLAG on an NC net would make KiCad report no_connect_connected."""
    from yasdl.kicad_export import render

    block = Block(
        "NcSupply",
        """
        [VCC]
          │
{inp}────+U1U1U1
          U1U1U1───{out}
{inn}─────U1U1U1
          │
          X1
""",
        U1=OPAMP(),
        X1=NC(),
    )
    info = render(block, tmp_path, svg=False)
    assert info["roundtrip_ok"], (info["missing"], info["extra"])
    assert info["erc"] == [], info["erc"]
