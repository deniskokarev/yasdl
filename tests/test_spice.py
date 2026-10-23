import re

import pytest
from yasdl import Block, GND, NPN, OPAMP, R, spice_netlist, YasdlError
from yasdl.kicad_lib import KICAD_CLI

have_kicad = KICAD_CLI.exists()


def test_subckt_supply_keeps_formal_port_alias():
    block = Block(
        "SupplyAlias",
        """
        {VP}──┬──R1──{out}
              │
            [VCC]
    """,
        R1=R("1k"),
    )
    text = spice_netlist(block, subckt="supply", port_order=["VP", "out"])
    assert ".subckt supply VP out" in text
    assert "R_R1 VP out 1k" in text
    assert "R_R1 VCC out 1k" in spice_netlist(block)


@pytest.mark.integration
@pytest.mark.skipif(not have_kicad, reason="kicad-cli missing")
@pytest.mark.parametrize(
    "canvas",
    [
        "{input}──┬──{output}\\n         │\\n         R1\\n         │\\n       [GND]\\n",
        "{VP}──┬──R1──{out}\\n      │\\n    [VCC]\\n",
    ],
)
def test_port_aliases_on_one_net_render_cleanly(tmp_path, canvas):
    from yasdl.kicad_export import render
    from yasdl.sexp import find_all, parse

    block = Block("AliasedPorts", canvas.replace("\\n", "\n"), R1=R("1k"))
    info = render(block, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"] and info["spice_ok"]
    assert info["erc"] == []
    root = parse(info["schematic"].read_text())
    visible = {
        str(item[1]) for kind in ("text", "label") for item in find_all(root, kind)
    }
    assert {port.name for port in block.ports} <= visible


@pytest.mark.integration
@pytest.mark.skipif(not have_kicad, reason="kicad-cli missing")
def test_crossing_between_power_label_and_component(tmp_path):
    from yasdl.kicad_export import render

    block = Block(
        "CrossingSupply",
        """
              [VCC]
        {a}─────│─────{b}
                R1
                │
              [GND]
    """,
        R1=R("1k"),
    )
    info = render(block, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"], (info["missing"], info["extra"])
    assert info["erc"] == []
    assert info["spice_ok"]


@pytest.mark.integration
@pytest.mark.skipif(not have_kicad, reason="kicad-cli missing")
def test_crossing_between_two_components(tmp_path):
    from yasdl.kicad_export import render

    block = Block(
        "CrossingComponents",
        """
            {top}
              │
        {a}─R1─R2─{b}
              │
            {bottom}
    """,
        R1=R("1k"),
        R2=R("2k"),
    )
    info = render(block, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"], (info["missing"], info["extra"])
    assert info["erc"] == []
    assert info["spice_ok"]


def test_spice_errors():
    amp = Block(
        "A",
        """
           [VEE]
             │
        ─────U1U1──
           ┌+U1U1
           │ │
          G1 [VCC]
    """,
        U1=OPAMP(),
        G1=GND(),
    )
    with pytest.raises(YasdlError, match="no SPICE mapping"):
        spice_netlist(amp)
    q = Block(
        "Q",
        """
         │
        ─Q1
         Q1
         │
    """,
        Q1=NPN(),
    )
    with pytest.raises(YasdlError, match="model name"):
        spice_netlist(q)
    assert "R_R1 W0 E0 1k" in spice_netlist(Block("S", "──R1──", R1=R("1k")))
