"""Atom factories for common KiCad 9 library symbols, and the power-net registry."""

from .block import Atom, YasdlError
from .kicad_lib import BUNDLED_MODELS
from .nets import POWER_NETS, register_power_net  # noqa: F401  (re-exported)


def R(value: str = "") -> Atom:
    return Atom("Device:R", value, symmetric=True)


def C(value: str = "") -> Atom:
    return Atom("Device:C", value, symmetric=True)


def L(value: str = "") -> Atom:
    return Atom("Device:L", value, symmetric=True)


def C_POL(value: str = "") -> Atom:
    return Atom("Device:C_Polarized", value, aliases={"+": "1"})


# Arrows show conventional current in the library orientation, one pin per arrow (spec 2.5).
def NPN(value: str = "") -> Atom:
    """B left (> current in), C top, E bottom (v current out, like the symbol's arrow)."""
    return Atom("Device:Q_NPN", value, arrows={"B": ">", "E": "v"})


def PNP(value: str = "") -> Atom:
    """B left (< current out), C top, E bottom (^ current in)."""
    return Atom("Device:Q_PNP", value, arrows={"B": "<", "E": "^"})


def D(value: str = "") -> Atom:
    """Diode: cathode (pin 1) left, anode (pin 2) right. The anode carries the arrow: current
    enters it, pointing at the cathode (< in the library orientation), so --->D1--- puts the
    anode on the left."""
    return Atom("Device:D", value, arrows={"2": "<"})


def OPAMP(value: str = "") -> Atom:
    """Ideal op-amp (Simulation_SPICE:OPAMP): + and - on the left, out right, V+ top, V- bottom."""
    return Atom("Simulation_SPICE:OPAMP", value)


def OPAMP_IDEAL() -> Atom:
    """Ideal op-amp without supply pins (yasdl:OPAMP_IDEAL): + above -, out on the right.
    Simulates as the bundled behavioural subcircuit yasdl_ideal_opamp (gain 1e9)."""
    from .spice import SpiceModel

    return Atom(
        "yasdl:OPAMP_IDEAL",
        "OPAMP_IDEAL",
        spice=SpiceModel(
            "X",
            ("1", "2", "3"),
            "yasdl_ideal_opamp",
            "1=inp 2=inn 3=out",
            str(BUNDLED_MODELS),
        ),
    )


POT_TAPERS = {"lin": 0, "log": 1, "rlog": 2}


def pot_position(rotation: float, taper: str = "lin") -> float:
    """Electrical track fraction for a shaft rotation from CCW (0) to CW (1)."""
    if not 0 <= rotation <= 1:
        raise YasdlError(f"POT rotation {rotation!r} must be within 0..1")
    if taper not in POT_TAPERS:
        raise YasdlError(f"POT taper must be one of {sorted(POT_TAPERS)}")
    if taper == "lin":
        return rotation
    if taper == "log":
        return (81.0 ** rotation - 1) / 80
    return 1 - (81.0 ** (1 - rotation) - 1) / 80


def POT(value: str = "10k", position: float = 0.5, taper: str = "lin", *, rotation=None) -> Atom:
    """Three-terminal potentiometer (Device:R_Potentiometer), pins by role (spec 6.2):
    pin 1 = `ccw` end (top in the library), pin 2 = wiper `w` (right), pin 3 = `cw` end
    (bottom). position: shaft rotation from fully counterclockwise (0, wiper at ccw) to fully
    clockwise (1, wiper at cw). taper: "lin" (F = position), "log" (audio "A" taper, 10 % at
    mid rotation) or "rlog" (reverse log, "C"), where F is the fraction of `value` between
    ccw and the wiper. A volume control takes its input on cw and has ccw grounded, so
    turning clockwise is louder. Simulates as the bundled yasdl_pot with instance
    parameters, so every pot keeps its own setting through the SPICE round trip."""
    from .spice import check_value, SpiceModel

    import re
    if not re.fullmatch(r"\d+(?:\.\d*)?(?:[eE][-+]?\d+)?(?:meg|[fpnumkgt])?", value, re.IGNORECASE):
        raise YasdlError(f"POT value {value!r}: use a plain SPICE number such as 10k or 1MEG")
    if rotation is not None:
        params = f"R={value} POS={pot_position(rotation, taper):.6g}"
    else:
        params = f"R={value} POS={float(position):g} TAPER={POT_TAPERS.get(taper)}"

    if not 0.0 <= float(position) <= 1.0:
        raise YasdlError(f"POT position must be within 0..1 (0 = fully ccw), not {position}")
    if taper not in POT_TAPERS:
        raise YasdlError(f"POT taper must be one of {sorted(POT_TAPERS)}, not {taper!r}")
    check_value("POT", "R", value)
    return Atom(
        "Device:R_Potentiometer",
        value,
        aliases={"ccw": "1", "w": "2", "wiper": "2", "cw": "3"},
        spice=SpiceModel(
            "X",
            ("1", "2", "3"),
            "yasdl_pot",
            "1=ccw 2=w 3=cw",
            str(BUNDLED_MODELS),
            params,
        ),
    )


def V(value: str = "") -> Atom:
    """Independent voltage source (Simulation_SPICE:VDC), + on top. The value is the SPICE
    source specification, e.g. "1", "dc 0 ac 1", "pulse(0 1 0 1n 1n 1m 2m)"."""
    from .spice import SpiceModel

    return Atom(
        "Simulation_SPICE:VDC",
        value,
        aliases={"+": "1"},
        spice=SpiceModel("V", ("1", "2")),
    )


def I(value: str = "") -> Atom:  # noqa: E743
    """Independent current source (Simulation_SPICE:IDC). SPICE convention: current flows from
    the + pin (top) through the source to the - pin, i.e. out of the bottom pin. The arrow `v`
    marks that pin: `v` below the part means the current leaves downwards."""
    from .spice import SpiceModel

    return Atom(
        "Simulation_SPICE:IDC",
        value,
        aliases={"+": "1"},
        arrows={"2": "v"},
        spice=SpiceModel("I", ("1", "2")),
    )


def GND() -> Atom:
    return Atom("power:GND", "GND")


def VCC() -> Atom:
    return Atom("power:VCC", "VCC")


def VEE() -> Atom:
    return Atom("power:VEE", "VEE")


def __getattr__(name):
    if name in {'AtomNPN', 'AtomPNP', 'AtomDiode', 'AtomOpamp3', 'AtomOpamp5', 'OpampPackage'}:
        from . import parts
        return getattr(parts, name)
    if name == 'NC':
        from .block import NC
        return NC
    raise AttributeError(name)
