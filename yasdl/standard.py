"""Positional, lowercase entry points to the reusable circuits of `yasdl.circuits`.

Each function returns the same Block as its `circuits` counterpart; arguments keep the
order shown. Compound devices expose c (N), b (W), e (S); supplies are global VCC/VEE.
"""

from __future__ import annotations

from . import circuits, YasdlError


def darlington(pnp=False):
    """Plain Darlington pair (no turn-off resistor): circuits.Darlington(turnoff=None)."""
    return circuits.Darlington(pnp=pnp, turnoff=None)


def sziklai(pnp=False):
    return circuits.Sziklai(pnp=pnp)


def diode_string(count=1):
    return circuits.DiodeString(count)


def bias_string(count=1, resistance="4.7k"):
    return circuits.BiasString(count, resistance)


def push_pull(variant="bjt", ballast="1", bias_resistance="4.7k"):
    """Self-biased unity-gain push-pull buffer {in} -> {out}: circuits.FollowerPushPull."""
    return circuits.FollowerPushPull(
        variant=variant, ballast=ballast, bias_resistance=bias_resistance
    )


def powered_opamp(atom):
    return circuits.PoweredOpamp(atom)


def follower(opamp=None):
    return circuits.Follower(opamp=opamp)


def inverting(ri="10k", rf="100k", opamp=None):
    return circuits.Inverting(opamp=opamp, input=ri, feedback=rf)


def noninverting(rg="10k", rf="100k", opamp=None):
    return circuits.NonInverting(opamp=opamp, feedback=rf, ground=rg)


def integrator(ri="10k", cf="100n", opamp=None):
    return circuits.Integrator(opamp=opamp, resistance=ri, capacitance=cf)


def rc_filter(kind="lowpass", r="10k", c="100n"):
    """kind: "lowpass" or "highpass"."""
    factories = {"lowpass": circuits.LowPass, "highpass": circuits.HighPass}
    if kind not in factories:
        raise YasdlError("rc_filter: kind must be lowpass or highpass")
    return factories[kind](resistance=r, capacitance=c)


def sallen_key(r="10k", c="10n", opamp=None):
    return circuits.SallenKey(resistance=r, capacitance=c, opamp=opamp)


def current_mirror(degeneration=None):
    """NPN mirror with its emitters on VEE: circuits.CurrentMirror(rail="VEE")."""
    return circuits.CurrentMirror(degeneration=degeneration, rail="VEE")


def differential_pair(degeneration=None, tail="4.7k", collector="10k"):
    """Resistor-loaded long-tailed pair: circuits.LongTailedPair."""
    return circuits.LongTailedPair(
        degeneration=degeneration, tail=tail, collector=collector
    )
