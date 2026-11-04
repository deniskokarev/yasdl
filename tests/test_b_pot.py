"""P0/P2: the standard three-pin potentiometer (spec 6.4): pin roles, rotation and taper,
instance parameters on one shared model, simulation and the round trip of its setting."""

import re
import shutil
import subprocess

import pytest
from yasdl import Block, POT, pot_position, R, spice_netlist, V, YasdlError
from yasdl.kicad_lib import KICAD_CLI, load

have_ngspice = shutil.which("ngspice") is not None


def test_symbol_pins_and_roles():
    pins = {p.number: p.side for p in load("Device:R_Potentiometer").pins}
    assert pins == {"1": "N", "2": "E", "3": "S"}  # CCW end top, wiper right, CW end bottom
    pot = POT("10k")
    assert pot.aliases == {"ccw": "1", "w": "2", "wiper": "2", "cw": "3"}


def test_labels_orient_the_pot():
    """{cw} on top and the wiper on the left: only a half turn puts pin 3 up, pin 2 left."""
    block = Block(
        "Pot",
        """
      │
     {cw}
 ──{w}RV
      │
""",
        RV=POT("10k"),
    )
    pins = {att.side: pin for att, pin in block.bound["RV"].pin_map}
    assert pins == {"N": "3", "W": "2", "S": "1"}


@pytest.mark.parametrize(
    "rotation, taper, pos",
    [(0.0, "lin", 0.0), (0.25, "lin", 0.25), (1.0, "lin", 1.0),
     (0.0, "log", 0.0), (0.5, "log", 0.1), (1.0, "log", 1.0)],
)
def test_position_and_taper(rotation, taper, pos):
    assert pot_position(rotation, taper) == pytest.approx(pos)


@pytest.mark.parametrize(
    "kwargs, match",
    [({"rotation": -0.1}, "rotation"), ({"rotation": 1.5}, "rotation"),
     ({"taper": "exp"}, "taper")],
)
def test_invalid_settings(kwargs, match):
    with pytest.raises(YasdlError, match=match):
        POT("10k", **kwargs)


@pytest.mark.parametrize("value", ["1M", "4.7M", "ten", "10 k", ""])
def test_invalid_values(value):
    with pytest.raises(YasdlError):
        POT(value)


def test_megohm_pot_uses_meg():
    assert "R=1MEG" in POT("1MEG").spice.params


DIVIDER = Block(
    "PotDivider",
    """
  ┌──────┐
  │     {ccw}
  +      RV{w}──{out}
  V1    {cw}
  │      │
[GND]  [GND]
""",
    V1=V("1"),
    RV=POT("10k", rotation=0.25),
)


def test_spice_element_carries_parameters():
    text = spice_netlist(DIVIDER)
    assert re.search(r"^X_RV \S+ out 0 yasdl_pot R=10k POS=0\.25$", text, re.M)
    assert text.count(".include") == 1


@pytest.mark.integration
@pytest.mark.skipif(not have_ngspice, reason="ngspice missing")
@pytest.mark.parametrize(
    "rotation, taper, expected",
    [(0.25, "lin", 0.75), (0.5, "log", 0.9), (0.0, "lin", 1.0), (1.0, "lin", 0.0)],
)
def test_wiper_voltage_in_ngspice(tmp_path, rotation, taper, expected):
    """CCW end at 1 V, CW end at 0 V: V(wiper) = 1 - POS."""
    block = DIVIDER.bind(RV=POT("10k", rotation=rotation, taper=taper))
    deck = spice_netlist(block) + ".control\nop\nprint v(out)\n.endc\n.end\n"
    (tmp_path / "pot.cir").write_text(deck)
    out = subprocess.run(["ngspice", "-b", "pot.cir"], cwd=tmp_path, capture_output=True,
                         text=True, timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr
    m = re.search(r"^v\(out\)\s*=\s*([-+\d.eE]+)", out.stdout, re.M)
    assert m, out.stdout + out.stderr
    assert float(m.group(1)) == pytest.approx(expected, abs=1e-4)


TWO_POTS = Block(
    "TwoPots",
    """
  ┌──────┬─────────┐
  │      │         │
  +      RA──┐     RB──┐
  V1     │   RX    │   RY
  │      │   │     │   │
  │    [GND] │   [GND] │
[GND]      [GND]     [GND]
""",
    V1=V("1"),
    RA=POT("10k", rotation=0.2),
    RB=POT("10k", rotation=0.7),
    RX=R("100k"),
    RY=R("100k"),
)


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(), reason="kicad-cli missing")
def test_settings_survive_the_round_trip(tmp_path):
    """Both pots have the same model and equivalent connections; only their settings differ,
    and exchanging the settings must be detected."""
    from yasdl.kicad_export import export_kicad_spice, render, spice_roundtrip

    info = render(TWO_POTS, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"] and info["erc"] == [], info
    assert info["spice_ok"], info["spice_diff"]
    kicad_text = export_kicad_spice(info["schematic"])
    assert "POS=0.2" in kicad_text and "POS=0.7" in kicad_text
    swapped = spice_netlist(TWO_POTS).replace("POS=0.2", "POS=X").replace(
        "POS=0.7", "POS=0.2").replace("POS=X", "POS=0.7")
    from yasdl.kicad_export import to_kicad

    sch, refmap = to_kicad(TWO_POTS, tmp_path / "t.kicad_sch")
    ok, diff = spice_roundtrip(TWO_POTS, sch, refmap, kicad_text=kicad_text,
                               yasdl_text=swapped)
    assert not ok and "pos=" in diff


def test_pot_is_still_a_resistor_symbol():
    # A fixed divider and a pot occupy the same three-terminal drawing
    assert POT("10k").lib_id == "Device:R_Potentiometer"
    assert R("1k").lib_id == "Device:R"
