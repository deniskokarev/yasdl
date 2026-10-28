"""Generic part factories and shared packages (spec 6.3).

Parts are built on KiCad's generic shapes with an explicit role -> physical pin map:
    Q2N3904 = AtomNPN("2N3904", pins={"E": 1, "B": 2, "C": 3}, library=JELLYBEAN_MODEL)
Canvas labels keep using roles ({b}, {e}, +, {out}); the map decides the physical pin
numbers in KiCad, the SPICE node order and the KiCad Sim.Pins mapping, consistently.

A multi-unit device (a dual op-amp) is one Package with separately bindable unit views:
    chip = Package(TL072, "U1")
    gain = NONINV.bind(U=chip.unit("A"))
    filt = SALLEN_KEY.bind(U=chip.unit("B"))
    top = Block(..., UP=chip.power())       # V+ above, V- below; bound once, anywhere
All units share one reference, footprint and SPICE element.

yasdl can't know whether a map matches the datasheet. Verify each descriptor against the
datasheet or KiCad's symbol for the exact device and package, then reuse it (see STANDARD
parts at the end of this module, and tests/test_parts.py for their reference fixtures).
"""

from __future__ import annotations

import re
from types import MappingProxyType
from dataclasses import dataclass, field
from pathlib import Path

from .block import Atom, YasdlError
from .kicad_lib import BUNDLED_MODELS, derive_symbol, JELLYBEAN_MODEL, load
from .spice import SpiceModel

BJT_ROLES = ("C", "B", "E")
OPAMP_ROLES = ("+", "-", "out", "V+", "V-")


def _pin_map(name: str, pins: dict, roles) -> dict[str, str]:
    """Validate a complete, one-to-one role -> physical pin map; values as strings."""
    if len({str(r).casefold() for r in pins}) != len(pins):
        raise YasdlError(f"{name}: the pin map needs exactly the roles {list(roles)} once")
    canonical = {r.casefold(): r for r in roles}
    pins = {canonical.get(str(k).casefold(), str(k)): str(v) for k, v in pins.items()}
    missing, extra = set(roles) - set(pins), set(pins) - set(roles)
    if missing or extra:
        raise YasdlError(
            f"{name}: the pin map needs exactly the roles {list(roles)}"
            + (f"; missing {sorted(missing)}" if missing else "")
            + (f"; unknown {sorted(extra)}" if extra else "")
        )
    if len(set(pins.values())) != len(pins):
        raise YasdlError(f"{name}: two roles share a physical pin; pins must be distinct: {pins}")
    if any(not re.fullmatch(r"[A-Za-z0-9]+", v) for v in pins.values()):
        raise YasdlError(f"{name}: physical pins are numbers or names: {pins}")
    return pins


def _metadata(footprint: str, datasheet: str, description: str = "") -> dict:
    props = {"Footprint": footprint, "Datasheet": datasheet}
    if description:
        props["Description"] = description
    return props


def subckt_pins(model: str, library) -> list[str]:
    """Formal node names of `.subckt model` in a SPICE library (continuation lines joined)."""
    from .spice import spice_lines

    from .kicad_lib import YasdlDependencyError
    try:
        text = Path(library).read_text(errors="replace")
    except OSError as e:
        raise YasdlDependencyError(f"reading model {model!r} from {library}: {e}; supply an existing library") from e
    for line in spice_lines(text):
        parts = line.split()
        if len(parts) > 1 and parts[0].lower() == ".subckt" and parts[1].lower() == model.lower():
            nodes = []
            for tok in parts[2:]:
                if "=" in tok or tok.lower() == "params:":
                    break
                nodes.append(tok)
            return nodes
    raise YasdlError(f"{library} defines no .subckt {model}")


# --- transistors and diodes --------------------------------------------------------------
def _bjt(kind: str, name, pins, model, library, footprint, datasheet, value):
    base = {"NPN": "Device:Q_NPN", "PNP": "Device:Q_PNP"}[kind]
    p = _pin_map(name, pins, BJT_ROLES)
    lib_id = derive_symbol(base, name, {r: p[r] for r in BJT_ROLES}, _metadata(footprint, datasheet))
    arrows = {"NPN": {p["B"]: ">", p["E"]: "v"}, "PNP": {p["B"]: "<", p["E"]: "^"}}[kind]
    spice = SpiceModel(
        "Q",
        (p["C"], p["B"], p["E"]),
        model or name,
        f"{p['C']}=C {p['B']}=B {p['E']}=E",
        str(library) if library else None,
    )
    return Atom(
        lib_id,
        value or name,
        arrows=arrows,
        spice=spice,
        footprint=footprint,
        datasheet=datasheet,
    )


def AtomNPN(name, pins, model=None, library=None, footprint="", datasheet="", value=None):
    """An NPN part on the generic Device:Q_NPN shape. pins: {"E": 1, "B": 2, "C": 3}, the
    physical pin of each role. SPICE: a Q element, nodes C B E, model `model` (default
    `name`) from `library` (default: found in render(spice_libs=...))."""
    return _bjt("NPN", name, pins, model, library, footprint, datasheet, value)


def AtomPNP(name, pins, model=None, library=None, footprint="", datasheet="", value=None):
    """A PNP part on the generic Device:Q_PNP shape; see AtomNPN."""
    return _bjt("PNP", name, pins, model, library, footprint, datasheet, value)


def AtomDiode(name, pins=None, model=None, library=None, footprint="", datasheet=""):
    """A diode on the generic Device:D shape (K left, A right). pins: {"K": 1, "A": 2}."""
    p = _pin_map(name, pins or {"K": 1, "A": 2}, ("K", "A"))
    lib_id = derive_symbol("Device:D", name, {"1": p["K"], "2": p["A"]}, _metadata(footprint, datasheet))
    return Atom(
        lib_id,
        name,
        arrows={p["A"]: "<"},
        spice=SpiceModel(
            "D", (p["A"], p["K"]), model or name, f"{p['K']}=K {p['A']}=A",
            str(library) if library else None,
        ),
        footprint=footprint,
        datasheet=datasheet,
    )


# --- single op-amps -------------------------------------------------------------------------
def _opamp_spice(name, p, model, library, model_pins):
    if model is None:
        return None
    roles = tuple(model_pins)
    if set(roles) != set(p) or len(roles) != len(p):
        raise YasdlError(f"{name}: model_pins must list every role exactly once: {tuple(p)}")
    nodes = subckt_pins(model, library) if library else [str(i + 1) for i in range(len(roles))]
    if len(nodes) != len(roles):
        raise YasdlError(
            f"{name}: .subckt {model} has {len(nodes)} pins {nodes}, model_pins lists "
            f"{len(roles)} {list(roles)}"
        )
    return SpiceModel(
        "X",
        tuple(p[r] for r in roles),
        model,
        " ".join(f"{p[r]}={n}" for r, n in zip(roles, nodes)),
        str(library) if library else None,
    )


def AtomOpamp5(
    name, pins, model=None, library=None, model_pins=("+", "-", "V+", "V-", "out"),
    footprint="", datasheet="",
):
    """A single op-amp with supply pins on the generic Simulation_SPICE:OPAMP shape:
    + above -, output right, V+ on top, V- at the bottom. pins: physical pin per role
    ("+", "-", "out", "V+", "V-"). model_pins: the roles in the subcircuit's node order."""
    p = _pin_map(name, pins, OPAMP_ROLES)
    base = {"+": "1", "-": "2", "V+": "3", "V-": "4", "out": "5"}
    lib_id = derive_symbol(
        "Simulation_SPICE:OPAMP", name, {base[r]: p[r] for r in OPAMP_ROLES},
        _metadata(footprint, datasheet),
    )
    return Atom(
        lib_id, name, aliases={"out": p["out"]},
        spice=_opamp_spice(name, p, model, library, model_pins),
        footprint=footprint, datasheet=datasheet,
    )


def AtomOpamp3(name, pins=None, model=None, library=None, model_pins=("+", "-", "out"),
               footprint="", datasheet="", value=None):
    """A supply-less op-amp on the yasdl:OPAMP_IDEAL shape (+ above -, output right)."""
    p = _pin_map(name, pins or {"+": 1, "-": 2, "out": 3}, ("+", "-", "out"))
    lib_id = derive_symbol("yasdl:OPAMP_IDEAL", name, {"1": p["+"], "2": p["-"], "3": p["out"]},
                           _metadata(footprint, datasheet))
    return Atom(
        lib_id, value or name, aliases={"out": p["out"]}, footprint=footprint, datasheet=datasheet,
        spice=_opamp_spice(name, p, model, library, model_pins),
    )


# --- packages ---------------------------------------------------------------------------------
_PACKAGE_SHAPES = {2: "Device:Opamp_Dual", 4: "Device:Opamp_Quad"}


@dataclass(frozen=True)
class OpampPackage:
    """Descriptor of a multi-amplifier package on KiCad's generic dual/quad op-amp shape.

    units: {"A": {"+": 3, "-": 2, "out": 1}, "B": {...}}; power: {"V+": 8, "V-": 4}.
    model/library/model_pins: a single-amplifier subcircuit and its node order in roles
    (scope "unit": yasdl wraps one instance per amplifier into a whole-package subcircuit,
    because KiCad exports one element per package), or with scope "package" a whole-device
    subcircuit whose nodes are the physical pins listed in model_pins.
    """

    name: str
    units: dict
    power: dict
    model: str | None = None
    library: str | None = None
    model_pins: tuple = ("+", "-", "V+", "V-", "out")
    scope: str = "unit"
    footprint: str = ""
    datasheet: str = ""
    lib_id: str = field(default="", compare=False)

    def __post_init__(self):
        if len(self.units) not in _PACKAGE_SHAPES:
            raise YasdlError(f"{self.name}: 2 or 4 amplifier units are supported")
        if self.scope not in ("unit", "package"):
            raise YasdlError(f"{self.name}: scope is 'unit' or 'package'")
        maps = {u: _pin_map(f"{self.name} unit {u}", m, ("+", "-", "out")) for u, m in self.units.items()}
        power = _pin_map(f"{self.name} power", self.power, ("V+", "V-"))
        physical = [v for m in maps.values() for v in m.values()] + list(power.values())
        if len(set(physical)) != len(physical):
            raise YasdlError(f"{self.name}: a physical pin is used twice: {sorted(physical)}")
        if self.model:
            expected = set(OPAMP_ROLES) if self.scope == 'unit' else set(physical)
            order = self.model_pins if self.scope == 'unit' else tuple(str(p) for p in self.model_pins)
            if len(order) != len(expected) or set(order) != expected:
                raise YasdlError(f"{self.name}: model_pins must list every {self.scope} terminal once")
            if self.library and len(subckt_pins(self.model, self.library)) != len(order):
                raise YasdlError(f"{self.name}: model_pins count differs from .subckt {self.model}")
        object.__setattr__(self, 'units', MappingProxyType({u: MappingProxyType(m) for u, m in maps.items()}))
        object.__setattr__(self, 'power', MappingProxyType(power))
        base = load(_PACKAGE_SHAPES[len(maps)])
        renumber = {}
        for k, (u, m) in enumerate(sorted(maps.items()), start=1):
            for pin in load(base.lib_id, k).pins:
                role = {"~": "out"}.get(pin.name, pin.name)
                renumber[pin.number] = m[role]
        for pin in load(base.lib_id, base.unit_count).pins:
            renumber[pin.number] = power[pin.name]
        lib_id = derive_symbol(base.lib_id, self.name, renumber, _metadata(self.footprint, self.datasheet))
        object.__setattr__(self, "lib_id", lib_id)

    def __call__(self, name=None, **kwargs):
        """Create one chip; an omitted name is derived from its first placed unit path."""
        return Package(self, name, **kwargs)

    def unit_names(self) -> list[str]:
        return sorted(self.units)

    def physical_pins(self) -> list[str]:
        pins = [str(v) for m in self.units.values() for v in m.values()]
        pins += [str(v) for v in self.power.values()]
        return sorted(pins, key=lambda s: (len(s), s))

    def wrapper_name(self) -> str:
        return "yasdl_pkg_" + re.sub(r"[^A-Za-z0-9_]", "_", self.name)

    def wrapper(self) -> str:
        """Whole-package subcircuit: one instance of the single-amplifier model per unit."""
        nodes = self.physical_pins()
        lines = [f".subckt {self.wrapper_name()} {' '.join('p' + n for n in nodes)}"]
        for u in self.unit_names():
            role_pin = {**{r: str(v) for r, v in self.units[u].items()},
                        **{r: str(v) for r, v in self.power.items()}}
            lines.append(
                f"X{u} {' '.join('p' + role_pin[r] for r in self.model_pins)} {self.model}"
            )
        lines.append(f".ends {self.wrapper_name()}")
        return "\n".join(lines) + "\n"

    def spice_element(self) -> tuple[str, tuple[str, ...]]:
        """(subcircuit name, physical pins in its node order) of the package element."""
        if self.scope == "unit":
            return self.wrapper_name(), tuple(self.physical_pins())
        return self.model, tuple(str(p) for p in self.model_pins)


@dataclass(frozen=True)
class PackageType:
    """Reusable multi-unit root symbol, metadata and one whole-device SPICE mapping."""
    lib_id: str
    value: str = ""
    spice: SpiceModel | None = None
    footprint: str = ""
    datasheet: str = ""
    sim: bool = True
    scope: str = field(default="package", init=False)

    @property
    def name(self):
        return self.value or self.lib_id.split(':', 1)[1]

    @property
    def model(self):
        return self.spice.model if self.spice else None

    @property
    def library(self):
        return self.spice.library if self.spice else None

    def power_unit(self):
        found = [u for u in range(1, load(self.lib_id).unit_count + 1)
                 if load(self.lib_id, u).pins and all(p.etype.startswith('power') for p in load(self.lib_id, u).pins)]
        return found[0] if len(found) == 1 else None

    def unit_names(self):
        return [chr(64 + u) for u in range(1, load(self.lib_id).unit_count + 1) if u != self.power_unit()]

    def physical_pins(self):
        return sorted({p.number for u in range(1, load(self.lib_id).unit_count + 1) for p in load(self.lib_id, u).pins})

    def spice_element(self):
        return self.spice.model or self.value, self.spice.pins

    def __call__(self, name=None, **kwargs):
        return Package(self, name=name, **kwargs)


class Package:
    """One physical multi-unit device. Its unit views bind into ordinary op-amp holes; every
    unit, including the power unit, must be bound exactly once in the design."""

    def __init__(self, descriptor: OpampPackage | PackageType | str, name: str | None = None, *,
                 spice=None, value=None, footprint=None, datasheet=None, sim=None):
        if isinstance(descriptor, str):
            try:
                load(descriptor)
            except NotImplementedError as e:
                raise YasdlError("Package needs an OpampPackage descriptor or a generic root symbol") from e
            descriptor = PackageType(descriptor)
        if isinstance(descriptor, OpampPackage) and spice is not None:
            descriptor = PackageType(descriptor.lib_id, descriptor.name, spice,
                                     descriptor.footprint, descriptor.datasheet)
        if isinstance(descriptor, PackageType):
            from dataclasses import replace
            changes = {k: v for k, v in dict(spice=spice, value=value, footprint=footprint, datasheet=datasheet, sim=sim).items() if v is not None}
            descriptor = replace(descriptor, **changes)
            if load(descriptor.lib_id).unit_count == 1:
                raise YasdlError(f"{descriptor.lib_id}: a single unit belongs in Atom, not Package")
            if descriptor.spice is not None:
                pins = descriptor.physical_pins()
                if sorted(descriptor.spice.pins) != pins:
                    raise YasdlError("Package SPICE mapping must list every physical pin exactly once")
                if descriptor.spice.prefix != 'X':
                    raise YasdlError("A whole-package SPICE model must be an X subcircuit")
        if not isinstance(descriptor, (OpampPackage, PackageType)):
            raise YasdlError("Package needs an OpampPackage descriptor (e.g. parts.TL072)")
        if name is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise YasdlError(f"package name {name!r}: letters, digits and _")
        self.descriptor, self.name = descriptor, name
        self.sim = descriptor.sim if isinstance(descriptor, PackageType) else (True if sim is None else sim)
        self.value = (descriptor.value if isinstance(descriptor, PackageType) else descriptor.name) if value is None else value
        self.footprint = descriptor.footprint if footprint is None else footprint
        self.datasheet = descriptor.datasheet if datasheet is None else datasheet
        self._units = {}

    def __repr__(self):
        return f"Package({self.descriptor.name}, {self.name!r})"

    def _atom(self, key: str, unit_no: int, aliases: dict) -> Atom:
        if key not in self._units:
            d = self.descriptor
            self._units[key] = Atom(
                d.lib_id, self.value, unit=unit_no, aliases=aliases, package=self,
                footprint=self.footprint, datasheet=self.datasheet,
                sim=self.sim,
            )
        return self._units[key]

    def unit(self, letter: str) -> Atom:
        """The amplifier unit `letter` ("A", "B", ...): + above -, output right."""
        d = self.descriptor
        names = d.unit_names()
        if isinstance(letter, int):
            letter = chr(64 + letter)
        if isinstance(d, PackageType):
            power_unit = d.power_unit()
            if power_unit is not None and str(letter).casefold() == chr(64 + power_unit).casefold():
                return self.power()
            if isinstance(letter, str):
                letter = letter.upper()
            if letter not in names:
                raise YasdlError(f"{self.name}: unit {letter!r} does not exist")
            out = [p.number for p in load(d.lib_id, ord(letter) - 64).pins if p.name == '~']
            return self._atom(letter, ord(letter) - 64, {'out': out[0]} if len(out) == 1 else {})
        if letter not in names:
            raise YasdlError(f"{self.name}: no unit {letter!r}; it does not exist (units {names})")
        out = str(self.descriptor.units[letter]["out"])
        return self._atom(letter, names.index(letter) + 1, {"out": out})

    def power(self) -> Atom:
        """The supply unit: V+ on top, V- at the bottom."""
        if isinstance(self.descriptor, PackageType):
            unit = self.descriptor.power_unit()
            if unit is None:
                raise YasdlError(f"{self.descriptor.lib_id}: no single power-only unit; use unit(...)")
            return self._atom("power", unit, {})
        return self._atom("power", len(self.descriptor.units) + 1, {})

    @property
    def units(self) -> list[str]:
        power = not isinstance(self.descriptor, PackageType) or self.descriptor.power_unit() is not None
        return [*self.descriptor.unit_names(), *(["power"] if power else [])]


# --- standard parts, verified against datasheets and KiCad's device symbols -------------------
# Pinouts (tests/test_parts.py checks them against KiCad 9's Transistor_BJT symbols for the
# exact device and package, which follow the manufacturers' datasheets):
#   2N3904/2N3906 TO-92: 1 = E, 2 = B, 3 = C (onsemi 2N3904/D, 2N3906/D)
#   BD139/BD140 TO-126: 1 = E, 2 = C, 3 = B (ST BD139/BD140 datasheet)
#   1N4148 DO-35: 1 = K (band), 2 = A
#   TL072/NE5532/LM358 dual DIP-8: A out 1, A- 2, A+ 3, V- 4, B+ 5, B- 6, B out 7, V+ 8
Q2N3904 = AtomNPN(
    "2N3904", {"E": 1, "B": 2, "C": 3}, library=JELLYBEAN_MODEL,
    footprint="Package_TO_SOT_THT:TO-92_Inline",
    datasheet="https://www.onsemi.com/pub/Collateral/2N3903-D.PDF",
)
Q2N3906 = AtomPNP(
    "2N3906", {"E": 1, "B": 2, "C": 3}, library=JELLYBEAN_MODEL,
    footprint="Package_TO_SOT_THT:TO-92_Inline",
    datasheet="https://www.onsemi.com/pub/Collateral/2N3906-D.PDF",
)
BD139 = AtomNPN(
    "BD139", {"E": 1, "C": 2, "B": 3},
    footprint="Package_TO_SOT_THT:TO-126-3_Vertical",
    datasheet="http://www.st.com/internet/com/TECHNICAL_RESOURCES/TECHNICAL_LITERATURE/DATASHEET/CD00001225.pdf",
)
BD140 = AtomPNP(
    "BD140", {"E": 1, "C": 2, "B": 3},
    footprint="Package_TO_SOT_THT:TO-126-3_Vertical",
    datasheet="http://www.st.com/internet/com/TECHNICAL_RESOURCES/TECHNICAL_LITERATURE/DATASHEET/CD00001225.pdf",
)
D1N4148 = AtomDiode(
    "1N4148", library=JELLYBEAN_MODEL,
    footprint="Diode_THT:D_DO-35_SOD27_P7.62mm_Horizontal",
    datasheet="https://assets.nexperia.com/documents/data-sheet/1N4148_1N4448.pdf",
)
DUAL_DIP8 = dict(
    units={"A": {"+": 3, "-": 2, "out": 1}, "B": {"+": 5, "-": 6, "out": 7}},
    power={"V+": 8, "V-": 4},
    footprint="Package_DIP:DIP-8_W7.62mm",
)


def dual_opamp(
    name: str, model: str | None = None, library=None,
    model_pins=("+", "-", "V+", "V-", "out"), datasheet="",
):
    """A standard DIP-8 dual op-amp (TL072, NE5532, LM358 pinout) with a single-amplifier
    subcircuit `model` (node order `model_pins`) from `library`."""
    model_pins = tuple(model_pins)
    scope = "unit"
    if any("." in r for r in model_pins):
        expected = {f"{u}.{r}" for u, pins in DUAL_DIP8['units'].items() for r in pins} | {"V+", "V-"}
        if set(model_pins) != expected or len(model_pins) != len(expected):
            raise YasdlError(f"{name}: model_pins must list every package role once")
        model_pins = tuple(str(DUAL_DIP8['units'][r.split('.')[0]][r.split('.')[1]])
                           if '.' in r else str(DUAL_DIP8['power'][r]) for r in model_pins)
        scope = "package"
    return OpampPackage(
        name, model=model, library=str(library) if library else None,
        model_pins=model_pins, scope=scope, datasheet=datasheet, **DUAL_DIP8,
    )


IDEAL_DUAL = dual_opamp(
    "IDEAL_DUAL", "yasdl_ideal_opamp5", BUNDLED_MODELS, ("+", "-", "V+", "V-", "out")
)
