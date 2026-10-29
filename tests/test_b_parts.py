"""P2: generic-shape part factories and the standard Atom definitions (spec 6.3).

Reference data is independent of the factories: hand-written datasheet pin tables, and KiCad
9's device-specific symbols resolved here (including (extends ...)) with the plain
S-expression reader. Physical pin numbers are checked through KiCad's own netlist export.
"""

import re

import pytest
from yasdl import AtomNPN, AtomOpamp5, AtomPNP, Block, netlist, R, spice_netlist, YasdlError
from yasdl.kicad_lib import JELLYBEAN_MODEL, KICAD_CLI, load, SYMBOL_DIR
from yasdl.sexp import find, find_all, parse

kicad = pytest.mark.skipif(not KICAD_CLI.exists(), reason="kicad-cli missing")
have_libs = (SYMBOL_DIR / "Transistor_BJT.kicad_sym").exists()

# Datasheet pin tables (pin -> role), typed from the manufacturers' package drawings.
DATASHEET = {
    "2N3904": {"1": "E", "2": "B", "3": "C"},  # onsemi 2N3903-D, TO-92
    "2N3906": {"1": "E", "2": "B", "3": "C"},  # onsemi 2N3906-D, TO-92
    "BD139": {"1": "E", "2": "C", "3": "B"},  # ST CD00001225, SOT-32 (TO-126)
    "BD140": {"1": "E", "2": "C", "3": "B"},
    "1N4148": {"1": "K", "2": "A"},  # Nexperia/Vishay, DO-35, cathode band = pin 1
}
# TI TL072 datasheet (SLOS080W) table 4-3, same as LM358 (SNOSBT3): 8-pin dual.
DUAL = {"1": "A.out", "2": "A.-", "3": "A.+", "4": "V-", "5": "B.+", "6": "B.-",
        "7": "B.out", "8": "V+"}


def kicad_pins(lib, name):
    """{number: name} of a KiCad library symbol, following (extends ...) to its parent."""
    root = parse((SYMBOL_DIR / f"{lib}.kicad_sym").read_text())
    syms = {str(s[1]): s for s in find_all(root, "symbol")}
    sym = syms[name]
    while find(sym, "extends"):
        sym = syms[str(find(sym, "extends")[1])]
    out = {}
    for unit in find_all(sym, "symbol"):
        for item in unit:
            if isinstance(item, list) and item[:1] == ["pin"]:
                out[str(find(item, "number")[1])] = str(find(item, "name")[1])
    return out


def factory_pins(atom_or_type):
    """{physical number: role} of a derived symbol, by its (generic) pin names."""
    lib_id = atom_or_type.lib_id
    n_units = load(lib_id).unit_count
    out = {}
    for unit in range(1, n_units + 1):
        for p in load(lib_id, unit).pins:
            role = {"~": "out"}.get(p.name, p.name)
            if n_units > 1 and p.etype != "power_in":
                role = f"{chr(64 + unit)}.{role}"
            out[p.number] = role
    return out


@pytest.mark.parametrize("name", ["2N3904", "2N3906", "BD139", "BD140", "1N4148"])
def test_standard_parts_match_datasheets(name):
    from yasdl import parts

    factory = {"2N3904": parts.Q2N3904, "2N3906": parts.Q2N3906, "BD139": parts.BD139,
               "BD140": parts.BD140, "1N4148": parts.D1N4148}[name]
    assert factory_pins(factory()) == DATASHEET[name]


@pytest.mark.skipif(not have_libs, reason="KiCad device libraries missing")
@pytest.mark.parametrize(
    "name, lib", [("2N3904", "Transistor_BJT"), ("2N3906", "Transistor_BJT"),
                  ("BD139", "Transistor_BJT"), ("BD140", "Transistor_BJT"),
                  ("1N4148", "Diode")],
)
def test_standard_parts_match_kicad_device_symbols(name, lib):
    from yasdl import parts

    factory = {"2N3904": parts.Q2N3904, "2N3906": parts.Q2N3906, "BD139": parts.BD139,
               "BD140": parts.BD140, "1N4148": parts.D1N4148}[name]
    assert factory_pins(factory()) == kicad_pins(lib, name)


@pytest.mark.skipif(not have_libs, reason="KiCad device libraries missing")
@pytest.mark.parametrize("device", ["LM358", "TL072"])
def test_dual_opamp_pinout_matches_datasheet_and_kicad(device):
    from yasdl.parts import dual_opamp

    kind = dual_opamp(f"{device}_PINS")
    assert factory_pins(kind) == DUAL
    kicad = kicad_pins("Amplifier_Operational", device)
    assert {n: r.split(".")[-1].replace("out", "~") for n, r in DUAL.items()} == kicad


def test_generic_symbol_is_not_mutated():
    from yasdl.parts import BD139, Q2N3904

    Q2N3904(), BD139()
    assert sorted(p.number for p in load("Device:Q_NPN").pins) == ["B", "C", "E"]


def test_factory_validation():
    with pytest.raises(YasdlError, match="exactly the roles"):
        AtomNPN("BAD1", {"E": "1", "B": "2"})
    with pytest.raises(YasdlError, match="distinct"):
        AtomNPN("BAD2", {"E": "1", "B": "1", "C": "3"})
    with pytest.raises(YasdlError, match="exactly the roles"):
        AtomPNP("BAD3", {"E": "1", "B": "2", "C": "3", "S": "4"})
    AtomNPN("SAME", {"E": "1", "B": "2", "C": "3"})
    AtomNPN("SAME", {"e": "1", "b": "2", "c": "3"})  # identical: fine (keys any case)
    with pytest.raises(ValueError, match="already defined"):
        AtomNPN("SAME", {"E": "1", "B": "3", "C": "2"})  # same name, other pinout


TWO_PINOUTS = Block(
    "TwoPinouts",
    """
     [VCC]    [VCC]
       │        │
  ┌─{b}Q1  ┌─{b}Q2
  │    Q1  │    Q2
  │   {e}  │   {e}
  │    │   │    │
  R1   R2  R3   R4
  │    │   │    │
[GND][GND][GND][GND]
""",
    R1=R("1k"), R2=R("1k"), R3=R("1k"), R4=R("1k"),
)


def test_spice_node_order_is_c_b_e_whatever_the_pinout():
    from yasdl.parts import BD139, Q2N3904

    block = TWO_PINOUTS.bind(Q1=Q2N3904(), Q2=BD139(model="2N3904"))
    nets = netlist(block)
    assert "Q1.3" in nets["VCC"] and "Q2.2" in nets["VCC"]  # collectors
    text = spice_netlist(block)
    q1 = re.search(r"^Q_Q1 (\S+) (\S+) (\S+) 2N3904$", text, re.M).groups()
    q2 = re.search(r"^Q_Q2 (\S+) (\S+) (\S+) 2N3904$", text, re.M).groups()
    assert q1[0] == q2[0] == "VCC"


@pytest.mark.integration
@kicad
def test_two_pinouts_in_one_schematic(tmp_path):
    """Both parts share Q_NPN geometry but keep their own physical numbers in KiCad."""
    from yasdl.kicad_export import render
    from yasdl.kicad_sch import export_netlist_full
    from yasdl.parts import BD139, Q2N3904

    block = TWO_PINOUTS.bind(Q1=Q2N3904(), Q2=BD139(model="2N3904"))
    info = render(block, tmp_path, svg=False, spice=True, spice_libs=(str(JELLYBEAN_MODEL),))
    assert info["roundtrip_ok"], (info["missing"], info["extra"])
    assert info["erc"] == [], info["erc"]
    assert info["spice_ok"], info["spice_diff"]
    nets, comps = export_netlist_full(info["schematic"])
    assert {("Q1", "3"), ("Q2", "2")} <= nets["VCC"]  # collectors: TO-92 pin 3, TO-126 pin 2
    base1 = next(n for n in nets.values() if ("Q1", "2") in n)
    base2 = next(n for n in nets.values() if ("Q2", "3") in n)
    assert ("R1", "1") in base1 and ("R3", "1") in base2
    assert comps["Q1"]["footprint"] == "Package_TO_SOT_THT:TO-92_Inline"
    assert comps["Q2"]["footprint"] == "Package_TO_SOT_THT:TO-126-3_Vertical"
    assert "onsemi" in comps["Q1"]["datasheet"]
    lib = (tmp_path / "yasdl_parts.kicad_sym").read_text()
    assert '(symbol "2N3904"' in lib and '(symbol "BD139"' in lib


@pytest.mark.integration
@kicad
def test_generic_parts_keep_blank_metadata(tmp_path):
    from yasdl import NPN
    from yasdl.kicad_export import render
    from yasdl.kicad_sch import export_netlist_full

    block = TWO_PINOUTS.bind(Q1=NPN("2N3904"), Q2=AtomNPN("PLAIN", {"E": "1", "B": "2", "C": "3"},
                                                            model="2N3904"))
    info = render(block, tmp_path, svg=False)
    assert info["roundtrip_ok"] and info["erc"] == [], info
    _, comps = export_netlist_full(info["schematic"])
    assert comps["Q1"]["footprint"] == "" and comps["Q2"]["footprint"] == ""
    assert comps["Q2"]["datasheet"] in ("", "~")


def test_opamp5_factory_maps_model_pins(tmp_path):
    lib = tmp_path / "single.lib"
    lib.write_text(".subckt SINGLE 1 2 3 4 5\n* noninv inv vcc vee out\nB1 5 0 V=1e5*(V(1)-V(2))\n.ends\n")
    tl071 = AtomOpamp5("TL071_T", {"+": "3", "-": "2", "V+": "7", "V-": "4", "out": "6"},
                       model="SINGLE", library=lib)
    assert tl071.spice.pins == ("3", "2", "7", "4", "6")
    assert tl071.spice.sim_pins == "3=1 2=2 7=3 4=4 6=5"
    assert factory_pins(tl071) == {"3": "+", "2": "-", "7": "V+", "4": "V-", "6": "out"}
    with pytest.raises(YasdlError, match="exactly the roles"):
        AtomOpamp5("TL071_U", {"+": "3", "-": "2", "out": "6"}, model="SINGLE", library=lib)
