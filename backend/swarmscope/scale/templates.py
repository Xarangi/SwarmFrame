"""Message template mining (a small Drain-style miner).

Thousands of agents writing thousands of messages say far fewer *kinds* of thing. The miner masks the variable parts
of each agent-written text (numbers, ids, urls, paths, emails), then groups texts whose remaining tokens agree
position by position. Models see a few hundred templates with counts, spread and example ids, never the firehose.

Templates are computed from untrusted text, so their wording is untrusted too: tools expose ids, counts and spread,
and only roles with raw access get a masked preview, wrapped in the untrusted envelope.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_MASKS = [
    (re.compile(r"https?://\S+|www\.\S+"), "<url>"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "<email>"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<id>"),
    (re.compile(r"\b(?:[A-Za-z]:)?(?:[\\/][\w.-]+){2,}"), "<path>"),
    (re.compile(r"\b(?=\w*\d)[0-9a-f]{10,}\b", re.I), "<hex>"),
    (re.compile(r"\b\d+(?:[.,:]\d+)*\b"), "<num>"),
]
_TOKEN = re.compile(r"<\w+>|[\w'’-]+|[^\w\s]")
VAR = "<*>"


def mask(text: str, max_tokens: int = 32) -> list[str]:
    t = text[:600]
    for rx, rep in _MASKS:
        t = rx.sub(rep, t)
    return [w.lower() for w in _TOKEN.findall(t)[:max_tokens]]


def _is_var(tok: str) -> bool:
    return tok.startswith("<") and tok.endswith(">")


@dataclass
class Template:
    id: str
    tokens: list[str]
    count: int = 0
    units: Counter = field(default_factory=Counter)
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    examples: list[str] = field(default_factory=list)       # event ids: first few, then latest
    recent: deque = field(default_factory=lambda: deque(maxlen=48))   # (window index, count)
    cohorts: Counter = field(default_factory=Counter)

    @property
    def text(self) -> str:
        return " ".join(self.tokens)

    def window_counts(self, idx: int, span: int) -> tuple[int, int]:
        """Count in the last `span` windows and in the `span` before that."""
        now = sum(n for i, n in self.recent if idx - span < i <= idx)
        prev = sum(n for i, n in self.recent if idx - 2 * span < i <= idx - span)
        return now, prev


class TemplateMiner:
    def __init__(self, similarity: float = 0.55, max_templates: int = 20000):
        self.similarity = similarity
        self.max_templates = max_templates
        self.groups: dict[tuple, list[Template]] = {}
        self.templates: dict[str, Template] = {}
        self.by_artifact: dict[str, str] = {}

    def _key(self, toks: list[str]) -> tuple:
        lead = tuple(t for t in toks[:3] if not _is_var(t))[:2]
        return (min(len(toks), 24) // 3, lead)

    @staticmethod
    def _sim(a: list[str], b: list[str]) -> float:
        n = max(len(a), len(b))
        if not n:
            return 1.0
        same = sum(1 for x, y in zip(a, b) if x == y or x == VAR)
        return same / n

    def assign(self, artifact_id: str, text: str) -> str:
        if artifact_id in self.by_artifact:
            return self.by_artifact[artifact_id]
        toks = mask(text)
        key = self._key(toks)
        group = self.groups.setdefault(key, [])
        best, score = None, 0.0
        for t in group:
            s = self._sim(t.tokens, toks)
            if s > score:
                best, score = t, s
        if best is not None and score >= self.similarity:
            if len(best.tokens) == len(toks):
                best.tokens = [x if x == y else VAR for x, y in zip(best.tokens, toks)]
            tid = best.id
        elif len(self.templates) < self.max_templates:
            tid = "tpl_" + hashlib.sha1(" ".join(toks).encode()).hexdigest()[:8]
            if tid not in self.templates:
                t = Template(id=tid, tokens=toks)
                self.templates[tid] = t
                group.append(t)
        else:
            tid = "tpl_overflow"
            self.templates.setdefault(tid, Template(id=tid, tokens=["<overflow>"]))
        self.by_artifact[artifact_id] = tid
        return tid

    def observe(self, tid: str, unit: str | None, ts: datetime, event_id: str, window_index: int,
                cohort: str | None = None) -> None:
        t = self.templates.get(tid)
        if t is None:
            return
        t.count += 1
        if unit:
            t.units[unit] += 1
        if cohort:
            t.cohorts[cohort] += 1
        t.first_ts = t.first_ts or ts
        t.last_ts = ts
        if len(t.examples) < 3:
            t.examples.append(event_id)
        elif len(t.examples) < 6 or t.count % 50 == 0:
            t.examples = t.examples[:3] + (t.examples[3:] + [event_id])[-3:]
        if t.recent and t.recent[-1][0] == window_index:
            i, n = t.recent[-1]
            t.recent[-1] = (i, n + 1)
        else:
            t.recent.append((window_index, 1))

    def stats(self) -> dict[str, Any]:
        live = [t for t in self.templates.values() if t.count]
        return {"templates": len(live), "messages": sum(t.count for t in live),
                "compression": round(sum(t.count for t in live) / max(1, len(live)), 1)}
