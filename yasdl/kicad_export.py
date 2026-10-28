"""Block -> KiCad 9 schematic (flat, one sheet), plus the netlist round-trip check."""

from __future__ import annotations

import re
import shutil
import tempfile
from collections import Counter
from pathlib import Path

from .block import Block, flat_names, netlist, partition, YasdlError
from .kicad_lib import (
    BUNDLED_DIR,
    DERIVED_LIB,
    KiCadCommandFailed,
    derived_symbols,
    write_derived_library,
    library_names,
    library_path,
    run_cli,
    TEMPLATE_DIR,
    to_screen,
    YasdlDependencyError,
)
from .kicad_sch import export_netlist, export_svg, run_erc, Schematic, snap
from .layout import layout
from .spice import (
    compare_spice as _compare_spice,
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
    block: Block,
    path,
    erc_helpers: bool = True,
    spice_libs: tuple = (),
    references: str = "annotate",
    values: bool = True,
    bundle_models: bool = True,
) -> tuple[Path, dict[str, str]]:
    """Write `block` as a .kicad_sch (+ .kicad_pro, sym-lib-table); return (path, refmap).

    bundle_models: copy every SPICE model library the schematic references into
    `<dir>/models/` and point Sim.Library at the copies with project-relative paths, so
    the project still simulates after it is moved (spec 6.5). False keeps absolute paths.

    refmap: {kicad reference: yasdl path}; ERC helpers (test points, power flags) map to None.
    references: "annotate" numbers parts per prefix (R1, R2, ...); "names" uses each
    component's own yasdl name (RI, Rint1) when names are unique design-wide, else the path
    ("INT1_RI"), so the drawing shows the names a netlist or question uses.
    values: False hides the value fields (symbolic drawings); the values stay in the file.
    """
    if references not in ("annotate", "names"):
        raise ValueError(
            f"references must be 'annotate' or 'names', not {references!r}"
        )
    from .spice import packages

    placed_pkgs = {id(pp.package): pp for pp in packages(block)}
    res = layout(block)
    dx = MARGIN - res.bbox[0]
    dy = MARGIN - res.bbox[1]
    t = lambda p: (snap(p[0] + dx), snap(p[1] + dy))  # noqa: E731
    sch = Schematic(block.name, paper=_paper_for_bbox(res.bbox))
    counters, refmap, placed = Counter(), {}, []
    leaf = {
        p: p.rsplit(".", 1)[-1]
        for p, a, *_ in res.symbols
        if not a.symbol.is_power and a.package is None
    }
    if len({v.casefold() for v in leaf.values()}) != len(leaf):
        leaf = {p: p.replace(".", "_") for p in leaf}
    for pp in placed_pkgs.values():  # a package's units share one reference: its name
        for unit_path in pp.unit_paths.values():
            leaf[unit_path] = pp.name
    pkg_refs: dict[int, str] = {}
    packages_used = []
    copies: dict = {}  # model files copied into the project by this export
    for ypath, atom, x, y, rot, mirror in res.symbols:
        sym = atom.symbol
        prefix = _ref_prefix(atom.lib_id, sym)
        if sym.is_power:
            ref = sch.add_symbol(
                atom.lib_id, "#PWR", atom.value, *t((x, y)), rot, mirror
            )
        else:
            pkg = atom.package
            if pkg is not None and id(pkg) in pkg_refs:
                ref = pkg_refs[id(pkg)]
            else:
                counters[prefix] += 1
                ref = (
                    f"{prefix}{counters[prefix]}"
                    if references == "annotate"
                    else leaf[ypath]
                )
            fields = {"yasdl_path": ypath, **_sim_fields(atom, spice_libs)}
            if pkg is not None:
                pkg_refs[id(pkg)] = ref
                fields.update(_package_sim_fields(pkg, Path(path).parent, spice_libs))
                if pkg.sim and pkg.descriptor not in packages_used:
                    packages_used.append(pkg.descriptor)
            if bundle_models and "Sim.Library" in fields:
                fields["Sim.Library"] = _bundle(Path(path).parent, fields["Sim.Library"], copies)
            sch.add_symbol(
                atom.lib_id,
                ref,
                atom.value,
                *t((x, y)),
                rot,
                mirror,
                fields=fields,
                hide_value=not values,
                sim=atom.sim,
                footprint=atom.footprint,
                datasheet=atom.datasheet,
                unit=atom.unit,
            )
        if atom.package is not None:
            pp = placed_pkgs[id(atom.package)]
            refmap[ref] = PackageRef(pp.name, pp.pin_path)
        else:
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
    for p in res.nc:
        sch.add_no_connect(t(p))
    uf, _, names = flat_names(block)
    # A child's local label can be joined through its ports to a differently named net (a
    # supply, a parent label): the electrical label carries the flattened net name, so KiCad
    # sees one name per net; the drawn name stays beside it as text.
    canonical = _label_net_names(block, uf, names)
    labels = []  # (text, point, global?)
    for text, p, scoped in res.labels:
        name = canonical.get(text, text)
        sch.add_label(name, t(p))
        if name != text:
            sch.add_text(text, (t(p)[0], snap(t(p)[1] - 2.54)))
        labels.append((name, t(p), not scoped))
    port_points = []
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
        for anchor, rot in _lonely_labels(placed, wires, labels, port_points):
            # A net label on a net with one pin is "label_dangling" for KiCad (a block
            # rendered on its own whose [Vref] or [x] reaches one part): add a test point.
            counters["TP"] += 1
            ref = f"TP{counters['TP']}"
            sch.add_symbol("Connector:TestPoint", ref, "", *anchor, rot, helper=True)
            refmap[ref] = None
        for anchor, rot in _power_flags(placed, wires, labels, [t(p) for p in res.nc]):
            ref = sch.add_symbol(
                "power:PWR_FLAG", "#FLG", "", anchor[0], anchor[1], rot=rot, helper=True
            )
            refmap[ref] = None
    path = sch.save(path)
    _write_package_lib(path.parent, packages_used, bundle_models, spice_libs)
    _write_project(path, [i for i in sch.lib_ids if i.startswith(DERIVED_LIB + ":")])
    _BBOX[str(path)] = (
        MARGIN,
        MARGIN,
        MARGIN + res.bbox[2] - res.bbox[0],
        MARGIN + res.bbox[3] - res.bbox[1],
    )
    return path, refmap


def _label_net_names(block: Block, uf, names) -> dict[str, str]:
    """{label text as laid out ("A1.bus" for a child's local label): flattened net name}."""
    out = {}

    def visit(current, prefix):
        for i, lab in enumerate(current.canvas.labels):
            if lab.kind in ("local", "global"):
                root = uf.find((prefix, current.canvas.uf.find(("l", i))))
                out[prefix + lab.text if lab.kind == "local" else lab.text] = names[root]
        for name, b in current.bound.items():
            if isinstance(b.obj, Block):
                visit(b.obj, f"{prefix}{name}.")

    visit(block, "")
    return out


class PackageRef(str):
    """refmap value of a multi-unit reference: the package name, plus the yasdl path of the
    unit view carrying each physical pin (pin_path)."""

    def __new__(cls, name, pin_path):
        obj = super().__new__(cls, name)
        obj.pin_path = dict(pin_path)
        return obj


PACKAGE_LIB = "yasdl_packages.lib"


def _package_sim_fields(pkg, out_dir: Path, spice_libs=()) -> dict:
    """Sim fields for every unit of a package (KiCad reads them per reference, from any
    unit): one subcircuit over all physical pins."""
    d = pkg.descriptor
    if not pkg.sim or not d.model:
        return {}
    model, order = d.spice_element()
    if d.scope == "unit":
        lib = str(out_dir.resolve() / PACKAGE_LIB)
        pins = " ".join(f"{n}=p{n}" for n in order)
    else:
        from .parts import subckt_pins

        lib = d.library or model_library(model, spice_libs)
        mapping = getattr(d, 'spice', None)
        if lib is None:
            return {'Sim.Device': 'SUBCKT', 'Sim.Name': model, **({'Sim.Pins': mapping.sim_pins} if mapping and mapping.sim_pins else {})}
        nodes = subckt_pins(model, lib)
        pins = " ".join(f"{n}={m}" for n, m in zip(order, nodes))
    fields = {"Sim.Device": "SUBCKT", "Sim.Library": lib, "Sim.Name": model, "Sim.Pins": pins}
    mapping = getattr(d, 'spice', None)
    if mapping is not None and mapping.sim_pins:
        fields['Sim.Pins'] = mapping.sim_pins
    if mapping is not None and mapping.params:
        fields['Sim.Params'] = mapping.params
    return fields


MODEL_DIR = "spice_models"


def _bundle(out_dir: Path, lib, cache=None, relative: bool = False) -> str:
    """Copy model library `lib` and its .include closure into out_dir/spice_models (see
    resources.copy_model_resource) and return its project-relative path,
    spice_models/<file>. A relative path also resolves for a schematic exported without its
    .kicad_pro (a renamed copy), where ${KIPRJMOD} is undefined."""
    from .resources import copy_model_resource

    lib = Path(lib)
    if not lib.is_absolute():
        lib = (out_dir / lib).resolve()
    if lib.parent == out_dir.resolve():  # generated next to the schematic already
        return lib.name
    copied = copy_model_resource(lib, out_dir / MODEL_DIR, cache)
    return f"{MODEL_DIR}/{copied.name}"


def _write_package_lib(out_dir: Path, descriptors, bundle: bool = True, spice_libs=()) -> None:
    """Whole-package wrapper subcircuits (and the includes they need) for KiCad's export,
    merged with wrappers already written to this directory by other renders."""
    import re as _re

    wanted = [d for d in descriptors if d.model and d.scope == "unit"]
    if not wanted:
        return
    path = out_dir / PACKAGE_LIB
    text = path.read_text() if path.exists() else "* yasdl package wrappers\n"
    for d in wanted:
        source = d.library or model_library(d.model, spice_libs)
        lib = (_bundle(out_dir, source, relative=True) if bundle else source) if source else None
        block = (f".include {lib}\n" if lib else "") + d.wrapper()
        m = _re.search(
            rf"(?ms)^(\.include [^\n]*\n)?\.subckt {d.wrapper_name()} .*?^\.ends {d.wrapper_name()}\n",
            text,
        )
        if m:
            if m.group(0) != block:
                text = text.replace(m.group(0), block)
        else:
            text += block
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def _sim_fields(atom, spice_libs) -> dict:
    """KiCad simulator fields for model-based parts (transistors, diodes): library, model, pins.
    Plain R/C/L need none: KiCad reads their value."""
    try:
        m = spice_model(atom)
    except (
        Exception
    ):  # no SPICE mapping: the schematic is still valid, just not simulatable
        return {}
    if m is not None and not m.model and m.prefix in ("V", "I"):
        # KiCad's VDC/IDC read the value as a bare DC level ("DC dc 0 ac 1"). A raw SPICE
        # model passes the complete yasdl source specification through unchanged.
        spec = atom.value.replace('"', "'")
        return {
            "Sim.Device": "SPICE",
            "Sim.Params": f'type="{m.prefix}" model="{spec}" lib=""',
            "Sim.Pins": " ".join(f"{p}={i}" for i, p in enumerate(m.pins, 1)),
        }
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
    if m.params:
        fields["Sim.Params"] = m.params
    return fields


# TestPoint body points away from the drawing (library body is above its pin).
_OUTWARD = {"W": 90, "E": 270, "N": 0, "S": 180}


def _geometric_nets(placed, wires, labels):
    """KiCad's view of connectivity: a find() over points joined by wires, pins, same-text
    labels and same-name power symbols; plus the pins as (point, etype, power?)."""
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
    pins = []
    for sym, (x, y), rot, mirror, value in placed:
        for p in sym.pins:
            sx, sy = to_screen(p.x, p.y, rot, mirror)
            pt = (snap(x + sx), snap(y + sy))
            find(pt)
            pins.append((pt, p.etype, sym.is_power))
            if sym.is_power:
                union(pt, ("label", value))
    for text, pt, _ in labels:
        union(pt, ("label", text))
    return find, pins


def _lonely_labels(placed, wires, labels, port_points):
    """(point, rotation) of a test point for each net label whose net has exactly one
    component pin and no port: the body points away from the label's wire."""
    find, pins = _geometric_nets(placed, wires, labels)
    count = Counter(find(pt) for pt, _, is_power in pins if not is_power)
    powered = {find(pt) for pt, _, is_power in pins if is_power}
    ported = {find(pt) for _, pt in port_points}
    out, done = [], set()
    for _text, pt, _ in labels:
        root = find(pt)
        if count[root] != 1 or root in powered or root in ported or root in done:
            continue
        done.add(root)
        away = "W"
        for a, b in wires:
            if pt in (a, b):
                other = b if a == pt else a
                away = (
                    ("W" if other[0] > pt[0] else "E")
                    if other[1] == pt[1]
                    else ("N" if other[1] > pt[1] else "S")
                )
                break
        out.append((pt, _OUTWARD[away]))
    return out


def _power_flags(placed, wires, labels, nc=()):
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
    nc_roots = {find(p) for p in nc}
    for root, members in nets.items():
        types = {e for _, e, _ in members}
        if root in nc_roots or "power_in" not in types or "power_out" in types:
            continue
        candidates = [pt for pt, _, is_power in members if is_power]
        candidates += [pt for _, pt, glob in labels if glob and find(pt) == root]
        candidates += [pt for pt, e, _ in members if e == "power_in"]
        anchor = candidates[0]
        rot = 90 if anchor in vertical else 180 if anchor in horizontal else 0
        flags.append((anchor, rot))
    return flags


def _write_project(sch_path: Path, derived=()):
    """A .kicad_pro and a sym-lib-table so ERC finds the libraries the symbols came from.
    Derived part definitions go to a project-local yasdl_parts.kicad_sym (merged with the
    ones other renders put in the same directory), referenced through ${KIPRJMOD}."""
    pro = sch_path.with_suffix(".kicad_pro")
    if not pro.exists():
        template = TEMPLATE_DIR / "kicad.kicad_pro"
        if not template.exists():
            from .kicad_lib import _remedy

            raise YasdlDependencyError(
                f"writing {pro} needs KiCad's project template {template}, which is "
                f"missing. {_remedy()}."
            )
        shutil.copy(template, pro)
    table = sch_path.parent / "sym-lib-table"
    lines = ["(sym_lib_table", "  (version 7)"]
    for lib in library_names():
        uri = library_path(lib)
        if uri.parent == BUNDLED_DIR:  # yasdl's own symbols travel with the project
            local = sch_path.parent / uri.name
            if not local.exists() or local.read_text() != uri.read_text():
                shutil.copy(uri, local)
            uri = f"${{KIPRJMOD}}/{uri.name}"
        lines.append(
            f'  (lib (name "{lib}")(type "KiCad")(uri "{uri}")(options "")(descr ""))'
        )
    if derived:
        _merge_derived_library(sch_path.parent / f"{DERIVED_LIB}.kicad_sym", derived)
    if derived or (sch_path.parent / f"{DERIVED_LIB}.kicad_sym").exists():
        lines.append(
            f'  (lib (name "{DERIVED_LIB}")(type "KiCad")'
            f'(uri "${{KIPRJMOD}}/{DERIVED_LIB}.kicad_sym")(options "")(descr ""))'
        )
    text = "\n".join(lines + [")"]) + "\n"
    if (
        not table.exists() or table.read_text() != text
    ):  # rewritten when libraries change
        table.write_text(text)


def _merge_derived_library(path: Path, lib_ids) -> None:
    """Write `lib_ids` into the directory's derived library, keeping other definitions; a
    name already defined differently there is an error (definitions are immutable)."""
    from .sexp import dumps, find_all, parse

    defs = derived_symbols()
    have = {}
    if path.exists():
        for sym in find_all(parse(path.read_text()), "symbol"):
            have[f"{DERIVED_LIB}:{sym[1]}"] = sym
    for lib_id in lib_ids:
        old = have.get(lib_id)
        if old is not None and dumps(old) != dumps(defs[lib_id]):
            raise YasdlDependencyError(
                f"{path} already defines {lib_id} differently (another design used the "
                "same part name with another pinout); render into another directory"
            )
        have[lib_id] = defs[lib_id]
    write_derived_library(path, have.keys(), have)


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
    def ypin(r, pin):  # a multi-unit reference maps each physical pin to its unit view
        target = refmap[r]
        path = target.pin_path.get(pin) if isinstance(target, PackageRef) else target
        return f"{path}.{pin}"

    got = {
        frozenset(
            ypin(r, pin)
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
    # Global nets (supplies, ground, global labels) also keep their names: the same pin
    # groups on a renamed supply are a different circuit.
    uf, pins, _ = flat_names(block)
    globals_ = {uf.find(k): k[1] for k in uf.parent if k[0] == "global"}
    want_named = set()
    for root, name in globals_.items():
        members = frozenset(
            f"{path}.{pin}"
            for (path, pin), n in pins.items()
            if uf.find(n) == root and path not in power_paths
        )
        if members:
            want_named.add((name.casefold(), members))
    global_names = {n for n, _ in want_named}
    got_named = set()
    for net, nodes in kicad.items():
        name = str(net).removeprefix("/").casefold()  # one flat sheet: labels are "/name"
        members = frozenset(
            ypin(r, pin)
            for r, pin in nodes
            if not r.startswith("#") and refmap.get(r) is not None
        )
        wanted = {n for n, m in want_named if m == members}
        if members and (name in global_names or wanted):
            got_named.add((name, members))
    named_missing = {("@" + n, m) for n, m in want_named - got_named}
    named_extra = {("@" + n, m) for n, m in got_named - want_named}
    ok = got == want and not named_missing and not named_extra
    return ok, (want - got) | named_missing, (got - want) | named_extra


def export_kicad_spice(sch_path) -> str:
    """kicad-cli's own SPICE export of a schematic."""
    with tempfile.TemporaryDirectory() as tmp:
        sch_path = Path(sch_path).resolve()
        out = Path(tmp) / "net.cir"
        run_cli(
            "SPICE export",
            ["sch", "export", "netlist", "--format", "spice", "-o", out, sch_path],
            cwd=sch_path.parent,
        )
        return out.read_text()


def check_models(block: Block, spice_libs=(), require: bool = True) -> None:
    """Every SPICE model resource a render needs: each spice_libs file must exist, and (with
    `require`) every model-based part's model must be defined in its SpiceModel.library or
    in one of spice_libs. Raises YasdlDependencyError naming the part and the files searched."""
    from .spice import _instances

    for lib in spice_libs:
        if not Path(lib).is_file():
            raise YasdlDependencyError(f"SPICE model library {lib} (spice_libs) not found; file does not exist")
    if not require:
        return
    for path, _, atom in _instances(block):
        m = spice_model(atom)
        if m is None or not m.model:
            continue
        if m.library:
            if not Path(m.library).is_file():
                raise YasdlDependencyError(
                    f"{path}: SPICE library {m.library} (for model {m.model}) not found"
                )
            if model_library(m.model, (m.library,)) is None:
                raise YasdlDependencyError(
                    f"{path}: {m.library} defines no .model/.subckt {m.model}"
                )
        elif model_library(m.model, spice_libs) is None:
            searched = ", ".join(map(str, spice_libs)) or "none given"
            raise YasdlDependencyError(
                f"{path}: SPICE model {m.model!r} is not defined in spice_libs "
                f"({searched}); pass the file that defines it, e.g. "
                "spice_libs=(yasdl.kicad_lib.JELLYBEAN_MODEL,) for 2N3904/2N3906/1N4148"
            )


def kicad_element_name(name: str, refmap) -> str | None:
    """yasdl path of a kicad-cli SPICE element. kicad-cli prefixes the element letter when
    the reference lacks it (a subcircuit U1 becomes XU1, a pot RV1 becomes XRV1)."""
    if name in refmap:
        return refmap[name]
    return refmap.get(name[1:]) if name[:1].upper() in "XVIRCLDQ" else None


_GENERATED = re.compile(r"^(N\d+|Net-.*|unconnected-.*|.*\..*)$")


def user_net_names(*decks) -> set[str]:
    """Node names that carry identity in a SPICE comparison: ground and every user-given
    name (globals, top-level ports and labels). Generated names (yasdl's N1, KiCad's
    Net-(...)/unconnected-(...)) and KiCad's sub-block labels (FB.x) are only connectivity."""
    names = {"0"}
    for deck in decks:
        for _, nodes, _ in deck:
            names |= {n for n in nodes if not _GENERATED.match(n)}
    return names


def spice_roundtrip(block: Block, sch_path, refmap, *, kicad_text=None, yasdl_text=None) -> tuple[bool, str]:
    """Compare kicad-cli's SPICE export of the schematic with yasdl's own SPICE netlist.

    Every top-level R/C/L/D/Q, V/I and X element is compared by identity (the reference
    map), terminal connectivity, the names of ground and user-named nets (compared without
    case, as ngspice does), and value: the R/C/L number as ngspice reads it, the complete
    source specification, or the model with its parameters.
    """
    # One flat sheet: yasdl draws net names as KiCad labels, which kicad-cli qualifies with
    # the root sheet path ("/Vref"). Strip it so global identity survives the comparison.
    if kicad_text is None:
        try:
            kicad_text = export_kicad_spice(sch_path)
        except KiCadCommandFailed as e:  # e.g. a model KiCad cannot load: not equal
            return False, f"KiCad SPICE export failed: {e}"
    try:
        kicad = [
            (name, [n[1:] if n.startswith("/") else n for n in nodes], value)
            for name, nodes, value in parse_spice(kicad_text)
        ]
        ours = parse_spice(
            spice_netlist(block, validate_values=False) if yasdl_text is None else yasdl_text
        )
    except YasdlError as e:  # a deck the comparison can't read is not equal
        return False, f"unreadable SPICE deck: {e}"
    named = user_net_names(kicad, ours)
    theirs = spice_partition(kicad, lambda n: _kicad_eid(n, refmap), named)
    mine = spice_partition(ours, lambda n: _eid(n.split("_", 1)[1]), named)
    diff = _compare_spice(mine, theirs)
    if diff:
        diff.append('raw values: ours ' + repr([(n, v.casefold()) for n, _, v in ours])
                    + '; KiCad ' + repr([(n, v.casefold()) for n, _, v in kicad]))
    return not diff, "; ".join(diff)


def compare_spice(ours, theirs, *args, **kwargs):
    """compare_spice(block, kicad_text, refmap) -> (ok, diff): a SPICE text, such as a
    (possibly edited) KiCad export, against `block`'s own netlist, with the same rules as
    spice_roundtrip. Other arguments are spice.compare_spice's texts or partitions."""
    if isinstance(ours, Block):
        if len(args) != 1 or kwargs:
            raise TypeError("compare_spice(block, text, refmap)")
        return spice_roundtrip(ours, None, args[0], kicad_text=theirs)
    return _compare_spice(ours, theirs, *args, **kwargs)


def _kicad_eid(name, refmap):
    """Element id of a KiCad SPICE element: its yasdl path; an element of no yasdl part
    (an added instance) keeps a distinct id, so it is reported as extra."""
    path = kicad_element_name(name, refmap)
    if path is None:
        key = name if name in refmap else name[1:]
        return None if key in refmap else "?" + name  # ERC helpers map to None
    return _eid(path)


def _eid(path):
    return None if path is None else path.replace(".", "_")


def render(
    block: Block,
    out_dir,
    svg: bool = True,
    spice_libs: tuple = (),
    spice: bool = False,
    references: str = "annotate",
    values: bool = True,
    erc_helpers: bool = True,
    export_name: str | None = None,
    bundle_models: bool = True,
) -> dict:
    """Schematic (+ SVG) of `block` with the netlist round trip, ERC and optional SPICE round
    trip. erc_helpers=False draws no test points or power flags (a cleaner picture); ERC is
    then not run (info["erc"] is None), since it would flag exactly what the helpers fix.
    export_name: file stem for the schematic, project and SVG (default: block.name); the
    block, its bindings and its circuit are unchanged. Two bindings of one template can so
    render side by side: render(upper, "out", export_name="DarlN")."""
    check_models(block, spice_libs, require=spice)
    stem = block.name if export_name is None else export_name
    if (
        not isinstance(stem, str)
        or not stem
        or Path(stem).name != stem
        or stem in (".", "..")
        or "\\" in stem
    ):
        raise ValueError(
            f"export_name must be a plain file stem (a filename stem without directories), not {stem!r}"
        )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sch_path, refmap = to_kicad(
        block,
        out_dir / f"{stem}.kicad_sch",
        spice_libs=spice_libs,
        references=references,
        values=values,
        erc_helpers=erc_helpers,
        bundle_models=bundle_models,
    )
    ok, missing, extra = roundtrip(block, sch_path, refmap)
    info: dict[str, object] = {
        "schematic": sch_path,
        "roundtrip_ok": ok,
        "missing": missing,
        "extra": extra,
        "erc": erc(sch_path) if erc_helpers else None,
    }
    if spice:
        info["spice_ok"], info["spice_diff"] = spice_roundtrip(block, sch_path, refmap)
    if svg:
        info["svg"] = export_svg(sch_path, out_dir)
        _crop_svg(info["svg"], _BBOX[str(sch_path)])
    return info
