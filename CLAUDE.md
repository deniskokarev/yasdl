# CLAUDE.md — yasdl

SPEC.md is the spec (README.md is the short overview). Read SPEC.md first, and update it in the same change whenever behaviour
changes.

## Invariants

- The canvas is the source of truth: connectivity, pin order and the layout topology all come
  from the drawing. Never infer connections that aren't drawn or named by a net label.
- Whatever the spec doesn't explicitly allow is an error, with block name, row and column. Never
  silently fix a drawing.
- Components never touch (gap rule). Names are block-local.
- Orientation only at binding, per spec 3.2: explicit → pin labels filter → best fit that
  keeps reading order. Never rotate anything on the canvas.
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
- Modules: `canvas.py` (parsing), `block.py` (binding, netlist, NC markers), `layout.py`
  (grid-bag), `kicad_lib.py` (library symbols, derived definitions, orientation, KiCad
  discovery and CLI), `kicad_sch.py` (file writer, kicad-cli), `kicad_export.py` (block →
  schematic, ERC helpers, round trips), `spice.py` (SPICE export, comparison parser),
  `sketch.py` (atomic canvas construction), `atoms.py` (atom factories, pots), `parts.py`
  (generic part factories, standard parts, packages), `resources.py` (portable model copies),
  `std.py` (standard blocks), `circuits.py` (reusable circuits) and `standard.py` (positional
  entry points to them).
- Standard topologies are literal ASCII canvases in the source; parameterized families repeat
  small literal cells or strips. Don't generate them with `Sketch`.
- Standard-part pin maps are checked against an independent reference (the exact KiCad
  symbol or the datasheet), never against the factory that produced them.
- Pin positions and sides come from the KiCad `.kicad_sym` files, never hard-coded.
- `docs/examples/blocks.py` (and `sgen.py`) are the fixtures for tests; `features.py` and
  `standard.py` render the parts, packages and reusable circuits. Each new feature gets an
  example and a test.
- `skills/yasdl-circuit-design/SKILL.md` is the agent-facing guide (symlinked into
  ~/.claude/skills). Keep it in sync with the API and spec.
- Sine-generator tests use the bundled `yasdl/lib/jellybean.lib` models and
  `tests/test_sine_generator.lib` netlist. KiCad and ngspice tests skip only when their tools
  are unavailable.
- Tests: `python -m pytest -q tests` (pytest in `~/venv`). Render: `python -m docs.examples.render`,
  output in `out/` (ignored); copy the PNGs to `docs/examples/generated/` when they change.

## KiCad

- KiCad 9.0.9 at `~/KiCad9` (override with `YASDL_KICAD`). CLI `~/KiCad9/bin/kicad-cli`;
  libraries in `~/KiCad9/share/kicad/symbols/`.
- Check orientation and transform changes with the netlist round trip, not by eye.

## Git

- Work on feature branches. Commit at milestones. Never push, never amend.
