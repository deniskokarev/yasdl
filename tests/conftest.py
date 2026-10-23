"""Symbol fixtures for test hosts without a KiCad installation."""

from pathlib import Path

import pytest
from yasdl import kicad_lib

if not kicad_lib.SYMBOL_DIR.is_dir():
    kicad_lib.SYMBOL_DIR = Path(__file__).parent / "data" / "kicad_symbols"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: requires KiCad or ngspice")
