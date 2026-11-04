"""P1/P2: diagnostic context in errors, and actionable dependency errors (spec 7.2, 6.1)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from yasdl import Atom, Block, C, NPN, R, spice_netlist, SpiceModel, YasdlError
from yasdl.canvas import Canvas, CanvasError
from yasdl.kicad_lib import DependencyError, KICAD_CLI, load, SymbolNotFound

ROOT = Path(__file__).resolve().parent.parent


def test_canvas_error_shows_rows_caret_and_source_position():
    text = "\n\n        {a}──R1──\n\n        {b}──R2──┐\n"
    with pytest.raises(CanvasError) as err:
        Canvas(text, "Demo")
    msg = str(err.value)
    # parsed canvas: 2 leading blank lines and 8 columns of indentation removed
    assert "dangling wire (arm E points at an empty cell) at row 0, col 8" in msg
    assert "canvas row 0, col 8 = source line 3, column 17" in msg
    assert "2 leading blank line(s) and 8 column(s) of indentation removed" in msg
    lines = msg.splitlines()
    caret = next(i for i, x in enumerate(lines) if x.rstrip().endswith("^"))
    assert lines[caret - 1].endswith("{a}──R1──")
    assert lines[caret].index("^") - lines[caret].index("|") - 2 == 8


def test_ragged_component_lists_each_row_extent():
    with pytest.raises(CanvasError) as err:
        Canvas("──Q1Q1\n   Q1Q1\n")
    msg = str(err.value)
    assert "row 0: 'Q1Q1' at cols 2-5; row 1: 'Q1Q1' at cols 3-6" in msg
    assert "span rows 0-1, cols 2-6" in msg


def test_collapsed_name_hint():
    with pytest.raises(YasdlError, match=r"drawn as 'CC' is named 'C'"):
        Block("T", "──CC──", CC=C("1n"))


def test_binding_failure_shows_signature_labels_and_candidates():
    with pytest.raises(YasdlError) as err:
        Block("Bad", "     │\n──{e}Q1\n     Q1\n     │\n", Q1=NPN("2N3904"))
    msg = str(err.value)
    assert "does not fit its drawing" in msg
    assert "drawn attachments: N: col 5; S: col 5; W: row 1 label 'e'" in msg
    assert "rot 0 mirror None: N: C; S: E; W: B -> label mismatch: 'e' at W row 1 vs B" in msg
    assert "pin counts differ" in msg


def test_missing_symbol_and_library_errors_name_paths():
    with pytest.raises(SymbolNotFound) as err:
        load("Device:DoesNotExist")
    msg = str(err.value)
    assert "Device:DoesNotExist" in msg and "Device.kicad_sym" in msg and "searched" in msg
    assert isinstance(err.value, KeyError)  # older callers caught KeyError
    with pytest.raises(SymbolNotFound) as err:
        load("NoSuchLibrary:X")
    assert "NoSuchLibrary.kicad_sym" in str(err.value) and "YASDL_KICAD" in str(err.value)
    with pytest.raises(NotImplementedError, match="AtomNPN"):
        load("Transistor_BJT:2N3904")  # inherited symbol: points at the generic factories


def test_missing_model_library_is_a_dependency_error(tmp_path):
    part = Atom("Device:R", "x", spice=SpiceModel("X", ("1", "2"), "m", "1=a 2=b",
                                                   str(tmp_path / "missing.lib")))
    with pytest.raises(DependencyError) as err:
        spice_netlist(Block("M", "{a}──RX──{b}", RX=part))
    assert "missing.lib" in str(err.value) and "model 'm'" in str(err.value)


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(), reason="kicad-cli missing")
def test_render_reports_unresolved_models_and_missing_spice_libs(tmp_path):
    from yasdl.kicad_export import render

    q = Block("Q", " │\n─Q1\n Q1\n │\n", Q1=NPN("NOSUCHMODEL"))
    with pytest.raises(DependencyError) as err:
        render(q, tmp_path, svg=False, spice=True, spice_libs=(str(ROOT / "yasdl/lib/jellybean.lib"),))
    assert "NOSUCHMODEL" in str(err.value) and "jellybean.lib" in str(err.value)
    info = render(q, tmp_path, svg=False)  # without spice=True the schematic is still written
    assert info["roundtrip_ok"]
    with pytest.raises(DependencyError, match="does not exist"):
        render(q, tmp_path, svg=False, spice_libs=(str(tmp_path / "nope.lib"),))


def _run_isolated(code, env_extra):
    env = {k: v for k, v in os.environ.items() if k != "YASDL_KICAD"}
    env.update(env_extra)
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          env=env, cwd=ROOT, timeout=120)


def test_missing_kicad_cli_error_is_actionable(tmp_path):
    code = (
        "from yasdl import Block, R\n"
        "from yasdl.kicad_export import render\n"
        "from yasdl.kicad_lib import DependencyError\n"
        "try:\n"
        "    render(Block('B', '{a}──R1──{b}', R1=R('1k')), r'%s', svg=False)\n"
        "except DependencyError as e:\n"
        "    print('ERR', e)\n" % tmp_path
    )
    out = _run_isolated(code, {"YASDL_KICAD": str(tmp_path / "nowhere")})
    assert out.returncode == 0, out.stderr
    msg = out.stdout
    assert msg.startswith("ERR ")
    assert "kicad-cli" in msg and str(tmp_path / "nowhere") in msg and "YASDL_KICAD" in msg


def test_discovery_order_without_override():
    out = _run_isolated(
        "from yasdl import kicad_lib as k; print([str(p) for p in k.kicad_candidates()][:5])",
        {},
    )
    assert out.returncode == 0, out.stderr
    roots = eval(out.stdout)
    assert roots[0].endswith("KiCad9") and "/Applications/KiCad" in roots and "/usr" in roots


def test_override_wins(tmp_path):
    out = _run_isolated("from yasdl import kicad_lib as k; print(k.KICAD_ROOT, k.KICAD_CLI)",
                        {"YASDL_KICAD": str(tmp_path)})
    assert out.stdout.split() == [str(tmp_path), str(tmp_path / "bin" / "kicad-cli")]
