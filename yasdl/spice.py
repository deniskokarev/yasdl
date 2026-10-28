"""SPICE netlist export (ngspice dialect) from a yasdl Block."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .block import Atom, Block, flat_names, ground_root, YasdlError


@dataclass(frozen=True)
class SpiceModel:
    """How an atom becomes a SPICE element.

    prefix: element letter (R, C, L, D, Q, M, X ...); pins: symbol pin numbers in SPICE node
    order; model: model/subckt name, or None to use the atom's value as the element value;
    sim_pins: KiCad "Sim.Pins" mapping (symbol pin -> model pin) for kicad-cli's export;
    params: instance parameters ("R=100k POS=0.25") appended to the element line and written
    to KiCad's "Sim.Params", so one subcircuit serves differently set instances.
    """

    prefix: str
    pins: tuple[str, ...]
    model: str | None = None
    sim_pins: str | None = None
    library: str | None = None  # file defining `model`; spice_netlist .includes it
    params: str | None = None


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
    """The SPICE mapping of an atom; None for power symbols (they are global nets) and for
    non-simulated parts (Atom(sim=False): connectors, jacks, mounting holes)."""
    if atom.symbol.is_power or not atom.sim or atom.package is not None:
        return None  # package units simulate as one element per package (packages())
    m = atom.spice or DEFAULTS.get(atom.lib_id)
    if m is None:
        raise YasdlError(
            f"{atom.lib_id}: no SPICE mapping; pass Atom(..., spice=SpiceModel(...)) or sim=False"
        )
    if m.model == "":  # model name comes from the value
        if not atom.value:
            raise YasdlError(
                f"{atom.lib_id}: give the SPICE model name as the value, e.g. NPN('2N3904')"
            )
        m = SpiceModel(m.prefix, m.pins, atom.value, m.sim_pins, m.library, m.params)
    return m


# --- values ---------------------------------------------------------------------------
# ngspice reads a number, then an optional scale factor (case-insensitive, MEG = mega and
# M = milli), and ignores any letters after it. KiCad reads M as mega, m as milli, and lets a
# prefix or R stand for the decimal point (4k7, 2R2). Spec 6.2: values whose two readings
# differ are rejected rather than rewritten.
_NG_SCALE = {"t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "mil": 25.4e-6, "m": 1e-3,
             "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15, "a": 1e-18}
_NG_NUMBER = re.compile(
    r"\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)(meg|mil|[tgkmunpfa])?(\w*)\s*",
    re.IGNORECASE,
)
_KI_SCALE = {"T": 1e12, "G": 1e9, "M": 1e6, "Meg": 1e6, "MEG": 1e6, "meg": 1e6, "k": 1e3,
             "K": 1e3, "R": 1.0, "r": 1.0, "": 1.0, "m": 1e-3, "u": 1e-6, "µ": 1e-6,
             "μ": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15}
_KI_NUMBER = re.compile(
    r"\s*(\d*)(?:\.(\d+))?(Meg|MEG|meg|[TGMkKRrmuµμnpf])?(\d*)\s*([A-Za-zΩ]*)\s*"
)


def ngspice_number(text: str) -> float | None:
    """The number ngspice reads from an element value, or None if it isn't a plain number."""
    m = _NG_NUMBER.fullmatch(text)
    if not m:
        return None
    return float(m.group(1)) * _NG_SCALE.get((m.group(2) or "").lower(), 1.0)


def kicad_number(text: str) -> float | None:
    """The number KiCad reads from a passive's value (1M = mega, 4k7 = 4.7k, 2R2 = 2.2)."""
    m = _KI_NUMBER.fullmatch(text)
    if not m or not (m.group(1) or m.group(2)):
        return None
    whole, frac, prefix, tail, _unit = m.groups()
    if tail and (frac or not prefix):
        return None
    digits = frac or tail
    return float(f"{whole or 0}.{digits or 0}") * _KI_SCALE[prefix or ""]


def check_value(path: str, prefix: str, value: str) -> None:
    """Reject an R/C/L value that KiCad and ngspice read as different numbers (spec 6.2):
    USE MEG FOR MEGA, lowercase m FOR MILLI, and a decimal point instead of 4k7/2R2."""
    if prefix not in ("R", "C", "L"):
        return
    ki, ng = kicad_number(value), ngspice_number(value)
    if ki is None or ng is None or math.isclose(ki, ng, rel_tol=1e-9):
        return
    raise YasdlError(
        f"{path}: value {value!r} means {ki:g} to KiCad but {ng:g} to ngspice; write it "
        "unambiguously: MEG for mega ('1Meg'), lowercase m for milli ('1m'), and a decimal "
        "point instead of an embedded prefix ('4.7k', not '4k7')"
    )


def _instances(block: Block, prefix: str = ""):
    """(path, Bound, Atom) for every atom in the flattened design."""
    for name, b in block.bound.items():
        if isinstance(b.obj, Atom):
            yield prefix + name, b, b.obj
        elif isinstance(b.obj, Block):
            yield from _instances(b.obj, f"{prefix}{name}.")


def spice_netlist(
    block: Block,
    subckt: str | None = None,
    port_order: list[str] | None = None,
    includes: tuple[str, ...] = (),
    title: str | None = None,
    validate_values: bool = True,
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
        if len(ports) != len(block.ports) or len(set(ports)) != len(ports):
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
    libs = []
    pkgs = packages(block)
    for _, _, atom in _instances(block):
        m = spice_model(atom)
        if m is not None and m.library and m.library not in libs:
            libs.append(m.library)
    for pkg in pkgs:
        if not pkg.package.sim:
            continue
        lib = pkg.package.descriptor.library
        if pkg.package.descriptor.model and lib and lib not in libs:
            libs.append(lib)
    from pathlib import Path
    from .kicad_lib import YasdlDependencyError
    for lib in [*libs, *includes]:
        if Path(lib).is_absolute() and not Path(lib).is_file():
            models = [spice_model(a).model for _, _, a in _instances(block)
                      if spice_model(a) is not None and spice_model(a).library == lib]
            raise YasdlDependencyError(f"SPICE export: library {lib} does not exist (model {models[0]!r})"
                                       if models else f"SPICE export: library {lib} does not exist")
    lines += [f".include {inc}" for inc in [*libs, *includes]]
    wrappers = []
    for pkg in pkgs:  # whole-package wrappers around single-amplifier models
        if not pkg.package.sim:
            continue
        d = pkg.package.descriptor
        if d.model and d.scope == "unit" and d.wrapper() not in wrappers:
            wrappers.append(d.wrapper())
    lines += [w.rstrip("\n") for w in wrappers]
    if subckt:
        # ngspice makes every non-pin node of a .subckt local. Global nets that aren't
        # subcircuit pins ([VCC] with no {vp} port) need .global to reach the testbench's
        # VCC; ground is node 0 and always global (spec 6.2).
        port_roots = {
            uf.find(("", cv.uf.find(cv.edge_ports[block.ports.index(p)].node)))
            for p in ports
        }
        global_roots = {
            uf.find(k) for k in uf.parent if k[0] == "global" and uf.find(k) != gnd
        }
        reached = used_roots(uf, pins)
        globals_ = sorted(
            {node(r) for r in global_roots - port_roots if r in reached},
            key=str.casefold,
        )
        if globals_:
            lines.append(f".global {' '.join(globals_)}")
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
        if not m.model and validate_values:
            check_value(path, m.prefix, atom.value)
        lines.append(
            f"{label} {' '.join(nodes)} {m.model or atom.value} {m.params or ''}".rstrip()
        )
    for pkg in pkgs:
        if not pkg.package.sim:
            continue
        d = pkg.package.descriptor
        if not d.model:
            raise YasdlError(
                f"package {pkg.package.name} ({d.name}): no SPICE model; give the "
                "OpampPackage a model and library, or mark its units sim=False"
            )
        model, order = d.spice_element()
        nodes = [node(pins[pkg.pin_path[pin], pin]) for pin in order]
        name = re.sub(r"[^A-Za-z0-9_]", "_", pkg.name)
        params = getattr(d, 'spice', None)
        lines.append(f"X_{name} {' '.join(nodes)} {model} {params.params or ''}".rstrip() if params else f"X_{name} {' '.join(nodes)} {model}")
    if subckt:
        lines.append(f".ends {subckt}")
    return "\n".join(lines) + "\n"


@dataclass
class PlacedPackage:
    """A Package as used in a design: its unit paths and, per physical pin, the path of the
    unit view that carries it."""

    package: object
    unit_paths: dict  # unit key -> yasdl path
    pin_path: dict  # physical pin -> yasdl path

    @property
    def name(self):
        return self.package.name or next(iter(self.unit_paths.values()))


def packages(block: Block) -> list[PlacedPackage]:
    """Packages of the flattened design, in order of appearance. Every unit (amplifiers and
    the power unit) must be bound exactly once: KiCad reports unplaced units, and one
    package can't sit in two places (spec 6.3)."""
    found: dict[int, PlacedPackage] = {}
    for path, _, atom in _instances(block):
        pkg = atom.package
        if pkg is None:
            continue
        key = next(k for k, a in pkg._units.items() if a is atom or a == atom)
        placed = found.setdefault(id(pkg), PlacedPackage(pkg, {}, {}))
        if key in placed.unit_paths:
            raise YasdlError(
                f"package {pkg.name}: unit {key} is bound twice ({placed.unit_paths[key]} "
                f"and {path}); each unit of one physical package is placed once"
            )
        placed.unit_paths[key] = path
        for pin in atom.symbol.pins:
            placed.pin_path[pin.number] = path
    for placed in found.values():
        missing = [u for u in placed.package.units if u not in placed.unit_paths]
        if missing:
            letters = [chr(65 + placed.package.units.index(u)) for u in missing]
            raise YasdlError(
                f"package {placed.package.name}: units {missing} are not bound; place every "
                f"unit (unbound units {', '.join(letters)}); place every "
                "unit (terminate an unused amplifier, e.g. as a grounded follower, and bind "
                "the power unit once with chip.power())"
            )
    names = {}
    for placed in found.values():
        if placed.name.casefold() in names:
            raise YasdlError(f"two packages are named {placed.name!r}")
        names[placed.name.casefold()] = placed
    return list(found.values())


def used_roots(uf, pins) -> set:
    """Flattened roots that reach at least one atom pin (nets a SPICE deck mentions)."""
    return {uf.find(n) for n in pins.values()}


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


_N_NODES = {"R": 2, "C": 2, "L": 2, "D": 2, "Q": 3, "V": 2, "I": 2,
            "M": 4, "J": 3, "B": 2, "E": 4, "G": 4, "F": 2, "H": 2}


def spice_lines(text: str) -> list[str]:
    """Logical lines of a netlist: continuation lines (+ ...) joined, comments dropped."""
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] == "*":
            continue
        if line[0] == "+" and out:
            out[-1] += " " + line[1:].strip()
        else:
            out.append(line)
    return out


def parse_spice(text: str, subckt: str | None = None) -> list[tuple[str, list[str], str]]:
    """(name, nodes, value) for the top-level R/C/L/D/Q, V/I and X lines of a netlist.

    Lines inside .subckt definitions, dot cards and comments are skipped; continuation lines
    are joined. The value is everything after the nodes: the R/C/L value, the D/Q model, the
    complete V/I source specification, or for X the subcircuit name followed by its instance
    parameters. Node names GND/gnd become 0 (ngspice treats them alike).
    """
    out, depth, selected = [], 0, False
    for line in spice_lines(text):
        low = line.lower()
        if low.startswith(".subckt"):
            depth += 1
            if depth == 1:
                selected = low.split()[1:2] == [subckt.casefold()] if subckt else False
            continue
        if low.startswith(".ends"):
            depth -= 1
            continue
        if (depth != 0 if subckt is None else depth != 1 or not selected) or line[0] == ".":
            continue
        kind = line[0].upper()
        parts = line.split()
        if kind == "X":
            rest = [t for t in parts[1:] if "=" not in t]
            params = [t for t in parts[1:] if "=" in t]
            if rest and rest[-1].lower() == "params:":
                rest.pop()
            nodes, value = rest[:-1], " ".join(rest[-1:] + params)
        elif kind in _N_NODES:
            k = _N_NODES[kind]
            nodes, value = parts[1 : 1 + k], " ".join(parts[1 + k :])
        else:
            nodes, value = [], " ".join(parts[1:])
        nodes = ["0" if n.casefold() == "gnd" else n for n in nodes]
        out.append((parts[0], nodes, value))
    return out


def normalize_value(name: str, value: str) -> str:
    """Comparable form of an element value: R/C/L as the number ngspice reads, everything
    else case- and whitespace-normalised text (the full source spec or model + params)."""
    if name[:1].upper() in ("R", "C", "L"):
        n = ngspice_number(value)
        if n is not None:
            return f"{n:.9g}"
    return " ".join(value.split()).casefold()


def spice_partition(elements, rename, named=()) -> tuple[set, set]:
    """Connectivity as a set of frozensets of (element id, node position), plus (id, value)
    pairs. `rename` maps an element name to a stable id (e.g. its yasdl path); None drops it.

    named: node names that carry identity beyond connectivity (ground 0 and global nets).
    A net with such a name gets a ("=", NAME) member, so swapping VCC and GND, or moving a
    pin from a global net to a local one, compares unequal.
    """
    keep = {n.casefold() for n in named} | {"0"}
    nets, values = {}, set()
    for name, nodes, value in elements:
        eid = rename(name)
        if eid is None:
            continue
        values.add((eid, normalize_value(name, value)))
        for i, n in enumerate(nodes):
            nets.setdefault(n.casefold(), set()).add((eid, i))
    for n, members in nets.items():
        if n.casefold() in keep:
            members.add(("=", n.upper()))
    return {frozenset(v) for v in nets.values()}, values


def compare_spice(ours, theirs, rename_ours=None, rename_theirs=None, named=()):
    """Differences between two (partition, values) pairs as readable lines; [] if equal."""
    if rename_ours is not None or rename_theirs is not None:
        a = spice_partition(parse_spice(ours), rename_ours or (lambda n: n), named)
        b = spice_partition(parse_spice(theirs), rename_theirs or (lambda n: n), named)
        diff = compare_spice(a, b)
        return not diff, '; '.join(diff)
    (o_part, o_vals), (t_part, t_vals) = ours, theirs
    diff = []
    o_ids = {e for e, _ in o_vals}
    t_ids = {e for e, _ in t_vals}
    if o_ids - t_ids:
        diff.append(f"missing elements {sorted(o_ids - t_ids)}")
    if t_ids - o_ids:
        diff.append(f"extra elements {sorted(t_ids - o_ids)}")
    common = o_ids & t_ids
    for e, v in sorted(o_vals - t_vals):
        if e in common:
            other = sorted(w for f, w in t_vals if f == e)
            diff.append(f"{e}: value {v!r} vs {other[0] if other else None!r}")
    if o_part != t_part:
        for net in sorted({m[1] for p in o_part | t_part for m in p if m[0] == '='}):
            a = {p for p in o_part if ('=', net) in p}
            b = {p for p in t_part if ('=', net) in p}
            if a != b:
                diff.append(f"net {net}: terminal membership differs")
        fmt = lambda s: sorted(sorted(map(str, net)) for net in s)  # noqa: E731
        diff.append(
            f"connectivity: only ours {fmt(o_part - t_part)[:4]}, "
            f"only theirs {fmt(t_part - o_part)[:4]}"
        )
    return diff
