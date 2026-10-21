import pytest

from docs.examples import blocks as ex
from yasdl import GND, NPN, R, Block, YasdlError, netlist


def net_of(nets, pin):
    return next(set(p) for p in nets.values() if pin in p)


FOLLOWER = """
                  │
    {input}────[b]Q1Q1
                  Q1Q1
                  Q1Q1
                  │
"""


def test_brace_label_names_a_port():
    blk = Block("F", FOLLOWER, Q1=NPN())
    assert blk.port("input").side == "W"
    assert blk.port("input").aliases[0] == "input"
    assert netlist(blk)["input"] == ["Q1.B"]


def test_reexported_pin_names():
    blk = Block("F", FOLLOWER, Q1=NPN())
    assert blk.port("C").side == "N" and blk.port("E").side == "S"  # from Q1's pin names
    d = {p.name for p in ex.DARLINGTON.ports}
    assert d == {"B", "C", "E"}


def test_reexport_conflict_keeps_defaults():
    blk = Block("TwoQ", """
             │          │
        [a]──Q1    [b]──Q2
             Q1         Q2
             │          │
            G1         G2
    """, Q1=NPN(), Q2=NPN(), G1=GND(), G2=GND())
    assert [p.name for p in blk.ports] == [None, None]  # both collectors would be "C"
    assert blk.port("N0") and blk.port("N1")


def test_dip_numbering():
    blk = Block("Cross", """
          │
        ──┼──
          │
    """)
    assert {p.default: p.dip for p in blk.ports} == {"W0": 0, "S0": 1, "E0": 2, "N0": 3}
    assert blk.port("D3").side == "N"


def test_brace_label_rules():
    with pytest.raises(YasdlError, match="edge"):
        Block("Inner", "──R2──────\n\n {x}──R1──", R1=R(), R2=R())  # {x} one cell off the edge
    with pytest.raises(YasdlError, match="exactly one wire"):
        Block("Inline", "──R1──{x}──", R1=R())
    with pytest.raises(YasdlError, match="two ports"):
        Block("Dup", "{x}──R1──{x}", R1=R())
    with pytest.raises(YasdlError, match="must not touch"):
        Block("Touch", "{x}R1──", R1=R())
    with pytest.raises(YasdlError, match="default port"):
        Block("Reserved", "{W1}──R1──", R1=R())


def test_programmatic_aliases():
    blk = Block("S", "──R1──R2──", port_attrs={"W0": {"aliases": ["in"]}, "D1": {"aliases": ["out"]}},
                R1=R(), R2=R())
    assert blk.port("in").side == "W" and blk.port("out").side == "E"
    with pytest.raises(YasdlError, match="two ports"):
        Block("S", "{in}──R1──", port_attrs={"E0": {"aliases": ["IN"]}}, R1=R())
    with pytest.raises(YasdlError, match="unsupported"):
        Block("S", "──R1──", port_attrs={"W0": {"direction": "in"}}, R1=R())
    with pytest.raises(YasdlError, match="matches no port"):
        Block("S", "──R1──", port_attrs={"nope": {"aliases": ["x"]}}, R1=R())
    with pytest.raises(YasdlError, match="default port"):
        Block("S", "──R1──", port_attrs={"W0": {"aliases": ["D7"]}}, R1=R())


def test_global_nets_cross_blocks():
    pull = Block("Pull", """
        ──R1──[VCC]
    """, R1=R())
    top = Block("Top", """
        ──P

        [VCC]──R2──
    """, P=pull, R2=R())
    nets = netlist(top)
    assert {"P.R1.2", "R2.1"} <= set(nets["VCC"]) or {"P.R1.1", "R2.1"} <= set(nets["VCC"])


def test_local_label_stays_in_block():
    inner = Block("Inner", """
        ──[x]──R1──
    """, R1=R())  # inline label: a local net name
    top = Block("Top", "──A──B──", A=inner, B=inner)
    nets = netlist(top)
    assert "x" not in nets  # local names don't leak (and don't merge the two instances)


def test_pin_labels_match_subblock_port_names():
    host = Block("Host", """
             │
            [c]
            DDDD
            DDDD[b]──
            DDDD
             │
    """, D=ex.DARLINGTON)  # re-exported names B/C/E orient the sub-block (mirrored)
    b = host.bound["D"]
    assert {att.side: ex.DARLINGTON.ports[k].name for att, k in b.pin_map} == {
        "N": "C", "E": "B", "S": "E"}


def test_power_net_labels_draw_power_symbols():
    from yasdl.layout import layout
    blk = Block("Pd", """
        ──R1──┐
              │
            [GND]
    """, R1=R())
    res = layout(blk)
    assert [a.lib_id for _, a, *_ in res.symbols if a.symbol.is_power] == ["power:GND"]
    assert res.labels == []  # drawn as the symbol, not as a text label
    assert "R1.2" in netlist(blk)["GND"] or "R1.1" in netlist(blk)["GND"]


def test_label_orientation_prefers_mirror_over_rotation():
    from docs.examples.sgen import PHASE_SHIFT
    host = Block("H", "──PS[in]──", PS=PHASE_SHIFT)  # 'in' on the right: 180 deg or mirror y
    b = host.bound["PS"]
    assert (b.rot, b.mirror) == (180, "x")  # mirror y: one axis flipped, legs stay down
    assert host.to_dict()["components"]["PS"]["binding"]["mirror"] == "y"


def test_explicit_orientation_checked_against_labels():
    from docs.examples.sgen import OSCILLATOR, PHASE_SHIFT
    assert (OSCILLATOR.bound["PS"].rot, OSCILLATOR.bound["PS"].mirror) == (180, "x")  # mirrored y
    Block("H", "──PS[in]──", PS=PHASE_SHIFT.mirrored("y"))  # label agrees
    with pytest.raises(YasdlError, match="does not fit"):
        Block("H", "──PS[out]──", PS=PHASE_SHIFT.mirrored("y"))  # label contradicts


def test_rotated_mirrored_api():
    from docs.examples.sgen import PHASE_SHIFT
    assert (R().mirrored("y").rot, R().mirrored("y").mirror) == (180, "x")
    assert R().mirrored("y").mirrored("y").rot % 360 == 0 and R().mirrored("y").mirrored("y").mirror is None
    assert PHASE_SHIFT.rotated(90).rot == 90
    host = Block("H", "──PS──", PS=PHASE_SHIFT.mirrored("y"))
    assert {att.side: PHASE_SHIFT.ports[k].name for att, k in host.bound["PS"].pin_map} == \
        {"W": "out", "E": "in"}


def test_sketch_builds_canvases():
    from yasdl import Sketch
    s = Sketch().text(0, 0, "{in}").hline(0, 4, 5).text(0, 6, "R1").hline(0, 8, 9).text(0, 10, "┐")
    s.vline(10, 1, 1).text(2, 8, "[GND]")
    blk = Block("SK", s.render(), R1=R("1k"))
    assert blk.port("in").side == "W" and "GND" in netlist(blk)
