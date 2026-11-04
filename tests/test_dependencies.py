"""Actionable errors for missing KiCad, symbol libraries/symbols, failing kicad-cli runs and
SPICE model resources; normal KiCad installation discovery (DECISIONS: dependency errors,
P2.5)."""

import os
from pathlib import Path

import pytest
from yasdl import Atom, Block, NPN, R
from yasdl import kicad_lib
from yasdl.kicad_lib import YasdlDependencyError


def _fake_cli(tmp_path, script):
    cli = tmp_path / "bin" / "kicad-cli"
    cli.parent.mkdir(parents=True, exist_ok=True)
    cli.write_text("#!/bin/sh\n" + script)
    cli.chmod(0o755)
    return cli


def test_yasdl_kicad_overrides_discovery(monkeypatch, tmp_path):
    monkeypatch.setenv("YASDL_KICAD", str(tmp_path))
    root, searched = kicad_lib.find_kicad_root()
    assert root == tmp_path and searched == [tmp_path]


def test_discovery_picks_the_first_installed_candidate(monkeypatch, tmp_path):
    monkeypatch.delenv("YASDL_KICAD", raising=False)
    empty, prefix, mac = tmp_path / "none", tmp_path / "usr", tmp_path / "Apps" / "KiCad"
    (prefix / "share" / "kicad" / "symbols").mkdir(parents=True)
    (mac / "KiCad.app" / "Contents" / "MacOS").mkdir(parents=True)
    (mac / "KiCad.app" / "Contents" / "MacOS" / "kicad-cli").touch()
    monkeypatch.setattr(kicad_lib, "KICAD_CANDIDATES", (empty, prefix, mac))
    assert kicad_lib.find_kicad_root()[0] == prefix
    monkeypatch.setattr(kicad_lib, "KICAD_CANDIDATES", (empty, mac, prefix))
    assert kicad_lib.find_kicad_root()[0] == mac
    monkeypatch.setattr(kicad_lib, "KICAD_CANDIDATES", (empty,))
    assert kicad_lib.find_kicad_root() == (empty, [empty])


def test_missing_cli_names_operation_path_and_remedy(monkeypatch, tmp_path):
    from yasdl.kicad_export import render

    monkeypatch.setattr(kicad_lib, "KICAD_CLI", tmp_path / "nope" / "kicad-cli")
    with pytest.raises(YasdlDependencyError) as e:
        render(Block("S", "{a}──R1──{b}", R1=R("1k")), tmp_path, svg=False)
    msg = str(e.value)
    assert "netlist export needs kicad-cli" in msg
    assert str(tmp_path / "nope" / "kicad-cli") in msg and "YASDL_KICAD" in msg


def test_failing_cli_reports_command_and_output(monkeypatch, tmp_path):
    from yasdl.kicad_sch import export_netlist

    cli = _fake_cli(tmp_path, 'echo "boom: library table broken" >&2\nexit 3\n')
    monkeypatch.setattr(kicad_lib, "KICAD_CLI", cli)
    with pytest.raises(YasdlDependencyError, match=r"(?s)exited with 3.*boom: library"):
        export_netlist(tmp_path / "x.kicad_sch")


def test_erc_without_report_is_an_error_not_a_pass(monkeypatch, tmp_path):
    """Before: a kicad-cli that wrote no report produced erc == [] (clean)."""
    from yasdl.kicad_export import erc

    cli = _fake_cli(tmp_path, 'echo "cannot load schematic" >&2\nexit 1\n')
    monkeypatch.setattr(kicad_lib, "KICAD_CLI", cli)
    with pytest.raises(YasdlDependencyError, match="produced no report"):
        erc(tmp_path / "x.kicad_sch")


def test_missing_library_and_symbol():
    with pytest.raises(YasdlDependencyError, match="symbol library 'NoSuchLib' not found"):
        Atom("NoSuchLib:R").symbol
    with pytest.raises(YasdlDependencyError, match=r"Device:Q_NPX not found.*did you mean"):
        Atom("Device:Q_NPX").symbol


def test_missing_symbol_dir_mentions_kicad_remedy(monkeypatch, tmp_path):
    monkeypatch.setattr(kicad_lib, "SYMBOL_DIR", tmp_path / "symbols")
    kicad_lib._library.cache_clear()
    kicad_lib.load.cache_clear()
    try:
        with pytest.raises(YasdlDependencyError, match="YASDL_KICAD"):
            Atom("Amplifier_Audio:LM386").symbol
    finally:
        kicad_lib._library.cache_clear()
        kicad_lib.load.cache_clear()


@pytest.mark.skipif(not kicad_lib.KICAD_CLI.exists(), reason="kicad-cli missing")
def test_spice_model_resources(tmp_path):
    from yasdl.kicad_export import render

    q = Block("Q", "     │\n{b}─Q1\n     │\n   [GND]", Q1=NPN("2N9999"))
    with pytest.raises(YasdlDependencyError, match=r"'2N9999' is not defined in spice_libs"):
        render(q, tmp_path, svg=False, spice=True, spice_libs=(kicad_lib.JELLYBEAN_MODEL,))
    with pytest.raises(YasdlDependencyError, match="not found"):
        render(q, tmp_path, svg=False, spice_libs=(tmp_path / "missing.lib",))
