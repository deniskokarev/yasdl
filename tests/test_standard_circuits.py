"""Standard topology connectivity fixtures, actual exports and selected device behavior."""

import math
import re
import shutil
import subprocess

import pytest
from yasdl import AtomOpamp5, SpiceModel, YasdlError, netlist, spice_netlist
from yasdl.circuits import (
    Darlington,
    Sziklai,
    PushPull,
    CurrentMirror,
    CurrentSink,
    DifferentialPair,
    LowPass,
    HighPass,
    BandPass,
    PoweredOpamp,
    NonInverting,
    Inverting,
    Integrator,
    Differentiator,
)
from yasdl.kicad_lib import KICAD_CLI
from yasdl.kicad_export import render
from yasdl.spice import parse_spice


def nets(block):
    return {frozenset(v) for v in netlist(block).values()}


@pytest.mark.parametrize("pnp", [False, True])
def test_darlington_and_cfp_topology_fixtures(pnp):
    d = Darlington(pnp=pnp)
    assert nets(d) == {
        frozenset(("QD.3", "QO.3")),
        frozenset(("QD.2",)),
        frozenset(("QD.1", "QO.2", "RD.1")),
        frozenset(("QO.1", "RD.2")),
    }
    s = Sziklai(pnp=pnp)
    assert nets(s) == {
        frozenset(("QO.1", "RB.1")),
        frozenset(("QD.3", "QO.2", "RB.2")),
        frozenset(("QD.2",)),
        frozenset(("QD.1", "QO.3")),
    }
    text = spice_netlist(s)
    models = {n: v for n, _, v in parse_spice(text)}
    assert models["Q_QD"] == ("2N3906" if pnp else "2N3904")
    assert models["Q_QO"] == ("2N3904" if pnp else "2N3906")


@pytest.mark.parametrize("degeneration", [None, "100"])
def test_current_mirror_node_fixture(degeneration):
    b = CurrentMirror(degeneration=degeneration)
    groups = nets(b)
    assert frozenset(("Q1.3", "Q1.2", "Q2.2")) in groups
    assert frozenset(("Q2.3",)) in groups
    if degeneration:
        assert frozenset(("Q1.1", "RE1.1")) in groups
        assert frozenset(("Q2.1", "RE2.1")) in groups
        assert frozenset(("RE1.2", "RE2.2")) in groups
    else:
        assert frozenset(("Q1.1", "Q2.1")) in groups
    # The same mirror with its emitters on the VEE rail instead of a {common} port.
    from yasdl import standard

    railed = netlist(standard.current_mirror(degeneration))
    assert netlist(CurrentMirror(degeneration=degeneration, rail="VEE")) == railed
    assert railed["ref"] == ["Q1.2", "Q1.3", "Q2.2"]
    assert railed["out"] == ["Q2.3"]
    if degeneration:
        assert railed["VEE"] == ["RE1.2", "RE2.2"]
        assert len([n for n, _, _ in parse_spice(spice_netlist(standard.current_mirror(degeneration))) if n.startswith("R_")]) == 2
    else:
        assert railed["VEE"] == ["Q1.1", "Q2.1"]


@pytest.mark.parametrize("tail", ["resistor", "active"])
def test_differential_pair_emitter_and_base_identity(tail):
    b = DifferentialPair(tail=tail)
    assert frozenset(("Q1.1", "RE1.1")) in nets(b)
    assert frozenset(("Q2.1", "RE2.1")) in nets(b)
    assert netlist(b)["inp"] == ["Q1.2"]
    assert netlist(b)["inn"] == ["Q2.2"]
    assert netlist(b)["left"] == ["Q1.3"]
    assert netlist(b)["right"] == ["Q2.3"]


@pytest.mark.parametrize(
    "variant,diodes", [("bjt", 2), ("darlington", 4), ("sziklai", 2)]
)
def test_pushpull_bias_and_complementary_output_identity(variant, diodes):
    b = PushPull(variant=variant)
    elements = parse_spice(spice_netlist(b))
    assert len([n for n, _, _ in elements if n.startswith("D_DS_")]) == diodes
    models = {n: v for n, _, v in elements if n.startswith("Q_")}
    if variant == "bjt":
        assert models["Q_HI_Q1"] == "2N3904" and models["Q_LO_Q1"] == "2N3906"
    elif variant == "darlington":
        assert models["Q_HI_QD"] == models["Q_HI_QO_Q1"] == "2N3904"
        assert models["Q_LO_QD"] == models["Q_LO_QO_Q1"] == "2N3906"
    else:
        assert models["Q_HI_QD"] == "2N3904" and models["Q_HI_QO_Q1"] == "2N3906"
        assert models["Q_LO_QD"] == "2N3906" and models["Q_LO_QO_Q1"] == "2N3904"
    assert b.crossing_count == 0
    assert PushPull(variant=variant, parallel=4).crossing_count == 6


@pytest.mark.parametrize(
    "f",
    [LowPass, HighPass, BandPass, NonInverting, Inverting, Integrator, Differentiator],
)
def test_common_filter_and_opamp_components(f):
    b = f()
    text = spice_netlist(b)
    assert "in" in netlist(b) and "out" in netlist(b)
    assert parse_spice(text)
    if f == Integrator:
        assert "C_RF " in text
    if f == Differentiator:
        assert "C_RI " in text
    if f in (LowPass, HighPass):
        assert (
            netlist(b)["GND"] == ["C1.2"]
            if f == LowPass
            else netlist(b)["GND"] == ["R1.2"]
        )


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(), reason="KiCad 9 missing")
@pytest.mark.parametrize(
    "factory",
    [
        Darlington,
        Sziklai,
        CurrentMirror,
        lambda: CurrentMirror(degeneration="100"),
        CurrentSink,
        DifferentialPair,
        lambda: DifferentialPair(tail="active"),
        LowPass,
        HighPass,
        BandPass,
        NonInverting,
        Inverting,
        Integrator,
        Differentiator,
        lambda: PushPull(variant="bjt"),
        lambda: PushPull(variant="darlington"),
        lambda: PushPull(variant="sziklai"),
    ],
)
def test_standard_blocks_live_kicad_exports(tmp_path, factory):
    b = factory()
    info = render(b, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"] and info["spice_ok"] and info["erc"] == [], info


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice missing")
@pytest.mark.parametrize(
    "variant,bias", [("bjt", 0.68), ("darlington", 1.3), ("sziklai", 0.68)]
)
def test_output_variants_selected_model_characterization(tmp_path, variant, bias):
    b = PushPull(variant=variant, ballast="1")
    text = spice_netlist(b, subckt="stage", port_order=["hi", "lo", "out"])
    deck = tmp_path / "tb.cir"
    deck.write_text(
        "* output stage\n"
        + text
        + f"VP VCC 0 5\nVM VEE 0 -5\nVH hi 0 SIN({bias} 0.2 1000)\nIL lo VEE 3m\nX1 hi lo out stage\nRL out 0 100\n.control\ntran 1u 20m\nmeas tran output rms v(out) from=10m to=20m\nmeas tran vmax max v(out) from=10m to=20m\nmeas tran vmin min v(out) from=10m to=20m\n.endc\n.end\n"
    )
    r = subprocess.run(
        ["ngspice", "-b", str(deck)], capture_output=True, text=True, timeout=60
    )
    log = r.stdout + r.stderr
    assert r.returncode == 0 and not re.search(r"error|failed", log, re.I), log
    values = {
        key: float(re.search(r"^" + key + r"\s*=\s*([\d.eE+-]+)", log, re.M)[1])
        for key in ["output", "vmax", "vmin"]
    }
    assert all(math.isfinite(v) for v in values.values())
    assert 0.25 < values["vmax"] - values["vmin"] < 0.45
    assert values["output"] < 0.5


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(), reason="KiCad 9 missing")
def test_powered_wrapper_mirror_keeps_physical_rails(tmp_path):
    lib = tmp_path / "amp.lib"
    lib.write_text(".subckt amp p m vp vm out\nE1 out 0 p m 10000\n.ends\n")
    atom = AtomOpamp5(
        "amp",
        pins={"inp": 3, "inn": 2, "out": 6, "V+": 7, "V-": 4},
        spice=SpiceModel(
            "X", ("3", "2", "7", "4", "6"), "amp", "3=p 2=m 7=vp 4=vm 6=out", str(lib)
        ),
    )
    powered = PoweredOpamp(atom)
    # Mirrored input placement: rail labels remain internal to the wrapper.
    b = Inverting(opamp=powered)
    info = render(b, tmp_path, spice=True, svg=False)
    assert info["roundtrip_ok"] and info["spice_ok"] and info["erc"] == [], info
    assert netlist(b)["VCC"] == ["U1.U1.7"]
    assert netlist(b)["VEE"] == ["U1.U1.4"]
    assert ".global VCC VEE" in spice_netlist(b, subckt="wrapped")


def test_standard_variant_validation():
    for kwargs in [{"variant": "wrong"}, {"parallel": 3}]:
        with pytest.raises(YasdlError):
            PushPull(**kwargs)
    with pytest.raises(YasdlError):
        DifferentialPair(tail="wrong")
