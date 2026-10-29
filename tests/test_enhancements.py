"""Independent physical pin fixtures and live KiCad 9 behavioral regressions."""

import re
import shutil
import subprocess

import pytest
from yasdl import (
    Atom,
    AtomNPN,
    AtomOpamp3,
    AtomOpamp5,
    Block,
    NC,
    Package,
    Pot,
    Q2N3904,
    Q2N3906,
    R,
    V,
    I,
    SpiceModel,
    YasdlError,
    netlist,
    spice_netlist,
)
from yasdl import transistor as standard_transistor
from yasdl.kicad_lib import KICAD_CLI, load, JELLYBEAN_MODEL
from yasdl.kicad_export import (
    compare_spice,
    export_kicad_spice,
    render,
    roundtrip,
    spice_roundtrip,
    to_kicad,
)
from yasdl.kicad_sch import export_netlist
from yasdl.sexp import Sym, dumps, find, find_all, parse
from yasdl.spice import parse_spice

live = pytest.mark.skipif(
    not KICAD_CLI.exists(), reason="KiCad 9 CLI missing: set YASDL_KICAD"
)


def transistor(atom, name="Transistor"):
    return Block(
        name,
        """
           {collector}
             │
            {C}
    {base}─{B}Q1Q1
              Q1Q1
             {E}
              │
            {emitter}
    """,
        Q1=atom,
    )


@live
@pytest.mark.integration
def test_verified_standard_physical_pinouts():
    # Trusted exact KiCad device variants, independent of generic factories.
    # Datasheets: onsemi 2N3903-D / 2N3906-D, TO-92 E=1 B=2 C=3.
    from yasdl.kicad_lib import library_path

    symbols = find_all(parse(library_path("Transistor_BJT").read_text()), "symbol")

    def exact_pinout(name):
        exact = next(s for s in symbols if s[1] == name)
        while find(exact, "extends") is not None:
            parent = str(find(exact, "extends")[1])
            exact = next(s for s in symbols if s[1] == parent)
        return {
            str(find(pin, "name")[1]): str(find(pin, "number")[1])
            for unit in find_all(exact, "symbol")
            for pin in find_all(unit, "pin")
        }

    for factory, name in [(Q2N3904, "2N3904"), (Q2N3906, "2N3906")]:
        fixture = exact_pinout(name)
        assert fixture == {"E": "1", "B": "2", "C": "3"}
        assert {p.name: p.number for p in factory().symbol.pins} == fixture
        assert {p.name: p.number for p in standard_transistor(name).symbol.pins} == fixture
    # A differently numbered exact variant, the BD139 regression map (TO-126).
    assert exact_pinout("BD139") == {"E": "1", "B": "3", "C": "2"}


def test_generic_definitions_do_not_mutate_shared_roots():
    base = load("Device:Q_NPN").sexp
    old = dumps(base)
    a = Q2N3904()
    b = AtomNPN(
        "BD139", pins={"E": 1, "B": 3, "C": 2}, library=JELLYBEAN_MODEL, model="2N3904"
    )
    assert a.lib_id != b.lib_id
    assert {p.name: p.number for p in a.symbol.pins} == {"E": "1", "B": "2", "C": "3"}
    assert {p.name: p.number for p in b.symbol.pins} == {"E": "1", "B": "3", "C": "2"}
    edited = a.symbol.sexp
    edited[1] = "broken"
    assert a.symbol.sexp[1] != "broken"
    assert dumps(load("Device:Q_NPN").sexp) == old
    with pytest.raises(TypeError):
        a.arrows["2"] = "<"


@pytest.mark.parametrize(
    "pins",
    [
        {"E": 1, "B": 2},
        {"E": 1, "B": 2, "C": 2},
        {"E": 1, "B": 2, "C": 0},
        {"E": 1, "B": 2, "C": "bogus"},
        {"E": 1, "B": 2, "C": 3, "extra": 4},
    ],
)
def test_generic_maps_reject_incomplete_or_duplicate_pins(pins):
    with pytest.raises(YasdlError):
        AtomNPN("bad", pins=pins)


@live
@pytest.mark.integration
def test_generic_parts_with_different_pinouts_export_together(tmp_path):
    a = transistor(Q2N3904())
    b = transistor(
        AtomNPN(
            "BD139",
            pins={"E": 1, "B": 3, "C": 2},
            library=JELLYBEAN_MODEL,
            model="2N3904",
            footprint="Package_TO_SOT_THT:TO-126-3_Vertical",
            datasheet="https://www.st.com/resource/en/datasheet/bd135.pdf",
        )
    )
    # Separate terminal names with compact disconnected sub-block placements.
    top = Block(
        "TwoDevices",
        """
       │       │
    ───QA      QB───
       │       │
    """,
        QA=a,
        QB=b,
    )
    info = render(top, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"] and info["spice_ok"] and info["erc"] == [], info
    nets = export_netlist(info["schematic"])
    assert {p for ns in nets.values() for p in ns if p[0] == "Q1"} == {
        ("Q1", "1"),
        ("Q1", "2"),
        ("Q1", "3"),
    }
    assert {p for ns in nets.values() for p in ns if p[0] == "Q2"} == {
        ("Q2", "1"),
        ("Q2", "2"),
        ("Q2", "3"),
    }
    assert netlist(a) == {"collector": ["Q1.3"], "base": ["Q1.2"], "emitter": ["Q1.1"]}
    assert netlist(b) == {"collector": ["Q1.2"], "base": ["Q1.3"], "emitter": ["Q1.1"]}
    root = parse(info["schematic"].read_text())
    props = [
        {str(p[1]): str(p[2]) for p in find_all(s, "property")}
        for s in find_all(root, "symbol")
    ]
    bd = next(p for p in props if p["Value"] == "BD139")
    assert bd["Footprint"] == "Package_TO_SOT_THT:TO-126-3_Vertical"
    assert bd["Datasheet"] == "https://www.st.com/resource/en/datasheet/bd135.pdf"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"position": -0.1},
        {"position": 1.1},
        {"position": float("nan")},
        {"position": float("inf")},
        {"taper": "audio"},
        {"resistance": "0"},
        {"resistance": "1M"},
    ],
)
def test_pot_rejects_invalid_settings(kwargs):
    with pytest.raises(YasdlError):
        Pot(**kwargs)


def bench():
    return Block(
        "SourcesAndPot",
        """
      ┌───────┬───────┐
      │       │       │
      V1      RP      I1
      │       RP───R1─┤
      │       │       │
      └───────┼───────┘
              │
            [GND]
    """,
        V1=V("dc 0 ac 1 sin(0 2 41)"),
        I1=I("dc 1m ac 2m pulse(0 1m 0 1u 1u 1m 2m)"),
        RP=Pot("100k", position=0.25),
        R1=R("10k"),
    )


@live
@pytest.mark.integration
def test_p0_live_x_v_i_roundtrip_and_export_mutations(tmp_path):
    b = bench()
    info = render(b, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"] and info["spice_ok"] and info["erc"] == [], info
    path, refs = to_kicad(b, tmp_path / "bench.kicad_sch")
    text = export_kicad_spice(path)
    assert len(parse_spice(text)) == 4
    assert "dc 0 ac 1 sin(0 2 41)" in text.lower()
    assert "pulse(0 1m 0 1u 1u 1m 2m)" in text.lower()
    # Mutate an actual KiCad export, preserving all other instance/node text.
    instances = parse_spice(text)
    for name, nodes, spec in instances:
        kind = name[0].upper()
        if kind not in "XVI":
            continue
        line = next(l for l in text.splitlines() if l.split() and l.split()[0] == name)
        variants = [
            text.replace(line, ""),
            text.replace(
                line,
                re.sub(re.escape(nodes[0]), "changed_node", line, count=1, flags=re.I),
            ),
        ]
        if kind == "X":
            variants += [
                text.replace(line, line.replace("yasdl_pot", "wrong_model")),
                text.replace(line, line.replace("P=0.25", "P=0.75")),
            ]
        else:
            variants.append(text.replace(line, line + " ac 9"))
        for mutated in variants:
            ok, why = compare_spice(b, mutated, refs)
            assert not ok and why
    # Mutate the generated schematic itself; invoke KiCad again for every negative case.
    root = parse(path.read_text())
    symbols = find_all(root, "symbol")
    for symbol in symbols:
        props = {str(p[1]): p for p in find_all(symbol, "property")}
        if props.get("Value", [None, None, None])[2] not in (
            "100k",
            "dc 0 ac 1 sin(0 2 41)",
            "dc 1m ac 2m pulse(0 1m 0 1u 1u 1m 2m)",
        ):
            continue
        original = props["Sim.Params"][2]
        props["Sim.Params"][2] = (
            str(original).replace("P=0.25", "P=0.8")
            if props["Value"][2] == "100k"
            else str(original).replace("ac 1", "ac 7").replace("ac 2m", "ac 7m")
        )
        changed = path
        changed.write_text(dumps(root) + "\n")
        assert not spice_roundtrip(b, changed, refs)[0]
        props["Sim.Params"][2] = original
        mapping = props["Sim.Pins"][2]
        if props["Value"][2] == "100k":
            props["Sim.Pins"][2] = "1=w 2=cw 3=ccw"
        else:
            props["Sim.Pins"][2] = "1=2 2=1"
        changed.write_text(dumps(root) + "\n")
        assert not spice_roundtrip(b, changed, refs)[0]
        props["Sim.Pins"][2] = mapping
        old = find(symbol, "exclude_from_sim")[1]
        find(symbol, "exclude_from_sim")[1] = Sym("yes")
        changed.write_text(dumps(root) + "\n")
        assert not spice_roundtrip(b, changed, refs)[0]
        find(symbol, "exclude_from_sim")[1] = old


@live
@pytest.mark.integration
@pytest.mark.parametrize(
    "spec",
    [
        "dc 1",
        "dc 0 ac 1",
        "sin(0 1 41)",
        "pulse(0 1 0 1n 1n 1m 2m)",
        "pwl(0 0 1m 1 2m 0)",
    ],
)
def test_p0_live_supported_transient_sources(tmp_path, spec):
    b = Block(
        "Voltage", "┌─R1─┐\n│    │\nV1   │\n│    │\n└────┘", V1=V(spec), R1=R("1k")
    )
    info = render(b, tmp_path, svg=False, spice=True)
    assert info["spice_ok"] and info["roundtrip_ok"] and info["erc"] == [], info


def test_parser_rejects_missing_duplicate_and_malformed_instances():
    assert parse_spice(
        ".subckt x a b\nR1 a b 1\n.ends\nV1 n 0 dc 0 ac 1\nX1 n 0 x R=1k P=0.5"
    ) == [("V1", ["n", "0"], "dc 0 ac 1"), ("X1", ["n", "0"], "x R=1k P=0.5")]
    for text in ["V1 n", "X1 n", "R1 a b 1\nR1 b c 2", ".ends", "+ stray"]:
        with pytest.raises(YasdlError):
            parse_spice(text)


def test_p0_global_scope_subcircuit():
    b = Block(
        "Divider",
        "[VCC]\n  │\n  R1\n  │\n  ├─{out}\n  │\n  R2\n  │\n[GND]",
        R1=R("10k"),
        R2=R("10k"),
    )
    assert ".global VCC\n.subckt divider out" in spice_netlist(b, subckt="divider")
    assert ".global" not in spice_netlist(b)


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice missing")
def test_p0_global_supply_measured_in_ngspice(tmp_path):
    b = Block(
        "Divider",
        "[VCC]\n  │\n  R1\n  │\n  ├─{out}\n  │\n  R2\n  │\n[GND]",
        R1=R("10k"),
        R2=R("10k"),
    )
    for declaration, expected in [(True, 6.0), (False, 0.0)]:
        net = spice_netlist(b, subckt="divider")
        if not declaration:
            net = net.replace(".global VCC\n", "")
        p = tmp_path / "tb.cir"
        p.write_text(
            "* scope\n"
            + net
            + "V1 VCC 0 12\nX1 out divider\n.control\nop\nprint v(out)\n.endc\n.end\n"
        )
        r = subprocess.run(["ngspice", "-b", str(p)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "Error" not in r.stdout + r.stderr
        measurement = re.search(r"v\(out\)\s*=\s*([\d.eE+-]+)", r.stdout)
        assert measurement and float(measurement[1]) == pytest.approx(expected)


@live
@pytest.mark.integration
def test_p0_special_net_identities_cannot_be_renamed(tmp_path):
    b = Block("Ground", "[VCC]─R1─R2─[GND]", R1=R("1k"), R2=R("1k"))
    path, refs = to_kicad(b, tmp_path / "ground.kicad_sch")
    text = export_kicad_spice(path)
    assert compare_spice(b, text, refs)[0]
    for before, after in [("VCC", "WRONG_RAIL"), (" GND ", " other_ground ")]:
        assert before in text
        assert not compare_spice(b, text.replace(before, after), refs)[0]


@live
@pytest.mark.integration
@pytest.mark.parametrize(
    "canvas", ["NC1─R1─{out}", "NC1─J1─NC2\nNC1─J1─NC2\nNC1─J1─NC2"]
)
def test_nc_groups_live_export_and_erc(tmp_path, canvas):
    if "J1" in canvas:
        b = Block(
            "NCGroup",
            canvas,
            NC1=NC(),
            NC2=NC(),
            J1=Atom("Connector_Generic:Conn_02x03_Odd_Even", sim=False),
        )
        count = 6
    else:
        b = Block("NCGroup", canvas, NC1=NC(), R1=R("1k"))
        count = 1
    before = netlist(b)
    info = render(b, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"] and info["spice_ok"] and info["erc"] == [], info
    root = parse(info["schematic"].read_text())
    assert len(find_all(root, "no_connect")) == count
    assert netlist(b) == before
    assert all("NC" not in pin for pins in before.values() for pin in pins)
    assert "NC" not in "\n".join(n for n, _, _ in parse_spice(spice_netlist(b)))


def test_nc_hierarchical_fanout_is_rejected_without_pruning():
    single = Block("Single", "{a}─R1─{b}", R1=R("1k"))
    good = Block("Good", "NC1─X1─{out}", NC1=NC(), X1=single)
    assert len(netlist(good)) == 2
    multiple = Block(
        "Parallel", "{a}─┬─R1─┬─{b}\n    │    │\n    └─R2─┘", R1=R("1k"), R2=R("2k")
    )
    bad = Block("Bad", "NC1─X1─{out}", NC1=NC(), X1=multiple)
    with pytest.raises(YasdlError, match="one isolated device pin"):
        netlist(bad)
    with pytest.raises(YasdlError):
        netlist(Block("Detached", "NC1", NC1=NC()))


def dual_package(tmp_path, *, sim=True):
    lib = tmp_path / "dual.lib"
    lib.write_text(
        ".subckt dual ap am ao bp bm bo vp vm\nEa ao 0 ap am 10000\nEb bo 0 bp bm 10000\n.ends dual\n"
    )
    chip = Package(
        spice=SpiceModel(
            "X",
            ("3", "2", "1", "5", "6", "7", "8", "4"),
            "dual",
            "3=ap 2=am 1=ao 5=bp 6=bm 7=bo 8=vp 4=vm",
            str(lib),
        ),
        sim=sim,
        footprint="Package_DIP:DIP-8_W7.62mm",
        datasheet="https://www.ti.com/lit/ds/symlink/lm358.pdf",
    )
    t = Block("Unit", "{p}──+UAUA\n      UAUA──{o}\n{n}───UAUA")
    power = Block("Power", "[VCC]\n  │\n  PC\n  │\n[VEE]", PC=chip.unit("C"))
    b = Block(
        "Dual",
        """
    {pa}──A1A1
          A1A1──{oa}
    {na}──A1A1

    {pb}──B1B1
          B1B1──{ob}
    {nb}──B1B1

          PW
    """,
        A1=t.bind(UA=chip.unit("A")),
        B1=t.bind(UA=chip.unit("B")),
        PW=power,
    )
    return b, chip, t, power


@live
@pytest.mark.integration
def test_shared_package_units_live_physical_and_spice_identity(tmp_path):
    b, chip, t, power = dual_package(tmp_path)
    info = render(b, tmp_path, spice=True, svg=False)
    assert info["roundtrip_ok"] and info["spice_ok"] and info["erc"] == [], info
    root = parse(info["schematic"].read_text())
    devices = [
        s
        for s in find_all(root, "symbol")
        if str(find(s, "lib_id")[1]).startswith("yasdl_parts:")
    ]
    assert len(devices) == 3
    assert {str(find(s, "unit")[1]) for s in devices} == {"1", "2", "3"}
    assert {
        str(next(p[2] for p in find_all(s, "property") if p[1] == "Reference"))
        for s in devices
    } == {"U1"}
    physical = export_netlist(info["schematic"])
    expected = {
        "/pa": ("U1", "3"),
        "/na": ("U1", "2"),
        "/oa": ("U1", "1"),
        "/pb": ("U1", "5"),
        "/nb": ("U1", "6"),
        "/ob": ("U1", "7"),
        "VCC": ("U1", "8"),
        "VEE": ("U1", "4"),
    }
    for net, pin in expected.items():
        assert pin in physical[net]
    assert len(parse_spice(export_kicad_spice(info["schematic"]))) == 1
    assert {p.number for p in chip.unit("A").symbol.pins} == {"1", "2", "3"}
    assert {p.number for p in chip.unit("B").symbol.pins} == {"5", "6", "7"}
    assert {p.number for p in chip.unit("C").symbol.pins} == {"8", "4"}
    # One package is a single component in KiCad's native BOM-capable electrical netlist.
    out = tmp_path / "bom.net"
    subprocess.run(
        [
            str(KICAD_CLI),
            "sch",
            "export",
            "netlist",
            "--format",
            "kicadsexpr",
            "-o",
            str(out),
            str(info["schematic"]),
        ],
        check=True,
        capture_output=True,
    )
    comps = find_all(find(parse(out.read_text()), "components"), "comp")
    assert len([c for c in comps if str(find(c, "ref")[1]) == "U1"]) == 1


def test_package_missing_power_duplicate_units_and_invalid_maps(tmp_path):
    b, chip, t, power = dual_package(tmp_path)
    assert netlist(b)
    duplicate = b.bind(B1=t.bind(UA=chip.unit("A")))
    with pytest.raises(YasdlError, match="used twice"):
        netlist(duplicate)
    missing = Block(
        "Missing", "{p}──+UAUA\n      UAUA──{o}\n{n}───UAUA", UA=chip.unit("A")
    )
    with pytest.raises(YasdlError, match="missing units"):
        netlist(missing)
    with pytest.raises(YasdlError, match="unknown unit"):
        chip.unit("D")
    with pytest.raises(YasdlError, match="duplicate physical"):
        Package(
            units={
                "A": {"inp": 3, "inn": 2, "out": 1},
                "B": {"inp": 3, "inn": 6, "out": 7},
            },
            power={"V+": 8, "V-": 4},
        )
    with pytest.raises(YasdlError, match="whole-device"):
        Package(spice=SpiceModel("X", ("1", "2"), "wrong"))


@live
@pytest.mark.integration
def test_non_simulated_connector_is_physical_and_excluded_consistently(tmp_path):
    b = Block(
        "Connector",
        "{left}──{1}J1\n{right}─{2}J1",
        J1=Atom("Connector_Generic:Conn_01x02", sim=False),
    )
    info = render(b, tmp_path, spice=True, svg=False)
    assert info["spice_ok"] and info["roundtrip_ok"] and info["erc"] == [], info
    assert netlist(b) == {"left": ["J1.1"], "right": ["J1.2"]}
    assert parse_spice(spice_netlist(b)) == []
    assert parse_spice(export_kicad_spice(info["schematic"])) == []
    sym = next(
        s
        for s in find_all(parse(info["schematic"].read_text()), "symbol")
        if str(find(s, "lib_id")[1]) == "Connector_Generic:Conn_01x02"
    )
    assert str(find(sym, "exclude_from_sim")[1]) == "yes"
    assert str(find(sym, "in_bom")[1]) == "yes"
    assert str(find(sym, "on_board")[1]) == "yes"


@live
@pytest.mark.integration
def test_export_name_variants_preserve_identity(tmp_path):
    template = Block("Same", "{in}─R1─{out}")
    a = template.bind(R1=R("1k"))
    b = template.bind(R1=R("2k"))
    before = (a.to_dict(), netlist(a))
    for block, stem in [(a, None), (a, "VariantA"), (b, "VariantB")]:
        info = render(block, tmp_path, export_name=stem, spice=True)
        expected = stem or "Same"
        assert info["schematic"].name == expected + ".kicad_sch"
        assert info["svg"].name == expected + ".svg"
        assert info["schematic"].with_suffix(".kicad_pro").exists()
        assert info["spice_ok"] and info["roundtrip_ok"] and info["erc"] == [], info
    assert (a.to_dict(), netlist(a)) == before and a.name == b.name == "Same"
    for stem in ["", "../bad", "nested/file", "a\\b", ".."]:
        with pytest.raises(ValueError):
            render(a, tmp_path, export_name=stem)


def test_diagnostic_excerpt_and_binding_context():
    with pytest.raises(YasdlError) as error:
        Block("Bad", "\n    R1\n     R1\n")
    text = str(error.value)
    assert (
        "Bad" in text
        and "row" in text
        and "columns" in text
        and "^" in text
        and "indentation offset" in text
    )
    with pytest.raises(YasdlError) as error:
        Block("Bound", "{a}─{B}Q1─{b}", Q1=Q2N3904())
    assert (
        "drawn" in str(error.value)
        and "candidate pins" in str(error.value)
        and "pin labels" in str(error.value)
    )


def test_dependency_failures_are_actionable(tmp_path, monkeypatch):
    from yasdl import kicad_lib

    missing = tmp_path / "absent"
    monkeypatch.setattr(kicad_lib, "KICAD_CLI", missing)
    with pytest.raises(FileNotFoundError, match="KiCad 9.*YASDL_KICAD"):
        kicad_lib.require_cli()
    with pytest.raises(FileNotFoundError, match="YASDL_KICAD"):
        load("Missing_Library_For_Test:missing")
    with pytest.raises(KeyError, match="YASDL_KICAD"):
        load("Device:Missing_Symbol_For_Test")
    bad = AtomNPN("q", pins={"E": 1, "B": 2, "C": 3}, library=missing)
    with pytest.raises(YasdlError, match="SPICE model resource.*restore"):
        spice_netlist(transistor(bad))


@live
@pytest.mark.integration
def test_hierarchical_nc_and_vertical_groups_live(tmp_path):
    from yasdl import Sketch

    single = Block("Single", "{a}─R1─{b}", R1=R("1k"))
    b = Block("NestedNC", "NC1─X1─{out}", NC1=NC(), X1=single)
    info = render(b, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"] and info["spice_ok"] and info["erc"] == [], info
    # Same inferred 3+3 endpoint groups on the vertical axis of a rotated connector.
    s = (
        Sketch()
        .box(0, 0, "NC1NC1NC1")
        .box(2, 0, "J1J1J1J1J1", rows=2)
        .box(5, 0, "NC2NC2NC2")
    )
    for col in (1, 4, 7):
        s.vline(col, 1, 1).vline(col, 4, 4)
    vertical = Block(
        "VerticalNC",
        s.render(),
        NC1=NC(),
        NC2=NC(),
        J1=Atom("Connector_Generic:Conn_02x03_Odd_Even", sim=False),
    )
    info = render(vertical, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"] and info["spice_ok"] and info["erc"] == [], info
    assert len(find_all(parse(info["schematic"].read_text()), "no_connect")) == 6


@live
@pytest.mark.integration
def test_schematic_models_remain_usable_after_project_move(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    b = bench()
    path, refs = to_kicad(b, original / "bench.kicad_sch")
    destination = tmp_path / "moved project"
    shutil.copytree(original, destination)
    assert spice_roundtrip(b, destination / path.name, refs)[0]
    root = parse((destination / path.name).read_text())
    libraries = [
        p[2]
        for s in find_all(root, "symbol")
        for p in find_all(s, "property")
        if p[1] == "Sim.Library"
    ]
    assert all(str(lib).startswith("spice_models/") for lib in libraries)


@live
@pytest.mark.integration
def test_package_export_negative_unit_and_physical_pin_changes(tmp_path):
    b, chip, t, power = dual_package(tmp_path)
    path, refs = to_kicad(b, tmp_path / "dual.kicad_sch")
    root = parse(path.read_text())
    units = [
        s
        for s in find_all(root, "symbol")
        if str(find(s, "lib_id")[1]).startswith("yasdl_parts:")
    ]
    # Removing the shared power view must fail both physical and SPICE comparison.
    power_unit = next(s for s in units if str(find(s, "unit")[1]) == "3")
    root.remove(power_unit)
    path.write_text(dumps(root) + "\n")
    assert not roundtrip(b, path, refs)[0]
    assert not spice_roundtrip(b, path, refs)[0]


@live
@pytest.mark.integration
def test_p0_spice_rejects_added_instances_and_changed_models(tmp_path):
    b = bench()
    path, refs = to_kicad(b, tmp_path / "bench.kicad_sch")
    text = export_kicad_spice(path)
    assert not compare_spice(b, text + "VEXTRA a 0 dc 1\n", refs)[0]
    root = parse(path.read_text())
    pot = next(
        s
        for s in find_all(root, "symbol")
        if any(p[1] == "Sim.Name" for p in find_all(s, "property"))
    )
    name = next(p for p in find_all(pot, "property") if p[1] == "Sim.Name")
    name[2] = "MISSING_MODEL"
    path.write_text(dumps(root) + "\n")
    assert not spice_roundtrip(b, path, refs)[0]


@live
@pytest.mark.integration
def test_p0_global_signal_name_is_preserved(tmp_path):
    b = Block("Shared", "[Shared]─R1─[GND]", R1=R("1k"))
    info = render(b, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"] and info["spice_ok"] and info["erc"] == [], info
    path, refs = to_kicad(b, tmp_path / "shared.kicad_sch")
    text = export_kicad_spice(path)
    assert not compare_spice(b, text.replace("/Shared", "/Different"), refs)[0]
    assert ".global Shared" in spice_netlist(b, subckt="shared")


def test_opamp_role_maps_and_model_order_are_independent():
    m = SpiceModel("X", ("7", "4", "6", "3", "2"), "model")
    a = AtomOpamp5(
        "741", pins={"inp": 3, "inn": 2, "out": 6, "V+": 7, "V-": 4}, spice=m
    )
    assert {p.name: p.number for p in a.symbol.pins} == {
        "+": "3",
        "-": "2",
        "~": "6",
        "V+": "7",
        "V-": "4",
    }
    assert a.spice.pins == ("7", "4", "6", "3", "2")
    a3 = AtomOpamp3("three", pins={"inp": 5, "inn": 4, "out": 3})
    assert {p.name: p.number for p in a3.symbol.pins} == {"+": "5", "-": "4", "~": "3"}
    for kwargs in [
        dict(pins={"inp": 3, "inn": 2, "out": 6, "V+": 7, "V-": 7}),
        dict(pins={"inp": 3, "inn": 2, "out": 6}),
        dict(
            pins={"inp": 3, "inn": 2, "out": 6, "V+": 7, "V-": 4},
            spice=SpiceModel("X", ("1", "2", "3"), "bad"),
        ),
    ]:
        with pytest.raises(YasdlError):
            AtomOpamp5("bad", **kwargs)


@live
@pytest.mark.integration
def test_portable_included_model_resources(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    child = models / "child.lib"
    child.write_text(".model childres R(R=1)\n")
    parent = models / "parent.lib"
    parent.write_text('.include "child.lib"\n.subckt trim a b\nR1 a b 1k\n.ends trim\n')
    atom = Atom(
        "Device:R",
        "trim",
        spice=SpiceModel("X", ("1", "2"), "trim", "1=a 2=b", str(parent)),
    )
    b = Block("Includes", "{a}─R1─{b}", R1=atom)
    out = tmp_path / "project"
    out.mkdir()
    path, refs = to_kicad(b, out / "includes.kicad_sch")
    moved = tmp_path / "moved"
    shutil.copytree(out, moved)
    shutil.rmtree(models)
    # Re-export with KiCad alone after the source model tree has been removed.
    assert len(parse_spice(export_kicad_spice(moved / path.name))) == 1
    assert len(list((moved / "spice_models").glob("*.lib"))) == 2


def test_wrong_kicad_version_is_actionable(tmp_path, monkeypatch):
    from yasdl import kicad_lib

    cli = tmp_path / "kicad-cli"
    cli.write_text('#!/bin/sh\nprintf "8.0.9\\n"\n')
    cli.chmod(0o755)
    monkeypatch.setattr(kicad_lib, "KICAD_CLI", cli)
    with pytest.raises(RuntimeError, match="KiCad 9.*8.0.9.*YASDL_KICAD"):
        kicad_lib.require_cli()


@pytest.mark.parametrize(
    "canvas",
    [
        """
           [VCC]
             │
            {V+}
    {a}───{-}U1U1
             U1U1──{out}
    {b}─────+U1U1
            {V-}
             │
           [VEE]
    """,
        # Only the lower input labelled (+), the other left to the orientation solver.
        """
                [VCC]
                  │
                 {V+}
        {in}─────U1U1
        {minus}─+U1U1──{out}
                 {V-}
                  │
                [VEE]
        """,
    ],
    ids=["both_inputs_labelled", "plus_below_only"],
)
def test_p0_direct_opamp_supply_assertions_reject_input_mirror(canvas):
    from yasdl import OPAMP

    with pytest.raises(YasdlError, match="does not fit.*pin labels"):
        Block("PolarityAssertion", canvas, U1=OPAMP())


@live
@pytest.mark.integration
@pytest.mark.parametrize("rail,voltage", [("+12V", 12), ("-12V", -12)])
def test_p0_registered_power_names_retain_spice_global_identity(
    tmp_path, rail, voltage
):
    b = Block(
        "RegisteredSupply",
        f"[{rail}]\n  │\n  R1\n  │\n  ├─{{out}}\n  │\n  R2\n  │\n[GND]",
        R1=R("10k"),
        R2=R("10k"),
    )
    text = spice_netlist(b, subckt="divider")
    assert f".global {rail}" in text
    info = render(b, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"] and info["spice_ok"] and info["erc"] == [], info
    if shutil.which("ngspice") is not None:
        deck = tmp_path / "registered.cir"
        deck.write_text(
            "* registered rail\n"
            + text
            + f"VP {rail} 0 {voltage}\nX1 out divider\n.control\nop\nprint v(out)\n.endc\n.end\n"
        )
        r = subprocess.run(["ngspice", "-b", str(deck)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        m = re.search(r"^v\(out\)\s*=\s*([\d.eE+-]+)", r.stdout, re.M)
        assert m and float(m[1]) == pytest.approx(voltage / 2)


def test_json_preserves_differently_bound_same_name_and_nested_definitions():
    from yasdl.circuits import Darlington, ParallelDevices, BallastedDevice

    upper = Darlington()
    lower = Darlington(pnp=True)
    b = Block(
        "Variants",
        """
         │      │
    ─────UP     DN─────
         │      │
    """,
        UP=upper,
        DN=lower,
    )
    data = b.to_dict()
    keys = [data["components"][name]["binding"]["block"] for name in ("UP", "DN")]
    assert keys[0] != keys[1] and upper.name == lower.name == "Darlington"
    assert data["blocks"][keys[0]]["components"]["QD"]["binding"]["value"] == "2N3904"
    assert data["blocks"][keys[1]]["components"]["QD"]["binding"]["value"] == "2N3906"
    pair = ParallelDevices(BallastedDevice())
    nested = ParallelDevices(pair).to_dict()
    assert (
        nested["components"]["K1"]["binding"]["block"]
        == nested["components"]["K2"]["binding"]["block"]
    )
    key = nested["components"]["K1"]["binding"]["block"]
    assert nested["blocks"][key]["components"]["K1"]["binding"]["block"] != key
