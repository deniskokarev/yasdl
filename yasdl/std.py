"""Standard reusable Blocks (spec 6.4).

Interfaces follow consistent roles so variants are interchangeable:
- compound transistors (Darlington, Sziklai, parallel arrays) have the NPN/PNP hole's
  ports: {c} N, {b} W, {e} S. A PNP-equivalent is the same template bound with the
  opposite polarity; a host labels {e}/{c} to orient it.
- op-amp circuits contain a hole U with the ideal three-terminal interface: + above -,
  output E. Bind OPAMP_IDEAL(), a package unit, or powered(OPAMP5) (a five-pin op-amp
  with its supplies wired to [VCC]/[VEE] inside, so rotating it carries them along).
- two-terminal sections (filters, bias strings) have {in} W and {out} E.
- mirrors and differential pairs take kind="npn" (rail {vn}) or "pnp" (rail {vp}).

Bias networks are part of the template that needs them: push_pull() sizes its diode
string for the output variant (2 diodes for single or Sziklai outputs, 4 for
Darlingtons) instead of deriving it from a mirrored half.
"""

from __future__ import annotations

from .atoms import C, D, NPN, OPAMP_IDEAL, PNP, R
from .block import Atom, Block, YasdlError

# --- op-amp interface ---------------------------------------------------------------------
POWERED = """
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


def powered(
    opamp: Atom, name: str | None = None, positive: str = "VCC", negative: str = "VEE"
) -> Block:
    """A five-pin op-amp as a three-port block (+ above -, output E) with V+ on the global
    net `positive` and V- on `negative` inside. The labels pin the canonical orientation
    (spec 3.2): + above -, V+ on top. SPICE subcircuits of designs using it declare the
    supplies .global."""
    text = POWERED.replace("[VCC]", f"[{positive}]").replace("[VEE]", f"[{negative}]")
    return Block(name or f"Powered_{opamp.value or 'U'}", text, U1=opamp)


FOLLOWER = Block(
    "Follower",
    """
{in}───+U1U1
    ┌───U1U1──┬──{out}
    │         │
    └─────────┘
""",
)


def follower(opamp: Atom | Block | None = None) -> Block:
    """Unity-gain buffer around hole U1."""
    return FOLLOWER.bind(U1=opamp or OPAMP_IDEAL())


def noninverting(rf: str, rg: str, opamp: Atom | Block | None = None) -> Block:
    """Gain 1 + RF/RG."""
    return NONINVERTING.bind(RF=R(rf), RG=R(rg), U1=opamp or OPAMP_IDEAL())


def inverting(ri: str, rf: str, opamp: Atom | Block | None = None) -> Block:
    """Gain -RF/RI, + input grounded."""
    return INVERTING.bind(RI=R(ri), RF=R(rf), U1=opamp or OPAMP_IDEAL())


def integrator(ri: str, cf: str, opamp: Atom | Block | None = None) -> Block:
    """Inverting integrator: INVERTING with the capacitor cf as RF. Practical designs need
    DC feedback."""
    return Block(
        "Integrator", INVERTING.text, RI=R(ri), RF=C(cf), U1=opamp or OPAMP_IDEAL()
    )


def differentiator(ci: str, rf: str, opamp: Atom | Block | None = None) -> Block:
    """Inverting differentiator: INVERTING with the capacitor ci as RI."""
    return Block(
        "Differentiator", INVERTING.text, RI=C(ci), RF=R(rf), U1=opamp or OPAMP_IDEAL()
    )


# --- filters --------------------------------------------------------------------------------
def rc_lowpass(r: str, c: str) -> Block:
    """First-order low-pass, fc = 1 / (2 pi R C)."""
    return RC_LOWPASS.bind(R1=R(r), C1=C(c))


def rc_highpass(c: str, r: str) -> Block:
    """First-order high-pass, fc = 1 / (2 pi R C)."""
    return RC_HIGHPASS.bind(C1=C(c), R1=R(r))


def rc_bandpass(c1: str, r1: str, r2: str, c2: str) -> Block:
    """rc_highpass(c1, r1) into rc_lowpass(r2, c2); loading shifts both corners."""
    return Block(
        "RCBandPass",
        "{in}──HP──LP──{out}",
        HP=rc_highpass(c1, r1),
        LP=rc_lowpass(r2, c2),
    )


# --- compound transistors (ports c N, b W, e S) ------------------------------------------------
_DARLINGTON_PLAIN = """
            {c}
             │
       ┌─────┴───┐
      {c}       {c}
{b}─{b}Q1  ┌──{b}Q2
       Q1  │     Q2
      {e}  │    {e}
       │   │     │
       └───┘     │
                {e}
"""


_SZIKLAI_PLAIN = """
              {c}
               │
              {e}
        ┌──{b}Q2Q2
        │     Q2Q2
        │     {c}
        │      │
{b}─{b}Q1Q1    │
       Q1Q1    │
       {e}     │
        │      │
        └───┬──┘
            │
           {e}
"""


# A diode string is the head, one cell per diode (anode up, so the string conducts
# downwards: the "v" arrow), and the tail.
_DIODE_HEAD = "{a}\n │\n"
_DIODE_CELL = " v\n D{k}\n │\n"
_DIODE_TAIL = "{k}"


def diode_string(n: int, diode: Atom | None = None, name: str | None = None) -> Block:
    """n diodes in series, anode end {a} on top, cathode end {k} at the bottom."""
    if n < 1:
        raise YasdlError("diode_string() needs at least one diode")
    canvas = (
        _DIODE_HEAD
        + "".join(_DIODE_CELL.format(k=k + 1) for k in range(n))
        + _DIODE_TAIL
    )
    d = diode or D("1N4148")
    return Block(
        name or f"Diodes{n}", canvas, bindings={f"D{k + 1}": d for k in range(n)}
    )


VBE_MULTIPLIER = """
     {a}
      │
  ┌───┴───┐
  │       │
  R1     {c}
  ├───{b}Q1Q1
  │      Q1Q1
  R2     {e}
  │       │
  └───┬───┘
      │
     {k}
"""


def vbe_multiplier(
    q: Atom | None = None, r1: str = "2.7k", r2: str = "1k", name: str | None = None
) -> Block:
    """Adjustable bias "diode" for push_pull(bias=...): V(a, k) = Vbe (1 + R1/R2), R1 from
    collector to base, R2 from base to emitter. Ports {a} N, {k} S, like diode_string.
    Mount the transistor on the output devices' heatsink so the bias tracks them."""
    return Block(
        name or "VbeMultiplier",
        VBE_MULTIPLIER,
        Q1=q or NPN("2N3904"),
        R1=R(r1),
        R2=R(r2),
    )


PUSH_PULL_KINDS = {"bjt": 2, "darlington": 4, "sziklai": 2}


PUSH_PULL_VAS = """
            {vp}
             │
      ┌──────┴────────┐
      │              {c}
      RB          ┌{b}QN
      │           │   QN
      ├───────────┘  {e}
      │               │
      BIAS            RE1
      │               ├──────{out}
      │               RE2
      │               │
      │              {e}
{in}──┴────────────{b}QP
                      QP
                     {c}
                      │
                    {vn}
"""


def push_pull_template() -> str:
    """Class-AB complementary emitter-follower canvas: holes QN, QP (transistor or compound
    device), BIAS (two-terminal, top to bottom), RB (bias feed from vp), RE1/RE2."""
    return PUSH_PULL_VAS


def push_pull_vas(
    kind: str = "bjt",
    npn: Atom | None = None,
    pnp: Atom | None = None,
    diode: Atom | None = None,
    rb: str | Atom | Block = "2.2k",
    re: str = "1",
    qn: Atom | Block | None = None,
    qp: Atom | Block | None = None,
    bias: Block | None = None,
    name: str | None = None,
) -> Block:
    """Complementary class-AB output stage. Ports: {vp} N, {in} W (drive: the bottom of the
    bias string, e.g. a VAS collector), {out} E, {vn} S. RB feeds the bias string from vp.

    kind selects the output devices and the matching bias string: "bjt" (npn/pnp, 2
    diodes), "darlington" (Darlington pairs, 4 diodes), "sziklai" (complementary feedback
    pairs, 2 diodes). qn/qp/bias override the devices (e.g. parallel() arrays) and string.
    """
    if kind not in PUSH_PULL_KINDS:
        raise YasdlError(f"push_pull kind must be one of {sorted(PUSH_PULL_KINDS)}")
    npn, pnp = npn or NPN("2N3904"), pnp or PNP("2N3906")
    devices = {
        "bjt": (npn, pnp),
        "darlington": (
            darlington(npn, rx=None, name="DarlingtonN"),
            darlington(pnp, rx=None, name="DarlingtonP"),
        ),
        "sziklai": (
            sziklai(npn, pnp, rx=None, name="SziklaiN"),
            sziklai(pnp, npn, rx=None, name="SziklaiP"),
        ),
    }[kind]
    qn, qp = qn or devices[0], qp or devices[1]
    bias = bias or diode_string(PUSH_PULL_KINDS[kind], diode)
    return Block(
        name or f"PushPull_{kind}",
        PUSH_PULL_VAS,
        QN=qn,
        QP=qp,
        BIAS=bias,
        RB=R(rb) if isinstance(rb, str) else rb,
        RE1=R(re),
        RE2=R(re),
    )


CURRENT_SINK = """
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
"""


def current_sink(
    q: Atom | None = None,
    re: str = "150",
    rb: str = "10k",
    diode: Atom | None = None,
    name: str | None = None,
) -> Block:
    """Diode-referenced current sink: {c} N sinks about 0.65 V / re, {e} S is the return;
    the two diodes are biased from VCC through rb. A two-terminal tail for diff_pair()."""
    d = diode or D("1N4148")
    return Block(
        name or "CurrentSink",
        CURRENT_SINK,
        Q1=q or NPN("2N3904"),
        RB=R(rb),
        RE=R(re),
        D1=d,
        D2=d,
    )


PUSH_PULL_CORE = """
               {vp}
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
               {vn}
"""


def push_pull_core(
    kind: str = "bjt",
    npn: Atom | None = None,
    pnp: Atom | None = None,
    diode: Atom | None = None,
    re: str = "1",
    n: int = 1,
    name: str | None = None,
) -> Block:
    """Class-AB output stage driven at both ends of its bias string: {hi} (upper base) and
    {lo} (lower base) W, {vp} N, {out} E, {vn} S. The enclosing driver supplies the bias
    current. kind sets the output devices and PUSH_PULL_KINDS[kind] diodes; each half has
    n (1-9) output transistors with emitter ballast re."""
    if kind not in PUSH_PULL_KINDS:
        raise YasdlError(f"push_pull kind must be one of {sorted(PUSH_PULL_KINDS)}")
    if not 1 <= n <= 9:
        raise YasdlError(f"push_pull_core(): n must be 1..9, got {n}")
    npn, pnp = npn or NPN("2N3904"), pnp or PNP("2N3906")

    def output(q, tag):
        if n == 1:
            return Block(f"Ballasted{tag}", _BALLASTED, Q1=q, RE1=R(re))
        return parallel(q, n, re, name=f"Parallel{tag}{n}")

    upper, lower = {
        "bjt": lambda: (output(npn, "N"), output(pnp, "P")),
        "darlington": lambda: (
            darlington(npn, output(npn, "N"), name="DarlingtonN"),
            darlington(pnp, output(pnp, "P"), name="DarlingtonP"),
        ),
        "sziklai": lambda: (
            sziklai(npn, output(pnp, "P"), name="SziklaiN"),
            sziklai(pnp, output(npn, "N"), name="SziklaiP"),
        ),
    }[kind]()
    return Block(
        name or f"PushPullCore_{kind}",
        PUSH_PULL_CORE,
        HI=upper,
        LO=lower,
        DS=diode_string(PUSH_PULL_KINDS[kind], diode),
    )


DARLINGTON = Block(
    "Darlington",
    """
              {c}
               │
        ┌──────┴────┐
        │           │
        Q1          Q2
{b}─────Q1   ┌──────Q2
        Q1   │      Q2
        │    │      │
        └────┤      │
             RX     │
             │      │
             └──────┤
                    │
                   {e}
""",
)

SZIKLAI = Block(
    "Sziklai",
    """
              {c}
               │
        ┌──────┤
        │      │
        RX    {e}
        │      Q2
        ├──────Q2
        │      Q2
        │     {c}
        │      │
        Q1     │
{b}─────Q1     │
        Q1     │
        │      │
        └──────┤
               │
              {e}
""",
)


def darlington(
    q1: "Atom | Block",
    q2: "Atom | Block | None" = None,
    rx: str | None = "1k",
    name: str | None = None,
) -> Block:
    """A Darlington of two same-polarity transistors (NPN-like with NPNs, PNP-like with
    PNPs): Q1 drives Q2, collectors joined, input drop 2 Vbe. rx is Q2's base-emitter
    turn-off resistor, or None for the plain pair."""
    if rx is None:
        return Block(name or "Darlington", _DARLINGTON_PLAIN, Q1=q1, Q2=q2 or q1)
    b = DARLINGTON.bind(Q1=q1, Q2=q2 or q1, RX=R(rx))
    return b if name is None else Block(name, b.text, bindings=b.bindings)


def sziklai(
    driver: "Atom | Block",
    output: "Atom | Block",
    rx: str | None = "1k",
    name: str | None = None,
) -> Block:
    """A Sziklai (complementary feedback) pair behaving like `driver`: sziklai(npn, pnp) is
    NPN-like; the output device's emitter is the compound collector, input drop 1 Vbe. rx
    is the output device's base-emitter turn-off resistor, or None for the plain pair."""
    if rx is None:
        return Block(name or "Sziklai", _SZIKLAI_PLAIN, Q1=driver, Q2=output)
    b = SZIKLAI.bind(Q1=driver, Q2=output, RX=R(rx))
    return b if name is None else Block(name, b.text, bindings=b.bindings)


# parallel(): the {b} strip, then one literal 8-column strip per device (its transistor in
# strip column 2), side by side. The first strip carries the {c}/{e} ports and starts the
# collector and emitter buses, the last ends them. The base bus on row 8 crosses the
# emitter leg of every device but the last: n - 1 deliberate crossings.
_PAR_LEFT = ["", "", "", "", "", "", "", "", "{b}─", "", "", "", "", "", ""]
_PAR_FIRST = [
    " {c}",
    "  │",
    "  ├─────",
    "  │",
    "  Q#",
    "┌─Q#",
    "│ Q#",
    "│ │",
    "┴─│─────",
    "  │",
    "  RE#",
    "  │",
    "  ├─────",
    "  │",
    " {e}",
]
_PAR_MIDDLE = [
    "",
    "",
    "──┬─────",
    "  │",
    "  Q#",
    "┌─Q#",
    "│ Q#",
    "│ │",
    "┴─│─────",
    "  │",
    "  RE#",
    "  │",
    "──┴─────",
    "",
    "",
]
_PAR_LAST = [
    "",
    "",
    "──┐",
    "  │",
    "  Q#",
    "┌─Q#",
    "│ Q#",
    "│ │",
    "┘ │",
    "  │",
    "  RE#",
    "  │",
    "──┘",
    "",
    "",
]


def parallel(device, n: int, re: str = "1", name: str | None = None) -> Block:
    """n identical transistor-like devices in parallel, each with an emitter ballast resistor.

    Three-terminal parts in parallel are not planar: the base bus crosses n-1 emitter stubs
    (deliberate crossings, spec 7). The canvas repeats one literal strip per device (#
    becomes the device number)."""
    if not 2 <= n <= 9:
        raise YasdlError(f"parallel(): n must be 2..9, got {n}")
    strips = [_PAR_FIRST] + [_PAR_MIDDLE] * (n - 2) + [_PAR_LAST]
    rows = []
    for r in range(len(_PAR_FIRST)):
        line = _PAR_LEFT[r].ljust(4)
        line += "".join(
            strip[r].replace("#", str(k + 1)).ljust(8) for k, strip in enumerate(strips)
        )
        rows.append(line.rstrip())
    bindings = {f"Q{k + 1}": device for k in range(n)}
    bindings.update({f"RE{k + 1}": R(re) for k in range(n)})
    return Block(name or f"Parallel{n}", "\n".join(rows), bindings=bindings)


_BALLASTED = """
      {c}
       │
      {c}
{b}─{b}Q1Q1
       Q1Q1
      {e}
       │
       RE1
       │
      {e}
"""


PUSH_PULL_DIODES = {"bjt": 1, "darlington": 2, "sziklai": 1}

PUSH_PULL_DEFAULTS = {
    "bjt": {"rt": "1k", "rq": "15"},
    "darlington": {"rt": "4.7k", "rq": "200"},
    "sziklai": {"rt": "4.7k", "rq": "39"},
}

# push_pull_buffer(): vp on top; the bias string on the left: RT, the upper base node, the
# upper diodes, the {in} node, RQ, the lower diodes, the lower base node, RB. The upper
# NPN-like device QH and the lower PNP-like device QL on the right, emitter resistors RH and
# RL meeting at {out}. One canvas per bias size (diodes on each side of {in}).
PUSH_PULL_BUFFER = {
    1: """
             {vp}
              │
       ┌──────┴───────┐
       │              │
       RT            {c}
       │              QH
       ├───────────{b}QH
       │              QH
       v             {e}
       DH1            │
       │              RH
{in}───┤              │
       │              ├────{out}
       RQ             │
       │              RL
       v              │
       DL1           {e}
       │              QL
       ├───────────{b}QL
       │              QL
       RB            {c}
       │              │
       └──────┬───────┘
              │
             {vn}
""",
    2: """
             {vp}
              │
       ┌──────┴───────┐
       │              │
       RT            {c}
       │              QH
       ├───────────{b}QH
       │              QH
       v             {e}
       DH1            │
       │              RH
       v              │
       DH2            │
       │              │
{in}───┤              │
       │              ├────{out}
       RQ             │
       │              │
       v              │
       DL1            │
       │              RL
       v              │
       DL2           {e}
       │              QL
       ├───────────{b}QL
       │              QL
       RB            {c}
       │              │
       └──────┬───────┘
              │
             {vn}
""",
}


def push_pull_buffer(
    variant: str,
    upper,
    lower,
    diode: Atom | None = None,
    rt: str | None = None,
    rb: str | None = None,
    rq: str | None = None,
    re: str = "0.22",
    name: str | None = None,
) -> Block:
    """Class-AB push-pull output stage (unity-gain buffer): {vp} N, {in} W, {out} E, {vn} S.

    variant: "bjt", "darlington" or "sziklai" sets the bias string: PUSH_PULL_DIODES[variant]
    diodes on each side of {in}, so each output half gets the drops it needs. upper/lower are
    NPN-like/PNP-like devices or compound blocks (darlington(), sziklai(), parallel()). RT/RB feed
    the string from the rails; RQ (in series below {in}) trims the quiescent current; RH/RL are
    the emitter resistors (PUSH_PULL_DEFAULTS gives the variant's RT/RB/RQ when omitted). {in}
    is the middle of the string: drive it from a low-impedance or current-mode source whose
    quiescent point is 0 V."""
    if variant not in PUSH_PULL_DIODES:
        raise YasdlError(
            f"push_pull variant {variant!r}: use one of {sorted(PUSH_PULL_DIODES)}"
        )
    n = PUSH_PULL_DIODES[variant]
    diode = diode or D("1N4148")
    rt = rt or PUSH_PULL_DEFAULTS[variant]["rt"]
    rb = rb or rt
    rq = rq or PUSH_PULL_DEFAULTS[variant]["rq"]
    canvas = PUSH_PULL_BUFFER[n]
    bindings = dict(
        QH=upper, QL=lower, RT=R(rt), RB=R(rb), RH=R(re), RL=R(re), RQ=R(rq)
    )
    bindings.update({f"DH{k + 1}": diode for k in range(n)})
    bindings.update({f"DL{k + 1}": diode for k in range(n)})
    return Block(name or f"PushPull_{variant}", canvas, bindings=bindings)


_MIRROR_NPN = """
 {in}       {out}
   │          │
   ├─────┐    │
   │     │    │
  {c}    │   {c}
   Q1    │    Q2
   Q1{b}─┴─{b}Q2
   Q1         Q2
  {e}        {e}
   │          │
   RA         RB
   │          │
   └────┬─────┘
        │
      {vn}
"""

_MIRROR_PNP = """
      {vp}
        │
   ┌────┴─────┐
   │          │
   RA         RB
   │          │
  {e}        {e}
   Q1         Q2
   Q1{b}─┬─{b}Q2
   Q1    │    Q2
  {c}    │   {c}
   │     │    │
   ├─────┘    │
   │          │
 {in}       {out}
"""

_WILSON_NPN = """
 {in}       {out}
   │          │
   │         {c}
   │          Q3
   ├───────{b}Q3
   │          Q3
   │         {e}
   │          │
   │     ┌────┤
   │     │    │
  {c}    │   {c}
   Q1    │    Q2
   Q1{b}─┴─{b}Q2
   Q1         Q2
  {e}        {e}
   │          │
   └────┬─────┘
        │
      {vn}
"""

_WILSON_PNP = """
      {vp}
        │
   ┌────┴─────┐
   │          │
  {e}        {e}
   Q1         Q2
   Q1{b}─┬─{b}Q2
   Q1    │    Q2
  {c}    │   {c}
   │     │    │
   │     └────┤
   │          │
   │         {e}
   │          Q3
   ├───────{b}Q3
   │          Q3
   │         {c}
   │          │
 {in}       {out}
"""

_LTP_NPN = """
           {vp}
            │
         ┌──┴──┐
         │     │
         RC1   RC2
         │     │
{o1}─────┤     ├─────{o2}
         │     │
        {c}   {c}
         Q1   Q2
{inp}─{b}Q1   Q2{b}─{inn}
         Q1   Q2
        {e}   {e}
         │     │
         RE1   RE2
         │     │
         └──┬──┘
            │
            RT
            │
           {vn}
"""

_LTP_PNP = """
           {vp}
            │
            RT
            │
         ┌──┴──┐
         │     │
         RE1   RE2
         │     │
        {e}   {e}
         Q1   Q2
{inp}─{b}Q1   Q2{b}─{inn}
         Q1   Q2
        {c}   {c}
         │     │
{o1}─────┤     ├─────{o2}
         │     │
         RC1   RC2
         │     │
         └──┬──┘
            │
           {vn}
"""

_LTP_MIRROR_NPN = """
               {vp}
                │
         ┌──────┴────────┐
         │               │
        {e}             {e}
         Q3              Q4
         Q3{b}──┬─────{b}Q4
         Q3     │        Q4
        {c}     │       {c}
         │      │        │
         ├──────┘        ├─────{out}
         │               │
        {c}             {c}
         Q1              Q2
{inp}─{b}Q1              Q2{b}─{inn}
         Q1              Q2
        {e}             {e}
         │               │
         RE1             RE2
         │               │
         └──────┬────────┘
                │
                RT
                │
               {vn}
"""

_LTP_MIRROR_PNP = """
               {vp}
                │
                RT
                │
         ┌──────┴────────┐
         │               │
         RE1             RE2
         │               │
        {e}             {e}
         Q1              Q2
{inp}─{b}Q1              Q2{b}─{inn}
         Q1              Q2
        {c}             {c}
         │               │
         ├──────┐        ├─────{out}
         │      │        │
        {c}     │       {c}
         Q3     │        Q4
         Q3{b}──┴─────{b}Q4
         Q3              Q4
        {e}             {e}
         │               │
         └──────┬────────┘
                │
               {vn}
"""


def _check_kind(kind):
    if kind not in ("npn", "pnp"):
        raise YasdlError(f"kind must be 'npn' or 'pnp', not {kind!r}")


def mirror(
    q, kind: str = "npn", re: str | None = None, name: str | None = None
) -> Block:
    """Two-transistor current mirror: {in} (reference current, diode-connected Q1) and {out}
    (Q2's collector) face away from the rail ({vn} for "npn", a sink; {vp} for "pnp", a
    source). re: emitter degeneration RA/RB, or None for direct emitter wires."""
    _check_kind(kind)
    canvas = _MIRROR_NPN if kind == "npn" else _MIRROR_PNP
    parts = {"Q1": q, "Q2": q}
    if re is None:
        canvas = canvas.replace("RA", "│ ").replace("RB", "│ ")
    else:
        parts.update(RA=R(re), RB=R(re))
    return Block(name or f"Mirror_{kind}", canvas, bindings=parts)


def wilson(q, kind: str = "npn", name: str | None = None) -> Block:
    """Wilson current mirror (higher output resistance, base-current error compensated): Q1
    takes the reference at {in}, Q3 delivers {out}, Q2 is diode-connected."""
    _check_kind(kind)
    canvas = _WILSON_NPN if kind == "npn" else _WILSON_PNP
    return Block(name or f"Wilson_{kind}", canvas, Q1=q, Q2=q, Q3=q)


def _two_terminal(part):
    return R(part) if isinstance(part, str) else part


def diff_pair(
    q,
    kind: str = "npn",
    rc: str = "10k",
    re: str | None = None,
    rt: "str | Atom | Block" = "10k",
    name: str | None = None,
) -> Block:
    """Long-tailed pair with collector resistors RC1/RC2: inputs {inp} (W) and {inn} (E),
    collector outputs {o1} (Q1, inverting for inp) and {o2}. "npn": loads to {vp} on top,
    tail to {vn}; "pnp": tail from {vp}. re: emitter degeneration RE1/RE2, or None for
    direct emitter wires. rt: the tail, a resistor value or any two-terminal part or block
    (e.g. current_sink())."""
    _check_kind(kind)
    canvas = _LTP_NPN if kind == "npn" else _LTP_PNP
    parts = {"Q1": q, "Q2": q, "RC1": R(rc), "RC2": R(rc), "RT": _two_terminal(rt)}
    if re is None:
        canvas = canvas.replace("RE1", "│  ").replace("RE2", "│  ")
    else:
        parts.update(RE1=R(re), RE2=R(re))
    return Block(name or f"DiffPair_{kind}", canvas, bindings=parts)


def diff_pair_mirror(
    q,
    load,
    kind: str = "npn",
    re: str = "100",
    rt: "str | Atom | Block" = "10k",
    name: str | None = None,
) -> Block:
    """Long-tailed pair with a current-mirror load (complementary transistors `load`), giving
    a single-ended output {out} at Q2/Q4's collectors: {out} rises with {inp} for "npn".
    rt: the tail, as for diff_pair()."""
    _check_kind(kind)
    canvas = _LTP_MIRROR_NPN if kind == "npn" else _LTP_MIRROR_PNP
    return Block(
        name or f"DiffPairMirror_{kind}",
        canvas,
        Q1=q,
        Q2=q,
        Q3=load,
        Q4=load,
        RE1=R(re),
        RE2=R(re),
        RT=_two_terminal(rt),
    )


RC_LOWPASS = Block(
    "RCLowPass",
    """
{in}──R1──┬──{out}
          │
          C1
          │
        [GND]
""",
)

RC_HIGHPASS = Block(
    "RCHighPass",
    """
{in}──C1──┬──{out}
          │
          R1
          │
        [GND]
""",
)

SALLEN_KEY = Block(
    "SallenKey",
    """
             ┌──────ZF────────┐
             │                │
{in}──ZA─────┴──ZB──┬───+U1U1 │
                    │    U1U1─┼──{out}
                    │  ┌─U1U1 │
                    │  │      │
                    ZS └──────┘
                    │
                  [GND]
""",
)


def sallen_key_lowpass(
    r1: str, r2: str, c_shunt: str, c_feedback: str, u=None, name: str | None = None
) -> Block:
    """Second-order low-pass (R, R in series; C to ground; C as feedback)."""
    b = SALLEN_KEY.bind(ZA=R(r1), ZB=R(r2), ZS=C(c_shunt), ZF=C(c_feedback))
    b = b.bind(U1=u or OPAMP_IDEAL())
    return b if name is None else Block(name, b.text, bindings=b.bindings)


def sallen_key_highpass(
    c1: str, c2: str, r_shunt: str, r_feedback: str, u=None, name: str | None = None
) -> Block:
    """Second-order high-pass (C, C in series; R to ground; R as feedback)."""
    b = SALLEN_KEY.bind(ZA=C(c1), ZB=C(c2), ZS=R(r_shunt), ZF=R(r_feedback))
    b = b.bind(U1=u or OPAMP_IDEAL())
    return b if name is None else Block(name, b.text, bindings=b.bindings)


INVERTING = Block(
    "Inverting",
    """
          ┌──RF──┐
          │      │
{in}──RI──┴─U1U1 │
            U1U1─┴──{out}
          ┌+U1U1
          │
        [GND]
""",
)

NONINVERTING = Block(
    "NonInverting",
    """
{in}───+U1U1
        U1U1──┬──{out}
     ┌──U1U1  │
     │        │
     ├───RF───┘
     │
     RG
     │
   [GND]
""",
)

OPAMP_UNUSED = Block(
    "OpampUnused",
    """
    ┌───────┐
    └──U1U1 │
       U1U1─┘
     ┌+U1U1
     │
   [GND]
""",
)


def push_pull(
    kind="bjt",
    npn=None,
    pnp=None,
    diode=None,
    *,
    rb=None,
    re=None,
    qn=None,
    qp=None,
    bias=None,
    rt=None,
    rq=None,
    name=None,
):
    """Class AB stage. rt/rq select the center-driven buffer. qn/qp/bias or a lone rb
    select the bottom-driven VAS stage. Prefer push_pull_buffer/push_pull_vas when choosing
    the drive point explicitly; their input ports are electrically different."""
    if (
        qn is not None
        or qp is not None
        or bias is not None
        or (rb is not None and rt is None and rq is None)
    ):
        return push_pull_vas(
            kind,
            npn,
            pnp,
            diode,
            rb=rb or "2.2k",
            re=re or "1",
            qn=qn,
            qp=qp,
            bias=bias,
            name=name,
        )
    npn, pnp = npn or NPN("2N3904"), pnp or PNP("2N3906")
    if kind == "darlington":
        npn = darlington(npn) if isinstance(npn, Atom) else npn
        pnp = darlington(pnp) if isinstance(pnp, Atom) else pnp
    elif kind == "sziklai" and isinstance(npn, Atom) and isinstance(pnp, Atom):
        npn, pnp = sziklai(npn, pnp), sziklai(pnp, npn)
    return push_pull_buffer(
        kind, npn, pnp, diode, rt=rt, rb=rb, rq=rq, re=re or "0.22", name=name
    )
