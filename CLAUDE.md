# CLAUDE.md — yasdl

README.md is the spec. Read it first, and update it in the same change whenever behaviour
changes.

## Invariants

- The canvas is the source of truth: connectivity, pin order and the layout topology all come
  from the drawing. Never infer connections that aren't drawn or named by a net label.
- Whatever the spec doesn't explicitly allow is an error, with block name, row and column. Never
  silently fix a drawing.
- Components never touch (gap rule). Names are block-local.
- No automatic rotation beyond spec 3.2 (explicit → pin labels → library orientation →
  forced for symmetric parts).
- Symbols are rigid; only wires stretch. All coordinates stay on the 1.27 mm grid.
- The schematic and the netlist come from the same Block. A renderer change is only done when
  the round-trip check passes for every example: KiCad's exported netlist equals
  `yasdl.netlist()`.
- Exported schematics must pass KiCad ERC (errors and warnings) with no help from the drawing;
  add export-time helpers instead of changing the ASCII spec.
- For simulatable examples, kicad-cli's SPICE export must equal `spice_netlist()`.
- Don't use SKiDL or its pin/net model.

## Code

- Python 3.12, stdlib only (no runtime dependencies).
- Modules: `canvas.py` (parsing), `block.py` (binding, netlist), `layout.py` (grid-bag),
  `kicad_lib.py` (library symbols, orientation), `kicad_sch.py` (file writer, kicad-cli),
  `kicad_export.py` (block → schematic, ERC helpers, round trips), `spice.py` (SPICE export).
- Pin positions and sides come from the KiCad `.kicad_sym` files, never hard-coded.
- `examples/blocks.py` is the fixture for tests. Each new feature gets an example and a test.
- Tests: `python -m pytest -q tests` (pytest in `~/venv`). Render: `python -m examples.render`,
  output in `out/` (ignored); copy the PNGs to `docs/examples/` when they change.

## KiCad

- KiCad 9.0.9 at `~/KiCad9` (override with `YASDL_KICAD`). CLI `~/KiCad9/bin/kicad-cli`;
  libraries in `~/KiCad9/share/kicad/symbols/`.
- Check orientation and transform changes with the netlist round trip, not by eye.

## Git

- Work on feature branches. Commit at milestones. Never push, never amend.
