"""P1: strict Sketch placement, deliberate crossings, explicit routes (spec 7.1), and
render(export_name=...) (spec 6.1)."""

import pytest
from yasdl import Block, netlist, R, Sketch
from yasdl.kicad_lib import KICAD_CLI
from yasdl.sketch import SketchError

kicad = pytest.mark.skipif(not KICAD_CLI.exists(), reason="kicad-cli missing")


def snapshot(s):
    return dict(s.cells), set(s.crossings), s.render()


def test_route_generates_corner_glyphs():
    s = Sketch().wire([(0, 0), (0, 6), (3, 6)])
    assert s.render() == "──────┐\n      │\n      │\n      │"
    s = Sketch().wire([(3, 0), (0, 0), (0, 4), (2, 4), (2, 7)])
    assert s.render().splitlines() == ["┌───┐", "│   │", "│   └───", "│"]
    # collinear intermediate points stay straight
    assert Sketch().wire([(0, 0), (0, 3), (0, 6)]).render() == "───────"


@pytest.mark.parametrize(
    "points, match",
    [([(0, 0)], "at least two"), ([(0, 0), (2, 3)], "diagonal"),
     ([(0, 0), (0, 4), (0, 1)], "reverses"), ([(0, 0), (0, 0)], "repeated"),
     ([(0, 0), (0, 3), (2, 3), (2, 1), (0, 1)], "twice"), ([(0, -1), (0, 2)], "negative")],
)
def test_invalid_routes(points, match):
    with pytest.raises(SketchError, match=match):
        Sketch().wire(points)


def test_crossing_requires_declaration_and_leaves_canvas_unchanged_on_mismatch():
    s = Sketch().hline(2, 0, 8)
    before = snapshot(s)
    with pytest.raises(SketchError, match=r"creates 1 crossing\(s\) at \[\(2, 4\)\].*cross=0"):
        s.vline(4, 0, 4)
    assert snapshot(s) == before
    with pytest.raises(SketchError, match="creates 1 crossing"):
        s.vline(4, 0, 4, cross=2)
    assert snapshot(s) == before
    s.vline(4, 0, 4, cross=1)
    assert s.crossings == {(2, 4)} and s.crossing_count == 1
    assert s.cells[(2, 4)] == "─"  # the existing wire stays on top


def test_crossing_on_a_real_block_keeps_nets_separate():
    s = Sketch()
    s.text(0, 6, "{t}").vline(7, 1, 1).text(2, 7, "R1").vline(7, 3, 6).text(7, 6, "{u}")
    s.text(5, 0, "{a}").hline(5, 3, 11, cross=1).text(5, 12, "R2").hline(5, 14, 15).text(5, 16, "{b}")
    canvas = s.render()
    assert canvas.splitlines()[5] == "{a}────│────R2──{b}"
    nets = netlist(Block("Cross", canvas, R1=R("1k"), R2=R("1k")))
    assert sorted(nets["a"]) == ["R2.1"] and sorted(nets["u"]) == ["R1.2"]


@pytest.mark.parametrize(
    "draw, reason",
    [
        (lambda s: s.text(0, 3, "X"), "text never overwrites"),
        (lambda s: s.text(0, 2, "─"), "text never overwrites"),  # identical glyph
        (lambda s: s.hline(0, 4, 6), "same axis"),
        (lambda s: s.hline(0, 0, 9), "same axis"),
        (lambda s: s.wire([(4, 0), (4, 9)], cross=1), "elbow, tee or junction"),
        (lambda s: s.vline(8, 3, 6), "components, labels or text"),
        (lambda s: s.wire([(3, 1), (2, 1)]), "continues on both sides"),  # ends on a wire
        (lambda s: s.wire([(0, 2), (0, 2)]), "repeated"),
        (lambda s: s.vline(1, 1, 2), "continues on both sides"),
        (lambda s: s.vline(2, 1, 4), "elbow, tee or junction"),
        (lambda s: s.junction(0, 2, "NES"), "text never overwrites"),
        (lambda s: s.box(3, 8, "R9", rows=2), "a component never overwrites"),
    ],
)
def test_overwrites_are_rejected_without_changes(draw, reason):
    s = Sketch().hline(0, 0, 5)            # row 0: ──────
    s.wire([(2, 0), (2, 4), (6, 4)])         # an elbow at (2, 4)
    s.text(4, 7, "{x}").text(4, 2, "┬")      # a label and an explicit tee
    before = snapshot(s)
    with pytest.raises(SketchError) as err:
        draw(s)
    assert reason in str(err.value)
    assert "Nothing was drawn" in str(err.value) or "repeated" in str(err.value)
    assert snapshot(s) == before


def test_existing_crossing_cannot_be_crossed_again():
    s = Sketch().hline(2, 0, 6).vline(3, 0, 4, cross=1)
    before = snapshot(s)
    with pytest.raises(SketchError, match="existing crossing already uses both axes"):
        s.wire([(2, 3), (2, 9)])
    with pytest.raises(SketchError, match="text never overwrites"):
        s.text(2, 3, "+")
    assert snapshot(s) == before


def test_collision_diagnostic_names_location_content_and_operation():
    s = Sketch().text(1, 4, "R1")
    with pytest.raises(SketchError) as err:
        s.wire([(1, 0), (1, 8)])
    msg = str(err.value)
    assert "Sketch.wire([(1, 0), (1, 8)])" in msg
    assert "(row 1, col 4) already holds 'R' from text(1, 4, 'R1')" in msg


def test_late_collision_leaves_long_route_undrawn():
    s = Sketch().text(9, 20, "R1")
    with pytest.raises(SketchError):
        s.wire([(0, 0), (0, 20), (12, 20)])
    assert s.cells == {(9, 20): "R", (9, 21): "1"}


def test_explicit_junction():
    s = Sketch().hline(0, 0, 3).junction(0, 4, "EWS").hline(0, 5, 8).vline(4, 1, 2)
    assert s.render().splitlines()[0] == "────┬────"
    with pytest.raises(SketchError, match="three or four"):
        Sketch().junction(0, 0, "NS")


# --- composition: crossings come only from the canvases ------------------------------------
def test_composed_layout_adds_no_crossings():
    from docs.examples import blocks, sgen
    from yasdl.layout import drawn_crossings, layout, wire_crossings

    cross = Block(
        "Cross",
        """
    {t}
     │
{a}──│──R2──{b}
     R1
     │
    {u}
""",
        R1=R("1k"), R2=R("1k"),
    )
    parent = Block(
        "TwoCross",
        """
     {ta}     {tb}
      │        │
{w}───C1───────C2───{e}
      │        │
{x}───│────────│────{y}
      │        │
     {ua}     {ub}
""",
        C1=cross, C2=cross,
    )
    designs = [cross, parent, *blocks.ALL.values(), *sgen.ALL.values()]
    for design in designs:
        found = wire_crossings(layout(design).wires)
        assert len(found) == drawn_crossings(design), design.name
    assert drawn_crossings(parent) == 4


# --- export names ---------------------------------------------------------------------------
DARL = Block(
    "Darl",
    """
            │
        ┌───┴───┐
        │       │
        Q1      Q2
    ────Q1   ┌──Q2
        Q1   │  Q2
        │    │  │
        └────┘  │
""",
)


@pytest.mark.integration
@kicad
def test_export_name_renders_two_variants_of_one_template(tmp_path):
    from yasdl import NPN, PNP
    from yasdl.kicad_export import render

    upper = DARL.bind(Q1=NPN("2N3904"), Q2=NPN("2N3904"))
    lower = DARL.bind(Q1=PNP("2N3906"), Q2=PNP("2N3906"))
    a = render(upper, tmp_path, export_name="DarlN")
    b = render(lower, tmp_path, export_name="DarlP")
    for info, stem in ((a, "DarlN"), (b, "DarlP")):
        assert info["schematic"] == tmp_path / f"{stem}.kicad_sch"
        assert info["svg"] == tmp_path / f"{stem}.svg" and info["svg"].exists()
        assert (tmp_path / f"{stem}.kicad_pro").exists()
        assert info["roundtrip_ok"] and info["erc"] == []
    assert "Q_PNP" in b["schematic"].read_text() and "Q_PNP" not in a["schematic"].read_text()
    assert upper.name == lower.name == "Darl"  # the blocks are unchanged
    assert not (tmp_path / "Darl.kicad_sch").exists()
    default = render(upper, tmp_path, svg=False)
    assert default["schematic"] == tmp_path / "Darl.kicad_sch"


@pytest.mark.parametrize("bad", ["", "sub/name", "..", "."])
def test_export_name_must_be_a_stem(tmp_path, bad):
    from yasdl.kicad_export import render

    from yasdl import NPN

    with pytest.raises(ValueError, match="plain file stem"):
        render(DARL.bind(Q1=NPN("Q"), Q2=NPN("Q")), tmp_path, export_name=bad)
