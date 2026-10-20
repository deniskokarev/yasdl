from pathlib import Path

from yasdl.kicad_export import MARGIN, SVG_PAD, _crop_svg, _paper_for_bbox
from yasdl.kicad_lib import _resolve_kicad_layout


def test_aquacap_kicad_layout_keeps_prefix_installation(tmp_path: Path) -> None:
    cli, symbols, template = _resolve_kicad_layout(tmp_path)

    assert cli == tmp_path / "bin" / "kicad-cli"
    assert symbols == tmp_path / "share" / "kicad" / "symbols"
    assert template == tmp_path / "share" / "kicad" / "template"


def test_aquacap_kicad_layout_accepts_macos_install_directory(tmp_path: Path) -> None:
    contents = tmp_path / "KiCad.app" / "Contents"
    cli = contents / "MacOS" / "kicad-cli"
    cli.parent.mkdir(parents=True)
    cli.touch()

    resolved_cli, symbols, template = _resolve_kicad_layout(tmp_path)

    assert resolved_cli == cli
    assert symbols == contents / "SharedSupport" / "symbols"
    assert template == contents / "SharedSupport" / "template"


def test_aquacap_paper_selection_keeps_exact_a4_fit() -> None:
    width = 297.0 - MARGIN - SVG_PAD
    height = 210.0 - MARGIN - SVG_PAD

    assert _paper_for_bbox((0.0, 0.0, width, height)) == "A4"


def test_aquacap_paper_selection_expands_collection_wide_overflow() -> None:
    width = 297.0 - MARGIN - SVG_PAD
    height = 210.0 - MARGIN - SVG_PAD + 0.01

    assert _paper_for_bbox((0.0, 0.0, width, height)) == "A3"


def test_aquacap_svg_crop_removes_generator_trailing_whitespace(
    tmp_path: Path,
) -> None:
    svg = tmp_path / "drawing.svg"
    svg.write_text(
        '<svg width="297mm" height="210mm" viewBox="0 0 297 210">  \n'
        '<path d="M0 0" /> \n'
        '</svg>\n'
    )

    _crop_svg(svg, (0.0, 0.0, 10.0, 10.0))

    assert all(line == line.rstrip() for line in svg.read_text().splitlines())
