import shutil
import pytest
from yasdl import Atom,Block,SpiceModel
from yasdl.kicad_export import render,spice_roundtrip,to_kicad
from yasdl.kicad_lib import KICAD_CLI
from yasdl.resources import copy_model_resource


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(),reason='KiCad unavailable')
def test_nested_models_move_without_originals(tmp_path,monkeypatch):
    src=tmp_path/'source';src.mkdir()
    (src/'inner.lib').write_text('.subckt resistor a b\nR1 a b 1k\n.ends\n')
    (src/'outer.lib').write_text('.include "inner.lib"\n.subckt outer a b\nX1 a b resistor\n.ends\n')
    b=Block('Portable','{a}──U1──{b}',U1=Atom('Device:R','outer',spice=SpiceModel('X',('1','2'),'outer','1=a 2=b',str(src/'outer.lib'))))
    generated=tmp_path/'generated'
    info=render(b,generated,spice=True)
    assert info['roundtrip_ok'] and info['spice_ok'] and info['erc']==[],info
    _,refs=to_kicad(b,generated/'reference.kicad_sch')
    moved=tmp_path/'moved';shutil.copytree(generated,moved)
    shutil.rmtree(src)
    monkeypatch.chdir(tmp_path)
    # Ours requires its descriptor source when regenerated; comparison can use a model
    # descriptor aimed at the already copied resource, with identical physical identity.
    resource=next((moved/'spice_models').glob('*outer.lib'))
    c=Block('Portable','{a}──U1──{b}',U1=Atom('Device:R','outer',spice=SpiceModel('X',('1','2'),'outer','1=a 2=b',str(resource))))
    assert spice_roundtrip(c,moved/'Portable.kicad_sch',refs)[0]


def test_missing_nested_resource_and_cycles(tmp_path):
    root=tmp_path/'root.lib';root.write_text('.include missing.lib\n')
    with pytest.raises(FileNotFoundError,match='missing.lib'):copy_model_resource(root,tmp_path/'out')
    root.write_text('.include root.lib\n')
    with pytest.raises(ValueError,match='cyclic'):copy_model_resource(root,tmp_path/'out')


def test_same_parent_text_distinct_nested_models_do_not_collide(tmp_path):
    cache={};copies=[]
    for i,value in enumerate(('1k','2k')):
        src=tmp_path/str(i);src.mkdir()
        (src/'child.lib').write_text('.subckt child a b\nR1 a b '+value+'\n.ends\n')
        (src/'parent.lib').write_text('.include child.lib\n')
        copies.append(copy_model_resource(src/'parent.lib',tmp_path/'out',cache))
    assert copies[0]!=copies[1]
    assert copies[0].read_text()!=copies[1].read_text()
