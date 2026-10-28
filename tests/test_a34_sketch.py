import pytest
from yasdl import Block, R, Sketch, netlist
from yasdl.sketch import SketchError


def test_route_corners_and_atomic_failure():
    s=Sketch().wire([(0,0),(0,3),(3,3),(3,0)])
    assert s.render()=='───┐\n   │\n   │\n───┘'
    before=s.render()
    for op in [lambda:s.text(0,0,'─'),lambda:s.hline(0,0,6),lambda:s.box(0,2,'R1',2),
               lambda:s.wire([(2,0),(2,3),(5,3)]),lambda:s.wire([(4,0),(4,3),(4,0)])]:
        with pytest.raises(SketchError): op()
        assert s.render()==before


@pytest.mark.parametrize('obstacle',['─','┌','├','┼','R','['])
def test_endpoint_and_text_are_never_crossings(obstacle):
    s=Sketch().text(2,2,obstacle)
    before=s.render()
    with pytest.raises(SketchError): s.vline(2,0,2,cross=1)
    assert s.render()==before


def test_multiple_crossings_and_box_atomicity():
    s=Sketch().hline(1,0,5).hline(3,0,5)
    before=s.render()
    with pytest.raises(SketchError): s.wire([(0,2),(4,2)],cross=1)
    assert s.render()==before
    s.wire([(0,2),(4,2)],cross=2)
    assert len(s.crossings)==2
    before=s.render()
    with pytest.raises(SketchError): s.box(0,0,'R1',4)
    assert s.render()==before
