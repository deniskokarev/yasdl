import pytest
from yasdl import Block,R,netlist
from yasdl.kicad_export import render
from yasdl.kicad_lib import KICAD_CLI


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(),reason='KiCad unavailable')
def test_joined_child_local_buses_use_one_electrical_name(tmp_path):
    child=Block('Bus','{a}──[bus]──R1──{b}',R1=R('1k'))
    b=Block('Composite','[VCC]──A1──B1──{out}',A1=child,B1=child)
    assert netlist(b)=={'VCC':['A1.R1.1'],'out':['B1.R1.2'],'N1':['A1.R1.2','B1.R1.1']}
    info=render(b,tmp_path,spice=True)
    assert info['roundtrip_ok'] and info['spice_ok'] and info['erc']==[],info
    text=info['schematic'].read_text()
    assert '(text "A1.bus"' in text and '(text "B1.bus"' in text
    assert '(label "A1.bus"' not in text and '(label "B1.bus"' not in text
