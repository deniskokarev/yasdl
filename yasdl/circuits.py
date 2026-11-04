"""Reusable analog circuits as compact literal canvases.

Compound devices share the logical roles c (N), b (W), e (S); opamp circuits use the
three-terminal opamp interface (inp, inn, out). Supplies are the global nets VCC and VEE,
ground is GND. Component values are starting points: characterize each stage with the
intended supplies, load and models.
"""

from __future__ import annotations

from . import Block, C, D1N4148, OPAMP_IDEAL, Q2N3904, Q2N3906, R, YasdlError


def _bjt(pnp: bool):
    return Q2N3906() if pnp else Q2N3904()


# --- compound devices -------------------------------------------------------------------
_DARLINGTON = """
           {c}
            │
       ┌────┴────┐
       │         │
      {c}       {c}
{b}─{b}QD   ┌─{b}QO
       QD   │    QO
      {e}   │   {e}
       │    │    │
       ├────┘    │
       │         │
       RD        │
       │         │
       └────┬────┘
            │
           {e}
"""

_DARLINGTON_PLAIN = """
           {c}
            │
       ┌────┴────┐
       │         │
      {c}       {c}
{b}─{b}QD   ┌─{b}QO
       QD   │    QO
      {e}   │   {e}
       │    │    │
       └────┘    │
                 │
                {e}
"""


def Darlington(*, pnp=False, output=None, turnoff="220"):
    """Darlington pair: two Vbe drops. turnoff: resistor from the output device's base to
    its emitter (RD), or None for the plain pair. output: a c/b/e device or Block replacing
    the output transistor QO (e.g. a parallel bank). Complementary variants share geometry."""
    q = _bjt(pnp)
    if turnoff is None:
        return Block("Darlington", _DARLINGTON_PLAIN, QD=q, QO=output or q)
    return Block("Darlington", _DARLINGTON, QD=q, QO=output or q, RD=R(turnoff))


def Sziklai(*, pnp=False, output=None, turnoff="1k"):
    """Complementary feedback pair: one effective Vbe. The output device QO has the opposite
    polarity of the driver QD; RB is its base-emitter turn-off resistor."""
    return Block(
        "Sziklai",
        """
           {c}
            │
       ┌────┴────┐
       │         │
       RB       {e}
       ├──────{b}QO
       │         QO
      {c}       {c}
{b}─{b}QD        │
       QD        │
      {e}        │
       │         │
       │         │
       └────┬────┘
            │
           {e}
""",
        QD=_bjt(pnp),
        QO=output or _bjt(not pnp),
        RB=R(turnoff),
    )


def BallastedDevice(*, pnp=False, resistance="1"):
    """One transistor with its emitter ballast resistor, as a c/b/e device."""
    return Block(
        "BallastedDevice",
        """
      {c}
       │
      {c}
{b}─{b}Q1Q1
       Q1Q1
      {e}
       │
       RE
       │
      {e}
""",
        Q1=_bjt(pnp),
        RE=R(resistance),
    )


def ParallelDevices(device):
    """Two copies of a c/b/e device in parallel; one deliberate crossing (the base bus
    passes the first emitter leg). Nest it for four or eight devices."""
    return Block(
        "ParallelDevices",
        """
               {c}
                │
          ┌─────┴──────┐
          │            │
         {c}          {c}
    ┌──{b}K1     ┌──{b}K2
    │     K1     │     K2
    │    {e}     │    {e}
    │     │      │     │
    ├────────────┘     │
    │     │            │
    │     └─────┬──────┘
    │           │
{b}─┘          {e}
""",
        K1=device,
        K2=device,
    )


def DiodeString(count=1):
    """`count` series 1N4148 diodes conducting from {a} (top) to {k} (bottom)."""
    if type(count) is not int or count < 1:
        raise YasdlError("DiodeString: count must be a positive integer")
    text = "{a}\n │\n" + "\n │\n".join(f" v\n D{i}" for i in range(1, count + 1))
    return Block(
        "DiodeString",
        text + "\n │\n{k}",
        **{f"D{i}": D1N4148() for i in range(1, count + 1)},
    )


# --- output stages ----------------------------------------------------------------------
def _output_devices(variant, ballast, parallel=1):
    """(upper, lower) complementary output devices for a push-pull stage; the ballast is
    inside each device."""
    devices = []
    for pnp in (False, True):
        device = BallastedDevice(
            pnp=(not pnp if variant == "sziklai" else pnp), resistance=ballast
        )
        for _ in range(parallel.bit_length() - 1):
            device = ParallelDevices(device)
        if variant == "darlington":
            device = Darlington(pnp=pnp, output=device)
        elif variant == "sziklai":
            device = Sziklai(pnp=pnp, output=device)
        devices.append(device)
    return devices


def _bias_diodes(variant):
    """Vbe drops each half of a complementary output stage needs: Darlington two, BJT and
    Sziklai one."""
    return 2 if variant == "darlington" else 1


def _check_variant(variant, where):
    if variant not in ("bjt", "darlington", "sziklai"):
        raise YasdlError(f"{where}: variant must be bjt, darlington or sziklai")


def PushPull(*, variant="bjt", ballast="1", parallel=1):
    """Class-AB output stage driven at {hi} and {lo}, the two ends of its bias diode string.

    The enclosing driver supplies the bias current. The string has two diodes for bjt and
    Sziklai outputs and four for Darlington outputs. parallel: devices per half (1, 2, 4, 8).
    """
    _check_variant(variant, "PushPull")
    if parallel not in (1, 2, 4, 8):
        raise YasdlError("PushPull: parallel must be 1, 2, 4 or 8")
    upper, lower = _output_devices(variant, ballast, parallel)
    return Block(
        "PushPull",
        """
               [VCC]
                 │
                {c}
      ┌───────{b}HI
      │          HI
      │         {e}
{hi}──┤          │
      │          ├────{out}
      DS         │
      │         {e}
{lo}──┤          LO
      └───────{b}LO
                {c}
                 │
               [VEE]
""",
        HI=upper,
        LO=lower,
        DS=DiodeString(2 * _bias_diodes(variant)),
    )


def BiasString(count=1, resistance="4.7k"):
    """Resistor-fed diode bias for a follower output stage: {upper} and {lower} sit `count`
    diode drops above and below {in}; RU/RL feed them from VCC/VEE."""
    return Block(
        f"Bias{count}",
        """
         [VCC]
           │
           RU
           │
           ├──{upper}
           │
          {a}
           DU
           │
{in}───────┤
           │
          {a}
           DL
           │
           ├──{lower}
           │
           RL
           │
         [VEE]
""",
        RU=R(resistance),
        RL=R(resistance),
        DU=DiodeString(count),
        DL=DiodeString(count),
    )


def FollowerPushPull(*, variant="bjt", ballast="1", bias_resistance="4.7k"):
    """Self-biased unity-gain push-pull buffer from {in} to {out}: a BiasString puts the
    complementary output devices' bases the right number of diode drops either side of the
    input. RN/RP are the emitter ballast resistors."""
    _check_variant(variant, "FollowerPushPull")
    if variant == "bjt":
        upper, lower = _bjt(False), _bjt(True)
    elif variant == "darlington":
        upper, lower = Darlington(), Darlington(pnp=True)
    else:
        upper, lower = Sziklai(), Sziklai(pnp=True)
    return Block(
        f"FollowerPushPull_{variant}",
        """
                    [VCC]
                      │
                     {c}
               ┌──{b}QNQN
               │     QNQN
               │     {e}
               │      │
               │      RN
               │      │
           BIBI┘      ├──{out}
{in}───────BIBI       │
           BIBI┐      RP
               │      │
               │     {e}
               └──{b}QPQP
                     QPQP
                     {c}
                      │
                    [VEE]
""",
        BI=BiasString(_bias_diodes(variant), bias_resistance),
        QN=upper,
        QP=lower,
        RN=R(ballast),
        RP=R(ballast),
    )


# --- current mirrors, sinks and differential pairs -------------------------------------
_MIRROR = """
      {ref}     {out}
       │         │
  ┌────┤         │
  │    │         │
  │   {c}       {c}
  ├─{b}Q1   ┌─{b}Q2
  │    Q1   │    Q2
  │   {e}   │   {e}
  │    │    │    │
  └─────────┘    │
       │         │
       RE1       RE2
       │         │
       └────┬────┘
            │
           {common}
"""


def CurrentMirror(*, pnp=False, degeneration=None, rail=None):
    """Two-BJT mirror: Q1 diode-connected at {ref}, Q2 sinks (PNP: sources) {out}.
    degeneration: emitter resistors RE1/RE2, or None for direct emitter wires. The joined
    emitters are the {common} port, or the global net `rail` (e.g. "VEE")."""
    text = _MIRROR
    parts = {"Q1": _bjt(pnp), "Q2": _bjt(pnp)}
    if degeneration is None:
        text = text.replace("RE1", "│  ").replace("RE2", "│  ")
    else:
        parts.update(RE1=R(degeneration), RE2=R(degeneration))
    if rail is not None:
        text = text.replace("{common}", f"[{rail}]")
    return Block("CurrentMirror", text, **parts)


def CurrentSink(*, resistance="150"):
    """Diode-referenced BJT current sink: {c} N sinks about 0.65 V / resistance; {e} S is
    the negative return; the diodes are biased from VCC through RB."""
    return Block(
        "CurrentSink",
        """
          {c}
           │
          {c}
[VCC]      Q1Q1
  │   ┌─{b}Q1Q1
  RB  │   {e}
  │   │    │
  ├───┘    RE
  │        │
  v        │
  D1       │
  │        │
  v        │
  D2       │
  │        │
  └────┬───┘
       │
      {e}
""",
        Q1=Q2N3904(),
        RB=R("10k"),
        RE=R(resistance),
        D1=D1N4148(),
        D2=D1N4148(),
    )


def DifferentialPair(*, tail="resistor", degeneration="100"):
    """Emitter-degenerated NPN pair with the collectors as ports {left}/{right}; the tail
    is a resistor RT to VEE or ("active") a CurrentSink."""
    if tail not in ("resistor", "active"):
        raise YasdlError("DifferentialPair: tail must be resistor or active")
    return Block(
        "DifferentialPair",
        """
          {left}    {right}
            │         │
           {c}       {c}
{inp}────{b}Q1        Q2{b}─{inn}
            Q1        Q2
           {e}       {e}
            │         │
            RE1       RE2
            │         │
            └────┬────┘
                 │
                 RT
                 │
               [VEE]
""",
        Q1=Q2N3904(),
        Q2=Q2N3904(),
        RE1=R(degeneration),
        RE2=R(degeneration),
        RT=R("6.8k") if tail == "resistor" else CurrentSink(),
    )


def LongTailedPair(*, degeneration=None, tail="4.7k", collector="10k"):
    """Resistor-loaded long-tailed pair: two identical branches A1/B1 (collector load RC
    from VCC, outputs {outp}/{outn}) joined at [tail], tail resistor RT to VEE.
    degeneration: emitter resistor RE per branch, or None for direct emitter wires."""
    canvas = """
          [VCC]
            │
            RC
            │
            ├──{out}
            │
{in}─────{b}Q1
           {e}
            │
            RE
            │
          {tail}
"""
    parts = {"Q1": Q2N3904(), "RC": R(collector)}
    if degeneration is None:
        canvas = canvas.replace("RE", "│ ")
    else:
        parts["RE"] = R(degeneration)
    branch = Block("DiffBranch", canvas, **parts)
    return Block(
        "LongTailedPair",
        """
{inp}──A1──{outp}
        │
      [tail]

{inn}──B1──{outn}
        │
      [tail]

      [tail]
        │
        RT
        │
      [VEE]
""",
        A1=branch,
        B1=branch,
        RT=R(tail),
    )


# --- filters ----------------------------------------------------------------------------
def LowPass(*, resistance="10k", capacitance="100n"):
    return Block(
        "LowPass",
        """
{in}─R1─┬─{out}
        │
        C1
        │
      [GND]
""",
        R1=R(resistance),
        C1=C(capacitance),
    )


def HighPass(*, resistance="10k", capacitance="100n"):
    return Block(
        "HighPass",
        """
{in}─C1─┬─{out}
        │
        R1
        │
      [GND]
""",
        R1=R(resistance),
        C1=C(capacitance),
    )


def BandPass():
    """Passive high-pass/low-pass cascade; loading shifts both corner frequencies."""
    return Block(
        "BandPass",
        "{in}─HP─LP─{out}",
        HP=HighPass(capacitance="1u"),
        LP=LowPass(capacitance="10n"),
    )


def SallenKey(*, resistance="10k", capacitance="10n", opamp=None):
    """Unity-gain Sallen-Key low-pass: R1/R2 in series, C1 feedback from the output, C2 to
    ground, a Follower buffer."""
    return Block(
        "SallenKey",
        """
          ┌────C1───────────┐
          │                 │
{in}──R1──┴──R2──┬──BUF─────┴──{out}
                 │
                 C2
                 │
               [GND]
""",
        R1=R(resistance),
        R2=R(resistance),
        C1=C(capacitance),
        C2=C(capacitance),
        BUF=Follower(opamp=opamp),
    )


# --- opamp circuits ---------------------------------------------------------------------
def PoweredOpamp(atom, *, positive="VCC", negative="VEE"):
    """Three-port wrapper (inp or +, inn, out) of a five-pin opamp whose supply pins are
    wired to the global nets `positive`/`negative` inside, so rails follow any mirror."""
    text = """
          [VCC]
            │
           {V+}
{inp,+}────+U1U1
            U1U1──{out}
{inn}───────U1U1
           {V-}
            │
          [VEE]
"""
    text = text.replace("[VCC]", f"[{positive}]").replace("[VEE]", f"[{negative}]")
    return Block("PoweredOpamp", text, U1=atom)


def Follower(*, opamp=None):
    return Block(
        "Follower",
        """
{in}──+U1U1
    ┌──U1U1──┬──{out}
    │        │
    └────────┘
""",
        U1=opamp or OPAMP_IDEAL(),
    )


def NonInverting(*, opamp=None, feedback="47k", ground="1k"):
    """Gain 1 + feedback/ground."""
    return Block(
        "NonInverting",
        """
{in}──+U1U1
       U1U1──┬──{out}
   ┌───U1U1  │
   │         │
   ├──RF─────┘
   │
   RG
   │
 [GND]
""",
        U1=opamp or OPAMP_IDEAL(),
        RF=R(feedback),
        RG=R(ground),
    )


def Inverting(*, opamp=None, input="10k", feedback="100k"):
    """Gain -feedback/input; the + input is grounded."""
    return Block(
        "Inverting",
        """
         ┌──RF────────┐
         │            │
{in}─RI──┴───U1U1     │
             U1U1─────┴──{out}
    [GND]───+U1U1
""",
        U1=opamp or OPAMP_IDEAL(),
        RI=R(input),
        RF=R(feedback),
    )


def Integrator(*, opamp=None, resistance="10k", capacitance="10n"):
    """Inverting integrator (RF is the capacitor). Practical designs need DC feedback."""
    return Inverting(opamp=opamp, input=resistance).bind(RF=C(capacitance))


def Differentiator(*, opamp=None, resistance="10k", capacitance="10n"):
    """Inverting differentiator (RI is the capacitor)."""
    return Inverting(opamp=opamp, feedback=resistance).bind(RI=C(capacitance))
