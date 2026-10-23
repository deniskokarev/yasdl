"""SPICE netlist export (ngspice dialect) from a yasdl Block."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .block import Atom, Block, flat_names, ground_root, YasdlError


@dataclass(frozen=True)
class SpiceModel:
    """How an atom becomes a SPICE element.

    prefix: element letter (R, C, L, D, Q, M, X ...); pins: symbol pin numbers in SPICE node
    order; model: model/subckt name, or None to use the atom's value as the element value;
    sim_pins: KiCad "Sim.Pins" mapping (symbol pin -> model pin) for kicad-cli's export.
    """

    prefix: str
    pins: tuple[str, ...]
    model: str | None = None
    sim_pins: str | None = None


# Defaults by KiCad lib_id. Model-based parts take the model name from the atom's value.
DEFAULTS = {
    "Device:R": SpiceModel("R", ("1", "2")),
    "Device:C": SpiceModel("C", ("1", "2")),
    "Device:C_Polarized": SpiceModel("C", ("1", "2")),
    "Device:L": SpiceModel("L", ("1", "2")),
    "Device:D": SpiceModel("D", ("2", "1"), model="", sim_pins="1=K 2=A"),
    "Device:Q_NPN": SpiceModel("Q", ("C", "B", "E"), model="", sim_pins="C=C B=B E=E"),
    "Device:Q_PNP": SpiceModel("Q", ("C", "B", "E"), model="", sim_pins="C=C B=B E=E"),
}


def spice_model(atom: Atom) -> SpiceModel | None:
    """The SPICE mapping of an atom; None for power symbols (they are global nets)."""
    if atom.symbol.is_power:
        return None
    m = atom.spice or DEFAULTS.get(atom.lib_id)
    if m is None:
        raise YasdlError(
            f"{atom.lib_id}: no SPICE mapping; pass Atom(..., spice=SpiceModel(...))"
        )
    if m.model == "":  # model name comes from the value
        if not atom.value:
            raise YasdlError(
                f"{atom.lib_id}: give the SPICE model name as the value, e.g. NPN('2N3904')"
            )
        m = SpiceModel(m.prefix, m.pins, atom.value, m.sim_pins)
    return m


def _instances(block: Block, prefix: str = ""):
    """(path, Bound) for every atom in the flattened design."""
    for name, b in block.bound.items():
        if isinstance(b.obj, Atom):
            yield prefix + name, b, b.obj
        else:
            yield from _instances(b.obj, f"{prefix}{name}.")


def spice_netlist(
    block: Block,
    subckt: str | None = None,
    port_order: list[str] | None = None,
    includes: tuple[str, ...] = (),
    title: str | None = None,
) -> str:
    """SPICE text for `block`.

    subckt: wrap in `.subckt <name> <ports>` (ports in DIP order unless port_order lists port
    names). Without it, a flat netlist is produced (ports become ordinary nodes).
    """
    uf, pins, names = flat_names(block)
    gnd = ground_root(uf)
    cv = block.canvas
    spice_names, used = {}, {}

    def node(n):
        """SPICE node of a flattened node: the global ground is 0; every other net keeps its
        yasdl name, sanitised and unique case-insensitively (ngspice ignores case)."""
        root = uf.find(n)
        if root == gnd:
            return "0"
        if root not in spice_names:
            base = re.sub(r"[^A-Za-z0-9_]", "_", names[root])
            cand, i = base, 2
            while used.get(cand.casefold(), root) != root or cand.casefold() in (
                "0",
                "gnd",
            ):
                cand, i = f"{base}_{i}", i + 1
            spice_names[root] = cand
            used[cand.casefold()] = root
        return spice_names[root]

    ports = sorted(block.ports, key=lambda p: p.dip)
    if port_order is not None:
        ports = [block.port(n) for n in port_order]
        if len(ports) != len(block.ports):
            raise YasdlError(f"{block.name}: port_order must list every port once")
    if subckt:
        # Formal interface names must survive an internal global supply label.
        # Flat exports retain the global name for KiCad/SPICE round trips.
        names = dict(names)
        for port in ports:
            edge = cv.edge_ports[block.ports.index(port)]
            root = uf.find(("", cv.uf.find(edge.node)))
            if port.name:
                names[root] = port.name
    if (
        subckt
    ):  # one net exposed twice: ngspice silently miswires duplicate formal nodes
        seen = {}
        for port in ports:
            root = uf.find(
                ("", cv.uf.find(cv.edge_ports[block.ports.index(port)].node))
            )
            if root in seen:
                raise YasdlError(
                    f"{block.name}: ports {seen[root]} and {port.name or port.default} "
                    "are the same net; a SPICE subcircuit can't expose one node as two "
                    "pins (ngspice would miswire it). Keep one of the ports."
                )
            seen[root] = port.name or port.default
    port_nodes = []
    for port in ports:
        edge_node = ("", cv.uf.find(cv.edge_ports[block.ports.index(port)].node))
        if subckt and uf.find(edge_node) == gnd:
            raise YasdlError(
                f"{block.name}: port {port.name or port.default} is on the global "
                "ground; ground is implicit in SPICE (node 0), so it can't be a "
                "subcircuit pin. Leave it out of the block's ports."
            )
        port_nodes.append(node(edge_node))

    lines = [f"* {title or block.name} (generated by yasdl)"]
    lines += [f".include {inc}" for inc in includes]
    if subckt:
        lines.append(f".subckt {subckt} {' '.join(port_nodes)}")
    for path, b, atom in _instances(block):
        m = spice_model(atom)
        if m is None:
            continue
        by_pin = {}
        for att, pin in b.pin_map:
            by_pin[pin] = att
        nodes = []
        for pin in m.pins:
            if (path, pin) not in pins:
                raise YasdlError(f"{path}: pin {pin} is not drawn")
            nodes.append(node(pins[(path, pin)]))
        label = m.prefix + "_" + re.sub(r"[^A-Za-z0-9_]", "_", path)
        lines.append(f"{label} {' '.join(nodes)} {m.model or atom.value}")
    if subckt:
        lines.append(f".ends {subckt}")
    return "\n".join(lines) + "\n"


def model_library(name: str, libs) -> str | None:
    """The first library file (path) that defines `.model name` or `.subckt name`."""
    pat = re.compile(
        rf"^\s*\.(model|subckt)\s+{re.escape(name)}\b", re.IGNORECASE | re.MULTILINE
    )
    for lib in libs:
        try:
            if pat.search(open(lib).read()):
                return str(lib)
        except OSError:
            continue
    return None


def parse_spice(text: str) -> list[tuple[str, list[str], str]]:
    """(name, nodes, value/model) for R/C/L/D/Q lines of a flat netlist (no subcircuits)."""
    n_nodes = {"R": 2, "C": 2, "L": 2, "D": 2, "Q": 3}
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] in "*." or line[0].upper() not in n_nodes:
            continue
        parts = line.split()
        k = n_nodes[line[0].upper()]
        out.append(
            (parts[0], parts[1 : 1 + k], parts[1 + k] if len(parts) > 1 + k else "")
        )
    return out


def spice_partition(elements, rename) -> tuple[set, set]:
    """Connectivity as a set of frozensets of (element id, node position), plus (id, value) pairs.
    `rename` maps an element name to a stable id (e.g. its yasdl path); None drops it."""
    nets, values = {}, set()
    for name, nodes, value in elements:
        eid = rename(name)
        if eid is None:
            continue
        values.add((eid, value.lower()))
        for i, n in enumerate(nodes):
            nets.setdefault(n, set()).add((eid, i))
    return {frozenset(v) for v in nets.values()}, values
