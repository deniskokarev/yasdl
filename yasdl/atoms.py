"""Atom factories for common KiCad 9 library symbols, and the power-net registry."""

from .block import Atom

# Global nets drawn as power symbols: a dangling <NAME> label whose name is registered here is
# rendered as that symbol (spec 2.4). Extend with register_power_net().
POWER_NETS = {name: f"power:{name}" for name in
              ("GND", "GNDA", "VCC", "VEE", "VDD", "VSS", "+5V", "+3V3", "+12V", "-12V")}


def register_power_net(name: str, lib_id: str) -> None:
    """Draw global net `name` as the power symbol `lib_id` (e.g. "power:+15V")."""
    POWER_NETS[name] = lib_id


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
