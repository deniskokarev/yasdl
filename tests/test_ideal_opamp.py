import re
import shutil
import subprocess

import pytest
from yasdl import Block, C, GND, I, netlist, OPAMP_IDEAL, R, spice_netlist, V
from yasdl.kicad_lib import BUNDLED_MODELS, KICAD_CLI, load

have_kicad = KICAD_CLI.exists()
have_ngspice = shutil.which("ngspice") is not None

INTEGRATOR = Block(
    "Integrator",
    """
            ┌───CF───┐
            │        │
{in}──RI────┴──U1U1  │
               U1U1──┴──{out}
             ┌+U1U1
             │
           [GND]
""",
    RI=R("1k"),
    CF=C("1u"),
    U1=OPAMP_IDEAL(),
)

TESTBENCH = Block(
    "IntegratorTB",
    """
  ┌──INT──{out}
  +
  V1
  │
[GND]
""",
    V1=V("dc 0 ac 1"),
    INT=INTEGRATOR,
)


def test_symbol_has_no_supply_pins():
    sym = load("yasdl:OPAMP_IDEAL")
    assert sorted((p.number, p.name, p.side) for p in sym.pins) == [
        ("1", "+", "W"),
        ("2", "-", "W"),
        ("3", "~", "E"),
    ]


def test_plus_label_puts_noninverting_input_at_the_bottom():
    assert INTEGRATOR.bound["U1"].mirror == "x"
    nets = netlist(INTEGRATOR)
    assert nets["GND"] == ["U1.1"]
    assert sorted(nets["out"]) == ["CF.2", "U1.3"]


def test_spice_includes_bundled_model():
    text = spice_netlist(TESTBENCH)
    assert f".include {BUNDLED_MODELS}" in text
    assert re.search(r"^X_INT_U1 0 \S+ out yasdl_ideal_opamp$", text, re.M)
    assert re.search(r"^V_V1 \S+ 0 dc 0 ac 1$", text, re.M)
    assert text.count(".include") == 1  # one include per library, however many op-amps


def test_current_source_arrow_orients_it():
    down = Block(
        "Down",
        """
    ┌──R1──┐
    │      │
    I1     │
    v      │
    └──────┴──[GND]
""",
        I1=I("1m"),
        R1=R("1k"),
    )
    up = Block(
        "Up",
        """
    ┌──R1──┐
    ^      │
    I1     │
    │      │
    └──────┴──[GND]
""",
        I1=I("1m"),
        R1=R("1k"),
    )

    def bottom_pin(blk):
        return next(pin for att, pin in blk.bound["I1"].pin_map if att.side == "S")

    assert bottom_pin(down) == "2"  # current leaves through the bottom pin
    assert bottom_pin(up) == "1"


@pytest.mark.integration
@pytest.mark.skipif(not have_ngspice, reason="ngspice not installed")
def test_integrator_simulates(tmp_path):
    deck = tmp_path / "tb.cir"
    deck.write_text(
        spice_netlist(TESTBENCH) + ".control\nac lin 1 159.1549 159.1549\n"
        "print vm(out) vp(out)\n.endc\n.end\n"
    )
    out = subprocess.run(
        ["ngspice", "-b", str(deck)], capture_output=True, text=True
    ).stdout
    mag = float(re.search(r"vm\(out\) = (\S+)", out).group(1))
    ph = float(re.search(r"vp\(out\) = (\S+)", out).group(1))
    assert mag == pytest.approx(1.0, rel=1e-5)  # |1/(jwRC)| = 1 at w = 1/RC
    assert ph == pytest.approx(1.5707963, rel=1e-6)  # inverting integrator: +90 degrees


@pytest.mark.integration
@pytest.mark.skipif(not have_kicad, reason="KiCad not installed")
def test_render_erc_clean_and_spice_roundtrip(tmp_path):
    from yasdl.kicad_export import render

    info = render(TESTBENCH, tmp_path, spice=True)
    assert info["roundtrip_ok"], (info["missing"], info["extra"])
    assert info["erc"] == []
    assert info["spice_ok"], info["spice_diff"]
    table = (tmp_path / "sym-lib-table").read_text()
    assert '(name "yasdl")' in table


@pytest.mark.integration
@pytest.mark.skipif(not have_kicad, reason="KiCad not installed")
def test_stale_sym_lib_table_is_rewritten(tmp_path):
    from yasdl.kicad_export import render

    (tmp_path / "sym-lib-table").write_text("(sym_lib_table\n  (version 7)\n)\n")
    info = render(TESTBENCH, tmp_path, svg=False)
    assert info["erc"] == []


@pytest.mark.integration
@pytest.mark.skipif(not have_kicad, reason="KiCad not installed")
def test_references_from_names_and_hidden_values(tmp_path):
    from yasdl.kicad_export import render
    from yasdl.sexp import find, find_all, parse

    info = render(
        TESTBENCH, tmp_path, svg=False, spice=True, references="names", values=False
    )
    assert info["roundtrip_ok"] and info["erc"] == [] and info["spice_ok"]
    text = info["schematic"].read_text()
    refs = set(re.findall(r'\(property "Reference" "([^"#]+)"', text))
    assert {"V1", "RI", "CF", "U1"} <= refs and not {"R1", "C1"} & refs
    value = re.search(r'\(property "Value" "1k"(.*?)\n\t\t\)', text, re.S).group(1)
    assert "(hide yes)" in value


@pytest.mark.integration
def test_reference_names_fall_back_to_paths_when_names_repeat():
    from yasdl.kicad_export import to_kicad

    twice = Block(
        "Twice",
        """
  ┌──A──B──{out}
  +
  V1
  │
[GND]
""",
        V1=V("ac 1"),
        A=INTEGRATOR,
        B=INTEGRATOR,
    )
    if not have_kicad:
        pytest.skip("KiCad not installed")
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        _, refmap = to_kicad(twice, f"{tmp}/t.kicad_sch", references="names")
    assert {"A_RI", "B_RI", "A_U1", "V1"} <= set(refmap)


@pytest.mark.integration
@pytest.mark.skipif(not have_kicad, reason="KiCad not installed")
def test_render_without_erc_helpers(tmp_path):
    from yasdl.kicad_export import render

    info = render(TESTBENCH, tmp_path, svg=False, erc_helpers=False)
    assert info["roundtrip_ok"] and info["erc"] is None
    text = info["schematic"].read_text()
    assert "PWR_FLAG" not in text and "TestPoint" not in text
