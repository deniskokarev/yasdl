"""Diagnostics: errors carry the block, positions in canvas and source coordinates, an
excerpt with a caret, ragged-row extents, KMP-collapse hints and binding candidates."""

import re

import pytest
from yasdl import Block, C, NPN, OPAMP, R, YasdlError


def error(*args, **kw):
    with pytest.raises(YasdlError) as e:
        Block(*args, **kw)
    return str(e.value)


def test_excerpt_and_source_coordinates():
    msg = error(
        "Dang",
        """

            {a}──R1──  R2
        """,
        R1=R("1k"),
    )
    # canvas row 0 (two blank lines removed), col 8 (12 columns of indentation removed)
    assert "dangling wire" in msg
    assert "at row 0, col 8 (canvas string line 3, column 21)" in msg
    lines = msg.splitlines()
    assert lines[1].endswith("0 | {a}──R1──  R2")
    assert lines[2].index("^") - lines[2].index("|") - 2 == 8


def test_ragged_component_lists_row_extents_and_points_at_the_shifted_row():
    msg = error("Rag", "──Q1Q1\n  Q1Q1\n   Q1Q1\n")
    assert "row 0: 'Q1Q1' at cols 2-5; row 1: 'Q1Q1' at cols 2-5; row 2: 'Q1Q1' at cols 3-6" in msg
    assert "at row 2, col 3" in msg
    assert re.search(r"2 \|    Q1Q1\n +\|    \^", msg)


def test_non_identical_rows_are_listed():
    msg = error("Rows", "──U1U1──\n  U2U2\n")
    assert "row 0: 'U1U1'" in msg and "row 1: 'U2U2'" in msg


def test_collapsed_name_hint():
    msg = error("T", "──CC──", CC=C("1n"))
    assert "drawn as 'CC' is named 'C'" in msg and "C1" in msg


def test_binding_failure_shows_labels_and_candidates():
    msg = error(
        "Amp",
        """
             │
        ─────U1U1──
           ┌+U1U1
           │ {V-}
         [GND] │
             [VCC]
        """,
        U1=OPAMP(),
    )
    assert "drawn attachments (labels; - = none): N=[-] E=[-] S=[V-] W=[-, +]" in msg
    assert "orientation rot=0 mirror=None" in msg and "label '+' on W is pin 2:-" in msg
    assert "orientation rot=0 mirror=x" in msg and "label 'V-' on S is pin 3:V+" in msg


def test_binding_failure_without_candidates():
    msg = error("Q", "──Q1──", Q1=NPN("2N3904"))
    assert "no orientation has the drawn number of pins on every side" in msg
