import pytest
from yasdl import Block, R, netlist, YasdlError
from yasdl.kicad_export import render
from yasdl.kicad_lib import KICAD_CLI


@pytest.mark.parametrize('stem',['','../escape','/abs','a/b','a\\b','..'])
def test_invalid_stems(tmp_path,stem):
    with pytest.raises(ValueError,match='filename stem'):
        render(Block('R','─R1─',R1=R('1k')),tmp_path,export_name=stem)


def test_diagnostic_excerpt_and_original_coordinates():
    with pytest.raises(YasdlError,match=r'original source 3:5') as e:
        Block('Bad','\n    R1\n    .')
    assert '^' in str(e.value)
    with pytest.raises(YasdlError,match='reduces to'):
        Block('Repeated','─RR─',RR=R('1k'))
