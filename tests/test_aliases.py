"""Comma-separated port aliases in {} and the name grammar (spec 2.7, 2.8)."""

import pytest

from yasdl import NPN, OPAMP, R, Block, D, YasdlError, netlist


def test_comma_aliases():
    blk = Block("Q", """
                         {c, collector}
                              │
        {b, base}──────────[b]Q1Q1
                              Q1Q1
                              Q1Q1
                              │
                           {e,emitter}
    """, Q1=NPN("2N3904"))
    for key in ("c", "collector", "b", "base", "e", "emitter"):
        assert blk.port(key)
    assert blk.port("collector").name == "c" and blk.port("collector").aliases == ("c", "collector")


def test_shortcuts_are_never_the_display_name():
    blk = Block("P", "{+, non_inv, noninverting, plus}──R1──{out}", R1=R())
    p = blk.port("plus")
    assert p.name == "non_inv" and "+" in p.aliases
    host = Block("H", "{a}──+PX──{b}", PX=blk)  # the + shortcut answers the port
    assert netlist(host)["a"] == ["PX.R1.1"]


def test_diode_block_with_arrow_and_names():
    dio = Block("Dio", "{>,A,Anode}──D1──{K,Cathode}", D1=D("1N4148").mirrored("y"))
    assert dio.port("Anode").name == "A"
    Block("H", "{x}──>DX──{y}", DX=dio)            # arrow form
    Block("H", "{x}──[Anode]DX──{y}", DX=dio)      # name form
    with pytest.raises(YasdlError, match="does not fit"):
        Block("H", "{x}──[Cathode]DX──{y}", DX=dio.rotated(90))  # a vertical block in a row


def test_two_arrows_on_one_port():
    both = Block("B", "{<,>}──R1──{out}", R1=R())  # this port answers either arrow
    Block("H", "{a}──<X──{b}", X=both)
    Block("H", "{a}──>X──{b}", X=both)
    with pytest.raises(YasdlError, match="two ports"):
        Block("B", "{<,>}──R1──{>}", R1=R())  # > on the opposite side: alias conflict


@pytest.mark.parametrize("label,msg", [
    ("{non-inv}", "letters, digits"),
    ("{a b}", "letters, digits"),
    ("{a,,b}", "empty alias"),
    ("{a, A}", "listed twice"),
    ("{a, W1}", "default port"),
    ("{x, GND}", "reserved"),
])
def test_alias_errors(label, msg):
    with pytest.raises(YasdlError, match=msg):
        Block("B", f"{label}──R1──{{out}}", R1=R())


def test_net_label_grammar():
    with pytest.raises(YasdlError, match="letters, digits"):
        Block("B", "{in}──R1──[a-b]──R2──{out}", R1=R(), R2=R())
    blk = Block("B", "{in}──R1──┐\n          │\n        [-12V]", R1=R())  # registered power net
    assert "-12V" in netlist(blk)


def test_pin_labels_stay_free_form():
    # the op-amp's inverting input is named "-" in KiCad: pin labels may use any name
    amp = Block("A", """
             [VEE]
               │
        ──[-]U1U1
             U1U1──
          ┌─+U1U1
          │    │
        [GND] [VCC]
    """, U1=OPAMP())
    # [-] matches pin 2 (named "-") on top, + matches pin 1 below: the op-amp is mirrored
    assert [pin for att, pin in amp.bound["U1"].pin_map if att.side == "W"] == ["2", "1"]
