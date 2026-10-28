import shutil
import subprocess
import re
import pytest
from yasdl import AtomNPN, Block, NC, Package, POT, R, YasdlError, netlist, spice_netlist
from yasdl.kicad_lib import JELLYBEAN_MODEL, KICAD_CLI, load
from yasdl.kicad_export import render
from yasdl.sexp import parse,find,find_all


def test_generic_maps_and_metadata_are_independent():
    baseline=load('Device:Q_NPN')
    a=AtomNPN('2N3904',{'e':1,'b':2,'c':3},JELLYBEAN_MODEL,footprint='TO92',datasheet='source')
    b=AtomNPN('BD139',{'e':1,'b':3,'c':2},JELLYBEAN_MODEL)
    assert {(p.name,p.number) for p in a.symbol.pins}=={('E','1'),('B','2'),('C','3')}
    assert {(p.name,p.number) for p in b.symbol.pins}=={('E','1'),('B','3'),('C','2')}
    assert a.lib_id!=b.lib_id
    a.symbol.sexp[1]='corrupt_copy'
    assert a.symbol.sexp[1]!='corrupt_copy'
    assert [(p.name,p.number) for p in baseline.pins]==[('B','B'),('C','C'),('E','E')]
    with pytest.raises(TypeError): a.aliases['e']='9'


@pytest.mark.parametrize('pins',[{'e':1,'b':2},{'e':1,'b':1,'c':3},{'e':0,'b':2,'c':3}])
def test_invalid_physical_maps(pins):
    with pytest.raises(YasdlError): AtomNPN('Bad',pins,JELLYBEAN_MODEL)


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(),reason='KiCad unavailable')
def test_nc_groups_keep_independent_nets_and_model_terminals(tmp_path):
    b=Block('NCGroup','X1─R1─{a}\nX1\nX1─R2─{b}\nX1\nX1─R3─{c}',X1=NC(),R1=R('1k'),R2=R('2k'),R3=R('3k'))
    nets=netlist(b)
    assert len(nets)==6 and all(not p.startswith('X1.') for ps in nets.values() for p in ps)
    assert len([l for l in spice_netlist(b).splitlines() if l.startswith('R_')])==3
    info=render(b,tmp_path,spice=True)
    assert info['roundtrip_ok'] and info['spice_ok'] and info['erc']==[],info
    root=parse(info['schematic'].read_text())
    assert len(find_all(root,'no_connect'))==3
    assert all(find(s,'lib_id')[1]!='yasdl:NC' for s in find_all(root,'symbol'))


def test_nc_child_single_pin_and_fanout_conflicts():
    single=Block('Single','{a}─R1─{b}',R1=R('1k'))
    good=Block('Good','X1─U1─{out}',X1=NC(),U1=single)
    assert len(netlist(good))==2
    fan=Block('Fan','{a}─┬─R1─{b}\n    │\n    R2\n    │\n  [GND]',R1=R('1k'),R2=R('2k'))
    with pytest.raises(YasdlError,match='one isolated device pin'):
        netlist(Block('Bad','X1─U1─{out}',X1=NC(),U1=fan))
    with pytest.raises(YasdlError): netlist(Block('NoPin','X1─{out}',X1=NC()))


def package_block(chip):
    # Units in separate child Blocks, each used as a unity buffer.
    def channel(key):
        return Block('Channel'+key,'''
{in}──+U1U1
    ┌──U1U1──┬──{out}
    │        │
    └────────┘
        ''',U1=chip.unit(key))
    power=Block('Power','[VCC]\n  │\n {vp}\n  U1\n {vm}\n  │\n[VEE]',U1=chip.unit('C'))
    return Block('Dual','{a}──A1──{oa}\n\n{b}──B1──{ob}\n\nP1',A1=channel('A'),B1=channel('B'),P1=power)


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(),reason='KiCad unavailable')
def test_one_package_units_and_spice(tmp_path):
    chip=Package()
    b=package_block(chip)
    info=render(b,tmp_path,spice=True)
    assert info['roundtrip_ok'] and info['spice_ok'] and info['erc']==[],info
    root=parse(info['schematic'].read_text())
    units=[s for s in find_all(root,'symbol') if find(s,'lib_id')[1].startswith('yasdl_parts:')]
    assert len(units)==3
    assert {str(find(s,'unit')[1]) for s in units}=={'1','2','3'}
    assert len({next(p[2] for p in find_all(s,'property') if p[1]=='Reference') for s in units})==1
    assert len([l for l in spice_netlist(b).splitlines() if l.startswith('X_')])==1
    assert set(p.rsplit('.',1)[1] for ps in netlist(b).values() for p in ps)==set('12345678')


def test_package_duplicate_and_missing_units():
    chip=Package()
    with pytest.raises(YasdlError,match='requires A/B/C'):
        netlist(Block('Missing','{a}─+U1U1\n{b}──U1U1─{out}',U1=chip.unit('A')))
    duplicate=Block('Double','{a}──A1──{oa}\n{b}──A1──{ob}\n\n{c}──B1──{oc}\n{d}──B1──{od}',A1=package_block(chip),B1=package_block(chip))
    with pytest.raises(YasdlError,match='duplicate package unit'): netlist(duplicate)


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which('ngspice'),reason='ngspice unavailable')
@pytest.mark.parametrize('position,expected',[(0,0),(.25,3),(1,12)])
def test_pot_endpoints_and_direction(tmp_path,position,expected):
    b=Block('Pot','[VCC]─{cw}P1{ccw}─[GND]\n         {wiper}\n            │\n          {out}',P1=POT('10k',position))
    deck=tmp_path/'pot.cir'
    deck.write_text(spice_netlist(b,subckt='pot')+'V1 VCC 0 12\nX1 out pot\n.control\nop\nprint v(out)\n.endc\n.end\n')
    r=subprocess.run(['ngspice','-b',str(deck)],capture_output=True,text=True)
    assert float(re.search(r'v\(out\) = (\S+)',r.stdout)[1])==pytest.approx(expected,abs=1e-6)


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(),reason='KiCad unavailable')
def test_vertical_nc_groups_and_hierarchical_isolation(tmp_path):
    b=Block('VerticalNC','''
       X1X1X1X1X1X1
       │   │   │
       R1  R2  R3
       │   │   │
     {a} {b} {c}
    ''',X1=NC(),R1=R('1k'),R2=R('2k'),R3=R('3k'))
    info=render(b,tmp_path,spice=True)
    assert info['roundtrip_ok'] and info['spice_ok'] and info['erc']==[],info
    single=Block('Single','{a}─R1─{b}',R1=R('1k'))
    b=Block('HierNC','X1─U1─{out}',X1=NC(),U1=single)
    info=render(b,tmp_path,spice=True)
    assert info['roundtrip_ok'] and info['spice_ok'] and info['erc']==[],info


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(),reason='KiCad unavailable')
def test_explicit_nc_supply_pins_get_no_power_flags(tmp_path):
    from yasdl import AtomOpamp5
    lib=tmp_path/'opamp.lib';lib.write_text('.subckt op inp inn vp vm out\nB1 out 0 V={V(inp)-V(inn)}\n.ends\n')
    real=AtomOpamp5('NCOpamp',{'inp':1,'inn':2,'vp':3,'vm':4,'out':5},lib,'op')
    b=Block('NCSupplies','''
           X1
            │
{a}────────+U1U1
{b}─────────U1U1──{out}
            │
           X2
    ''',X1=NC(),X2=NC(),U1=real)
    info=render(b,tmp_path,spice=True)
    assert info['roundtrip_ok'] and info['spice_ok'] and info['erc']==[],info
    assert 'PWR_FLAG' not in info['schematic'].read_text()
