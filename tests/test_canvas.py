import shutil

import pytest

from docs.examples import blocks as ex
from yasdl import NPN, OPAMP, R, Block, CanvasError, YasdlError, minimal_period, netlist
from yasdl.canvas import Canvas
from yasdl.kicad_lib import KICAD_CLI


def net_of(nets, pin):
    return next(set(p) for p in nets.values() if pin in p)


@pytest.mark.parametrize("word,name", [("U1U1U1", "U1"), ("NPN", "NPN"), ("RRRR", "R"),
                                       ("U1U1U", "U1U1U"), ("FB", "FB")])
def test_component_name_is_minimal_period(word, name):
    assert minimal_period(word) == name


def test_component_rectangle_rules():
    cv = Canvas("""
        U1U1──
        U1U1
    """)
    assert set(cv.comps) == {"U1"}
    with pytest.raises(CanvasError, match="rectangle"):
        Canvas("R1\nR1R2")
    with pytest.raises(CanvasError, match="identical"):
        Canvas("AB\nBA")


def test_dangling_and_tee_rules():
    with pytest.raises(CanvasError, match="dangling"):
        Canvas("──  ")
    with pytest.raises(CanvasError, match="tee"):
        Canvas(" │ \n───")  # vertical wire ends on a straight horizontal wire


def test_crossing_keeps_nets_apart():
    cv = Canvas("""
         │
        ─│─
         │
    """)
    ports = {p.side: cv.uf.find(p.node) for p in cv.edge_ports}
    assert ports["W"] == ports["E"] and ports["N"] == ports["S"] and ports["W"] != ports["N"]
    cv = Canvas(" │ \n─┼─\n │ ")  # junction: one net
    assert len({cv.uf.find(p.node) for p in cv.edge_ports}) == 1


def test_net_labels_are_implicit_wires():
    blk = Block("L", """
        ──R1──[x]

        [x]──R2──
    """, R1=R(), R2=R())
    nets = netlist(blk)
    assert {"R1.2", "R2.1"} <= set(nets["x"]) or {"R1.1", "R2.2"} <= set(nets["x"])


def test_pin_labels_set_orientation():
    blk = Block("Mirrored", """
         │
        [c]
        Q1Q1
        Q1Q1[b]─
        Q1Q1
         │
    """, Q1=NPN())
    b = blk.bound["Q1"]
    pins = {att.side: pin for att, pin in b.pin_map}
    assert pins == {"N": "C", "E": "B", "S": "E"}


def test_inconsistent_pin_labels_rejected():
    with pytest.raises(YasdlError, match="does not fit"):
        Block("Bad", """
             │
            [c]
            Q1Q1
            Q1Q1[e]─
            Q1Q1
             │
        """, Q1=NPN())


def test_explicit_orientation_and_signature():
    with pytest.raises(YasdlError, match="does not fit"):  # op-amp drawn without supply pins
        Block("NoSupply", """
            ──U1U1
              U1U1──
            ──U1U1
        """, U1=OPAMP())
    with pytest.raises(YasdlError, match="does not fit"):  # 3-port block into a 2-wire component
        ex.INV_AMP.bind(IN=ex.DARLINGTON, FB=R())


def test_examples_netlists():
    nets = netlist(ex.DARLINGTON)
    assert net_of(nets, "Q1.E") == {"Q1.E", "Q2.B"}
    assert net_of(nets, "Q1.C") == {"Q1.C", "Q2.C"}
    nets = netlist(ex.INV_AMP_RESISTORS)
    assert net_of(nets, "U1.2") == {"U1.2", "IN.R2.2", "FB.R1.1", "FB.R2.1"}  # inverting input
    assert nets["GND"] == ["U1.1"]  # [GND] label, no ground atom
    assert net_of(nets, "U1.5") >= {"FB.R1.2", "FB.R2.2"}
    assert nets["VEE"] == ["U1.4"] and nets["VCC"] == ["U1.3"]


def test_unbound_components_are_the_interface():
    assert ex.INV_AMP.unbound == ["FB", "IN"]
    with pytest.raises(YasdlError, match="unbound"):
        netlist(ex.INV_AMP)


@pytest.mark.skipif(not KICAD_CLI.exists() and not shutil.which("kicad-cli"),
                    reason="kicad-cli not available")
@pytest.mark.parametrize("name", list(ex.ALL))
def test_kicad_roundtrip(name, tmp_path):
    from yasdl.kicad_export import render
    info = render(ex.ALL[name], tmp_path, svg=False)
    assert info["roundtrip_ok"], (info["missing"], info["extra"])
    assert info["erc"] == [], info["erc"]  # errors and warnings


def test_block_orientation_at_binding():
    p = ex.SHUNT.bound["P"]
    assert (p.rot, p.mirror) == (270, None)  # left port on top (reading order)
    by_side = {att.side: idx for att, idx in p.pin_map}
    assert ex.PARALLEL.ports[by_side["N"]].side == "W"
    flipped = ex.SHUNT.bind(P=ex.PARALLEL.oriented(90))
    by_side = {att.side: idx for att, idx in flipped.bound["P"].pin_map}
    assert ex.PARALLEL.ports[by_side["N"]].side == "E"
    with pytest.raises(YasdlError, match="does not fit"):
        ex.SHUNT.bind(P=ex.PARALLEL.oriented(0))  # horizontal block, vertical slot


def test_json_view():
    import json
    d = ex.INV_AMP_RESISTORS.to_dict()
    json.dumps(d)  # serialisable
    assert set(d["blocks"]) == {"Series", "Parallel"}
    assert d["components"]["U1"]["binding"]["mirror"] == "x"
    assert d["components"]["FB"]["binding"]["block"] == "Parallel"
    assert set(d["nets"]["VEE"]["pins"]) == {"U1.4"}
    minus = d["components"]["U1"]["attachments"]["W"][0]["net"]
    assert {"U1.2", "IN.E0", "FB.W0"} <= set(d["nets"][minus]["pins"])


def test_bracket_labels_and_reserved_arrows():
    nets = netlist(Block("L", "──R1──[x]\n\n[x]──R2──", R1=R(), R2=R()))
    assert len(nets["x"]) == 2
    with pytest.raises(CanvasError, match="old-style label"):
        Canvas("──R1──<GND>")  # old label syntax: arrows around a component, no wire: hint
    for ch in "<>^vV":
        with pytest.raises(CanvasError, match="arrow pin label and must touch"):
            Canvas(f"──R1──{ch}──")  # arrows are pin labels, not wire decorations


@pytest.mark.parametrize("name", ["vv", "VVV"])  # a lone v/V is an arrow, never a component
def test_component_named_v_rejected(name):
    with pytest.raises(CanvasError, match="named v or V"):
        Canvas(f"──{name}──")


@pytest.mark.parametrize("word,name", [("v1v1v1", "v1"), ("V1", "V1"), ("VR1", "VR1"), ("Rv", "Rv")])
def test_v_inside_names_is_fine(word, name):
    assert set(Canvas(f"──{word}──").comps) == {name}


def test_dot_is_reserved():
    with pytest.raises(CanvasError, match="reserved for future use"):
        Canvas("──R1──.")
    with pytest.raises(CanvasError, match="reserved for future use"):
        Canvas(".──R1──")
