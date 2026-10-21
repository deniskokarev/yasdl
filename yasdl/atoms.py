"""Atom factories for common KiCad 9 library symbols, and the power-net registry."""

from .block import Atom
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


def GND() -> Atom:
    return Atom("power:GND", "GND")


def VCC() -> Atom:
    return Atom("power:VCC", "VCC")


def VEE() -> Atom:
    return Atom("power:VEE", "VEE")
