"""yasdl: yet another schematic definition language (ASCII canvas of rectangular blocks)."""

from .atoms import (
    C,
    C_POL,
    D,
    GND,
    I,
    L,
    NPN,
    OPAMP,
    OPAMP_IDEAL,
    PNP,
    POT,
    POWER_NETS,
    R,
    register_power_net,
    V,
    VCC,
    VEE,
)
from .block import Atom, Block, NC, netlist, partition, YasdlError
from .canvas import CanvasError, minimal_period
from .sketch import Sketch
from .spice import spice_netlist, SpiceModel
from .kicad_lib import YasdlDependencyError as DependencyError
from .atoms import pot_position


def __getattr__(name):
    if name in {'AtomNPN', 'AtomPNP', 'AtomDiode', 'AtomOpamp3', 'AtomOpamp5', 'OpampPackage', 'Package', 'PackageType'}:
        from . import parts
        return getattr(parts, name)
    raise AttributeError(name)

__all__ = [
    "AtomNPN", "AtomPNP", "AtomDiode", "AtomOpamp3", "AtomOpamp5",
    "OpampPackage", "Package", "PackageType", "DependencyError", "pot_position",
    "Atom",
    "Block",
    "C",
    "C_POL",
    "D",
    "PNP",
    "POT",
    "POWER_NETS",
    "Sketch",
    "SpiceModel",
    "register_power_net",
    "spice_netlist",
    "CanvasError",
    "GND",
    "I",
    "L",
    "NC",
    "NPN",
    "OPAMP",
    "OPAMP_IDEAL",
    "R",
    "V",
    "VCC",
    "VEE",
    "YasdlError",
    "minimal_period",
    "netlist",
    "partition",
]
