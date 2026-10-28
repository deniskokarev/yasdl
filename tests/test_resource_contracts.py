"""Generic descriptor and export-resource contracts."""
import re
import shutil
import subprocess

import pytest

from yasdl import Block, POT, R, YasdlError
from yasdl.kicad_lib import KICAD_CLI
from yasdl.parts import AtomOpamp5, OpampPackage


def test_package_copies_and_freezes_caller_maps():
    units = {"A": {"+": 3, "-": 2, "out": 1}, "B": {"+": 5, "-": 6, "out": 7}}
    power = {"V+": 8, "V-": 4}
    descriptor = OpampPackage("IMMUTABLE_DUAL", units, power)
    units["A"]["+"] = 99
    power["V+"] = 99
    assert descriptor.units["A"]["+"] == "3"
    assert descriptor.power["V+"] == "8"
    with pytest.raises(TypeError):
        descriptor.units["A"]["+"] = "99"


def test_opamp_model_mapping_requires_every_role_once():
    pins = {"+": 3, "-": 2, "V+": 7, "V-": 4, "out": 6}
    with pytest.raises(YasdlError, match="every role exactly once"):
        AtomOpamp5("DUPLICATE_MODEL_ROLE", pins, model="m", model_pins=("+", "+", "V+", "V-", "out"))


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(), reason="kicad-cli missing")
def test_spice_export_resolves_models_for_a_renamed_schematic(tmp_path):
    from yasdl.kicad_export import export_kicad_spice, render, spice_roundtrip, to_kicad
    from yasdl.spice import parse_spice

    block = Block("PortablePot", "{a}──RV──{b}\n     │\n     R1\n     │\n   [GND]",
                  RV=POT("10k", rotation=0.25), R1=R("100k"))
    info = render(block, tmp_path, svg=False, spice=True)
    assert info["spice_ok"] and info["roundtrip_ok"] and info["erc"] == []
    copied = tmp_path / "Renamed.kicad_sch"
    shutil.copyfile(info["schematic"], copied)
    elements = parse_spice(export_kicad_spice(copied))
    assert any(value == "yasdl_pot R=10k POS=0.25" for _, _, value in elements)
    _, refmap = to_kicad(block, tmp_path / "Original.kicad_sch")
    assert spice_roundtrip(block, copied, refmap)[0]


def test_subckt_port_order_cannot_repeat_a_port():
    from yasdl import spice_netlist
    block = Block("TwoPorts", "{a}──R1──{b}", R1=R("1k"))
    with pytest.raises(YasdlError, match="every port once"):
        spice_netlist(block, subckt="two", port_order=["a", "a"])


def test_renaming_a_block_preserves_its_port_aliases_and_circuit():
    from yasdl import netlist
    original = Block("Original", "{a}──R1──{b}", R1=R("2k"),
                     port_attrs={"a": {"aliases": ["input"]}})
    renamed = original.renamed("DisplayName")
    assert original.name == "Original" and renamed.name == "DisplayName"
    assert renamed.port("input") == renamed.port("a")
    assert netlist(renamed) == {"a": ["R1.1"], "b": ["R1.2"]}


def test_spice_nodes_are_case_insensitive_but_supply_identity_is_preserved():
    from yasdl.spice import compare_spice
    original = "R1 VCC 0 1k\nR2 vcc out 2k\n"
    canonical = "R1 VCC 0 1k\nR2 VCC out 2k\n"
    assert compare_spice(original, canonical, str, str, named=["VCC"])[0]
    assert not compare_spice(original, canonical.replace("VCC", "VEE"), str, str, named=["VCC", "VEE"])[0]


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice missing")
@pytest.mark.parametrize("kind", ["lowpass", "highpass"])
def test_sallen_key_explicit_roles_preserve_the_1125hz_characterization(tmp_path, kind):
    """Equal 10k series R / 20n feedback,10n shunt C and the dual HP are Butterworth."""
    from yasdl import spice_netlist, std
    if kind == "lowpass":
        block = std.sallen_key_lowpass("10k", "10k", c_shunt="10n", c_feedback="20n")
    else:
        block = std.sallen_key_highpass("10n", "10n", r_shunt="20k", r_feedback="10k")
    circuit = spice_netlist(block, subckt="filter", port_order=["in", "out"])
    deck = "* corner\n" + circuit + "VI in 0 ac 1\nX1 in out filter\nRL out 0 1e9\n.control\nac lin 1 1125.3953951963827 1125.3953951963827\nprint vm(out)\n.endc\n.end\n"
    path = tmp_path / "corner.cir"
    path.write_text(deck)
    run = subprocess.run(["ngspice", "-b", str(path)], capture_output=True, text=True, check=True)
    result = re.search(r"vm\(out\)\s*=\s*([-+\d.eE]+)", run.stdout)
    assert result, run.stdout + run.stderr
    assert float(result.group(1)) == pytest.approx(0.7071067811865476, rel=0.01)
