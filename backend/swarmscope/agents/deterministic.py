"""Deterministic behaviours per role kind: the free baseline for every role, and the fallback when a model
call fails or the budget runs out. Each returns data in the role's output schema."""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from swarmscope.core.models import ClaimStatus, Question

if TYPE_CHECKING:
    from swarmscope.agents.runtime import RunContext
    from swarmscope.core.models import ExecutiveStep

KIND_OF_OBS = {"convergence": "convergence", "content_reuse": "propagation", "say_do_mismatch": "integrity",
               "environment": "environment", "focus_shift": "goals", "rate_surge": "surge", "new_actors": "surge"}
SPECIALIST_FOR = {"say_do_mismatch": "integrity", "content_reuse": "propagation", "convergence": "timeline",
                  "environment": "response"}


def _c(statement: str, status: str, ids: list[str], conf: float = 0.8) -> dict[str, Any]:
    return {"statement": statement, "status": status, "evidence_ids": [i for i in ids if i][:12], "confidence": conf}


# ------------------------------------------------------------------ director

def director_stub(ctx: "RunContext", det: "ExecutiveStep") -> dict[str, Any]:
    """Executive state comes from the deterministic executive; the org decisions are rule-based."""
    org, actions = ctx.org, []
    roles = org.topology.roles
    me = roles[ctx.node.role]
    specialist_roles = {r.kind: rid for rid, r in roles.items() if rid in me.can_spawn or any(
        rid in roles[c].can_spawn for c in me.can_spawn)}
    for n in org.active():
        rep = n.last_report or {}
        rec = rep.get("recommend") or {}
        if n.id == org.root_id or n.last_run != org.engine.now():
            continue
        if rec.get("split") and n.scope.startswith("division:"):
            actions.append({"action": "split", "scope": n.scope, "brief": rec.get("reason", "division too broad")})
        want = rec.get("specialist")
        rid = specialist_roles.get(want) or specialist_roles.get("specialist") if want else None
        if rid:
            already = any(c in org.nodes and org.nodes[c].role == rid and org.nodes[c].status != "retired"
                          for c in n.children)
            if not already:
                focus = next((f for f in rep.get("flags", []) if f.get("priority") in ("high", "critical")), None)
                actions.append({"action": "spawn_child", "parent": n.id, "role": rid,
                                "scope": (focus or {}).get("scope") or n.scope,
                                "brief": f"[{want}] " + ((focus or {}).get("text") or f"Look into {n.last_headline}")})
    tri = org.engine.triage
    if tri.warnings() and tri.lanes.get("audit", 0) < 0.3:
        actions.append({"action": "set_triage", "triage": {"lanes": {"audit": tri.lanes["audit"] + 0.1}},
                        "brief": "random audits find as much as triage; widen the random slice"})
    hot = [n.scope for n in org.active() if n.id != org.root_id and n.last_status == "concerning"
           and n.last_run == org.engine.now() and n.scope.startswith(("division:", "cohort:", "agent:", "resource:"))]
    if hot:
        actions.append({"action": "set_triage", "triage": {"focus": hot[:6]}, "brief": "focus next cycle on concerning scopes"})
    return {"headline": det.state.population_state, "population_state": det.state.population_state,
            "org_rationale": f"{len(actions)} structural changes from analyst recommendations",
            "org_actions": [a for a in actions if a["action"] != "spawn_child"],
            "_child_spawns": [a for a in actions if a["action"] == "spawn_child"]}


# ------------------------------------------------------------------ division analyst

def analyst(ctx: "RunContext") -> dict[str, Any]:
    org, t = ctx.org, ctx.tools
    span = org.engine.window_len * int(org.engine.org.get("executive", {}).get("cadence_windows", 6)) * 2
    since = (org.engine.now() - span).isoformat(sep=" ")
    rows = t.query_events(since=since, limit=200)
    fam = Counter(r["family"] for r in rows)
    act = Counter(r["actor"] for r in rows)
    res = Counter(r["object"] for r in rows if r["object"])
    obs = [o for o in t.observations(limit=30) if o["ts"] >= since[:16]]
    claims, flags = [], []
    noun = org.engine.profile.entity_noun
    rnoun = getattr(org.engine.profile, "resource_noun", "resource") or "resource"
    ident = org.engine.profile.has("identities")
    who = (lambda n: f"by {n} {noun}{'s' if n != 1 else ''}") if ident else (lambda n: "")  # noqa: E731
    if rows:
        top_f = ", ".join(f"{f} ({n})" for f, n in fam.most_common(3))
        claims.append(_c(f"{len(rows)} {'events' if ident else noun + 's'} {who(len(act))} in the last {span.total_seconds() / 3600:.0f} h; "
                         f"mostly {top_f}.", "DERIVED", [r["id"] for r in rows[-8:]], 0.9))
        if res:
            r0, n0 = res.most_common(1)[0]
            claims.append(_c(f"Most-used {rnoun}: {r0} ({n0} events).", "DERIVED",
                             [r["id"] for r in rows if r["object"] == r0][-6:], 0.85))
    for o in sorted(obs, key=lambda o: -o["severity"])[:4]:
        if o["evidence"]:
            claims.append(_c(o["title"] + ".", "OBSERVED", o["evidence"], 0.85))
        if o["severity"] >= 0.5 and o["kind"] in KIND_OF_OBS:
            flags.append({"kind": KIND_OF_OBS[o["kind"]], "scope": o["scope"], "text": o["title"],
                          "priority": "high" if o["severity"] >= 0.65 else "medium"})
    top_obs = max(obs, key=lambda o: o["severity"]) if obs else None
    status = "quiet" if len(rows) < 3 else "concerning" if top_obs and top_obs["severity"] >= 0.65 else \
        "notable" if obs else "normal"
    div = org.divisions.get(ctx.node.scope.partition(":")[2])
    split_over = org.topology.maintain.get("split_when_events_over") or 10 ** 9
    split = bool(div and len(div.agents) >= 6 and div.events > 0.6 * int(split_over))
    specialist = SPECIALIST_FOR.get(next((k for k in ("say_do_mismatch", "content_reuse", "environment", "convergence")
                                          if any(o["kind"] == k and o["severity"] >= 0.5 for o in obs)), ""), None)
    headline = (top_obs["title"] if top_obs else
                (f"{len(rows)} events, {len(act)} {noun}s active" if ident else f"{len(rows)} {noun}s")
                if rows else "No activity in scope")
    prev = ctx.node.notes
    looked, blind = work_plan(ctx, obs)
    if any(x["status"] == "concerning" for x in looked) and status != "concerning":
        status = "concerning"
        headline = next(x["finding"] for x in looked if x["status"] == "concerning")
    elif any(x["status"] == "notable" for x in looked) and status in ("quiet", "normal"):
        status = "notable"
        headline = next(x["finding"] for x in looked if x["status"] == "notable")
    return {"headline": headline, "status": status, "looked_at": looked, "blind_spots": blind,
            "cohort_labels": cohort_labels(ctx),
            "summary": f"{len(rows)} events {who(len(act))}. Workstreams: {dict(fam.most_common(4))}. "
                       f"{len(obs)} watcher observations in scope." + (f" Previously: {prev[:160]}" if prev else ""),
            "claims": claims, "flags": flags,
            "recommend": {"split": split, "retire": False, "specialist": specialist,
                          "reason": "division is large and busy" if split else ""},
            "notes_for_next_time": f"cycle {org.cycle_index}: {len(rows)} events, status {status}; {headline[:120]}"}


def _plan(ctx: "RunContext") -> list[Any]:
    return list(ctx.org.assignments.get(ctx.node.id) or [])


def look(ctx: "RunContext", item: Any, obs: list[dict[str, Any]]) -> dict[str, Any]:
    """Close look at one triage pick, deterministically: a cohort, a unit or a template."""
    t, lay = ctx.tools, ctx.org.engine.scale
    kind, _, ident = item.scope.partition(":")
    eng = ctx.org.engine
    span = eng.window_len * int(lay.cfg["span_windows"])
    obs = obs + [{"scope": o.scope, "severity": o.severity, "title": o.title}      # signals on this exact scope
                 for o in eng.store.all("Observation")
                 if o.scope == item.scope and eng.now() - span < o.window_end <= eng.now()]
    try:
        if kind == "cohort":
            c = t.cohort(ident) or {}
            moved = c.get("events_now", 0) + c.get("events_prev", 0) >= 10 and \
                abs(lay.cohorts[ident].change if ident in lay.cohorts else 0) >= 1
            outs = c.get("outliers") or []
            members = {m["unit"] for m in c.get("members", [])}
            hot = [o for o in obs if o["severity"] >= 0.5 and (o["scope"].split(":", 1)[-1] in members)]
            status = "concerning" if hot and (moved or outs) else "notable" if hot or moved or len(outs) >= 2 else \
                "nothing_notable"
            bits = [f"{c.get('units', 0)} units, {c.get('events_prev', 0)}→{c.get('events_now', 0)} events ({c.get('change')})"]
            if outs:
                bits.append(f"outliers {', '.join(o['label'] for o in outs[:2])}")
            if hot:
                bits.append(hot[0]["title"])
            return {"scope": item.scope, "status": status, "finding": f"Cohort {c.get('label', ident)}: " + "; ".join(bits)}
        if kind == "resource" and lay.cfg["unit"] == "actor":
            nb = t.neighborhood(ident, hours=6)
            actors = nb.get("actors", [])
            hot = [x for x in obs if x["scope"] == item.scope]
            sev = max([x["severity"] for x in hot], default=0.0)
            status = "concerning" if sev >= 0.65 and len(actors) >= 5 else "notable" if sev >= 0.45 or len(actors) >= 5 \
                else "nothing_notable"
            return {"scope": item.scope, "status": status,
                    "finding": f"{lay.label(ident)}: {len(actors)} agents acted on it in the last 6 h"
                               + (f"; {hot[-1]['title']}" if hot else "")}
        if kind in ("agent", "resource"):
            p = t.unit_profile(ident) or {}
            o = p.get("outlier") or {}
            hot = [x for x in obs if x["severity"] >= 0.5 and x["scope"].split(":", 1)[-1] == ident]
            status = "concerning" if hot and o.get("score", 0) >= 0.6 else \
                "notable" if hot or o.get("score", 0) >= 0.6 or p.get("self_shift", 0) >= 0.5 else "nothing_notable"
            why = o.get("why") or (hot[0]["title"] if hot else "in line with its cohort")
            return {"scope": item.scope, "status": status,
                    "finding": f"{p.get('label', ident)} ({p.get('cohort_label') or 'no cohort'}): {p.get('events_now', 0)} "
                               f"events recently (was {p.get('events_prev', 0)}); {why}"}
        if kind == "template":
            rows = [r for r in t.templates(sort="growth", limit=40) if r["id"] == ident]
            r = rows[0] if rows else {}
            status = "notable" if r.get("units", 0) >= 3 and r.get("cohorts", 0) >= 2 else "nothing_notable"
            return {"scope": item.scope, "status": status,
                    "finding": f"Template {ident}: {r.get('now', 0)} recent messages from {r.get('units', 0)} units in "
                               f"{r.get('cohorts', 0)} cohorts (was {r.get('prev', 0)})"}
    except Exception as exc:                                    # out of scope or unknown id
        return {"scope": item.scope, "status": "nothing_notable", "finding": f"could not examine: {exc}"}
    return {"scope": item.scope, "status": "nothing_notable", "finding": "unsupported scope"}


def cohort_labels(ctx: "RunContext") -> list[dict[str, Any]]:
    """Models off: label each of the division's cohorts from its behaviour signature (derived, not inferred)."""
    div = ctx.org.divisions.get(ctx.node.scope.partition(":")[2])
    return label_cohorts(ctx.org.engine, (div.cohorts if div else [])[:12])


def label_cohorts(engine: Any, cids: list[str]) -> list[dict[str, Any]]:
    """What each cohort is doing, from its behaviour signature: its main kind of work and busiest place."""
    lay = engine.scale
    out = []
    for cid in cids:
        c = lay.cohorts.get(cid)
        if not c:
            continue
        fam = next((k[2:] for k, _ in sorted(c.mix.items(), key=lambda kv: -kv[1]) if k.startswith("f:")), None)
        where = engine.label(c.top_resources[0][0]) if c.top_resources else None
        task = f"mostly {fam} work" + (f", busiest on {where}" if where else "") if fam else c.label
        state = "idle" if not c.events_now else "talking" if fam == "chat" else "working"
        out.append({"cohort": cid, "task": task, "state": state, "confidence": 0.9})
    return out


def work_plan(ctx: "RunContext", obs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    plan = _plan(ctx)
    looked = [look(ctx, it, obs) for it in plan]
    blind = []
    div = ctx.org.divisions.get(ctx.node.scope.partition(":")[2])
    if div and div.cohorts:
        tri = ctx.org.engine.triage
        stale = [c for c in div.cohorts if f"cohort:{c}" not in {i.scope for i in plan}
                 and tri.last_covered.get(f"cohort:{c}", -99) <= ctx.org.cycle_index - tri.coverage_every]
        if stale:
            blind.append(f"{len(stale)} of {len(div.cohorts)} cohorts in this division had no close look this cycle "
                         f"or in the last {tri.coverage_every}")
    if ctx.org.engine.profile.has("artifacts"):
        blind.append("agent-written text not read; judged from structure and templates")
    return looked, blind


def sector_lead(ctx: "RunContext") -> dict[str, Any]:
    """Merge the sector's division reports: rank by status, keep the strongest claims, union blind spots."""
    org = ctx.org
    rank = {"concerning": 3, "notable": 2, "normal": 1, "quiet": 0}
    kids = [org.nodes[c] for c in ctx.node.children if c in org.nodes and org.nodes[c].status != "retired"
            and org.nodes[c].last_report]
    kids.sort(key=lambda n: -rank.get(n.last_status, 0))
    claims, flags, blind, looked = [], [], [], []
    for n in kids:
        r = n.last_report or {}
        for cid in r.get("claim_ids", [])[:2]:
            c = org.engine.store.get("Claim", cid)
            if c and c.status.value in ("OBSERVED", "DERIVED"):
                claims.append(_c(f"{org.scope_label(n.scope)}: {c.statement}", c.status.value,
                                 [e.id for e in c.support if e.kind == "event"], c.confidence))
        flags += [f for f in r.get("flags", []) if f.get("priority") in ("high", "critical")][:2]
        blind += [f"{org.scope_label(n.scope)}: {b}" for b in r.get("blind_spots", [])[:2]]
        looked += r.get("looked_at", [])[:3]
    sec = org.sectors.get(ctx.node.scope.partition(":")[2], {})
    silent = [d for d in sec.get("divisions", []) if not any(n.scope == f"division:{d}" for n in kids)]
    if silent:
        blind.append(f"{len(silent)} divisions in this sector did not report")
    top = kids[0] if kids else None
    status = top.last_status if top else "quiet"
    worrying = [n for n in kids if n.last_status in ("notable", "concerning")]
    headline = (f"{org.scope_label(top.scope)}: {top.last_headline}" if top and status in ("notable", "concerning")
                else f"{len(kids)} divisions reported; nothing notable")
    return {"headline": headline[:300], "status": status if status in rank else "normal",
            "summary": f"{len(kids)} division reports; {len(worrying)} notable or concerning: "
                       + "; ".join(f"{org.scope_label(n.scope)} ({n.last_status})" for n in worrying[:4]),
            "claims": claims[:6], "flags": flags[:4], "looked_at": looked[:8], "blind_spots": blind[:6],
            "recommend": {"split": False, "retire": False, "specialist": None, "reason": ""},
            "notes_for_next_time": f"cycle {org.cycle_index}: {headline[:140]}"}


def auditor(ctx: "RunContext") -> dict[str, Any]:
    """Read the random sample; say how many were notable and whether triage would have found them."""
    org = ctx.org
    plan = [i for i in _plan(ctx) if i.lane == "audit"]
    span = org.engine.window_len * int(org.engine.scale.cfg["span_windows"])
    now = org.engine.now()
    obs = [{"scope": o.scope, "severity": o.severity, "title": o.title}
           for o in org.engine.store.all("Observation") if now - span < o.window_end <= now]
    picked_cohorts = {i.cohort for i in org.engine.triage.items if i.lane != "audit"}
    looked, claims, missed = [], [], 0
    for it in plan:
        x = look(ctx, it, obs)
        if x["status"] != "nothing_notable" and it.cohort not in picked_cohorts:
            missed += 1
            x["finding"] += " (its cohort was not in triage this cycle)"
        looked.append(x)
        uid = it.scope.split(":", 1)[1]
        rows = ctx.tools.query_events(actor=uid if it.scope.startswith("agent:") else None,
                                      object=uid if it.scope.startswith("resource:") else None, limit=6)
        if rows:
            claims.append(_c(f"{it.label}: {len(rows)} recent events reviewed; {x['status'].replace('_', ' ')}.",
                             "DERIVED", [r["id"] for r in rows], 0.8))
    notable = sum(1 for x in looked if x["status"] != "nothing_notable")
    headline = (f"Audited {len(looked)} random units; {notable} of {len(looked)} notable"
                + (f", {missed} outside this cycle's triage" if missed else ""))
    status = "notable" if missed else "normal" if looked else "quiet"
    return {"headline": headline, "status": status, "summary": headline + ".", "claims": claims, "looked_at": looked,
            "flags": [{"kind": "general", "scope": x["scope"], "text": x["finding"][:200], "priority": "medium"}
                      for x in looked if "not in triage" in x["finding"]][:3],
            "blind_spots": [] if looked else ["no audit sample this cycle"],
            "recommend": {"split": False, "retire": False, "specialist": None, "reason": ""},
            "notes_for_next_time": headline}


# ------------------------------------------------------------------ specialists (reuse investigation roles)

def _specialist(kind: str):
    def run(ctx: "RunContext") -> dict[str, Any]:
        from swarmscope.org import investigations as I
        org = ctx.org
        shim = SimpleNamespace(now=org.engine.now, label=org.engine.label, store=org.engine.store)
        scope = ctx.node.scope
        if scope.startswith("division:"):
            div = org.divisions.get(scope.split(":", 1)[1])
            scope = f"agent:{div.agents[0]}" if div and div.agents else scope
        qkind = {"integrity": "integrity", "propagation": "propagation", "timeline": "convergence",
                 "response": "environment"}.get(kind, "general")
        q = Question(text=ctx.node.brief or ctx.task or kind, scope=scope, kind=qkind)
        obs = [o for o in org.engine.store.all("Observation") if o.scope == scope and o.window_end <= org.engine.now()]
        seed = max(obs, key=lambda o: o.window_end) if obs else None
        fn = {"integrity": I.role_action_verifier, "propagation": I.role_exposure, "timeline": I.role_timeline,
              "response": I.role_response}.get(kind, I.role_deep_dive)
        out = fn(shim, ctx.tools, q, seed, [])
        claims = out.get("claims", [])
        obs_n = sum(1 for c in claims if c["status"] in ("OBSERVED", "DERIVED"))
        unk = [c["statement"] for c in claims if c["status"] == "UNKNOWN"]
        verdict = "supported" if obs_n and not unk else "partially_supported" if obs_n else "unknown"
        return {"headline": out.get("summary", ""), "verdict": verdict, "claims": claims, "open_points": unk[:4],
                "notes_for_next_time": out.get("summary", "")}
    return run


def scout(ctx: "RunContext") -> dict[str, Any]:
    """Rules-only Scout: the selector's pick for this stream, as an architecture_proposal. No new roles."""
    from swarmscope.agents.selector import select, shape
    from swarmscope.agents.spec import list_topologies
    eng = ctx.org.engine
    sh = shape(eng)
    pick = select(sh, {t["id"] for t in list_topologies()})
    unused = [a["field"] for a in sh.get("axes", []) if a["field"] != (pick["partition"] or {}).get("field")][:4]
    return {"headline": f"Proposed team: {pick['topology']}", "base": pick["topology"], "partition": pick["partition"],
            "standing": [], "new_roles": [], "questions": {}, "human": {}, "reasons": pick["reasons"],
            "blind_spots": ([f"axes not used for the partition: {', '.join(unused)}"] if unused else [])
            + ([] if sh.get("environment") else ["no environment actions in the stream: operator interventions are invisible"])}


def generic(ctx: "RunContext") -> dict[str, Any]:
    rows = ctx.tools.query_events(limit=40)
    return {"headline": f"{len(rows)} recent events in scope", "summary": "", "status": "normal" if rows else "quiet",
            "verdict": "unknown", "claims": [_c(f"{len(rows)} recent events in scope.", "DERIVED",
                                                [r["id"] for r in rows[-6:]])] if rows else [],
            "flags": [], "open_points": [], "recommend": {"split": False, "retire": not rows},
            "notes_for_next_time": ""}


def specialist(ctx: "RunContext") -> dict[str, Any]:
    """Kind from a '[kind]' prefix in the brief, else from the scope."""
    import re
    m = re.match(r"\[(\w+)\]", ctx.node.brief or "")
    kind = m.group(1) if m else ("propagation" if ctx.node.scope.startswith("artifact:") else
                                 "integrity" if ctx.node.scope.startswith("agent:") else "timeline")
    return _specialist(kind)(ctx)


BEHAVIOURS = {"specialist": specialist, "analyst": analyst, "sector_lead": sector_lead, "auditor": auditor, "integrity": _specialist("integrity"), "propagation": _specialist("propagation"),
              "timeline": _specialist("timeline"), "response": _specialist("response"),
              "investigator": _specialist("general"), "generic": generic, "scout": scout}
