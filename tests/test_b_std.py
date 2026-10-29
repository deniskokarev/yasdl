"""P2: the standard Blocks library (spec 8): connectivity, KiCad export, and ngspice
characterization of each output-stage variant with the bundled jellybean models."""

import re
import shutil
import subprocess

import pytest
from yasdl import Block, netlist, OPAMP, OPAMP_IDEAL, R, spice_netlist, V
from yasdl import std
from yasdl.kicad_lib import JELLYBEAN_MODEL, KICAD_CLI
from yasdl.parts import D1N4148, Q2N3904, Q2N3906

kicad = pytest.mark.skipif(not KICAD_CLI.exists(), reason="kicad-cli missing")
have_ngspice = shutil.which("ngspice") is not None
ngspice = pytest.mark.skipif(not have_ngspice, reason="ngspice missing")


def stage(variant, n=None):
    """A push-pull stage of the given variant with jellybean parts (n: output arrays)."""
    npn, pnp = Q2N3904(), Q2N3906()
    if n:
        npn, pnp = std.parallel(npn, n, name=f"ArrN{n}"), std.parallel(pnp, n, name=f"ArrP{n}")
    upper, lower = {
        "bjt": (npn, pnp),
        "darlington": (std.darlington(Q2N3904(), npn, name="DarlN"),
                       std.darlington(Q2N3906(), pnp, name="DarlP")),
        "sziklai": (std.sziklai(Q2N3904(), pnp, name="SzN"),
                    std.sziklai(Q2N3906(), npn, name="SzP")),
    }[variant]
    return std.push_pull(variant, upper, lower, diode=D1N4148())


# --- connectivity ----------------------------------------------------------------------------
def test_darlington_and_sziklai_connections():
    d = netlist(std.darlington(Q2N3904(), Q2N3904()))
    assert sorted(d["c"]) == ["Q1.3", "Q2.3"]  # collectors tied
    assert sorted(next(v for v in d.values() if "Q1.1" in v)) == ["Q1.1", "Q2.2", "RX.1"]
    assert sorted(d["e"]) == ["Q2.1", "RX.2"]
    s = netlist(std.sziklai(Q2N3904(), Q2N3906()))
    assert sorted(s["e"]) == ["Q1.1", "Q2.3"]  # driver emitter = output collector
    assert sorted(s["c"]) == ["Q2.1", "RX.1"]  # output emitter is the compound collector
    assert sorted(next(v for v in s.values() if "Q1.3" in v)) == ["Q1.3", "Q2.2", "RX.2"]


@pytest.mark.parametrize("n", [2, 4])
def test_parallel_array(n):
    arr = std.parallel(Q2N3904(), n)
    nets = netlist(arr)
    assert sorted(nets["b"]) == [f"Q{k}.2" for k in range(1, n + 1)]
    assert sorted(nets["c"]) == [f"Q{k}.3" for k in range(1, n + 1)]
    assert sorted(nets["e"]) == [f"RE{k}.2" for k in range(1, n + 1)]
    assert len(arr.canvas.crossings) == n - 1  # three-terminal parts in parallel: non-planar
    assert [(p.side, p.name) for p in sorted(arr.ports, key=lambda p: p.side)] == \
        [("N", "c"), ("S", "e"), ("W", "b")]


@pytest.mark.parametrize("variant, diodes", [("bjt", 1), ("darlington", 2), ("sziklai", 1)])
def test_push_pull_bias_string_matches_variant(variant, diodes):
    b = stage(variant)
    nets = netlist(b)
    dh = sorted(k for k in b.bound if k.startswith("DH"))
    assert len(dh) == diodes and len([k for k in b.bound if k.startswith("DL")]) == diodes
    upper_base = next(v for v in nets.values() if "RT.2" in v)
    assert f"DH1.2" in upper_base  # string top: anode of the first diode, upper base, RT
    assert any(p.startswith("QH.") for p in upper_base)
    assert f"DH{diodes}.1" in nets["in"] and "RQ.1" in nets["in"]
    assert sorted(nets["out"]) == ["RH.2", "RL.1"]


def test_mirrors_and_pairs():
    m = netlist(std.mirror(Q2N3904()))
    assert sorted(m["in"]) == ["Q1.2", "Q1.3", "Q2.2"] and m["out"] == ["Q2.3"]
    w = netlist(std.wilson_mirror(Q2N3906(), "pnp"))
    assert sorted(w["in"]) == ["Q1.3", "Q3.2"] and w["out"] == ["Q3.3"]
    assert sorted(w["vp"]) == ["Q1.1", "Q2.1"]
    p = netlist(std.diff_pair(Q2N3906(), "pnp"))
    assert p["vp"] == ["RT.1"] and sorted(p["vn"]) == ["RC1.2", "RC2.2"]
    pm = netlist(std.diff_pair_mirror(Q2N3904(), Q2N3906()))
    assert sorted(pm["out"]) == ["Q2.3", "Q4.3"]
    assert sorted(next(v for v in pm.values() if "Q3.3" in v)) == ["Q1.3", "Q3.2", "Q3.3", "Q4.2"]


def test_opamp_circuits_take_any_three_terminal_opamp():
    inv = std.INVERTING.bind(RI=R("10k"), RF=R("47k"), U1=OPAMP_IDEAL())
    assert netlist(inv)["GND"] == ["U1.1"]
    wrapped = std.INVERTING.bind(RI=R("10k"), RF=R("47k"), U1=std.powered_opamp(OPAMP()))
    nets = netlist(wrapped)
    assert nets["GND"] == ["U1.U1.1"] and nets["VCC"] == ["U1.U1.3"]
    assert sorted(netlist(std.OPAMP_UNUSED.bind(U1=OPAMP_IDEAL()))["GND"]) == ["U1.1"]


# --- KiCad --------------------------------------------------------------------------------------
STANDALONE = {
    "darlington": lambda: std.darlington(Q2N3904(), Q2N3904()),
    "sziklai": lambda: std.sziklai(Q2N3904(), Q2N3906()),
    "parallel3": lambda: std.parallel(Q2N3906(), 3),
    "push_pull_darlington_arrays": lambda: stage("darlington", n=2),
    "push_pull_sziklai": lambda: stage("sziklai"),
    "mirror_pnp": lambda: std.mirror(Q2N3906(), "pnp"),
    "wilson_npn": lambda: std.wilson_mirror(Q2N3904()),
    "diff_pair_mirror_pnp": lambda: std.diff_pair_mirror(Q2N3906(), Q2N3904(), "pnp"),
    "sallen_key_lp": lambda: std.sallen_key_lowpass("10k", "10k", "10n", "22n", OPAMP_IDEAL()),
    "noninverting": lambda: std.NONINVERTING.bind(RG=R("1k"), RF=R("3k"), U1=OPAMP_IDEAL()),
}


@pytest.mark.integration
@kicad
@pytest.mark.parametrize("key", list(STANDALONE))
def test_standard_blocks_render_cleanly(tmp_path, key):
    from yasdl.kicad_export import render

    info = render(STANDALONE[key](), tmp_path, svg=False, spice=True,
                  spice_libs=(str(JELLYBEAN_MODEL),))
    assert info["roundtrip_ok"], (info["missing"], info["extra"])
    assert info["erc"] == [], info["erc"]
    assert info["spice_ok"], info["spice_diff"]


# --- ngspice characterization -------------------------------------------------------------------
def run(tmp_path, deck, name="tb.cir"):
    (tmp_path / name).write_text(deck)
    out = subprocess.run(["ngspice", "-b", name], cwd=tmp_path, capture_output=True, text=True,
                         timeout=600)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "error" not in out.stdout.lower().replace("errors: 0", ""), out.stdout
    return out.stdout


def meas(text, name):
    m = re.search(rf"^{name}\s*=\s*([-+\d.eE]+)", text, re.M)
    assert m, f"measurement {name} missing:\n{text}"
    return float(m.group(1))


def stage_bench(block, amplitude):
    sub = spice_netlist(block, subckt="stage", port_order=["vp", "in", "out", "vn"])
    return (
        f"* push-pull characterization\n{sub}"
        "VP vp 0 9\nVN vn 0 -9\n"
        f"VIN in 0 dc 0 sin(0 {amplitude} 1k)\n"
        "X1 vp in out vn stage\nRL out 0 8\n"
        ".tran 2u 6m 2m 2u\n.control\nrun\n"
        "meas tran iq avg i(VP) from=2m to=6m\n"
        "meas tran vout_rms rms v(out) from=2m to=6m\n"
        "meas tran vin_rms rms v(in) from=2m to=6m\n"
        "fourier 1k v(out)\n.endc\n.end\n"
    )


def thd(text):
    m = re.search(r"THD:\s*([-+\d.eE]+)", text)
    assert m, text
    return float(m.group(1))


@pytest.mark.integration
@ngspice
@pytest.mark.parametrize("variant, n", [("bjt", None), ("darlington", 2), ("sziklai", None),
                                        ("darlington", None)])
def test_push_pull_variants_are_biased_and_linear(tmp_path, variant, n):
    """Quiescent current flows (no dead band), gain near 1 into 8 ohm at 2 Vpk, THD < 2 %."""
    quiet = run(tmp_path, stage_bench(stage(variant, n), 0.0), "q.cir")
    iq = -meas(quiet, "iq")
    assert 0.5e-3 < iq < 0.2, iq
    loud = run(tmp_path, stage_bench(stage(variant, n), 2.0))
    gain = meas(loud, "vout_rms") / meas(loud, "vin_rms")
    assert 0.8 < gain < 1.02, gain
    assert thd(loud) < 2.0, thd(loud)


@pytest.mark.integration
@ngspice
def test_darlington_needs_its_own_bias_string(tmp_path):
    """The same Darlington halves in a one-diode (BJT) string are under-biased: the drawing
    alone would accept them, so the variant must choose the bias network deliberately."""
    up = std.darlington(Q2N3904(), Q2N3904(), name="DarlN")
    lo = std.darlington(Q2N3906(), Q2N3906(), name="DarlP")
    right = run(tmp_path, stage_bench(std.push_pull("darlington", up, lo), 1.0), "a.cir")
    wrong = run(tmp_path, stage_bench(std.push_pull("bjt", up, lo), 1.0), "b.cir")
    assert thd(wrong) > 3 * thd(right)


@pytest.mark.integration
@ngspice
@pytest.mark.parametrize("kind, q, wilson", [("npn", Q2N3904, False), ("pnp", Q2N3906, False),
                                             ("npn", Q2N3904, True), ("pnp", Q2N3906, True)])
def test_mirrors_copy_the_reference_current(tmp_path, kind, q, wilson):
    block = std.wilson_mirror(q(), kind) if wilson else std.mirror(q(), kind)
    rail = "vn" if kind == "npn" else "vp"
    sub = spice_netlist(block, subckt="m", port_order=[rail, "in", "out"])
    sign = 1 if kind == "npn" else -1
    deck = (
        f"* mirror\n{sub}"
        f"VR {rail} 0 {-9 * sign}\n"
        f"IREF 0 in {sign * 1e-3}\n"  # 1 mA into (npn) or out of (pnp) the reference
        f"VO out 0 0\nX1 {rail} in out m\n.control\nop\nprint i(VO)\n.endc\n.end\n"
    )
    text = run(tmp_path, deck)
    i_out = float(re.search(r"^i\(vo\)\s*=\s*([-+\d.eE]+)", text, re.M).group(1))
    assert abs(abs(i_out) - 1e-3) < 0.1e-3, i_out


@pytest.mark.integration
@ngspice
@pytest.mark.parametrize("kind", ["lowpass", "highpass"])
def test_sallen_key_corner(tmp_path, kind):
    """Butterworth sections (Q = 0.707) at 1 kHz: -3 dB at the corner within 5 %."""
    if kind == "lowpass":
        block = std.sallen_key_lowpass("10k", "10k", "11.25n", "22.5n", OPAMP_IDEAL())
    else:
        block = std.sallen_key_highpass("10n", "10n", "22.5k", "11.25k", OPAMP_IDEAL())
    bench = Block("SKBench", "  ┌──SK──{out}\n  +\n  V1\n  │\n[GND]\n", V1=V("dc 0 ac 1"),
                  SK=block)
    deck = spice_netlist(bench) + (
        ".ac dec 200 10 100k\n.control\nrun\n"
        "meas ac f3db when vdb(out)=-3.0103\n.endc\n.end\n"
    )
    assert abs(meas(run(tmp_path, deck), "f3db") - 1000) < 50
