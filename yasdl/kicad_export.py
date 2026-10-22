"""Block -> KiCad 9 schematic (flat, one sheet), plus the netlist round-trip check."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from .block import Block, flat_names, netlist, partition
from .kicad_lib import KICAD_CLI, library_names, library_path, TEMPLATE_DIR, to_screen
from .kicad_sch import export_netlist, export_svg, run_erc, Schematic, snap
from .layout import layout
from .spice import (
    model_library,
    parse_spice,
    spice_model,
    spice_netlist,
    spice_partition,
)

MARGIN = 25.4
SVG_PAD = 12.7
_PAPER_SIZES = (
    ("A4", 297.0, 210.0),
    ("A3", 420.0, 297.0),
    ("A2", 594.0, 420.0),
    ("A1", 841.0, 594.0),
    ("A0", 1189.0, 841.0),
)


def _paper_for_bbox(bbox) -> str:
    """Smallest landscape ISO page containing the whole drawing and label pad."""
    width = bbox[2] - bbox[0] + MARGIN + SVG_PAD
    height = bbox[3] - bbox[1] + MARGIN + SVG_PAD
    for name, page_width, page_height in _PAPER_SIZES:
        if width <= page_width and height <= page_height:
            return name
    return "A0"


def _ref_prefix(lib_id: str, sym) -> str:
    prop = next(
        (
            c
            for c in sym.sexp
            if isinstance(c, list) and c[:2] == ["property", "Reference"]
        ),
        None,
    )
    return str(prop[2]) if prop else "X"


def to_kicad(
    block: Block, path, erc_helpers: bool = True, spice_libs: tuple = ()
) -> tuple[Path, dict[str, str]]:
    """Write `block` as a .kicad_sch (+ .kicad_pro, sym-lib-table); return (path, refmap).

    refmap: {kicad reference: yasdl path}; ERC helpers (test points, power flags) map to None.
    """
    res = layout(block)
    dx = MARGIN - res.bbox[0]
    dy = MARGIN - res.bbox[1]
    t = lambda p: (snap(p[0] + dx), snap(p[1] + dy))  # noqa: E731
    sch = Schematic(block.name, paper=_paper_for_bbox(res.bbox))
    counters, refmap, placed = Counter(), {}, []
    for ypath, atom, x, y, rot, mirror in res.symbols:
        sym = atom.symbol
        prefix = _ref_prefix(atom.lib_id, sym)
        if sym.is_power:
            ref = sch.add_symbol(
                atom.lib_id, "#PWR", atom.value, *t((x, y)), rot, mirror
            )
        else:
            counters[prefix] += 1
            ref = f"{prefix}{counters[prefix]}"
            sch.add_symbol(
                atom.lib_id,
                ref,
                atom.value,
                *t((x, y)),
                rot,
                mirror,
                fields={"yasdl_path": ypath, **_sim_fields(atom, spice_libs)},
            )
        refmap[ref] = ypath
        placed.append(
            (sym, t((x, y)), rot, mirror, atom.value or atom.lib_id.split(":")[1])
        )
    wires = [(t(a), t(b)) for a, b in res.wires]
    ends = Counter()
    for a, b in wires:
        sch.add_wire(a, b)
        ends[a] += 1
        ends[b] += 1
    for p, n in ends.items():
        if n >= 3:
            sch.add_junction(p)
    labels = []  # (text, point, global?)
    for text, p, scoped in res.labels:
        sch.add_label(text, t(p))
        labels.append((text, t(p), not scoped))
    port_points = []
    uf, _, names = flat_names(block)
    for port, edge, p in zip(block.ports, block.canvas.edge_ports, res.ports):
        alias = port.name or port.default
        root = uf.find(("", block.canvas.uf.find(edge.node)))
        angle = {"W": 180, "E": 0, "N": 90, "S": 270}[port.side]
        if alias == names[root]:
            sch.add_label(alias, t(p), angle)
            labels.append((alias, t(p), False))
        else:
            # Multiple interface aliases need not rename one electrical net.
            sch.add_text(alias, t(p), angle)
        port_points.append((port.side, t(p)))
    if erc_helpers:
        for (
            side,
            p,
        ) in port_points:  # open interface: a test point gives the net a second pin
            counters["TP"] += 1
            ref = f"TP{counters['TP']}"
            sch.add_symbol(
                "Connector:TestPoint", ref, "", *p, _OUTWARD[side], helper=True
            )
            refmap[ref] = None
        for anchor, rot in _power_flags(placed, wires, labels):
            ref = sch.add_symbol(
                "power:PWR_FLAG", "#FLG", "", anchor[0], anchor[1], rot=rot, helper=True
            )
            refmap[ref] = None
    path = sch.save(path)
    _write_project(path)
    _BBOX[str(path)] = (
        MARGIN,
        MARGIN,
        MARGIN + res.bbox[2] - res.bbox[0],
        MARGIN + res.bbox[3] - res.bbox[1],
    )
    return path, refmap


def _sim_fields(atom, spice_libs) -> dict:
    """KiCad simulator fields for model-based parts (transistors, diodes): library, model, pins.
    Plain R/C/L need none: KiCad reads their value."""
    try:
        m = spice_model(atom)
    except (
        Exception
    ):  # no SPICE mapping: the schematic is still valid, just not simulatable
        return {}
    if m is None or not m.model or atom.spice is None and not m.sim_pins:
        return {}
    lib = m.library or model_library(m.model, spice_libs)
    if lib is None:
        return {}
    fields = {"Sim.Library": lib, "Sim.Name": m.model}
    if m.prefix == "X":
        fields["Sim.Device"] = "SUBCKT"
    if m.sim_pins:
        fields["Sim.Pins"] = m.sim_pins
    return fields


# TestPoint body points away from the drawing (library body is above its pin).
_OUTWARD = {"W": 90, "E": 270, "N": 0, "S": 180}


def _power_flags(placed, wires, labels):
    """One PWR_FLAG per net that has power-input pins but no power-output pin (ERC rule).

    Nets are rebuilt from geometry, as KiCad does: coincident wire ends and pin points, and
    same-text labels, and same-name power symbols. The flag sits on a power symbol pin, else a global label, else any
    point of the net, turned across the wire there so it doesn't overlap it.
    """
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    for a, b in wires:
        union(a, b)
    pins = []  # (point, etype, power symbol?)
    for sym, (x, y), rot, mirror, value in placed:
        for p in sym.pins:
            sx, sy = to_screen(p.x, p.y, rot, mirror)
            pt = (snap(x + sx), snap(y + sy))
            find(pt)
            pins.append((pt, p.etype, sym.is_power))
            if (
                sym.is_power
            ):  # power symbols with one name are one net, wherever they are
                union(pt, ("label", value))
    for text, pt, _ in labels:
        union(pt, ("label", text))
    nets = {}
    for pt, etype, is_power in pins:
        nets.setdefault(find(pt), []).append((pt, etype, is_power))
    vertical = {p for a, b in wires if a[0] == b[0] for p in (a, b)}
    horizontal = {p for a, b in wires if a[1] == b[1] for p in (a, b)}
    flags = []
    for root, members in nets.items():
        types = {e for _, e, _ in members}
        if "power_in" not in types or "power_out" in types:
            continue
        candidates = [pt for pt, _, is_power in members if is_power]
        candidates += [pt for _, pt, glob in labels if glob and find(pt) == root]
        candidates += [pt for pt, e, _ in members if e == "power_in"]
        anchor = candidates[0]
        rot = 90 if anchor in vertical else 180 if anchor in horizontal else 0
        flags.append((anchor, rot))
    return flags


def _write_project(sch_path: Path):
    """A .kicad_pro and a sym-lib-table so ERC finds the libraries the symbols came from."""
    pro = sch_path.with_suffix(".kicad_pro")
    if not pro.exists():
        shutil.copy(TEMPLATE_DIR / "kicad.kicad_pro", pro)
    table = sch_path.parent / "sym-lib-table"
    lines = ["(sym_lib_table", "  (version 7)"]
    lines += [
        f'  (lib (name "{lib}")(type "KiCad")(uri "{library_path(lib)}")'
        '(options "")(descr ""))'
        for lib in library_names()
    ]
    text = "\n".join(lines + [")"]) + "\n"
    if not table.exists() or table.read_text() != text:  # rewritten when libraries change
        table.write_text(text)


def erc(sch_path) -> list[str]:
    """ERC violations (errors and warnings) reported by kicad-cli, as "[code] message @ where"."""
    report = run_erc(sch_path)
    out, current = [], None
    for line in report.splitlines():
        m = re.match(r"^\[(\w+)\]: (.*)", line)
        if m:
            current = f"[{m.group(1)}] {m.group(2)}"
        elif current and line.strip().startswith("@"):
            out.append(f"{current} {line.strip()}")
            current = None
    return out


_BBOX: dict[str, tuple] = {}


def _crop_svg(svg_path: Path, bbox, pad: float = SVG_PAD, px_per_mm: float = 12.0):
    """Shrink the A4 page of a kicad-cli SVG to the drawing, scaled up for viewing."""
    x0, y0, x1, y1 = bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad
    w, h = x1 - x0, y1 - y0
    text = svg_path.read_text()
    text = re.sub(
        r'width="[^"]*mm" height="[^"]*mm" viewBox="[^"]*"',
        f'width="{w * px_per_mm:.0f}" height="{h * px_per_mm:.0f}" '
        f'viewBox="{x0:.4f} {y0:.4f} {w:.4f} {h:.4f}"',
        text,
        count=1,
    )
    text = "\n".join(line.rstrip() for line in text.splitlines()) + "\n"
    svg_path.write_text(text)


def roundtrip(block: Block, sch_path, refmap) -> tuple[bool, set, set]:
    """Compare the KiCad netlist of `sch_path` with yasdl's netlist (power symbols excluded)."""
    kicad = export_netlist(sch_path)
    power_paths = {p for r, p in refmap.items() if r.startswith("#PWR")}
    got = {
        frozenset(
            f"{refmap[r]}.{pin}"
            for r, pin in nodes
            if not r.startswith("#") and refmap.get(r) is not None
        )
        for nodes in kicad.values()
    }
    got.discard(frozenset())
    want = {
        frozenset(x for x in net if x.rsplit(".", 1)[0] not in power_paths)
        for net in partition(netlist(block))
    }
    want.discard(frozenset())
    return got == want, want - got, got - want


def export_kicad_spice(sch_path) -> str:
    """kicad-cli's own SPICE export of a schematic."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "net.cir"
        subprocess.run(
            [
                str(KICAD_CLI),
                "sch",
                "export",
                "netlist",
                "--format",
                "spice",
                "-o",
                str(out),
                str(sch_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return out.read_text()


def spice_roundtrip(block: Block, sch_path, refmap) -> tuple[bool, str]:
    """Compare kicad-cli's SPICE export of the schematic with yasdl's own SPICE netlist."""
    kicad = parse_spice(export_kicad_spice(sch_path))
    ours = parse_spice(spice_netlist(block))
    k_part, k_vals = spice_partition(kicad, lambda n: refmap.get(n))
    o_part, o_vals = spice_partition(ours, lambda n: n.split("_", 1)[1])
    norm = lambda s: {frozenset((e.replace(".", "_"), i) for e, i in net) for net in s}  # noqa: E731
    vals = lambda s: {(e.replace(".", "_"), v) for e, v in s}  # noqa: E731
    ok = norm(k_part) == norm(o_part) and vals(k_vals) == vals(o_vals)
    return (
        ok,
        "" if ok else f"kicad {sorted(map(sorted, norm(k_part) ^ norm(o_part)))[:4]}",
    )


def render(
    block: Block, out_dir, svg: bool = True, spice_libs: tuple = (), spice: bool = False
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sch_path, refmap = to_kicad(
        block, out_dir / f"{block.name}.kicad_sch", spice_libs=spice_libs
    )
    ok, missing, extra = roundtrip(block, sch_path, refmap)
    info: dict[str, object] = {
        "schematic": sch_path,
        "roundtrip_ok": ok,
        "missing": missing,
        "extra": extra,
        "erc": erc(sch_path),
    }
    if spice:
        info["spice_ok"], info["spice_diff"] = spice_roundtrip(block, sch_path, refmap)
    if svg:
        info["svg"] = export_svg(sch_path, out_dir)
        _crop_svg(info["svg"], _BBOX[str(sch_path)])
    return info
