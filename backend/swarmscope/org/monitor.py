"""Monitors: a manifest plus five strategy slots. Composition, not inheritance.

A monitor owns a set of watchers (deterministic, every window) and turns their
observations into a MonitorReport: claims with epistemic status, questions, a
risk vector and an escalation level. Which strategy fills each slot comes from
the manifest, overridden by the pack defaults, the org config and the UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from swarmscope.core.models import CapabilityProfile, MonitorReport, Observation
from swarmscope.strategies.base import MonitorContext
from swarmscope.strategies.slots import SLOTS, maybe_await

MANIFEST_DIR = Path(__file__).parent / "monitors"
SLOT_ORDER = ["retrieval", "summarization", "evaluation", "escalation", "critique"]


@dataclass
class MonitorManifest:
    id: str
    title: str
    description: str
    requires: list[str]
    optional: list[str]
    watchers: list[str]
    slots: dict[str, str]
    params: dict[str, Any] = field(default_factory=dict)
    tunables: dict[str, list[float]] = field(default_factory=dict)
    outputs: list[str] = field(default_factory=list)

    def satisfiable(self, profile: CapabilityProfile) -> tuple[bool, list[str]]:
        missing = [r for r in self.requires if not profile.has(r)]
        return not missing, missing


def load_manifests() -> dict[str, MonitorManifest]:
    out = {}
    for p in sorted(MANIFEST_DIR.glob("*.yaml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        out[d["id"]] = MonitorManifest(**{k: d.get(k, v) for k, v in {
            "id": None, "title": None, "description": "", "requires": [], "optional": [], "watchers": [],
            "slots": {}, "params": {}, "tunables": {}, "outputs": []}.items()})
    return out


class Monitor:
    def __init__(self, manifest: MonitorManifest, slots: dict[str, str], params: dict[str, Any]):
        self.manifest = manifest
        self.slots = {s: slots.get(s, manifest.slots.get(s)) for s in SLOT_ORDER}
        for s, name in self.slots.items():
            if name not in SLOTS[s]:
                raise ValueError(f"monitor {manifest.id}: unknown {s} strategy {name!r}")
        self.params = {**manifest.params, **params}
        self.rolling_summary = ""
        self.reports = 0
        self.spent_usd = 0.0
        self.tokens = 0
        self.last_level = "NONE"

    @property
    def id(self) -> str:
        return self.manifest.id

    async def run(self, ctx: MonitorContext, observations: list[Observation]) -> tuple[MonitorReport, list, list]:
        ctx.prior_summary = self.rolling_summary
        ctx.params = self.params
        sl = await maybe_await(SLOTS["retrieval"][self.slots["retrieval"]](ctx, observations))
        summary = await SLOTS["summarization"][self.slots["summarization"]](ctx, sl)
        evaluation = await SLOTS["evaluation"][self.slots["evaluation"]](ctx, sl, summary)
        decision = await maybe_await(SLOTS["escalation"][self.slots["escalation"]](ctx, sl, evaluation))
        critique = await SLOTS["critique"][self.slots["critique"]](ctx, sl, evaluation)
        self.rolling_summary = summary.text
        claims = evaluation.claims + critique
        cost = summary.cost_usd + evaluation.cost_usd
        tokens = summary.tokens + evaluation.tokens
        self.spent_usd += cost
        self.tokens += tokens
        self.reports += 1
        self.last_level = decision.level.value
        top = max(observations, key=lambda o: o.severity)
        report = MonitorReport(
            monitor=self.id, window_end=ctx.window.end, scope=top.scope, headline=evaluation.headline,
            observations=[o.id for o in observations], claims=[c.id for c in claims],
            questions=[q.id for q in evaluation.questions], risk=decision.risk, escalation=decision.level,
            summary=summary.text + (f" ({decision.reason})" if decision.reason else ""), strategies=dict(self.slots),
            cost_usd=cost, tokens=tokens, disagreement=evaluation.disagreement)
        return report, claims, evaluation.questions
