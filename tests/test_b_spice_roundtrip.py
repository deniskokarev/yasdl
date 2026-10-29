"""P0: the KiCad 9 SPICE round trip covers X instances (model + instance parameters), V/I
sources with their full specification, ground and global net identity (spec 6.2).

The integration tests generate schematics and run the real kicad-cli. Mutations are applied
both to yasdl's netlist text and to the generated schematic (re-exported by kicad-cli), and
every mutation must be rejected.
"""

import re

import pytest
from yasdl import Atom, Block, C, I, NPN, OPAMP_IDEAL, POT, R, spice_netlist, SpiceModel, V
from yasdl.kicad_lib import JELLYBEAN_MODEL, KICAD_CLI
from yasdl.spice import compare_spice, parse_spice

have_kicad = KICAD_CLI.exists()
kicad = pytest.mark.skipif(not have_kicad, reason="kicad-cli missing")

# A custom subcircuit with instance parameters (one model, per-instance settings).
ATTEN_LIB = """* test attenuator: out = in * K through R
.subckt atten in out params: R=1k K=0.5
B1 mid 0 V={K}*V(in)
R1 mid out {R}
.ends atten
* a second three-terminal model with the op-amp's pin names (model mutation)
.subckt opamp_alt inp inn out
B1 out 0 V=1e3*(V(inp)-V(inn))
.ends opamp_alt
"""


def bench(tmp_path):
    lib = tmp_path / "atten.lib"
    lib.write_text(ATTEN_LIB)
    atten = Atom(
        "Device:R",
        "atten",
        spice=SpiceModel("X", ("1", "2"), "atten", "1=in 2=out", str(lib), "R=2k K=0.25"),
    )
    return Block(
        "Bench",
        """
          [VCC]
            │
  ┌──R1─────┤
  │         │
  +         RV──AT──┬──RL────┐
  V1        │       │        │
  │         │       └───U1U1 │
[GND]     [GND]  ┌─────+U1U1─┴──R3──┐
                 │      U1U1        │
  ┌──R2──┐       V2                 │
  I1     │       +                  │
  v      │       │                  │
  │      │       │                  │
[GND]  [GND]   [VCC]              [GND]
""",
        V1=V("dc 0 ac 1"),
        V2=V("sin(0 1 1k)"),
        I1=I("1m"),
        R1=R("1k"),
        R2=R("4.7k"),
        R3=R("10k"),
        RL=R("22k"),
        RV=POT("10k", rotation=0.3),
        AT=atten,
        U1=OPAMP_IDEAL(),
    )


def test_parse_reads_x_v_i_with_full_values_and_skips_subckt_bodies():
    text = """* t
.subckt inner a b
R9 a b 1k
.ends inner
X1 n1 GND inner R=1k
+ K=2
V1 n1 0 dc 0 ac 1
I1 n2 0 PULSE(0 1m 0 1n 1n 1u 2u)
R1 n1 n2 4.7k
.param BASE=1k
"""
    got = {name: (nodes, value) for name, nodes, value in parse_spice(text)}
    assert got == {
        "X1": (["n1", "0"], "inner R=1k K=2"),
        "V1": (["n1", "0"], "dc 0 ac 1"),
        "I1": (["n2", "0"], "PULSE(0 1m 0 1n 1n 1u 2u)"),
        "R1": (["n1", "n2"], "4.7k"),
    }
    assert parse_spice(text, "inner") == [("R9", ["a", "b"], "1k")]


def test_compare_spice_unit():
    a = "R1 a b 1k\nV1 a 0 dc 0 ac 1\nX1 a b atten R=1k\n"
    ids = lambda n: n  # noqa: E731
    assert compare_spice(a, a, ids, ids)[0]
    # case and whitespace are normalised; anything else in the value counts
    assert compare_spice(a, a.replace("dc 0 ac 1", "DC 0  AC 1"), ids, ids)[0]
    for mutated in (
        a.replace("ac 1", "ac 2"),  # a later token of a source specification
        a.replace("R=1k", "R=2k"),  # instance parameter
        a.replace("atten", "other"),  # model
        a.replace("X1 a b", "X1 b a"),  # connection
        a.replace("V1 a 0", "V1 0 a"),  # polarity
        "\n".join(a.splitlines()[:-1]),  # omitted instance
    ):
        ok, diff = compare_spice(a, mutated, ids, ids)
        assert not ok and diff
    # ground identity: the same grouping on another node is still wrong
    ok, diff = compare_spice(a, a.replace(" 0 ", " gnd2 "), ids, ids, ["0"])
    assert not ok and "net 0" in diff


@pytest.mark.integration
@kicad
def test_kicad_export_agrees_and_keeps_full_specs(tmp_path):
    from yasdl.kicad_export import export_kicad_spice, render

    info = render(bench(tmp_path), tmp_path, svg=False, spice=True,
                  spice_libs=(str(JELLYBEAN_MODEL),))
    assert info["roundtrip_ok"], (info["missing"], info["extra"])
    assert info["erc"] == []
    assert info["spice_ok"], info["spice_diff"]
    text = export_kicad_spice(info["schematic"])
    elements = {name: (nodes, value) for name, nodes, value in parse_spice(text)}
    values = sorted(v for _, v in elements.values())
    # the baseline exported "DC dc 0 ac 1" and "DC sin(0 1 1k)"
    assert "dc 0 ac 1" in values and "sin(0 1 1k)" in values and "1m" in values
    assert not any(v.lower().startswith("dc dc") or "dc sin" in v.lower() for v in values)
    assert "yasdl_pot R=10k POS=0.3" in values
    assert "atten R=2k K=0.25" in values
    assert "yasdl_ideal_opamp" in values


def _mutate_yasdl(block):
    base = spice_netlist(block)
    lines = base.splitlines()

    def edit(prefix, old, new):
        out = []
        for line in lines:
            if line.startswith(prefix):
                assert old in line, (old, line)
                line = line.replace(old, new, 1)
            out.append(line)
        return "\n".join(out) + "\n"

    def swap_nodes(prefix):
        out = []
        for line in lines:
            if line.startswith(prefix):
                p = line.split()
                p[1], p[2] = p[2], p[1]
                line = " ".join(p)
            out.append(line)
        return "\n".join(out) + "\n"

    def drop(prefix):
        return "\n".join(x for x in lines if not x.startswith(prefix)) + "\n"

    def rename_node(old, new):
        return re.sub(rf"(?<=\s){re.escape(old)}(?=\s|$)", new, base)

    return {
        "omitted X": drop("X_AT "),
        "omitted V": drop("V_V2 "),
        "omitted I": drop("I_I1 "),
        "X model": edit("X_U1 ", "yasdl_ideal_opamp", "yasdl_pot"),
        "X parameter": edit("X_AT ", "K=0.25", "K=0.5"),
        "pot setting": edit("X_RV ", "POS=0.3", "POS=0.7"),
        "X connection": swap_nodes("X_AT "),
        "V spec last token": edit("V_V1 ", "ac 1", "ac 2"),
        "V transient spec": edit("V_V2 ", "1k)", "2k)"),
        "V connection": swap_nodes("V_V1 "),
        "I spec": edit("I_I1 ", "1m", "2m"),
        "I connection": swap_nodes("I_I1 "),
        "ground identity": rename_node("0", "gnd_moved"),
        "global identity": rename_node("VCC", "VCC_other"),
    }


@pytest.mark.integration
@kicad
def test_mutated_yasdl_netlists_are_rejected(tmp_path):
    from yasdl.kicad_export import export_kicad_spice, spice_roundtrip, to_kicad

    block = bench(tmp_path)
    sch, refmap = to_kicad(block, tmp_path / "Bench.kicad_sch",
                           spice_libs=(str(JELLYBEAN_MODEL),))
    kicad_text = export_kicad_spice(sch)
    assert spice_roundtrip(block, sch, refmap, kicad_text=kicad_text)[0]
    for what, text in _mutate_yasdl(block).items():
        ok, diff = spice_roundtrip(block, sch, refmap, kicad_text=kicad_text, yasdl_text=text)
        assert not ok, what
        assert diff, what


def _edit_symbol(sch_text, ref, edit):
    """Apply `edit` to the (symbol ...) block whose Reference is `ref`."""
    from yasdl.sexp import dumps, find, find_all, parse

    root = parse(sch_text)
    for sym in find_all(root, "symbol"):
        props = {str(p[1]): p for p in find_all(sym, "property")}
        if "Reference" in props and props["Reference"][2] == ref:
            if edit(root, sym, props) is False:
                root.remove(sym)
            return dumps(root) + "\n"
    raise AssertionError(f"no symbol {ref}")


def _set_prop(name, old, new):
    def edit(root, sym, props):
        assert old in props[name][2], props[name][2]
        props[name][2] = props[name][2].replace(old, new)

    return edit


def _set_model(library, name):
    def edit(root, sym, props):
        props["Sim.Library"][2] = library
        props["Sim.Name"][2] = name

    return edit


def _swap_pins(a, b):
    """Swap the Sim.Pins model names of two symbol pins (a changed connection)."""
    def edit(root, sym, props):
        pairs = dict(x.split("=") for x in props["Sim.Pins"][2].split())
        pairs[a], pairs[b] = pairs[b], pairs[a]
        props["Sim.Pins"][2] = " ".join(f"{k}={v}" for k, v in pairs.items())

    return edit


@pytest.mark.integration
@kicad
def test_mutated_schematics_are_rejected_by_kicad_export(tmp_path):
    """The schematic is changed and re-exported by kicad-cli; yasdl's netlist is unchanged."""
    from yasdl.kicad_export import spice_roundtrip, to_kicad

    block = bench(tmp_path)
    sch, refmap = to_kicad(block, tmp_path / "Bench.kicad_sch", references="names",
                           spice_libs=(str(JELLYBEAN_MODEL),))
    original = sch.read_text()
    assert spice_roundtrip(block, sch, refmap)[0]
    mutations = {
        "X parameter": ("AT", _set_prop("Sim.Params", "K=0.25", "K=0.3")),
        "pot setting": ("RV", _set_prop("Sim.Params", "POS=0.3", "POS=0.31")),
        "X model": ("U1", _set_model(str(tmp_path / "atten.lib"), "opamp_alt")),
        "X connection": ("AT", _swap_pins("1", "2")),
        "V spec": ("V1", _set_prop("Sim.Params", "ac 1", "ac 1.5")),
        "V transient spec": ("V2", _set_prop("Sim.Params", "sin(0 1 1k)", "sin(0 1 1k 1m)")),
        "V connection": ("V1", _swap_pins("1", "2")),
        "I spec": ("I1", _set_prop("Sim.Params", '"1m"', '"1.1m"')),
        "I connection": ("I1", _swap_pins("1", "2")),
        "omitted instance": ("R3", lambda root, sym, props: False),
    }
    for what, (ref, edit) in mutations.items():
        mutated = tmp_path / f"m_{what.replace(' ', '_')}.kicad_sch"
        mutated.write_text(_edit_symbol(original, ref, edit))
        ok, diff = spice_roundtrip(block, mutated, refmap)
        assert not ok, what
        assert diff, what


# --- .global for supply nets in subcircuits (spec 6.2) ----------------------------------
DIVIDER = Block(
    "Divider",
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


def test_subckt_declares_unexported_global_supplies():
    text = spice_netlist(DIVIDER, subckt="div")
    assert ".global VCC" in text.splitlines()
    assert text.index(".global") < text.index(".subckt")
    assert ".global" not in spice_netlist(DIVIDER)  # flat: top-level nodes are global
    alias = Block("SupplyAlias", "{VP}──┬──R1──{out}\n      │\n    [VCC]\n", R1=R("1k"))
    assert ".global" not in spice_netlist(alias, subckt="s")  # exported through a port
    signal = Block("Sig", "{in}──R1──[Shared]", R1=R("1k"))
    assert ".global Shared" in spice_netlist(signal, subckt="sig")


@pytest.mark.integration
@pytest.mark.skipif(__import__("shutil").which("ngspice") is None, reason="ngspice missing")
@pytest.mark.parametrize("declared, expected", [(True, 6.0), (False, 0.0)])
def test_global_supply_reaches_subcircuit_in_ngspice(tmp_path, declared, expected):
    """With .global VCC the divider sees the testbench's 12 V and gives 6 V; without the card
    (the baseline export) its VCC is a floating local node and the output is 0 V."""
    import subprocess

    sub = spice_netlist(DIVIDER, subckt="div")
    if not declared:
        sub = "\n".join(x for x in sub.splitlines() if not x.startswith(".global")) + "\n"
    (tmp_path / "tb.cir").write_text(
        "* divider\n" + sub + "VS VCC 0 12\nX1 out div\n.control\nop\nprint v(out)\n.endc\n.end\n"
    )
    out = subprocess.run(["ngspice", "-b", "tb.cir"], cwd=tmp_path, capture_output=True,
                         text=True, timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr
    m = re.search(r"^v\(out\)\s*=\s*([-+\d.eE]+)", out.stdout, re.M)
    assert m, out.stdout
    assert abs(float(m.group(1)) - expected) < 1e-3


# --- MEG for mega (spec 6.2) --------------------------------------------------------------
@pytest.mark.integration
@kicad
@pytest.mark.parametrize("value, agrees", [("1MEG", True), ("1Meg", True), ("1M", False)])
def test_mega_must_be_spelled_meg(tmp_path, value, agrees):
    """KiCad reads 1M as mega and exports 1Meg; ngspice reads yasdl's 1M as milli. The round
    trip exposes the disagreement instead of rewriting the value."""
    from yasdl.kicad_export import render

    block = Block("Meg", "{a}──R1──┬──{b}\n         │\n         C1\n         │\n       [GND]\n",
                  R1=R(value), C1=C("1n"))
    info = render(block, tmp_path, svg=False, spice=True)
    assert info["spice_ok"] is agrees, info["spice_diff"]
    if not agrees:
        assert "1meg" in info["spice_diff"] and "1m" in info["spice_diff"]


# --- ground and global net identity in a real export --------------------------------------
@pytest.mark.integration
@kicad
def test_named_net_identity_is_checked_against_kicad(tmp_path):
    from yasdl.kicad_export import export_kicad_spice, spice_roundtrip, to_kicad

    block = Block(
        "Rails",
        """
 [VCC]   [VEE]
   │       │
   R1      R2
   │       │
   └───┬───┘
       R3
       │
     [GND]
""",
        R1=R("1k"), R2=R("2k"), R3=R("3k"),
    )
    sch, refmap = to_kicad(block, tmp_path / "Rails.kicad_sch")
    kicad_text = export_kicad_spice(sch)
    assert spice_roundtrip(block, sch, refmap, kicad_text=kicad_text)[0]
    ours = spice_netlist(block)
    # swapping the two supply names keeps every terminal grouping; only names differ
    swapped = ours.replace("VCC", "TMP").replace("VEE", "VCC").replace("TMP", "VEE")
    ok, diff = spice_roundtrip(block, sch, refmap, kicad_text=kicad_text, yasdl_text=swapped)
    assert not ok and "net VCC" in diff
    moved = re.sub(r"(?<=\s)0(?=\s|$)", "ground_lost", ours)
    ok, diff = spice_roundtrip(block, sch, refmap, kicad_text=kicad_text, yasdl_text=moved)
    assert not ok and "net 0" in diff


def test_npn_default_mapping_unchanged():
    q = Block("Q", " │\n─Q1\n Q1\n │\n", Q1=NPN("2N3904"))
    assert re.search(r"^Q_Q1 \S+ \S+ \S+ 2N3904$", spice_netlist(q), re.M)
