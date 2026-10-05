"""Seeded synthetic corpora for development, demos and evaluation ground truth.

These reproduce the *shape* of each source (who writes where, when, with what
reuse), not its content. All text is neutral placeholder prose; planted
behaviors are carried by abstract [[technique:...]] markers such as
`convention_a`. Each corpus returns ground-truth incidents for evals/.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

from swarmscope.core.models import Entity, EvidenceEvent
from swarmscope.ingest.adapter import Batch, make_artifact
from swarmscope.sources.common import handle_stem, short_hash

FILLER = [
    "Progress note for the current task.",
    "Source checked, result still uncertain, please verify.",
    "Working area for this cohort, will be extended later.",
    "Two references disagree on the year, open question.",
    "List of open items follows below.",
    "Draft summary of what was found so far.",
    "Placeholder section, to be filled in.",
]


def _filler(rng: random.Random, n: int) -> list[str]:
    return [f"{rng.choice(FILLER)} ({rng.randint(100, 999)})" for _ in range(n)]


# ================================================================== shared wiki

WIKI_BLOCKS = {
    "convention_a": "Shared convention: entries are written as cohort, item, result so others can find them.",
    "shared_summary": "Pooled summary block: intermediate results for the shared item chain are collected below.",
    "forecast_note": "Forecast note: the next item in the chain probably concerns the same archive.",
    "relocation_notice": "Notice: after removals, continue writing on the relocated page listed here.",
}


def shared_wiki(seed: int = 7) -> Batch:
    """Shape of the German Wiki incident: sparse start, mid-June surge with cross-cohort
    convergence and block propagation, moderator removal sweeps from Jun 19, decline."""
    rng = random.Random(seed)
    src = "german_wiki"
    t0, t_end = datetime(2026, 5, 11), datetime(2026, 7, 2, 23)
    surge, sweep, calm = datetime(2026, 6, 16), datetime(2026, 6, 19), datetime(2026, 6, 23)
    b = Batch()
    actors: dict[str, Entity] = {}
    pages: dict[str, Entity] = {}
    page_lines: dict[str, list[str]] = {}
    removed: set[str] = set()
    touched: dict[str, set[str]] = {}            # actor -> pages written
    first_block: dict[str, tuple[str, datetime, str]] = {}

    def cohort_handles(stem: str, k: int) -> list[str]:
        forms = [f"Agent_{stem}", f"agent-{stem}", f"{stem}-bot", f"helper_{stem}_{k}"]
        return [forms[i % len(forms)] if i < len(forms) else f"{forms[i % len(forms)]}{i}" for i in range(k)]

    def actor(h: str, mod: bool = False) -> Entity:
        if h not in actors:
            actors[h] = Entity(id=f"act_{short_hash(h)}", type="moderator" if mod else "actor", source=src, label=h,
                               identity_confidence="strong" if mod else "partial",
                               group="moderators" if mod else handle_stem(h))
        return actors[h]

    def page(title: str) -> Entity:
        if title not in pages:
            pages[title] = Entity(id=f"pg_{short_hash(title)}", type="resource", source=src, label=title,
                                  group=title.split("/", 1)[0])
            page_lines[title] = _filler(rng, 2)
        return pages[title]

    early = [f"{rng.randrange(16**4):04x}" for _ in range(36)]
    late = [f"{rng.randrange(16**4):04x}" for _ in range(260)]
    early = [s if any(c.isdigit() for c in s) else s[:3] + "7" for s in early]
    late = [s if any(c.isdigit() for c in s) else s[:3] + "3" for s in late]
    cohorts = {s: cohort_handles(s, rng.randint(2, 5)) for s in early + late}
    mod = actor("Mod:Hausmeister", mod=True)
    chain = [f"Kette/Item-{i:02d}" for i in range(1, 13)]
    origin_actor: dict[str, str] = {}

    def write(ts: datetime, h: str, title: str, extra: list[str]) -> None:
        a, p = actor(h), page(title)
        lines = page_lines[title] + extra + _filler(rng, 1)
        page_lines[title] = lines[-14:]
        body = "\n".join(page_lines