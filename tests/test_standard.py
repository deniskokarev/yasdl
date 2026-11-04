import re
import shutil
import subprocess
import pytest
from yasdl import Block, YasdlError, netlist, spice_netlist
from yasdl import standard as s
from yasdl.kicad_export import render
from yasdl.kicad_lib import KICAD_CLI,JELLYBEAN_MODEL


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(),reason='KiCad unavailable')
@pytest.mark.parametrize('variant',['bjt','darlington','sziklai'])
def test_compound_push_pull_exports_and_bias(variant,tmp_path):
    b=s.push_pull(variant)
    assert len([l for l in spice_netlist(b).splitlines() if l.startswith('D_')])==(4 if variant=='darlington' else 2)
    info=render(b,tmp_path,spice_libs=(JELLYBEAN_MODEL,),spice=True)
    assert info['roundtrip_ok'] and info['spice_ok'] and info['erc']==[],info


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which('ngspice'),reason='ngspice unavailable')
@pytest.mark.parametrize('variant',['bjt','darlington','sziklai'])
def test_push_pull_characterization(variant,tmp_path):
    b=s.push_pull(variant)
    deck=tmp_path/'tb.cir'
    deck.write_text(spice_netlist(b,subckt='stage',port_order=['in','out'],includes=(str(JELLYBEAN_MODEL),))+
     'VP VCC 0 6\nVN VEE 0 -6\nVIN in 0 sin(0 0.1 1000)\nX1 in out stage\nRL out 0 1k\n'
     '.control\ntran 1u 10m\nmeas tran vrms rms v(out) from=5m to=10m\nmeas tran vmean avg v(out) from=5m to=10m\n.endc\n.end\n')
    r=subprocess.run(['ngspice','-b',str(deck)],capture_output=True,text=True)
    assert 'failed' not in (r.stdout+r.stderr).lower()
    val=float(re.search(r'vrms\s*=\s*(\S+)',r.stdout)[1])
    mean=float(re.search(r'vmean\s*=\s*(\S+)',r.stdout)[1])
    val=max(0,val*val-mean*mean)**.5
    assert abs(mean)<1
    assert .045<val<.085 # emitter follower near 0.1/sqrt(2), independently chosen range


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(),reason='KiCad unavailable')
@pytest.mark.parametrize('factory',[s.darlington,lambda:s.darlington(True),lambda:s.sziklai(True),s.current_mirror,
                                    lambda:s.current_mirror('100'),s.differential_pair,lambda:s.differential_pair('100'),
                                    s.follower,s.sallen_key],
                         ids=['darlington','darlington_pnp','sziklai_pnp','current_mirror','current_mirror_degenerated',
                              'differential_pair','differential_pair_degenerated','follower','sallen_key'])
def test_standard_blocks_real_exports(factory,tmp_path):
    b=factory()
    info=render(b,tmp_path,spice_libs=(JELLYBEAN_MODEL,),spice=True)
    assert info['roundtrip_ok'] and info['spice_ok'] and info['erc']==[],info


def test_invalid_variants():
    with pytest.raises(YasdlError): s.push_pull('wrong')
    with pytest.raises(YasdlError): s.rc_filter('wrong')


def test_basic_and_degenerated_differential_pairs_are_distinct_topologies():
    basic=netlist(s.differential_pair())
    assert any(set(ps)=={'A1.Q1.1','B1.Q1.1','RT.1'} for ps in basic.values())
    deg=netlist(s.differential_pair('100'))
    assert any(set(ps)=={'A1.RE.2','B1.RE.2','RT.1'} for ps in deg.values())
