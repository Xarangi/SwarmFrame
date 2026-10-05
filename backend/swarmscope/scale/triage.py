"""The triage allocator: where the organization's limited reading goes each cycle.

Each cycle has a reading budget (how many scopes an analyst, auditor or specialist will look at closely).
It is split into three lanes:

  triage    the highest priority scopes: watcher severity, change, novelty, director focus
  coverage  the cohorts that have gone longest without a close look (coverage debt), so nothing is
            unvisited for long however quiet it seems
  audit     uniformly random units drawn with a secret seed that no data can influence, so a population that
            learns what triage looks for still cannot predict what will be read

Outcomes come back (`record`): a lane's hit rate is the share of its looks that found something notable. If random
audits find as much as triage does, triage is not discriminating, and the allocator reports that as a blind spot.
Every pick carries its reasons, so the triage policy itself can be audited.
"""
from __future__ import annotations

import math
import os
import random
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from swarmscope.scale.layer import ScaleLayer

DEFAULT_WEIGHTS = {"severity": 0.35, "change": 0.2, "novelty": 0.15, "debt": 0.2, "focus": 0.1}
DEFAULT_LANES = {"triage": 0.6, "coverage": 0.25, "audit": 0.15}


@dataclass
class TriageItem:
    scope: str
    kind: str                      # cohort | unit | template
    label: str
    priority: float
    lane: str
    components: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    cohort: str | None = None
    assigned_to: str | None = None
    units: list[str] = field(default_factory=list)      # the units this pick covers (for evaluation; not shown to models)


class Triage:
    def __init__(self, cfg: dict[str, Any] | None = None):
        cfg = cfg or {}
        r = cfg.get("reads_per_cycle", "auto")
        self.reads_auto = r in (None, "auto")
        self.reads = 10 if self.reads_auto else int(r)
        self.weights = {**DEFAULT_WEIGHTS, **(cfg.get("weights") or {})}
        self.lanes = {**DEFAULT_LANES, **(cfg.get("lanes") or {})}
        self.coverage_every = int(cfg.get("coverage_every_cycles", 4))
        self._seed = int.from_bytes(os.urandom(8), "big")          # secret: never derived from the data
        self.last_covered: dict[str, int] = {}                      # scope -> cycle
        self.outcomes: dict[str, Counter] = {k: Counter() for k in DEFAULT_LANES}
        self.items: list[TriageItem] = []
        self.ranked: list[TriageItem] = []
        self.cycle = 0
        self.focus: dict[str, float] = {}
        self.director_focus: dict[str, float] = {}

    # ------------------------------------------------------------ outcome tracking
    def record(self, scope: str, lane: str | None, status: str, cycle: int) -> None:
        self.last_covered[scope] = cycle
        if lane in self.outcomes:
            self.outcomes[lane]["looks"] += 1
            if status in ("notable", "concerning", "supported", "partially_supported"):
                self.outcomes[lane]["hits"] += 1

    def lane_of(self, scope: str) -> str | None:
        return next((i.lane for i in self.items if i.scope == scope), None)

    def hit_rates(self) -> dict[str, float | None]:
        return {k: (round(c["hits"] / c["looks"], 2) if c["looks"] else None) for k, c in self.outcomes.items()}

    def warnings(self) -> list[str]:
        hr, out = self.hit_rates(), []
        t, a = hr.get("triage"), hr.get("audit")
        if t is not None and a is not None and self.outcomes["audit"]["looks"] >= 4 and a >= max(0.2, t * 0.8):
            out.append(f"Random audits find something {a:.0%} of the time against {t:.0%} for triage: "
                       "triage is not separating interesting scopes from the rest.")
        return out

    # ------------------------------------------------------------ allocation
    def allocate(self, layer: "ScaleLayer", cycle: int, observations: list[dict[str, Any]],
                 focus: dict[str, float] | None = None) -> list[TriageItem]:
        self.cycle = cycle
        self.focus = dict(focus or {})
        obs_by_unit: dict[str, float] = {}
        obs_titles: dict[str, str] = {}
        for o in observations:
            ids = [o["scope"].split(":", 1)[-1]] + list(o.get("members") or [])
            for u in ids:
                if o["severity"] > obs_by_unit.get(u, 0):
                    obs_by_unit[u], obs_titles[u] = o["severity"], o["title"]
        cands: list[TriageItem] = []
        for c in layer.cohorts.values():
            scope = f"cohort:{c.id}"
            sev_u = max(((obs_by_unit.get(u, 0.0), u) for u in c.members), default=(0.0, None))
            sev = sev_u[0]
            change = min(1.0, abs(c.change) / 3) if c.events_now + c.events_prev >= 6 else 0.0
            new_tpl = sum(1 for t, _ in c.top_templates if t in layer.miner.templates
                          and layer.miner.templates[t].recent
                          and layer.miner.templates[t].recent[0][0] > layer.window_index - int(layer.cfg["span_windows"]))
            is_new = c.prev_size == 0 and c.created_window > 0
            novelty = min(1.0, 0.6 * is_new + 0.2 * new_tpl + 0.3 * min(1.0, len(c.outliers) / 4))
            debt = min(1.5, (cycle - self.last_covered.get(scope, -10 ** 3 if c.events_now else cycle)) / self.coverage_every)
            debt = max(0.0, debt)
            foc = max([w for s, w in self.focus.items() if s == scope or s in (f"agent:{u}" for u in c.members[:50])],
                      default=0.0)
            comp = {"severity": round(sev, 2), "change": round(change, 2), "novelty": round(novelty, 2),
                    "debt": round(min(1.0, debt), 2), "focus": round(foc, 2)}
            pr = sum(self.weights[k] * v for k, v in comp.items())
            reasons = []
            if sev >= 0.4:
                reasons.append(f"watcher: {obs_titles.get(sev_u[1], '')[:90]}")
            if change >= 0.3:
                reasons.append(f"activity {('+' if c.change > 0 else '')}{(2 ** c.change - 1) * 100:.0f}% "
                               f"({c.events_prev}→{c.events_now})")
            if is_new:
                reasons.append("new cohort")
            if new_tpl:
                reasons.append(f"{new_tpl} new message templates")
            if c.outliers:
                reasons.append(f"{len(c.outliers)} outlier units")
            if debt >= 1:
                reasons.append("not looked at recently" if scope in self.last_covered else "never looked at")
            if foc:
                reasons.append("director focus")
            cands.append(TriageItem(scope, "cohort", c.label, round(pr, 3), "", comp, reasons, c.id, units=list(c.members)))
            for u, score, why in c.outliers[:3]:
                us = layer.scope_of_unit(u)
                sev2 = obs_by_unit.get(u, 0.0)
                comp2 = {"severity": round(sev2, 2), "change": 0.0, "novelty": round(score, 2), "debt": 0.0,
                         "focus": round(self.focus.get(us, 0.0), 2)}
                pr2 = sum(self.weights[k] * v for k, v in comp2.items()) + 0.05
                cands.append(TriageItem(us, "unit", layer.label(u), round(pr2, 3), "", comp2,
                                        [f"outlier ({why}, {score:.2f})"] + ([obs_titles[u][:90]] if u in obs_titles else []),
                                        c.id, units=[u]))
        # watcher signals on specific agents or resources are candidates of their own: a few agents saying one
        # thing and doing another, or scattered agents converging on one host, are invisible at cohort level
        best: dict[str, dict[str, Any]] = {}
        for o in observations:
            kind = o["scope"].split(":", 1)[0]
            if kind not in ("agent", "actor", "resource") or o["severity"] < 0.4:
                continue
            if o["severity"] > best.get(o["scope"], {}).get("severity", 0):
                best[o["scope"]] = o
        for scope, o in best.items():
            ident = scope.split(":", 1)[1]
            units = list(o.get("members") or []) or ([ident] if ident in layer.profiles else [])
            seen = scope in self.last_covered
            comp4 = {"severity": round(o["severity"], 2), "change": 0.0, "novelty": 0.3 if seen else 1.0,
                     "debt": 0.0, "focus": round(self.focus.get(scope, 0.0), 2)}
            pr4 = sum(self.weights[k] * v for k, v in comp4.items()) + 0.05
            label = layer.label(ident) if layer.label(ident) != ident else ident
            cands.append(TriageItem(scope, "signal", label, round(pr4, 3), "", comp4,
                                    [f"watcher: {o['title'][:100]}"] + ([] if seen else ["not looked at yet"]),
                                    layer.unit_cohort.get(units[0]) if units else None, units=units))
        span = int(layer.cfg["span_windows"])
        for t in layer.template_rows(limit=6, sort="growth"):
            if t["units"] >= 3 and t["now"] > max(4, 2 * t["prev"]):
                spread = min(1.0, t["units"] / 20)
                comp3 = {"severity": 0.0, "change": round(min(1.0, math.log2((t["now"] + 1) / (t["prev"] + 1)) / 3), 2),
                         "novelty": round(spread, 2), "debt": 0.0, "focus": round(self.focus.get(f"template:{t['id']}", 0.0), 2)}
                pr3 = sum(self.weights[k] * v for k, v in comp3.items()) + 0.05
                cands.append(TriageItem(f"template:{t['id']}", "template", f"message template {t['id']}", round(pr3, 3),
                                        "", comp3, [f"spreading: {t['now']} messages from {t['units']} units in "
                                                    f"the last {span} windows (was {t['prev']})"],
                                        units=list(layer.miner.templates[t["id"]].units)[:200]))
        dedup: dict[str, TriageItem] = {}
        for i in cands:
            if i.scope not in dedup or i.priority > dedup[i.scope].priority:
                dedup[i.scope] = i
        cands = sorted(dedup.values(), key=lambda i: -i.priority)
        self.ranked = cands
        if self.reads_auto:       # attention grows with the number of cohorts (square root), not with units
            self.reads = max(8, min(60, round(4 * math.sqrt(max(1, len(layer.cohorts))))))
        n = max(1, self.reads)
        n_tri = max(1, round(n * self.lanes["triage"]))
        n_cov = max(1, round(n * self.lanes["coverage"])) if n > 2 else 0
        n_aud = max(0, n - n_tri - n_cov)
        picked: list[TriageItem] = []
        taken: set[str] = set()
        for i in cands:
            if len(picked) >= n_tri:
                break
            if i.priority > 0.08:
                i.lane = "triage"
                picked.append(i)
                taken.add(i.scope)
        cov = sorted([i for i in cands if i.kind == "cohort" and i.scope not in taken],
                     key=lambda i: (-i.components["debt"], -i.priority))
        for i in cov[:n_cov]:
            i.lane = "coverage"
            picked.append(i)
            taken.add(i.scope)
        rng = random.Random(self._seed ^ (cycle * 0x9E3779B97F4A7C15))
        pool = sorted(u for u in layer.unit_cohort if layer.scope_of_unit(u) not in taken)
        for u in rng.sample(pool, min(n_aud, len(pool))):
            picked.append(TriageItem(layer.scope_of_unit(u), "unit", layer.label(u), 0.0, "audit",
                                     {}, ["random audit"], layer.unit_cohort.get(u), units=[u]))
        self.items = picked
        return picked

    def to_dict(self) -> dict[str, Any]:
        lanes = Counter(i.lane for i in self.items)
        return {"cycle": self.cycle, "reads_per_cycle": self.reads, "reads_auto": self.reads_auto, "weights": self.weights, "lanes": self.lanes,
                "coverage_every_cycles": self.coverage_every, "picked": dict(lanes),
                "items": [_public(i) for i in self.items],
                "next_in_line": [_public(i) for i in self.ranked if i.scope not in {x.scope for x in self.items}][:8],
                "hit_rates": self.hit_rates(), "outcomes": {k: dict(v) for k, v in self.outcomes.items()},
                "warnings": self.warnings()}

    def configure(self, reads: int | None = None, weights: dict[str, float] | None = None,
                  lanes: dict[str, float] | None = None, coverage_every: int | None = None) -> None:
        if reads == "auto":
            self.reads_auto = True
        elif reads is not None:
            self.reads_auto = False
            self.reads = max(1, min(200, int(reads)))
        for k, v in (weights or {}).items():
            if k in self.weights:
                self.weights[k] = max(0.0, float(v))
        if lanes:
            new = {**self.lanes, **{k: max(0.0, float(v)) for k, v in lanes.items() if k in self.lanes}}
            s = sum(new.values()) or 1
            self.lanes = {k: v / s for k, v in new.items()}
            if self.lanes["audit"] < 0.1:          # the random slice is a floor, not an option
                self.lanes["audit"] = 0.1
                rest = sum(v for k, v in self.lanes.items() if k != "audit") or 1
                self.lanes.update({k: v * 0.9 / rest for k, v in self.lanes.items() if k != "audit"})
        if coverage_every is not None:
            self.coverage_every = max(1, int(coverage_every))


def _public(i: TriageItem) -> dict[str, Any]:
    d = asdict(i)
    d["n_units"] = len(d.pop("units"))
    return d
