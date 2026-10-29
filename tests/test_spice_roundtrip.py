"""P0: KiCad 9 SPICE round trip covering X instances, V/I sources, instance parameters, values,
global supplies in subcircuits and ground/global net identity (DECISIONS 1-4).

The integration tests generate schematics, run the real `kicad-cli sch export netlist
--format spice`, and compare it with yasdl's own netlist. Mutation tests edit the generated
schematic (or compare against a different design) and must be rejected.
"""

import re
import shutil
import subprocess

import pytest
from yasdl import (
    Atom,
    Block,
    C,
    D,
    I,
    L,
    NPN,
    OPAMP_IDEAL,
    R,
    spice_netlist,
    SpiceModel,
    V,
    YasdlError,
)
from yasdl.kicad_lib import JELLYBEAN_MODEL, KICAD_CLI
from yasdl.spice import (
    compare_spice,
    kicad_number,
    ngspice_number,
    parse_spice,
    spice_partition,
)

have_kicad = KICAD_CLI.exists()
have_ngspice = shutil.which("ngspice") is not None
kicad = pytest.mark.skipif(not have_kicad, reason="kicad-cli missing")
ngspice = pytest.mark.skipif(not have_ngspice, reason="ngspice missing")

POT_LIB = """* test potentiometer: t-w is (1-X)*R, w-b is X*R
.subckt tpot t w b params: R=10k X=0.5
R1 t w {R*(1-X)+1m}
R2 w b {R*X+1m}
.ends tpot
.subckt tpot2 t w b params: R=10k X=0.5
R1 t w {R*X+1m}
R2 w b {R*(1-X)+1m}
.ends tpot2
"""


def pot_atom(lib, params="R=100k X=0.25", model="tpot"):
    return Atom(
        "Device:R_Potentiometer",
        "B100k",
        spice=SpiceModel("X", ("1", "2", "3"), model, "1=t 2=w 3=b", str(lib), params),
    )


def bench(lib, **over):
    """Sources (DC/AC, SIN, PULSE), an X with parameters, an ideal op-amp X, R/C/L/D/Q."""
    parts = dict(
        V1=V("dc 0 ac 1 sin(0 0.5 1k)"),
        R1=R("1Meg"),
        VR=pot_atom(lib),
        C1=C("2.2u"),
        I1=I("pulse(0 1m 0 1u 1u 1m 2m)"),
        L1=L("10m"),
        D1=D("1N4148"),
        Q1=NPN("2N3904"),
        U1=OPAMP_IDEAL(),
        V2=V("12"),
    )
    parts.update(over)
    return Block(
        "SpiceBench",
        """
     ┌──R1──{1}VR{3}──┬──────┐    [VCC]     [VCC]
     +       {2}      │      │      │         │
     V1       │       I1     │      L1        +
     │        C1      v      │      │         V2
     │        │       │      └─{b}Q1Q1        │
   [GND]    [GND]   [GND]         Q1Q1      [GND]
                                  Q1Q1
                                   v
                                   │
          ┌──────+U1U1             v
          │       U1U1──┐          D1
        [GND] ┌───U1U1  │          │
              │         │        [GND]
              └─────────┘
""",
        **parts,
    )


# --- unit level ------------------------------------------------------------------------
def test_parse_spice_reads_x_v_i_and_skips_definitions():
    text = """* deck
.subckt inner a b params: R=1k
R9 a b {R}
.ends inner
X1 n1 GND inner R=2k
+ X=0.3
V1 n1 0 dc 0 ac 1 sin(0 1 1k)
I1 n2 0 pulse(0 1m 0 1u 1u 1m 2m)
R1 n1 n2 4.7k
.end
"""
    got = {name: (nodes, value) for name, nodes, value in parse_spice(text)}
    assert got == {
        "X1": (["n1", "0"], "inner R=2k X=0.3"),
        "V1": (["n1", "0"], "dc 0 ac 1 sin(0 1 1k)"),
        "I1": (["n2", "0"], "pulse(0 1m 0 1u 1u 1m 2m)"),
        "R1": (["n1", "n2"], "4.7k"),
    }


@pytest.mark.parametrize(
    "text, ng, ki",
    [
        ("1M", 1e-3, 1e6),
        ("1Meg", 1e6, 1e6),
        ("1MEG", 1e6, 1e6),
        ("1m", 1e-3, 1e-3),
        ("4k7", 4e3, 4.7e3),
        ("4.7k", 4.7e3, 4.7e3),
        ("2R2", 2.0, 2.2),
        ("100nF", 1e-7, 1e-7),
        ("2.2u", 2.2e-6, 2.2e-6),
        ("47", 47.0, 47.0),
        ("{RVAL}", None, None),
    ],
)
def test_ngspice_and_kicad_readings(text, ng, ki):
    for got, want in ((ngspice_number(text), ng), (kicad_number(text), ki)):
        assert got == pytest.approx(want) if want is not None else got is None


@pytest.mark.parametrize("value", ["1M", "4k7", "2R2", "4M7"])
def test_values_read_differently_by_kicad_and_ngspice_are_rejected(value):
    block = Block("Val", "{a}──R1──{b}", R1=R(value))
    with pytest.raises(YasdlError, match="MEG for mega"):
        spice_netlist(block)


@pytest.mark.parametrize("value", ["1Meg", "1m", "4.7k", "100nF", "2.2", "{RV}"])
def test_unambiguous_values_pass_through_unchanged(value):
    text = spice_netlist(Block("Val", "{a}──C1──{b}", C1=C(value)))
    assert f"C_C1 a b {value}" in text


def test_sources_are_not_value_checked():
    assert "V_V1 W0 E0 dc 1M" in spice_netlist(Block("S", "──V1──", V1=V("dc 1M")))


def test_instance_params_on_the_element_line(tmp_path):
    block = Block("Trim", "{a}──VR──{b}\n    {2}\n     │\n   [GND]", VR=pot_atom("x.lib"))
    assert re.search(r"^X_VR a 0 b tpot R=100k X=0.25$", spice_netlist(block), re.M)


def test_comparison_keeps_ground_and_global_identity():
    a = parse_spice("R1 VCC n1 1k\nR2 n1 0 1k\n")
    b = parse_spice("R1 0 n1 1k\nR2 n1 VCC 1k\n")
    same = lambda n: n  # noqa: E731
    pa, pb = spice_partition(a, same, {"VCC"}), spice_partition(b, same, {"VCC"})
    assert compare_spice(pa, pb), "swapped VCC/GND must differ"
    # ordinary generated names do not matter
    c = parse_spice("R1 VCC x7 1k\nR2 x7 0 1k\n")
    assert not compare_spice(pa, spice_partition(c, same, {"VCC"}))


# --- .global supplies (DECISION 4) -------------------------------------------------------
RAILS = Block(
    "Rails",
    """
     [VCC]
       │
       R1
       │
       ├──{out}
       │
       R2
       │
     [GND]
""",
    R1=R("10k"),
    R2=R("10k"),
)


def test_subckt_declares_global_supplies_not_ground():
    text = spice_netlist(RAILS, subckt="rails")
    assert re.search(r"^\.global VCC$", text, re.M)
    assert text.index(".global") < text.index(".subckt")
    assert ".global" not in spice_netlist(RAILS)  # flat: nothing to declare
    alias = Block("SupplyAlias", "{VP}──┬──R1──{out}\n      │\n    [VCC]\n", R1=R("1k"))
    assert ".global" not in spice_netlist(alias, subckt="s")  # supply is a pin


def test_subckt_declares_unported_globals_of_nested_blocks():
    top = Block("Top", "{o}──RS", RS=RAILS)
    text = spice_netlist(top, subckt="top")
    assert re.search(r"^\.global VCC$", text, re.M)


@pytest.mark.integration
@ngspice
def test_global_supply_reaches_subckt_in_ngspice(tmp_path):
    """12 V on VCC outside the subcircuit: 6 V with .global, 0 V without it."""

    def run(deck):
        cir = tmp_path / "rails.cir"
        cir.write_text(
            "* rails\n" + deck + "VS VCC 0 12\nX1 out rails\n"
            ".control\nop\nprint v(out)\n.endc\n.end\n"
        )
        out = subprocess.run(["ngspice", "-b", str(cir)], capture_output=True, text=True)
        m = re.search(r"v\(out\) = (\S+)", out.stdout)
        assert m, out.stdout + out.stderr
        return float(m.group(1))

    deck = spice_netlist(RAILS, subckt="rails")
    assert run(deck) == pytest.approx(6.0)
    assert run(deck.replace(".global VCC\n", "")) == pytest.approx(0.0, abs=1e-9)


# --- KiCad 9 round trips -------------------------------------------------------------------
def _render(block, tmp_path, lib):
    from yasdl.kicad_export import render

    return render(block, tmp_path, svg=False, spice=True, spice_libs=(str(lib), str(JELLYBEAN_MODEL)))


@pytest.fixture
def pot_lib(tmp_path):
    lib = tmp_path / "tpot.lib"
    lib.write_text(POT_LIB)
    return lib


@pytest.mark.integration
@kicad
def test_roundtrip_agrees_for_x_v_i_and_params(tmp_path, pot_lib):
    from yasdl.kicad_export import export_kicad_spice

    info = _render(bench(pot_lib), tmp_path, pot_lib)
    assert info["roundtrip_ok"], (info["missing"], info["extra"])
    assert info["erc"] == []
    assert info["spice_ok"], info["spice_diff"]
    exported = export_kicad_spice(info["schematic"])
    assert "DC dc" not in exported
    assert "dc 0 ac 1 sin(0 0.5 1k)" in exported
    assert "pulse(0 1m 0 1u 1u 1m 2m)" in exported
    assert re.search(r"^XRV\d+ .* tpot R=100k X=0.25$", exported, re.M)


def _mutate(sch, ref, old, new):
    """Replace `old` by `new` inside the (symbol ...) whose Reference is `ref`."""
    text = sch.read_text()
    m = re.search(r'\(property "Reference" "%s"' % re.escape(ref), text)
    assert m, ref
    start = text.rfind("\t(symbol", 0, m.start())
    start = text.rfind("(symbol\n", 0, m.start()) if start < 0 else start
    end = text.find("(instances", m.end())
    body = text[start:end]
    assert old in body, (ref, old)
    sch.write_text(text[:start] + body.replace(old, new, 1) + text[end:])


def _remove_symbol(sch, ref):
    text = sch.read_text()
    m = re.search(r'\(property "Reference" "%s"' % re.escape(ref), text)
    lines = text.split("\n")
    line_no = text[: m.start()].count("\n")
    start = max(i for i in range(line_no) if lines[i].strip() == "(symbol")
    depth, end = 0, start
    for i in range(start, len(lines)):
        depth += lines[i].count("(") - lines[i].count(")")
        if depth == 0:
            end = i
            break
    sch.write_text("\n".join(lines[:start] + lines[end + 1 :]))


def _ref_of(refmap, path):
    return next(r for r, p in refmap.items() if p == path)


@pytest.mark.integration
@kicad
@pytest.mark.parametrize(
    "path, old, new, what",
    [
        ("VR", '"Sim.Name" "tpot"', '"Sim.Name" "tpot2"', "X model"),
        ("VR", "R=100k X=0.25", "R=100k X=0.75", "X parameter"),
        ("VR", "1=t 2=w 3=b", "1=w 2=t 3=b", "X connection"),
        ("V1", 'sin(0 0.5 1k)\\" lib', 'sin(0 0.5 2k)\\" lib', "V spec, late token"),
        ("V1", "1=1 2=2", "1=2 2=1", "V connection"),
        ("I1", 'model=\\"pulse(0 1m', 'model=\\"pulse(0 2m', "I spec"),
        ("I1", "1=1 2=2", "1=2 2=1", "I connection"),
        ("U1", "1=inp 2=inn", "1=inn 2=inp", "op-amp X connection"),
        ("R1", '"Value" "1Meg"', '"Value" "1k"', "R value"),
    ],
)
def test_roundtrip_rejects_mutations(tmp_path, pot_lib, path, old, new, what):
    from yasdl.kicad_export import spice_roundtrip, to_kicad

    tmp_lib = tmp_path / "x"
    tmp_lib.mkdir()
    block = bench(pot_lib)
    sch, refmap = to_kicad(
        block, tmp_path / "b.kicad_sch", spice_libs=(str(pot_lib), str(JELLYBEAN_MODEL))
    )
    ok, diff = spice_roundtrip(block, sch, refmap)
    assert ok, diff
    _mutate(sch, _ref_of(refmap, path), old, new)
    ok, diff = spice_roundtrip(block, sch, refmap)
    assert not ok, what
    assert diff


@pytest.mark.integration
@kicad
@pytest.mark.parametrize("path", ["VR", "V1", "I1", "U1"])
def test_roundtrip_rejects_omitted_instances(tmp_path, pot_lib, path):
    from yasdl.kicad_export import spice_roundtrip, to_kicad

    block = bench(pot_lib)
    sch, refmap = to_kicad(
        block, tmp_path / "b.kicad_sch", spice_libs=(str(pot_lib), str(JELLYBEAN_MODEL))
    )
    _remove_symbol(sch, _ref_of(refmap, path))
    ok, diff = spice_roundtrip(block, sch, refmap)
    assert not ok and "missing elements" in diff


@pytest.mark.integration
@kicad
def test_roundtrip_rejects_changed_design_values(tmp_path, pot_lib):
    """The schematic of one design against the netlist of a changed design."""
    from yasdl.kicad_export import spice_roundtrip, to_kicad

    sch, refmap = to_kicad(
        bench(pot_lib), tmp_path / "b.kicad_sch", spice_libs=(str(pot_lib),)
    )
    for over in (
        dict(VR=pot_atom(pot_lib, "R=100k X=0.3")),
        dict(VR=pot_atom(pot_lib, "X=0.25 R=100k")),  # reordered text: unequal (documented)
        dict(V1=V("dc 0 ac 2 sin(0 0.5 1k)")),
        dict(I1=I("1m")),
        dict(V2=V("15")),
        dict(Q1=NPN("2N3906")),
    ):
        ok, diff = spice_roundtrip(bench(pot_lib, **over), sch, refmap)
        assert not ok, over


SWAP_A = """
  [VCC]
    │
    R1
    │
    ├──R3──[GND]
    │
    R2
    │
  [GND]
"""
SWAP_B = """
  [GND]
    │
    R1
    │
    ├──R3──[VCC]
    │
    R2
    │
  [VCC]
"""


@pytest.mark.integration
@kicad
def test_roundtrip_keeps_ground_and_global_identity(tmp_path):
    """Same terminal grouping, but GND and VCC swapped: must be rejected."""
    from yasdl.kicad_export import spice_roundtrip, to_kicad

    parts = dict(R1=R("1k"), R2=R("2k"), R3=R("3k"))
    a, b = Block("SwapA", SWAP_A, **parts), Block("SwapB", SWAP_B, **parts)
    sch, refmap = to_kicad(a, tmp_path / "a.kicad_sch")
    assert spice_roundtrip(a, sch, refmap)[0]
    ok, diff = spice_roundtrip(b, sch, refmap)
    assert not ok and "connectivity" in diff
    # a global moved to a local net is also caught
    g = Block("SwapG", SWAP_A.replace("[VCC]", "[Vref]"), **parts)
    sch, refmap = to_kicad(g, tmp_path / "g.kicad_sch")
    assert spice_roundtrip(g, sch, refmap)[0]
    renamed = Block("SwapL", SWAP_A.replace("[VCC]", "[bias]"), **parts)
    assert not spice_roundtrip(renamed, sch, refmap)[0]
    # flat SPICE ignores case: a local [vref] is the same node as Vref
    same = Block("SwapS", SWAP_A.replace("[VCC]", "[vref]"), **parts)
    assert spice_roundtrip(same, sch, refmap)[0]


# --- non-simulated parts (P2.3) --------------------------------------------------------------
JACKS = """
   ┌──────J1
   │    ┌─J1
   R1   │
   │    │
 [GND] [GND]
"""


def test_sim_false_parts_are_left_out_of_spice():
    j = Atom("Connector_Generic:Conn_01x02", "IN", sim=False)
    block = Block("Jack", JACKS, J1=j, R1=R("1k"))
    text = spice_netlist(block)
    assert "J1" not in text and "R_R1" in text
    # a non-simulated part needs no SPICE mapping at all
    assert spice_netlist(block, subckt="jack")


@pytest.mark.integration
@kicad
def test_sim_false_parts_render_and_roundtrip(tmp_path):
    from yasdl.kicad_export import export_kicad_spice, render
    from yasdl.sexp import find, find_all, parse

    j = Atom("Connector_Generic:Conn_01x02", "IN", sim=False)
    block = Block("Jack", JACKS, J1=j, R1=R("1k"))
    info = render(block, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"] and info["erc"] == [] and info["spice_ok"], info
    assert not re.search(r"^\w*J1 ", export_kicad_spice(info["schematic"]), re.M)
    root = parse(info["schematic"].read_text())
    conn = [s for s in find_all(root, "symbol") if find(s, "lib_id") and
            find(s, "lib_id")[1] == "Connector_Generic:Conn_01x02"]
    assert str(find(conn[0], "exclude_from_sim")[1]) == "yes"
    assert str(find(conn[0], "in_bom")[1]) == "yes"
