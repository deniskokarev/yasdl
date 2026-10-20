"""Minimal S-expression reader/writer for KiCad files."""

from __future__ import annotations


class Sym(str):
    """An unquoted atom (keyword or number), as opposed to a quoted string."""


def parse(text: str):
    """Parse one S-expression into nested lists of Sym / str."""
    pos, n = 0, len(text)

    def skip():
        nonlocal pos
        while pos < n and text[pos].isspace():
            pos += 1

    def node():
        nonlocal pos
        skip()
        ch = text[pos]
        if ch == "(":
            pos += 1
            out = []
            while True:
                skip()
                if text[pos] == ")":
                    pos += 1
                    return out
                out.append(node())
        if ch == '"':
            pos += 1
            buf = []
            while text[pos] != '"':
                if text[pos] == "\\":
                    pos += 1
                buf.append(text[pos])
                pos += 1
            pos += 1
            return "".join(buf)
        start = pos
        while pos < n and not text[pos].isspace() and text[pos] not in "()":
            pos += 1
        return Sym(text[start:pos])

    return node()


def find(node, key):
    """First child list whose head is `key`."""
    return next((c for c in node if isinstance(c, list) and c and c[0] == key), None)


def find_all(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


def dumps(node, indent: int = 0) -> str:
    """Serialise nested lists back to KiCad-style text (tab-indented)."""
    if not isinstance(node, list):
        if isinstance(node, Sym):
            return str(node)
        return '"' + str(node).replace("\\", "\\\\").replace('"', '\\"') + '"'
    if all(not isinstance(c, list) for c in node):
        return "(" + " ".join(dumps(c) for c in node) + ")"
    pad = "\t" * (indent + 1)
    head = [dumps(c) for c in node if not isinstance(c, list)]
    parts = ["(" + " ".join(head)]
    for c in node:
        if isinstance(c, list):
            parts.append("\n" + pad + dumps(c, indent + 1))
    parts.append("\n" + "\t" * indent + ")")
    return "".join(parts)
