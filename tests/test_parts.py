"""Generic part factories, derived symbols, standard descriptors and multi-unit packages
(DECISIONS: generic NPN/PNP/op-amp factories, P2.2 packages, metadata)."""

import re
import shutil
import subprocess

import pytest
from yasdl import Block, NPN, netlist, R, spice_netlist, V, YasdlError
from yasdl.kicad_lib import _symbol_sexp, BUNDLED_MODELS, derive_symbol, KICAD_CLI, load
from yasdl.parts import (
    AtomNPN,
    AtomOpamp3,
    AtomOpamp5,
    BD139,
    BD140,
    D1N4148,
    dual_opamp,
    IDEAL_DUAL,
    Package,
    Q2N3904,
    Q2N3906,
)

have_kicad = KICAD_CLI.exists()
have_ngspice = shutil.which("ngspice") is not None
kicad = pytest.mark.skipif(not have_kicad, reason="kicad-cli missing")

# Independent pinout references: manufacturer datasheets (TO-92: E B C; TO-126: E C B) and
# KiCad 9's symbols for the exact devices (2N3904 extends Q_NPN_EBC, BD139 Q_NPN_ECB, ...).
DATASHEET = {
    "2N3904": {"E": "1", "B": "2", "C": "3"},
    "2N3906": {"E": "1", "B": "2", "C": "3"},
    "BD139": {"E": "1", "C": "2", "B": "3"},
    "BD140": {"E": "1", "C": "2", "B": "3"},
}
KICAD_DEVICE = {
    "2N3904": "Transistor_BJT:Q_NPN_EBC",
    "2N3906": "Transistor_BJT:Q_PNP_EBC",
    "BD139": "Transistor_BJT:Q_NPN_ECB",
    "BD140": "Transistor_BJT:Q_PNP_ECB",
}
PARTS = {"2N3904": Q2N3904, "2N3906": Q2N3906, "BD139": BD139, "BD140": BD140}


def bjt_bench(**parts):
    """Transistors side by side: base from local net [a], [c], [d]..., collector to VCC,
    emitter (arrow v) to GND. Built with Sketch so columns can't drift."""
    from yasdl import Sketch

    sk = Sketch()
    for k, (name, net) in enumerate(zip(parts, "acdfgh")):
        x = 12 * k
        sk.text(2, x, f"[{net}]").hline(2, x + 3, x + 3).text(2, x + 4, "{b}")
        sk.box(2, x + 7, name, rows=2)
        sk.text(0, x + 5, "[VCC]").vline(x + 7, 1, 1)
        sk.text(4, x + 7, "v").vline(x + 7, 5, 5).text(6, x + 5, "[GND]")
    return Block("Two", sk.render(), **parts)


def roles(atom):
    return {p.name: p.number for p in atom.symbol.pins}


@pytest.mark.parametrize("name", sorted(PARTS))
def test_standard_bjt_pinouts_match_datasheet_and_kicad_device_symbol(name):
    assert roles(PARTS[name]) == DATASHEET[name]
    device = {p.name: p.number for p in load(KICAD_DEVICE[name]).pins}
    assert roles(PARTS[name]) == device


def test_diode_and_dual_opamp_pinouts_match_kicad():
    assert roles(D1N4148) == {"K": "1", "A": "2"}
    kicad_dual = [{p.name: p.number for p in load("Amplifier_Operational:LM2904", u).pins} for u in (1, 2, 3)]
    ours = [{p.name: p.number for p in load(IDEAL_DUAL.lib_id, u).pins} for u in (1, 2, 3)]
    assert ours == kicad_dual


def test_generic_base_is_not_modified():
    derive_symbol("Device:Q_NPN", "TEST_ECB", {"E": 1, "C": 2, "B": 3})
    assert {p.number for p in load("Device:Q_NPN").pins} == {"B", "C", "E"}
    assert str(_symbol_sexp("Device:Q_NPN")[1]) == "Q_NPN"


def test_derived_definitions_are_immutable():
    derive_symbol("Device:Q_NPN", "TEST_IMM", {"E": 1, "B": 2, "C": 3})
    derive_symbol("Device:Q_NPN", "TEST_IMM", {"E": 1, "B": 2, "C": 3})  # identical: fine
    with pytest.raises(ValueError, match="already defined differently"):
        derive_symbol("Device:Q_NPN", "TEST_IMM", {"E": 1, "B": 3, "C": 2})


@pytest.mark.parametrize(
    "pins, match",
    [
        ({"E": 1, "B": 2}, "missing"),
        ({"E": 1, "B": 2, "C": 3, "S": 4}, "unknown"),
        ({"E": 1, "B": 1, "C": 3}, "share a physical pin"),
    ],
)
def test_pin_maps_are_validated(pins, match):
    with pytest.raises(YasdlError, match=match):
        AtomNPN("BAD" + str(len(pins)) + match[:3], pins)


def test_spice_node_order_is_c_b_e_whatever_the_package():
    block = bjt_bench(Q1=Q2N3904, Q2=BD139)
    text = spice_netlist(block)
    assert re.search(r"^Q_Q1 VCC a 0 2N3904$", text, re.M)
    assert re.search(r"^Q_Q2 VCC c 0 BD139$", text, re.M)
    nets = netlist(block)
    # physical pins: base of the 2N3904 is pin 2, base of the BD139 is pin 3
    assert nets["a"] == ["Q1.2"] and nets["c"] == ["Q2.3"]
    assert sorted(nets["VCC"]) == ["Q1.3", "Q2.2"]


@kicad
def test_kicad_physical_pins_metadata_and_checks(tmp_path):
    from yasdl.kicad_export import render
    from yasdl.kicad_sch import export_netlist
    from yasdl.sexp import find, find_all, parse

    block = bjt_bench(Q1=Q2N3904, Q2=BD139, Q3=NPN("2N3904"))
    from yasdl.kicad_lib import JELLYBEAN_MODEL

    syntax_only = tmp_path / "bd139.lib"
    syntax_only.write_text(".model BD139 NPN(BF=100)\n")  # pin test, not characterisation
    info = render(block, tmp_path, svg=False, spice=True, spice_libs=(JELLYBEAN_MODEL, syntax_only))
    assert info["roundtrip_ok"] and info["erc"] == [] and info["spice_ok"], info
    nets = export_netlist(info["schematic"])
    base = {name: sorted(p for r, p in nodes if r.startswith("Q")) for name, nodes in nets.items()}
    assert base["/a"] == ["2"] and base["/c"] == ["3"] and base["/d"] == ["B"]
    root = parse(info["schematic"].read_text())
    props = {}
    for sym in find_all(root, "symbol"):
        lib = find(sym, "lib_id")
        if lib is None:
            continue
        fields = {str(p[1]): str(p[2]) for p in find_all(sym, "property")}
        props[str(lib[1])] = fields
    assert props["yasdl_parts:2N3904"]["Footprint"] == "Package_TO_SOT_THT:TO-92_Inline"
    assert props["yasdl_parts:BD139"]["Footprint"] == "Package_TO_SOT_THT:TO-126-3_Vertical"
    assert "onsemi" in props["yasdl_parts:2N3904"]["Datasheet"]
    assert props["Device:Q_NPN"]["Footprint"] == "" and props["Device:Q_NPN"]["Datasheet"] == ""
    assert (tmp_path / "yasdl_parts.kicad_sym").exists()
    assert "${KIPRJMOD}/yasdl_parts.kicad_sym" in (tmp_path / "sym-lib-table").read_text()


@kicad
def test_conflicting_part_definition_in_one_directory(tmp_path):
    from yasdl.kicad_export import render

    lib_id = derive_symbol("Device:Q_NPN", "TEST_DIR", {"E": 1, "B": 2, "C": 3})
    from yasdl import Atom

    blk = Block("T", "     │\n{b}─Q1\n     │\n   [GND]", Q1=Atom(lib_id, "TEST_DIR", sim=False))
    render(blk, tmp_path, svg=False)
    lib = tmp_path / "yasdl_parts.kicad_sym"
    lib.write_text(lib.read_text().replace('(number "2"', '(number "9"'))
    with pytest.raises(Exception, match="already defines yasdl_parts:TEST_DIR differently"):
        render(blk, tmp_path, svg=False)


# --- single op-amps ---------------------------------------------------------------------------
def test_opamp_factories_map_roles_to_pins_and_model_nodes():
    single = AtomOpamp5(
        "TEST_OP5", {"+": 3, "-": 2, "out": 6, "V+": 7, "V-": 4},
        model="yasdl_ideal_opamp5", library=BUNDLED_MODELS,
    )
    assert roles(single) == {"+": "3", "-": "2", "V+": "7", "V-": "4", "~": "6"}
    assert single.spice.pins == ("3", "2", "7", "4", "6")
    assert single.spice.sim_pins == "3=inp 2=inn 7=vp 4=vn 6=out"
    three = AtomOpamp3("TEST_OP3", model="yasdl_ideal_opamp", library=BUNDLED_MODELS)
    assert three.spice.sim_pins == "1=inp 2=inn 3=out"
    with pytest.raises(YasdlError, match="has 3 pins"):
        AtomOpamp5("TEST_BAD5", {"+": 3, "-": 2, "out": 6, "V+": 7, "V-": 4},
                   model="yasdl_ideal_opamp", library=BUNDLED_MODELS)


# --- packages -------------------------------------------------------------------------------
FOLLOW = Block(
    "Follow",
    """
  {in}──+U1U1
      ┌──U1U1──┬──{out}
      │        │
      └────────┘
""",
)
INVERT = Block(
    "Invert",
    """
         ┌──RF──┐
         │      │
  {in}─RI┴─U1U1─┴─{out}
          +U1U1
          │
        [GND]
""",
    RI=R("10k"),
    RF=R("20k"),
)
SUPPLY = Block(
    "Supply",
    """
   [VCC]
     │
     PW
     │
   [VEE]
""",
)


def two_unit_design(chip):
    return Block(
        "TwoUnits",
        """
   SP

  {in}──FA──IV──{out}
""",
        FA=FOLLOW.bind(U1=chip.unit("A")),
        IV=INVERT.bind(U1=chip.unit("B")),
        SP=SUPPLY.bind(PW=chip.power()),
    )


def test_units_share_one_package_and_map_physical_pins():
    chip = Package(IDEAL_DUAL, "U7")
    nets = netlist(two_unit_design(chip))
    assert sorted(nets["in"]) == ["FA.U1.3"]
    assert sorted(nets["VCC"]) == ["SP.PW.8"] and sorted(nets["VEE"]) == ["SP.PW.4"]
    assert "IV.U1.7" in nets["out"]
    text = spice_netlist(two_unit_design(Package(IDEAL_DUAL, "U7")))
    assert len(re.findall(r"^X_U7 ", text, re.M)) == 1
    assert ".subckt yasdl_pkg_IDEAL_DUAL p1 p2 p3 p4 p5 p6 p7 p8" in text


def test_every_unit_once():
    chip = Package(IDEAL_DUAL, "U1")
    missing = Block("Miss", "{in}──FA──{out}", FA=FOLLOW.bind(U1=chip.unit("A")))
    with pytest.raises(YasdlError, match=r"units \['B', 'power'\] are not bound"):
        spice_netlist(missing)
    chip = Package(IDEAL_DUAL, "U2")
    twice = Block(
        "Twice",
        "   SP\n\n{in}──FA──FB──{out}",
        FA=FOLLOW.bind(U1=chip.unit("A")),
        FB=FOLLOW.bind(U1=chip.unit("A")),
        SP=SUPPLY.bind(PW=chip.power()),
    )
    with pytest.raises(YasdlError, match="unit A is bound twice"):
        spice_netlist(twice)
    with pytest.raises(YasdlError, match="no unit 'C'"):
        chip.unit("C")


@pytest.mark.integration
@pytest.mark.skipif(not have_ngspice, reason="ngspice missing")
def test_package_simulates_per_unit(tmp_path):
    deck = spice_netlist(two_unit_design(Package(IDEAL_DUAL, "U1")), subckt="two",
                         port_order=["in", "out"])
    cir = tmp_path / "two.cir"
    cir.write_text("* two\n" + deck + "VP VCC 0 12\nVN VEE 0 -12\nVI in 0 1.5\nX1 in out two\n"
                   ".control\nop\nprint v(out)\n.endc\n.end\n")
    run = subprocess.run(["ngspice", "-b", str(cir)], capture_output=True, text=True)
    m = re.search(r"v\(out\) = (\S+)", run.stdout)
    assert m, run.stdout + run.stderr
    assert float(m.group(1)) == pytest.approx(-3.0, abs=1e-3)  # follower, then gain -2


@pytest.mark.integration
@kicad
def test_package_kicad_reference_erc_and_spice(tmp_path):
    from yasdl.kicad_export import export_kicad_spice, render, spice_roundtrip, to_kicad
    from yasdl.sexp import find, find_all, parse

    info = render(two_unit_design(Package(IDEAL_DUAL, "U1")), tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"], (info["missing"], info["extra"])
    assert info["erc"] == [] and info["spice_ok"], info
    root = parse(info["schematic"].read_text())
    units = sorted(
        (str(find(s, "property")[2]), int(find(s, "unit")[1]))
        for s in find_all(root, "symbol")
        if find(s, "lib_id") and str(find(s, "lib_id")[1]) == IDEAL_DUAL.lib_id
    )
    assert units == [("U1", 1), ("U1", 2), ("U1", 3)]
    exported = export_kicad_spice(info["schematic"])
    assert len(re.findall(r"^XU1 ", exported, re.M)) == 1
    # a changed package pin mapping is caught
    design = two_unit_design(Package(IDEAL_DUAL, "U1"))
    sch, refmap = to_kicad(design, tmp_path / "m.kicad_sch")
    assert spice_roundtrip(design, sch, refmap)[0]
    text = sch.read_text()
    assert "3=p3 4=p4 5=p5" in text
    sch.write_text(text.replace("3=p3 4=p4 5=p5", "3=p5 4=p4 5=p3"))
    assert not spice_roundtrip(design, sch, refmap)[0]


def test_package_needs_descriptor_and_valid_maps():
    with pytest.raises(YasdlError, match="OpampPackage"):
        Package("Amplifier_Operational:LM358", "U1")
    with pytest.raises(YasdlError, match="used twice"):
        dual_opamp("TEST_BADDUAL").__class__(
            "TEST_BADDUAL2", units={"A": {"+": 3, "-": 2, "out": 1}, "B": {"+": 5, "-": 6, "out": 1}},
            power={"V+": 8, "V-": 4},
        )
