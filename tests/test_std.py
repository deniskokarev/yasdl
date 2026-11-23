"""Standard Blocks (P2.4), the powered op-amp wrapper and five-pin op-amp orientation
(P0 DECISIONS 7-8): KiCad checks for every block, ngspice characterisation of the
behaviour each block promises."""

import math
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from yasdl import (
    Block,
    netlist,
    OPAMP,
    OPAMP_IDEAL,
    R,
    spice_netlist,
    std,
    V,
    YasdlError,
)
from yasdl.kicad_lib import BUNDLED_MODELS, JELLYBEAN_MODEL, KICAD_CLI
from yasdl.parts import AtomOpamp5, D1N4148, IDEAL_DUAL, Package, Q2N3904, Q2N3906

have_kicad = KICAD_CLI.exists()
have_ngspice = shutil.which("ngspice") is not None
ngspice = pytest.mark.skipif(not have_ngspice, reason="ngspice missing")

OP5 = AtomOpamp5(
    "IDEAL_OP5",
    {"+": 3, "-": 2, "out": 6, "V+": 7, "V-": 4},
    model="yasdl_ideal_opamp5",
    library=BUNDLED_MODELS,
)

BLOCKS = {
    "powered": lambda: std.powered(OP5),
    "follower": lambda: std.follower(),
    "noninverting": lambda: std.noninverting("10k", "1k"),
    "inverting": lambda: std.inverting("10k", "20k"),
    "rc_lowpass": lambda: std.rc_lowpass("1k", "1u"),
    "rc_highpass": lambda: std.rc_highpass("1u", "1k"),
    "sallen_key_lowpass": lambda: std.sallen_key_lowpass("10k", "10k", "20n", "10n"),
    "sallen_key_highpass": lambda: std.sallen_key_highpass("10n", "10n", "10k", "20k"),
    "darlington_npn": lambda: std.darlington(Q2N3904),
    "darlington_pnp": lambda: std.darlington(Q2N3906),
    "sziklai_npn": lambda: std.sziklai(Q2N3904, Q2N3906),
    "sziklai_pnp": lambda: std.sziklai(Q2N3906, Q2N3904),
    "parallel3": lambda: std.parallel(Q2N3904, 3, "1"),
    "diodes2": lambda: std.diode_string(2, D1N4148),
    "vbe_multiplier": lambda: std.vbe_multiplier(Q2N3904, "2.7k", "1k"),
    "mirror": lambda: std.mirror(Q2N3904),
    "wilson": lambda: std.wilson(Q2N3904),
    "diff_pair": lambda: std.diff_pair(Q2N3904, rc="10k", rt="10k"),
    "diff_pair_mirror": lambda: std.diff_pair_mirror(Q2N3904, Q2N3906, rt="10k"),
    "darlington_plain": lambda: std.darlington(Q2N3904, rx=None),
    "mirror_degenerated": lambda: std.mirror(Q2N3904, re="100"),
    "diff_pair_degenerated": lambda: std.diff_pair(Q2N3904, re="100"),
    "diff_pair_current_sink": lambda: std.diff_pair(
        Q2N3904, re="100", rt=std.current_sink(Q2N3904, diode=D1N4148)
    ),
    "current_sink": lambda: std.current_sink(Q2N3904, diode=D1N4148),
    "rc_bandpass": lambda: std.rc_bandpass("1u", "10k", "10k", "10n"),
    "integrator": lambda: std.integrator("10k", "10n"),
    "differentiator": lambda: std.differentiator("10n", "10k"),
    "push_pull_core_bjt": lambda: std.push_pull_core("bjt", Q2N3904, Q2N3906, D1N4148),
    "push_pull_core_darlington": lambda: std.push_pull_core(
        "darlington", Q2N3904, Q2N3906, D1N4148
    ),
    "push_pull_core_sziklai": lambda: std.push_pull_core(
        "sziklai", Q2N3904, Q2N3906, D1N4148
    ),
    "push_pull_bjt": lambda: std.push_pull("bjt", Q2N3904, Q2N3906, D1N4148),
    "push_pull_darlington": lambda: std.push_pull(
        "darlington", Q2N3904, Q2N3906, D1N4148
    ),
    "push_pull_sziklai": lambda: std.push_pull("sziklai", Q2N3904, Q2N3906, D1N4148),
}


@pytest.mark.integration
@pytest.mark.skipif(not have_kicad, reason="kicad-cli missing")
@pytest.mark.parametrize("name", sorted(BLOCKS))
def test_every_standard_block_renders_clean(tmp_path: Path, name: str) -> None:
    from yasdl.kicad_export import render

    block = BLOCKS[name]()
    info = render(block, tmp_path, svg=False, spice=True, spice_libs=(JELLYBEAN_MODEL,))
    assert info["roundtrip_ok"], (info["missing"], info["extra"])
    assert info["erc"] == []
    assert info["spice_ok"], info["spice_diff"]


def test_parallel_array_crossings_are_declared() -> None:
    for n in (2, 3, 4):
        assert std.parallel(Q2N3904, n, "1").crossing_count() == n - 1
    with pytest.raises(YasdlError):
        std.parallel(Q2N3904, 1, "1")


def test_compound_devices_share_the_transistor_interface() -> None:
    for blk in (
        std.darlington(Q2N3904),
        std.sziklai(Q2N3904, Q2N3906),
        std.parallel(Q2N3904, 2, "1"),
    ):
        assert {(p.side, p.name) for p in blk.ports} == {
            ("N", "c"),
            ("W", "b"),
            ("S", "e"),
        }


def nets(block: Block) -> set[frozenset[str]]:
    return {frozenset(v) for v in netlist(block).values()}


@pytest.mark.parametrize("re", [None, "100"])
def test_mirror_degeneration_fixture(re: str | None) -> None:
    groups = nets(std.mirror(Q2N3904, re=re))
    assert frozenset(("Q1.3", "Q1.2", "Q2.2")) in groups
    assert frozenset(("Q2.3",)) in groups
    if re:
        assert frozenset(("Q1.1", "RA.1")) in groups
        assert frozenset(("Q2.1", "RB.1")) in groups
        assert frozenset(("RA.2", "RB.2")) in groups
    else:
        assert frozenset(("Q1.1", "Q2.1")) in groups


def test_diff_pair_degeneration_is_a_distinct_topology() -> None:
    plain = netlist(std.diff_pair(Q2N3904))
    assert any(set(ps) == {"Q1.1", "Q2.1", "RT.1"} for ps in plain.values())
    degenerated = netlist(std.diff_pair(Q2N3904, re="100"))
    assert any(set(ps) == {"RE1.2", "RE2.2", "RT.1"} for ps in degenerated.values())


@pytest.mark.parametrize("tail", ["resistor", "current_sink"])
def test_diff_pair_tail_options(tail: str) -> None:
    rt = "6.8k" if tail == "resistor" else std.current_sink(Q2N3904, diode=D1N4148)
    b = std.diff_pair(Q2N3904, re="100", rt=rt)
    assert frozenset(("Q1.1", "RE1.1")) in nets(b)
    assert frozenset(("Q2.1", "RE2.1")) in nets(b)
    n = netlist(b)
    assert (n["inp"], n["inn"]) == (["Q1.2"], ["Q2.2"])
    assert (n["o1"], n["o2"]) == (["Q1.3", "RC1.2"], ["Q2.3", "RC2.2"])
    tail_top = "RT.1" if tail == "resistor" else "RT.Q1.3"
    assert any(set(ps) == {"RE1.2", "RE2.2", tail_top} for ps in n.values())


@pytest.mark.parametrize(
    "kind, diodes", [("bjt", 2), ("darlington", 4), ("sziklai", 2)]
)
def test_push_pull_core_bias_and_complementary_outputs(kind: str, diodes: int) -> None:
    from yasdl.spice import parse_spice

    b = std.push_pull_core(kind, Q2N3904, Q2N3906, D1N4148)
    elements = parse_spice(spice_netlist(b))
    assert len([n for n, _, _ in elements if n.startswith("D_DS_")]) == diodes
    models = {n: v for n, _, v in elements if n.startswith("Q_")}
    if kind == "bjt":
        assert models["Q_HI_Q1"] == "2N3904" and models["Q_LO_Q1"] == "2N3906"
    elif kind == "darlington":
        assert models["Q_HI_Q1"] == models["Q_HI_Q2_Q1"] == "2N3904"
        assert models["Q_LO_Q1"] == models["Q_LO_Q2_Q1"] == "2N3906"
    else:
        assert models["Q_HI_Q1"] == "2N3904" and models["Q_HI_Q2_Q1"] == "2N3906"
        assert models["Q_LO_Q1"] == "2N3906" and models["Q_LO_Q2_Q1"] == "2N3904"
    assert b.crossing_count == 0
    assert std.push_pull_core(kind, Q2N3904, Q2N3906, n=4).crossing_count == 6


def test_integrator_differentiator_and_bandpass() -> None:
    integ = spice_netlist(std.integrator("10k", "10n"))
    assert "C_RF " in integ and "R_RI " in integ
    diff = spice_netlist(std.differentiator("10n", "10k"))
    assert "C_RI " in diff and "R_RF " in diff
    bp = netlist(std.rc_bandpass("1u", "10k", "10k", "10n"))
    assert bp["in"] == ["HP.C1.1"] and sorted(bp["GND"]) == ["HP.R1.2", "LP.C1.2"]


def test_invalid_kinds_are_rejected() -> None:
    for build in (
        lambda: std.push_pull("wrong"),
        lambda: std.push_pull_core("wrong"),
        lambda: std.push_pull_core(n=10),
        lambda: std.mirror(Q2N3904, "wrong"),
        lambda: std.diff_pair(Q2N3904, "wrong"),
    ):
        with pytest.raises(YasdlError):
            build()


# --- simulation helpers -------------------------------------------------------------------
def run(tmp_path: Path, body: str, analyses: str) -> str:
    cir = tmp_path / "tb.cir"
    cir.write_text(
        f"* tb\n.include {JELLYBEAN_MODEL}\n{body}\n.control\n{analyses}\n.endc\n.end\n"
    )
    out = subprocess.run(["ngspice", "-b", str(cir)], capture_output=True, text=True)
    return out.stdout + out.stderr


def value(text: str, name: str) -> float:
    m = re.search(rf"^\s*{re.escape(name)}\s*=\s*(\S+)", text, re.M | re.I)
    assert m, f"{name} missing:\n{text[-3000:]}"
    return float(m.group(1))


def sub(block: Block, name: str, order: list[str]) -> str:
    return spice_netlist(block, subckt=name, port_order=order)


@pytest.mark.integration
@ngspice
@pytest.mark.parametrize(
    "block, gain",
    [
        (std.noninverting("10k", "1k"), 11.0),
        (std.inverting("10k", "20k"), -2.0),
        (std.follower(), 1.0),
        (std.noninverting("10k", "1k", std.powered(OP5)), 11.0),
    ],
)
def test_opamp_circuit_gains(tmp_path: Path, block: Block, gain: float) -> None:
    body = (
        sub(block, "amp", ["in", "out"])
        + "VP VCC 0 15\nVN VEE 0 -15\nVI in 0 0.1\nX1 in out amp\n"
    )
    out = run(tmp_path, body, "op\nprint v(out)")
    assert value(out, "v(out)") == pytest.approx(0.1 * gain, rel=1e-4)


@pytest.mark.integration
@ngspice
@pytest.mark.parametrize(
    "block, kind, f0",
    [
        (std.rc_lowpass("1k", "1u"), "lp", 1 / (2 * math.pi * 1e-3)),
        (std.rc_highpass("1u", "1k"), "hp", 1 / (2 * math.pi * 1e-3)),
    ],
)
def test_filter_corner(tmp_path: Path, block: Block, kind: str, f0: float) -> None:
    """Butterworth-sized sections: |H(f0)| = 1/sqrt(2) (both first and second order here)."""
    body = (
        sub(block, "flt", ["in", "out"])
        + "VI in 0 dc 0 ac 1\nX1 in out flt\nRL out 0 1e9\n"
    )
    out = run(tmp_path, body, f"ac lin 1 {f0} {f0}\nprint vm(out)")
    assert value(out, "vm(out)") == pytest.approx(1 / math.sqrt(2), rel=0.01)


@pytest.mark.integration
@ngspice
@pytest.mark.parametrize(
    "factory, vout, lo, hi",
    [
        (
            std.mirror,
            0.7,
            0.98,
            1.0,
        ),  # matched Vce: only the base-current error, 2/beta
        (std.mirror, 10.0, 1.05, 1.15),  # Early effect (VAF = 100 V) at Vce = 10 V
        (std.wilson, 10.0, 0.99, 1.01),  # high output resistance: still ~1 at 10 V
    ],
)
def test_current_mirrors(
    tmp_path: Path, factory: Callable[..., Block], vout: float, lo: float, hi: float
) -> None:
    body = sub(factory(Q2N3904), "mir", ["in", "out", "vn"]) + (
        f"VCC vcc 0 10\nIIN vcc in 1m\nVOUT out 0 {vout}\nX1 in out 0 mir\n"
    )
    out = run(tmp_path, body, "op\nprint -i(VOUT)")
    # VOUT holds the output node; the mirror sinks current out of VOUT's + terminal
    assert lo <= value(out, "-i(VOUT)") / 1e-3 <= hi


@pytest.mark.integration
@ngspice
def test_diff_pairs_amplify_the_difference(tmp_path: Path) -> None:
    for block, outs in (
        (
            std.diff_pair(Q2N3904, rc="10k", rt="10k"),
            ["o1", "vp", "o2", "inp", "inn", "vn"],
        ),
        (
            std.diff_pair_mirror(Q2N3904, Q2N3906, rt="10k"),
            ["vp", "out", "inp", "inn", "vn"],
        ),
    ):
        body = sub(block, "dp", outs)
        node = "o2" if "o2" in outs else "out"
        conn = " ".join({"vp": "vp", "vn": "vn"}.get(p, p) for p in outs)
        body += f"VP vp 0 12\nVN vn 0 -12\nVA inp 0 dc 0\nVB inn 0 dc 0\nX1 {conn} dp\n"
        out = run(tmp_path, body, f"dc VA -0.005 0.005 0.01\nprint v({node})")
        vals = [float(x) for x in re.findall(r"^\d+\s+\S+\s+(\S+)\s*$", out, re.M)]
        assert len(vals) == 2, out[-2000:]
        assert vals[1] > vals[0] + 0.1  # raising inp raises the inn-side output


def push_pull_bench(kind: str, diodes: int | None = None) -> str:
    pp = std.push_pull(
        kind,
        Q2N3904,
        Q2N3906,
        D1N4148,
        rb="2.2k",
        re="2.2",
        bias=None if diodes is None else std.diode_string(diodes, D1N4148),
    )
    return sub(pp, "pp", ["vp", "in", "out", "vn"]) + (
        "VP vp 0 12\nVN vn 0 -12\nVS sig 0 dc 0 sin(0 1 1k)\nCC sig in 1000u\n"
        "RS in vn 2.2k\nX1 vp in out vn pp\nRL out 0 8\n"
    )


@pytest.mark.integration
@ngspice
@pytest.mark.parametrize(
    "kind, right, wrong, max_thd, min_wrong_thd",
    [
        ("bjt", 2, 1, 5.0, 15.0),
        ("darlington", 4, 2, 1.0, 30.0),
        ("sziklai", 2, 1, 2.0, 10.0),
    ],
)
def test_push_pull_bias_matches_its_output_variant(
    tmp_path, kind, right, wrong, max_thd, min_wrong_thd
):
    """Open loop, 1 V peak at 1 kHz into 8 ohm, AC-coupled drive: the bias string sized for
    the variant keeps crossover distortion low; one string short of it does not."""
    analyses = "op\nprint v(out)\ntran 2u 25m 5m\nfourier 1k v(out)"
    good = run(tmp_path, push_pull_bench(kind), analyses)
    bad = run(tmp_path, push_pull_bench(kind, wrong), analyses)
    thd = lambda t: float(re.search(r"THD:\s*(\S+)", t).group(1))  # noqa: E731
    assert abs(value(good, "v(out)")) < 0.05  # output centred
    assert thd(good) < max_thd
    assert thd(bad) > min_wrong_thd


@pytest.mark.integration
@ngspice
@pytest.mark.parametrize(
    "kind, bias", [("bjt", 0.68), ("darlington", 1.3), ("sziklai", 0.68)]
)
def test_push_pull_core_follows_its_drive(
    tmp_path: Path, kind: str, bias: float
) -> None:
    """{hi} driven with the half-string bias plus 0.2 V peak, a 3 mA sink at {lo}: the
    output follows into 100 ohm without clipping."""
    core = std.push_pull_core(kind, Q2N3904, Q2N3906, D1N4148)
    body = sub(core, "stage", ["vp", "hi", "lo", "out", "vn"]) + (
        f"VP vp 0 5\nVN vn 0 -5\nVH hi 0 SIN({bias} 0.2 1000)\nIL lo vn 3m\n"
        "X1 vp hi lo out vn stage\nRL out 0 100\n"
    )
    analyses = (
        "tran 1u 20m\nmeas tran output rms v(out) from=10m to=20m\n"
        "meas tran vmax max v(out) from=10m to=20m\n"
        "meas tran vmin min v(out) from=10m to=20m"
    )
    out = run(tmp_path, body, analyses)
    assert 0.25 < value(out, "vmax") - value(out, "vmin") < 0.45
    assert value(out, "output") < 0.5


def test_vbe_multiplier_connections() -> None:
    """Fixture (2N3904 TO-92: 1 = E, 2 = B, 3 = C): R1 collector-base, R2 base-emitter,
    collector = {a}, emitter = {k}. Resistor pin numbers are ignored (symmetric parts)."""
    nets = netlist(std.vbe_multiplier(Q2N3904, "2.7k", "1k"))
    parts = {
        name: {p.split(".")[0] if p[0] == "R" else p for p in pins}
        for name, pins in nets.items()
    }
    assert parts["a"] == {"Q1.3", "R1"}
    assert parts["k"] == {"Q1.1", "R2"}
    assert sorted(map(sorted, parts.values())) == sorted(
        [["Q1.3", "R1"], ["Q1.1", "R2"], ["Q1.2", "R1", "R2"]]
    )


@pytest.mark.integration
@ngspice
def test_vbe_multiplier_scales_vbe(tmp_path: Path) -> None:
    """2 mA into {a}: V(a, k) = Vbe (1 + R1/R2) with Vbe of a small NPN at ~1.5 mA
    (0.6-0.75 V); doubling R1/R2 + 1 doubles the voltage (within base-current error)."""
    volts = []
    for r1 in ("1k", "3k"):
        bench = sub(std.vbe_multiplier(Q2N3904, r1, "1k"), "vm", ["a", "k"]) + (
            "I1 0 a 2m\nX1 a 0 vm\n"
        )
        volts.append(value(run(tmp_path, bench, "op\nprint v(a)"), "v(a)"))
    assert 1.2 < volts[0] < 1.5  # 2 Vbe
    assert 2.4 < volts[1] < 3.0  # 4 Vbe
    assert volts[1] / volts[0] == pytest.approx(2.0, rel=0.05)


# --- five-pin op-amp orientation (P0) -----------------------------------------------------------
LOWER_PLUS = """
          [VCC]
            │
{a}────────U1U1U1
           U1U1U1───{out}
{b}───────+U1U1U1
            │
          [VEE]
"""


def test_lone_plus_label_mirrors_supplies_too() -> None:
    """Documented trap: + on the lower input mirrors the whole symbol, so V- moves up."""
    nets = netlist(Block("Trap", LOWER_PLUS, U1=OPAMP()))
    assert nets["VCC"] == ["U1.4"] and nets["VEE"] == ["U1.3"]  # V- on VCC!


def test_supply_labels_reject_the_mirror() -> None:
    canvas = """
          [VCC]
            │
           {V+}
{a}────────U1U1U1
           U1U1U1───{out}
{b}───────+U1U1U1
           {V-}
            │
          [VEE]
"""
    with pytest.raises(YasdlError, match="does not fit"):
        Block("Labelled", canvas, U1=OPAMP())


def test_powered_wrapper_keeps_supplies_when_mirrored() -> None:
    host = Block(
        "Host",
        """
{a}────────UWUW
           UWUW───{out}
{b}───────+UWUW
""",
        UW=std.powered(OPAMP()),
    )
    assert host.bound["UW"].mirror == "x"
    nets = netlist(host)
    assert nets["VCC"] == ["UW.U1.3"] and nets["VEE"] == ["UW.U1.4"]  # V+ still on VCC
    assert nets["b"] == ["UW.U1.1"]  # + input where the label says


@pytest.mark.integration
@ngspice
def test_powered_inverting_stage_simulates(tmp_path: Path) -> None:
    amp = std.inverting("10k", "47k", std.powered(OP5))
    text = sub(amp, "inv", ["in", "out"])
    assert ".global VCC VEE" in text
    body = text + "VP VCC 0 15\nVN VEE 0 -15\nVI in 0 0.1\nX1 in out inv\n"
    assert value(run(tmp_path, body, "op\nprint v(out)"), "v(out)") == pytest.approx(
        -0.47, rel=1e-4
    )


@pytest.mark.integration
@ngspice
def test_package_units_in_standard_circuits(tmp_path: Path) -> None:
    chip = Package(IDEAL_DUAL, "U1")
    top = Block(
        "Chain",
        """
  [VCC]
     │
     PW
     │
  [VEE]

{in}──GA──IV──{out}
""",
        GA=std.noninverting("10k", "10k", chip.unit("A")),
        IV=std.inverting("10k", "10k", chip.unit("B")),
        PW=chip.power(),
    )
    body = (
        sub(top, "chain", ["in", "out"])
        + "VP VCC 0 15\nVN VEE 0 -15\nVI in 0 0.2\nX1 in out chain\n"
    )
    assert value(run(tmp_path, body, "op\nprint v(out)"), "v(out)") == pytest.approx(
        -0.4, rel=1e-4
    )
