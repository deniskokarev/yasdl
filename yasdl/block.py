"""Blocks: a canvas plus component bindings (atoms or other blocks), and flat netlists."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import NamedTuple

from .canvas import Canvas, CanvasError, _UF
from .kicad_lib import ORIENTATIONS, compose, load, orient_side, orient_vec, pin_side, to_screen


class YasdlError(ValueError):
    pass


@dataclass(frozen=True)
class Atom:
    """A KiCad library symbol. rot: degrees counterclockwise; mirror: "x" (top/bottom) or "y"."""

    lib_id: str
    value: str = ""
    rot: int | None = None
    mirror: str | None = None
    symmetric: bool = False  # all pins interchangeable (R, C, L)
    aliases: dict = field(default_factory=dict)  # pin label -> pin number, e.g. {"+": "1"}
    spice: object = None  # spice.SpiceModel override (default by lib_id)

    def oriented(self, rot: int = 0, mirror: str | None = None) -> Atom:
        """Fixed orientation: rotate `rot` degrees counterclockwise, then mirror ("x"/"y")."""
        return replace(self, rot=rot, mirror=mirror)

    def rotated(self, deg: int) -> Atom:
        """Rotate counterclockwise by `deg` (multiple of 90), on top of any orientation set."""
        return replace(self, **dict(zip(("rot", "mirror"),
                                        compose((deg % 360, None), (self.rot or 0, self.mirror)))))

    def mirrored(self, axis: str) -> Atom:
        """Mirror about an axis: "y" flips left/right, "x" flips top/bottom (KiCad's convention)."""
        return replace(self, **dict(zip(("rot", "mirror"),
                                        compose(_MIRROR[axis], (self.rot or 0, self.mirror)))))

    @property
    def symbol(self):
        return load(self.lib_id)

    def side_pins(self, rot: int, mirror: str | None) -> dict[str, list]:
        """Pins per side in drawing order (W/E top to bottom, N/S left to right)."""
        out = {s: [] for s in "NESW"}
        for p in self.symbol.pins:
            out[pin_side(p, rot, mirror)].append(p)
        for s, lst in out.items():
            lst.sort(key=lambda p: to_screen(p.x, p.y, rot, mirror)[1 if s in "EW" else 0])
        return out

    def matches_label(self, pin, label: str) -> bool:
        """Pin labels match a pin's name or number, case-insensitively, or an alias."""
        lab = label.casefold()
        return lab in (pin.name.casefold(), pin.number.casefold()) or \
            self.aliases.get(label) == pin.number


@dataclass
class Bound:
    """A component as resolved in a block: what it is and how its pins map to attachments."""

    name: str
    obj: object  # Atom or Block
    rot: int = 0
    mirror: str | None = None
    pin_map: list = field(default_factory=list)  # [(Attachment, pin number or port index)]


_MIRROR = {"x": (0, "x"), "y": (180, "x")}  # "y" (left/right) = top/bottom flip + 180 deg


def display_orientation(rot: int, mirror: str | None) -> tuple[int, str | None]:
    """Readable form of an orientation: a left/right mirror shows as mirror "y", not 180 + "x"."""
    if mirror == "x" and rot in (90, 180):
        return (rot - 180) % 360, "y"
    return rot, mirror

RESERVED_NAME = re.compile(r"^[NESWD]\d+$", re.IGNORECASE)  # default port names W0, D3, ...
PORT_ATTRS = {"aliases"}  # programmatic port attributes supported so far


class Port(NamedTuple):
    """An external pin of a block. Default names: f"{side}{index}" and f"D{dip}"."""

    side: str
    index: int  # order along its side: W/E top to bottom, N/S left to right
    name: str | None  # primary alias, if any
    dip: int  # DIP-style number: counterclockwise from the top of the W side
    aliases: tuple = ()

    @property
    def default(self) -> str:
        return f"{self.side}{self.index}"

    def names(self) -> list[str]:
        return [*self.aliases, self.default, f"D{self.dip}"]

    def answers(self, label: str) -> bool:
        return label.casefold() in (n.casefold() for n in self.names())


def dip_order(edge_ports) -> list[int]:
    """DIP numbers for ports given as (side, pos): W top->bottom, S left->right,
    E bottom->top, N right->left."""
    key = {"W": lambda p: (0, p), "S": lambda p: (1, p), "E": lambda p: (2, -p), "N": lambda p: (3, -p)}
    order = sorted(range(len(edge_ports)), key=lambda i: key[edge_ports[i][0]](edge_ports[i][1]))
    dip = [0] * len(edge_ports)
    for n, i in enumerate(order):
        dip[i] = n
    return dip


@dataclass(frozen=True)
class OrientedBlock:
    """A block bound with an explicit orientation: `PARALLEL.oriented(270)`."""

    block: "Block"
    rot: int = 0
    mirror: str | None = None

    def rotated(self, deg: int) -> "OrientedBlock":
        return OrientedBlock(self.block, *compose((deg % 360, None), (self.rot, self.mirror)))

    def mirrored(self, axis: str) -> "OrientedBlock":
        return OrientedBlock(self.block, *compose(_MIRROR[axis], (self.rot, self.mirror)))


class Block:
    def __init__(self, name: str, canvas: str, port_attrs: dict | None = None, **bindings):
        """port_attrs: {port key: {"aliases": [...]}}; a key is W0-style, D3-style or an alias."""
        self.name, self.text, self.bindings = name, canvas, bindings
        self.port_attrs = port_attrs or {}
        try:
            self.canvas = Canvas(canvas, name)
        except CanvasError as e:
            raise YasdlError(str(e)) from None
        cv = self.canvas
        for b in bindings:
            if b not in cv.comps:
                raise YasdlError(f"{name}: binding {b!r} has no component on the canvas "
                                 f"(components: {sorted(cv.comps)})")
        self.unbound = sorted(set(cv.comps) - set(bindings))
        self.bound: dict[str, Bound] = {}
        for comp_name, obj in bindings.items():
            self.bound[comp_name] = self._bind(cv.comps[comp_name], obj)
        self.ports = self._make_ports()

    def _make_ports(self) -> list[Port]:
        """Ports in canvas edge-port order, with DIP numbers and validated aliases."""
        cv = self.canvas
        counters = {s: 0 for s in "NESW"}
        index = []
        for p in cv.edge_ports:
            index.append(counters[p.side])
            counters[p.side] += 1
        dip = dip_order([(p.side, p.pos) for p in cv.edge_ports])
        defaults = [f"{p.side}{i}" for p, i in zip(cv.edge_ports, index)]
        explicit = [[p.alias] if p.alias else [] for p in cv.edge_ports]
        reexport = [self._reexport_candidate(p) for p in cv.edge_ports]

        def lookup(key):
            for k, p in enumerate(cv.edge_ports):
                names = [defaults[k], f"D{dip[k]}", *explicit[k]]
                if reexport[k]:
                    names.append(reexport[k])
                if key.casefold() in (n.casefold() for n in names):
                    return k
            raise YasdlError(f"{self.name}: port_attrs key {key!r} matches no port")

        for key, attrs in self.port_attrs.items():
            unknown = set(attrs) - PORT_ATTRS
            if unknown:
                raise YasdlError(f"{self.name}: unsupported port attributes {sorted(unknown)} "
                                 f"for {key!r} (supported: {sorted(PORT_ATTRS)})")
            explicit[lookup(key)] += list(attrs.get("aliases", []))
        seen = {}
        for k, names in enumerate(explicit):
            for n in names:
                if RESERVED_NAME.match(n):
                    raise YasdlError(f"{self.name}: port alias {n!r} looks like a default port "
                                     "name (W0, D3, ...); pick another")
                if n.casefold() in seen and seen[n.casefold()] != k:
                    raise YasdlError(f"{self.name}: port alias {n!r} is used by two ports "
                                     f"({defaults[seen[n.casefold()]]} and {defaults[k]})")
                seen[n.casefold()] = k
        # Re-exported names only when unambiguous: unique among all ports, not reserved.
        counts = {}
        for r in reexport:
            if r:
                counts[r.casefold()] = counts.get(r.casefold(), 0) + 1
        ports = []
        for k, p in enumerate(cv.edge_ports):
            aliases = list(dict.fromkeys(explicit[k]))
            r = reexport[k]
            if (r and counts[r.casefold()] == 1 and r.casefold() not in seen
                    and not RESERVED_NAME.match(r) and not aliases):
                aliases.append(r)
            ports.append(Port(p.side, index[k], aliases[0] if aliases else None, dip[k],
                              tuple(aliases)))
        return ports

    def _reexport_candidate(self, edge_port) -> str | None:
        """The one pin name (atom pin name or sub-block port name) on the port's net, if any."""
        cv = self.canvas
        root = cv.uf.find(edge_port.node)
        names = set()
        for b in self.bound.values():
            for att, key in b.pin_map:
                if cv.uf.find(att.node) != root:
                    continue
                if isinstance(b.obj, Atom):
                    if b.obj.symbol.is_power:
                        continue
                    pin = next(p for p in b.obj.symbol.pins if p.number == key)
                    if pin.name not in ("", "~"):
                        names.add(pin.name)
                elif b.obj.ports[key].name:
                    names.add(b.obj.ports[key].name)
        folded = {n.casefold() for n in names}
        return sorted(names)[0] if len(folded) == 1 else None

    def port(self, key: str) -> Port:
        """Look a port up by W0-style name, D3-style number or alias."""
        for p in self.ports:
            if p.answers(key):
                return p
        raise YasdlError(f"{self.name}: no port {key!r}")

    def bind(self, **more) -> Block:
        """A copy with more components bound (the unbound ones are the block's open interface)."""
        return Block(self.name, self.text, self.port_attrs, **{**self.bindings, **more})

    def oriented(self, rot: int = 0, mirror: str | None = None) -> "OrientedBlock":
        """This block with a binding-time orientation (same convention as atoms)."""
        return OrientedBlock(self, rot, mirror)

    def rotated(self, deg: int) -> "OrientedBlock":
        return OrientedBlock(self).rotated(deg)

    def mirrored(self, axis: str) -> "OrientedBlock":
        """"y" flips left/right, "x" flips top/bottom."""
        return OrientedBlock(self).mirrored(axis)

    @property
    def symmetric(self) -> bool:
        return False

    def side_ports(self, rot: int, mirror: str | None) -> dict[str, list]:
        """Port indices per side, in drawing order, after orienting the block."""
        big = 10_000.0
        rep = {"W": lambda i: (0.0, i + 1.0), "E": lambda i: (big, i + 1.0),
               "N": lambda i: (i + 1.0, 0.0), "S": lambda i: (i + 1.0, big)}
        out = {s: [] for s in "NESW"}
        for k, port in enumerate(self.ports):
            side, idx = port.side, port.index
            new_side = orient_side(side, rot, mirror)
            x, y = orient_vec(*rep[side](idx), rot, mirror)
            out[new_side].append((y if new_side in "EW" else x, k))
        return {s: [k for _, k in sorted(v)] for s, v in out.items()}

    # --- binding -------------------------------------------------------------
    def _bind(self, comp, obj) -> Bound:
        """Resolve orientation (spec 3.2) and map pins/ports to the drawn attachments."""
        if isinstance(obj, OrientedBlock):
            target, fixed = obj.block, (obj.rot, obj.mirror)
        elif isinstance(obj, Block):
            target, fixed = obj, None
        elif isinstance(obj, Atom):
            target = obj
            fixed = None if obj.rot is None and obj.mirror is None else (obj.rot or 0, obj.mirror)
        else:
            raise YasdlError(f"{self.name}: {comp.name} must be bound to an Atom or a Block")
        drawn = {s: len(comp.attachments[s]) for s in "NESW"}
        is_atom = isinstance(target, Atom)

        def keys(rot, mirror):
            """Per side, in drawing order: (key, original side, labels it answers to)."""
            if is_atom:
                return {s: [(p.number, p.side, p) for p in v]
                        for s, v in target.side_pins(rot, mirror).items()}
            return {s: [(k, target.ports[k].side, target.ports[k]) for k in v]
                    for s, v in target.side_ports(rot, mirror).items()}

        def answers(item, label):
            if is_atom:
                return target.matches_label(item[2], label)
            return item[2].answers(label)

        def mapping(rot, mirror):
            sp = keys(rot, mirror)
            if {s: len(sp[s]) for s in "NESW"} != drawn:
                return None
            pairs = []
            for s in "NESW":
                pairs += [(att, item, s) for att, item in zip(comp.attachments[s], sp[s])]
            if any(att.pin_label and not answers(item, att.pin_label) for att, item, _ in pairs):
                return None
            return pairs

        labelled = any(a.pin_label for s in "NESW" for a in comp.attachments[s])
        options = [fixed] if fixed else ORIENTATIONS
        fits = [(o, m) for o in options if (m := mapping(*o)) is not None]
        what = target.lib_id if is_atom else f"block {target.name}"
        if not fits:
            have = {s: len(v) for s, v in keys(*(fixed or (0, None))).items()}
            raise YasdlError(f"{self.name}: {comp.name} ({what}) does not fit its drawing: "
                             f"drawn {drawn}, has {have}"
                             + (f" in orientation {fixed}" if fixed else " in any orientation"))
        def reading_order(fit):
            """Pins that stay on a start side (N/W) or an end side (S/E): higher is better."""
            return sum((orig in "NW") == (new in "NW") for _, (_, orig, _), new in fit[1])

        def axis_flips(fit):
            """How many of the two axes the orientation changes (mirror: 1, 180 deg: 2)."""
            rot, mirror = fit[0]
            return (orient_side("E", rot, mirror) != "E") + (orient_side("S", rot, mirror) != "S")

        best = max(fits, key=lambda f: (reading_order(f), -axis_flips(f), -ORIENTATIONS.index(f[0])))
        (rot, mirror), pairs = best
        return Bound(comp.name, target, rot, mirror, [(a, item[0]) for a, item, _ in pairs])

    # --- JSON view -------------------------------------------------------------
    def local_nets(self) -> dict:
        """This block's own nets (one level, sub-blocks opaque): {name: node roots}."""
        cv = self.canvas
        names, auto = {}, {}
        for root, text in cv.net_names.items():
            names[root] = text
        for b in self.bound.values():  # power symbols name their nets (GND, VCC, ...)
            if isinstance(b.obj, Atom) and b.obj.symbol.is_power:
                for att, _ in b.pin_map:
                    names.setdefault(cv.uf.find(att.node), b.obj.value or b.obj.lib_id.split(":")[1])
        for p, port in zip(cv.edge_ports, self.ports):
            names.setdefault(cv.uf.find(p.node), port.name or port.default)
        roots = {cv.uf.find(n) for n in cv.uf.parent}
        for r in sorted(roots, key=str):
            if r not in names:
                auto[r] = f"N{len(auto) + 1}"
        return {**names, **auto}

    def to_dict(self, _blocks: dict | None = None) -> dict:
        """Source (canvas + bindings) and the parsed view: components, attachments, nets, ports.

        Sub-block definitions are listed once under "blocks" (top level only) and referenced by
        name, so shared sub-circuits are not duplicated.
        """
        top = _blocks is None
        blocks = {} if top else _blocks
        cv = self.canvas
        net_of = self.local_nets()
        net = lambda node: net_of[cv.uf.find(node)]  # noqa: E731
        comps, net_pins = {}, {}
        for name, comp in sorted(cv.comps.items()):
            b = self.bound.get(name)
            key_of = {id(a): k for a, k in (b.pin_map if b else [])}
            atts = {}
            for side in "NESW":
                lst = []
                for a in comp.attachments[side]:
                    entry = {"pos": a.pos, "net": net(a.node)}
                    if a.pin_label:
                        entry["label"] = a.pin_label
                    if b:
                        k = key_of[id(a)]
                        entry["pin"] = (k if isinstance(b.obj, Atom)
                                        else (b.obj.ports[k].name or b.obj.ports[k].default))
                        net_pins.setdefault(entry["net"], []).append(f"{name}.{entry['pin']}")
                    lst.append(entry)
                if lst:
                    atts[side] = lst
            if b is None:
                binding = None
            elif isinstance(b.obj, Atom):
                rot, mir = display_orientation(b.rot, b.mirror)
                binding = {"atom": b.obj.lib_id, "value": b.obj.value, "rot": rot, "mirror": mir}
            else:
                if b.obj.name not in blocks:
                    blocks[b.obj.name] = None  # reserve (recursion guard)
                    blocks[b.obj.name] = b.obj.to_dict(blocks)
                rot, mir = display_orientation(b.rot, b.mirror)
                binding = {"block": b.obj.name, "rot": rot, "mirror": mir}
            comps[name] = {"rect": {"row": comp.r0, "col": comp.c0, "rows": comp.r1 - comp.r0 + 1,
                                    "cols": comp.c1 - comp.c0 + 1},
                           "binding": binding, "attachments": atts}
        labels = {}
        for i, lab in enumerate(cv.labels):
            if lab.pin_of is None:
                labels.setdefault(net(("l", i)), []).append(
                    {"text": lab.text, "row": lab.row, "col": lab.c0})
        nets = {}
        for n in sorted(set(net_of.values())):
            nets[n] = {"pins": sorted(net_pins.get(n, [])),
                       "ports": [port.name or port.default
                                 for port, p in zip(self.ports, cv.edge_ports) if net(p.node) == n],
                       "labels": labels.get(n, [])}
        out = {"name": self.name, "size": {"cols": cv.W, "rows": cv.H}, "canvas": cv.g,
               "components": comps, "unbound": self.unbound,
               "ports": [{"side": port.side, "index": port.index, "dip": port.dip,
                          "aliases": list(port.aliases), "net": net(p.node)}
                         for port, p in zip(self.ports, cv.edge_ports)],
               "nets": {k: v for k, v in nets.items() if v["pins"] or v["ports"] or v["labels"]}}
        if top and blocks:
            out["blocks"] = blocks
        return out

    def __repr__(self):
        return (f"Block({self.name}, {self.canvas.H}x{self.canvas.W}, ports={self.ports}, "
                f"unbound={self.unbound})")


# --- flat netlist ------------------------------------------------------------------
def _flatten(block: Block, prefix: str, uf: _UF, pins: dict, ext: dict):
    """ext: canvas edge-port index -> outer node to join (sub-block instances)."""
    cv = block.canvas
    if block.unbound:
        raise YasdlError(f"{prefix or block.name}: unbound components {block.unbound}")
    key = lambda n: (prefix, cv.uf.find(n))  # noqa: E731
    for i, port in enumerate(cv.edge_ports):
        if i in ext:
            uf.union(key(port.node), ext[i])
    for i, lab in enumerate(cv.labels):  # global net labels join across the whole design
        if lab.kind == "global":
            uf.union(key(("l", i)), ("global", lab.text))
    for name, b in block.bound.items():
        if isinstance(b.obj, Atom):
            power = b.obj.symbol.is_power
            for att, pin in b.pin_map:
                pins[(prefix + name, pin)] = key(att.node)
                if power:
                    uf.union(key(att.node), ("global", b.obj.value or b.obj.lib_id.split(":")[1]))
        else:
            child_ext = {idx: key(att.node) for att, idx in b.pin_map}
            _flatten(b.obj, f"{prefix}{name}.", uf, pins, child_ext)
    for n in cv.uf.parent:
        uf.find(key(n))


def netlist(block: Block) -> dict[str, list[str]]:
    """{net name: sorted ["path.pin", ...]}; global power nets and named nets keep names."""
    uf, pins = _UF(), {}
    _flatten(block, "", uf, pins, {})
    names = {}
    for k in list(uf.parent):
        if k[0] == "global":
            names[uf.find(k)] = k[1]
    cv = block.canvas
    for root, text in cv.net_names.items():
        names.setdefault(uf.find(("", root)), text)
    for edge, port in zip(cv.edge_ports, block.ports):
        names.setdefault(uf.find(("", cv.uf.find(edge.node))), port.name or port.default)
    nets, auto = {}, {}
    for (ref, pin), node in sorted(pins.items()):
        root = uf.find(node)
        name = names.get(root) or auto.setdefault(root, f"N{len(auto) + 1}")
        nets.setdefault(name, []).append(f"{ref}.{pin}")
    return nets


def partition(nets: dict) -> set[frozenset]:
    return {frozenset(v) for v in nets.values()}
