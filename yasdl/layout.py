"""Grid-bag layout: canvas rows/columns -> schematic coordinates (mm, y down).

Each canvas row r gets a centreline y[r], each column c a centreline x[c]; every component
gets an origin (ox, oy). X and Y are solved independently as systems of difference
constraints (longest path, Bellman-Ford):
- rows/columns are strictly ordered (>= one grid step apart);
- consecutive occupied items in the same column (for Y) or row (for X) keep a clearance;
- a component's first attached pin on a side lies exactly on its wire's row/column, and further
  pins are aligned greedily when that stays feasible;
- pins that can't be aligned are reached by ladder jogs in the gap next to the component, and
  the component's extent grows by one track per jog on that side.
Symbols are never stretched; only wires change length.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

from .block import Atom, Block
from .kicad_lib import (
    compose,
    orient_vec,
    power_body_side,
    rot_with_pin_on,
    screen_bbox,
    to_screen,
)

GRID = 1.27
PITCH = 2.54
CHAR_W = 1.27  # label text width per character (KiCad default 1.27 mm font)


class LayoutError(ValueError):
    pass


def _up(v: float) -> float:
    return math.ceil(round(v / GRID, 6)) * GRID


def _down(v: float) -> float:
    return math.floor(round(v / GRID, 6)) * GRID


@dataclass
class Shape:
    """Placed-object geometry relative to its origin: bbox and pin points per attachment."""

    bbox: tuple  # x0, y0, x1, y1
    pins: dict  # id(attachment) -> (x, y)


@dataclass
class Result:
    bbox: tuple
    ports: list  # per canvas edge port: (x, y)
    symbols: list = field(default_factory=list)  # (path, Atom, x, y, rot, mirror)
    wires: list = field(default_factory=list)  # ((x, y), (x, y))
    labels: list = field(default_factory=list)  # (text, (x, y))

    def shape(self, block_bound) -> Shape:
        pins = {id(att): self.ports[idx] for att, idx in block_bound.pin_map}
        return Shape(self.bbox, pins)

    def oriented(self, rot: int, mirror: str | None) -> Result:
        """The whole drawing rotated/mirrored about its origin (binding-time orientation)."""
        if (rot, mirror) == (0, None):
            return self

        def orient(point):
            return tuple(
                round(value, 4) + 0.0
                for value in orient_vec(point[0], point[1], rot, mirror)
            )

        corners = [
            orient((x, y))
            for x in (self.bbox[0], self.bbox[2])
            for y in (self.bbox[1], self.bbox[3])
        ]
        return Result(
            (
                min(c[0] for c in corners),
                min(c[1] for c in corners),
                max(c[0] for c in corners),
                max(c[1] for c in corners),
            ),
            [orient(point) for point in self.ports],
            [
                (path, atom, *orient((x, y)), *compose((rot, mirror), (r, m)))
                for path, atom, x, y, r, m in self.symbols
            ],
            [(orient(start), orient(end)) for start, end in self.wires],
            [(text, orient(point), scoped) for text, point, scoped in self.labels],
        )

    def translated(self, dx, dy, prefix):
        t = lambda p: (round(p[0] + dx, 4), round(p[1] + dy, 4))  # noqa: E731
        return Result(
            (
                self.bbox[0] + dx,
                self.bbox[1] + dy,
                self.bbox[2] + dx,
                self.bbox[3] + dy,
            ),
            [t(p) for p in self.ports],
            [
                (prefix + path, a, x + dx, y + dy, r, m)
                for path, a, x, y, r, m in self.symbols
            ],
            [(t(a), t(b)) for a, b in self.wires],
            [
                (prefix + txt if scoped else txt, t(p), scoped)
                for txt, p, scoped in self.labels
            ],
        )


def symbol_extent(a: Atom, rot: int, mirror: str | None, name: str) -> tuple:
    """Symbol bbox (relative to its origin) plus room for its text, placed as in kicad_sch."""
    sym = a.symbol
    x0, y0, x1, y1 = screen_bbox(sym, rot, mirror)
    text = max(len(name), len(a.value or sym.lib_id.split(":")[1])) * CHAR_W
    if sym.is_power:
        body = power_body_side(sym, rot, mirror)
        if body in "NS":
            y0, y1 = (y0 - PITCH, y1) if body == "N" else (y0, y1 + PITCH)
            x0, x1 = min(x0, -text / 2), max(x1, text / 2)
        else:
            x0, x1 = (x0 - text - GRID, x1) if body == "W" else (x0, x1 + text + GRID)
    elif x1 - x0 > y1 - y0:  # reference above, value below
        y0, y1 = y0 - PITCH, y1 + PITCH + GRID
        x0, x1 = min(x0, (x0 + x1) / 2 - text / 2), max(x1, (x0 + x1) / 2 + text / 2)
    else:  # both to the right
        x1 += GRID + text
    return (_down(x0), _down(y0), _up(x1), _up(y1))


def _atom_shape(bound) -> Shape:
    a: Atom = bound.obj
    sym = a.symbol
    pins_by_no = {p.number: p for p in sym.pins}
    pins = {}
    for att, number in bound.pin_map:
        p = pins_by_no[number]
        pins[id(att)] = to_screen(p.x, p.y, bound.rot, bound.mirror)
    return Shape(symbol_extent(a, bound.rot, bound.mirror, bound.name), pins)


# --- difference-constraint solver ---------------------------------------------------
class _System:
    def __init__(self, n):
        self.n = n
        self.edges = []  # (i, j, w): v[j] >= v[i] + w

    def ge(self, j, i, w):
        self.edges.append((i, j, w))

    def eq(self, j, i, w):  # v[j] == v[i] + w
        self.edges += [(i, j, w), (j, i, -w)]

    def solve(self, extra=()):
        edges = self.edges + list(extra)
        dist = [0.0] * self.n
        for _ in range(self.n + 1):
            changed = False
            for i, j, w in edges:
                if dist[i] + w > dist[j] + 1e-9:
                    dist[j] = dist[i] + w
                    changed = True
            if not changed:
                return dist
        return None  # positive cycle: infeasible


# --- layout ---------------------------------------------------------------------------
class Layout:
    def __init__(self, block: Block, cache: dict | None = None):
        self.block, self.cv = block, block.canvas
        if block.unbound:
            raise LayoutError(f"{block.name}: unbound components {block.unbound}")
        self.cache = {} if cache is None else cache
        self.children: dict[str, Result] = {}
        self.shapes: dict[str, Shape] = {}
        from .atoms import POWER_NETS  # registry of global nets drawn as power symbols

        # label index -> (Atom, rot, extent): dangling global labels drawn as power symbols
        self.power = {}
        for i, lab in enumerate(self.cv.labels):
            if (
                lab.kind == "global"
                and lab.text in POWER_NETS
                and len(lab.entries) == 1
            ):
                atom = Atom(POWER_NETS[lab.text], lab.text)
                rot = rot_with_pin_on(atom.symbol, lab.entries[0])
                self.power[i] = (atom, rot, symbol_extent(atom, rot, None, ""))
        for name, b in block.bound.items():
            if isinstance(b.obj, Atom):
                self.shapes[name] = _atom_shape(b)
            else:
                key = id(b.obj)
                if key not in self.cache:
                    self.cache[key] = Layout(b.obj, self.cache).run()
                self.children[name] = self.cache[key].oriented(b.rot, b.mirror)
                self.shapes[name] = self.children[name].shape(b)

    # Items occupying the canvas, for adjacency: per cell -> ("wire"|"label"|"comp", key).
    def _item_at(self, r, c):
        cv = self.cv
        if (r, c) in cv.wires:
            return ("wire", (r, c))
        if (r, c) in cv.label_at:
            return ("label", cv.label_at[(r, c)])
        if (r, c) in cv.comp_at:
            return ("comp", cv.comp_at[(r, c)])
        return None

    def run(self) -> Result:
        jogs = {name: {s: set() for s in "NESW"} for name in self.shapes}
        self.sep = {
            "x": set(),
            "y": set(),
        }  # extra pairwise separations (spilling shapes)
        for _ in range(12):
            ys, oy = self._solve(jogs, "y")
            changed = self._find_jogs(jogs, ys, oy, "y")
            xs, ox = self._solve(jogs, "x")
            changed |= self._find_jogs(jogs, xs, ox, "x")
            changed |= self._find_overlaps(xs, ys, ox, oy, jogs)
            if not changed:
                break
        else:
            raise LayoutError(f"{self.block.name}: layout did not converge")
        ys, oy = self._solve(jogs, "y")
        return self._emit(xs, ys, ox, oy, jogs)

    # --- constraints ---------------------------------------------------------------
    def _solve(self, jogs, axis):
        cv = self.cv
        horiz = axis == "x"  # x positions are constrained along rows
        n_lines = cv.W if horiz else cv.H
        comps = sorted(self.shapes)
        var = {("line", i): i for i in range(n_lines)}
        for k, name in enumerate(comps):
            var[("comp", name)] = n_lines + k
        sys_ = _System(len(var))
        for i in range(n_lines - 1):
            sys_.ge(i + 1, i, GRID)

        def extent(item):
            """(var index, low offset, high offset) along this axis."""
            kind, key = item
            if kind == "wire":
                r, c = key
                return var[("line", c if horiz else r)], 0.0, 0.0
            if kind == "label" and key in self.power:
                lab = cv.labels[key]
                x0, y0, x1, y1 = self.power[key][2]
                if horiz:
                    return (
                        var[("line", lab.vcol if lab.vcol is not None else lab.c0)],
                        x0,
                        x1,
                    )
                return var[("line", lab.row)], y0, y1
            if kind == "label":
                lab = cv.labels[key]
                if horiz:
                    if lab.pin_of is not None:  # not drawn: just a point on the wire
                        col = lab.vcol if lab.vcol is not None else lab.c0
                        return var[("line", col)], 0.0, 0.0
                    width = _up(len(lab.text) * CHAR_W) + GRID
                    return var[("line", lab.c0)], 0.0, width
                return var[("line", lab.row)], (0.0 if lab.pin_of else -PITCH), 0.0
            shape = self.shapes[key]
            x0, y0, x1, y1 = shape.bbox
            lo, hi = (x0, x1) if horiz else (y0, y1)
            j = jogs[key]
            lo -= PITCH * len(j["W" if horiz else "N"])
            hi += PITCH * len(j["E" if horiz else "S"])
            return var[("comp", key)], lo, hi

        # Clearance between consecutive items along each line of the other axis.
        lines = range(cv.H) if horiz else range(cv.W)
        for ln in lines:
            items = []
            for k in range(cv.W if horiz else cv.H):
                r, c = (ln, k) if horiz else (k, ln)
                it = self._item_at(r, c)
                if it and (not items or items[-1][0] != it):
                    items.append((it, k))
            for (a, ka), (b, kb) in zip(items, items[1:]):
                ia, _, a_hi = extent(a)
                ib, b_lo, _ = extent(b)
                clear = PITCH
                if self._touching(a, b, ka, kb, ln, horiz):
                    clear = GRID
                sys_.ge(ib, ia, clear + a_hi - b_lo)

        # Shapes that spill beyond their own rows/columns and would overlap (see run()).
        for a, b in self.sep[axis]:
            ia, _, a_hi = extent(a)
            ib, b_lo, _ = extent(b)
            sys_.ge(ib, ia, PITCH + a_hi - b_lo)

        # Pin alignment: sides whose pins run along this axis' lines.
        aligned_sides = "NS" if horiz else "EW"
        must, maybe = [], []
        for name in comps:
            comp = cv.comps[name]
            shape = self.shapes[name]
            first = True
            for side in aligned_sides:
                for att in comp.attachments[side]:
                    px, py = shape.pins[id(att)]
                    off = px if horiz else py
                    eq = (var[("line", att.pos)], var[("comp", name)], off)
                    (must if first else maybe).append(eq)
                    first = False
            if (
                first
            ):  # no pins on this axis: centre the component between its first/last line
                lo_line, hi_line = (comp.c0, comp.c1) if horiz else (comp.r0, comp.r1)
                x0, y0, x1, y1 = shape.bbox
                mid = _down(((x0 + x1) if horiz else (y0 + y1)) / 2)
                sys_.ge(var[("comp", name)], var[("line", lo_line)], -mid)
                sys_.ge(var[("line", hi_line)], var[("comp", name)], mid)
        for line_v, comp_v, off in must:
            sys_.eq(line_v, comp_v, off)
        if sys_.solve() is None:
            raise LayoutError(f"{self.block.name}: infeasible {axis} layout")
        for line_v, comp_v, off in maybe:
            trial = [(comp_v, line_v, off), (line_v, comp_v, -off)]
            if sys_.solve(trial) is not None:
                sys_.eq(line_v, comp_v, off)
        dist = sys_.solve()
        pos = [dist[i] for i in range(n_lines)]
        origin = {name: dist[var[("comp", name)]] for name in comps}
        return pos, origin

    def _touching(self, a, b, ka, kb, ln, horiz):
        """Directly connected neighbours (a wire running into the next item) may sit closer."""
        if kb != ka + 1 or a[0] != "wire" and b[0] != "wire":
            return False
        arm = "E" if horiz else "S"
        if a[0] == "wire":
            r, c = a[1]
            return arm in self.cv.wires[(r, c)]
        r, c = b[1]
        return ("W" if horiz else "N") in self.cv.wires[(r, c)]

    def _find_overlaps(self, xs, ys, ox, oy, jogs) -> bool:
        """Separate boxes (components, net labels) that overlap physically although they sit in
        different rows/columns: in Y if their canvas rows are disjoint, else in X."""
        cv = self.cv
        boxes: list[tuple] = []
        for name, comp in cv.comps.items():
            boxes.append(
                (
                    ("comp", name),
                    (comp.r0, comp.r1),
                    (comp.c0, comp.c1),
                    self._comp_box(name, ox, oy, jogs),
                )
            )
        for i, lab in enumerate(cv.labels):
            if lab.pin_of is None:
                boxes.append(
                    (
                        ("label", i),
                        (lab.row, lab.row),
                        (lab.c0, lab.c1),
                        self._label_box(i, xs, ys),
                    )
                )
        changed = False
        for (ia, ra, ca, ba), (ib, rb, cb, bb) in itertools.combinations(boxes, 2):
            if not (
                ba[0] < bb[2] + GRID
                and bb[0] < ba[2] + GRID
                and ba[1] < bb[3] + GRID
                and bb[1] < ba[3] + GRID
            ):
                continue
            if ra[1] < rb[0] or rb[1] < ra[0]:
                pair = (ia, ib) if ra[1] < rb[0] else (ib, ia)
                axis = "y"
            elif ca[1] < cb[0] or cb[1] < ca[0]:
                pair = (ia, ib) if ca[1] < cb[0] else (ib, ia)
                axis = "x"
            else:
                continue
            if pair not in self.sep[axis]:
                self.sep[axis].add(pair)
                changed = True
        return changed

    def _find_jogs(self, jogs, pos, origin, axis):
        horiz = axis == "x"
        changed = False
        for name, comp in self.cv.comps.items():
            shape = self.shapes[name]
            for side in "NS" if horiz else "EW":
                for att in comp.attachments[side]:
                    px, py = shape.pins[id(att)]
                    want = origin[name] + (px if horiz else py)
                    if (
                        abs(pos[att.pos] - want) > 1e-6
                        and id(att) not in jogs[name][side]
                    ):
                        jogs[name][side].add(id(att))
                        changed = True
        return changed

    # --- geometry --------------------------------------------------------------------
    def _emit(self, xs, ys, ox, oy, jogs) -> Result:
        cv = self.cv
        res = Result(bbox=(0, 0, 0, 0), ports=[])
        pt = lambda r, c: (xs[c], ys[r])  # noqa: E731

        def node_point(cell):
            """One point per node: a label's point is its vertical-wire column, else its '<'."""
            if cell in cv.label_at:
                lab = cv.labels[cv.label_at[cell]]
                return (xs[lab.vcol if lab.vcol is not None else lab.c0], ys[lab.row])
            return pt(*cell)

        # Symbols and sub-blocks.
        for name, b in self.block.bound.items():
            if name in self.children:
                child = self.children[name].translated(ox[name], oy[name], f"{name}.")
                res.symbols += child.symbols
                res.wires += child.wires
                res.labels += child.labels
            else:
                res.symbols.append((name, b.obj, ox[name], oy[name], b.rot, b.mirror))

        # Wires between cells (crossings pass straight through).
        def walk(cell, arm):
            """Follow `arm` from `cell` through crossings; return the next real node cell."""
            dr, dc = {"N": (-1, 0), "S": (1, 0), "E": (0, 1), "W": (0, -1)}[arm]
            r, c = cell[0] + dr, cell[1] + dc
            while (r, c) in cv.crossings:
                r, c = r + dr, c + dc
            return (r, c)

        done = set()
        for cell, arms in cv.wires.items():
            if cell in cv.crossings:
                continue
            for arm in arms:
                nxt = walk(cell, arm)
                key = frozenset((cell, nxt))
                if key in done or not cv.inside(*nxt):
                    continue
                if nxt in cv.wires or nxt in cv.label_at:
                    done.add(key)
                    res.wires.append((node_point(cell), node_point(nxt)))

        # Pin connections, with ladder jogs where a pin is off its wire's line.
        for name, comp in cv.comps.items():
            shape = self.shapes[name]
            origin = (ox[name], oy[name])
            for side in "NESW":
                items = []
                for att in comp.attachments[side]:
                    px, py = shape.pins[id(att)]
                    cell = att.cell
                    while cell in cv.crossings:
                        cell = walk(cell, side)
                    if cell in cv.comp_at:
                        # A crossing may be the only cell between two symbols.
                        other = cv.comp_at[cell]
                        opposite = {"N": "S", "S": "N", "E": "W", "W": "E"}[side]
                        target = next(
                            a
                            for a in cv.comps[other].attachments[opposite]
                            if a.pos == att.pos
                        )
                        tx, ty = self.shapes[other].pins[id(target)]
                        wire_point = (ox[other] + tx, oy[other] + ty)
                    else:
                        wire_point = node_point(cell)
                    items.append((wire_point, (origin[0] + px, origin[1] + py)))
                res.wires += _route_side(side, items, f"{self.block.name}.{name}")

        # Edge ports.
        all_pts = [p for w in res.wires for p in w]
        boxes = [self._comp_box(n, ox, oy, jogs) for n in cv.comps]
        boxes += [
            self._label_box(i, xs, ys)
            for i, lab in enumerate(cv.labels)
            if lab.pin_of is None
        ]
        x0 = min([p[0] for p in all_pts] + [b[0] for b in boxes] + xs)
        y0 = min([p[1] for p in all_pts] + [b[1] for b in boxes] + ys)
        x1 = max([p[0] for p in all_pts] + [b[2] for b in boxes] + xs)
        y1 = max([p[1] for p in all_pts] + [b[3] for b in boxes] + ys)
        for port in cv.edge_ports:
            p = node_point(port.cell)
            edge = {"W": (x0, p[1]), "E": (x1, p[1]), "N": (p[0], y0), "S": (p[0], y1)}[
                port.side
            ]
            res.wires.append((p, edge))
            res.ports.append(edge)
        # Net labels (block-scoped: prefixed when the block is nested).
        for i, lab in enumerate(cv.labels):
            if i in self.power:  # drawn as its power symbol, pin on the label's point
                atom, rot, _ = self.power[i]
                x, y = node_point((lab.row, lab.c0))
                res.symbols.append(
                    (f"[{lab.text}]@{lab.row}.{lab.c0}", atom, x, y, rot, None)
                )
            elif lab.kind in (
                "local",
                "global",
            ):  # local names are block-scoped (prefixed)
                res.labels.append(
                    (lab.text, node_point((lab.row, lab.c0)), lab.kind == "local")
                )
        res.wires = [w for w in res.wires if w[0] != w[1]]
        res.bbox = (x0, y0, x1, y1)
        return res

    def _comp_box(self, name, ox, oy, jogs):
        x0, y0, x1, y1 = self.shapes[name].bbox
        j = jogs[name]
        return (
            ox[name] + x0 - PITCH * len(j["W"]),
            oy[name] + y0 - PITCH * len(j["N"]),
            ox[name] + x1 + PITCH * len(j["E"]),
            oy[name] + y1 + PITCH * len(j["S"]),
        )

    def _label_box(self, i, xs, ys):
        lab = self.cv.labels[i]
        if i in self.power:
            x0, y0, x1, y1 = self.power[i][2]
            x, y = xs[lab.vcol if lab.vcol is not None else lab.c0], ys[lab.row]
            return (x + x0, y + y0, x + x1, y + y1)
        return (
            xs[lab.c0],
            ys[lab.row] - PITCH,
            xs[lab.c0] + _up(len(lab.text) * CHAR_W) + GRID,
            ys[lab.row],
        )


# --- ladder routing --------------------------------------------------------------------
def _route_side(side, items, where):
    """Connect wire points to pin points on one component side without crossings.

    Each item is (wire point, pin point). Aligned items get a straight wire; the others get a
    jog on its own track in the gap between the wires and the pins.
    """
    # Normalise to "wires come from the left (small u), pins on the right"; v is across.
    fwd = {
        "W": lambda p: (p[0], p[1]),
        "E": lambda p: (-p[0], p[1]),
        "N": lambda p: (p[1], p[0]),
        "S": lambda p: (-p[1], p[0]),
    }[side]
    back = {
        "W": lambda u, v: (u, v),
        "E": lambda u, v: (-u, v),
        "N": lambda u, v: (v, u),
        "S": lambda u, v: (v, -u),
    }[side]
    norm = [(fwd(a), fwd(b)) for a, b in items]
    straight = [(a, b) for a, b in norm if abs(a[1] - b[1]) < 1e-6]
    jog = [(a, b) for a, b in norm if abs(a[1] - b[1]) >= 1e-6]
    out = [[a, b] for a, b in straight]
    if jog:
        u_pin = min(b[0] for _, b in jog)
        tracks = [round(u_pin - PITCH * (k + 1), 4) for k in range(len(jog))]
        for order in itertools.permutations(range(len(jog))):
            paths = [
                [a, (tracks[t], a[1]), (tracks[t], b[1]), b]
                for (a, b), t in zip(jog, order)
            ]
            if not any(
                _crosses(p, q) for p, q in itertools.combinations(paths + out, 2)
            ):
                out += paths
                break
        else:
            raise LayoutError(f"{where}: no crossing-free ladder for side {side}")
    segs = []
    for path in out:
        pts = [back(*p) for p in path]
        segs += [(p, q) for p, q in zip(pts, pts[1:]) if p != q]
    return segs


def _crosses(p, q):
    """Do two axis-aligned polylines intersect anywhere?"""
    for a1, a2 in zip(p, p[1:]):
        for b1, b2 in zip(q, q[1:]):
            if _seg_hit(a1, a2, b1, b2):
                return True
    return False


def _seg_hit(a1, a2, b1, b2):
    ax0, ax1 = sorted((a1[0], a2[0]))
    ay0, ay1 = sorted((a1[1], a2[1]))
    bx0, bx1 = sorted((b1[0], b2[0]))
    by0, by1 = sorted((b1[1], b2[1]))
    return (
        ax0 <= bx1 + 1e-9
        and bx0 <= ax1 + 1e-9
        and ay0 <= by1 + 1e-9
        and by0 <= ay1 + 1e-9
    )


def layout(block: Block) -> Result:
    return Layout(block).run()
