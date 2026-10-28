"""Sketch: build a canvas programmatically (place text, wires and labels by coordinates).

Hand-typing wide canvases is error-prone; a Sketch keeps every glyph at an explicit (row, col).
    s = Sketch()
    s.text(0, 0, "{in}").hline(0, 4, 9).text(0, 10, "R1").hline(0, 12, 15)
    s.wire([(2, 0), (2, 6), (5, 6)])        # a route: corner glyphs are generated
    Block("Name", s.render(), R1=R("1k"))

Every operation is checked as a whole before anything is written (spec 7). It may not
overwrite existing content: text, labels, components, wires, elbows, tees or junctions, not even
with the same glyph. The one permitted overlap is a clean 90-degree crossing of a straight
horizontal and a straight vertical wire, both continuing through the cell; the existing glyph
stays on top and the two nets stay separate. Each operation declares how many crossings it
creates with `cross=N` (default 0); a different count is an error. A wire may not end against
the side of another wire (an implied T): place the junction explicitly with `junction()` in
an empty cell and let the wires meet it. A failed operation leaves the canvas unchanged.
"""

from __future__ import annotations

from .canvas import ARMS, STEP, OPPOSITE

_GLYPH = {
    frozenset("EW"): "─",
    frozenset("NS"): "│",
    frozenset("ES"): "┌",
    frozenset("SW"): "┐",
    frozenset("NE"): "└",
    frozenset("NW"): "┘",
    frozenset("NES"): "├",
    frozenset("NSW"): "┤",
    frozenset("ESW"): "┬",
    frozenset("NEW"): "┴",
    frozenset("NESW"): "┼",
}
_STRAIGHT = {"─": "EW", "-": "EW", "│": "NS", "|": "NS"}


class SketchError(ValueError):
    pass


class CrossingSet(frozenset):
    """Immutable crossing coordinates; equality with an integer compares the count."""
    def __eq__(self, other):
        return len(self) == other if isinstance(other, int) else super().__eq__(other)

    def __ne__(self, other):
        return not self == other

    def __int__(self):
        return len(self)

    __hash__ = None


class Sketch:
    def __init__(self):
        self.cells: dict[tuple[int, int], str] = {}
        self.crossing_cells: set[tuple[int, int]] = set()
        self.origin = {}

    @property
    def crossings(self) -> CrossingSet:
        """Number of deliberate wire crossings drawn so far."""
        return CrossingSet(self.crossing_cells)

    @property
    def crossing_count(self):
        return len(self.crossing_cells)

    # --- primitives ------------------------------------------------------------------
    def text(self, row: int, col: int, s: str) -> Sketch:
        """Place a string left to right: component names, [labels], {ports}, glyphs. Spaces
        are transparent (they leave the cell as it is)."""
        plan = {(row, col + i): ch for i, ch in enumerate(s) if ch != " "}
        self._commit(f"text({row}, {col}, {s!r})", plan, set(), 0)
        return self

    def box(self, row: int, col: int, name: str, rows: int = 1) -> Sketch:
        """A component rectangle: `name` repeated on `rows` rows (e.g. a 3-row transistor)."""
        plan = {(row + r, col + i): ch for r in range(rows) for i, ch in enumerate(name)}
        self._commit(f"box({row}, {col}, {name!r}, rows={rows})", plan, set(), 0)
        return self

    def hline(self, row: int, c0: int, c1: int, ch: str = "─", cross: int = 0) -> Sketch:
        """A straight horizontal wire over columns c0..c1 (inclusive)."""
        cells = [(row, c) for c in range(min(c0, c1), max(c0, c1) + 1)]
        what = f"hline({row}, {c0}, {c1})"
        self._straight(what, cells, "EW", ch, cross)
        return self

    def vline(self, col: int, r0: int, r1: int, ch: str = "│", cross: int = 0) -> Sketch:
        """A straight vertical wire over rows r0..r1 (inclusive)."""
        cells = [(r, col) for r in range(min(r0, r1), max(r0, r1) + 1)]
        what = f"vline({col}, {r0}, {r1})"
        self._straight(what, cells, "NS", ch, cross)
        return self

    def wire(self, points, cross: int = 0) -> Sketch:
        """A wire along orthogonal segments through (row, col) points, e.g.
        `wire([(0, 0), (0, 6), (3, 6)])`: a horizontal run, a ┐ elbow at (0, 6), then down.
        A free end cell continues straight in its segment's direction. An end point may
        instead be an anchor: a cell holding a label, port or component character, or a
        junction with an arm pointing into the route. The anchor is not drawn; the route
        attaches to it, so `wire([(4, 18), (4, 17), (7, 17)])` from a `{b}` at (4, 18)
        draws a ┌ at (4, 17)."""
        pts = [tuple(p) for p in points]
        what = f"wire({pts})"
        if len(pts) < 2:
            raise SketchError(f"{what}: a route needs at least two points")
        path = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            if a == b:
                raise SketchError(f"Sketch.{what}: repeated point {a}")
            if a[0] != b[0] and a[1] != b[1]:
                raise SketchError(f"Sketch.{what}: {a} -> {b} is diagonal")
            dr = (b[0] > a[0]) - (b[0] < a[0])
            dc = (b[1] > a[1]) - (b[1] < a[1])
            if len(path) > 1 and (dr, dc) == (path[-2][0] - a[0], path[-2][1] - a[1]):
                raise SketchError(f"Sketch.{what}: the route reverses at {a}")
            r, c = a
            while (r, c) != b:
                r, c = r + dr, c + dc
                path.append((r, c))
        anchors = set()
        for end, nxt in ((path[0], path[1]), (path[-1], path[-2])):
            old = self.cells.get(end)
            if old is None:
                continue
            arms = ARMS.get(old)
            if arms is None or (_direction(end, nxt) in arms and end not in self.crossing_cells
                                and old not in _STRAIGHT):
                anchors.add(end)
        plan, crossing = {}, set()
        for i, cell in enumerate(path):
            if cell in anchors:
                continue
            arms = set()
            if i > 0:
                arms.add(_direction(cell, path[i - 1]))
            if i + 1 < len(path):
                arms.add(_direction(cell, path[i + 1]))
            if len(arms) == 1:  # an end: continue straight
                arms.add(OPPOSITE[next(iter(arms))])
            glyph = _GLYPH[frozenset(arms)]
            if cell in plan:  # the route crosses itself
                if i in (0, len(path) - 1) or cell == path[0]:
                    raise SketchError(f"Sketch.{what}: the route visits {cell} twice at an endpoint")
                if {plan[cell], glyph} != {"─", "│"} or cell in crossing:
                    raise SketchError(
                        f"{what}: the route overlaps itself at row {cell[0]}, col {cell[1]}"
                    )
                crossing.add(cell)
                continue
            plan[cell] = glyph
        inner = [c for c in path if c not in anchors]
        if not inner:
            raise SketchError(f"{what}: nothing to draw between the anchors")
        self._commit(what, plan, crossing, cross, ends={inner[0], inner[-1]})
        return self

    def junction(self, row: int, col: int, arms: str | None = None) -> Sketch:
        """An explicit junction in an empty cell, joining the wires that point at it
        (three: a tee ├ ┤ ┬ ┴; four: ┼)."""
        inferred = {
            side
            for side, (dr, dc) in STEP.items()
            if OPPOSITE[side] in ARMS.get(self.cells.get((row + dr, col + dc), ""), "")
        }
        what = f"junction({row}, {col})"
        if arms is not None:
            selected = set(arms.upper())
            if len(selected) != len(arms) or len(selected) not in (3, 4) or selected - set('NESW'):
                raise SketchError(f"{what}: a junction joins three or four distinct sides")
            self.text(row, col, _GLYPH[frozenset(selected)])
            return self
        arms = inferred
        if len(arms) < 3:
            raise SketchError(
                f"{what}: only {len(arms)} wire(s) point at this cell ({''.join(sorted(arms))}); "
                "a junction joins three or four"
            )
        self._commit(what, {(row, col): _GLYPH[frozenset(arms)]}, set(), 0)
        return self

    # --- checking --------------------------------------------------------------------
    def _straight(self, what, cells, axis, ch, cross):
        if ch not in _STRAIGHT or _STRAIGHT[ch] != axis:
            raise SketchError(f"{what}: {ch!r} is not a straight {axis} wire glyph")
        plan = {cell: ch for cell in cells}
        self._commit(what, plan, set(), cross, ends={cells[0], cells[-1]})

    def _commit(self, what, plan, crossing, cross, ends=None):
        """Validate the whole operation, then write it (or raise with nothing written).
        ends: the end cells of a wire operation (None for text)."""
        route = ends is not None
        ends = ends or set()
        for cell in plan:
            if cell[0] < 0 or cell[1] < 0:
                raise SketchError(f"{what}: negative coordinate {cell}")
        for cell, glyph in list(plan.items()):
            old = self.cells.get(cell)
            if old is None:
                continue
            new_arms = _STRAIGHT.get(glyph)
            old_arms = _STRAIGHT.get(old)
            clean = (
                route
                and new_arms is not None
                and old_arms is not None
                and new_arms != old_arms
                and cell not in self.crossing_cells
                and cell not in ends
            )
            if not clean:
                kind = "crossing" if cell in self.crossing_cells else repr(old)
                reason = (
                    "a wire may not end or turn on another wire"
                    if route and old_arms is not None and new_arms != old_arms
                    else "drawing may not overwrite existing content"
                )
                detail = ('existing crossing already uses both axes' if cell in self.crossing_cells else
                          'text never overwrites; a component never overwrites' if not route else
                          'wires overlap along the same axis' if old_arms == new_arms and old_arms else
                          'continues on both sides' if old_arms else
                          'an elbow, tee or junction is never crossed' if old in ARMS else
                          'components, labels or text are never overwritten')
                raise SketchError(
                    f"Sketch.{what}: row {cell[0]}, col {cell[1]} already holds {kind}; {reason}; {detail}. "
                    + ('text never overwrites. ' if not route else '') + "Nothing was drawn.\n"
                    f"cell (row {cell[0]}, col {cell[1]}) already holds {kind} from {self.origin.get(cell)}"
                    + (
                        " (cross only straight wires, at 90 degrees, both continuing)"
                        if route
                        else ""
                    )
                )
            crossing.add(cell)
            del plan[cell]  # the existing glyph stays on top
        # Wire arms must agree with existing neighbouring wires (no implied T, no dead ends
        # against a wire's side).
        view = dict(self.cells)
        view.update(plan)
        crossed = crossing | self.crossing_cells
        for cell, glyph in plan.items():
            arms = "NESW" if cell in crossing else ARMS.get(glyph)
            if arms is None:
                continue
            for side, (dr, dc) in STEP.items():
                nb = (cell[0] + dr, cell[1] + dc)
                nb_arms = "NESW" if nb in crossed else ARMS.get(view.get(nb, ""), None)
                if nb_arms is None:
                    continue
                into_new = OPPOSITE[side] in nb_arms
                out_of_new = side in arms
                if into_new != out_of_new:
                    who = (
                        f"the wire at row {nb[0]}, col {nb[1]} ends against it"
                        if into_new
                        else f"it ends against the wire at row {nb[0]}, col {nb[1]}"
                    )
                    raise SketchError(
                        f"{what}: {glyph!r} at row {cell[0]}, col {cell[1]}: {who} "
                        "(an implied T); leave the cell empty and place junction() there"
                    )
        if len(crossing) != cross:
            at = ", ".join(f"({r}, {c})" for r, c in sorted(crossing)) or "none"
            raise SketchError(
                f"{what}: creates {len(crossing)} crossing(s) at {at}, expected cross={cross}; "
                f"creates {len(crossing)} crossing(s) at {sorted(crossing)}, but cross={cross} was given"
            )
        self.cells.update(plan)
        self.origin.update({cell: what for cell in plan})
        self.crossing_cells |= crossing

    def render(self) -> str:
        if not self.cells:
            return ""
        h = max(r for r, _ in self.cells) + 1
        w = max(c for _, c in self.cells) + 1
        rows = [[" "] * w for _ in range(h)]
        for (r, c), ch in self.cells.items():
            rows[r][c] = ch
        return "\n".join("".join(row).rstrip() for row in rows)


def _direction(a, b) -> str:
    return {(-1, 0): "N", (1, 0): "S", (0, 1): "E", (0, -1): "W"}[(b[0] - a[0], b[1] - a[1])]
