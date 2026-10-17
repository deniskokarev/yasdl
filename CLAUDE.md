# CLAUDE.md — yasdl

Read README.md first: it defines the model. Keep it in sync when the model changes.

## Model invariants (don't break these)

- The grid is the source of truth. Connectivity comes only from touching cell edges.
- Planar by construction: no wire crossings; `┼` is always a junction.
- At most one connection per cell side; connections sit on edge midpoints.
- Neighbouring cells must agree on their shared edge; anything else is an error, never
  silently fixed.
- Outer ports are inferred from boundary connections, never declared separately.
- Holes are filled or exported explicitly; a top-level design has no holes.
- The drawing, the netlist and the SPICE output come from the same block object.
- Stretching goes into wires, never into symbols. Multi-pin symbols are rigid.
- Don't use SKiDL or its pin/net model.

## Code

- Python 3.12, stdlib-only core (`yasdl/`). KiCad specifics live in `atoms.py` and,
  later, an export module.
- Atom ports are written in the KiCad symbol's library orientation, taken from the
  `.kicad_sym` files, not guessed.
- Errors raise `YasdlError` with the block name and the row/column involved.
- `examples/blocks.py` doubles as the test fixture. Each new feature gets an example and a
  test in `tests/`.
- Run tests: `python -m pytest -q tests` (pytest is in `~/venv`).

## KiCad

- KiCad 9.0.9 is at `~/KiCad9`. CLI: `~/KiCad9/bin/kicad-cli`; symbol libraries:
  `~/KiCad9/share/kicad/symbols/`.
- A renderer is only "working" once its output passes the round-trip check: `kicad-cli sch
  export netlist` on the generated schematic matches `yasdl.netlist()`.

## Git

- Commit when asked or at a natural milestone. Never push, never amend.
