"""A small, safe query language for dashboard views.

Agents (and humans) describe what a view shows; this module compiles it to parameterized SQL over the evidence
store, or computes it from the scale layer. No raw SQL is accepted, every query is clipped to the clock horizon, and
agent-written text never comes back: only structural fields and attributes judged categorical by the stream profile.

  {"from": "events",
   "where": {"family": ["chat", "files"], "action": {"prefix": "scan."}, "attr.confidence": "significant",
             "actor": "<id or label>", "object": "<id or label>"},
   "time": {"last_hours": 48} | {"all": true},
   "group_by": ["ts:day", "attr.confidence"],          # zero, one or two dimensions
   "metric": "count" | "distinct:actor" | "distinct:object",
   "top": 12}

Other sources: "observations" (kind, scope, severity), "cohorts", "templates", "triage", "claims", "org".
Results are {columns, rows, meta}; rows are lists in column order, labels resolved for actor/object.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from swarmscope.engine import Engine

CORE = {"actor": "actor", "object": "object", "family": "family", "action": "action", "group": "actor_group",
        "source": "source"}
BUCKETS = {"ts:hour": "hour", "ts:day": "day", "ts:week": "week", "ts:month": "month"}
ATTR = re.compile(r"^attr\.([a-z_][a-z0-9_]{0,40})$")
SOURCES = ["events", "observations", "cohorts", "templates", "triage", "claims", "org"]
METRICS = ["count", "distinct:actor", "distinct:object"]


class QueryError(ValueError):
    pass


def _field_sql(f: str, text_attrs: set[str]) -> tuple[str, str]:
    """(sql expression, column name) for a group-by or filter field."""
    if f in CORE:
        return CORE[f], f
    if f in BUCKETS:
        return f"date_trunc('{BUCKETS[f]}', ts)", f
    if f == "ts:window":
        return "ts", f
    m = ATTR.match(f)
    if m:
        if m.group(1) in text_attrs:
            raise QueryError(f"{f} holds agent-written or high-cardinality text and cannot be used in a view")
        return f"json_extract_string(attributes, '$.{m.group(1)}')", f
    raise QueryError(f"unknown field {f!r}; use one of {sorted(CORE)}, {sorted(BUCKETS)}, attr.<key>")


def run(engine: "Engine", q: dict[str, Any], text_attrs: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(q, dict):
        raise QueryError("a query is an object")
    src = q.get("from", "events")
    if src not in SOURCES:
        raise QueryError(f"from must be one of {SOURCES}")
    if src == "events":
        return _events(engine, q, text_attrs or set())
    return _derived(engine, src, q)


def _events(engine: "Engine", q: dict[str, Any], text_attrs: set[str]) -> dict[str, Any]:
    horizon = engine.now()
    if q.get("list"):
        return _list(engine, q, text_attrs)
    where, params = ["ts <= ?"], [horizon.replace(tzinfo=None)]
    t = q.get("time") or {"last_hours": 24}
    if not t.get("all"):
        hours = float(t.get("last_hours", 24))
        if not 0 < hours <= 24 * 3650:
            raise QueryError("time.last_hours must be between 0 and 87600")
        where.append("ts > ?")
        params.append((horizon - timedelta(hours=hours)).replace(tzinfo=None))
    for k, v in (q.get("where") or {}).items():
        expr, _ = _field_sql(k, text_attrs)
        if k in ("actor", "object") and isinstance(v, str):
            v = _resolve(engine, v)
        if isinstance(v, dict) and "prefix" in v:
            where.append(f"{expr} LIKE ?")
            params.append(str(v["prefix"]).replace("%", "") + "%")
        elif isinstance(v, list):
            if not v:
                continue
            where.append(f"{expr} IN ({','.join('?' * len(v))})")
            params.extend(str(x) for x in v[:50])
        else:
            where.append(f"{expr} = ?")
            params.append(str(v))
    group = list(q.get("group_by") or [])[:2]
    metric = q.get("metric", "count")
    if metric not in METRICS:
        raise QueryError(f"metric must be one of {METRICS}")
    agg = "count(*)" if metric == "count" else f"count(DISTINCT {metric.split(':')[1]})"
    top = max(1, min(int(q.get("top", 12)), 60))
    if not group:
        n = engine.store.scalar(f"SELECT {agg} FROM events WHERE {' AND '.join(where)}", params)
        return {"columns": ["value"], "rows": [[int(n or 0)]], "meta": {"metric": metric}}
    if group == ["ts:window"]:
        group = ["ts:hour" if engine.window_len <= timedelta(hours=1) else "ts:day"]
    exprs = [_field_sql(g, text_attrs) for g in group]
    sel = ", ".join(f"{e} AS g{i}" for i, (e, _) in enumerate(exprs))
    gb = ", ".join(f"g{i}" for i in range(len(exprs)))
    time_dims = [i for i, g in enumerate(group) if g.startswith("ts:")]
    sql = f"SELECT {sel}, {agg} AS v FROM events WHERE {' AND '.join(where)} GROUP BY {gb}"
    rows = engine.store.sql(sql, params)
    # events without an actor / object / group say nothing about who or where: leave them out of those breakdowns
    for i, g in enumerate(group):
        if g in ("actor", "object", "group") or g.startswith("attr."):
            had = bool(rows)
            rows = [r for r in rows if r[f"g{i}"] not in (None, "")]
            if had and not rows and g.startswith("attr."):
                raise QueryError(f"no events in range carry {g}; see stream_profile for the attributes this stream has")
    # the bucket holding the replay clock is still filling; drop it so a chart does not appear to fall to zero
    partial = None
    if time_dims and rows:
        last = max(r[f"g{time_dims[0]}"] for r in rows)
        bucket = {"ts:hour": timedelta(hours=1), "ts:day": timedelta(days=1), "ts:week": timedelta(days=7),
                  "ts:month": timedelta(days=28)}.get(group[time_dims[0]])
        if bucket is not None and isinstance(last, datetime) and last + bucket > horizon.replace(tzinfo=None):
            if len({r[f"g{time_dims[0]}"] for r in rows}) > 2:
                rows = [r for r in rows if r[f"g{time_dims[0]}"] != last]
                partial = last.isoformat(sep=" ", timespec="minutes")
    # keep the top categories of each non-time dimension, so a view stays readable
    for i, g in enumerate(group):
        if i in time_dims:
            continue
        tot: Counter = Counter()
        for r in rows:
            tot[r[f"g{i}"]] += r["v"]
        keep = {k for k, _ in tot.most_common(top)}
        rows = [r for r in rows if r[f"g{i}"] in keep]
    if time_dims:
        rows.sort(key=lambda r: tuple(str(r[f"g{i}"]) for i in range(len(group))))
    else:
        rows.sort(key=lambda r: -r["v"])
    rows = rows[:2000]
    out, ids = [], []
    for r in rows:
        vals, rid = [], []
        for i, g in enumerate(group):
            v = r[f"g{i}"]
            rid.append(v if g in ("actor", "object") else None)
            if g in ("actor", "object") and v is not None:
                v = engine.label(v)
            elif isinstance(v, datetime):
                v = v.isoformat(sep=" ", timespec="minutes")
            vals.append(v if v is not None else "none")
        out.append(vals + [int(r["v"])])
        ids.append(rid + [None])
    meta = {"metric": metric, "time_dims": time_dims, "dropped_partial_bucket": partial}
    if any(g in ("actor", "object") for g in group):
        meta["ids"] = ids                       # entity ids behind actor/object labels, so a click opens the evidence
    return {"columns": group + [metric], "rows": out, "meta": meta}


def _list(engine: "Engine", q: dict[str, Any], text_attrs: set[str]) -> dict[str, Any]:
    """The latest matching events, newest first: structure only (never agent text), each with its event id."""
    if q.get("group_by"):
        raise QueryError("a list (feed) query has no group_by")
    horizon = engine.now()
    where, params = ["ts <= ?"], [horizon.replace(tzinfo=None)]
    t = q.get("time") or {"last_hours": 24}
    if not t.get("all"):
        hours = float(t.get("last_hours", 24))
        if not 0 < hours <= 24 * 3650:
            raise QueryError("time.last_hours must be between 0 and 87600")
        where.append("ts > ?")
        params.append((horizon - timedelta(hours=hours)).replace(tzinfo=None))
    for k, v in (q.get("where") or {}).items():
        expr, _ = _field_sql(k, text_attrs)
        if k in ("actor", "object") and isinstance(v, str):
            v = _resolve(engine, v)
        if isinstance(v, dict) and "prefix" in v:
            where.append(f"{expr} LIKE ?")
            params.append(str(v["prefix"]).replace("%", "") + "%")
        elif isinstance(v, list):
            if v:
                where.append(f"{expr} IN ({','.join('?' * len(v))})")
                params.extend(str(x) for x in v[:50])
        else:
            where.append(f"{expr} = ?")
            params.append(str(v))
    n = max(1, min(int(q.get("top", 20)), 100))
    rows = engine.store.sql(f"SELECT id, ts, actor, action, object, family FROM events WHERE {' AND '.join(where)} "
                            f"ORDER BY ts DESC LIMIT {n}", params)
    out, eids, ids = [], [], []
    for r in rows:
        ts = r["ts"].isoformat(sep=" ", timespec="minutes") if isinstance(r["ts"], datetime) else str(r["ts"])
        out.append([ts, engine.label(r["actor"]) if r["actor"] else "", r["action"],
                    engine.label(r["object"]) if r["object"] else "", r["family"] or ""])
        eids.append(r["id"])
        ids.append([None, r["actor"], None, r["object"], None])
    return {"columns": ["time", "actor", "action", "object", "family"], "rows": out,
            "meta": {"event_ids": eids, "ids": ids, "list": True}}


def _resolve(engine: "Engine", ref: str) -> str:
    if engine.store.entity(ref):
        return ref
    for e in engine.store.entities():
        if e.label.lower() == ref.lower():
            return e.id
    return ref


def _derived(engine: "Engine", src: str, q: dict[str, Any]) -> dict[str, Any]:
    top = max(1, min(int(q.get("top", 12)), 60))
    if src == "cohorts":
        lay = engine.scale
        cs = sorted(lay.cohorts.values(), key=lambda c: -c.events_now)[:top]
        return {"columns": ["cohort", "units", "events_now", "events_prev", "outliers"],
                "rows": [[c.label, len(c.members), c.events_now, c.events_prev, len(c.outliers)] for c in cs],
                "meta": {"ids": [c.id for c in cs]}}
    if src == "templates":
        rows = engine.scale.template_rows(limit=top, sort=q.get("sort", "spread"))
        return {"columns": ["template", "messages", "units", "cohorts", "now", "prev"],
                "rows": [[r["id"], r["messages"], r["units"], r["cohorts"], r["now"], r["prev"]] for r in rows],
                "meta": {}}
    if src == "triage":
        t = engine.triage.to_dict()
        return {"columns": ["scope", "lane", "priority", "reasons"],
                "rows": [[i["label"], i["lane"], i["priority"], "; ".join(i["reasons"][:2])] for i in t["items"]],
                "meta": {"hit_rates": t["hit_rates"]}}
    if src == "claims":
        c = Counter(x.status.value for x in engine.store.all("Claim") if not x.ts or x.ts <= engine.now())
        return {"columns": ["status", "count"], "rows": [[k, v] for k, v in c.most_common()], "meta": {}}
    if src == "org":
        c = Counter(n.role for n in engine.agent_org.active())
        return {"columns": ["role", "agents"], "rows": [[k, v] for k, v in c.most_common()], "meta": {}}
    if src == "observations":
        h = engine.now()
        hours = float((q.get("time") or {}).get("last_hours", 24 * 365))
        obs = [o for o in engine.store.all("Observation") if h - timedelta(hours=hours) < o.window_end <= h]
        kinds = (q.get("where") or {}).get("kind")
        if kinds:
            kinds = [kinds] if isinstance(kinds, str) else kinds
            obs = [o for o in obs if o.kind in kinds]
        group = list(q.get("group_by") or ["kind"])[:2]

        def key(o, g):
            if g == "kind":
                return o.kind
            if g == "scope":
                return engine._scope_label(o.scope)
            if g in BUCKETS:
                d = o.window_end
                return (d.replace(minute=0, second=0, microsecond=0) if g == "ts:hour" else
                        d.replace(hour=0, minute=0, second=0, microsecond=0)).isoformat(sep=" ", timespec="minutes")
            raise QueryError("observations group_by: kind, scope, ts:hour, ts:day")
        c = Counter(tuple(key(o, g) for g in group) for o in obs)
        rows = sorted(([*k, v] for k, v in c.items()), key=lambda r: (str(r[0]) if group[0].startswith("ts:") else -r[-1]))
        return {"columns": group + ["count"], "rows": rows[:2000] if group[0].startswith("ts:") else rows[:top],
                "meta": {"time_dims": [i for i, g in enumerate(group) if g.startswith("ts:")]}}
    raise QueryError(f"unknown source {src}")
