"""Blocks: a canvas plus component bindings (atoms or other blocks), and flat netlists."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .canvas import Canvas, CanvasError, _UF
from .kicad_lib import ORIENTATIONS, load, pin_side, to_screen


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

    def side_counts(self) -> dict[str, int]:
        return {s: sum(1 for p in self.ports if p[0] == s) for s in "NESW"}

    def bind(self, **more) -> Block:
        """A copy with more components bound (the unbound ones are the block's open interface)."""
        return Block(self.name, self.text, **{**self.bindings, **more})

    # --- binding -------------------------------------------------------------
    def _bind(self, comp, obj) -> Bound:
        drawn = {s: len(comp.attachments[s]) for s in "NESW"}
        if isinstance(obj, Block):
            if obj.side_counts() != drawn:
                raise YasdlError(f"{self.name}: {comp.name} is drawn with {drawn} connections, "
                                 f"block {obj.name} has ports {obj.side_counts()}")
            pin_map = []
            for s in "NESW":
                idx = [i for i, p in enumerate(obj.ports) if p[0] == s]
                pin_map += list(zip(comp.attachments[s], idx))
            return Bound(comp.name, obj, pin_map=pin_map)
        if not isinstance(obj, Atom):
            raise YasdlError(f"{self.name}: {comp.name} must be bound to an Atom or a Block")

        def mapping(rot, mirror):
            sp = obj.side_pins(rot, mirror)
            if {s: len(sp[s]) for s in "NESW"} != drawn:
                return None
            pairs = []
            for s in "NESW":
                pairs += list(zip(comp.attachments[s], sp[s]))
            for att, pin in pairs:
                if att.pin_label and not obj.matches_label(pin, att.pin_label):
                    return None
            return pairs

        labelled = any(a.pin_label for s in "NESW" for a in comp.attachments[s])
        if obj.rot is not None or obj.mirror is not None:
            options = [(obj.rot or 0, obj.mirror)]
        elif labelled:
            options = ORIENTATIONS
        else:
            options = [(0, None)] + ([o for o in ORIENTATIONS if o != (0, None)]
                                     if obj.symmetric else [])
        fits = [(o, m) for o in options if (m := mapping(*o)) is not None]
        if not fits:
            sides = {s: [p.name for p in v] for s, v in obj.side_pins(*options[0]).items()}
            raise YasdlError(f"{self.name}: {comp.name} ({obj.lib_id}) does not fit its drawing: "
                             f"drawn {drawn}, symbol sides {sides} for orientation {options[0]}"
                             + (" — give rot/mirror or label pins" if len(options) == 1 else ""))
        if labelled and not obj.symmetric:
            maps = {tuple(p.number for _, p in m) for _, m in fits}
            if len(maps) > 1:
                raise YasdlError(f"{self.name}: pin labels of {comp.name} fit several orientations; "
                                 "label another pin")
        (rot, mirror), pairs = fits[0]
        return Bound(comp.name, obj, rot, mirror, [(a, p.number) for a, p in pairs])

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
