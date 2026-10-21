"""Net naming (spec 2.8): reserved global names, unique user names, collision-free generated names."""

import re

import pytest

from yasdl import NPN, R, Block, YasdlError, netlist, partition, spice_netlist

DIVIDER = """
    {in}──R1──┬──{out}
              │
              R2
              │
            <GND>
"""


@pytest.mark.parametrize("alias", ["GND", "gnd", "0", "VCC", "+5V"])
def test_reserved_port_aliases_rejected(alias):
    with pytest.raises(YasdlError, match="reserved"):
        Block("B", DIVIDER.replace("{out}", "{" + alias + "}"), R1=R(), R2=R())
    with pytest.raises(YasdlError, match="reserved"):
        Block("B", DIVIDER, port_attrs={"out": {"aliases": [alias]}}, R1=R(), R2=R())


def test_reserved_label_spelling():
    with pytest.raises(YasdlError, match="reserved"):
        Block("B", DIVIDER.replace("<GND>", "<gnd>"), R1=R(), R2=R())
    with pytest.raises(YasdlError, match="reserved"):
        Block("B", DIVIDER.replace("<GND>", " <0> "), R1=R(), R2=R())


def test_inline_reserved_label_is_global():
    blk = Block("B", "{in}──R1──<GND>──R2──{out}", R1=R(), R2=R())  # wires on both sides
    nets = netlist(blk)
    assert {"R1.2", "R2.1"} <= set(nets["GND"]) or {"R1.1", "R2.2"} <= set(nets["GND"])
    assert " 0 " in spice_netlist(blk)


def test_label_name_clashes():
    with pytest.raises(YasdlError, match="default port"):
        Block("B", "{in}──R1──<N1>──R2──{out}", R1=R(), R2=R())
    with pytest.raises(YasdlError, match="clashes"):
        Block("B", "{in}──R1──<OUT>──R2──{out}", R1=R(), R2=R())


def test_generated_names_never_collide():
    # unnamed top ports N0/N1 and two unnamed internal nets: previously both named "N1"
    blk = Block("B", "│      │\nR1     R2\n│      │\n└──R3──┘", R1=R("1k"), R2=R("2k"), R3=R("3k"))
    nets = netlist(blk)
    assert len(nets) == 4 and len(set(nets)) == 4
    assert partition(nets) == {frozenset({"R1.1"}), frozenset({"R2.1"}),
                               frozenset({"R1.2", "R3.1"}), frozenset({"R2.2", "R3.2"})}
    lines = [l.split() for l in spice_netlist(blk).splitlines() if l.startswith("R_")]
    nodes = {l[0]: l[1:3] for l in lines}
    assert nodes["R_R1"][1] == nodes["R_R3"][0]  # R1-R3 joined...
    assert nodes["R_R2"][0] not in nodes["R_R3"]  # ...and not shorted to port N1


def test_port_alias_vs_nested_global():
    inner = Block("Inner", "──R1──<sig>", R1=R())  # global net "sig"
    with pytest.raises(YasdlError, match="two different nets"):
        netlist(Block("Top", "{sig}──A", A=inner))  # top port alias "sig" on another net


def test_ground_port_not_a_subckt_pin():
    blk = Block("B", """
        {in}──R1──┬──
                  │
                <GND>
    """, R1=R())  # the E port is wired to ground
    assert "0" in spice_netlist(blk).split()
    with pytest.raises(YasdlError, match="global ground"):
        spice_netlist(blk, subckt="x")


def test_one_net_two_subckt_pins_rejected():
    blk = Block("Thru", "{input}──┬──{output}\n         │\n         R1\n         │\n       <GND>",
                R1=R("1k"))
    assert re.search(r"^R_R1 (input|output) 0 1k$", spice_netlist(blk), re.M)  # flat is fine
    with pytest.raises(YasdlError, match="same net"):
        spice_netlist(blk, subckt="thru")  # ngspice silently miswires duplicate formal nodes


def test_reserved_pin_names_not_reexported():
    # a pin named like a global net is never re-exported as a port alias
    blk = Block("F", """
                      │
        {input}────<b>Q1Q1
                      Q1Q1
                      Q1Q1
                      │
    """, Q1=NPN())
    assert all(p.name not in ("GND", "VCC") for p in blk.ports)
