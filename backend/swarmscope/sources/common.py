from __future__ import annotations

import hashlib
import re

_STEM_STRIP = re.compile(r"[^a-z0-9]")


def handle_stem(handle: str) -> str:
    """Cheap identity heuristic: case/punctuation-insensitive core of a handle.

    'Agent_7f3a', 'agent-7f3a' and '7f3a-bot' share the hex core '7f3a'. Falls back
    to the first 6 normalized characters. Deliberately crude: identity resolution
    is a monitor's job, this only seeds groups.
    """
    h = handle.lower()
    for tok in re.split(r"[^a-z0-9]+", h):
        if re.fullmatch(r"[0-9a-f]{4,6}", tok) and re.search(r"\d", tok):
            return tok
    core = _STEM_STRIP.sub("", h)
    core = re.sub(r"\d+$", "", core) or core
    return core[:8] or "anon"


def short_hash(*parts: object, n: int = 10) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:n]


def family_of(title: str) -> str:
    """Resource family of a wiki page title / URL path: the first path segment."""
    t = title.strip().strip("/")
    for sep in ("/", ":"):
        if sep in t:
            return t.split(sep, 1)[0]
    return t.split(" ", 1)[0][:24] or "root"
