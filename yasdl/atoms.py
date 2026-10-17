"""Atomic elements backed by KiCad 9 library symbols.

Ports are given in the symbol's library orientation (pin positions from the .kicad_sym files):
Device:R/C/L have pin 1 on top and pin 2 at the bottom; Device:Q_NPN has B left, C top,
E bottom; Simulation_SPICE:OPAMP has + (pin 1) upper-left, - (pin 2) lower-left and the
output (pin 5) right, so it spans 3 rows. Its supply pins (3, 4) are not grid ports yet.
"""

from .core import Atom


def R(value: str = "") -> Atom:
    return Atom("R", "Device:R", (("N", 0, "1"), ("S", 0, "2")), value=value)


def C(value: str = "") -> Atom:
    return Atom("C", "Device:C", (("N", 0, "1"), ("S", 0, "2")), value=value)


def L(value: str = "") -> Atom:
    return Atom("L", "Device:L", (("N", 0, "1"), ("S", 0, "2")), value=value)


def NPN(value: str = "") -> Atom:
    return Atom("NPN", "Device:Q_NPN", (("W", 0, "B"), ("N", 0, "C"), ("S", 0, "E")), value=value)


def OPAMP(value: str = "") -> Atom:
    return Atom("OPAMP", "Simulation_SPICE:OPAMP",
                (("W", 0, "1"), ("W", 2, "2"), ("E", 1, "5")), h=3, value=value)


def GND() -> Atom:
    return Atom("GND", "power:GND", (("N", 0, "1"),), global_net="GND")


def VCC() -> Atom:
    return Atom("VCC", "power:VCC", (("S", 0, "1"),), global_net="VCC")
