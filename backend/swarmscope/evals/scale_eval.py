"""Scale evaluation: does the organization find planted behaviours in a large swarm, and does its attention stay
bounded as the population grows?

Per planted incident (units = the agents involved):
  watcher     first watcher observation touching at least `k` of the units
  triaged     first triage pick (any lane) covering the units (a cohort that is >= 25% planted units, a planted
              unit, or a template whose writers are planted)
  surfaced    first close look at such a pick that came back notable or concerning
  lane        which lane first surfaced it (triage, coverage, audit)
Overall:
  director_input_chars   size of the director's input in its last cycle (should stay flat as N grows)
  share_looked_at        mean share of recent activity in cohorts that got a close look
  audit / triage hit rates, agents, seconds per window
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from swarmscope.engine import Engine


def _covers(item, units: set[str]) -> bool:
    us = set(item.units)
    if not us:
        return False
    hit = len(us & units)
    if item.kind == "cohort":
        return hit >= max(2, 0.25 * len(us))
    if item.kind == "template":
        return hit >= max(2, 0.5 * len(us))
    return hit > 0


def _mins(a: datetime | None, b: datetime) -> float | None:
    return round((a - b).total_seconds() / 60, 1) if a else None


async def evaluate_scale(agents: int = 2000, hours: float = 36, org: str = "default", topology: str = "triage_tree",
                         seed: int = 7, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    from swarmscope.agents.runners import user_prompt
    from swarmscope.agents.runtime import RunContext
    t0 = time.time()
    eng = Engine("swarm_scale", org, slice_override={"agents": agents, "hours": hours, "seed": seed},
                 overrides={"agents.topology": topology, "investigations.node_delay_s": 0, "agents.stub_delay_s": 0,
                            **(overrides or {})})
    load_s = time.time() - t0
    t1 = time.time()
    await eng.run_to_end()
    run_s = time.time() - t1
    org_ = eng.agent_org
    obs = eng.store.all("Observation")
    rows = []
    for gt in eng.ground_truth:
        at = datetime.fromisoformat(gt["ts"][:19])
        units = set(gt["units"])
        k = min(3, len(units))
        w = sorted([o for o in obs if o.window_end >= at and (
            len(units & set(o.metrics.get("members_ids") or [])) >= k or o.scope.split(":", 1)[-1] in units
            or o.scope == gt["scope"])], key=lambda o: o.window_end)
        picks = [(log["ts"], it) for log in org_.triage_log if log["ts"] >= at for it in log["items"] if _covers(it, units)]
        by_scope = {}
        for log in org_.triage_log:
            for it in log["items"]:
                if _covers(it, units):
                    by_scope.setdefault((log["cycle"], it.scope), it)
        surfaced = sorted([x for x in org_.lookups if x["ts"] >= at and x["status"] in ("notable", "concerning")
                           and (x["cycle"], x["scope"]) in by_scope], key=lambda x: x["ts"])
        first_pick = picks[0] if picks else None
        rows.append({"incident": gt["id"], "kind": gt["kind"], "units": len(units),
                     "minutes_to_watcher": _mins(w[0].window_end if w else None, at),
                     "minutes_to_triage": _mins(first_pick[0] if first_pick else None, at),
                     "triage_lane": first_pick[1].lane if first_pick else None,
                     "minutes_to_surfaced": _mins(surfaced[0]["ts"] if surfaced else None, at),
                     "surfaced_by": surfaced[0]["role"] if surfaced else None,
                     "surfaced_lane": surfaced[0]["lane"] if surfaced else None,
                     "looks": len({(x["cycle"], x["scope"]) for x in surfaced})})
    root = org_.nodes.get(org_.root_id) if org_.root_id else None
    prompt_chars = None
    if root is not None:
        ctx = RunContext(org_, root, org_.topology.roles[root.role], "cycle", eng.tools("investigator"))
        ctx.x = org_.current_x
        prompt_chars = len(user_prompt(ctx)) if ctx.x is not None else None
    cov = [c["share_of_activity_looked_at_now"] for c in org_.coverage_log if c.get("share_of_activity_looked_at_now") is not None]
    n = len(rows) or 1
    return {"agents": agents, "hours": hours, "events": eng.store.count_events(), "windows": eng.windows_processed,
            "cycles": org_.cycle_index, "cohorts": len(eng.scale.cohorts), "divisions": len(org_.divisions),
            "sectors": len(org_.sectors), "org_agents": len(org_.active()),
            "templates": eng.scale.population()["templates"], "compression": eng.scale.population()["compression"],
            "recall_watcher": round(sum(r["minutes_to_watcher"] is not None for r in rows) / n, 2),
            "recall_triage": round(sum(r["minutes_to_triage"] is not None for r in rows) / n, 2),
            "recall_surfaced": round(sum(r["minutes_to_surfaced"] is not None for r in rows) / n, 2),
            "director_input_chars": prompt_chars,
            "mean_share_looked_at": round(sum(cov) / len(cov), 3) if cov else None,
            "hit_rates": eng.triage.hit_rates(), "load_seconds": round(load_s, 1),
            "seconds_per_window": round(run_s / max(1, eng.windows_processed), 2), "incidents": rows,
            "errors": eng.router.errors[-3:]}
