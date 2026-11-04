"""P2.1: explicit no-connect marker groups, NC() (DECISIONS P2.1 follow-ups)."""

import re

import pytest
from yasdl import Atom, Block, NC, netlist, R, spice_netlist, SpiceModel, YasdlError
from yasdl.kicad_lib import KICAD_CLI

have_kicad = KICAD_CLI.exists()

LM386_CANVAS = """
       [VCC] X1
           │ │
{in}──────+U1U1U1──{out}
      ┌────U1U1U1
      │    U1U1U1
      │    │ │ │
    [GND]  │ X2X2
       [GND]
"""


def lm386(lib=None, sim=True):
    """KiCad Amplifier_Audio:LM386: + 3, - 2, V+ 6, GND 4, BYPASS 7 (top), GAIN 1 and 8
    (bottom), out 5."""
    spice = None
    if lib is not None:
        spice = SpiceModel("X", tuple("12345678"), "dummy386", " ".join(f"{n}={n}" for n in "12345678"), str(lib))
    return Atom("Amplifier_Audio:LM386", "LM386", spice=spice, sim=sim)


def test_each_marker_keeps_its_own_single_pin_net():
    block = Block("Amp386", LM386_CANVAS, U1=lm386(sim=False), X1=NC(), X2=NC())
    nets = netlist(block)
    singles = sorted(v[0] for v in nets.values() if len(v) == 1)
    assert {"U1.7", "U1.1", "U1.8"} <= set(singles)
    assert len({tuple(v) for v in nets.values()}) == len(nets)
    data = block.to_dict()
    assert data["components"]["X2"]["binding"] == {"nc": 2}


def test_group_size_comes_from_the_drawing():
    one = Block("One", "{a}──R1──X1", R1=R("1k"), X1=NC())
    three = Block(
        "Three",
        """
        {a}──U1U1U1──X1
        {b}──U1U1U1──X1
        {c}──U1U1U1──X1
        """,
        X1=NC(),
    )
    assert len(one.bound["X1"].pin_map) == 1
    assert len(three.bound["X1"].pin_map) == 3


@pytest.mark.parametrize(
    "canvas, match",
    [
        ("{a}──R1──┬──R2──{b}\n         │\n         X1", "exactly one device pin; it reaches 2"),
        ("{a}──R1──┬──[Sig]\n         │\n         X1", "global net Sig"),
        ("{a}──R1──┬──{b}\n         │\n         X1", "external port"),
        ("{a}──R1──┬──X1\n         │\n         X2", "terminate the same net"),
    ],
)
def test_invalid_terminations(canvas, match):
    parts = {"R1": R("1k"), "R2": R("1k"), "X1": NC(), "X2": NC()}
    block = Block("Bad", canvas, **{k: v for k, v in parts.items() if k in canvas})
    with pytest.raises(YasdlError, match=match):
        netlist(block)


def test_nc_with_pin_label_or_no_wire_is_rejected():
    with pytest.raises(YasdlError, match="no wires"):
        Block("N", "{a}──R1──{b}\n\n   X1", R1=R("1k"), X1=NC())


INNER = Block(
    "Inner",
    """
    {i}──R1──┬──{o}
             │
             R2
             │
           [GND]
    """,
    R1=R("1k"),
    R2=R("1k"),
)
LEAF = Block("Leaf", "{i}──R1──{o}", R1=R("1k"))


def test_child_port_may_end_at_nc_only_when_it_reaches_one_pin():
    ok = Block("ParentOk", "{a}──LF──X1", LF=LEAF, X1=NC())
    assert ["LF.R1.2"] in netlist(ok).values()
    bad = Block("ParentBad", "{a}──IN──X1", IN=INNER, X1=NC())
    with pytest.raises(YasdlError, match=r"reaches 2: \['IN.R1.2', 'IN.R2.1'\]"):
        netlist(bad)


def test_markers_are_not_spice_elements(tmp_path):
    lib = tmp_path / "d.lib"
    lib.write_text(".subckt dummy386 p1 p2 p3 p4 p5 p6 p7 p8\nR1 p1 p8 1k\n.ends\n")
    text = spice_netlist(Block("Amp386", LM386_CANVAS, U1=lm386(lib), X1=NC(), X2=NC()))
    line = next(x for x in text.splitlines() if x.startswith("X_U1 "))
    nodes = line.split()[1:9]
    # pins 1, 7, 8 keep distinct, isolated nodes
    assert len({nodes[0], nodes[6], nodes[7]}) == 3
    assert sum(n in text.replace(line, "") for n in (nodes[0], nodes[6], nodes[7])) == 0
    assert not re.search(r"^\w*X[12] ", text, re.M)


@pytest.mark.integration
@pytest.mark.skipif(not have_kicad, reason="kicad-cli missing")
def test_kicad_erc_netlist_and_spice_with_nc_group(tmp_path):
    from yasdl.kicad_export import erc, export_kicad_spice, render
    from yasdl.sexp import find_all, parse

    lib = tmp_path / "d.lib"
    lib.write_text(".subckt dummy386 p1 p2 p3 p4 p5 p6 p7 p8\nR1 p1 p8 1k\n.ends\n")
    block = Block("Amp386", LM386_CANVAS, U1=lm386(lib), X1=NC(), X2=NC())
    info = render(block, tmp_path, svg=False, spice=True, spice_libs=(lib,))
    assert info["roundtrip_ok"], (info["missing"], info["extra"])
    assert info["erc"] == []
    assert info["spice_ok"], info["spice_diff"]
    sch = info["schematic"]
    assert len(find_all(parse(sch.read_text()), "no_connect")) == 3
    assert re.search(r"^XU1 (\S+ ){8}dummy386$", export_kicad_spice(sch), re.M)
    # Without the markers KiCad reports exactly those three pins.
    text = sch.read_text()
    stripped = re.sub(r"\t\(no_connect\n(?:\t\t[^\n]*\n)*?\t\)\n", "", text)
    assert stripped.count("no_connect") == 0, "markers removed"
    sch.write_text(stripped)
    problems = [e for e in erc(sch) if "pin_not_connected" in e]
    assert len(problems) == 3 and all(re.search(r"Pin [178] ", e) for e in problems)


@pytest.mark.integration
@pytest.mark.skipif(not have_kicad, reason="kicad-cli missing")
def test_hierarchical_nc_renders_clean(tmp_path):
    from yasdl.kicad_export import render

    info = render(Block("ParentOk", "{a}──LF──X1", LF=LEAF, X1=NC()), tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"] and info["erc"] == [] and info["spice_ok"], info
