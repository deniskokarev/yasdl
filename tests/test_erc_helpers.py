"""ERC helpers: a net label whose net reaches one pin gets a hidden test point, so a block
rendered on its own (reaching a shared [Vref], or a local [x]) is ERC-clean."""

import pytest
from yasdl import Block, R
from yasdl.kicad_lib import KICAD_CLI


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(), reason="kicad-cli missing")
@pytest.mark.parametrize(
    "canvas",
    [
        "{in}──R1──[Vref]",
        "{in}──R1──[vref]",
        "[Vref]──R1──{in}",
        "{in}──R1──┐\n          │\n        [bias]",
    ],
)
def test_single_pin_labels_render_erc_clean(tmp_path, canvas):
    from yasdl.kicad_export import erc, render, to_kicad

    parts = {k: R("1k") for k in ("R1", "R2") if k in canvas}
    block = Block("Lonely", canvas, **parts)
    info = render(block, tmp_path, svg=False, spice=True)
    assert info["roundtrip_ok"] and info["spice_ok"], info
    assert info["erc"] == []
    # without the helpers KiCad would report the label (proves the helper is needed)
    sch, _ = to_kicad(block, tmp_path / "raw.kicad_sch", erc_helpers=False)
    assert any("label_dangling" in e for e in erc(sch))
