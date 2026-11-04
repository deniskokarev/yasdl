"""P2: shared multi-unit packages (spec 3.4) and non-simulated parts, Atom(sim=False) (6.5).

A dual op-amp is one physical chip: unit A and unit B fill ordinary three-terminal op-amp
holes in different blocks, the power unit is bound once, and the export keeps one KiCad
reference with the datasheet's physical pins (A: + 3, - 2, out 1; B: + 5, - 6, out 7;
V+ 8, V- 4), one footprint, and one whole-device SPICE element.
"""

import re
import shutil
import subprocess

import pytest
from yasdl import (Atom, Block, C, netlist, OPAMP_IDEAL, Package, R, spice_netlist, SpiceModel, V,
                   YasdlError)
from yasdl.kicad_lib import KICAD_CLI
from yasdl.parts import dual_opamp

kicad = pytest.mark.skipif(not KICAD_CLI.exists(), reason="kicad-cli missing")
have_ngspice = shutil.which("ngspice") is not None

DUAL_LIB = """* whole-device test dual op-amp (two ideal channels), node order as TI's dual models
.subckt testdual out1 inn1 inp1 vee inp2 inn2 out2 vcc
B1 out1 0 V=1e5*(V(inp1)-V(inn1))
B2 out2 0 V=1e5*(V(inp2)-V(inn2))
Rq vcc vee 100k
.ends testdual
"""
MODEL_PINS = ["A.out", "A.-", "A.+", "V-", "B.+", "B.-", "B.out", "V+"]

FOLLOWER = Block(
    "Follower",
    """
    ┌───────────┐
    └───U1U1    │
        U1U1────┴──{out}
{in}───+U1U1
""",
)

TOP_CANVAS = """
               [VCC]
                 │
{a}──FA──FB──┐   PW
             │   │
            {b} [VEE]
"""


@pytest.fixture
def dual(tmp_path):
    lib = tmp_path / "dual.lib"
    lib.write_text(DUAL_LIB)
    return dual_opamp("TESTDUAL", model="testdual", library=lib, model_pins=MODEL_PINS)


def top(chip, **override):
    bindings = dict(
        FA=FOLLOWER.bind(U1=chip.unit("A")),
        FB=FOLLOWER.bind(U1=chip.unit("B")),
        PW=chip.power(),
    )
    bindings.update(override)
    return Block("DualTop", TOP_CANVAS, **bindings)


def test_units_fill_three_terminal_holes(dual):
    chip = dual(name="UA")
    block = top(chip)
    nets = netlist(block)
    assert nets["a"] == ["FA.U1.3"]  # A+
    assert sorted(nets["b"]) == ["FB.U1.6", "FB.U1.7"]  # B- and B out
    inner = next(v for v in nets.values() if "FA.U1.1" in v)
    assert sorted(inner) == ["FA.U1.1", "FA.U1.2", "FB.U1.5"]  # A out, A-, B+
    assert nets["VCC"] == ["PW.8"] and nets["VEE"] == ["PW.4"]


def test_whole_device_spice_element(dual):
    text = spice_netlist(top(dual(name="UA")))
    assert text.count("X_UA ") == 1
    m = re.search(r"^X_UA (.*) testdual$", text, re.M)
    out1, inn1, inp1, vee, inp2, inn2, out2, vcc = m.group(1).split()
    assert out1 == inn1 == inp2 and inp1 == "a" and inn2 == out2 == "b"
    assert (vee, vcc) == ("VEE", "VCC")
    assert text.count(".include") == 1


def test_default_package_name_is_its_first_unit_path(dual):
    assert "X_FA_U1 " in spice_netlist(top(dual()))


def test_every_unit_must_be_bound_once(dual):
    chip = dual(name="UA")
    with pytest.raises(YasdlError, match="unbound units B"):
        netlist(top(chip, FB=FOLLOWER.bind(U1=OPAMP_IDEAL())))
    with pytest.raises(YasdlError, match="unbound units C"):
        netlist(top(chip, PW=Atom("Device:R", "1k")))
    same = FOLLOWER.bind(U1=chip.unit("A"))
    with pytest.raises(YasdlError, match="bound twice"):
        netlist(top(chip, FA=same, FB=same))


def test_package_api_errors(dual, tmp_path):
    with pytest.raises(YasdlError, match="single unit"):
        Package("Device:R")
    chip = dual(name="UA")
    with pytest.raises(YasdlError, match="does not exist"):
        chip.unit("D")
    with pytest.raises(YasdlError, match="every physical pin"):
        Package(dual.lib_id, spice=SpiceModel("X", ("1", "2", "3"), "testdual"))
    with pytest.raises(YasdlError, match="model_pins"):
        dual_opamp("BADPINS", model="testdual", library=tmp_path / "dual.lib",
                   model_pins=MODEL_PINS[:-1])


def test_two_packages_need_distinct_names(dual):
    a, b = dual(name="U1"), dual(name="U1")
    block = Block(
        "TwoChips",
        "{a}──FA──FB──FC──FD──{b}\n\n  PA  PB",
        FA=FOLLOWER.bind(U1=a.unit("A")), FB=FOLLOWER.bind(U1=a.unit("B")),
        FC=FOLLOWER.bind(U1=b.unit("A")), FD=FOLLOWER.bind(U1=b.unit("B")),
        PA=Block("P", "[VCC]\n  │\n  PW\n  │\n[VEE]", PW=a.power()),
        PB=Block("P", "[VCC]\n  │\n  PW\n  │\n[VEE]", PW=b.power()),
    )
    with pytest.raises(YasdlError, match="two packages are named 'U1'"):
        spice_netlist(block)


@pytest.mark.integration
@kicad
def test_one_physical_chip_in_kicad(dual, tmp_path):
    from yasdl.kicad_export import render
    from yasdl.kicad_sch import export_netlist_full
    from yasdl.sexp import find, find_all, parse

    block = top(dual(name="UA"))
    info = render(block, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"], (info["missing"], info["extra"])
    assert info["erc"] == [], info["erc"]
    assert info["spice_ok"], info["spice_diff"]
    nets, comps = export_netlist_full(info["schematic"])
    chips = [r for r in comps if r.startswith("U")]
    assert chips == ["U1"]
    assert comps["U1"]["footprint"] == "Package_DIP:DIP-8_W7.62mm"
    assert nets["/a"] >= {("U1", "3")}
    assert {("U1", "6"), ("U1", "7")} <= nets["/b"]
    assert any({("U1", "1"), ("U1", "2"), ("U1", "5")} <= n for n in nets.values())
    assert ("U1", "8") in nets["VCC"] and ("U1", "4") in nets["VEE"]
    root = parse(info["schematic"].read_text())
    units = sorted(
        int(find(s, "unit")[1]) for s in find_all(root, "symbol")
        if find(s, "lib_id") and str(find(s, "lib_id")[1]).endswith("TESTDUAL")
    )
    assert units == [1, 2, 3]


@pytest.mark.integration
@pytest.mark.skipif(not have_ngspice, reason="ngspice missing")
def test_whole_device_simulates(dual, tmp_path):
    chip = dual(name="UA")
    chain = Block(
        "Chain",
        "{a}──FA──FB──{b}\n\n  PW",
        FA=FOLLOWER.bind(U1=chip.unit("A")),
        FB=FOLLOWER.bind(U1=chip.unit("B")),
        PW=Block("P", "[VCC]\n  │\n  PW\n  │\n[VEE]", PW=chip.power()),
    )
    block = Block(
        "DualBench",
        """
  ┌──CH──{b}
  +
  V1
  │
[GND]
""",
        V1=V("dc 0.5"),
        CH=chain,
    )
    deck = spice_netlist(block) + "VP VCC 0 12\nVN VEE 0 -12\n.control\nop\nprint v(b)\n.endc\n.end\n"
    (tmp_path / "tb.cir").write_text(deck)
    out = subprocess.run(["ngspice", "-b", "tb.cir"], cwd=tmp_path, capture_output=True,
                         text=True, timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr
    m = re.search(r"^v\(b\)\s*=\s*([-+\d.eE]+)", out.stdout, re.M)
    assert m and float(m.group(1)) == pytest.approx(0.5, abs=1e-3), out.stdout


# --- Atom(sim=False) ------------------------------------------------------------------------
JACKED = Block(
    "Jacked",
    """
J1J1──R1──┬──{out}
J1J1──┐   │
      │   C1
    [GND] │
        [GND]
""",
    J1=Atom("Connector_Audio:AudioJack2", "JACK", sim=False, footprint="Connector_Audio:Jack_6.35mm_Neutrik_NJ2FD-V_Vertical"),
    R1=R("1k"),
    C1=C("1n"),
)


def test_non_simulated_part_is_left_out_of_spice_only():
    nets = netlist(JACKED)
    assert any(p.startswith("J1.") for pins in nets.values() for p in pins)
    text = spice_netlist(JACKED)
    assert "J1" not in text and "R_R1 " in text and "C_C1 " in text


def test_part_without_model_suggests_sim_false():
    block = Block("NoModel", "J1J1──R1──{out}\nJ1J1──┐\n      │\n    [GND]",
                  J1=Atom("Connector_Audio:AudioJack2", "JACK"), R1=R("1k"))
    with pytest.raises(YasdlError, match="sim=False"):
        spice_netlist(block)


@pytest.mark.integration
@kicad
def test_non_simulated_part_in_kicad(tmp_path):
    from yasdl.kicad_export import export_kicad_spice, render
    from yasdl.kicad_sch import export_netlist_full
    from yasdl.sexp import find, find_all, parse

    info = render(JACKED, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"] and info["erc"] == [] and info["spice_ok"], info
    from yasdl.spice import parse_spice

    names = [name for name, _, _ in parse_spice(export_kicad_spice(info["schematic"]))]
    assert sorted(names) == ["C1", "R1"]  # the jack is no SPICE element
    _, comps = export_netlist_full(info["schematic"])
    assert comps["J1"]["footprint"] == "Connector_Audio:Jack_6.35mm_Neutrik_NJ2FD-V_Vertical"  # still a board part
    root = parse(info["schematic"].read_text())
    jack = next(s for s in find_all(root, "symbol")
                if find(s, "lib_id") and str(find(s, "lib_id")[1]) == "Connector_Audio:AudioJack2")
    assert str(find(jack, "exclude_from_sim")[1]) == "yes"
    assert str(find(jack, "in_bom")[1]) == "yes" and str(find(jack, "on_board")[1]) == "yes"
