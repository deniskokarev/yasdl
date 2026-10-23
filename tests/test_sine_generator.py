"""SPICE export, KiCad round trip and simulation of the sine-generator example."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from docs.examples.sgen import BJT_MODELS, PHASE_SHIFT, SGEN, SGEN_PINS
from yasdl import spice_netlist, YasdlError
from yasdl.kicad_lib import KICAD_CLI
from yasdl.spice import parse_spice, spice_partition

SINE_GENERATOR_NETLIST = Path(__file__).with_suffix(".lib")
have_ngspice = shutil.which("ngspice") is not None
have_kicad = KICAD_CLI.exists()

# yasdl element names mapped to the fixed sine-generator test netlist.
NAME_MAP = {
    "R_OSC_RA": "Rb1a",
    "R_OSC_RB": "Rb1b",
    "R_OSC_RC": "Rcol1",
    "R_OSC_REUP": "Re_up",
    "R_OSC_REDN": "Re_down",
    "C_OSC_CE": "Ce1",
    "Q_OSC_Q1": "Q1",
    "C_OSC_PS_C1": "Cps1",
    "C_OSC_PS_C2": "Cps2",
    "C_OSC_PS_C3": "Cps3",
    "R_OSC_PS_R1": "Rps1",
    "R_OSC_PS_R2": "Rps2",
    "C_AMP_CK": "Cc1",
    "R_AMP_RBUF": "Rbuf_series",
    "R_AMP_RBIN": "Rbin",
    "Q_AMP_Q2": "Q2",
    "R_AMP_RE2": "Re2",
    "C_AMP_COUT": "Cout",
    "R_AMP_ROUT": "Rout",
    "R_AMP_RBLD": "Rbleed",
}


def test_sine_generator_spice_netlist():
    assert ".subckt sgen vm out vp" in spice_netlist(
        SGEN, subckt="sgen"
    )  # DIP order
    text = spice_netlist(SGEN, subckt="sgen", port_order=SGEN_PINS)
    assert ".subckt sgen vp vm out" in text  # explicit supply/output order
    assert "Q_OSC_Q1 " in text and "2N3904" in text
    assert re.search(r"^R_OSC_RB \S+ 0 47k$", text, re.M)  # GND is node 0
    assert ".subckt ps out in" in spice_netlist(
        PHASE_SHIFT, subckt="ps", port_order=["out", "in"]
    )
    with pytest.raises(YasdlError, match="every port"):
        spice_netlist(PHASE_SHIFT, subckt="ps", port_order=["in"])


def test_sine_generator_matches_reference_netlist():
    expected = SINE_GENERATOR_NETLIST.read_text()
    actual = spice_netlist(SGEN, subckt="sgen", port_order=SGEN_PINS)
    assert re.search(r"^\.subckt sgen (.*)$", actual, re.M).group(
        1
    ) == re.search(r"^\.subckt sgen (.*)$", expected, re.M).group(1)
    expected_part, expected_vals = spice_partition(
        parse_spice(expected), lambda n: n
    )
    actual_part, actual_vals = spice_partition(
        parse_spice(actual), lambda n: NAME_MAP[n]
    )
    assert actual_part == expected_part
    assert actual_vals == expected_vals


@pytest.mark.skipif(not have_kicad, reason="kicad-cli missing")
def test_sine_generator_kicad_export(tmp_path):
    from yasdl.kicad_export import render

    info = render(
        SGEN, tmp_path, svg=False, spice_libs=(BJT_MODELS,), spice=True
    )
    assert info["roundtrip_ok"] and info["erc"] == []
    assert info["spice_ok"], info["spice_diff"]


@pytest.mark.skipif(not have_ngspice, reason="ngspice missing")
@pytest.mark.parametrize("netlist", ["reference", "generated"])
def test_sine_generator_oscillates_near_2khz(tmp_path, netlist):
    text = (
        SINE_GENERATOR_NETLIST.read_text()
        if netlist == "reference"
        else spice_netlist(SGEN, subckt="sgen", port_order=SGEN_PINS)
    )
    (tmp_path / "sgen.lib").write_text(text)
    (tmp_path / "tb.cir").write_text(
        f"""* Sine-generator transient test
.include {BJT_MODELS}
.include sgen.lib
VP vp 0 PWL(0 0 10m 12)
VM vm 0 PWL(0 0 10m -12)
X1 vp vm out sgen
.tran 1u 150m 100m 1u
.control
run
meas tran t20 TRIG v(out) VAL=0 RISE=5 TARG v(out) VAL=0 RISE=25
.endc
.end
"""
    )
    result = subprocess.run(
        ["ngspice", "-b", "tb.cir"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    measurement = re.search(r"^t20\s*=\s*([-\d.eE+]+)", result.stdout, re.M)
    assert measurement is not None, result.stdout + result.stderr
    t20 = float(measurement.group(1))
    assert 1700 <= 20 / t20 <= 2300
