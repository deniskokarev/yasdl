import cmath
import math
import re
import shutil
import subprocess

import pytest

from yasdl import GND, I, L, OPAMP_IDEAL, Atom, C, R, V, Block, YasdlError, spice_netlist
from yasdl.analysis import Circuit, elements, parse_value

from test_ideal_opamp import INTEGRATOR, TESTBENCH

have_ngspice = shutil.which("ngspice") is not None
try:
    import sympy  # noqa: F401
    have_sympy = True
except ImportError:
    have_sympy = False

DIVIDER = Block("Divider", """
  ┌──R1──┬──{out}
  +      │
  V1     R2
  │      │
[GND]  [GND]
""", V1=V("1"), R1=R("1k"), R2=R("3k"))

# Lossy integrator feeding an inverting amplifier: two op-amp stages, sub-blocks reused.
LOSSY = Block("Lossy", """
            ┌───CF───┐
            │        │
            ├───RF───┤
            │        │
{in}──RI────┴──U1U1  │
               U1U1──┴──{out}
             ┌+U1U1
             │
           [GND]
""", U1=OPAMP_IDEAL())
INV = Block("Inv", """
            ┌───RF───┐
            │        │
{in}──RI────┴──U1U1  │
               U1U1──┴──{out}
             ┌+U1U1
             │
           [GND]
""", U1=OPAMP_IDEAL())
CHAIN = Block("Chain", """
  ┌──A──B──{vo}
  +
  V1
  │
[GND]
""", V1=V("ac 1"), A=LOSSY.bind(RI=R("10k"), RF=R("100k"), CF=C("10n")),
     B=INV.bind(RI=R("10k"), RF=R("22k")))


def test_parse_value():
    assert parse_value("4.7k") == pytest.approx(4700)
    assert parse_value("100n") == pytest.approx(1e-7)
    assert parse_value("2meg") == pytest.approx(2e6)
    assert parse_value("10uF") == pytest.approx(1e-5)
    assert parse_value("1M") == pytest.approx(1e-3)  # SPICE: m and M are milli
    assert parse_value("") is None


def test_elements_flatten_with_unique_names():
    els = {e.name: e for e in elements(TESTBENCH)}
    assert set(els) == {"V1", "RI", "CF", "U1"}
    assert els["U1"].kind == "OPAMP" and els["U1"].nodes[0] == "0"
    assert els["CF"].nodes[1] == "out"
    names = {e.name for e in elements(CHAIN)}  # RI, RF and U1 repeat: paths instead
    assert {"A_RI", "B_RI", "A_U1", "B_U1", "V1"} <= names


def test_divider():
    assert Circuit(DIVIDER).transfer("V1", "out") == pytest.approx(0.75)


def test_integrator_numeric_matches_closed_form():
    w = 2 * math.pi * 1e3
    h = Circuit(TESTBENCH).transfer("V1", "out", s=1j * w)
    assert h == pytest.approx(-1 / (1j * w * 1e3 * 1e-6))


def test_chain_numeric_matches_closed_form():
    s = 2j * math.pi * 500
    h = Circuit(CHAIN).transfer("V1", "vo", s=s)
    zf = 1 / (1 / 100e3 + s * 10e-9)
    assert h == pytest.approx((-zf / 10e3) * (-22e3 / 10e3))


def test_inductor_and_current_source():
    rl = Block("RL", """
  ┌──L1──┬──{out}
  │      │
  I1     R1
  v      │
  │      │
[GND]  [GND]
""", I1=I("1m"), L1=L("1m"), R1=R("1k"))
    # 1 A out of I1's bottom pin into ground: I1's top pin pulls 1 A out of the L1-R1 path.
    v = Circuit(rl).solve(1j, "I1")
    assert v["out"] == pytest.approx(-1000)


def test_singular_circuit_is_an_error():
    loop = Block("Loop", """
  ┌──────┬──{out}
  +      +
  V1     V2
  │      │
[GND]  [GND]
""", V1=V("1"), V2=V("1"))
    with pytest.raises(YasdlError, match="no unique solution"):
        Circuit(loop).transfer("V1", "out")


def test_physical_parts_are_left_out_and_ambiguous_values_rejected():
    canvas = """
[in]──R1──┬──[out]
          │
          C1
          │
        [GND]

J1J1{1}──[in]
J1J1{2}──[GND]
"""
    jack = Atom("Connector_Generic:Conn_01x02", sim=False)
    rc = Block("RC", canvas, R1=R("1k"), C1=C("1u"), J1=jack)
    assert {e.name for e in elements(rc)} == {"R1", "C1"}
    with pytest.raises(YasdlError, match="MEG for mega"):
        elements(Block("RC", canvas, R1=R("1M"), C1=C("1u"), J1=jack))


@pytest.mark.skipif(not have_sympy, reason="sympy not installed")
def test_symbolic():
    import sympy as sp
    h = Circuit(TESTBENCH).transfer_symbolic("V1", "out")
    s, RI, CF = sp.symbols("s RI CF", positive=True)
    assert sp.simplify(h.subs({sp.Symbol("RI", positive=True): RI}) + 1 / (sp.Symbol("CF", positive=True) * RI * sp.Symbol("s"))) == 0
    assert Circuit(TESTBENCH).transfer_symbolic("V1", "out", numeric=True) == -1000 / sp.Symbol("s")
    hc = Circuit(CHAIN).transfer_symbolic("V1", "vo", numeric=True)
    assert complex(hc.subs(sp.Symbol("s"), 2j * math.pi * 500)) == \
        pytest.approx(Circuit(CHAIN).transfer("V1", "vo", s=2j * math.pi * 500))


@pytest.mark.skipif(not have_ngspice, reason="ngspice not installed")
def test_mna_agrees_with_ngspice(tmp_path):
    deck = tmp_path / "chain.cir"
    f = 500.0
    deck.write_text(spice_netlist(CHAIN) + f".control\nac lin 1 {f} {f}\nprint vr(vo) vi(vo)\n"
                    ".endc\n.end\n")
    out = subprocess.run(["ngspice", "-b", str(deck)], capture_output=True, text=True).stdout
    got = complex(float(re.search(r"vr\(vo\) = (\S+)", out).group(1)),
                  float(re.search(r"vi\(vo\) = (\S+)", out).group(1)))
    want = Circuit(CHAIN).transfer("V1", "vo", s=2j * math.pi * f)
    assert abs(got - want) < 1e-6 * abs(want)


def _ladder(sections: int) -> Block:
    """V1 driving an RC ladder: R in series along the top, C legs to ground."""
    from yasdl import Sketch
    sk = Sketch()
    binds = {"V1": V("ac 1")}
    sk.text(0, 2, "┌").vline(2, 1, 1).text(2, 2, "+").text(3, 2, "V1").vline(2, 4, 4)
    sk.text(5, 0, "[GND]")
    col = 3
    for i in range(1, sections + 1):
        sk.hline(0, col, col + 1).text(0, col + 2, f"R{i}").hline(0, col + 4, col + 5)
        sk.text(0, col + 6, "┬").vline(col + 6, 1, 1).text(2, col + 6, f"C{i}")
        sk.vline(col + 6, 3, 4).text(5, col + 4, "[GND]")
        binds[f"R{i}"], binds[f"C{i}"] = R("1k"), C("1u")
        col += 7
    sk.hline(0, col, col + 1).text(0, col + 2, "{out}")
    return Block("Ladder", sk.render(), **binds)


@pytest.mark.skipif(not have_sympy, reason="sympy not installed")
def test_symbolic_ladder_is_fast():
    """A 6-section RC ladder: Matrix.det on expressions took minutes, the polynomial-ring
    det with conductance stamps about 2 s."""
    import time
    import sympy as sp
    ladder = _ladder(6)
    t0 = time.time()
    h = Circuit(ladder).transfer_symbolic("V1", "out")
    assert time.time() - t0 < 20
    num = Circuit(ladder).transfer("V1", "out", s=3j)
    vals = {sp.Symbol(k, positive=True): v for k, v in Circuit(ladder).values.items()}
    assert complex(h.xreplace(vals).subs(sp.Symbol("s"), 3j)) == pytest.approx(num, rel=1e-9)
