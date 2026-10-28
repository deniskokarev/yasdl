"""P0 (DECISION 5): standard three-pin potentiometer with documented ccw/wiper/cw pins,
position direction, tapers and per-instance settings that survive the SPICE round trip."""

import re
import shutil
import subprocess

import pytest
from yasdl import Block, netlist, POT, spice_netlist, YasdlError
from yasdl.kicad_lib import KICAD_CLI

have_kicad = KICAD_CLI.exists()
have_ngspice = shutil.which("ngspice") is not None

VOLUME = """
   {in}──┐
         │
        {cw}
        VR1{w}──{out}
        {ccw}
         │
       [GND]
"""

TWO = """
   {in}──┬────────┐
         │        │
        {cw}     {cw}
        VR1{w}─┐ VR2{w}──{b}
        {ccw}  │ {ccw}
         │     │  │
       [GND]  {a}[GND]
"""


def test_pins_follow_role_labels():
    """Independent fixture: KiCad R_Potentiometer pin 1 = ccw, 2 = wiper, 3 = cw."""
    nets = netlist(Block("Vol", VOLUME, VR1=POT("10k")))
    assert nets["in"] == ["VR1.3"]
    assert nets["out"] == ["VR1.2"]
    assert nets["GND"] == ["VR1.1"]


def test_element_line_carries_value_position_and_taper():
    text = spice_netlist(Block("Vol", VOLUME, VR1=POT("50k", 0.25, "log")))
    assert re.search(r"^X_VR1 0 out in yasdl_pot R=50k POS=0.25 TAPER=1$", text, re.M)
    assert re.search(r"^\.include .*yasdl\.lib$", text, re.M)


@pytest.mark.parametrize(
    "kwargs, match",
    [
        (dict(position=-0.1), "within 0..1"),
        (dict(position=1.5), "within 0..1"),
        (dict(taper="audio"), "taper"),
        (dict(value="1M"), "MEG for mega"),
    ],
)
def test_invalid_settings(kwargs, match):
    with pytest.raises(YasdlError, match=match):
        POT(**kwargs)


def test_wrong_role_label_is_rejected():
    with pytest.raises(YasdlError, match="does not fit"):
        Block("Bad", VOLUME.replace("{cw}", "{w}  ").replace("VR1{w}", "VR1{cw}"), VR1=POT())


def _ratio(tmp_path, pot):
    deck = spice_netlist(Block("Vol", VOLUME, VR1=pot), subckt="vol", port_order=["in", "out"])
    cir = tmp_path / "vol.cir"
    cir.write_text(
        "* vol\n" + deck + "V1 in 0 1\nX1 in out vol\nRL out 0 1e12\n"
        ".control\nop\nprint v(out)\n.endc\n.end\n"
    )
    run = subprocess.run(["ngspice", "-b", str(cir)], capture_output=True, text=True)
    m = re.search(r"v\(out\) = (\S+)", run.stdout)
    assert m, run.stdout + run.stderr
    return float(m.group(1))


@pytest.mark.integration
@pytest.mark.skipif(not have_ngspice, reason="ngspice missing")
@pytest.mark.parametrize(
    "position, taper, want",
    [
        (0.0, "lin", 0.0),
        (1.0, "lin", 1.0),
        (0.3, "lin", 0.3),
        (0.5, "log", 0.1),  # audio taper: 10 % at mid rotation
        (1.0, "log", 1.0),
        (0.5, "rlog", 0.9),
    ],
)
def test_volume_divider_in_ngspice(tmp_path, position, taper, want):
    """Input on cw, ccw grounded: the output is F(position) of the input."""
    assert _ratio(tmp_path, POT("10k", position, taper)) == pytest.approx(want, abs=1e-4)


@pytest.mark.integration
@pytest.mark.skipif(not have_ngspice, reason="ngspice missing")
def test_clockwise_is_louder(tmp_path):
    levels = [_ratio(tmp_path, POT("10k", p, "log")) for p in (0.2, 0.4, 0.6, 0.8)]
    assert levels == sorted(levels) and levels[0] < levels[-1]


@pytest.mark.integration
@pytest.mark.skipif(not have_kicad, reason="kicad-cli missing")
def test_two_settings_survive_the_kicad_round_trip(tmp_path):
    from yasdl.kicad_export import export_kicad_spice, render, spice_roundtrip

    block = Block("Pots", TWO, VR1=POT("10k", 0.2, "log"), VR2=POT("10k", 0.7))
    info = render(block, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"] and info["erc"] == [], info["erc"]
    assert info["spice_ok"], info["spice_diff"]
    exported = export_kicad_spice(info["schematic"])
    assert "yasdl_pot R=10k POS=0.2 TAPER=1" in exported
    assert "yasdl_pot R=10k POS=0.7 TAPER=0" in exported
    # Same connections, different setting: rejected.
    moved = Block("Pots", TWO, VR1=POT("10k", 0.2, "log"), VR2=POT("10k", 0.6))
    from yasdl.kicad_export import to_kicad

    sch, refmap = to_kicad(block, tmp_path / "p.kicad_sch")
    assert spice_roundtrip(block, sch, refmap)[0]
    ok, diff = spice_roundtrip(moved, sch, refmap)
    assert not ok and "POS=0.6" in diff.replace("pos=", "POS=")
