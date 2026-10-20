"""Atom factories for common KiCad 9 library symbols."""

from .block import Atom


def R(value: str = "") -> Atom:
    return Atom("Device:R", value, symmetric=True)


def C(value: str = "") -> Atom:
    return Atom("Device:C", value, symmetric=True)


def L(value: str = "") -> Atom:
    return Atom("Device:L", value, symmetric=True)


def C_POL(value: str = "") -> Atom:
    return Atom("Device:C_Polarized", value, aliases={"+": "1"})


def NPN(value: str = "") -> Atom:
    return Atom("Device:Q_NPN", value)


def PNP(value: str = "") -> Atom:
    return Atom("Device:Q_PNP", value)


def D(value: str = "") -> Atom:
    return Atom("Device:D", value)


def OPAMP(value: str = "") -> Atom:
    """Ideal op-amp (Simulation_SPICE:OPAMP): + and - on the left, out right, V+ top, V- bottom."""
    return Atom("Simulation_SPICE:OPAMP", value)


def GND() -> Atom:
    return Atom("power:GND", "GND")


def VCC() -> Atom:
    return Atom("power:VCC", "VCC")


def VEE() -> Atom:
    return Atom("power:VEE", "VEE")
