"""Risk is a vector, not a score. A RiskPolicy maps it to an operational state.
Different deployments swap the policy: research and security ops should not page on the same evidence."""
from __future__ import annotations

from typing import Callable

from swarmscope.core.models import Observation, OperationalState, RiskVector

KIND_PROFILE: dict[str, dict[str, float]] = {
    # kind -> which risk dimensions it speaks to
    "convergence": {"coordination_evidence": 0.8, "scope": 0.5},
    "content_reuse": {"coordination_evidence": 0.8, "novelty": 0.4, "impact": 0.3},
    "rate_surge": {"scope": 0.7, "novelty": 0.4},
    "new_actors": {"scope": 0.5, "novelty": 0.6},
    "environment": {"external_capability": 0.6, "impact": 0.7},
    "human_intervention": {"impact": 0.2},
    "say_do_mismatch": {"impact": 0.9, "monitor_integrity_hit": 0.8},
    "focus_shift": {"novelty": 0.5},
    "alias": {"uncertainty": 0.6},
    "reasoning_cue": {"impact": 0.9, "monitor_integrity_hit": 0.8},   # what an agent thinks vs what it says and does
}


def risk_from(observations: list[Observation], population: int) -> RiskVector:
    r = RiskVector()
    for o in observations:
        prof = KIND_PROFILE.get(o.kind, {})
        s = o.severity
        units = o.metrics.get("units") or o.metrics.get("reusers") or len(o.metrics.get("affected") or []) or len(o.metrics.get("members") or []) or 1
        frac = 0.5 if o.kind == "rate_surge" else min(1.0, float(units) / max(population, 1))
        r = r.merge(RiskVector(
            impact=s * prof.get("impact", 0.3),
            scope=max(frac, s * prof.get("scope", 0.0)),
            coordination_evidence=s * prof.get("coordination_evidence", 0.0),
            external_capability=s * prof.get("external_capability", 0.0),
            novelty=s * prof.get("novelty", 0.2),
            evidence_strength=min(1.0, 0.2 + 0.08 * len(o.evidence)),
            monitor_integrity=1.0 - prof.get("monitor_integrity_hit", 0.0) * s,
            uncertainty=0.6 if o.metrics.get("chronological_only") else 0.4,
        ))
    return r


def research_default(r: RiskVector) -> OperationalState:
    """The strongest single concern dominates; breadth and novelty add to it; weak evidence discounts it."""
    concern = max(0.55 * r.coordination_evidence, 0.5 * r.impact, 0.45 * r.external_capability,
                  0.6 * (1 - r.monitor_integrity), 0.35 * r.novelty)
    score = (concern + 0.15 * r.scope + 0.1 * r.novelty) * (0.6 + 0.4 * r.evidence_strength)
    if score >= 0.42:
        return OperationalState.ALERT
    if score >= 0.22:
        return OperationalState.INVESTIGATE
    if score >= 0.07:
        return OperationalState.WATCH
    return OperationalState.NONE


def secops_strict(r: RiskVector) -> OperationalState:
    if r.external_capability >= 0.5 or (r.coordination_evidence >= 0.5 and r.scope >= 0.3):
        return OperationalState.PAGE
    if r.impact >= 0.35 or r.coordination_evidence >= 0.3:
        return OperationalState.ALERT
    if max(r.novelty, r.scope) >= 0.2:
        return OperationalState.INVESTIGATE
    return OperationalState.WATCH if r.evidence_strength > 0.2 else OperationalState.NONE


POLICIES: dict[str, Callable[[RiskVector], OperationalState]] = {
    "research_default": research_default, "secops_strict": secops_strict}

LEVEL_ORDER = [OperationalState.NONE, OperationalState.WATCH, OperationalState.INVESTIGATE,
               OperationalState.ALERT, OperationalState.PAGE]


def at_least(a: OperationalState, b: OperationalState) -> bool:
    return LEVEL_ORDER.index(a) >= LEVEL_ORDER.index(b)
