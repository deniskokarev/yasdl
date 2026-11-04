# KiCad symbol fixtures

These fixtures contain the symbols used by the yasdl unit tests, extracted from
the KiCad 9.0.9 installation's libraries and reformatted as standalone libraries:

- `Device`: `C`, `D`, `Q_NPN`, `Q_PNP`, `R`
- `Simulation_SPICE`: `IDC`, `OPAMP`, `VDC`
- `power`: `GND`, `VCC`, `VEE`

The symbol definitions, including their pin positions and drawing geometry, are
unchanged. Their source is the [KiCad community symbol libraries](https://github.com/KiCad/kicad-symbols).
Copyright belongs to the KiCad library contributors. The fixtures retain the
KiCad libraries' CC BY-SA 4.0 license and design exception; see `LICENSE.md`.

`conftest.py` uses these packaged resources when the configured KiCad symbol
directory is absent. Tests that invoke KiCad still require a full installation.
