"""View queries: each returns data shaped for one visualization primitive.

A ViewSpec (packs/<id>/views.yaml) names a primitive and one of these queries.
All queries are clipped to the clock horizon.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable

from swarmscope.core.models import ClaimStatus
from swarmscope.ingest import boundary

SKIP_ACTORS = ("operator", "summarizer")


def _horizon(eng) -> tuple[datetime, datetime]:
    now = eng.now()
    start = getattr(eng.clock, "start", now - timedelta(hours=6))
    return start, now


def activity_timeline(eng, buckets: int = 90, stack: str = "family", top: int = 7, **_) -> dict[str, Any]:
    start, now = _horizon(eng)
    end = getattr(eng.clock, "end", None) or now
    if now <= start:
        return {"start": start, "end": end, "now": now, "series": [], "buckets": [], "markers": []}
    width = (end - start) / buckets
    rows = eng.store.sql("SELECT ts, family FROM events WHERE ts > ? AND ts <= ?", [start, now])
    fams = Counter(r["family"] or "other" for r in rows)
    series = [f for f, _ in fams.most_common(top)]
    data = [{"t": start + width * i, "by": defaultdict(int), "total": 0} for i in range(buckets)]
    for r in rows:
        i = min(buckets - 1, int((r["ts"] - start) / width))
        f = r["family"] or "other"
        data[i]["by"][f if f in series else "other"] += 1
        data[i]["total"] += 1
    markers = [{"t": b.ts, "kind": b.kind, "level": b.level, "text": b.text[:140], "id": b.id}
               for b in eng.store.all("BriefingEntry") if b.kind in ("NEW", "REVISED") or b.level in ("ALERT", "PAGE")]
    if fams.keys() - set(series):
        series.append("other")
    return {"start": start, "end": end, "now": now, "series": series, "markers": markers,
            "buckets": [{"t": d["t"], "total": d["total"], "by": dict(d["by"])} for d in data]}


def actor_resource_graph(eng, hours: float = 12, max_resources: int = 28, max_actors: int = 40, **_) -> dict[str, Any]:
    _, now = _horizon(eng)
    since = now - timedelta(hours=hours)
    rows = eng.store.sql("SELECT actor, object, family, count(*) n, max(ts) AS last_ts FROM events WHERE ts > ? AND ts <= ? "
                         "AND actor IS NOT NULL AND object IS NOT NULL GROUP BY actor, object, family", [since, now])
    res_tot: Counter = Counter()
    for r in rows:
        if r["actor"] not in SKIP_ACTORS and r["family"] not in ("summary", "goal"):
            res_tot[r["object"]] += r["n"]
    keep = {o for o, _ in res_tot.most_common(max_resources)}
    focus = {f.scope: f.weight for f in eng.policy.active(now)}
    incidents = {i.scope: i.level.value for i in eng.exec_state.active_incidents if i.status != "resolved"}
    nodes, edges, actors = {}, [], Counter()
    for r in rows:
        a, o = r["actor"], r["object"]
        if o not in keep or a in SKIP_ACTORS:
            continue
        actors[a] += r["n"]
        edges.append({"source": a, "target": o, "weight": r["n"], "family": r["family"],
                      "recent": (now - r["last_ts"]).total_seconds() < eng.window_len.total_seconds() * 3})
    collapsed = len(actors) > max_actors
    if collapsed:
        # at swarm scale, one node per group (team / model family) keeps the map legible
        members: Counter = Counter()
        grouped: dict[tuple, dict] = {}
        for e in edges:
            ent = eng.store.entity(e["source"])
            g = (ent.group if ent and ent.group else "ungrouped")
            members[g] += 0
            key = (g, e["target"])
            agg = grouped.setdefault(key, {**e, "source": f"group:{g}", "weight": 0, "recent": False})
            agg["weight"] += e["weight"]
            agg["recent"] = agg["recent"] or e["recent"]
        for a in actors:
            ent = eng.store.entity(a)
            members[(ent.group if ent and ent.group else "ungrouped")] += 1
        edges = list(grouped.values())
        gw: Counter = Counter()
        for e in edges:
            gw[e["source"]] += e["weight"]
        for g, cnt in members.items():
            gid = f"group:{g}"
            nodes[gid] = {"id": gid, "kind": "actor", "label": f"{g} · {cnt} agents", "group": g, "type": "group",
                          "weight": gw[gid], "focus": 0, "incident": None}
    else:
        for a, n in actors.items():
            e = eng.store.entity(a)
            sc = f"agent:{a}"
            nodes[a] = {"id": a, "kind": "actor", "label": e.label if e else a, "group": e.group if e else None,
                        "type": e.type if e else "actor", "weight": n, "focus": focus.get(sc, 0), "incident": incidents.get(sc)}
    for o in keep:
        e = eng.store.entity(o)
        sc = f"resource:{o}"
        nodes[o] = {"id": o, "kind": "resource", "label": e.label if e else o,
                    "group": (e.group if e else None) or "other", "weight": res_tot[o], "focus": focus.get(sc, 0),
                    "incident": incidents.get(sc)}
    return {"nodes": list(nodes.values()), "edges": edges, "hours": hours, "collapsed": collapsed,
            "actors": len(actors)}


def actor_swimlane(eng, hours: float = 10, bins: int = 60, **_) -> dict[str, Any]:
    _, now = _horizon(eng)
    since = now - timedelta(hours=hours)
    rows = eng.store.sql("SELECT actor, ts, family, action FROM events WHERE ts > ? AND ts <= ? AND actor IS NOT NULL",
                         [since, now])
    width = (now - since) / bins
    lanes: dict[str, list[Counter]] = defaultdict(lambda: [Counter() for _ in range(bins)])
    totals: Counter = Counter()
    for r in rows:
        if r["actor"] in SKIP_ACTORS or str(r["actor"]).startswith("human:"):
            continue
        i = min(bins - 1, int((r["ts"] - since) / width))
        lanes[r["actor"]][i][r["family"] or "other"] += 1
        totals[r["actor"]] += 1
    out = []
    for a, _ in totals.most_common(30):
        e = eng.store.entity(a)
        cells = [{"family": c.most_common(1)[0][0], "n": sum(c.values())} if c else None for c in lanes[a]]
        out.append({"id": a, "label": e.label if e else a, "group": e.group if e else None, "cells": cells,
                    "total": totals[a]})
    return {"since": since, "now": now, "bins": bins, "lanes": out}


def say_vs_do(eng, **_) -> dict[str, Any]:
    w = eng.watchers.get("self_report_mismatch")
    rows = []
    for r in (w.state.get("ledger", []) if w else [])[-60:]:
        rows.append({"event": r["event"], "actor": eng.label(r["actor"]), "actor_id": r["actor"], "claim": r["claim"],
                     "ts": r["ts"], "corroborating": len(r["corroborating"]), "third_party": r["third_party"],
                     "status": "corroborated" if r["corroborating"] else "uncorroborated"})
    rows.reverse()
    return {"rows": rows, "uncorroborated": sum(1 for r in rows if r["status"] == "uncorroborated"),
            "total": len(rows)}


def artifact_lineage(eng, **_) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for o in eng.store.all("Observation"):
        if o.kind == "content_reuse":
            prev = latest.get(o.scope)
            if not prev or o.window_end >= prev.window_end:
                latest[o.scope] = o
    chains = []
    for scope, o in sorted(latest.items(), key=lambda kv: kv[1].window_end, reverse=True)[:12]:
        m = o.metrics
        origin = eng.store.events(ids=[m.get("origin_event")])
        reusers = []
        for who, ev in (m.get("reuse_events") or {}).items():
            e = eng.store.events(ids=[ev])
            reusers.append({"actor": who, "event": ev, "ts": e[0].ts if e else None,
                            "exposed_via": (m.get("exposure") or {}).get(who),
                            "channel": eng.label(e[0].object) if e else None})
        reusers.sort(key=lambda r: r["ts"] or datetime.min)
        chains.append({"scope": scope, "origin_actor": eng.label(m.get("origin_actor")), "origin_event": m.get("origin_event"),
                       "origin_ts": origin[0].ts if origin else None, "origin_channel": eng.label(m.get("origin_resource")),
                       "reusers": reusers, "observation": o.id})
    return {"chains": chains}


def event_feed(eng, n: int = 80, family: str | None = None, actor: str | None = None, **_) -> dict[str, Any]:
    _, now = _horizon(eng)
    evs = eng.store.events(None, now, family=family, actor=actor, limit=int(n), order="DESC")
    return {"events": [_event_row(eng, e) for e in evs]}


def environment_feed(eng, n: int = 40, **_) -> dict[str, Any]:
    _, now = _horizon(eng)
    rows = eng.store.sql("SELECT id FROM events WHERE ts <= ? AND (action LIKE 'environment.%' OR action = 'chat.human') "
                         "ORDER BY ts DESC LIMIT ?", [now, int(n)])
    return {"events": [_event_row(eng, e) for e in eng.store.events(ids=[r["id"] for r in rows], order="DESC")]}


def agents_table(eng, hours: float = 6, **_) -> dict[str, Any]:
    _, now = _horizon(eng)
    rows = eng.store.sql("SELECT actor, count(*) n, max(ts) AS last_ts, mode(family) fam FROM events WHERE ts > ? AND ts <= ? "
                         "AND actor IS NOT NULL GROUP BY actor ORDER BY n DESC", [now - timedelta(hours=hours), now])
    ctl = eng.control.agents if eng.control else {}
    out = []
    for r in rows:
        e = eng.store.entity(r["actor"])
        if not e or e.type not in ("agent", "actor"):
            continue
        c = ctl.get(r["actor"], {})
        out.append({"id": r["actor"], "label": e.label, "group": e.group, "events": r["n"], "last": r["last_ts"],
                    "family": r["fam"], "status": c.get("status", "observed"), "cost_usd": c.get("cost_usd"),
                    "tool_calls": c.get("tool_calls"), "pending": c.get("pending")})
    return {"agents": out, "controllable": bool(eng.control)}


def _event_row(eng, e) -> dict[str, Any]:
    return {"id": e.id, "ts": e.ts, "actor": eng.label(e.actor), "actor_id": e.actor, "action": e.action,
            "object": eng.label(e.object), "object_id": e.object, "family": e.attributes.get("family"),
            "note": e.attributes.get("short_goal") or e.attributes.get("room") or e.attributes.get("tool"),
            "artifact": e.artifact}


def event_detail(eng, eid: str) -> dict[str, Any] | None:
    evs = eng.store.events(ids=[eid])
    if not evs or evs[0].ts > eng.now():
        return None
    e = evs[0]
    row = _event_row(eng, e)
    row["attributes"] = {k: v for k, v in e.attributes.items() if isinstance(v, (str, int, float, bool, list))}
    row["locator"] = e.locator
    row["source"] = e.source
    if e.artifact:
        a = eng.store.artifact(e.artifact)
        text = eng.store.artifact_text(e.artifact) or ""
        row["artifact_meta"] = {"id": a.id, "fingerprint": a.fingerprint[:16], "size": a.size, "labels": a.labels,
                                "provenance": a.provenance} if a else None
        row["untrusted_text"] = boundary.sanitize(text)[:6000]
    for k, label in (("reasoning", "reasoning_text"), ("rationale", "rationale_text"), ("answer", "answer_text")):
        aid = e.attributes.get(k)
        if aid:                                       # the agent's own reasoning or rationale: untrusted, shown bounded
            row[label] = boundary.sanitize(eng.store.artifact_text(aid) or "")[:6000]
    return row


def claim_detail(eng, cid: str) -> dict[str, Any] | None:
    c = eng.store.get("Claim", cid)
    if not c:
        return None
    def expand(refs):
        out = []
        for r in refs:
            if r.kind == "event":
                d = event_detail(eng, r.id)
                if d:
                    out.append({"kind": "event", **d})
            elif r.kind == "claim":
                cc = eng.store.get("Claim", r.id)
                if cc:
                    out.append({"kind": "claim", "id": cc.id, "statement": cc.statement, "status": cc.status.value})
        return out
    related = [x.model_dump(mode="json") for x in eng.store.all("Claim")
               if x.id != c.id and x.scope and x.scope == c.scope][-8:]
    return {**c.model_dump(mode="json"), "support_detail": expand(c.support), "counter_detail": expand(c.counter),
            "related": related}


def entity_detail(eng, eid: str) -> dict[str, Any] | None:
    e = eng.store.entity(eid)
    if not e:
        return None
    _, now = _horizon(eng)
    fam = eng.store.sql("SELECT family, count(*) n FROM events WHERE (actor = ? OR object = ?) AND ts <= ? "
                        "GROUP BY family ORDER BY n DESC", [eid, eid, now])
    recent = eng.store.events(None, now, actor=eid, limit=25, order="DESC") or \
        eng.store.events(None, now, obj=eid, limit=25, order="DESC")
    obs = [o.model_dump(mode="json") for o in eng.store.all("Observation") if o.scope.endswith(eid)][-10:]
    return {"entity": e.model_dump(mode="json"), "families": fam, "recent": [_event_row(eng, x) for x in recent],
            "observations": obs}


VIEWS: dict[str, Callable[..., dict[str, Any]]] = {
    "activity_timeline": activity_timeline, "actor_resource_graph": actor_resource_graph,
    "actor_swimlane": actor_swimlane, "say_vs_do": say_vs_do, "artifact_lineage": artifact_lineage,
    "event_feed": event_feed, "environment_feed": environment_feed, "agents_table": agents_table,
}
