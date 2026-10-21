"""Sketch: build a canvas programmatically (place text, wires and labels by coordinates).

Hand-typing wide canvases is error-prone; a Sketch keeps every glyph at an explicit (row, col).
    s = Sketch()
    s.text(0, 0, "{in}"); s.hline(0, 4, 9); s.text(0, 10, "R1"); s.hline(0, 12, 15)
    Block("Name", s.render(), R1=R("1k"))
"""

from __future__ import annotations


class Sketch:
    def __init__(self):
        self.cells: dict[tuple[int, int], str] = {}

    def text(self, row: int, col: int, s: str) -> Sketch:
        """Place a string left to right: component names, [labels], {ports}, glyphs."""
        for i, ch in enumerate(s):
            self.cells[(row, col + i)] = ch
        return self

    def hline(self, row: int, c0: int, c1: int, ch: str = "─") -> Sketch:
        for c in range(min(c0, c1), max(c0, c1) + 1):
            self.cells[(row, c)] = ch
        return self

    def vline(self, col: int, r0: int, r1: int, ch: str = "│") -> Sketch:
        for r in range(min(r0, r1), max(r0, r1) + 1):
            self.cells[(r, col)] = ch
        return self

    def box(self, row: int, col: int, name: str, rows: int = 1) -> Sketch:
        """A component rectangle: `name` repeated on `rows` rows (e.g. a 3-row transistor)."""
        for r in range(rows):
            self.text(row + r, col, name)
        return self

    def render(self) -> str:
        if not self.cells:
            return ""
        h = max(r for r, _ in self.cells) + 1
        w = max(c for _, c in self.cells) + 1
        rows = [[" "] * w for _ in range(h)]
        for (r, c), ch in self.cells.items():
            rows[r][c] = ch
        return "\n".join("".join(row).rstrip() for row in rows)
