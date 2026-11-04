"""P0: real KiCad exports and independent negative controls."""
import pytest
from yasdl import Atom, Block, I, R, SpiceModel, V, YasdlError, spice_netlist
from yasdl.kicad_export import compare_spice, export_kicad_spice, render, to_kicad
from yasdl.kicad_lib import KICAD_CLI


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(), reason="KiCad CLI unavailable")
@pytest.mark.parametrize("source", ["dc 0 ac 1", "pulse(0 1 0 1n 1n 1m 2m)", "sin(0 1 41)"])
@pytest.mark.parametrize("current_spec", ["dc 0 ac 1m", "pulse(0 1m 0 1n 1n 1m 2m)", "sin(0 1m 41)"])
def test_p0_real_sources_x_parameters_and_mutations(tmp_path, source, current_spec):
    lib = tmp_path / 'trim.lib'
    lib.write_text('.subckt trim a b params: r=1k\nR1 a b {r}\n.ends\n')
    x = Atom('Device:R', 'trim', spice=SpiceModel('X', ('1','2'), 'trim',
                 '1=a 2=b', str(lib), 'r=2k'))
    b = Block('Bench', '''
      [Drive]──X1──[GND]

      [Drive]──R1──[GND]

      [Drive]  [Drive]
         │        │
         +        +
         V1       I1
         │        │
       [GND]    [GND]
    ''', X1=x, R1=R('1k'), V1=V(source), I1=I(current_spec))
    info = render(b, tmp_path, svg=False, spice=True)
    assert info['roundtrip_ok'] and info['spice_ok'], info.get('spice_diff')
    assert info['erc'] == []
    _, refs = to_kicad(b, tmp_path/'check.kicad_sch')
    text = export_kicad_spice(info['schematic'])
    assert compare_spice(b, text, refs)[0]
    lines = [l for l in text.splitlines() if l and l[0] in 'XVI']
    assert len(lines) == 3
    for line in lines:
        assert not compare_spice(b, text.replace(line, ''), refs)[0]
        tokens=line.split()
        tokens[1]='changed_node'
        assert not compare_spice(b, text.replace(line, ' '.join(tokens)), refs)[0]
    assert not compare_spice(b, text.replace('trim r=2k', 'other r=2k'), refs)[0]
    assert not compare_spice(b, text.replace('r=2k', 'r=3k'), refs)[0]
    iline=next(l for l in lines if l.startswith('I'))
    assert not compare_spice(b, text.replace(iline, iline.replace('1m', '2m')), refs)[0]
    vline=next(l for l in lines if l.startswith('V'))
    assert not compare_spice(b, text.replace(vline, vline+' ac 2'), refs)[0]
    assert not compare_spice(b, text.replace('GND', 'fake_ground'), refs)[0]
    assert not compare_spice(b, text.replace('Drive', 'fake_global'), refs)[0]


def test_port_order_rejects_duplicate_aliases():
    b=Block('R', '{a}──R1──{b}',R1=R('1k'))
    with pytest.raises(YasdlError,match='every port once'):
        spice_netlist(b,subckt='r',port_order=['a','a'])


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(),reason='KiCad unavailable')
@pytest.mark.parametrize('value,agrees',[('1MEG',True),('1m',True),('1M',False)])
def test_explicit_mega_and_milli_convention(tmp_path,value,agrees):
    info=render(Block('Scale','{a}──R1──{b}',R1=R(value)),tmp_path,svg=False,spice=True)
    assert info['roundtrip_ok'] and info['erc']==[]
    assert info['spice_ok']==agrees
