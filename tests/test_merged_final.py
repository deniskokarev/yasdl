"""Contracts settled when the a1/a2 and a3/a4 libraries were combined."""

import re
import shutil
import subprocess

import pytest
from yasdl import Block, POT, Pot, R, spice_netlist
from yasdl.kicad_export import spice_roundtrip


@pytest.mark.parametrize("position", [0, 0.5, 1])
def test_pot_keyword_form_uses_canonical_terminals(position):
    # One pot convention for POT and Pot: pin 1 = ccw end, 2 = wiper, 3 = cw end.
    pot = Pot("100k", position=position)
    assert dict(pot.aliases) == {"ccw": "1", "w": "2", "wiper": "2", "cw": "3"}
    assert dict(POT("100k", position).aliases) == dict(pot.aliases)
    assert f"P={position:g}" in pot.spice.params
    assert pot.spice.model == POT("100k").spice.model == "yasdl_pot"


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice missing")
@pytest.mark.parametrize(
    "pot,expected",
    [
        (Pot("10k", position=0.25), 3.0),  # P: electrical fraction from ccw
        (POT("10k", 0.25), 3.0),  # POS, linear taper
        (POT("10k", 0.5, "log"), 12 * 8 / 80),  # audio taper: (81^0.5 - 1)/80 at mid
        (Pot("10k", position=0.5, taper="rlog"), 12 * (1 - 8 / 80)),
    ],
)
def test_shared_pot_model_reads_fraction_and_shaft_position(tmp_path, pot, expected):
    b = Block(
        "Pot",
        "[VCC]─{cw}P1{ccw}─[GND]\n         {wiper}\n            │\n          {out}",
        P1=pot,
    )
    deck = tmp_path / "pot.cir"
    deck.write_text(
        spice_netlist(b, subckt="pot")
        + "V1 VCC 0 12\nX1 out pot\n.control\nop\nprint v(out)\n.endc\n.end\n"
    )
    r = subprocess.run(["ngspice", "-b", str(deck)], capture_output=True, text=True)
    assert r.returncode == 0 and "error" not in (r.stdout + r.stderr).lower(), r.stdout
    assert float(re.search(r"v\(out\) = (\S+)", r.stdout)[1]) == pytest.approx(
        expected, abs=1e-5
    )


def test_unreadable_spice_deck_is_a_mismatch_not_a_crash():
    b = Block("One", "{a}─R1─{b}", R1=R("1k"))
    ok, why = spice_roundtrip(b, None, {"R1": "R1"}, kicad_text="R1 a\n")
    assert not ok and "unreadable" in why
    ok, why = spice_roundtrip(b, None, {"R1": "R1"}, kicad_text="R1 a b 1k\n")
    assert ok, why


def test_standard_topologies_are_literal_canvases():
    # Every reusable topology is written as inspectable ASCII in the library source.
    from pathlib import Path

    import yasdl

    for module in ("std.py", "circuits.py"):
        source = (Path(yasdl.__file__).parent / module).read_text()
        assert "Sketch" not in source, module

