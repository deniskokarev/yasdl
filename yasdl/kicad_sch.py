"""Write KiCad 9 schematics and read them back through kicad-cli."""

from __future__ import annotations

import subprocess
import tempfile
import uuid as _uuid
from pathlib import Path

from .kicad_lib import KICAD_CLI, load, orient_vec, screen_bbox
from .sexp import Sym, dumps, find, find_all, parse

GRID = 1.27  # KiCad's default schematic grid (50 mil)


def _uid() -> str:
    return str(_uuid.uuid4())


def snap(v: float) -> float:
    return round(round(v / GRID) * GRID, 4)


def _num(v: float) -> Sym:
    v = round(v, 4)
    return Sym(str(int(v)) if v == int(v) else repr(v))


def _effects(hide: bool = False, justify: str | None = None):
    e = [Sym("effects"), [Sym("font"), [Sym("size"), _num(1.27), _num(1.27)]]]
    if justify:
        e.append([Sym("justify"), *[Sym(j) for j in justify.split()]])
    if hide:
        e.append([Sym("hide"), Sym("yes")])
    return e


class Schematic:
    def __init__(self, title: str = "yasdl"):
        self.title = title
        self.uuid = _uid()
        self.symbols, self.items, self.lib_ids = [], [], []
        self._pwr = 0

    def add_symbol(self, lib_id: str, ref: str, value: str, x: float, y: float,
                   rot: int = 0, mirror: str | None = None, fields: dict | None = None,
                   helper: bool = False):
        """helper: an ERC helper (test point, power flag): hidden fields, not in BOM/simulation."""
        sym = load(lib_id)
        if lib_id not in self.lib_ids:
            self.lib_ids.append(lib_id)
        if sym.is_power:
            self._pwr += 1
            ref = f"#PWR{self._pwr:03d}"
        node = [Sym("symbol"), [Sym("lib_id"), lib_id], [Sym("at"), _num(x), _num(y), _num(rot)]]
        if mirror:
            node.append([Sym("mirror"), Sym(mirror)])
        node += [[Sym("unit"), _num(1)], [Sym("exclude_from_sim"), Sym("yes" if helper else "no")],
                 [Sym("in_bom"), Sym("no" if helper else "yes")], [Sym("on_board"), Sym("yes")],
                 [Sym("dnp"), Sym("no")], [Sym("uuid"), _uid()]]
        props = {"Reference": ref, "Value": value or lib_id.split(":")[1],
                 "Footprint": "", "Datasheet": "", **(fields or {})}
        x0, y0, x1, y1 = screen_bbox(sym, rot, mirror)
        if sym.is_power:  # value text beyond the symbol, away from the pin
            below = sym.pins and sym.pins[0].side == "N"
            spots = {"Value": (x, y + (y1 + 1.27 if below else y0 - 1.27), "center")}
        elif x1 - x0 > y1 - y0:  # wide: reference above, value below
            spots = {"Reference": (x + (x0 + x1) / 2, y + y0 - 1.27, "center"),
                     "Value": (x + (x0 + x1) / 2, y + y1 + 2.54, "center")}
        else:  # tall: both to the right
            spots = {"Reference": (x + x1 + 1.27, y - 0.635, "left"),
                     "Value": (x + x1 + 1.27, y + 1.905, "left")}
        if helper:
            spots = {}
        field_angle = rot % 180  # cancels the symbol rotation: text stays horizontal
        # KiCad keeps text readable: if the symbol transform turns the text direction to point
        # left, it swaps left/right justification. Pre-swap so the text lands where intended.
        tx, _ = orient_vec(1.0 if field_angle == 0 else 0.0, 0.0 if field_angle == 0 else -1.0,
                           rot, mirror)
        swap = {"left": "right", "right": "left"} if tx < -0.5 else {}
        for k, v in props.items():
            hide = k not in spots
            fx, fy, just = spots.get(k, (x, y, "center"))
            just = swap.get(just, just)
            node.append([Sym("property"), k, str(v),
                         [Sym("at"), _num(snap(fx)), _num(snap(fy)), _num(field_angle)],
                         _effects(hide=hide, justify=None if just == "center" else just)])
        for p in sym.pins:
            node.append([Sym("pin"), p.number, [Sym("uuid"), _uid()]])
        node.append([Sym("instances"), [Sym("project"), self.title,
                     [Sym("path"), f"/{self.uuid}", [Sym("reference"), ref], [Sym("unit"), _num(1)]]]])
        self.symbols.append(node)
        return ref

    def add_wire(self, a, b):
        if a == b:
            return
        self.items.append([Sym("wire"), [Sym("pts"), [Sym("xy"), _num(a[0]), _num(a[1])],
                                         [Sym("xy"), _num(b[0]), _num(b[1])]],
                           [Sym("stroke"), [Sym("width"), _num(0)], [Sym("type"), Sym("default")]],
                           [Sym("uuid"), _uid()]])

    def add_junction(self, p):
        self.items.append([Sym("junction"), [Sym("at"), _num(p[0]), _num(p[1])],
                           [Sym("diameter"), _num(0)], [Sym("color"), _num(0), _num(0), _num(0), _num(0)],
                           [Sym("uuid"), _uid()]])

    def add_label(self, name: str, p, angle: int = 0):
        justify = {0: "left bottom", 180: "right bottom", 90: "left bottom", 270: "right bottom"}[angle]
        self.items.append([Sym("label"), name, [Sym("at"), _num(p[0]), _num(p[1]), _num(angle)],
                           _effects(justify=justify), [Sym("uuid"), _uid()]])

    def to_sexp(self):
        libs = [Sym("lib_symbols")]
        for lib_id in self.lib_ids:
            d = list(load(lib_id).sexp)
            d[1] = lib_id  # embedded copies are named with the full lib_id
            libs.append(d)
        return [Sym("kicad_sch"), [Sym("version"), Sym("20250114")], [Sym("generator"), "yasdl"],
                [Sym("generator_version"), "9.0"], [Sym("uuid"), self.uuid], [Sym("paper"), "A4"],
                libs, *self.items, *self.symbols,
                [Sym("sheet_instances"), [Sym("path"), "/", [Sym("page"), "1"]]],
                [Sym("embedded_fonts"), Sym("no")]]

    def save(self, path) -> Path:
        path = Path(path)
        path.write_text(dumps(self.to_sexp()) + "\n")
        return path


def export_netlist(sch_path) -> dict[str, set[tuple[str, str]]]:
    """Run kicad-cli and return {net name: {(ref, pin), ...}} (single-pin nets included)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "net.net"
        subprocess.run([str(KICAD_CLI), "sch", "export", "netlist", "--format", "kicadsexpr",
                        "-o", str(out), str(sch_path)], check=True, capture_output=True, text=True)
        root = parse(out.read_text())
    nets = {}
    for net in find_all(find(root, "nets"), "net"):
        name = str(find(net, "name")[1])
        nets[name] = {(str(find(n, "ref")[1]), str(find(n, "pin")[1])) for n in find_all(net, "node")}
    return nets


def export_svg(sch_path, out_dir) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(KICAD_CLI), "sch", "export", "svg", "--exclude-drawing-sheet",
                    "-o", str(out_dir), str(sch_path)], check=True, capture_output=True, text=True)
    return out_dir / (Path(sch_path).stem + ".svg")


def run_erc(sch_path) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "erc.rpt"
        subprocess.run([str(KICAD_CLI), "sch", "erc", "--severity-all", "-o", str(out), str(sch_path)],
                       capture_output=True, text=True)
        return out.read_text() if out.exists() else ""
