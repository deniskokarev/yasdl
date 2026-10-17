"""yasdl: yet another schematic definition language (rectangular-block based)."""

from .atoms import C, GND, L, NPN, OPAMP, R, VCC
from .core import GLYPHS, Atom, Block, Hole, Tx, YasdlError, netlist


def Series(*items, name: str = "Series") -> Block:
    """Elements in a row: W port of the first, E port of the last."""
    names = [f"X{i + 1}" for i in range(len(items))]
    return Block(name, " ".join(names), **dict(zip(names, items)))


def Parallel(*items, name: str = "Parallel") -> Block:
    """Elements stacked between a left and a right bus; ports on the first row."""
    if len(items) < 2:
        raise YasdlError("Parallel needs at least 2 items")
    names = [f"X{i + 1}" for i in range(len(items))]
    rows = [f"┬ {names[0]} ┬"]
    rows += [f"├ {n} ┤" for n in names[1:-1]]
    rows += [f"└ {names[-1]} ┘"]
    return Block(name, "\n".join(rows), **dict(zip(names, items)))


__all__ = ["Atom", "Block", "C", "GLYPHS", "GND", "Hole", "L", "NPN", "OPAMP", "Parallel", "R",
           "Series", "Tx", "VCC", "YasdlError", "netlist"]
