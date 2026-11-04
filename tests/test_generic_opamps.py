import pytest
from yasdl import AtomOpamp3,AtomOpamp5,Block,Package,R,SpiceModel,YasdlError,netlist,spice_netlist
from yasdl import standard
from yasdl.kicad_export import render
from yasdl.kicad_lib import KICAD_CLI


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(),reason='KiCad unavailable')
def test_generic_opamp_physical_maps_and_powered_wrapper_mirror(tmp_path):
    lib=tmp_path/'opamp.lib'
    lib.write_text('.subckt realop inp inn vp vm out\nB1 out 0 V={1e6*(V(inp)-V(inn))}\n.ends\n.subckt ideal inp inn out\nB1 out 0 V={1e6*(V(inp)-V(inn))}\n.ends\n')
    real=AtomOpamp5('Real',{'inp':3,'inn':2,'out':1,'vp':8,'vm':4},lib,'realop')
    three=AtomOpamp3('Ideal',{'inp':5,'inn':6,'out':7},spice=SpiceModel('X',('5','6','7'),'ideal','5=inp 6=inn 7=out',str(lib)))
    wrapper=standard.powered_opamp(real)
    amp=standard.inverting('10k','20k',opamp=wrapper)
    expected=netlist(amp)
    assert expected['VCC']==['U1.U1.8'] and expected['VEE']==['U1.U1.4']
    assert expected['GND']==['U1.U1.3']
    for b in (amp,standard.follower(three)):
        info=render(b,tmp_path,spice=True)
        assert info['roundtrip_ok'] and info['spice_ok'] and info['erc']==[],info


def test_model_order_requires_every_role(tmp_path):
    with pytest.raises(YasdlError,match='all five opamp roles'):
        AtomOpamp5('Bad',{'inp':3,'inn':2,'out':1,'vp':8,'vm':4},tmp_path/'model.lib','opamp',model_order=('inp','inp','vp','vm','out'))


def test_package_physical_ports_are_independent_reference_map():
    from test_devices import package_block
    b=package_block(Package())
    assert netlist(b)=={'a':['A1.U1.3'],'oa':['A1.U1.1','A1.U1.2'],
                      'b':['B1.U1.5'],'ob':['B1.U1.6','B1.U1.7'],
                      'VCC':['P1.U1.8'],'VEE':['P1.U1.4']}


def test_generic_role_aliases_ignore_case(tmp_path):
    real=AtomOpamp5('Real',{'inp':3,'inn':2,'out':1,'vp':8,'vm':4},tmp_path/'model.lib','realop')
    wrapper=standard.powered_opamp(real)
    canvas=wrapper.text.replace('{V+}','{VP}').replace('{V-}','{VM}')
    b=Block('UppercaseSupplyRoles',canvas,U1=real)
    assert netlist(b)['VCC']==['U1.8'] and netlist(b)['VEE']==['U1.4']
