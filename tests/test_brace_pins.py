"""Brace pin labels and interface declarations are distinguished by adjacency."""

import pytest

from yasdl import Block, CanvasError, netlist, NPN, R, spice_netlist
from yasdl.canvas import Canvas
from yasdl.kicad_lib import JELLYBEAN_MODEL, KICAD_CLI


TRANSISTOR = """
           [VCC]
              │
             {c}
{input}────{b}Q1
             {e}
              │
            [GND]
"""


def test_braces_identify_component_pins_and_interface():
    block = Block("NamedPins", TRANSISTOR, Q1=NPN("2N3904"))
    assert netlist(block) == {"VCC": ["Q1.C"], "input": ["Q1.B"], "GND": ["Q1.E"]}
    assert [(p.name, p.side) for p in block.ports] == [("input", "W")]


@pytest.mark.parametrize("column", [1, 2, 3])
def test_vertical_brace_may_overlap_component_and_wire_at_different_columns(column):
    canvas = Canvas("Q1\n {e}\n" + " " * column + "│")
    label = canvas.labels[0]
    attachment = canvas.comps["Q1"].attachments["S"][0]
    assert label.kind == "pin" and label.vcol == column
    assert attachment.pos == 1 and attachment.pin_label == "e"


@pytest.mark.parametrize("canvas", ["Q1Q1Q1\n {e}\n  │", "   │\n {c}\nQ1"])
def test_vertical_brace_adjacency_above_and_below(canvas):
    assert Canvas(canvas).labels[0].kind == "pin"


def test_brace_after_wire_bend_declares_interface():
    block = Block(
        "BentInterface", "   [VCC]\n      │\n     {c}\n{b}─Q1\n     └{e}", Q1=NPN()
    )
    assert [(p.name, p.side) for p in block.ports] == [("e", "E"), ("b", "W")]
    assert netlist(block) == {"VCC": ["Q1.C"], "b": ["Q1.B"], "e": ["Q1.E"]}


@pytest.mark.parametrize("canvas", ["Q1{b}Q2", "Q1 Q2\n {e}"])
def test_brace_cannot_touch_two_components(canvas):
    with pytest.raises(CanvasError, match="several component edges"):
        Canvas(canvas)


def test_unattached_brace_needs_wire():
    with pytest.raises(CanvasError, match="exactly one wire"):
        Canvas("   [VCC]\n      │\n     {c}\n{b}─Q1\n      {e}")


@pytest.mark.parametrize("canvas", ["─[1]R1─", "R1\n[1]\n │"])
def test_square_pin_labels_report_migration(canvas):
    with pytest.raises(CanvasError, match="square brackets name nets"):
        Canvas(canvas)


@pytest.mark.parametrize("column", range(5))
def test_vertical_net_wire_may_enter_any_bracket_column(column):
    canvas = Canvas("[Sig]\n" + " " * column + "│")
    assert canvas.labels[0].kind == "global"
    assert canvas.labels[0].vcol == column


def test_two_vertical_net_wires_must_share_one_column():
    with pytest.raises(CanvasError, match="share one column"):
        Canvas("│\n[Sig]\n    │")


def test_numeric_pin_and_interface_names_remain_supported():
    assert netlist(Block("NumberedPin", "─{1}R1─", R1=R("1k")))
    block = Block("NumberedInterface", "{1}─R1─{2}", R1=R("1k"))
    assert ".subckt numbered 1 2" in spice_netlist(
        block, subckt="numbered", port_order=["1", "2"]
    )


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(), reason="kicad-cli missing")
def test_offset_vertical_pin_label_renders_and_roundtrips(tmp_path):
    from yasdl.kicad_export import render

    block = Block(
        "OffsetPins", "   [VCC]\n      │\n     {c}\n{b}─Q1\n     └{e}", Q1=NPN("2N3904")
    )
    info = render(
        block, tmp_path, svg=False, spice_libs=(str(JELLYBEAN_MODEL),), spice=True
    )
    assert info["roundtrip_ok"] and info["spice_ok"] and info["erc"] == []
