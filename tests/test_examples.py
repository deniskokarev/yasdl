import pytest

from examples import blocks as ex
from yasdl import NPN, R, Block, Hole, YasdlError, netlist


def net_of(nets, pin):
    return next(set(p) for p in nets.values() if pin in p)


def test_all_examples_build():
    for blk in ex.ALL.values():
        assert netlist(blk)


def test_series_rotates_into_a_row():
    assert ex.SERIES2.ports == [("E", 0), ("W", 0)]
    nets = netlist(ex.SERIES2)
    assert len(nets) == 3  # in, middle, out


def test_parallel_and_series_parallel():
    nets = netlist(ex.SERIES_PARALLEL)
    assert {"R1.1", "P.R1.2", "P.R2.2"} <= net_of(nets, "R1.1")


def test_darlington_has_npn_signature():
    assert sorted(s for s, _ in ex.DARLINGTON.ports) == ["N", "S", "W"]
    nets = netlist(ex.DARLINGTON)
    assert net_of(nets, "Q1.E") == {"Q1.E", "Q2.B"}
    assert net_of(nets, "Q1.C") == {"Q1.C", "Q2.C"}


def test_ce_amp_feedback_and_transistor_swap():
    nets = netlist(ex.CE_NPN)
    assert {"Q.B", "RF.2", "CIN.1"} == net_of(nets, "Q.B")
    assert {"Q.C", "RC.2", "RF.1"} == net_of(nets, "Q.C")
    assert "Q.E" in nets["GND"]
    assert "Q.Q2.E" in netlist(ex.CE_DARLINGTON)["GND"]


def test_inverting_amp():
    nets = netlist(ex.INV_GAIN10)
    assert {"U1.2", "IN.1", "FB.2"} == net_of(nets, "U1.2")  # inverting input
    assert "U1.1" in nets["GND"]  # non-inverting input
    assert "FB.1" in net_of(nets, "U1.5")  # output


def test_two_stage_chain():
    nets = netlist(ex.TWO_STAGE_FILLED)
    assert "A2.IN.2" in net_of(nets, "A1.U1.5")


def test_holes_must_be_filled_or_exported():
    with pytest.raises(YasdlError, match="neither filled nor exported"):
        Block("Bad", "A", A=ex.INV_AMP)
    with pytest.raises(YasdlError, match="unfilled"):
        netlist(ex.INV_AMP)


def test_port_count_and_dangling_checks():
    with pytest.raises(YasdlError, match="takes 2 ports"):
        ex.INV_AMP.fill(IN=NPN())
    with pytest.raises(YasdlError):
        Block("Dangling", "─ .", )  # wire runs into an empty cell
    two_rows = Block("TwoRows", "R1\nR2", R1=R().rot(), R2=R().rot())  # 2 ports on W and on E
    assert two_rows.ports == [("E", 0), ("E", 1), ("W", 0), ("W", 1)]
    with pytest.raises(YasdlError, match="single cell"):
        Block("Host", "─ U ─", U=two_rows)


def test_hole_accepts_rotated_content():
    vertical_hole = Block("V", "┌\nH\n└", H=Hole("H", 2), )  # hole between N and S neighbours
    assert vertical_hole.bindings["H"].n == 2
    filled = vertical_hole.fill(H=ex.SERIES2)  # horizontal 2-port block, rotated to fit
    assert len(netlist(filled)) == 3
