"""ASCII canvas parser: components, wires, crossings, labels, pin attachments and edge ports.

See README.md, "Canvas syntax", for the rules implemented here.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field

from .nets import global_spelling, reserved

STEP = {"N": (-1, 0), "S": (1, 0), "E": (0, 1), "W": (0, -1)}
OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}
ARMS = {
    "─": "EW",
    "-": "EW",
    "│": "NS",
    "|": "NS",
    "┌": "ES",
    "┐": "SW",
    "└": "NE",
    "┘": "NW",
    "├": "NES",
    "┤": "NSW",
    "┬": "ESW",
    "┴": "NEW",
    "┼": "NESW",
}
STRAIGHT_H, STRAIGHT_V = "─-", "│|"
BUS_CHARS = set("═║╔╗╚╝╟╢╤╧")
EMPTY = " "
RESERVED_CHARS = "."  # reserved for future use (spec 2.1)
ARROWS = {">": "E", "<": "W", "^": "N", "v": "S"}  # directional pin labels (spec 2.5)
PIN_SHORTCUTS = "+<>^"  # one-character pin labels (plus a lone v, see _scan)


def _word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


class CanvasError(ValueError):
    pass


def minimal_period(s: str) -> str:
    """Smallest p with s == s[:p] * (len(s) // p); the whole string if none (KMP failure function)."""
    fail = [0] * len(s)
    k = 0
    for i in range(1, len(s)):
        while k and s[i] != s[k]:
            k = fail[k - 1]
        if s[i] == s[k]:
            k += 1
        fail[i] = k
    p = len(s) - fail[-1]
    return s[:p] if len(s) % p == 0 else s


@dataclass
class Label:
    text: str
    row: int
    c0: int
    c1: int  # inclusive; for a 1-char shortcut c0 == c1
    shortcut: bool = False
    brace: bool = False  # {name}: component pin when adjacent, otherwise an interface
    pin_of: str | None = None  # component name when this is a pin label
    vcol: int | None = None  # column where a vertical wire passes through
    arms: int = 0  # wire arms that end on this label
    entries: list = field(
        default_factory=list
    )  # sides of the label its wires come from
    kind: str = ""  # "pin" | "global" | "local" | "port" (set after parsing)


@dataclass
class Attachment:
    side: str  # side of the component
    pos: int  # row (W/E sides) or column (N/S sides) of the attaching cell
    cell: tuple[int, int]  # the cell outside the component that attaches
    node: tuple  # union-find node of that cell
    pin_label: str | None = None


@dataclass
class Comp:
    name: str
    r0: int
    c0: int
    r1: int
    c1: int
    attachments: dict = field(default_factory=lambda: {s: [] for s in "NESW"})


@dataclass
class EdgePort:
    side: str
    pos: int
    cell: tuple[int, int]
    node: tuple
    aliases: tuple = ()  # from a {name, other, ...} label


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


class Canvas:
    """Parsed canvas. Nodes: ("w", r, c) wire cell, ("h"/"v", r, c) crossing halves,
    ("l", i) label i."""

    def __init__(self, text: str, name: str = "block"):
        self.name = name
        lines = textwrap.dedent(text).split("\n")
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            raise CanvasError(f"{name}: empty canvas")
        self.W = max(len(line) for line in lines)
        self.H = len(lines)
        self.g = [line.ljust(self.W) for line in lines]
        self.uf = _UF()
        self.labels: list[Label] = []
        self.label_at: dict[tuple[int, int], int] = {}
        self.comps: dict[str, Comp] = {}
        self.comp_at: dict[tuple[int, int], str] = {}
        self.wires: dict[tuple[int, int], str] = {}  # cell -> arms
        self.crossings: set[tuple[int, int]] = set()
        self.edge_ports: list[EdgePort] = []
        self._scan()
        self._crossings()
        self._connect()
        self._pin_labels()
        self._brace_ports()
        self._classify_labels()
        self._merge_named_nets()
        for comp in self.comps.values():
            for side, lst in comp.attachments.items():
                lst.sort(key=lambda a: a.pos)
                if len({a.pos for a in lst}) != len(lst):
                    raise CanvasError(
                        f"{name}: {comp.name} has two connections at one {side} position"
                    )
        self.edge_ports.sort(key=lambda p: ("NESW".index(p.side), p.pos))

    # --- helpers -----------------------------------------------------------
    def err(self, msg, r=None, c=None):
        where = f" at row {r}, col {c}" if r is not None else ""
        raise CanvasError(f"{self.name}: {msg}{where}")

    def inside(self, r, c):
        return 0 <= r < self.H and 0 <= c < self.W

    def ch(self, r, c):
        return self.g[r][c] if self.inside(r, c) else " "

    def _wire_node(self, r, c, arm):
        if (r, c) in self.crossings:
            return ("h", r, c) if arm in "EW" else ("v", r, c)
        return ("w", r, c)

    # --- passes ------------------------------------------------------------
    def _scan(self):
        for r, row in enumerate(self.g):
            c = 0
            while c < self.W:
                ch = row[c]
                if ch in "[{":
                    close = "]" if ch == "[" else "}"
                    end = row.find(close, c + 1)
                    if end < 0 or end == c + 1:
                        self.err(f"unterminated or empty {ch}label{close}", r, c)
                    self._add_label(row[c + 1 : end], r, c, end, brace=ch == "{")
                    c = end + 1
                    continue
                if ch in "]}":
                    self.err(f"{ch!r} without its opening bracket", r, c)
                lone_v = (
                    ch in "vV"
                    and not (c > 0 and _word_char(row[c - 1]))
                    and not (c + 1 < self.W and _word_char(row[c + 1]))
                )
                if lone_v:
                    ch = "v"  # a lone v (no letters/digits beside it) is the down arrow
                if ch in RESERVED_CHARS:
                    self.err(
                        f"{ch!r} is reserved for future use; use spaces for empty cells",
                        r,
                        c,
                    )
                if ch in PIN_SHORTCUTS or lone_v:
                    self._add_label(ch, r, c, c, shortcut=True)
                elif ch in ARMS:
                    self.wires[(r, c)] = ARMS[ch]
                elif ch in BUS_CHARS:
                    self.err(
                        f"buses are specified but not implemented yet ({ch!r})", r, c
                    )
                elif not (ch in EMPTY or ch.isalnum() or ch == "_"):
                    self.err(f"unexpected character {ch!r}", r, c)
                c += 1
        seen = set()
        for r in range(self.H):
            for c in range(self.W):
                if (r, c) in seen or (r, c) in self.label_at:
                    continue
                ch = self.g[r][c]
                if ch.isalnum() or ch == "_":
                    self._add_component(r, c, seen)

    def _add_label(self, text, r, c0, c1, shortcut=False, brace=False):
        i = len(self.labels)
        self.labels.append(Label(text, r, c0, c1, shortcut, brace))
        for c in range(c0, c1 + 1):
            self.label_at[(r, c)] = i

    def _add_component(self, r, c, seen):
        stack, cells = [(r, c)], []
        seen.add((r, c))
        while stack:
            cr, cc = stack.pop()
            cells.append((cr, cc))
            for dr, dc in STEP.values():
                nr, nc = cr + dr, cc + dc
                if (
                    (nr, nc) in seen
                    or (nr, nc) in self.label_at
                    or not self.inside(nr, nc)
                ):
                    continue
                ch = self.g[nr][nc]
                if ch.isalnum() or ch == "_":
                    seen.add((nr, nc))
                    stack.append((nr, nc))
        r0, r1 = min(x for x, _ in cells), max(x for x, _ in cells)
        c0, c1 = min(y for _, y in cells), max(y for _, y in cells)
        if len(cells) != (r1 - r0 + 1) * (c1 - c0 + 1):
            self.err(
                "component characters must form a rectangle (keep a 1-cell gap between "
                "components)",
                r0,
                c0,
            )
        rows = {self.g[x][c0 : c1 + 1] for x in range(r0, r1 + 1)}
        if len(rows) != 1:
            self.err(
                f"all rows of a component rectangle must be identical: {sorted(rows)}",
                r0,
                c0,
            )
        name = minimal_period(rows.pop())
        if name in ("v", "V"):
            self.err(
                "a component can't be named v or V (reserved for the down-arrow pin "
                "label)",
                r0,
                c0,
            )
        if name in self.comps:
            self.err(f"duplicate component {name}", r0, c0)
        self.comps[name] = Comp(name, r0, c0, r1, c1)
        for cell in cells:
            self.comp_at[cell] = name

    def _points_into(self, r, c, from_side):
        """Does the wire cell on `from_side` of (r, c) have an arm pointing at (r, c)?"""
        dr, dc = STEP[from_side]
        arms = self.wires.get((r + dr, c + dc), "")
        return OPPOSITE[from_side] in arms

    def _crossings(self):
        for r, c in list(self.wires):
            ch = self.g[r][c]
            if ch in STRAIGHT_H:
                cross = ("N", "S")
            elif ch in STRAIGHT_V:
                cross = ("W", "E")
            else:
                continue
            ins = [self._points_into(r, c, s) for s in cross]
            if all(ins):
                self.crossings.add((r, c))
                self.wires[(r, c)] = "NESW"
            elif any(ins):
                self.err(
                    "a wire ends on a straight wire; use a tee glyph (├┤┬┴) for a junction",
                    r,
                    c,
                )

    def _connect(self):
        for (r, c), arms in self.wires.items():
            for arm in arms:
                node = self._wire_node(r, c, arm)
                self.uf.find(node)
                dr, dc = STEP[arm]
                nr, nc = r + dr, c + dc
                if not self.inside(nr, nc):
                    self.edge_ports.append(
                        EdgePort(arm, r if arm in "EW" else c, (r, c), node)
                    )
                elif (nr, nc) in self.wires:
                    if OPPOSITE[arm] not in self.wires[(nr, nc)]:
                        self.err(
                            f"wire arm {arm} runs into a wire that doesn't continue it",
                            r,
                            c,
                        )
                    self.uf.union(node, self._wire_node(nr, nc, OPPOSITE[arm]))
                elif (nr, nc) in self.label_at:
                    i = self.label_at[(nr, nc)]
                    lab = self.labels[i]
                    if arm == "E" and nc != lab.c0 or arm == "W" and nc != lab.c1:
                        self.err(
                            "a horizontal wire must enter a label at its opening or closing delimiter",
                            r,
                            c,
                        )
                    if arm in "NS":
                        if lab.vcol is not None and lab.vcol != nc:
                            self.err(
                                "vertical wires through a label must share one column",
                                r,
                                c,
                            )
                        lab.vcol = nc
                    lab.arms += 1
                    lab.entries.append(OPPOSITE[arm])
                    self.uf.union(node, ("l", i))
                elif (nr, nc) in self.comp_at:
                    comp = self.comps[self.comp_at[(nr, nc)]]
                    side = OPPOSITE[arm]
                    comp.attachments[side].append(
                        Attachment(side, r if side in "EW" else c, (r, c), node)
                    )
                else:
                    self.err(f"dangling wire (arm {arm} points at an empty cell)", r, c)

    def _pin_labels(self):
        """Labels touching a component edge are pin labels: they attach and name a pin."""
        for i, lab in enumerate(self.labels):
            touches = []
            for c in range(lab.c0, lab.c1 + 1):
                for side in "NS":
                    dr, _ = STEP[side]
                    if (lab.row + dr, c) in self.comp_at:
                        touches.append((self.comp_at[(lab.row + dr, c)], side))
            for c, side in ((lab.c0 - 1, "W"), (lab.c1 + 1, "E")):
                if (lab.row, c) in self.comp_at:
                    touches.append((self.comp_at[(lab.row, c)], side))
            names = {t[0] for t in touches}
            if not names:
                continue
            if not lab.brace and not lab.shortcut:
                self.err(
                    f"[{lab.text}] touches a component: square brackets name nets; "
                    f"use {{{lab.text}}} for a pin, or add a wire between the net label and component",
                    lab.row,
                    lab.c0,
                )
            spelling = f"{{{lab.text}}}" if lab.brace else repr(lab.text)
            if len(names) > 1 or len({t[1] for t in touches}) > 1:
                self.err(
                    f"pin label {spelling} touches several component edges",
                    lab.row,
                    lab.c0,
                )
            comp = self.comps[touches[0][0]]
            direction = touches[0][1]  # where the component is, seen from the label
            side = OPPOSITE[direction]
            if lab.text in ARROWS and (ARROWS[lab.text] in "EW") != (side in "EW"):
                axis = "left or right of" if lab.text in "<>" else "above or below"
                self.err(
                    f"arrow {lab.text!r} must sit {axis} a component (it points along the "
                    "pin)",
                    lab.row,
                    lab.c0,
                )
            if lab.brace and lab.entries != [side]:
                self.err(
                    f"pin label {spelling} needs exactly one wire on the side opposite its component",
                    lab.row,
                    lab.c0,
                )
            if side in "EW":
                pos = lab.row
            else:
                if lab.vcol is None and not lab.shortcut:
                    self.err(
                        f"pin label {spelling} needs a vertical wire through it",
                        lab.row,
                        lab.c0,
                    )
                pos = lab.c0 if lab.shortcut else lab.vcol
                pos = min(max(pos, comp.c0), comp.c1)
            if not self._label_has_wire(i):
                hint = (
                    " (old-style label? use {name} for pins or [name] for nets)"
                    if lab.text in "<>"
                    else ""
                )
                self.err(
                    f"pin label {spelling} of {comp.name} is not connected to a wire"
                    + hint,
                    lab.row,
                    lab.c0,
                )
            lab.pin_of = comp.name
            cell = (
                lab.row,
                pos if side in "NS" else (lab.c1 if side == "W" else lab.c0),
            )
            comp.attachments[side].append(
                Attachment(side, pos, cell, ("l", i), lab.text)
            )

    def _brace_ports(self):
        """{name} labels are external ports: on the canvas edge, with one wire going inward."""
        for i, lab in enumerate(self.labels):
            if not lab.brace or lab.pin_of is not None:
                continue
            if lab.arms != 1:
                self.err(f"{{{lab.text}}} needs exactly one wire", lab.row, lab.c0)
            if lab.vcol is not None:
                side = "N" if lab.row == 0 else "S" if lab.row == self.H - 1 else None
                pos = lab.vcol
            else:
                left_wire = (lab.row, lab.c0 - 1) in self.wires
                side = (
                    ("E" if lab.c1 == self.W - 1 else None)
                    if left_wire
                    else ("W" if lab.c0 == 0 else None)
                )
                pos = lab.row
            if side is None:
                self.err(
                    f"{{{lab.text}}} must sit on the block edge, on the side opposite "
                    "its wire",
                    lab.row,
                    lab.c0,
                )
            lab.kind = "port"
            aliases = [a.strip() for a in lab.text.split(",")]
            if any(not a for a in aliases):
                self.err(
                    f"{{{lab.text}}}: empty alias in the comma-separated list",
                    lab.row,
                    lab.c0,
                )
            aliases = [
                "v" if a == "V" else a for a in aliases
            ]  # V is the down arrow too
            if len({a.casefold() for a in aliases}) != len(aliases):
                self.err(f"{{{lab.text}}}: an alias is listed twice", lab.row, lab.c0)
            self.edge_ports.append(
                EdgePort(side, pos, (lab.row, lab.c0), ("l", i), tuple(aliases))
            )

    def _classify_labels(self):
        for lab in self.labels:
            if lab.kind:
                continue
            if lab.pin_of is not None:
                lab.kind = "pin"
            elif lab.shortcut:
                kind = "arrow" if lab.text in ARROWS else "pin shortcut"
                self.err(
                    f"{lab.text!r} is a one-character {kind} pin label and must touch a component",
                    lab.row,
                    lab.c0,
                )
            elif lab.arms == 0:
                self.err(f"[{lab.text}] is not connected to a wire", lab.row, lab.c0)
            elif reserved(
                lab.text
            ):  # reserved names always mean the global net (spec 2.8)
                if global_spelling(lab.text) is None:
                    self.err(
                        f"[{lab.text}] is a reserved global net name; write it exactly as "
                        "registered (e.g. [GND]; [0] is not allowed)",
                        lab.row,
                        lab.c0,
                    )
                lab.kind = "global"
            elif "A" <= lab.text[0] <= "Z":
                lab.kind = "global"
            elif "a" <= lab.text[0] <= "z" or lab.text[0] == "_":
                lab.kind = "local"
            else:
                self.err(
                    f"[{lab.text}]: net names must start with an uppercase letter "
                    "(global), a lowercase letter or _ (local); leading digits are not allowed",
                    lab.row,
                    lab.c0,
                )

    def _label_has_wire(self, i):
        root = self.uf.find(("l", i))
        return any(
            self.uf.find(n) == root for n in list(self.uf.parent) if n[0] in "whv"
        )

    def _merge_named_nets(self):
        """Net labels with the same text are one net (implicit wires); pin labels are excluded."""
        by_text: dict[str, tuple] = {}
        for i, lab in enumerate(self.labels):
            if lab.pin_of is None and not lab.brace:
                node = ("l", i)
                if lab.text in by_text:
                    self.uf.union(node, by_text[lab.text])
                else:
                    by_text[lab.text] = node
        self.net_names = {self.uf.find(n): t for t, n in by_text.items()}
