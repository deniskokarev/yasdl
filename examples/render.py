"""Render the examples to KiCad schematics + SVG under out/: netlist round trip, ERC, and
(for simulatable designs) the KiCad-vs-yasdl SPICE round trip."""

import sys

from examples import blocks, sgen
from yasdl.kicad_export import render

if __name__ == "__main__":
    failed = False
    jobs = [(t, b, {}) for t, b in blocks.ALL.items()]
    jobs += [(t, b, {"spice_libs": (sgen.BJT_MODELS,), "spice": True}) for t, b in sgen.ALL.items()]
    for title, blk, opts in jobs:
        info = render(blk, "out", **opts)
        status = "OK" if info["roundtrip_ok"] else f"MISMATCH missing={info['missing']} extra={info['extra']}"
        erc = "clean" if not info["erc"] else f"{len(info['erc'])} violations"
        spice = "" if "spice_ok" not in info else f"  SPICE {'OK' if info['spice_ok'] else info['spice_diff']}"
        print(f"{title:18s} {info['schematic']}  round-trip {status}  ERC {erc}{spice}")
        for v in info["erc"]:
            print(f"    {v}")
        failed |= not info["roundtrip_ok"] or bool(info["erc"]) or info.get("spice_ok") is False
    sys.exit(1 if failed else 0)
