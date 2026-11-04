"""Contracts of the consolidated API that neither source suite covered on its own."""

import pytest
from yasdl import (
    AtomOpamp5,
    Block,
    NC,
    Package,
    R,
    SpiceModel,
    YasdlError,
    netlist,
    spice_netlist,
)
from yasdl.kicad_export import roundtrip, to_kicad
from yasdl.kicad_lib import BUNDLED_MODELS, KICAD_CLI, library_path, load
from yasdl.sexp import find, find_all, parse
from yasdl.spice import parse_spice


def exact_unit_pins(name):
    """{unit: {pin name: number}} of an exact KiCad Amplifier_Operational symbol,
    resolving (extends). Independent of yasdl's package factory."""
    root = parse(library_path("Amplifier_Operational").read_text())
    symbols = {str(s[1]): s for s in find_all(root, "symbol")}
    sym = symbols[name]
    while find(sym, "extends") is not None:
        sym = symbols[str(find(sym, "extends")[1])]
    units = {}
    for unit in find_all(sym, "symbol"):
        number = int(str(unit[1]).rsplit("_", 2)[1])
        for pin in find_all(unit, "pin"):
            units.setdefault(number, {})[str(find(pin, "name")[1])] = str(
                find(pin, "number")[1]
            )
    return units


@pytest.mark.integration
@pytest.mark.skipif(
    not library_path("Amplifier_Operational").exists(),
    reason="installed KiCad 9 Amplifier_Operational library is the reference",
)
@pytest.mark.parametrize("device", ["LM358", "TL072"])
def test_default_dual_opamp_pinouts_match_exact_kicad_symbols(device):
    chip = Package(device)
    views = {
        i: {p.name: p.number for p in chip.unit(u).symbol.pins}
        for i, u in enumerate("ABC", 1)
    }
    assert views == exact_unit_pins(device)
    with pytest.raises(YasdlError, match="explicit units"):
        Package("NE5532")


def test_package_model_arguments_build_one_whole_device_instance(tmp_path):
    lib = tmp_path / "dual.lib"
    lib.write_text(".subckt dual a b c d e f g h\n.ends\n")
    order = ("8", "4", "3", "2", "1", "5", "6", "7")
    chip = Package("TL072", library=lib, model_name="dual", model_order=order)
    m = chip.unit("A").spice
    assert (m.pins, m.model, m.library) == (order, "dual", str(lib))
    assert chip.unit("C").spice is m
    default = Package().unit("B").spice
    assert default.model == "yasdl_dual_opamp" and default.library == str(BUNDLED_MODELS)
    assert default.pins == ("3", "2", "1", "5", "6", "7", "8", "4")
    with pytest.raises(YasdlError, match="every package pin once"):
        Package(model_order=("3", "2", "1"))
    with pytest.raises(YasdlError, match="either spice"):
        Package(spice=default, model_name="dual")
    with pytest.raises(AttributeError, match="immutable"):
        chip.name = "other"


def test_opamp_role_keys_accept_both_spellings(tmp_path):
    upper = AtomOpamp5("a", pins={"INP": 3, "inn": 2, "Out": 1, "V+": 8, "vm": 4})
    lower = AtomOpamp5("b", pins={"inp": 3, "inn": 2, "out": 1, "vp": 8, "V-": 4})
    assert {p.name: p.number for p in upper.symbol.pins} == {
        p.name: p.number for p in lower.symbol.pins
    }
    with pytest.raises(YasdlError, match="twice"):
        AtomOpamp5("c", pins={"inp": 3, "inn": 2, "out": 1, "vp": 8, "V+": 7})
    with pytest.raises(YasdlError, match="either spice"):
        AtomOpamp5(
            "d",
            {"inp": 3, "inn": 2, "out": 1, "vp": 8, "vm": 4},
            tmp_path / "m.lib",
            "m",
            spice=SpiceModel("X", ("3", "2", "8", "4", "1"), "m"),
        )


def test_spice_instance_names_must_not_collide():
    child = Block("Child", "{x}─B1─{y}", B1=R("1k"))
    b = Block(
        "Collide", "{a}─A1_B1─{b}\n\n{p}──A1───{q}", A1_B1=R("1k"), A1=child
    )
    assert len(netlist(b)) == 4
    with pytest.raises(YasdlError, match="instance name collision: R_A1_B1"):
        spice_netlist(b)


def test_comparison_parser_rejects_unknown_elements_and_reads_mosfets():
    assert parse_spice("M1 d g s b NMOD w=1u") == [
        ("M1", ["d", "g", "s", "b"], "NMOD w=1u")
    ]
    with pytest.raises(YasdlError, match="Unsupported SPICE comparison element"):
        parse_spice("R1 a 0 1k\nE1 b 0 a 0 10\n")


def test_cached_library_symbols_cannot_be_edited():
    sym = load("Device:R").sexp
    with pytest.raises(TypeError, match="immutable"):
        sym.append("extra")
    with pytest.raises(TypeError):
        sym[1] = "renamed"
    assert load("Device:R").sexp[1] == "R"


def test_nc_endpoints_reject_pin_labels():
    with pytest.raises(YasdlError, match="no pin labels"):
        Block("Labelled", "NC1{x}─R1─{out}", NC1=NC(), R1=R("1k"))


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(), reason="KiCad 9 CLI missing")
def test_electrical_roundtrip_rejects_a_renamed_global_net(tmp_path):
    b = Block("Ground", "[VCC]─R1─R2─[GND]", R1=R("1k"), R2=R("1k"))
    path, refs = to_kicad(b, tmp_path / "ground.kicad_sch")
    assert roundtrip(b, path, refs)[0]
    # Same pin groups, but the supply symbol now names a different global net.
    path.write_text(path.read_text().replace('"VCC"', '"VXX"'))
    assert not roundtrip(b, path, refs)[0]
