"""P1.1/P1.2: strict Sketch placement, explicit routes, deliberate crossings (DECISIONS P1)."""

import pytest
from yasdl import Block, netlist, R, Sketch
from yasdl.sketch import SketchError


def snapshot(s):
    return dict(s.cells), set(s.crossing_cells)


def test_route_generates_elbows():
    s = Sketch().wire([(0, 0), (0, 6), (3, 6)])
    assert s.render() == "──────┐\n      │\n      │\n      │"
    s = Sketch().wire([(2, 0), (2, 3), (0, 3), (0, 6), (2, 6)])
    assert s.render() == "   ┌──┐\n   │  │\n───┘  │"




def _base():
    """{in}──R1──┐ with a vertical wire below the elbow and a label."""
    s = Sketch().text(0, 0, "{in}").hline(0, 4, 5).text(0, 6, "R1").hline(0, 8, 9)
    s.text(0, 10, "┐").vline(10, 1, 3).text(4, 8, "[GND]")
    return s


@pytest.mark.parametrize(
    "op, match",
    [
        (lambda s: s.text(0, 6, "R2"), "already holds 'R'"),  # component text
        (lambda s: s.text(4, 9, "X"), "already holds 'G'"),  # label text
        (lambda s: s.box(0, 4, "U1"), "already holds '─'"),  # box over a wire
        (lambda s: s.text(0, 4, "─"), "already holds '─'"),  # identical glyph repaint
        (lambda s: s.hline(0, 3, 4), "already holds"),  # same-direction overlap
        (lambda s: s.vline(4, 0, 2), "already holds"),  # wire ends on a wire
        (lambda s: s.hline(0, 9, 11), "already holds"),  # through the elbow
        (lambda s: s.wire([(2, 7), (2, 10), (3, 10)]), "already holds"),  # turns on a wire
        (lambda s: s.hline(2, 11, 14), "implied T"),  # dead end against a wire's side
        (lambda s: s.text(2, 11, "R9"), None),  # text beside a wire is fine
    ],
)
def test_collisions_are_rejected_without_changes(op, match):
    s = _base()
    before = snapshot(s)
    if match is None:
        op(s)
        return
    with pytest.raises(SketchError, match=match):
        op(s)
    assert snapshot(s) == before


def test_late_collision_in_a_long_wire_leaves_nothing_behind():
    s = _base()
    before = snapshot(s)
    with pytest.raises(SketchError, match=r"row 4, col 9"):
        s.wire([(6, 0), (6, 9), (3, 9)])  # 11 free cells, then it runs through [GND]
    assert snapshot(s) == before


def test_error_names_location_content_and_operation():
    s = _base()
    with pytest.raises(SketchError) as e:
        s.hline(0, 8, 12)
    msg = str(e.value)
    assert "hline(0, 8, 12)" in msg and "row 0, col 8" in msg and "'─'" in msg


def test_crossing_needs_explicit_count():
    s = _base()
    before = snapshot(s)
    with pytest.raises(SketchError, match=r"creates 1 crossing\(s\) at \(2, 10\), expected cross=0"):
        s.hline(2, 8, 12)
    assert snapshot(s) == before
    s.hline(2, 8, 12, cross=1)
    assert s.crossings == 1
    assert s.cells[(2, 10)] == "│"  # the existing wire stays on top


def test_crossing_count_must_match_exactly():
    s = Sketch().vline(2, 0, 4).vline(5, 0, 4)
    with pytest.raises(SketchError, match="creates 2"):
        s.hline(2, 0, 7, cross=1)
    s.hline(2, 0, 7, cross=2)
    assert s.crossings == 2


@pytest.mark.parametrize(
    "op",
    [
        lambda s: s.hline(2, 10, 12, cross=1),  # the crossing would be the wire's end
        lambda s: s.vline(10, 2, 2, cross=1),  # parallel overlap is never a crossing
        lambda s: s.wire([(2, 8), (2, 10), (5, 10)], cross=1),  # corner on a wire
    ],
)
def test_unclean_crossings_are_rejected(op):
    s = _base()
    before = snapshot(s)
    with pytest.raises(SketchError):
        op(s)
    assert snapshot(s) == before


def test_existing_crossing_and_junctions_cannot_be_crossed():
    s = _base().hline(2, 8, 12, cross=1)
    before = snapshot(s)
    with pytest.raises(SketchError, match="already holds crossing"):
        s.vline(10, 2, 2, cross=1)
    s.vline(14, 0, 4)
    with pytest.raises(SketchError, match="already holds '┐'"):
        s.vline(10, 0, 0)
    assert snapshot(s)[0] == {**before[0], **{(r, 14): "│" for r in range(5)}}
    t = Sketch().hline(1, 0, 1).hline(1, 3, 4).vline(2, 2, 3)
    t.junction(1, 2)
    with pytest.raises(SketchError, match="already holds '┬'"):
        t.vline(2, 0, 2, cross=1)


def test_route_crossing_itself_counts():
    s = Sketch().wire([(0, 2), (4, 2), (4, 4), (2, 4), (2, 0)], cross=1)
    assert s.crossings == 1 and s.cells[(2, 2)] == "│"


def test_junction_is_explicit():
    with pytest.raises(SketchError, match="only 0 wire"):
        Sketch().junction(0, 0)
    s = Sketch().text(0, 0, "{a}").hline(0, 3, 5).hline(0, 7, 9).text(0, 10, "{b}")
    s.vline(6, 1, 1).text(2, 6, "R1").vline(6, 3, 3).text(4, 4, "[GND]")
    with pytest.raises(SketchError, match="only 2 wire"):
        Sketch().hline(0, 0, 1).hline(0, 3, 4).junction(0, 2)
    s.junction(0, 6)
    assert s.cells[(0, 6)] == "┬"
    nets = netlist(Block("J", s.render(), R1=R("1k")))
    assert sorted(nets.values()) == [["R1.1"], ["R1.2"]]  # ports a and b are one net


def test_crossing_keeps_two_nets():
    s = Sketch().text(0, 4, "{top}").vline(6, 1, 1).text(2, 6, "R1").vline(6, 3, 5)
    s.text(6, 4, "[GND]")
    s.text(4, 0, "{a}").hline(4, 3, 9, cross=1).text(4, 10, "R2").hline(4, 12, 13)
    s.text(4, 14, "{b}")
    nets = netlist(Block("X", s.render(), R1=R("1k"), R2=R("2k")))
    assert nets["top"] == ["R1.1"] and nets["a"] == ["R2.1"]
    assert nets["GND"] == ["R1.2"] and nets["b"] == ["R2.2"]


def test_straight_glyph_must_match_axis():
    with pytest.raises(SketchError):
        Sketch().hline(0, 0, 3, ch="│")


# --- composition adds no crossings (P1.1 clarified claim) ---------------------------------
def _crossing_child():
    s = Sketch().text(0, 4, "{top}").vline(6, 1, 1).text(2, 6, "R1").vline(6, 3, 5)
    s.text(6, 4, "[GND]")
    s.text(4, 0, "{a}").hline(4, 3, 9, cross=1).text(4, 10, "R2").hline(4, 12, 13)
    s.text(4, 14, "{b}")
    return Block("CrossChild", s.render(), R1=R("1k"), R2=R("2k"))


def test_composed_crossings_are_the_sum_of_drawn_ones():
    from yasdl.layout import layout, wire_crossings

    child = _crossing_child()
    parent = Block(
        "CrossParent",
        """
               ┌───────────┐
               │           │
        {i}────CA────┐  ┌──CB───{o}
                     │  │
        {q}──────────│──┘
                     │
                   [GND]
        """,
        CA=child,
        CB=child,
    )
    assert parent.crossing_count() == 3
    assert len(wire_crossings(layout(parent))) == 3


@pytest.mark.parametrize("name", ["SGEN", "CROSSING_SUPPLY", "SERIES_PARALLEL", "SHUNT"])
def test_examples_have_only_drawn_crossings(name):
    import docs.examples.blocks as ex
    import docs.examples.sgen as sg
    from yasdl.layout import layout, wire_crossings

    block = {**ex.ALL, "SGEN": sg.SGEN}[name]
    assert len(wire_crossings(layout(block))) == block.crossing_count()


def test_route_ends_may_anchor_on_labels_components_and_junctions():
    s = Sketch().text(0, 4, "{b}").box(0, 7, "Q1", rows=2)
    before = dict(s.cells)
    s.wire([(0, 4), (0, 3), (3, 3), (3, 0)])  # starts on the brace label: ┌ at (0, 3)
    assert s.cells[(0, 3)] == "┌" and s.cells[(3, 3)] == "┘" and s.cells[(3, 0)] == "─"
    assert all(s.cells[k] == v for k, v in before.items())
    # a route may also end on a component cell (it attaches to its edge)
    s.wire([(5, 0), (5, 7), (1, 7)])
    assert s.cells[(5, 7)] == "┘" and s.cells[(2, 7)] == "│" and s.cells[(1, 7)] == "Q"


def test_route_anchored_on_a_junction_arm():
    t = Sketch().text(1, 3, "┬").hline(1, 0, 2).hline(1, 4, 6)
    t.wire([(1, 3), (3, 3), (3, 6)])  # leaves the tee through its S arm
    assert t.cells[(2, 3)] == "│" and t.cells[(3, 3)] == "└"
    assert t.render().splitlines()[1:] == ["───┬───", "   │", "   └───"]


def test_anchor_must_be_a_real_attachment():
    u = Sketch().hline(0, 0, 4)
    with pytest.raises(SketchError):
        u.wire([(0, 2), (3, 2)])  # a straight wire is not an anchor: implied T
    v = Sketch().text(1, 3, "┴").hline(1, 0, 2).hline(1, 4, 6)
    with pytest.raises(SketchError):
        v.wire([(1, 3), (3, 3)])  # ┴ has no S arm
