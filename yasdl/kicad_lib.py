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


# Normal installation roots, searched in order when YASDL_KICAD is not set (spec 6.1).
KICAD_CANDIDATES = (
    Path.home() / "KiCad9",
    Path("/Applications/KiCad"),
    Path("/Applications/KiCad/KiCad.app"),
    Path("/Applications/KiCad.app"),
    Path("/usr"),
    Path("/usr/local"),
    Path("/opt/kicad"),
)


class YasdlDependencyError(RuntimeError):
    """A required external tool or resource (KiCad, a symbol library, a SPICE model) is
    missing or failed. The message names the operation, what was searched and the remedy."""


DependencyError = YasdlDependencyError


class SymbolNotFound(YasdlDependencyError, KeyError):
    """A missing library symbol, catchable as either a dependency error or KeyError."""

    def __str__(self):  # KeyError would quote the message
        return str(self.args[0]) if self.args else ""


class LibraryNotFound(SymbolNotFound, FileNotFoundError):
    """A missing symbol library file (also a FileNotFoundError)."""


class KiCadNotFound(YasdlDependencyError, FileNotFoundError):
    """kicad-cli is missing (also a FileNotFoundError)."""


class KiCadCommandFailed(YasdlDependencyError):
    """kicad-cli ran and exited with an error; the message holds its command and output."""


def kicad_candidates():
    """Normal installation roots, then the prefix of a kicad-cli found on PATH."""
    import shutil

    found = shutil.which("kicad-cli")
    extra = [Path(found).resolve().parent.parent] if found else []
    return list(KICAD_CANDIDATES) + [p for p in extra if p not in KICAD_CANDIDATES]


def find_kicad_root() -> tuple[Path, list[Path]]:
    """(root, searched): YASDL_KICAD when set, else the first normal installation that has
    kicad-cli or KiCad's symbol libraries; ~/KiCad9 if none does."""
    env = os.environ.get("YASDL_KICAD")
    if env:
        return Path(env).expanduser(), [Path(env).expanduser()]
    candidates = kicad_candidates()
    for root in candidates:
        cli, symbols, _ = _resolve_kicad_layout(root)
        if cli.exists() or symbols.is_dir():
            return root, candidates
    return KICAD_CANDIDATES[0], candidates


def discover_kicad() -> Path:
    """The KiCad installation root yasdl uses: YASDL_KICAD, else a normal installation."""
    return find_kicad_root()[0]


KICAD_ROOT, KICAD_SEARCHED = find_kicad_root()
KICAD_CLI, SYMBOL_DIR, TEMPLATE_DIR = _resolve_kicad_layout(KICAD_ROOT)


def _remedy() -> str:
    searched = ", ".join(str(p) for p in KICAD_SEARCHED)
    return (
        f"KiCad root {KICAD_ROOT} (searched: {searched}). Install KiCad 9, or set YASDL_KICAD "
        "to its installation root (a prefix with bin/kicad-cli and share/kicad, or the "
        "directory containing KiCad.app)"
    )


def require_cli(operation: str = "KiCad schematic export/ERC") -> Path:
    """kicad-cli of KiCad 9, checked when an operation needs it (never at import). A missing
    CLI raises KiCadNotFound (a FileNotFoundError); another major version, RuntimeError."""
    if not Path(KICAD_CLI).is_file():
        raise KiCadNotFound(
            f"{operation} needs kicad-cli, not found at {KICAD_CLI}. {_remedy()}."
        )
    _check_cli_version(str(KICAD_CLI))
    return Path(KICAD_CLI)


@lru_cache(maxsize=None)
def _check_cli_version(path: str) -> None:
    """Reject a kicad-cli that reports another major version. A CLI that can't report a
    version is left to fail (with its own output) in the operation that runs it."""
    import re
    import subprocess

    try:
        result = subprocess.run([path, "version"], capture_output=True, text=True)
    except OSError:
        return
    m = re.match(r"\s*(\d+)\.\d+", result.stdout)
    if result.returncode == 0 and m and m.group(1) != "9":
        raise YasdlDependencyError(
            f"KiCad 9 is required; {path} reports version {result.stdout.strip()!r}. Install "
            "KiCad 9 and set YASDL_KICAD to its installation root"
        )


def run_cli(operation, args=None, check: bool = True, cwd=None, ok=(0,)):
    """Run kicad-cli: run_cli("SVG export", [args...]) or run_cli([args...], cwd=..., ok=(0,)).
    A missing CLI raises KiCadNotFound; with `check`, an exit status outside `ok` raises
    KiCadCommandFailed with the command, exit status and kicad-cli's output."""
    import subprocess

    if args is None and not isinstance(operation, str):  # run_cli([args...])
        args = list(operation)
        operation = "kicad-cli " + " ".join(map(str, args[:2]))
    cmd = [str(require_cli(operation)), *map(str, args)]
    run = subprocess.run(cmd, capture_output=True, text=True, **({'cwd': cwd} if cwd else {}))
    if check and run.returncode not in ok:
        raise KiCadCommandFailed(
            f"{operation} failed: {' '.join(cmd)} exited with {run.returncode}\n"
            f"{(run.stderr or run.stdout).strip()}"
        )
    return run


# Libraries shipped with yasdl (symbols KiCad lacks, e.g. the supply-less ideal op-amp) and
# their simulation models. A bundled library shadows a KiCad library of the same name.
BUNDLED_DIR = Path(__file__).parent / "lib"
BUNDLED_MODELS = BUNDLED_DIR / "yasdl.lib"
JELLYBEAN_MODEL = BUNDLED_DIR / "jellybean.lib"


def library_path(lib: str) -> Path:
    """The .kicad_sym file of library `lib`: bundled first, then KiCad's."""
    bundled = BUNDLED_DIR / f"{lib}.kicad_sym"
    return bundled if bundled.exists() else SYMBOL_DIR / f"{lib}.kicad_sym"


def _missing_library(lib: str) -> YasdlDependencyError:
    where = f"{BUNDLED_DIR / (lib + '.kicad_sym')} and {SYMBOL_DIR / (lib + '.kicad_sym')}"
    if not SYMBOL_DIR.is_dir():
        return LibraryNotFound(
            f"symbol library {lib!r}: KiCad's symbol directory {SYMBOL_DIR} does not exist. "
            f"{_remedy()}."
        )
    return LibraryNotFound(
        f"symbol library {lib!r} not found (searched {where}); {_remedy()}; check the library name "
        "in the lib_id 'Library:Symbol'"
    )


def library_names() -> list[str]:
    """Every library a schematic can draw from (KiCad's and yasdl's bundled ones)."""
    return sorted(
        {f.stem for f in SYMBOL_DIR.glob("*.kicad_sym")}
        | {f.stem for f in BUNDLED_DIR.glob("*.kicad_sym")}
    )


# Library pin angle -> side of the symbol the pin sits on (pin points towards the body).
_ANGLE_SIDE = {0: "W", 180: "E", 270: "N", 90: "S"}


@dataclass(frozen=True)
class LibPin:
    number: str
    name: str
    x: float  # connection point, library coordinates (y up)
    y: float
    side: str  # N/E/S/W in library orientation
    etype: str = (
        "passive"  # electrical type: input, output, passive, power_in, power_out, ...
    )


class _FrozenList(list):
    """An S-expression list that refuses in-place edits (cached library definitions)."""

    def _blocked(self, *args, **kwargs):
        raise TypeError("symbol definitions are immutable; derive a new definition")

    __setitem__ = __delitem__ = append = extend = insert = pop = remove = _blocked
    clear = reverse = sort = __iadd__ = __imul__ = _blocked

    def __deepcopy__(self, memo):
        import copy

        return [copy.deepcopy(x, memo) for x in self]


def _freeze(value):
    return _FrozenList(_freeze(x) for x in value) if isinstance(value, list) else value


@dataclass(frozen=True)
class LibSymbol:
    lib_id: str
    definition: list  # the (symbol ...) definition, embedded into schematics' lib_symbols
    pins: tuple[LibPin, ...]  # pins of this unit (plus pins common to all units)
    bbox: tuple[float, float, float, float]  # xmin, ymin, xmax, ymax (library coords)
    is_power: bool
    unit: int = 1
    unit_count: int = 1

    def __post_init__(self):
        object.__setattr__(self, "definition", _freeze(self.definition))

    @property
    def sexp(self) -> list:
        """The definition. KiCad library symbols are shared and immutable; a derived
        definition hands out a fresh copy, so editing it never changes the registered one."""
        if self.lib_id.startswith(DERIVED_LIB + ":"):
            import copy

            return copy.deepcopy(self.definition)
        return self.definition


# --- derived symbol definitions (spec 6.3) -----------------------------------------
# Parts built from a generic KiCad shape with their own physical pin numbers (2N3904 from
# Device:Q_NPN, a dual op-amp from the LM2904 shape). Each definition is immutable once
# registered; the schematic writer embeds exactly this definition and writes it to a
# project-local library so KiCad's ERC finds a matching library symbol.
DERIVED_LIB = "yasdl_parts"
_DERIVED: dict[str, list] = {}


def _symbol_sexp(lib_id: str) -> list:
    lib, name = lib_id.split(":", 1)
    if lib == DERIVED_LIB:
        if lib_id not in _DERIVED:
            raise YasdlDependencyError(f"derived symbol {lib_id} is not registered")
        return _DERIVED[lib_id]
    root = _library(lib)
    sym = next((s for s in find_all(root, "symbol") if s[1] == name), None)
    if sym is None:
        import difflib

        names = [str(x[1]) for x in find_all(root, "symbol")]
        close = difflib.get_close_matches(name, names, n=3)
        raise SymbolNotFound(
            f"symbol {lib_id} not found; searched {library_path(lib)}"
            + (f"; did you mean {', '.join(close)}?" if close else "")
            + "; check the symbol name, or install the standard KiCad 9 libraries and set "
            "YASDL_KICAD to their installation root"
        )
    return sym


def derived_symbols() -> dict[str, list]:
    """Every registered derived definition: {lib_id: (symbol ...)}."""
    return dict(_DERIVED)


def derive_symbol(base: str, name: str, renumber: dict, properties: dict | None = None) -> str:
    """Register `yasdl_parts:<name>`: a copy of symbol `base` whose pins get new numbers.

    renumber: {base pin number: physical pin number}, complete and one-to-one. properties:
    fields to set (Footprint, Datasheet, Description, ...). Pin names, geometry and units
    are kept. Registering one name twice with a different definition is an error; the
    generic base definition is never modified.
    """
    import copy

    from .sexp import dumps

    src = _symbol_sexp(base)
    if find(src, "extends"):
        raise NotImplementedError(f"{base}: derive from a root symbol, not one using (extends)")
    base_name = str(src[1]).split(":")[-1]
    numbers = [
        str(find(item, "number")[1])
        for unit in find_all(src, "symbol")
        for item in unit
        if isinstance(item, list) and item and item[0] == "pin"
    ]
    renumber = {str(k): str(v) for k, v in renumber.items()}
    if sorted(renumber) != sorted(set(numbers)):
        raise ValueError(
            f"{name}: renumber must map every pin of {base} exactly once: "
            f"pins {sorted(set(numbers))}, given {sorted(renumber)}"
        )
    if len(set(renumber.values())) != len(renumber):
        raise ValueError(f"{name}: two pins get the same physical number: {renumber}")
    sym = copy.deepcopy(src)
    sym[1] = name
    for item in sym:
        if isinstance(item, list) and item and str(item[0]) == "property":
            key = str(item[1])
            if key == "Value":
                item[2] = name
            elif properties and key in properties:
                item[2] = str(properties[key])
    present = {str(i[1]) for i in sym if isinstance(i, list) and i and str(i[0]) == "property"}
    for key, val in (properties or {}).items():
        if key not in present:
            raise ValueError(f"{name}: {base} has no {key} field to set")
    for unit in find_all(sym, "symbol"):
        unit[1] = name + str(unit[1])[len(base_name):]
        for item in unit:
            if isinstance(item, list) and item and str(item[0]) == "pin":
                num = find(item, "number")
                num[1] = renumber[str(num[1])]
    lib_id = f"{DERIVED_LIB}:{name}"
    if lib_id in _DERIVED and dumps(_DERIVED[lib_id]) != dumps(sym):
        raise ValueError(f"{lib_id} is already defined differently; pick another name")
    _DERIVED[lib_id] = sym
    return lib_id


def write_derived_library(path: Path, lib_ids, defs: dict | None = None) -> Path:
    """A .kicad_sym file holding the given derived definitions (for the project's table)."""
    from .sexp import dumps, Sym

    defs = _DERIVED if defs is None else defs
    root = [
        Sym("kicad_symbol_lib"),
        [Sym("version"), Sym("20241209")],
        [Sym("generator"), "yasdl"],
        [Sym("generator_version"), "9.0"],
        *[defs[i] for i in sorted(set(lib_ids))],
    ]
    path.write_text(dumps(root) + "\n")
    return path


@lru_cache(maxsize=None)
def _library(lib: str):
    path = library_path(lib)
    try:
        text = path.read_text()
    except FileNotFoundError:
        raise _missing_library(lib) from None
    return parse(text)


@lru_cache(maxsize=None)
def load(lib_id: str, unit: int = 1) -> LibSymbol:
    """Pins and extent of one unit (default 1) of a library or derived symbol."""
    sym = _symbol_sexp(lib_id)
    if find(sym, "extends"):
        raise NotImplementedError(
            f"{lib_id}: symbols using (extends) are not supported; use its root symbol "
            f"({find(sym, 'extends')[1]}) or a generic part factory (AtomNPN, OpampPackage)"
        )
    units = {
        int(str(u[1]).rsplit("_", 2)[1]) for u in find_all(sym, "symbol")
    } - {0}
    unit_count = max(units) if units else 1
    if not 1 <= unit <= unit_count:
        raise ValueError(f"{lib_id} has units 1..{unit_count}, not {unit}")
    pins, xs, ys = [], [], []
    for sub in find_all(sym, "symbol"):
        _, unit_no, style = str(sub[1]).rsplit("_", 2)
        if int(unit_no) not in (0, unit) or int(style) not in (0, 1):  # normal body style
            continue
        for item in sub:
            if not isinstance(item, list):
                continue
            kind = item[0]
            if kind == "pin":
                at = find(item, "at")
                x, y, ang = float(at[1]), float(at[2]), int(float(at[3])) % 360
                length = float(find(item, "length")[1])
                pins.append(
                    LibPin(
                        str(find(item, "number")[1]),
                        str(find(item, "name")[1]),
                        x,
                        y,
                        _ANGLE_SIDE[ang],
                        str(item[1]),
                    )
                )
                dx, dy = (
                    round(math.cos(math.radians(ang))),
                    round(math.sin(math.radians(ang))),
                )
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
    return LibSymbol(
        lib_id,
        sym,
        tuple(pins),
        (min(xs), min(ys), max(xs), max(ys)),
        is_power,
        unit,
        unit_count,
    )


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


def compose(
    outer: tuple[int, str | None], inner: tuple[int, str | None]
) -> tuple[int, str | None]:
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
    return (
        min(p[0] for p in pts),
        min(p[1] for p in pts),
        max(p[0] for p in pts),
        max(p[1] for p in pts),
    )
