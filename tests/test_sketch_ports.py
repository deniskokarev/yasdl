"""N3: Sketch.render() rejects a {port} that is not on the canvas edge, at draw
time (before Block parsing), naming the port and its distance from the edge."""

import pytest

from yasdl import Block, R, Sketch, SketchError


def test_east_port_inside_edge_is_rejected_with_distance():
    s = Sketch()
    s.hline(0, 0, 3).text(0, 4, "{out}").text(0, 10, "R1")
    with pytest.raises(SketchError, match=r"port \{out\}.*3 cell\(s\) inside the east edge"):
        s.render()


def test_west_port_inside_edge_is_rejected_with_distance():
    s = Sketch()
    s.text(0, 2, "{in}").hline(0, 6, 9).text(0, 12, "R1").hline(1, 0, 1)
    with pytest.raises(SketchError, match=r"port \{in\}.*2 cell\(s\) inside the west edge"):
        s.render()


def test_south_port_inside_edge_is_rejected_with_distance():
    s = Sketch()
    s.vline(2, 0, 1).text(2, 0, "{fb}").text(4, 0, "R1")
    with pytest.raises(SketchError, match=r"port \{fb\}.*inside the south edge"):
        s.render()


def test_ports_on_the_edge_render_and_parse():
    s = Sketch()
    s.text(0, 0, "{in}").hline(0, 4, 6).text(0, 7, "R1").hline(0, 9, 11).text(0, 12, "{out}")
    canvas = s.render()
    block = Block("Ports", canvas, R1=R("1k"))
    assert {p.name for p in block.ports} == {"in", "out"}


def test_pin_label_next_to_component_is_not_a_port():
    # {b} touches the Q1 box mid-canvas: a pin label, not an edge port.
    s = Sketch()
    s.text(1, 0, "{b}").box(1, 4, "Q1Q1", rows=3)
    assert "{b}" in s.render()
