"""Blocks: a canvas plus component bindings (atoms or other blocks), and flat netlists."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .canvas import Canvas, CanvasError, _UF
from .kicad_lib import ORIENTATIONS, load, orient_side, orient_vec, pin_side, to_screen


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

    def oriented(self, rot: int = 0, mirror: str | None = None) -> Atom:
        return replace(self, rot=rot, mirror=mirror)

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


@dataclass(frozen=True)
class OrientedBlock:
    """A block bound with an explicit orientation: `PARALLEL.oriented(270)`."""

    block: "Block"
    rot: int = 0
    mirror: str | None = None


class Block:
    def __init__(self, name: str, canvas: str, **bindings):
        self.name, self.text, self.bindings = name, canvas, bindings
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
        # External ports per side, in order: [(side, index, name)].
        self.ports = []
        counters = {s: 0 for s in "NESW"}
        for p in cv.edge_ports:
            self.ports.append((p.side, counters[p.side], cv.port_name(p)))
            counters[p.side] += 1

    def bind(self, **more) -> Block:
        """A copy with more components bound (the unbound ones are the block's open interface)."""
        return Block(self.name, self.text, **{**self.bindings, **more})

    def oriented(self, rot: int = 0, mirror: str | None = None) -> "OrientedBlock":
        """This block with a binding-time orientation (same convention as atoms)."""
        return OrientedBlock(self, rot, mirror)

    @property
    def symmetric(self) -> bool:
        return False

    def side_ports(self, rot: int, mirror: str | None) -> dict[str, list]:
        """Port indices per side, in drawing order, after orienting the block."""
        big = 10_000.0
        rep = {"W": lambda i: (0.0, i + 1.0), "E": lambda i: (big, i + 1.0),
               "N": lambda i: (i + 1.0, 0.0), "S": lambda i: (i + 1.0, big)}
        out = {s: [] for s in "NESW"}
        for k, (side, idx, _) in enumerate(self.ports):
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
            return {s: [(k, target.ports[k][0], target.ports[k][2]) for k in v]
                    for s, v in target.side_ports(rot, mirror).items()}

        def answers(item, label):
            if is_atom:
                return target.matches_label(item[2], label)
            return item[2] is not None and item[2].casefold() == label.casefold()

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
        if labelled and not target.symmetric:
            if len({tuple(item[0] for _, item, _ in m) for _, m in fits}) > 1:
                raise YasdlError(f"{self.name}: pin labels of {comp.name} fit several "
                                 "orientations; label another pin")

        def reading_order(fit):
            """Pins that stay on a start side (N/W) or an end side (S/E): higher is better."""
            return sum((orig in "NW") == (new in "NW") for _, (_, orig, _), new in fit[1])

        best = max(fits, key=lambda f: (reading_order(f), -ORIENTATIONS.index(f[0])))
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
        for p, (side, idx, pname) in zip(cv.edge_ports, self.ports):
            names.setdefault(cv.uf.find(p.node), pname or f"{side}{idx}")
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
                                        else (b.obj.ports[k][2] or f"{b.obj.ports[k][0]}{b.obj.ports[k][1]}"))
                        net_pins.setdefault(entry["net"], []).append(f"{name}.{entry['pin']}")
                    lst.append(entry)
                if lst:
                    atts[side] = lst
            if b is None:
                binding = None
            elif isinstance(b.obj, Atom):
                binding = {"atom": b.obj.lib_id, "value": b.obj.value, "rot": b.rot, "mirror": b.mirror}
            else:
                if b.obj.name not in blocks:
                    blocks[b.obj.name] = None  # reserve (recursion guard)
                    blocks[b.obj.name] = b.obj.to_dict(blocks)
                binding = {"block": b.obj.name, "rot": b.rot, "mirror": b.mirror}
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
                       "ports": [f"{s}{i}" for (s, i, _), p in zip(self.ports, cv.edge_ports)
                                 if net(p.node) == n],
                       "labels": labels.get(n, [])}
        out = {"name": self.name, "size": {"cols": cv.W, "rows": cv.H}, "canvas": cv.g,
               "components": comps, "unbound": self.unbound,
               "ports": [{"side": s, "index": i, "name": nm, "net": net(p.node)}
                         for (s, i, nm), p in zip(self.ports, cv.edge_ports)],
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
    for i, port in enumerate(cv.edge_ports):
        side, idx, pname = block.ports[i]
        names.setdefault(uf.find(("", cv.uf.find(port.node))), pname or f"{side}{idx}")
    nets, auto = {}, {}
    for (ref, pin), node in sorted(pins.items()):
        root = uf.find(node)
        name = names.get(root) or auto.setdefault(root, f"N{len(auto) + 1}")
        nets.setdefault(name, []).append(f"{ref}.{pin}")
    return nets


def partition(nets: dict) -> set[frozenset]:
    return {frozenset(v) for v in nets.values()}
