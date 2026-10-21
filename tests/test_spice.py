import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from docs.examples.sgen import BJT_MODELS, PHASE_SHIFT, SGEN, SGEN_PINS
from yasdl import GND, NPN, OPAMP, R, Block, YasdlError, spice_netlist
from yasdl.kicad_lib import KICAD_CLI
from yasdl.spice import parse_spice, spice_partition

# ee_sgen task oracle (solve.sh); the comparison test is skipped unless this is set
ORACLE = Path(os.environ.get("YASDL_SGEN_ORACLE", "/nonexistent"))
have_models = os.path.exists(BJT_MODELS)
have_ngspice = shutil.which("ngspice") is not None
have_kicad = KICAD_CLI.exists()

# yasdl element -> oracle element (ee_sgen solution)
NAME_MAP = {"R_OSC_RA": "Rb1a", "R_OSC_RB": "Rb1b", "R_OSC_RC": "Rcol1", "R_OSC_REUP": "Re_up",
            "R_OSC_REDN": "Re_down", "C_OSC_CE": "Ce1", "Q_OSC_Q1": "Q1",
            "C_OSC_PS_C1": "Cps1", "C_OSC_PS_C2": "Cps2", "C_OSC_PS_C3": "Cps3",
            "R_OSC_PS_R1": "Rps1", "R_OSC_PS_R2": "Rps2",
            "C_AMP_CK": "Cc1", "R_AMP_RBUF": "Rbuf_series", "R_AMP_RBIN": "Rbin", "Q_AMP_Q2": "Q2",
            "R_AMP_RE2": "Re2", "C_AMP_COUT": "Cout", "R_AMP_ROUT": "Rout", "R_AMP_RBLD": "Rbleed"}


def test_spice_basics():
    assert ".subckt sgen vm out vp" in spice_netlist(SGEN, subckt="sgen")  # DIP order
    text = spice_netlist(SGEN, subckt="sgen", port_order=SGEN_PINS)
    assert ".subckt sgen vp vm out" in text  # the task's order
    assert "Q_OSC_Q1 " in text and "2N3904" in text
    assert re.search(r"^R_OSC_RB \S+ 0 47k$", text, re.M)  # GND is node 0
    assert ".subckt ps out in" in spice_netlist(PHASE_SHIFT, subckt="ps", port_order=["out", "in"])
    with pytest.raises(YasdlError, match="every port"):
        spice_netlist(PHASE_SHIFT, subckt="ps", port_order=["in"])


def test_subckt_supply_keeps_formal_port_alias():
    block = Block("SupplyAlias", """
        {VP}──┬──R1──{out}
              │
            [VCC]
    """, R1=R("1k"))
    text = spice_netlist(block, subckt="supply", port_order=["VP", "out"])
    assert ".subckt supply VP out" in text
    assert "R_R1 VP out 1k" in text
    assert "R_R1 VCC out 1k" in spice_netlist(block)


@pytest.mark.skipif(not have_kicad, reason="kicad-cli missing")
@pytest.mark.parametrize("canvas", [
    "{input}──┬──{output}\\n         │\\n         R1\\n         │\\n       [GND]\\n",
    "{VP}──┬──R1──{out}\\n      │\\n    [VCC]\\n",
])
def test_port_aliases_on_one_net_render_cleanly(tmp_path, canvas):
    from yasdl.kicad_export import render
    from yasdl.sexp import find_all, parse
    block = Block("AliasedPorts", canvas.replace("\\n", "\n"), R1=R("1k"))
    info = render(block, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"] and info["spice_ok"]
    assert info["erc"] == []
    root = parse(info["schematic"].read_text())
    visible = {str(item[1]) for kind in ("text", "label") for item in find_all(root, kind)}
    assert {port.name for port in block.ports} <= visible


@pytest.mark.skipif(not have_kicad, reason="kicad-cli missing")
def test_crossing_between_power_label_and_component(tmp_path):
    from yasdl.kicad_export import render
    block = Block("CrossingSupply", """
              [VCC]
        {a}─────│─────{b}
                R1
                │
              [GND]
    """, R1=R("1k"))
    info = render(block, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"], (info["missing"], info["extra"])
    assert info["erc"] == []
    assert info["spice_ok"]


@pytest.mark.skipif(not have_kicad, reason="kicad-cli missing")
def test_crossing_between_two_components(tmp_path):
    from yasdl.kicad_export import render
    block = Block("CrossingComponents", """
            {top}
              │
        {a}─R1─R2─{b}
              │
            {bottom}
    """, R1=R("1k"), R2=R("2k"))
    info = render(block, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"], (info["missing"], info["extra"])
    assert info["erc"] == []
    assert info["spice_ok"]


def test_spice_errors():
    amp = Block("A", """
           [VEE]
             │
        ─────U1U1──
           ┌+U1U1
           │ │
          G1 [VCC]
    """, U1=OPAMP(), G1=GND())
    with pytest.raises(YasdlError, match="no SPICE mapping"):
        spice_netlist(amp)
    q = Block("Q", """
         │
        ─Q1
         Q1
         │
    """, Q1=NPN())
    with pytest.raises(YasdlError, match="model name"):
        spice_netlist(q)
    assert "R_R1 W0 E0 1k" in spice_netlist(Block("S", "──R1──", R1=R("1k")))


@pytest.mark.skipif(not ORACLE.exists(), reason="ee_sgen oracle not available")
def test_sgen_matches_oracle_netlist():
    oracle = ORACLE.read_text().split("<<'SGEN'\n")[1].split("\nSGEN")[0]
    ours = spice_netlist(SGEN, subckt="sgen", port_order=SGEN_PINS)
    assert re.search(r"^\.subckt sgen (.*)$", ours, re.M).group(1) == \
        re.search(r"^\.subckt sgen (.*)$", oracle, re.M).group(1)
    o_part, o_vals = spice_partition(parse_spice(oracle), lambda n: n)
    y_part, y_vals = spice_partition(parse_spice(ours), lambda n: NAME_MAP[n])
    assert y_part == o_part
    assert y_vals == o_vals


@pytest.mark.skipif(not (have_kicad and have_models), reason="kicad-cli or bjt.mod missing")
def test_sgen_kicad_export(tmp_path):
    from yasdl.kicad_export import render
    info = render(SGEN, tmp_path, svg=False, spice_libs=(BJT_MODELS,), spice=True)
    assert info["roundtrip_ok"] and info["erc"] == []
    assert info["spice_ok"], info["spice_diff"]  # kicad-cli SPICE == yasdl SPICE


@pytest.mark.skipif(not (have_ngspice and have_models), reason="ngspice or bjt.mod missing")
def test_sgen_oscillates_near_2khz(tmp_path):
    (tmp_path / "sgen.lib").write_text(spice_netlist(SGEN, subckt="sgen", port_order=SGEN_PINS))
    (tmp_path / "tb.cir").write_text(f"""* tb
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
""")
    r = subprocess.run(["ngspice", "-b", "tb.cir"], cwd=tmp_path, capture_output=True, text=True,
                       timeout=600)
    t20 = float(re.search(r"^t20\s*=\s*([-\d.eE+]+)", r.stdout, re.M).group(1))
    assert 1700 <= 20 / t20 <= 2300
