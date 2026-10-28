"""P1.3: render(export_name=...) chooses output file names independently of the block."""

import pytest
from docs.examples.blocks import DARLINGTON
from yasdl import NPN, netlist, PNP
from yasdl.kicad_lib import KICAD_CLI

have_kicad = KICAD_CLI.exists()


@pytest.mark.integration
@pytest.mark.skipif(not have_kicad, reason="kicad-cli missing")
def test_two_bindings_of_one_template_render_side_by_side(tmp_path):
    from yasdl.kicad_export import render

    upper = DARLINGTON.bind(Q1=NPN("2N3904"), Q2=NPN("2N3904"))
    lower = DARLINGTON.bind(Q1=PNP("2N3906"), Q2=PNP("2N3906"))
    a = render(upper, tmp_path, export_name="DarlN")
    b = render(lower, tmp_path, export_name="DarlP")
    for info, stem in ((a, "DarlN"), (b, "DarlP")):
        assert info["schematic"] == tmp_path / f"{stem}.kicad_sch"
        assert info["svg"] == tmp_path / f"{stem}.svg"
        assert (tmp_path / f"{stem}.kicad_pro").exists()
        assert info["roundtrip_ok"] and info["erc"] == []
    assert "Q_NPN" in a["schematic"].read_text()
    assert "Q_PNP" in b["schematic"].read_text()
    # the blocks keep their identity and circuit
    assert upper.name == lower.name == "Darlington"
    assert netlist(upper) == netlist(DARLINGTON.bind(Q1=NPN("2N3904"), Q2=NPN("2N3904")))
    assert not (tmp_path / "Darlington.kicad_sch").exists()


@pytest.mark.integration
@pytest.mark.skipif(not have_kicad, reason="kicad-cli missing")
def test_default_name_is_the_block_name(tmp_path):
    from yasdl.kicad_export import render

    info = render(DARLINGTON.bind(Q1=NPN("2N3904"), Q2=NPN("2N3904")), tmp_path, svg=False)
    assert info["schematic"] == tmp_path / "Darlington.kicad_sch"


@pytest.mark.parametrize("bad", ["", "a/b", "..", "."])
def test_export_name_must_be_a_plain_stem(tmp_path, bad):
    from yasdl.kicad_export import render

    with pytest.raises(ValueError, match="export_name"):
        render(DARLINGTON, tmp_path, export_name=bad)
