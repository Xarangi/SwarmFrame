"""Evaluation harness: score monitoring organizations against planted ground truth.

Baselines are org configs (orgs/baseline_*.yaml), so every comparison runs the same code
path with different strategies. Metrics per org:
  recall, time to first signal, explained (an investigation concluded on the incident),
  time to explanation, exposure correctness (propagation), unsupported-claim rate,
  false incidents, LLM calls / tokens / cost, fraction of evidence inspected.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from swarmscope.core.models import ClaimStatus
from swarmscope.engine import Engine

KIND_MATCH = {"convergence": {"convergence"}, "propagation": {"content_reuse"}, "integrity": {"say_do_mismatch"},
              "environment": {"environment"}, "rate": {"rate_surge"}, "goals": {"focus_shift"}}


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s[:19])


def _match(gt: dict[str, Any], obs, eng: Engine) -> bool:
    if obs.kind not in KIND_MATCH.get(gt["kind"], set()):
        return False
    scope = gt["scope"]
    if gt["kind"] == "propagation":
        room = scope.split(":", 1)[1]
        return room in (eng.label(obs.metrics.get("origin_resource")) or "")
    if gt["kind"] == "rate":
        return True
    return obs.scope.endswith(scope.split(":", 1)[1]) if ":" in scope else obs.scope == scope


async def evaluate(org: str, source: str = "ai_village", path: str = "synthetic",
                   overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    t0 = time.time()
    eng = Engine(source, org, path=path, overrides={"investigations.node_delay_s": 0, **(overrides or {})})
    if not eng.ground_truth:
        raise RuntimeError("source has no ground truth; evaluation runs on the synthetic corpus")
    await eng.run_to_end()
    obs = eng.store.all("Observation")
    reports = {r.id: r for r in eng.store.all("MonitorReport")}
    invs = eng.store.all("Investigation")
    claims = eng.store.all("Claim")
    briefing = " ".join(b.text for b in eng.store.all("BriefingEntry")).lower()
    rows, signal_mins, explain_mins = [], [], []
    detected = explained = 0
    exposure_ok = None
    for gt in eng.ground_truth:
        at = _ts(gt["ts"])
        hits = sorted([o for o in obs if _match(gt, o, eng) and o.window_end >= at], key=lambda o: o.window_end)
        first = hits[0] if hits else None
        reported = any(set(r.observations) & {o.id for o in hits} for r in reports.values())
        inv = next((i for i in invs if i.status == "concluded" and first and i.scope in {o.scope for o in hits}), None)
        if first:
            detected += 1
            signal_mins.append((first.window_end - at).total_seconds() / 60)
        if inv and inv.concluded:
            explained += 1
            explain_mins.append((inv.concluded - at).total_seconds() / 60)
        if gt["kind"] == "propagation" and hits:
            last = hits[-1].metrics
            exposure_ok = (sorted(last.get("exposed", [])) == sorted(gt.get("exposed", [])) and
                           sorted(last.get("chronological_only", [])) == sorted(gt.get("chronological_only", [])))
        rows.append({"incident": gt["id"], "kind": gt["kind"], "detected": bool(first), "reported": reported,
                     "minutes_to_signal": round(signal_mins[-1], 1) if first else None,
                     "explained": bool(inv), "conclusion": inv.conclusion if inv else None,
                     "mentioned_in_briefing": any(w.lower() in briefing for w in gt["detail"].split()[:1])})
    gt_scopes = {g["scope"].split(":", 1)[-1] for g in eng.ground_truth}
    incidents = eng.exec_state.active_incidents
    false_inc = [i for i in incidents if not any(s in i.scope for s in gt_scopes) and "population" not in i.scope]
    unsupported = [c for c in claims if c.status in (ClaimStatus.INFERRED,) and not c.support]
    recs = eng.store.all("AttentionRecord")
    llm_calls = sum(r.calls for r in recs if r.backend != "stub")
    n = len(eng.ground_truth)
    return {
        "org": org, "name": eng.org.get("name", org), "llm_mode": eng.router.mode,
        "recall": round(detected / n, 2), "explained": round(explained / n, 2),
        "median_minutes_to_signal": _median(signal_mins), "median_minutes_to_explanation": _median(explain_mins),
        "exposure_correct": exposure_ok, "claims": len(claims),
        "unsupported_inference_rate": round(len(unsupported) / max(1, len(claims)), 3),
        "false_incidents": len(false_inc), "incidents": len(incidents), "investigations": len(invs),
        "llm_calls": llm_calls, "tokens": sum(r.tokens_in + r.tokens_out for r in recs),
        "cost_usd": round(sum(r.cost_usd for r in recs), 4), "coverage": eng.monitor_health()["coverage"],
        "briefing_entries": len(eng.store.all("BriefingEntry")), "seconds": round(time.time() - t0, 1),
        "incidents_detail": rows,
    }


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    m = len(s) // 2
    return round(s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2, 1)


async def compare(orgs: list[str], source: str = "ai_village", path: str = "synthetic") -> dict[str, Any]:
    results = []
    for o in orgs:
        try:
            results.append(await evaluate(o, source, path))
        except Exception as exc:
            results.append({"org": o, "error": f"{type(exc).__name__}: {exc}"})
    return {"source": source, "path": path, "results": results}
