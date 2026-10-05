"""The scale layer: deterministic compression of a large population into units, cohorts, templates and a
triage queue, so model attention grows with the number of cohorts, not the number of agents or messages.

  unit      what the population is made of: an agent (identities present) or a key such as the targeted
            resource (identity-free sources like scan reports)
  profile   per-unit streaming statistics: workstream / action / resource / template mix, rate, self-shift
  cohort    units that behave alike, by an interpretable signature (dominant workstream, action, group,
            rate tier). Ids are stable because the signature is the id
  outlier   a unit far from its cohort's centroid, or far from its own history
  template  a kind of message (scale/templates.py), with spread across units and cohorts

Everything here is code. It runs every window, never calls a model, and is what the organization's tools and
the triage allocator (scale/triage.py) read.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from swarmscope.scale.templates import TemplateMiner

if TYPE_CHECKING:
    from swarmscope.core.models import EvidenceEvent

SKIP_ACTORS = {"operator", "summarizer", "system"}
TEXT_ACTIONS_SKIP = {"goal.start", "goal.assign", "summary.generated"}


def _norm(c: Counter) -> dict[str, float]:
    s = sum(c.values()) or 1
    return {k: v / s for k, v in c.items()}


def tv(a: dict[str, float], b: dict[str, float]) -> float:
    """Total variation distance between two distributions (0 = same, 1 = disjoint)."""
    return 0.5 * sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in set(a) | set(b))


@dataclass
class Profile:
    unit: str
    n: int = 0
    fam: Counter = field(default_factory=Counter)
    act: Counter = field(default_factory=Counter)
    res: Counter = field(default_factory=Counter)
    tpl: Counter = field(default_factory=Counter)
    errors: int = 0
    first: datetime | None = None
    last: datetime | None = None
    last_window: int = -1
    windows: deque = field(default_factory=lambda: deque(maxlen=96))     # (window index, Counter of mix keys)
    group: str | None = None
    extra: dict = field(default_factory=dict)                            # attr:<key> -> Counter of values

    def add(self, e: "EvidenceEvent", widx: int, fam: str, tpl: str | None) -> None:
        self.n += 1
        self.fam[fam] += 1
        act = (e.action or "other").split(".")[0]
        self.act[act] += 1
        if e.object:
            self.res[e.object] += 1
            if len(self.res) > 60:
                self.res = Counter(dict(self.res.most_common(30)))
        if tpl:
            self.tpl[tpl] += 1
            if len(self.tpl) > 60:
                self.tpl = Counter(dict(self.tpl.most_common(30)))
        if any(k in (e.action or "") for k in ("error", "denied", "blocked", "fail")):
            self.errors += 1
        self.first = self.first or e.ts
        self.last = e.ts
        if not self.windows or self.windows[-1][0] != widx:
            self.windows.append((widx, Counter()))
        self.windows[-1][1][f"f:{fam}"] += 1
        self.windows[-1][1][f"a:{act}"] += 1
        self.last_window = widx

    def span_counts(self, idx: int, span: int) -> tuple[Counter, Counter]:
        now, prev = Counter(), Counter()
        for i, c in self.windows:
            if idx - span < i <= idx:
                now.update(c)
            elif idx - 2 * span < i <= idx - span:
                prev.update(c)
        return now, prev

    def rate(self, idx: int, span: int) -> tuple[int, int]:
        now, prev = self.span_counts(idx, span)
        return sum(v for k, v in now.items() if k.startswith("f:")), sum(v for k, v in prev.items() if k.startswith("f:"))

    def mix(self, idx: int, span: int) -> dict[str, float]:
        now, _ = self.span_counts(idx, span)
        return _norm(now) if now else _norm(Counter({f"f:{k}": v for k, v in self.fam.items()}
                                                    | {f"a:{k}": v for k, v in self.act.items()}))

    def self_shift(self, idx: int, span: int) -> float:
        now, prev = self.span_counts(idx, span)
        if sum(now.values()) < 8 or sum(prev.values()) < 8:
            return 0.0
        return tv(_norm(now), _norm(prev))

    def dominant(self, what: str) -> str:
        if what.startswith("attr:"):
            c = self.extra.get(what)
            return c.most_common(1)[0][0] if c else "none"
        c = {"family": self.fam, "action": self.act, "resource": self.res}.get(what)
        if c is None:
            return self.group or "ungrouped"
        return c.most_common(1)[0][0] if c else "none"


@dataclass
class Cohort:
    id: str
    signature: tuple
    label: str
    members: list[str] = field(default_factory=list)
    events_now: int = 0
    events_prev: int = 0
    mix: dict[str, float] = field(default_factory=dict)
    top_resources: list[tuple[str, int]] = field(default_factory=list)
    top_templates: list[tuple[str, int]] = field(default_factory=list)
    outliers: list[tuple[str, float, str]] = field(default_factory=list)   # (unit, score, why)
    created_window: int = 0
    prev_size: int = 0

    @property
    def change(self) -> float:
        return math.log2((self.events_now + 1) / (self.events_prev + 1))


class ScaleLayer:
    def __init__(self, cfg: dict[str, Any] | None = None, label=None, entity=None, identities: bool = True):
        self.cfg = {"unit": "actor" if identities else "object", "signature": ["family", "action", "group"],
                    "span_windows": 6, "lookback_windows": 36, "recluster_every": 3, "max_cohort_size": 400,
                    "min_cohort_size": 3, "outlier_threshold": 0.55, **(cfg or {})}
        self.label = label or (lambda x: x or "unknown")
        self.entity = entity or (lambda x: None)
        self.profiles: dict[str, Profile] = {}
        self.cohorts: dict[str, Cohort] = {}
        self.unit_cohort: dict[str, str] = {}
        self.miner = TemplateMiner()
        self.window_index = -1
        self.events_total = 0
        self.texts_total = 0
        self.history: deque = deque(maxlen=200)                  # (window index, events) for the population rate
        self._art_text: dict[str, str] = {}
        self._attr_keys = [k for k in self.cfg["signature"] if str(k).startswith("attr:")]

    # ------------------------------------------------------------ units
    def unit_of(self, e: "EvidenceEvent") -> str | None:
        u = self.cfg["unit"]
        if u == "actor":
            a = e.actor
            if not a or a in SKIP_ACTORS or a.startswith("human:"):
                return None
            return a
        if u == "object":
            return e.object
        if u.startswith("attr:"):
            v = e.attributes.get(u[5:])
            return f"{u[5:]}:{v}" if v is not None else None
        return e.actor

    def scope_of_unit(self, unit: str) -> str:
        return f"agent:{unit}" if self.cfg["unit"] == "actor" else f"resource:{unit}"

    # ------------------------------------------------------------ ingest
    def add_texts(self, items: list[tuple[str, str | None]]) -> None:
        """Artifacts as they are ingested: assign each a template (code only)."""
        for aid, text in items:
            if text:
                self.miner.assign(aid, text)

    def observe_window(self, widx: int, events: list["EvidenceEvent"]) -> None:
        self.window_index = widx
        self.history.append((widx, len(events)))
        for e in events:
            self.events_total += 1
            unit = self.unit_of(e)
            fam = e.attributes.get("family") or "other"
            tpl = self.miner.by_artifact.get(e.artifact) if e.artifact else None
            if tpl:
                self.texts_total += 1
                self.miner.observe(tpl, unit, e.ts, e.id, widx, self.unit_cohort.get(unit) if unit else None)
            if unit is None or fam in ("goal", "summary"):
                continue
            p = self.profiles.get(unit)
            if p is None:
                ent = self.entity(unit)
                p = self.profiles[unit] = Profile(unit=unit, group=getattr(ent, "group", None))
            p.add(e, widx, fam, tpl)
            for k in self._attr_keys:
                v = e.attributes.get(k[5:])
                if v is not None:
                    p.extra.setdefault(k, Counter())[str(v)] += 1
        if widx % int(self.cfg["recluster_every"]) == 0 or not self.cohorts:
            self.recluster()
        else:
            self._refresh_stats()

    # ------------------------------------------------------------ cohorts
    def active_units(self) -> list[Profile]:
        lb = int(self.cfg["lookback_windows"])
        return [p for p in self.profiles.values() if p.last_window > self.window_index - lb]

    def _signature(self, p: Profile, tiers: dict[str, str]) -> tuple:
        sig = tuple(p.dominant(k) for k in self.cfg["signature"])
        return sig + ((tiers.get(p.unit),) if p.unit in tiers else ())

    def recluster(self) -> None:
        units = self.active_units()
        span = int(self.cfg["span_windows"])
        groups: dict[tuple, list[Profile]] = {}
        for p in units:
            groups.setdefault(self._signature(p, {}), []).append(p)
        # split oversized cohorts by rate tier, so one cohort never hides a busy minority
        tiers: dict[str, str] = {}
        for sig, ps in list(groups.items()):
            if len(ps) > int(self.cfg["max_cohort_size"]):
                rates = sorted(math.log1p(p.rate(self.window_index, span)[0]) for p in ps)
                lo, hi = rates[len(rates) // 3], rates[2 * len(rates) // 3]
                for p in ps:
                    r = math.log1p(p.rate(self.window_index, span)[0])
                    tiers[p.unit] = "quiet" if r <= lo else "busy" if r > hi else "steady"
        if tiers:
            groups = {}
            for p in units:
                groups.setdefault(self._signature(p, tiers), []).append(p)
        # fold tiny cohorts into "other <dominant family>", so noise does not become a cohort of its own
        minsz = int(self.cfg["min_cohort_size"])
        folded: dict[tuple, list[Profile]] = {}
        for sig, ps in groups.items():
            key = sig if len(ps) >= minsz or len(units) < 4 * minsz else (sig[0], "mixed")
            folded.setdefault(key, []).extend(ps)
        prev = self.cohorts
        self.cohorts, self.unit_cohort = {}, {}
        for sig, ps in folded.items():
            cid = "coh_" + hashlib.sha1("|".join(map(str, sig)).encode()).hexdigest()[:6]
            keys = list(self.cfg["signature"]) + ["tier"]
            parts = [self.label(s) if k == "resource" else str(s) for k, s in zip(keys, sig)
                     if s not in ("none", "ungrouped")]
            lab = " · ".join(parts) or "unclassified"
            old = prev.get(cid)
            c = Cohort(id=cid, signature=sig, label=lab, members=[p.unit for p in ps],
                       created_window=old.created_window if old else self.window_index,
                       prev_size=len(old.members) if old else 0)
            self.cohorts[cid] = c
            for p in ps:
                self.unit_cohort[p.unit] = cid
        self._refresh_stats()

    def _refresh_stats(self) -> None:
        span = int(self.cfg["span_windows"])
        idx = self.window_index
        for c in self.cohorts.values():
            ps = [self.profiles[u] for u in c.members if u in self.profiles]
            now = prev = 0
            res, tpl = Counter(), Counter()
            mixes = []
            for p in ps:
                a, b = p.rate(idx, span)
                now, prev = now + a, prev + b
                res.update(dict(p.res.most_common(5)))
                tpl.update(dict(p.tpl.most_common(5)))
                mixes.append(p.mix(idx, span))
            c.events_now, c.events_prev = now, prev
            centroid: Counter = Counter()
            for m in mixes:
                centroid.update(m)
            c.mix = {k: round(v / max(1, len(mixes)), 3) for k, v in centroid.most_common(8)}
            c.top_resources = res.most_common(6)
            c.top_templates = tpl.most_common(6)
            # outliers: far from the cohort centroid, far from their own history, or far busier than peers
            full = {k: v / max(1, len(mixes)) for k, v in centroid.items()}
            rates = [math.log1p(p.rate(idx, span)[0]) for p in ps]
            mu = sum(rates) / max(1, len(rates))
            sd = (sum((r - mu) ** 2 for r in rates) / max(1, len(rates))) ** 0.5 or 1.0
            outs = []
            for p, m, r in zip(ps, mixes, rates):
                d_c = tv(m, full) if len(ps) >= 3 else 0.0
                d_s = p.self_shift(idx, span)
                z = (r - mu) / sd if len(ps) >= 5 else 0.0
                score = max(d_c * 1.2, d_s, min(1.0, max(0.0, z) / 5))
                if score >= float(self.cfg["outlier_threshold"]) and p.rate(idx, span)[0] >= 3:
                    why = "unlike its cohort" if d_c * 1.2 == score else "changed its own pattern" if d_s == score \
                        else "far busier than its cohort"
                    outs.append((p.unit, round(min(1.0, score), 2), why))
            c.outliers = sorted(outs, key=lambda x: -x[1])[:8]

    # ------------------------------------------------------------ queries (structured, no raw text)
    def cohort_card(self, c: Cohort, detail: bool = False) -> dict[str, Any]:
        card = {"id": c.id, "label": c.label, "units": len(c.members), "events_now": c.events_now,
                "events_prev": c.events_prev, "change": f"{'+' if c.change >= 0 else ''}{(2 ** c.change - 1) * 100:.0f}%",
                "new": c.created_window >= self.window_index - int(self.cfg["recluster_every"]) and c.prev_size == 0,
                "size_change": len(c.members) - c.prev_size if c.prev_size else None,
                "mix": c.mix, "top_resources": [{"id": r, "label": self.label(r), "events": n} for r, n in c.top_resources[:4]],
                "top_templates": [{"id": t, "events": n, "units": len(self.miner.templates[t].units)}
                                  for t, n in c.top_templates[:4] if t in self.miner.templates],
                "outliers": [{"unit": u, "label": self.label(u), "score": s, "why": w} for u, s, w in c.outliers[:4]]}
        if detail:
            busiest = sorted(c.members, key=lambda u: -self.profiles[u].rate(self.window_index,
                                                                             int(self.cfg["span_windows"]))[0])
            card["members"] = [{"unit": u, "label": self.label(u)} for u in busiest[:24]]
            card["members_total"] = len(c.members)
        return card

    def unit_profile(self, unit: str) -> dict[str, Any] | None:
        p = self.profiles.get(unit)
        if not p:
            return None
        span = int(self.cfg["span_windows"])
        now, prev = p.rate(self.window_index, span)
        cid = self.unit_cohort.get(unit)
        c = self.cohorts.get(cid) if cid else None
        out = next((o for o in (c.outliers if c else []) if o[0] == unit), None)
        return {"unit": unit, "label": self.label(unit), "cohort": cid, "cohort_label": c.label if c else None,
                "events_total": p.n, "events_now": now, "events_prev": prev, "errors": p.errors,
                "families": dict(p.fam.most_common(5)), "actions": dict(p.act.most_common(5)),
                "resources": [{"id": r, "label": self.label(r), "events": n} for r, n in p.res.most_common(6)],
                "templates": dict(p.tpl.most_common(5)), "self_shift": round(p.self_shift(self.window_index, span), 2),
                "outlier": {"score": out[1], "why": out[2]} if out else None,
                "first": str(p.first)[:16], "last": str(p.last)[:16]}

    def template_rows(self, units: set[str] | None = None, limit: int = 15, sort: str = "spread") -> list[dict[str, Any]]:
        span = int(self.cfg["span_windows"])
        rows = []
        for t in self.miner.templates.values():
            if not t.count:
                continue
            us = t.units if units is None else Counter({u: n for u, n in t.units.items() if u in units})
            if units is not None and not us:
                continue
            now, prev = t.window_counts(self.window_index, span)
            rows.append({"id": t.id, "messages": t.count if units is None else sum(us.values()), "units": len(us),
                         "cohorts": len(t.cohorts), "now": now, "prev": prev,
                         "new": bool(t.first_ts and t.recent and t.recent[0][0] > self.window_index - span),
                         "first": str(t.first_ts)[:16], "last": str(t.last_ts)[:16], "examples": t.examples[:4]})
        key = {"spread": lambda r: (-r["units"], -r["now"]), "growth": lambda r: (-(r["now"] - r["prev"]), -r["units"]),
               "volume": lambda r: -r["messages"]}.get(sort, lambda r: -r["units"])
        return sorted(rows, key=key)[:limit]

    def population(self) -> dict[str, Any]:
        span = int(self.cfg["span_windows"])
        units = self.active_units()
        now = sum(n for i, n in self.history if self.window_index - span < i <= self.window_index)
        prev = sum(n for i, n in self.history if self.window_index - 2 * span < i <= self.window_index - span)
        outliers = sum(len(c.outliers) for c in self.cohorts.values())
        return {"unit": self.cfg["unit"], "units_seen": len(self.profiles), "units_active": len(units),
                "cohorts": len(self.cohorts), "events_total": self.events_total, "events_now": now, "events_prev": prev,
                "texts": self.texts_total, **self.miner.stats(), "outliers": outliers,
                "largest_cohort": max((len(c.members) for c in self.cohorts.values()), default=0)}

    def members_of(self, scope: str) -> list[str] | None:
        kind, _, ident = scope.partition(":")
        if kind == "cohort" and ident in self.cohorts:
            return list(self.cohorts[ident].members)
        return None
