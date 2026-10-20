"""KiCad 9 symbol library access: pins, body extents and orientation transforms.

Coordinates:
- library symbols use y-up; schematics use y-down (mm);
- an instance placed at (X, Y) with angle `rot` (degrees, counterclockwise on screen) and
  optional mirror ("x": flip top/bottom, "y": flip left/right) maps a library point (x, y) to
  (X, Y) + mirror(rotate(x, -y)). Rotation is applied first, then the mirror (this matches
  eeschema; tests check it through a kicad-cli netlist round trip).
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .sexp import find, find_all, parse

def _resolve_kicad_layout(root: Path) -> tuple[Path, Path, Path]:
    """Return CLI, symbol, and template paths for prefix or macOS app layouts."""
    root = Path(root).expanduser()
    app = root if root.suffix == ".app" else root / "KiCad.app"
    contents = app / "Contents"
    macos_cli = contents / "MacOS" / "kicad-cli"
    if macos_cli.exists():
        shared = contents / "SharedSupport"
        return macos_cli, shared / "symbols", shared / "template"
    shared = root / "share" / "kicad"
    return root / "bin" / "kicad-cli", shared / "symbols", shared / "template"


KICAD_ROOT = Path(os.environ.get("YASDL_KICAD", Path.home() / "KiCad9"))
KICAD_CLI, SYMBOL_DIR, TEMPLATE_DIR = _resolve_kicad_layout(KICAD_ROOT)

# Library pin angle -> side of the symbol the pin sits on (pin points towards the body).
_ANGLE_SIDE = {0: "W", 180: "E", 270: "N", 90: "S"}


@dataclass(frozen=True)
class LibPin:
    number: str
    name: str
    x: float  # connection point, library coordinates (y up)
    y: float
    side: str  # N/E/S/W in library orientation
    etype: str = "passive"  # electrical type: input, output, passive, power_in, power_out, ...


@dataclass(frozen=True)
class LibSymbol:
    lib_id: str
    sexp: list  # the (symbol ...) definition, embedded into schematics' lib_symbols
    pins: tuple[LibPin, ...]
    bbox: tuple[float, float, float, float]  # xmin, ymin, xmax, ymax (library coords)
    is_power: bool


@lru_cache(maxsize=None)
def _library(lib: str):
    return parse((SYMBOL_DIR / f"{lib}.kicad_sym").read_text())


@lru_cache(maxsize=None)
def load(lib_id: str) -> LibSymbol:
    lib, name = lib_id.split(":", 1)
    root = _library(lib)
    sym = next((s for s in find_all(root, "symbol") if s[1] == name), None)
    if sym is None:
        raise KeyError(f"symbol {lib_id} not found in {SYMBOL_DIR}")
    if find(sym, "extends"):
        raise NotImplementedError(f"{lib_id}: symbols using (extends) are not supported yet")
    pins, xs, ys = [], [], []
    for unit in find_all(sym, "symbol"):
        _, unit_no, style = str(unit[1]).rsplit("_", 2)
        if int(unit_no) not in (0, 1) or int(style) not in (0, 1):  # unit 1, normal body style
            continue
        for item in unit:
            if not isinstance(item, list):
                continue
            kind = item[0]
            if kind == "pin":
                at = find(item, "at")
                x, y, ang = float(at[1]), float(at[2]), int(float(at[3])) % 360
                length = float(find(item, "length")[1])
                pins.append(LibPin(str(find(item, "number")[1]), str(find(item, "name")[1]),
                                   x, y, _ANGLE_SIDE[ang], str(item[1])))
                dx, dy = round(math.cos(math.radians(ang))), round(math.sin(math.radians(ang)))
                xs += [x, x + dx * length]
                ys += [y, y + dy * length]
            elif kind in ("rectangle", "polyline", "arc", "circle", "bezier"):
                pts = []
                for k in ("start", "end", "mid", "center"):
                    v = find(item, k)
                    if v:
                        pts.append((float(v[1]), float(v[2])))
                p = find(item, "pts")
                if p:
                    pts += [(float(xy[1]), float(xy[2])) for xy in find_all(p, "xy")]
                r = find(item, "radius")
                if r and find(item, "center"):
                    cx, cy = pts[-1]
                    rad = float(r[1])
                    pts += [(cx - rad, cy - rad), (cx + rad, cy + rad)]
                xs += [q[0] for q in pts]
                ys += [q[1] for q in pts]
    is_power = find(sym, "power") is not None
    return LibSymbol(lib_id, sym, tuple(pins), (min(xs), min(ys), max(xs), max(ys)), is_power)


# --- orientation ----------------------------------------------------------------
ORIENTATIONS = [(r, m) for m in (None, "x") for r in (0, 90, 180, 270)]


def to_screen(x: float, y: float, rot: int, mirror: str | None) -> tuple[float, float]:
    """Library point -> schematic offset (y down) for an instance orientation."""
    x, y = x, -y
    for _ in range((rot // 90) % 4):  # 90 degrees counterclockwise on screen
        x, y = y, -x
    if mirror == "x":
        y = -y
    elif mirror == "y":
        x = -x
    return x, y


def orient_vec(x: float, y: float, rot: int, mirror: str | None) -> tuple[float, float]:
    """Apply an orientation to a schematic (y-down) vector: rotate, then mirror."""
    return to_screen(x, -y, rot, mirror)


def compose(outer: tuple[int, str | None], inner: tuple[int, str | None]) -> tuple[int, str | None]:
    """The single orientation equal to applying `inner`, then `outer`."""
    probes = [(1, 0), (0, 1)]
    want = [orient_vec(*orient_vec(x, y, *inner), *outer) for x, y in probes]
    for o in ORIENTATIONS:
        if [orient_vec(x, y, *o) for x, y in probes] == want:
            return o
    raise AssertionError("orientations are closed under composition")


SIDE_VEC = {"N": (0, -1), "S": (0, 1), "W": (-1, 0), "E": (1, 0)}  # schematic, y down
_SCREEN_SIDE = {(0, -1): "N", (0, 1): "S", (-1, 0): "W", (1, 0): "E"}


def orient_side(side: str, rot: int, mirror: str | None) -> str:
    x, y = orient_vec(*SIDE_VEC[side], rot, mirror)
    return _SCREEN_SIDE[(round(x), round(y))]
_SIDE_VEC = {"N": (0, 1), "S": (0, -1), "W": (-1, 0), "E": (1, 0)}  # library y-up


def pin_side(pin: LibPin, rot: int, mirror: str | None) -> str:
    vx, vy = _SIDE_VEC[pin.side]
    sx, sy = to_screen(vx, vy, rot, mirror)
    return _SCREEN_SIDE[(round(sx), round(sy))]


def power_body_side(sym: LibSymbol, rot: int, mirror: str | None) -> str:
    """Schematic side on which a one-pin (power) symbol's body sits: opposite its pin."""
    return {"N": "S", "S": "N", "E": "W", "W": "E"}[pin_side(sym.pins[0], rot, mirror)]


def rot_with_pin_on(sym: LibSymbol, side: str) -> int:
    """Rotation (no mirror) that puts the symbol's first pin on `side`."""
    return next(r for r in (0, 90, 180, 270) if pin_side(sym.pins[0], r, None) == side)


def screen_bbox(sym: LibSymbol, rot: int, mirror: str | None):
    xmin, ymin, xmax, ymax = sym.bbox
    pts = [to_screen(x, y, rot, mirror) for x in (xmin, xmax) for y in (ymin, ymax)]
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            max(p[0] for p in pts), max(p[1] for p in pts))
