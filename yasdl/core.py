"""yasdl core model: grid parsing, auto-orientation, port inference, holes and flat netlists.

Geometry (track sizes, stretching) and KiCad export are not implemented yet; this module
checks that a block is well-formed and computes its connectivity.

Conventions:
- A block is H rows x W cols of cells, written as a grid string, one whitespace-separated
  token per cell: a wire glyph, "." for an empty cell, or a binding name.
- Every connection sits on the midpoint of a cell edge, at most one per cell side.
- A binding name repeated over a rectangle of cells makes one spanned element (atoms only).
- Port index along a side: row from the top for W/E, column from the left for N/S.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, replace

SIDES = ("N", "E", "S", "W")
OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}
ROT90 = {"N": "E", "E": "S", "S": "W", "W": "N"}  # quarter turn clockwise
STEP = {"N": (-1, 0), "S": (1, 0), "E": (0, 1), "W": (0, -1)}
EMPTY = "."
# Every set of 2+ sides has exactly one glyph; a 4-way glyph is always a junction.
GLYPHS = {
    "─": "EW", "│": "NS",
    "┌": "ES", "┐": "SW", "└": "NE", "┘": "NW",
    "├": "NES", "┤": "NSW", "┬": "ESW", "┴": "NEW",
    "┼": "NESW",
}


class YasdlError(ValueError):
    pass


@dataclass(frozen=True)
class Tx:
    """Orientation: optional top/bottom mirror, then `rot` quarter turns clockwise."""

    rot: int = 0
    mirror: bool = False

    def side(self, s: str) -> str:
        if self.mirror and s in "NS":
            s = OPPOSITE[s]
        for _ in range(self.rot):
            s = ROT90[s]
        return s


# Order in which automatic orientation tries transforms when several fit.
PREFERENCE = [Tx(0), Tx(1), Tx(3), Tx(2), Tx(0, True), Tx(1, True), Tx(3, True), Tx(2, True)]


def _port_cell(side: str, idx: int, h: int, w: int) -> tuple[int, int]:
    return {"W": (idx, 0), "E": (idx, w - 1), "N": (0, idx), "S": (h - 1, idx)}[side]


def transform_ports(tx: Tx, ports, h: int, w: int):
    """Apply `tx` to ((side, idx, pin), ...) on an h x w rectangle -> (ports, h, w)."""
    out = []
    for s, i, pin in ports:
        r, c = _port_cell(s, i, h, w)
        hh, ww = h, w
        if tx.mirror:
            r = hh - 1 - r
            s = OPPOSITE[s] if s in "NS" else s
        for _ in range(tx.rot):
            r, c = c, hh - 1 - r
            hh, ww = ww, hh
            s = ROT90[s]
        out.append((s, r if s in "WE" else c, pin))
    return tuple(out), (w if tx.rot % 2 else h), (h if tx.rot % 2 else w)


@dataclass(frozen=True)
class Atom:
    """A KiCad symbol occupying h x w cells. `ports` is in the symbol's library orientation."""

    kind: str
    symbol: str
    ports: tuple
    h: int = 1
    w: int = 1
    value: str = ""
    global_net: str = ""  # power symbols: all pins join this global net
    tx: Tx | None = None  # None: orientation chosen from the neighbours

    def rot(self, k: int = 1) -> Atom:
        t = self.tx or Tx()
        return replace(self, tx=Tx((t.rot + k) % 4, t.mirror))

    def flip(self) -> Atom:
        """Mirror top/bottom (e.g. op-amp with the inverting input on top)."""
        t = self.tx or Tx()
        return replace(self, tx=Tx((-t.rot) % 4, not t.mirror))


@dataclass(frozen=True)
class Hole:
    """An inner interface cell: a placeholder for any element with `n` ports (one per side)."""

    name: str
    n: int


@dataclass
class _Placed:
    name: str | None  # binding name; None for glyphs and empty cells
    obj: object  # glyph char, EMPTY, Atom, Hole or Block
    top: int
    left: int
    h: int
    w: int
    tx: Tx | None = None
    sides: frozenset | None = None  # single-cell elements, once oriented
    cell_sides: dict | None = None  # spanned atoms: (r, c) -> sides

    def sides_at(self, r: int, c: int) -> frozenset:
        if self.cell_sides is not None:
            return self.cell_sides.get((r, c), frozenset())
        return self.sides


def _single_cell_sides(obj) -> list[str]:
    """Canonical port sides of an element that occupies one cell."""
    if isinstance(obj, Atom):
        sides = [s for s, _, _ in obj.ports]
    else:
        sides = [s for s, _ in obj.ports]
    if len(sides) != len(set(sides)):
        label = obj.kind if isinstance(obj, Atom) else obj.name
        raise YasdlError(f"{label} has 2+ ports on one side; "
                         "it cannot occupy a single cell")
    return sides


class Block:
    """A rectangular grid of cells. Holes are filled with `fill` or re-exported with `export`."""

    def __init__(self, name: str, grid: str, export=(), **bindings):
        self.name, self.grid, self.export, self.bindings = name, grid, tuple(export), bindings
        rows = [line.split() for line in grid.splitlines() if line.strip()]
        if not rows or len({len(r) for r in rows}) != 1:
            raise YasdlError(f"{name}: grid rows must all have the same number of cells")
        self.H, self.W = len(rows), len(rows[0])
        self.owner: dict[tuple[int, int], _Placed] = {}
        self.placed: list[_Placed] = []
        self._parse(rows)
        self._orient()
        self._check_edges()
        self.ports = sorted(
            (s, r if s in "WE" else c)
            for (r, c, s) in self.conns
            if not self._inside(r + STEP[s][0], c + STEP[s][1])
        )
        self._collect_holes()

    # --- construction -------------------------------------------------------
    def _inside(self, r: int, c: int) -> bool:
        return 0 <= r < self.H and 0 <= c < self.W

    def _parse(self, rows):
        regions: dict[str, list[tuple[int, int]]] = {}
        for r, row in enumerate(rows):
            for c, tok in enumerate(row):
                if tok in GLYPHS or tok == EMPTY:
                    p = _Placed(None, tok, r, c, 1, 1, sides=frozenset(GLYPHS.get(tok, "")))
                    self.placed.append(p)
                    self.owner[(r, c)] = p
                elif tok in self.bindings:
                    regions.setdefault(tok, []).append((r, c))
                else:
                    raise YasdlError(f"{self.name}: unknown token {tok!r} at row {r}, col {c}")
        for tok, cells in regions.items():
            obj = self.bindings[tok]
            r0, c0 = min(r for r, _ in cells), min(c for _, c in cells)
            h = max(r for r, _ in cells) - r0 + 1
            w = max(c for _, c in cells) - c0 + 1
            if len(cells) != h * w:
                raise YasdlError(f"{self.name}: {tok} must cover a rectangle of cells")
            p = _Placed(tok, obj, r0, c0, h, w)
            if h * w > 1:
                if not isinstance(obj, Atom):
                    raise YasdlError(f"{self.name}: only atoms may span cells ({tok})")
                ports, ah, aw = transform_ports(obj.tx or Tx(), obj.ports, obj.h, obj.w)
                if (ah, aw) != (h, w):
                    raise YasdlError(f"{self.name}: {tok} needs {ah}x{aw} cells, got {h}x{w}")
                p.tx = obj.tx or Tx()
                p.cell_sides = {}
                for s, i, _ in ports:
                    rc = _port_cell(s, i, h, w)
                    cell = (r0 + rc[0], c0 + rc[1])
                    p.cell_sides[cell] = p.cell_sides.get(cell, frozenset()) | {s}
            elif isinstance(obj, Atom) and obj.h * obj.w > 1:
                raise YasdlError(f"{self.name}: {tok} needs {obj.h}x{obj.w} cells")
            self.placed.append(p)
            for cell in cells:
                self.owner[cell] = p

    def _candidates(self, p: _Placed):
        """(sides, tx) options for an unoriented single-cell element, in preference order."""
        if isinstance(p.obj, Hole):
            return [(frozenset(c), None) for c in itertools.combinations(SIDES, p.obj.n)]
        canon = _single_cell_sides(p.obj)
        txs = [p.obj.tx] if isinstance(p.obj, Atom) and p.obj.tx else PREFERENCE
        seen, out = set(), []
        for tx in txs:
            sides = frozenset(tx.side(s) for s in canon)
            if sides not in seen:
                seen.add(sides)
                out.append((sides, tx))
        return out

    def _fits(self, p: _Placed):
        req = {}
        for s in SIDES:
            nr, nc = p.top + STEP[s][0], p.left + STEP[s][1]
            if not self._inside(nr, nc):
                continue  # block boundary: either way (becomes an outer port)
            other = self.owner[(nr, nc)]
            if other.sides is None and other.cell_sides is None:
                continue  # neighbour not oriented yet
            req[s] = OPPOSITE[s] in other.sides_at(nr, nc)
        fits = [f for f in self._candidates(p) if all((s in f[0]) == v for s, v in req.items())]
        if not fits:
            raise YasdlError(f"{self.name}: no orientation of {p.name} matches its neighbours {req}")
        return fits

    def _inward(self, p: _Placed, sides) -> int:
        """Number of `sides` facing an in-grid neighbour that is, or may become, connected."""
        n = 0
        for s in sides:
            nr, nc = p.top + STEP[s][0], p.left + STEP[s][1]
            if self._inside(nr, nc):
                other = self.owner[(nr, nc)]
                if other.sides is None and other.cell_sides is None:
                    n += 1
                elif OPPOSITE[s] in other.sides_at(nr, nc):
                    n += 1
        return n

    def _orient(self):
        todo = [p for p in self.placed if p.sides is None and p.cell_sides is None]
        while todo:
            progress = True
            while progress:  # propagate forced choices
                progress = False
                for p in list(todo):
                    fits = self._fits(p)
                    if len({f[0] for f in fits}) == 1:
                        p.sides, p.tx = fits[0]
                        todo.remove(p)
                        progress = True
            if todo:  # free choice: connect to as many neighbours as possible, then propagate
                p = todo.pop(0)
                fits = self._fits(p)
                p.sides, p.tx = max(fits, key=lambda f: self._inward(p, f[0]))
        self.conns = {(r, c, s) for (r, c), p in self.owner.items() for s in p.sides_at(r, c)}

    def _check_edges(self):
        for r, c, s in self.conns:
            nr, nc = r + STEP[s][0], c + STEP[s][1]
            if self._inside(nr, nc) and self.owner[(nr, nc)] is not self.owner[(r, c)]:
                if (nr, nc, OPPOSITE[s]) not in self.conns:
                    a = self.owner[(r, c)].name or self.owner[(r, c)].obj
                    b = self.owner[(nr, nc)].name or self.owner[(nr, nc)].obj
                    raise YasdlError(f"{self.name}: dangling connection from {a} (row {r}, col {c}) "
                                     f"side {s} into {b}")

    def _collect_holes(self):
        own = [n for n, o in self.bindings.items() if isinstance(o, Hole)]
        for n, o in self.bindings.items():
            if isinstance(o, Block):
                for h in o.holes:
                    if f"{n}.{h}" not in self.export:
                        raise YasdlError(f"{self.name}: inner hole {n}.{h} is neither filled "
                                         "nor exported")
        self.holes = own + list(self.export)

    # --- composition --------------------------------------------------------
    def fill(self, mapping: dict | None = None, **contents) -> Block:
        """Return a copy with holes filled; keys may be dotted paths into sub-blocks."""
        contents = {**(mapping or {}), **contents}
        bindings, export = dict(self.bindings), list(self.export)
        for key, content in contents.items():
            head, _, rest = key.partition(".")
            if head not in bindings:
                raise YasdlError(f"{self.name}: no binding {head!r}")
            if rest:
                bindings[head] = bindings[head].fill({rest: content})
                if key in export:
                    export.remove(key)
                continue
            hole = bindings[head]
            if not isinstance(hole, Hole):
                raise YasdlError(f"{self.name}: {head} is not a hole")
            n = len(content.ports)
            if n != hole.n:
                raise YasdlError(f"{self.name}: hole {head} takes {hole.n} ports, got {n}")
            bindings[head] = content
        return Block(self.name, self.grid, export=export, **bindings)

    def __repr__(self):
        return f"Block({self.name}, {self.H}x{self.W}, ports={self.ports}, holes={self.holes})"


# --- flat netlist --------------------------------------------------------------
class _UF:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        self.parent[self.find(a)] = self.find(b)


def _flatten(block: Block, prefix: str, port_nodes: dict, uf: _UF, pins: dict):
    def node(r, c, s):
        nr, nc = r + STEP[s][0], c + STEP[s][1]
        if not block._inside(nr, nc):
            key = (s, r if s in "WE" else c)
            return port_nodes.setdefault(key, ("port", prefix, key))
        if s in "WN":
            return (prefix, nr, nc, OPPOSITE[s])
        return (prefix, r, c, s)

    for p in block.placed:
        if p.name is None:  # glyph: all its sides are one net
            nodes = [node(p.top, p.left, s) for s in p.sides]
            for a in nodes[1:]:
                uf.union(a, nodes[0])
        elif isinstance(p.obj, Hole):
            raise YasdlError(f"{prefix}{p.name}: unfilled hole")
        elif isinstance(p.obj, Atom):
            if p.cell_sides is not None:
                ports, _, _ = transform_ports(p.tx, p.obj.ports, p.obj.h, p.obj.w)
            else:
                ports = tuple((p.tx.side(s), i, pin) for s, i, pin in p.obj.ports)
            for s, i, pin in ports:
                rc = _port_cell(s, i, p.h, p.w)
                n = node(p.top + rc[0], p.left + rc[1], s)
                pins[(prefix + p.name, pin)] = n
                if p.obj.global_net:
                    uf.union(n, ("global", p.obj.global_net))
        else:  # sub-block in a single cell
            child_nodes = {(s, i): node(p.top, p.left, p.tx.side(s)) for s, i in p.obj.ports}
            _flatten(p.obj, f"{prefix}{p.name}.", child_nodes, uf, pins)


def netlist(block: Block) -> dict[str, list[str]]:
    """Flat netlist {net name: sorted ["ref.pin", ...]}. Power nets keep their names."""
    if block.holes:
        raise YasdlError(f"{block.name}: unfilled holes {block.holes}")
    uf, pins, ports = _UF(), {}, {}
    _flatten(block, "", ports, uf, pins)
    names = {uf.find(n): f"{block.name}.{s}{i}" for (s, i), n in ports.items()}
    for key in list(uf.parent):
        if key[0] == "global":
            names[uf.find(key)] = key[1]
    nets: dict[str, list[str]] = {}
    unnamed = {}
    for (ref, pin), n in sorted(pins.items()):
        root = uf.find(n)
        name = names.get(root) or unnamed.setdefault(root, f"N{len(unnamed) + 1}")
        nets.setdefault(name, []).append(f"{ref}.{pin}")
    return nets
