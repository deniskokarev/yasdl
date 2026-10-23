"""Atom factories for common KiCad 9 library symbols, and the power-net registry."""

from .block import Atom
from .kicad_lib import BUNDLED_MODELS
from .nets import POWER_NETS, register_power_net  # noqa: F401  (re-exported)


def R(value: str = "") -> Atom:
    return Atom("Device:R", value, symmetric=True)


def C(value: str = "") -> Atom:
    return Atom("Device:C", value, symmetric=True)


def L(value: str = "") -> Atom:
    return Atom("Device:L", value, symmetric=True)


def C_POL(value: str = "") -> Atom:
    return Atom("Device:C_Polarized", value, aliases={"+": "1"})


# Arrows show conventional current in the library orientation, one pin per arrow (spec 2.5).
def NPN(value: str = "") -> Atom:
    """B left (> current in), C top, E bottom (v current out, like the symbol's arrow)."""
    return Atom("Device:Q_NPN", value, arrows={"B": ">", "E": "v"})


def PNP(value: str = "") -> Atom:
    """B left (< current out), C top, E bottom (^ current in)."""
    return Atom("Device:Q_PNP", value, arrows={"B": "<", "E": "^"})


def D(value: str = "") -> Atom:
    """Diode: cathode (pin 1) left, anode (pin 2) right. The anode carries the arrow: current
    enters it, pointing at the cathode (< in the library orientation), so --->D1--- puts the
    anode on the left."""
    return Atom("Device:D", value, arrows={"2": "<"})


def OPAMP(value: str = "") -> Atom:
    """Ideal op-amp (Simulation_SPICE:OPAMP): + and - on the left, out right, V+ top, V- bottom."""
    return Atom("Simulation_SPICE:OPAMP", value)


def OPAMP_IDEAL() -> Atom:
    """Ideal op-amp without supply pins (yasdl:OPAMP_IDEAL): + above -, out on the right.
    Simulates as the bundled behavioural subcircuit yasdl_ideal_opamp (gain 1e9)."""
    from .spice import SpiceModel

    return Atom(
        "yasdl:OPAMP_IDEAL",
        "OPAMP_IDEAL",
        spice=SpiceModel(
            "X",
            ("1", "2", "3"),
            "yasdl_ideal_opamp",
            "1=inp 2=inn 3=out",
            str(BUNDLED_MODELS),
        ),
    )


def V(value: str = "") -> Atom:
    """Independent voltage source (Simulation_SPICE:VDC), + on top. The value is the SPICE
    source specification, e.g. "1", "dc 0 ac 1", "pulse(0 1 0 1n 1n 1m 2m)"."""
    from .spice import SpiceModel

    return Atom(
        "Simulation_SPICE:VDC",
        value,
        aliases={"+": "1"},
        spice=SpiceModel("V", ("1", "2")),
    )


def I(value: str = "") -> Atom:  # noqa: E743
    """Independent current source (Simulation_SPICE:IDC). SPICE convention: current flows from
    the + pin (top) through the source to the - pin, i.e. out of the bottom pin. The arrow `v`
    marks that pin: `v` below the part means the current leaves downwards."""
    from .spice import SpiceModel

    return Atom(
        "Simulation_SPICE:IDC",
        value,
        aliases={"+": "1"},
        arrows={"2": "v"},
        spice=SpiceModel("I", ("1", "2")),
    )


def GND() -> Atom:
    return Atom("power:GND", "GND")


def VCC() -> Atom:
    return Atom("power:VCC", "VCC")


def VEE() -> Atom:
    return Atom("power:VEE", "VEE")
