"""Render the examples to KiCad schematics + SVG under out/, with the netlist round-trip check."""

import sys

from examples.blocks import ALL
from yasdl.kicad_export import render

if __name__ == "__main__":
    failed = False
    for title, blk in ALL.items():
        info = render(blk, "out")
        status = "OK" if info["roundtrip_ok"] else f"MISMATCH missing={info['missing']} extra={info['extra']}"
        erc = "clean" if not info["erc"] else f"{len(info['erc'])} violations"
        print(f"{title:18s} {info['schematic']}  round-trip {status}  ERC {erc}")
        for v in info["erc"]:
            print(f"    {v}")
        failed |= not info["roundtrip_ok"] or bool(info["erc"])
    sys.exit(1 if failed else 0)
