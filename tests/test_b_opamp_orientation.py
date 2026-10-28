"""P0: the five-pin op-amp's canonical orientation, supply pins under mirroring, and the two
recommended patterns: a powered three-port wrapper and explicit {V+}/{V-} labels (spec 3.2).

Expected pin numbers come from Simulation_SPICE:OPAMP: 1 = +, 2 = -, 3 = V+, 4 = V-, 5 = out.
"""

import re

import pytest
from yasdl import Block, netlist, OPAMP, R, spice_netlist, YasdlError
from yasdl.kicad_lib import KICAD_CLI, load


def side_pins(block, comp):
    """{side: [pin numbers in drawing order]} of a bound atom, from Block.bound.pin_map."""
    out = {}
    for att, pin in block.bound[comp].pin_map:
        out.setdefault(att.side, []).append((att.pos, pin))
    return {s: [p for _, p in sorted(v)] for s, v in out.items()}


def test_library_symbol_is_canonical():
    pins = {p.number: (p.name, p.side) for p in load("Simulation_SPICE:OPAMP").pins}
    assert pins == {
        "1": ("+", "W"), "2": ("-", "W"), "3": ("V+", "N"), "4": ("V-", "S"), "5": ("~", "E")
    }
    # + above - on the left
    by_y = sorted((p for p in load("Simulation_SPICE:OPAMP").pins if p.side == "W"),
                  key=lambda p: -p.y)
    assert [p.name for p in by_y] == ["+", "-"]


TRAP = Block(
    "Trap",
    """
            [VCC]
              │
{in}──R1──┬───U1U1U1
          │   U1U1U1──┬──{out}
       ┌──│──+U1U1U1  │
       │  │    │      │
     [GND]│  [GND]    │
          │           │
          └────RF─────┘
""",
    R1=R("10k"),
    RF=R("100k"),
    U1=OPAMP(),
)


def test_mirror_moves_v_minus_to_the_top():
    b = TRAP.bound["U1"]
    assert (b.rot, b.mirror) == (0, "x")
    assert side_pins(TRAP, "U1") == {"N": ["4"], "S": ["3"], "W": ["2", "1"], "E": ["5"]}
    nets = netlist(TRAP)
    assert nets["VCC"] == ["U1.4"]  # V- on the positive rail: electrically wrong
    assert nets["GND"] == sorted(["U1.1", "U1.3"])


def test_supply_labels_reject_the_mirror():
    labelled = """
            [VCC]
              │
             {V+}
{in}──R1──┬───U1U1U1
          │   U1U1U1──┬──{out}
       ┌──│──+U1U1U1  │
       │  │   {V-}    │
       │  │    │      │
     [GND]│  [GND]    │
          │           │
          └────RF─────┘
"""
    with pytest.raises(YasdlError) as err:
        Block("Labelled", labelled, R1=R("10k"), RF=R("100k"), U1=OPAMP())
    msg = str(err.value)
    assert "does not fit" in msg and "label mismatch" in msg and "'V+'" in msg


def test_minus_above_plus_with_v_plus_on_top_is_impossible():
    """- above + needs the mirror, which puts V- on top: with {V+} above the labels
    contradict each other, and the binding report shows both candidates' mismatches."""
    with pytest.raises(YasdlError) as err:
        Block(
            "Inverting",
            """
              [VCC]
                │
               {V+}
{in}──R1──┬──{-}U1U1U1
          │     U1U1U1──┬──{out}
       ┌──│──{+}U1U1U1  │
       │  │     {V-}    │
       │  │      │      │
     [GND]│    [VEE]    │
          │             │
          └─────RF──────┘
""",
            R1=R("10k"),
            RF=R("100k"),
            U1=OPAMP(),
        )
    msg = str(err.value)
    assert "rot 0 mirror None: N: 3(V+); E: 5; S: 4(V-); W: 1(+), 2(-) -> label mismatch" in msg
    assert "rot 0 mirror x: N: 4(V-); E: 5; S: 3(V+); W: 2(-), 1(+) -> label mismatch" in msg
    assert "canvas row 3, col 16 = source line 5, column 17" in msg


def test_canonical_orientation_with_supply_labels():
    good = Block(
        "NonInverting",
        """
              [VCC]
                │
               {V+}
{in}─────────{+}U1U1U1
                U1U1U1──┬──{out}
       ┌─────{-}U1U1U1  │
       │        {V-}    │
       │         │      │
       ├──┐   [VEE]     │
       │  RG            │
       │  │             │
       │[GND]           │
       │                │
       └───────RF───────┘
""",
        RG=R("10k"),
        RF=R("100k"),
        U1=OPAMP(),
    )
    assert (good.bound["U1"].rot, good.bound["U1"].mirror) == (0, None)
    nets = netlist(good)
    assert nets["VCC"] == ["U1.3"] and nets["VEE"] == ["U1.4"]
    assert nets["in"] == ["U1.1"]


# The powered three-port wrapper: the supplies are wired inside, so any orientation of the
# wrapper in a parent keeps V+ on VCC and V- on VEE.
POWERED = Block(
    "PoweredOpamp",
    """
        [VCC]
          │
{+, inp}─+U1U1U1
          U1U1U1───{out}
{inn}─────U1U1U1
          │
        [VEE]
""",
    U1=OPAMP(),
)


def test_wrapper_exposes_three_signal_ports():
    assert len(POWERED.ports) == 3
    assert POWERED.port("+").side == POWERED.port("inn").side == "W"
    assert POWERED.port("+") == POWERED.port("inp")
    assert POWERED.port("out").side == "E"
    assert netlist(POWERED)["VCC"] == ["U1.3"] and netlist(POWERED)["VEE"] == ["U1.4"]


INVERTING_WITH_WRAPPER = Block(
    "InvWrapped",
    """
{in}──R1──┬──{inn}AMP
          │       AMP──┬──{out}
       ┌──│──────+AMP  │
       │  │            │
     [GND]│            │
          │            │
          └──────RF────┘
""",
    R1=R("10k"),
    RF=R("100k"),
    AMP=POWERED,
)


def test_wrapper_mirrored_in_parent_keeps_supplies():
    assert INVERTING_WITH_WRAPPER.bound["AMP"].mirror == "x"  # - on top: mirrored wrapper
    nets = netlist(INVERTING_WITH_WRAPPER)
    assert nets["VCC"] == ["AMP.U1.3"] and nets["VEE"] == ["AMP.U1.4"]
    assert nets["GND"] == ["AMP.U1.1"]


def test_wrapper_subckt_declares_global_supplies():
    from yasdl import Atom, SpiceModel

    model = SpiceModel("X", ("1", "2", "3", "4", "5"), "myopamp")
    amp = POWERED.bind(U1=Atom("Simulation_SPICE:OPAMP", "myopamp", spice=model)) \
        if "U1" in POWERED.unbound else Block(
            "PoweredOpamp", POWERED.text, U1=Atom("Simulation_SPICE:OPAMP", "myopamp", spice=model)
        )
    block = INVERTING_WITH_WRAPPER.bind(AMP=amp)
    text = spice_netlist(block, subckt="inv", port_order=["in", "out"])
    assert ".global VCC VEE" in text
    assert re.search(r"^X_AMP_U1 0 \S+ VCC VEE out myopamp$", text, re.M)


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(), reason="kicad-cli missing")
def test_wrapper_composition_renders_cleanly(tmp_path):
    from yasdl.kicad_export import render

    info = render(INVERTING_WITH_WRAPPER, tmp_path, svg=False)
    assert info["roundtrip_ok"], (info["missing"], info["extra"])
    assert info["erc"] == []
