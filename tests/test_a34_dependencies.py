import pytest
from yasdl import Block, OPAMP_IDEAL, R, YasdlError, spice_netlist
from yasdl import kicad_lib
from yasdl.kicad_export import render
from yasdl.spice import model_library


def test_missing_cli_actionable(monkeypatch,tmp_path):
    monkeypatch.setattr(kicad_lib,'KICAD_CLI',tmp_path/'missing')
    with pytest.raises(FileNotFoundError,match='YASDL_KICAD'):
        kicad_lib.require_cli('export schematic')


def test_missing_model_resource_is_not_silently_ignored(tmp_path):
    with pytest.raises(YasdlError,match='required model resource missing'):
        spice_netlist(Block('R','─R1─',R1=R('1k')),includes=(str(tmp_path/'missing.lib'),))
    with pytest.raises(YasdlError,match='cannot read') as e:
        model_library('model',[tmp_path/'missing.lib'])
    assert e.value.__cause__ is not None


def test_discovery_override(monkeypatch,tmp_path):
    monkeypatch.setenv('YASDL_KICAD',str(tmp_path))
    assert kicad_lib.discover_kicad()==tmp_path
