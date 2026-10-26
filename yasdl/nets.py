"""Registered power nets and the names reserved for ground and supply rails.

Registered power names are reserved everywhere (spec 2.8): no port alias or local label may
use them, and global labels must use their registered spelling. Other net names use their
initial character to select scope (spec 2.4). "0" is reserved too: KiCad's SPICE export and
ngspice both treat a net named 0 as ground.
"""

from __future__ import annotations

import re

# Global nets drawn as power symbols (spec 2.4). The first one is the ground net.
GROUND = "GND"
POWER_NETS = {
    name: f"power:{name}"
    for name in (
        "GND",
        "GNDA",
        "VCC",
        "VEE",
        "VDD",
        "VSS",
        "+5V",
        "+3V3",
        "+12V",
        "-12V",
    )
}

DEFAULT_PORT_NAME = re.compile(r"^[NESWD]\d+$", re.IGNORECASE)  # W0, N1, D3, ...


def register_power_net(name: str, lib_id: str) -> None:
    """Draw global net `name` as the power symbol `lib_id` (e.g. "power:+15V")."""
    POWER_NETS[name] = lib_id


def reserved(name: str) -> bool:
    """Is `name` (any case) reserved for a global net?"""
    return name == "0" or name.casefold() in {k.casefold() for k in POWER_NETS}


def global_spelling(name: str) -> str | None:
    """The registered spelling of a reserved global name, or None if `name` isn't one exactly."""
    return name if name in POWER_NETS else None
