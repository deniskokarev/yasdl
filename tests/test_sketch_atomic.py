import pytest
from yasdl import Block, Sketch, SketchError
from yasdl.layout import layout


def test_route_elbows_and_reversed_coordinates():
    s = Sketch().wire([(0, 0), (0, 3), (3, 3), (3, 1)])
    assert s.render() == "───┐\n   │\n   │\n ──┘"
    assert Sketch().hline(0, 3, 0).render() == "────"
    assert Sketch().vline(0, 2, 0).render() == "│\n│\n│"


@pytest.mark.parametrize("old", ["R1", "{a}", "[VCC]", "─", "│", "┌", "├", "┼"])
def test_text_never_overwrites_even_identical(old):
    s = Sketch().text(1, 3, old)
    before = s.render()
    with pytest.raises(ValueError, match="collision.*row 1, col 3"):
        s.text(1, 3, old)
    assert s.render() == before


def test_late_box_and_wire_collisions_are_atomic():
    s = Sketch().text(4, 8, "X1")
    before = s.render()
    with pytest.raises(ValueError):
        s.box(2, 8, "X1", rows=4)
    assert s.render() == before
    with pytest.raises(ValueError):
        s.wire([(0, 0), (0, 8), (6, 8)])
    assert s.render() == before


def test_crossing_count_and_separate_nets():
    s = Sketch().hline(3, 0, 6)
    before = s.render()
    with pytest.raises(ValueError, match="found 1.*created 1"):
        s.vline(3, 0, 6)
    assert s.render() == before
    s.vline(3, 0, 6, cross=1)
    assert s.crossings == {(3, 3)}
    block = Block("Cross", s.render())
    assert block.crossing_count == 1
    # All four external ports: N/S join; E/W join; the axes remain distinct.
    d = block.to_dict()["nets"]
    assert {frozenset(n["ports"]) for n in d.values()} == {
        frozenset(("N0", "S0")),
        frozenset(("E0", "W0")),
    }
    before = s.render()
    with pytest.raises(ValueError):
        s.hline(3, 0, 6, cross=1)
    assert s.render() == before


@pytest.mark.parametrize(
    "points",
    [
        [(0, 0), (1, 1)],
        [(0, 0), (0, 0)],
        [(0, 0)],
        [(0, 0), (0, 2), (0, 0)],
        [(-1, 0), (0, 0)],
        [(-1, 0), (-1, 2)],
        [(0.5, 0), (0, 0)],
    ],
)
def test_invalid_routes_leave_canvas_unchanged(points):
    s = Sketch().text(7, 7, "R1")
    before = s.render()
    with pytest.raises(SketchError):  # a ValueError
        s.wire(points)
    assert s.render() == before
    empty = Sketch()
    with pytest.raises(SketchError):
        empty.wire(points)
    assert empty.render() == ""


@pytest.mark.parametrize("operation", ["end", "same", "bend", "tee", "count"])
def test_wire_crossing_is_only_exception(operation):
    s = Sketch().hline(3, 1, 7)
    if operation == "bend":
        s.text(3, 9, "┌")
    if operation == "tee":
        s.text(3, 9, "├")
    before = s.render()
    with pytest.raises(ValueError):
        if operation == "end":
            s.vline(4, 0, 3, cross=1)
        elif operation == "same":
            s.hline(3, 0, 8)
        elif operation == "bend":
            s.vline(9, 0, 6, cross=1)
        elif operation == "tee":
            s.vline(9, 0, 6, cross=1)
        else:
            s.vline(4, 0, 6, cross=2)
    assert s.render() == before


def test_composition_preserves_crossings_without_adapter_crossings():
    child = Block("Crossing", "{top}\n  │\n──│──\n  │\n{bot}")
    parent = Block(
        "Composed",
        """
       {top}
         │
    {a}──X1──{b}
         │
       {bot}
    """,
        X1=child,
    )
    assert parent.crossing_count == 1
    result = layout(parent)
    # Count distinct proper geometric intersections, independent of Canvas counters.
    h = [
        (min(a[0], b[0]), max(a[0], b[0]), a[1])
        for a, b in result.wires
        if a[1] == b[1]
    ]
    v = [
        (a[0], min(a[1], b[1]), max(a[1], b[1]))
        for a, b in result.wires
        if a[0] == b[0]
    ]
    crossings = {
        (x, y)
        for left, right, y in h
        for x, top, bot in v
        if left < x < right and top < y < bot
    }
    assert len(crossings) == parent.crossing_count


@pytest.mark.parametrize("orientation", [(0, None), (90, None), (180, "x")])
def test_repeated_oriented_children_add_to_parent_crossing_count(orientation):
    child = Block("Child", "{top}\n  │\n──│──\n  │\n{bot}")
    s = Sketch().text(0, 7, "{ta}").text(0, 18, "{mid}").text(0, 27, "{tb}")
    s.box(2, 8, "X1").box(2, 28, "X2")
    for col in (8, 20, 28):
        s.vline(col, 1, 1).vline(col, 3, 3)
    s.vline(20, 2, 2)
    s.hline(2, 0, 7).hline(2, 10, 27, cross=1).hline(2, 30, 38)
    s.text(4, 7, "{ba}").text(4, 18, "{midbot}").text(4, 27, "{bb}")
    b = Block(
        "Parent", s.render(), X1=child.oriented(*orientation), X2=child.mirrored("y")
    )
    assert b.crossing_count == 3
    result = layout(b)
    h = [
        (min(a[0], q[0]), max(a[0], q[0]), a[1])
        for a, q in result.wires
        if a[1] == q[1]
    ]
    v = [
        (a[0], min(a[1], q[1]), max(a[1], q[1]))
        for a, q in result.wires
        if a[0] == q[0]
    ]
    crossings = {
        (x, y)
        for left, right, y in h
        for x, top, bot in v
        if left < x < right and top < y < bot
    }
    assert len(crossings) == 3
