"""Standard reusable Blocks (spec 6.4).

Interfaces follow consistent roles so variants are interchangeable:
- compound transistors (Darlington, Sziklai, parallel arrays) have the NPN/PNP hole's
  ports: {c} N, {b} W, {e} S. A PNP-equivalent is the same template bound with the
  opposite polarity; a host labels {e}/{c} to orient it.
- op-amp circuits contain a hole U with the ideal three-terminal interface: + above -,
  output E. Bind OPAMP_IDEAL(), a package unit, or powered(OPAMP5) (a five-pin op-amp
  with its supplies wired to [VCC]/[VEE] inside, so rotating it carries them along).
- two-terminal sections (filters, bias strings) have {in} W and {out} E.

Bias networks are part of the template that needs them: push_pull() sizes its diode
string for the output variant (2 diodes for single or Sziklai outputs, 4 for
Darlingtons) instead of deriving it from a mirrored half.
"""

from __future__ import annotations

from .atoms import C, D, NPN, OPAMP_IDEAL, PNP, R
from .block import Atom, Block, YasdlError
from .sketch import Sketch

# --- op-amp interface ---------------------------------------------------------------------
POWERED = """
          [VCC]
            │
{inp,+}───+U1U1U1
           U1U1U1───{out}
{inn}──────U1U1U1
            │
          [VEE]
"""


def powered(opamp: Atom, name: str | None = None) -> Block:
    """A five-pin op-amp as a three-port block (+ above -, output E) with V+ on [VCC] and
    V- on [VEE] inside. The labels pin the canonical orientation (spec 3.2): + above -,
    V+ on top. SPICE subcircuits of designs using it declare .global VCC VEE."""
    return Block(name or f"Powered_{opamp.value or 'U'}", POWERED, U1=opamp)


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


NONINV = """
{in}───+U1U1
    ┌───U1U1──┬──{out}
    │         │
    ├───RF────┘
    │
    RG
    │
  [GND]
"""


def noninverting(rf: str, rg: str, opamp: Atom | Block | None = None) -> Block:
    """Gain 1 + RF/RG."""
    return Block("NonInverting", NONINV, RF=R(rf), RG=R(rg), U1=opamp or OPAMP_IDEAL())


_INVERTING_CANVAS = """
        ┌──RF──┐
        │      │
{in}──RI┴─U1U1─┴──{out}
         +U1U1
         │
       [GND]
"""


def inverting(ri: str, rf: str, opamp: Atom | Block | None = None) -> Block:
    """Gain -RF/RI, + input grounded."""
    return Block("Inverting", _INVERTING_CANVAS, RI=R(ri), RF=R(rf), U1=opamp or OPAMP_IDEAL())


# --- filters --------------------------------------------------------------------------------
RC = """
{in}──S1──┬──{out}
          │
          P1
          │
        [GND]
"""


def rc_lowpass(r: str, c: str) -> Block:
    """First-order low-pass, fc = 1 / (2 pi R C)."""
    return Block("RCLowPass", RC, S1=R(r), P1=C(c))


def rc_highpass(c: str, r: str) -> Block:
    """First-order high-pass, fc = 1 / (2 pi R C)."""
    return Block("RCHighPass", RC, S1=C(c), P1=R(r))








# --- compound transistors (ports c N, b W, e S) ------------------------------------------------
_DARLINGTON_CANVAS = """
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


def _darlington_simple(q1: Atom, q2: Atom | None = None, name: str = "Darlington") -> Block:
    """Q1 drives Q2; collectors joined. Bind NPNs for an NPN-equivalent, PNPs for a
    PNP-equivalent (then {c} is the compound collector at the negative side). Input drop
    2 Vbe."""
    return Block(name, _DARLINGTON_CANVAS, Q1=q1, Q2=q2 or q1)


_SZIKLAI_CANVAS = """
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


def _sziklai_simple(driver: Atom, output: Atom, name: str = "Sziklai") -> Block:
    """Complementary feedback pair: driver (NPN for an NPN-equivalent) feeds the opposite
    polarity output device, whose emitter is the compound collector. Input drop 1 Vbe."""
    return Block(name, _SZIKLAI_CANVAS, Q1=driver, Q2=output)




def diode_string(n: int, diode: Atom | None = None, name: str | None = None) -> Block:
    """n diodes in series, anode end {a} on top, cathode end {k} at the bottom."""
    if n < 1:
        raise YasdlError("diode_string() needs at least one diode")
    s = Sketch().text(0, 0, "{a}").vline(1, 1, 1)
    for k in range(n):
        s.text(2 + 3 * k, 1, "v").box(3 + 3 * k, 1, f"D{k + 1}").vline(1, 4 + 3 * k, 4 + 3 * k)
    s.text(5 + 3 * (n - 1), 0, "{k}")
    d = diode or D("1N4148")
    return Block(name or f"Diodes{n}", s.render(), **{f"D{k + 1}": d for k in range(n)})


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


def vbe_multiplier(q: Atom | None = None, r1: str = "2.7k", r2: str = "1k",
                   name: str | None = None) -> Block:
    """Adjustable bias "diode" for push_pull(bias=...): V(a, k) = Vbe (1 + R1/R2), R1 from
    collector to base, R2 from base to emitter. Ports {a} N, {k} S, like diode_string.
    Mount the transistor on the output devices' heatsink so the bias tracks them."""
    return Block(name or "VbeMultiplier", VBE_MULTIPLIER, Q1=q or NPN("2N3904"), R1=R(r1), R2=R(r2))


PUSH_PULL_KINDS = {"bjt": 2, "darlington": 4, "sziklai": 2}


def push_pull_template() -> str:
    """Class-AB complementary emitter-follower canvas: holes QN, QP (transistor or compound
    device), BIAS (two-terminal, top to bottom), RB (bias feed from vp), RE1/RE2."""
    L, M, Q = 6, 13, 22
    s = Sketch().text(0, M - 1, "{vp}").vline(M, 1, 1)
    s.text(2, L, "┌").hline(2, L + 1, M - 1).hline(2, M + 1, Q - 1).text(2, Q, "┐").junction(2, M)
    s.vline(L, 3, 3).box(4, L, "RB").vline(L, 5, 5)
    s.text(3, Q - 1, "{c}").box(4, Q, "QN", rows=2).text(4, Q - 3, "{b}").text(6, Q - 1, "{e}")
    s.wire([(4, Q - 3), (4, Q - 4), (6, Q - 4), (6, L + 1)])
    s.vline(L, 7, 7).junction(6, L)
    s.box(8, L, "BIAS").vline(L, 9, 12)
    s.vline(Q, 7, 7).box(8, Q, "RE1").box(10, Q, "RE2").vline(Q, 11, 11)
    s.hline(9, Q + 1, Q + 6).text(9, Q + 7, "{out}").text(9, Q, "├")  # tee between RE1/RE2
    s.text(12, Q - 1, "{e}").box(13, Q, "QP", rows=2).text(13, Q - 3, "{b}").text(15, Q - 1, "{c}")
    s.text(13, 0, "{in}").hline(13, 4, L - 1).wire([(13, Q - 3), (13, L + 1)]).junction(13, L)
    s.vline(Q, 16, 16).text(17, Q - 2, "{vn}")
    return s.render()


def push_pull_vas(
    kind: str = "bjt", npn: Atom | None = None, pnp: Atom | None = None,
    diode: Atom | None = None, rb: str | Atom | Block = "2.2k", re: str = "1",
    qn: Atom | Block | None = None, qp: Atom | Block | None = None,
    bias: Block | None = None, name: str | None = None,
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
        "darlington": (_darlington_simple(npn, name="DarlingtonN"), _darlington_simple(pnp, name="DarlingtonP")),
        "sziklai": (_sziklai_simple(npn, pnp, name="SziklaiN"), _sziklai_simple(pnp, npn, name="SziklaiP")),
    }[kind]
    qn, qp = qn or devices[0], qp or devices[1]
    bias = bias or diode_string(PUSH_PULL_KINDS[kind], diode)
    return Block(
        name or f"PushPull_{kind}", push_pull_template(),
        QN=qn, QP=qp, BIAS=bias, RB=R(rb) if isinstance(rb, str) else rb,
        RE1=R(re), RE2=R(re),
    )


# --- current mirrors (ports in N-left, out N-right, com S) ------------------------------------
MIRROR = """
  {in}             {out}
    │                 │
    ├──────┐          │
    │      │          │
    Q1Q1{b}┴──────{b}Q2Q2
    Q1Q1             Q2Q2
    {e}              {e}
     │                │
     └───────┬────────┘
             │
           {com}
"""


def _plain_mirror(q: Atom, name: str = "Mirror") -> Block:
    """Two-transistor current mirror: Q1 diode-connected on the input side. NPN: a sink with
    {com} at the negative rail; PNP (bind PNPs, flip the block): a source."""
    return Block(name, MIRROR, Q1=q, Q2=q)


WILSON = """
  {in}           {out}
    │              │
    ├──────────{b}Q3Q3
    │             Q3Q3
    │             {e}
    │              │
    Q1Q1{b}────┬───┤
    Q1Q1       │   │
    {e}        └{b}Q2Q2
     │             Q2Q2
     │             {e}
     │              │
     └──────┬───────┘
            │
          {com}
"""


def wilson(q: Atom, name: str = "Wilson") -> Block:
    """Wilson current mirror (higher output resistance, base-current error cancelled)."""
    return Block(name, WILSON, Q1=q, Q2=q, Q3=q)


# --- differential pairs ---------------------------------------------------------------------
DIFF_RES = """
        {o1}  {vp}  {o2}
         │     │     │
         │  ┌──┴──┐  │
         │  R1    R2 │
         │  │     │  │
         ├──┘     └──┤
         │           │
{inp}─{b}Q1Q1       Q2Q2{b}─{inn}
         Q1Q1       Q2Q2
         {e}         {e}
          │           │
          └────┬──────┘
               T1
               │
             {vn}
"""


def _plain_diff_pair(q: Atom, rc: str, tail: str | Atom | Block, name: str = "DiffPair") -> Block:
    """Long-tailed pair: collector resistors rc to {vp}, outputs {o1} (inp side) and {o2}
    (inn side), tail to {vn} as a resistor value or any two-terminal part/block (e.g. a
    current source)."""
    t = R(tail) if isinstance(tail, str) else tail
    return Block(name, DIFF_RES, Q1=q, Q2=q, R1=R(rc), R2=R(rc), T1=t)


DIFF_ACTIVE = """
              {vp}
                │
             LDLDLD
             LDLDLD
             │    │
             │    ├──────{out}
             │    │
{inp}─────{b}Q1  Q2{b}───{inn}
             Q1  Q2
            {e}  {e}
             │    │
             └─┬──┘
               T1
               │
             {vn}
"""


def diff_active(q: Atom, load: Block, tail: str | Atom | Block, name: str = "DiffActive") -> Block:
    """Long-tailed pair with a current-mirror load (e.g. mirror(PNP)) and single-ended
    output {out} on the inn side."""
    t = R(tail) if isinstance(tail, str) else tail
    return Block(name, DIFF_ACTIVE, Q1=q, Q2=q, LD=load, T1=t)


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

def darlington(q1: Atom, q2: Atom | None = None, rx: str = "1k", name: str | None = None) -> Block:
    """A Darlington of two same-polarity transistors (NPN-like with NPNs, PNP-like with PNPs)."""
    b = DARLINGTON.bind(Q1=q1, Q2=q2 or q1, RX=R(rx))
    return b if name is None else Block(name, b.text, **b.bindings)

def sziklai(driver: Atom, output: Atom, rx: str = "1k", name: str | None = None) -> Block:
    """A Sziklai pair behaving like `driver`: sziklai(npn, pnp) is NPN-like."""
    b = SZIKLAI.bind(Q1=driver, Q2=output, RX=R(rx))
    return b if name is None else Block(name, b.text, **b.bindings)

def parallel(device, n: int, re: str = "1", name: str | None = None) -> Block:
    """n identical transistor-like devices in parallel, each with an emitter ballast resistor.

    Three-terminal parts in parallel are not planar: the base bus crosses n-1 emitter stubs.
    The canvas is generated with Sketch, which declares each crossing (spec 7.1)."""
    if not 2 <= n <= 9:
        raise YasdlError(f"parallel(): n must be 2..9, got {n}")
    s = Sketch()
    xs = [6 + 8 * k for k in range(n)]
    mid = (xs[0] + xs[-1]) // 2 + 1 if n % 2 == 0 else xs[n // 2] - 2
    # collector bus with the {c} port
    s.text(0, mid - 1, "{c}").vline(mid, 1, 1)
    s.junction(2, mid, "EWN")
    for k, x in enumerate(xs):
        s.vline(x, 3, 3).box(4, x, f"Q{k + 1}", rows=3)
        if 0 < k < n - 1:
            s.junction(2, x, "EWS")
        else:
            s.text(2, x, "┌" if k == 0 else "┐")
    edges = sorted(xs + [mid])
    for a, b in zip(edges, edges[1:]):
        if b - a > 1:
            s.hline(2, a + 1, b - 1)
    # emitter stubs, ballast resistors, emitter bus with the {e} port
    for k, x in enumerate(xs):
        s.vline(x, 7, 9).box(10, x, f"RE{k + 1}").vline(x, 11, 11)
        s.text(12, x, "└" if k == 0 else ("┘" if k == n - 1 else "┴"))
    s.junction(12, mid, "EWS")
    for a, b in zip(edges, edges[1:]):
        if b - a > 1:
            s.hline(12, a + 1, b - 1)
    s.vline(mid, 13, 13).text(14, mid - 1, "{e}")
    # bases: each drops to a bus on row 8 that crosses the emitter stubs on its way
    s.text(8, 0, "{b}")
    for k, x in enumerate(xs):
        s.hline(5, x - 1, x - 1).text(5, x - 2, "┌").vline(x - 2, 6, 7)
        s.text(8, x - 2, "┴" if k < n - 1 else "┘")
    stops = [x - 2 for x in xs]
    s.hline(8, 3, stops[0] - 1)
    for a, b in zip(stops, stops[1:]):
        s.hline(8, a + 1, b - 1, cross=1)  # crosses the previous device's emitter stub
    bindings = {f"Q{k + 1}": device for k in range(n)}
    bindings.update({f"RE{k + 1}": R(re) for k in range(n)})
    return Block(name or f"Parallel{n}", s.render(), **bindings)

PUSH_PULL_DIODES = {"bjt": 1, "darlington": 2, "sziklai": 1}

PUSH_PULL_DEFAULTS = {
    "bjt": {"rt": "1k", "rq": "15"},
    "darlington": {"rt": "4.7k", "rq": "200"},
    "sziklai": {"rt": "4.7k", "rq": "39"},
}

def _push_pull_canvas(diodes: int) -> str:
    """vp on top; the bias string on the left: RT, the upper base node, `diodes` diodes, the
    {in} node, RQ, `diodes` diodes, the lower base node, RB. The upper NPN-like device QH and the
    lower PNP-like device QL on the right, emitter resistors RH and RL meeting at {out}."""
    s = Sketch()
    xs, xq = 7, 22  # string column, device column
    s.text(0, 13, "{vp}").vline(14, 1, 1)
    s.text(2, xs, "┌").hline(2, xs + 1, 13).junction(2, 14, "EWN").hline(2, 15, xq - 1)
    s.text(2, xq, "┐")
    s.vline(xs, 3, 3).box(4, xs, "RT").vline(xs, 5, 5)
    hb = 6  # upper base row
    s.vline(xq, 3, hb - 3).text(hb - 2, xq - 1, "{c}").box(hb - 1, xq, "QH", rows=3)
    s.junction(hb, xs, "NES").hline(hb, xs + 1, xq - 4).text(hb, xq - 3, "{b}")
    s.text(hb + 2, xq - 1, "{e}").vline(xq, hb + 3, hb + 3).box(hb + 4, xq, "RH")
    row = hb + 1
    for k in range(diodes):  # anode on top: the string current flows downwards
        s.vline(xs, row, row).text(row + 1, xs, "v").box(row + 2, xs, f"DH{k + 1}")
        row += 3
    s.vline(xs, row, row)
    in_row = row + 1
    s.text(in_row, 0, "{in}").hline(in_row, 4, xs - 1).junction(in_row, xs, "NSW")
    s.vline(xs, in_row + 1, in_row + 1).box(in_row + 2, xs, "RQ")
    row = in_row + 3
    for k in range(diodes):
        s.vline(xs, row, row).text(row + 1, xs, "v").box(row + 2, xs, f"DL{k + 1}")
        row += 3
    s.vline(xs, row, row)
    lb = row + 1  # lower base row
    out_row = (hb + 5 + lb - 5) // 2
    s.vline(xq, hb + 5, out_row - 1).junction(out_row, xq, "NES")
    s.hline(out_row, xq + 1, xq + 4).text(out_row, xq + 5, "{out}")
    s.vline(xq, out_row + 1, lb - 5).box(lb - 4, xq, "RL").vline(xq, lb - 3, lb - 3)
    s.text(lb - 2, xq - 1, "{e}").box(lb - 1, xq, "QL", rows=3).text(lb + 2, xq - 1, "{c}")
    s.junction(lb, xs, "NES").hline(lb, xs + 1, xq - 4).text(lb, xq - 3, "{b}")
    s.vline(xs, lb + 1, lb + 1).box(lb + 2, xs, "RB").vline(xs, lb + 3, lb + 3)
    s.vline(xq, lb + 3, lb + 3)
    bot = lb + 4
    s.text(bot, xs, "└").hline(bot, xs + 1, 13).junction(bot, 14, "EWS").hline(bot, 15, xq - 1)
    s.text(bot, xq, "┘").vline(14, bot + 1, bot + 1).text(bot + 2, 13, "{vn}")
    return s.render()

def push_pull_buffer(variant: str, upper, lower, diode: Atom | None = None, rt: str | None = None,
              rb: str | None = None, rq: str | None = None, re: str = "0.22",
              name: str | None = None) -> Block:
    """Class-AB push-pull output stage (unity-gain buffer): {vp} N, {in} W, {out} E, {vn} S.

    variant: "bjt", "darlington" or "sziklai" sets the bias string: PUSH_PULL_DIODES[variant]
    diodes on each side of {in}, so each output half gets the drops it needs. upper/lower are
    NPN-like/PNP-like devices or compound blocks (darlington(), sziklai(), parallel()). RT/RB feed
    the string from the rails; RQ (in series below {in}) trims the quiescent current; RH/RL are
    the emitter resistors (PUSH_PULL_DEFAULTS gives the variant's RT/RB/RQ when omitted). {in}
    is the middle of the string: drive it from a low-impedance or current-mode source whose
    quiescent point is 0 V."""
    if variant not in PUSH_PULL_DIODES:
        raise YasdlError(f"push_pull variant {variant!r}: use one of {sorted(PUSH_PULL_DIODES)}")
    n = PUSH_PULL_DIODES[variant]
    diode = diode or D("1N4148")
    rt = rt or PUSH_PULL_DEFAULTS[variant]["rt"]
    rb = rb or rt
    rq = rq or PUSH_PULL_DEFAULTS[variant]["rq"]
    canvas = _push_pull_canvas(n)
    bindings = dict(QH=upper, QL=lower, RT=R(rt), RB=R(rb), RH=R(re), RL=R(re), RQ=R(rq))
    bindings.update({f"DH{k + 1}": diode for k in range(n)})
    bindings.update({f"DL{k + 1}": diode for k in range(n)})
    return Block(name or f"PushPull_{variant}", canvas, **bindings)

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

def _polarity_mirror(q, kind: str = "npn", re: str = "100", name: str | None = None) -> Block:
    """Two-transistor current mirror with emitter degeneration: {in} (reference current,
    diode-connected Q1) and {out} (Q2's collector) face away from the rail ({vn} for "npn", a
    sink; {vp} for "pnp", a source)."""
    _check_kind(kind)
    canvas = _MIRROR_NPN if kind == "npn" else _MIRROR_PNP
    return Block(name or f"Mirror_{kind}", canvas, Q1=q, Q2=q, RA=R(re), RB=R(re))

def wilson_mirror(q, kind: str = "npn", name: str | None = None) -> Block:
    """Wilson current mirror (higher output resistance, base-current error compensated): Q1
    takes the reference at {in}, Q3 delivers {out}, Q2 is diode-connected."""
    _check_kind(kind)
    canvas = _WILSON_NPN if kind == "npn" else _WILSON_PNP
    return Block(name or f"Wilson_{kind}", canvas, Q1=q, Q2=q, Q3=q)

def _polarity_diff_pair(q, kind: str = "npn", rc: str = "10k", re: str = "100", rt: str = "10k",
              name: str | None = None) -> Block:
    """Long-tailed pair with collector resistors RC1/RC2 and emitter degeneration RE1/RE2 on a
    resistor tail RT: inputs {inp} (W) and {inn} (E), collector outputs {o1} (Q1, inverting
    for inp) and {o2}. "npn": loads to {vp} on top, tail to {vn}; "pnp": tail from {vp}."""
    _check_kind(kind)
    canvas = _LTP_NPN if kind == "npn" else _LTP_PNP
    return Block(name or f"DiffPair_{kind}", canvas, Q1=q, Q2=q, RC1=R(rc), RC2=R(rc),
                 RE1=R(re), RE2=R(re), RT=R(rt))

def diff_pair_mirror(q, load, kind: str = "npn", re: str = "100", rt: str = "10k",
                     name: str | None = None) -> Block:
    """Long-tailed pair with a current-mirror load (complementary transistors `load`), giving
    a single-ended output {out} at Q2/Q4's collectors: {out} rises with {inp} for "npn"."""
    _check_kind(kind)
    canvas = _LTP_MIRROR_NPN if kind == "npn" else _LTP_MIRROR_PNP
    return Block(name or f"DiffPairMirror_{kind}", canvas, Q1=q, Q2=q, Q3=load, Q4=load,
                 RE1=R(re), RE2=R(re), RT=R(rt))

RC_LOWPASS = Block("RCLowPass", """
{in}──R1──┬──{out}
          │
          C1
          │
        [GND]
""")

RC_HIGHPASS = Block("RCHighPass", """
{in}──C1──┬──{out}
          │
          R1
          │
        [GND]
""")

SALLEN_KEY = Block("SallenKey", """
             ┌──────ZF────────┐
             │                │
{in}──ZA─────┴──ZB──┬───+U1U1 │
                    │    U1U1─┼──{out}
                    │  ┌─U1U1 │
                    │  │      │
                    ZS └──────┘
                    │
                  [GND]
""")

def sallen_key_lowpass(r1: str, r2: str, c_shunt: str, c_feedback: str, u=None,
                       name: str | None = None) -> Block:
    """Second-order low-pass (R, R in series; C to ground; C as feedback)."""
    b = SALLEN_KEY.bind(ZA=R(r1), ZB=R(r2), ZS=C(c_shunt), ZF=C(c_feedback))
    b = b.bind(U1=u or OPAMP_IDEAL())
    return b if name is None else Block(name, b.text, **b.bindings)

def sallen_key_highpass(c1: str, c2: str, r_shunt: str, r_feedback: str, u=None,
                        name: str | None = None) -> Block:
    """Second-order high-pass (C, C in series; R to ground; R as feedback)."""
    b = SALLEN_KEY.bind(ZA=C(c1), ZB=C(c2), ZS=R(r_shunt), ZF=R(r_feedback))
    b = b.bind(U1=u or OPAMP_IDEAL())
    return b if name is None else Block(name, b.text, **b.bindings)

INVERTING = Block("Inverting", """
          ┌──RF──┐
          │      │
{in}──RI──┴─U1U1 │
            U1U1─┴──{out}
          ┌+U1U1
          │
        [GND]
""")

NONINVERTING = Block("NonInverting", """
{in}───+U1U1
        U1U1──┬──{out}
     ┌──U1U1  │
     │        │
     ├───RF───┘
     │
     RG
     │
   [GND]
""")

OPAMP_UNUSED = Block("OpampUnused", """
    ┌───────┐
    └──U1U1 │
       U1U1─┘
     ┌+U1U1
     │
   [GND]
""")

def powered_opamp(atom: Atom, name: str | None = None) -> Block:
    """A five-pin op-amp with its supplies wired inside to [VCC] (V+) and [VEE] (V-), exposing
    the three-terminal op-amp interface: {+, inp} and {inn} on the left, {out} on the right.
    Rotating or mirroring the wrapper carries the supply connections along (spec 3.2), and a
    subcircuit export declares VCC/VEE .global (spec 6.2)."""
    return Block(name or "PoweredOpamp", """
        [VCC]
          │
{+, inp}─+U1U1U1
          U1U1U1───{out}
{inn}─────U1U1U1
          │
        [VEE]
""", U1=atom)


def push_pull(kind="bjt", npn=None, pnp=None, diode=None, *, rb=None, re=None,
              qn=None, qp=None, bias=None, rt=None, rq=None, name=None):
    """Class AB stage. rt/rq select the center-driven buffer. qn/qp/bias or a lone rb
    select the bottom-driven VAS stage. Prefer push_pull_buffer/push_pull_vas when choosing
    the drive point explicitly; their input ports are electrically different."""
    if qn is not None or qp is not None or bias is not None or (rb is not None and rt is None and rq is None):
        return push_pull_vas(kind, npn, pnp, diode, rb=rb or "2.2k", re=re or "1",
                             qn=qn, qp=qp, bias=bias, name=name)
    npn, pnp = npn or NPN("2N3904"), pnp or PNP("2N3906")
    if kind == "darlington":
        npn = darlington(npn) if isinstance(npn, Atom) else npn
        pnp = darlington(pnp) if isinstance(pnp, Atom) else pnp
    elif kind == "sziklai" and isinstance(npn, Atom) and isinstance(pnp, Atom):
        npn, pnp = sziklai(npn, pnp), sziklai(pnp, npn)
    return push_pull_buffer(kind, npn, pnp, diode, rt=rt, rb=rb, rq=rq, re=re or "0.22", name=name)


def mirror(q, kind=None, re="100", name=None):
    """Plain mirror with {com}, or a polarity-specific degenerated mirror with {vn}/{vp}.
    Supply kind="npn" or "pnp" to select the latter topology."""
    if kind in ("npn", "pnp"):
        return _polarity_mirror(q, kind, re, name)
    b = _plain_mirror(q, name or kind or "Mirror")
    return Block(b.name, b.text.replace("{com}", "{com, vn}"), **b.bindings)


def diff_pair(q, *args, kind="npn", rc="10k", re="100", rt="10k", tail=None, name=None):
    """A long-tailed pair. (q, rc, tail) accepts any two-terminal tail; kind/rt/re select
    a polarity-specific resistor-tail pair with emitter degeneration."""
    if args and args[0] not in ("npn", "pnp") or tail is not None:
        rc = args[0] if args else rc
        tail = args[1] if len(args) > 1 else tail
        return _plain_diff_pair(q, rc, tail, name or "DiffPair")
    return _polarity_diff_pair(q, args[0] if args else kind, rc, re, rt, name)
