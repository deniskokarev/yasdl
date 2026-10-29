"""P2.5: generated projects carry their yasdl symbols and SPICE models with relative paths,
so they still pass ERC and export SPICE after being moved; KiCad's own libraries stay
installation dependencies."""

import re
import shutil

import pytest
from yasdl import Block, POT, R
from yasdl.kicad_lib import BUNDLED_DIR, KICAD_CLI
from yasdl.parts import IDEAL_DUAL, Package, Q2N3904

DESIGN = """
   [VCC]     [VCC]
     │         │
     PW       {c}
     │   ┌─{b}Q1
   [VEE] │    Q1
         │    {e}
{in}─────┤     │
         │   [GND]
        {cw}
        VR1{w}──{out}
        {ccw}
         │
       [GND]
"""


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(), reason="kicad-cli missing")
def test_moved_project_still_checks_and_simulates(tmp_path):
    from yasdl.kicad_export import erc, export_kicad_spice, render

    chip = Package(IDEAL_DUAL, "U1")
    term = Block("Term", "[GND]──+U1U1\n     ┌──U1U1──┐\n     │        │\n     └────────┘\n")
    term2 = Block("Term2", "[GND]──+U1U1\n     ┌──U1U1──┐\n     │        │\n     └────────┘\n")
    top = Block(
        "Portable",
        DESIGN + "\n  TA   TB\n",
        PW=chip.power(), Q1=Q2N3904, VR1=POT("10k", 0.3, "log"),
        TA=term.bind(U1=chip.unit("A")), TB=term2.bind(U1=chip.unit("B")),
    )
    a = tmp_path / "a"
    info = render(top, a, svg=False, spice=True)
    assert info["roundtrip_ok"] and info["erc"] == [] and info["spice_ok"], info
    sch_text = (a / "Portable.kicad_sch").read_text()
    assert str(BUNDLED_DIR) not in sch_text and str(a) not in sch_text
    assert re.search(r'"Sim.Library" "spice_models/jellybean.lib"', sch_text)
    assert re.search(r'"Sim.Library" "spice_models/yasdl.lib"', sch_text)
    assert re.search(r'"Sim.Library" "yasdl_packages.lib"', sch_text)
    assert "${KIPRJMOD}/yasdl.kicad_sym" in (a / "sym-lib-table").read_text()
    b = tmp_path / "moved"
    shutil.move(a, b)
    assert erc(b / "Portable.kicad_sch") == []
    exported = export_kicad_spice(b / "Portable.kicad_sch")
    includes = re.findall(r'^\.include "([^"]+)"', exported, re.M)
    assert includes and all(path.startswith(str(b)) for path in includes), includes
