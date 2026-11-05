"""Linear circuit analysis of a yasdl design: modified nodal analysis (MNA) in the s-domain.

The design is flattened (the same recursion as the netlist), so a transfer function comes for
free with every drawing, exact whatever the loading between stages. Supported elements: R, C,
L, independent V and I sources, and the ideal op-amp (OPAMP_IDEAL) as a nullor: V(+) = V(-),
no input current, output current free.

- Numeric solving is stdlib only (complex Gaussian elimination with pivoting).
- `Circuit.transfer_symbolic` needs sympy (optional); symbols are the element names.

    ckt = Circuit(block)
    ckt.transfer("V1", "vo", s=2j * math.pi * 1e3)        # numeric, values from the bindings
    ckt.transfer_symbolic("V1", "vo")                      # sympy expression in R1, C1, ..., s
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .block import Block, YasdlError, flat_names, ground_root
from .spice import _instances, check_value, spice_model

_SUFFIX = {"t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "m": 1e-3, "u": 1e-6, "µ": 1e-6,
           "n": 1e-9, "p": 1e-12, "f": 1e-15}
_NUMBER = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*(meg|[tgkmuµnpf])?",
                     re.IGNORECASE)


def parse_value(text: str) -> float | None:
    """SPICE number with an optional scale suffix ("4.7k", "100n", "2meg"); None if absent.
    Trailing units are ignored ("10uF")."""
    m = _NUMBER.match(text or "")
    if not m:
        return None
    return float(m.group(1)) * _SUFFIX.get((m.group(2) or "").lower(), 1.0)


@dataclass(frozen=True)
class Element:
    """One flattened element. nodes are SPICE-ordered net names, ground is "0".
    kind: R, C, L, V, I or OPAMP (nodes: +, -, out)."""

    name: str  # leaf component name (unique per design, else the flattened path)
    path: str  # flattened yasdl path, e.g. "INT1.RI"
    kind: str
    nodes: tuple[str, ...]
    value: float | None


_KIND = {"Device:R": "R", "Device:C": "C", "Device:C_Polarized": "C", "Device:L": "L",
         "Simulation_SPICE:VDC": "V", "Simulation_SPICE:IDC": "I", "yasdl:OPAMP_IDEAL": "OPAMP"}


def elements(block: Block) -> list[Element]:
    """The flattened linear elements of `block`, with net names as in `netlist()` (GND -> "0").

    Element names are the components' own names when those are unique across the design,
    otherwise the flattened path with "." replaced by "_"."""
    uf, pins, names = flat_names(block)
    gnd = ground_root(uf)

    def node(n):
        root = uf.find(n)
        return "0" if root == gnd else names[root]

    # Non-simulated physical parts (connectors, jacks) are left out, as in spice_netlist().
    insts = [(path, atom) for path, _, atom in _instances(block)
             if not atom.symbol.is_power and atom.sim]
    leaves = [p.rsplit(".", 1)[-1] for p, _ in insts]
    unique = len({x.casefold() for x in leaves}) == len(leaves)
    out = []
    for (path, atom), leaf in zip(insts, leaves):
        kind = _KIND.get(atom.lib_id)
        if kind is None:
            raise YasdlError(f"{path}: {atom.lib_id} is not a linear element analysis supports")
        m = spice_model(atom)
        assert m is not None  # every linear element kind has a SPICE model
        nodes = []
        for pin in m.pins:
            if (path, pin) not in pins:
                raise YasdlError(f"{path}: pin {pin} is not drawn")
            nodes.append(node(pins[(path, pin)]))
        if kind in "RCL":
            check_value(path, kind, atom.value)
        value = _source_value(atom.value) if kind in "VI" else parse_value(atom.value)
        out.append(Element(leaf if unique else path.replace(".", "_"), path, kind, tuple(nodes), value))
    return out


def _source_value(spec: str) -> float:
    """Small-signal amplitude of a source spec: its `ac` magnitude, else its DC value, else 1."""
    m = re.search(r"\bac\s+([^\s]+)", spec or "", re.IGNORECASE)
    if m:
        return parse_value(m.group(1)) or 0.0
    v = parse_value(re.sub(r"^\s*dc\s+", "", spec or "", flags=re.IGNORECASE))
    return 1.0 if v is None else v


class Circuit:
    """MNA system of a flattened design. Unknowns: node voltages, then one branch current per
    V source, inductor and op-amp output."""

    def __init__(self, block: Block):
        self.elements = elements(block)
        self.by_name = {e.name: e for e in self.elements}
        self.nodes = sorted({n for e in self.elements for n in e.nodes} - {"0"})
        self.index = {n: i for i, n in enumerate(self.nodes)}
        self.branches = [e for e in self.elements if e.kind in ("V", "L", "OPAMP")]
        self.size = len(self.nodes) + len(self.branches)

    @property
    def values(self) -> dict[str, float]:
        return {e.name: e.value for e in self.elements if e.value is not None and e.kind in "RCL"}

    # -- assembly, generic over the number type (complex or sympy) ---------------------------
    def _system(self, s, val, sources, zero, one):
        n = self.size
        A = [[zero] * n for _ in range(n)]
        b = [zero] * n
        idx = self.index

        def add(r, c, v):
            if r is not None and c is not None:
                A[r][c] = A[r][c] + v

        def row(node):
            return idx.get(node)

        for k, e in enumerate(self.elements):
            if e.kind in ("R", "C"):
                y = one / val(e) if e.kind == "R" else s * val(e)
                p, q = row(e.nodes[0]), row(e.nodes[1])
                add(p, p, y), add(q, q, y), add(p, q, -y), add(q, p, -y)
            elif e.kind == "I":
                i = sources.get(e.name, zero)
                p, q = row(e.nodes[0]), row(e.nodes[1])
                if p is not None:  # SPICE: current flows from n+ through the source to n-
                    b[p] = b[p] - i
                if q is not None:
                    b[q] = b[q] + i
        for j, e in enumerate(self.branches):
            k = len(self.nodes) + j
            if e.kind in ("V", "L"):
                p, q = row(e.nodes[0]), row(e.nodes[1])
                add(p, k, one), add(q, k, -one)  # branch current enters n+ ... leaves n-
                add(k, p, one), add(k, q, -one)
                if e.kind == "V":
                    b[k] = sources.get(e.name, zero)
                else:
                    add(k, k, -s * val(e))
            else:  # nullor: output current free, V(+) - V(-) = 0
                plus, minus, out = (row(x) for x in e.nodes)
                add(out, k, one)
                add(k, plus, one), add(k, minus, -one)
        return A, b

    def _sources(self, source, sources):
        if sources is None:
            if source not in self.by_name or self.by_name[source].kind not in "VI":
                raise YasdlError(f"{source!r} is not an independent source")
            sources = {source: 1}
        return sources

    def solve(self, s: complex, source: str | None = None, sources: dict | None = None,
              values: dict | None = None) -> dict[str, complex]:
        """Node voltages at complex frequency s. `source` drives one source with 1 (others 0);
        `sources` sets each source's value. `values` overrides element values by name."""
        vals = {**self.values, **(values or {})}

        def val(e):
            if e.name not in vals:
                raise YasdlError(f"{e.name}: no numeric value; bind one or pass values=")
            return complex(vals[e.name])

        A, b = self._system(complex(s), val, self._sources(source, sources), 0j, 1 + 0j)
        x = _gauss(A, b)
        out = {"0": 0j}
        out.update({n: x[i] for n, i in self.index.items()})
        return out

    def transfer(self, source: str, out: str, ref: str = "0", s: complex = 1j,
                 values: dict | None = None) -> complex:
        """(V(out) - V(ref)) / source at complex frequency s."""
        v = self.solve(s, source, values=values)
        for n in (out, ref):
            if n not in v:
                raise YasdlError(f"no net {n!r}; nets: {', '.join(self.nodes)}")
        return v[out] - v[ref]

    def transfer_symbolic(self, source: str, out: str, ref: str = "0", numeric: bool = False,
                          simplify: bool = True):
        """Exact H(s) as a sympy expression in s and the element names (numeric=True plugs in
        the bound values as exact rationals). Cramer's rule, determinants over a polynomial
        ring."""
        import sympy as sp

        s = sp.Symbol("s")
        syms = {e.name: sp.Symbol(e.name, positive=True) for e in self.elements if e.kind in "RCL"}
        # Resistors are stamped as conductance symbols so every matrix entry is a polynomial:
        # determinants over a polynomial ring are much faster than over its fraction field.
        cond = {e.name: sp.Dummy("G_" + e.name, positive=True) for e in self.elements
                if e.kind == "R" and not numeric}

        def val(e):
            if numeric:
                if e.value is None:
                    raise YasdlError(f"{e.name}: no numeric value")
                return sp.nsimplify(e.value, rational=True)
            if e.kind == "R":
                return 1 / cond[e.name]
            return syms[e.name]

        from sympy.polys.matrices import DomainMatrix

        A, b = self._system(s, val, self._sources(source, None), sp.Integer(0), sp.Integer(1))
        n = len(A)

        def det(rows):
            # Polynomial-ring determinant: orders of magnitude faster than Matrix.det on
            # expressions (a 10-unknown circuit: about a second instead of minutes).
            M = DomainMatrix.from_list_sympy(n, n, rows)
            return M.domain.to_sympy(M.det())

        d = det(A)
        if d == 0:
            raise YasdlError(f"{source} -> {out}: the circuit has no unique solution (singular MNA)")

        def node_numerator(node):
            if node == "0":
                return sp.Integer(0)
            k = self.index[node]
            return det([[b[r] if c == k else A[r][c] for c in range(n)] for r in range(n)])

        h = (node_numerator(out) - node_numerator(ref)) / d
        h = h.xreplace({g: 1 / syms[name] for name, g in cond.items()})
        return sp.factor(sp.cancel(h)) if simplify else h


def _gauss(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    scale = max((abs(v) for row in A for v in row), default=1.0) or 1.0
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) <= 1e-12 * scale:
            raise YasdlError("the circuit has no unique solution (singular MNA matrix)")
        M[c], M[p] = M[p], M[c]
        piv = M[c][c]
        for r in range(c + 1, n):
            f = M[r][c] / piv
            if f:
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    x = [0j] * n
    for r in range(n - 1, -1, -1):
        x[r] = (M[r][n] - sum(M[r][k] * x[k] for k in range(r + 1, n))) / M[r][r]
    return x
