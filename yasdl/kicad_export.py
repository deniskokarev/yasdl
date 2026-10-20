"""Block -> KiCad 9 schematic (flat, one sheet), plus the netlist round-trip check."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .block import Block, netlist, partition
from .kicad_sch import Schematic, export_netlist, export_svg, snap
from .layout import layout
from .sexp import find

MARGIN = 25.4


def _ref_prefix(lib_id: str, sym) -> str:
    prop = next((c for c in sym.sexp if isinstance(c, list) and c[:2] == ["property", "Reference"]),
                None)
    return str(prop[2]) if prop else "X"


def to_kicad(block: Block, path) -> tuple[Path, dict[str, str]]:
    """Write `block` as a .kicad_sch; return (path, {kicad reference: yasdl path})."""
    res = layout(block)
    dx = MARGIN - res.bbox[0]
    dy = MARGIN - res.bbox[1]
    t = lambda p: (snap(p[0] + dx), snap(p[1] + dy))  # noqa: E731
    sch = Schematic(block.name)
    counters, refmap = Counter(), {}
    for ypath, atom, x, y, rot, mirror in res.symbols:
        sym = atom.symbol
        prefix = _ref_prefix(atom.lib_id, sym)
        if sym.is_power:
            ref = sch.add_symbol(atom.lib_id, "#PWR", atom.value, *t((x, y)), rot, mirror)
        else:
            counters[prefix] += 1
            ref = f"{prefix}{counters[prefix]}"
            sch.add_symbol(atom.lib_id, ref, atom.value, *t((x, y)), rot, mirror,
                           fields={"yasdl_path": ypath})
        refmap[ref] = ypath
    ends = Counter()
    for a, b in res.wires:
        a, b = t(a), t(b)
        sch.add_wire(a, b)
        ends[a] += 1
        ends[b] += 1
    for p, n in ends.items():
        if n >= 3:
            sch.add_junction(p)
    for text, p, _scoped in res.labels:
        sch.add_label(text, t(p))
    for (side, idx, name), p in zip(block.ports, res.ports):
        sch.add_label(name or f"{side}{idx}", t(p), {"W": 180, "E": 0, "N": 90, "S": 270}[side])
    path = sch.save(path)
    _BBOX[str(path)] = (MARGIN, MARGIN, MARGIN + res.bbox[2] - res.bbox[0],
                        MARGIN + res.bbox[3] - res.bbox[1])
    return path, refmap


_BBOX: dict[str, tuple] = {}


def _crop_svg(svg_path: Path, bbox, pad: float = 6.0, px_per_mm: float = 12.0):
    """Shrink the A4 page of a kicad-cli SVG to the drawing, scaled up for viewing."""
    x0, y0, x1, y1 = bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad
    w, h = x1 - x0, y1 - y0
    text = svg_path.read_text()
    text = re.sub(r'width="[^"]*mm" height="[^"]*mm" viewBox="[^"]*"',
                  f'width="{w * px_per_mm:.0f}" height="{h * px_per_mm:.0f}" '
                  f'viewBox="{x0:.4f} {y0:.4f} {w:.4f} {h:.4f}"', text, count=1)
    svg_path.write_text(text)


def roundtrip(block: Block, sch_path, refmap) -> tuple[bool, set, set]:
    """Compare the KiCad netlist of `sch_path` with yasdl's netlist (power symbols excluded)."""
    kicad = export_netlist(sch_path)
    power_paths = {p for r, p in refmap.items() if r.startswith("#PWR")}
    got = {frozenset(f"{refmap[r]}.{pin}" for r, pin in nodes if not r.startswith("#"))
           for nodes in kicad.values()}
    got.discard(frozenset())
    want = {frozenset(x for x in net if x.rsplit(".", 1)[0] not in power_paths)
            for net in partition(netlist(block))}
    want.discard(frozenset())
    return got == want, want - got, got - want


def render(block: Block, out_dir, svg: bool = True) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sch_path, refmap = to_kicad(block, out_dir / f"{block.name}.kicad_sch")
    ok, missing, extra = roundtrip(block, sch_path, refmap)
    info = {"schematic": sch_path, "roundtrip_ok": ok, "missing": missing, "extra": extra}
    if svg:
        info["svg"] = export_svg(sch_path, out_dir)
        _crop_svg(info["svg"], _BBOX[str(sch_path)])
    return info
