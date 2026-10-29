"""Copy SPICE model resources into a movable schematic project.

A model library and every file it reaches through literal `.include`/`.inc` lines are copied
into one directory; include paths are rewritten to the copied file names. A copy keeps its
original file name unless the directory already holds a different file of that name; then
it is named `<stem>_<digest><suffix>`, the digest taken over the rewritten text. A rewritten
include names its child's copy, so two equal parent files that include different child
models get different copies.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_INCLUDE = re.compile(
    r"(?im)^(\s*\.(?:include|inc)\s+)(?:\"([^\"]+)\"|'([^']+)'|(\S+))([^\n]*)$"
)


def copy_model_resource(source, destination, cache=None, _active=None) -> Path:
    """Copy `source` and its include closure into `destination`; return the copied path.

    cache: {resolved source: copied path}, shared across calls to copy each file once.
    Missing files raise FileNotFoundError and include cycles ValueError, naming the path.
    """
    source = Path(source).expanduser().resolve()
    destination = Path(destination)
    cache = {} if cache is None else cache
    active = set() if _active is None else _active
    if source in active:
        raise ValueError(f"cyclic SPICE include: {source} includes itself")
    if source in cache:
        return cache[source]
    try:
        text = source.read_bytes().decode(errors="replace")
    except OSError as e:
        raise FileNotFoundError(
            f"copying SPICE model resource: cannot read {source}; restore the file or "
            "correct the library path or the .include that names it"
        ) from e
    active.add(source)

    def include(m):
        child = Path(m[2] or m[3] or m[4]).expanduser()
        if not child.is_absolute():
            child = source.parent / child
        copied = copy_model_resource(child, destination, cache, active)
        return f'{m[1]}"{copied.name}"{m[5]}'

    text = _INCLUDE.sub(include, text)
    active.remove(source)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / source.name
    if target.exists() and target.read_text(errors="replace") != text:
        digest = hashlib.sha256(text.encode()).hexdigest()[:12]
        target = destination / f"{source.stem}_{digest}{source.suffix}"
    if not target.exists() or target.read_text(errors="replace") != text:
        target.write_text(text)
    cache[source] = target
    return target
