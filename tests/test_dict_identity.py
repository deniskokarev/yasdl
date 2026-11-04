from yasdl import Block,R


def test_distinct_bound_variants_and_repeated_instances():
    first=Block('Variant','─R1─',R1=R('1k'))
    second=first.bind(R1=R('2k'))
    top=Block('Top','─A1─B1─C1─',A1=first,B1=second,C1=first)
    data=top.to_dict();children=data['blocks']
    refs={key:part['binding']['block'] for key,part in data['components'].items()}
    assert refs['A1']==refs['C1'] and refs['A1']!=refs['B1']
    assert len(children)==2
    assert children[refs['A1']]['components']['R1']['binding']['value']=='1k'
    assert children[refs['B1']]['components']['R1']['binding']['value']=='2k'
    assert first.name==second.name=='Variant'


def test_nested_equal_names_do_not_become_self_references():
    leaf=Block('Bank','─R1─',R1=R('1k'))
    mid=Block('Bank','─U1─',U1=leaf)
    root=Block('Bank','─U1─',U1=mid)
    data=root.to_dict()
    assert len(data['blocks'])==2
    for key,child in data['blocks'].items():
        assert child is not None and child['name']=='Bank'
        for part in child['components'].values():
            assert part['binding'].get('block')!=key
