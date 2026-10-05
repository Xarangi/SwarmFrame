"""Division strategies: how the population is partitioned for division-scoped agents.

  by_resource_cluster  communities in the agent–resource graph (hubs like chat rooms removed)
  by_family            one division per workstream family
  by_group             one division per entity group (team, model family)
  llm                  starts from clusters; the main agent may redefine divisions with org tools

Division ids are kept stable across cycles by matching on membership overlap, so an analyst
keeps "its" division as the population drifts.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

import networkx as nx

SKIP_FAMILIES = {"summary", "goal", "lifecycle", "control", "narration"}
SKIP_ACTORS = {"operator", "summarizer"}


@dataclass
class Division:
    id: str
    label: str
    kind: str                                       # cluster | family | group | split | merged | defined
    agents: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    families: list[str] = field(default_factory=list)
    events: int = 0
    prev_events: int = 0
    parent: str | None = None
    created: datetime | None = None
    pinned: bool = False                            # defined/split by an agent or human: not recomputed
    missed: int = 0                                 # refreshes without a matching fresh division
    cohorts: list[str] = field(default_factory=list)   # by_cohort: the cohorts this division groups

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["created"] = self.created.isoformat() if self.created else None
        return d


def _rows(store, now: datetime, lookback: timedelta) -> list[dict[str, Any]]:
    return store.sql("SELECT actor, object, family, count(*) n FROM events WHERE ts > ? AND ts <= ? AND actor IS NOT NULL "
                     "GROUP BY actor, object, family", [now - lookback, now])


def _keep(r: dict[str, Any]) -> bool:
    a = str(r["actor"])
    return a not in SKIP_ACTORS and not a.startswith("human:") and (r["family"] or "other") not in SKIP_FAMILIES


def _did(kind: str, key: str) -> str:
    return f"div_{kind[:3]}_{hashlib.sha1(key.encode()).hexdigest()[:8]}"


def by_family(store, now, lookback, label, max_n: int, min_events: int) -> list[Division]:
    agg: dict[str, dict[str, Any]] = defaultdict(lambda: {"agents": Counter(), "res": Counter(), "n": 0})
    for r in _rows(store, now, lookback):
        if not _keep(r) or (r["family"] or "other") == "chat":
            continue
        g = agg[r["family"] or "other"]
        g["agents"][r["actor"]] += r["n"]
        if r["object"]:
            g["res"][r["object"]] += r["n"]
        g["n"] += r["n"]
    out = [Division(id=_did("family", f), label=f"{f} workstream", kind="family", agents=list(g["agents"]),
                    resources=[o for o, _ in g["res"].most_common(40)], families=[f], events=g["n"])
           for f, g in agg.items() if g["n"] >= min_events]
    return sorted(out, key=lambda d: -d.events)[:max_n]


def by_group(store, now, lookback, label, max_n: int, min_events: int) -> list[Division]:
    agg: dict[str, dict[str, Any]] = defaultdict(lambda: {"agents": Counter(), "res": Counter(), "fam": Counter(), "n": 0})
    for r in _rows(store, now, lookback):
        if not _keep(r):
            continue
        ent = store.entity(r["actor"])
        g = agg[(ent.group if ent and ent.group else "ungrouped")]
        g["agents"][r["actor"]] += r["n"]
        g["fam"][r["family"] or "other"] += r["n"]
        if r["object"]:
            g["res"][r["object"]] += r["n"]
        g["n"] += r["n"]
    out = [Division(id=_did("group", k), label=f"{k} group", kind="group", agents=list(g["agents"]),
                    resources=[o for o, _ in g["res"].most_common(40)], families=[f for f, _ in g["fam"].most_common(4)],
                    events=g["n"]) for k, g in agg.items() if g["n"] >= min_events]
    return sorted(out, key=lambda d: -d.events)[:max_n]


def by_field(store, now, lookback, label, max_n: int, min_events: int, field: str = "family",
             unit: str = "actor") -> list[Division]:
    """One division per value of a categorical field: each unit (actor, or object for identity-free sources) joins the
    division of its dominant value. Core columns (family, action, actor_group) are read directly; anything else is an
    attribute key."""
    core = {"family": "family", "action": "action", "actor_group": "actor_group", "object": "object"}
    col = core.get(field)
    if col is None:
        col = f"json_extract_string(attributes, '$.{field}')"
    ucol = "actor" if unit == "actor" else "object"
    try:
        rows = store.sql(f"SELECT {ucol} AS u, object, family, {col} AS v, count(*) n FROM events WHERE ts > ? AND ts <= ? "
                         f"AND {ucol} IS NOT NULL GROUP BY u, object, family, v", [now - lookback, now])
    except Exception:
        rows = []
        for r in store.sql(f"SELECT {ucol} AS u, object, family, attributes FROM events WHERE ts > ? AND ts <= ? AND {ucol} IS NOT NULL",
                           [now - lookback, now]):
            try:
                v = (json.loads(r["attributes"] or "{}") or {}).get(field)
            except Exception:
                v = None
            rows.append({"u": r["u"], "object": r["object"], "family": r["family"], "v": v, "n": 1})
    per_unit: dict[str, Counter] = defaultdict(Counter)
    detail: dict[str, dict[str, Any]] = defaultdict(lambda: {"res": Counter(), "fam": Counter(), "n": 0})
    for r in rows:
        u = str(r["u"])
        if unit == "actor" and (u in SKIP_ACTORS or u.startswith("human:")):
            continue
        per_unit[u][str(r["v"] if r["v"] is not None else "other")] += r["n"]
        d = detail[u]
        d["n"] += r["n"]
        d["fam"][r["family"] or "other"] += r["n"]
        if r["object"]:
            d["res"][r["object"]] += r["n"]
    agg: dict[str, dict[str, Any]] = defaultdict(lambda: {"units": [], "res": Counter(), "fam": Counter(), "n": 0})
    for u, c in per_unit.items():
        v = c.most_common(1)[0][0]
        g = agg[v]
        g["units"].append(u)
        g["res"].update(detail[u]["res"])
        g["fam"].update(detail[u]["fam"])
        g["n"] += detail[u]["n"]
    out = []
    for v, g in agg.items():
        if g["n"] < min_events:
            continue
        agents = sorted(g["units"]) if unit == "actor" else []
        resources = [o for o, _ in g["res"].most_common(40)] if unit == "actor" else sorted(g["units"])
        out.append(Division(id=_did("field", f"{field}={v}"), label=f"{v}" if field == "family" else f"{field} {v}",
                            kind="field", agents=agents, resources=resources,
                            families=[f for f, _ in g["fam"].most_common(4)], events=g["n"]))
    return sorted(out, key=lambda d: -d.events)[:max_n]


def by_resource_cluster(store, now, lookback, label, max_n: int, min_events: int) -> list[Division]:
    rows = [r for r in _rows(store, now, lookback) if _keep(r) and r["object"]]
    G = nx.Graph()
    actors = {r["actor"] for r in rows}
    deg: Counter = Counter()
    for r in rows:
        deg[r["object"]] += 1
    # hubs touched by more than half the population (chat rooms, shared boards) say little about divisions
    hub = {o for o, d in deg.items() if len(actors) > 4 and d > 0.5 * len(actors)}
    for r in rows:
        if r["object"] in hub:
            continue
        G.add_edge(("a", r["actor"]), ("r", r["object"]), weight=r["n"])
    if G.number_of_edges() == 0:
        return by_group(store, now, lookback, label, max_n, min_events)
    comms = nx.community.louvain_communities(G, weight="weight", seed=7, resolution=1.0)
    ev = Counter()
    fam: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        ev[("a", r["actor"])] += r["n"]
        fam[r["actor"]][r["family"] or "other"] += r["n"]
    out = []
    for c in comms:
        ags = [n[1] for n in c if n[0] == "a"]
        res = [n[1] for n in c if n[0] == "r"]
        if not ags:
            continue
        n = sum(ev[("a", a)] for a in ags)
        if n < min_events:
            continue
        fams = Counter()
        for a in ags:
            fams.update(fam[a])
        top_res = sorted(res, key=lambda o: -deg[o])[:3]
        name = ", ".join(label(o) for o in top_res[:2]) or ", ".join(label(a) for a in ags[:2])
        out.append(Division(id=_did("cluster", "|".join(sorted(ags))), label=name, kind="cluster", agents=sorted(ags),
                            resources=sorted(res, key=lambda o: -deg[o])[:40],
                            families=[f for f, _ in fams.most_common(4)], events=n))
    return sorted(out, key=lambda d: -d.events)[:max_n]


def by_cohort(layer, max_n: int, per_division: int = 6, min_events: int = 1) -> list[Division]:
    """Group behavioural cohorts (scale layer) into balanced divisions of related cohorts.

    Works at any population size: a division is a handful of cohorts, so an analyst reads cohort cards, not agents.
    For identity-free sources the units are keys (e.g. targets), and they become the division's resources."""
    cs = [c for c in layer.cohorts.values() if c.events_now + c.events_prev >= min_events or c.outliers]
    if not cs:
        return []
    k = max(1, min(max_n, -(-len(cs) // max(1, per_division))))
    cs.sort(key=lambda c: (str(c.signature[0]), -c.events_now))
    total = sum(c.events_now + 1 for c in cs)
    bins: list[list] = [[]]
    acc = 0.0
    for c in cs:
        if acc >= total / k * len(bins) and len(bins) < k:
            bins.append([])
        bins[-1].append(c)
        acc += c.events_now + 1
    out = []
    actor_units = layer.cfg["unit"] == "actor"
    for b in bins:
        if not b:
            continue
        units = sorted({u for c in b for u in c.members})
        res = Counter()
        fams = Counter()
        for c in b:
            res.update(dict(c.top_resources))
            fams[str(c.signature[0])] += c.events_now + 1
        lead = ", ".join(f for f, _ in fams.most_common(2))
        label = f"{lead} · {len(b)} cohort{'s' if len(b) > 1 else ''}, {len(units)} {'agents' if actor_units else 'units'}"
        out.append(Division(id=_did("cohort", "|".join(sorted(c.id for c in b))), label=label, kind="cohort",
                            agents=units if actor_units else [],
                            resources=[r for r, _ in res.most_common(40)] if actor_units else units,
                            families=[f for f, _ in fams.most_common(4)], events=sum(c.events_now for c in b),
                            cohorts=[c.id for c in b]))
    return sorted(out, key=lambda d: -d.events)


STRATEGIES = {"by_resource_cluster": by_resource_cluster, "by_family": by_family, "by_group": by_group,
              "by_field": by_field, "llm": by_resource_cluster}


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / max(1, len(sa | sb))


def reconcile(prev: dict[str, Division], fresh: list[Division], now: datetime, grace: int = 3,
              store=None, lookback: timedelta | None = None) -> dict[str, Division]:
    """Keep ids stable: a fresh division inherits the id of the previous one it overlaps most.
    Unmatched divisions linger for `grace` refreshes (while still active) so agents are not churned."""
    out: dict[str, Division] = {d.id: d for d in prev.values() if d.pinned}
    taken = set(out)
    for d in fresh:
        best, score = None, 0.0
        for p in prev.values():
            if p.id in taken or p.pinned:
                continue
            s = max(jaccard(d.agents, p.agents) if d.agents or p.agents else 0.0,
                    0.8 * jaccard(d.resources, p.resources), jaccard(d.cohorts, p.cohorts) if d.cohorts else 0.0)
            if s > score:
                best, score = p, s
        if best and score >= 0.3:
            d.prev_events, d.id, d.created = best.events, best.id, best.created
            d.label = best.label if best.kind == d.kind and d.kind != "cohort" else d.label
        d.created = d.created or now
        if d.id in out:
            continue
        taken.add(d.id)
        out[d.id] = d
    for p in prev.values():
        if p.id in out or p.pinned:
            continue
        p.missed += 1
        if store is not None and lookback is not None:
            refresh_pinned(store, p, now, lookback)
        if p.missed <= grace and p.events > 0:
            out[p.id] = p
    for d in out.values():
        if d.id in {f.id for f in fresh}:
            d.missed = 0
    return out


def refresh_pinned(store, d: Division, now: datetime, lookback: timedelta) -> None:
    if not d.agents:
        return
    q = f"SELECT count(*) FROM events WHERE ts > ? AND ts <= ? AND actor IN ({','.join('?' * len(d.agents))})"
    d.prev_events, d.events = d.events, int(store.scalar(q, [now - lookback, now, *d.agents]) or 0)


def split(store, d: Division, now: datetime, lookback: timedelta, label) -> list[Division]:
    """Split a division into sub-communities of its own agent–resource graph."""
    if len(d.agents) < 2:
        return [d]
    rows = store.sql(f"SELECT actor, object, family, count(*) n FROM events WHERE ts > ? AND ts <= ? AND actor IN "
                     f"({','.join('?' * len(d.agents))}) AND object IS NOT NULL GROUP BY actor, object, family",
                     [now - lookback, now, *d.agents])
    G = nx.Graph()
    for r in rows:
        if (r["family"] or "other") not in SKIP_FAMILIES | {"chat"}:
            G.add_edge(("a", r["actor"]), ("r", r["object"]), weight=r["n"])
    parts = nx.community.louvain_communities(G, weight="weight", seed=11, resolution=1.6) if G.number_of_edges() else []
    groups = [[n[1] for n in c if n[0] == "a"] for c in parts]
    groups = sorted([g for g in groups if g], key=len, reverse=True)
    # fold singletons into the largest part; a split must leave at least two parts of two or more agents
    big = [g for g in groups if len(g) >= 2]
    for g in groups:
        if len(g) < 2 and big:
            big[-1] = big[-1] + g
    groups = big
    if len(groups) < 2:
        if len(d.agents) < 4:
            return [d]
        half = len(d.agents) // 2
        groups = [d.agents[:half], d.agents[half:]]
    out = []
    use: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        use[r["object"]][r["actor"]] += r["n"]
    base = d.label.split(" · ")[0]
    for i, g in enumerate(groups[:4]):
        gs = set(g)
        res = sorted({r["object"] for r in rows if r["actor"] in gs})
        # most distinctive resource: highest share of its use coming from this part
        dist = max(res, key=lambda o: (sum(n for a, n in use[o].items() if a in gs) / max(1, sum(use[o].values())),
                                       sum(use[o].values())), default=None)
        lead = max(g, key=lambda a: sum(use[o][a] for o in use))
        lab = f"{base} · {label(dist) if dist else label(lead)} ({label(lead)}{' +' + str(len(g) - 1) if len(g) > 1 else ''})"
        out.append(Division(id=f"{d.id}_{i + 1}", label=lab, kind="split", agents=sorted(g), resources=res[:40],
                            families=d.families, parent=d.id, created=now, pinned=True,
                            events=sum(r["n"] for r in rows if r["actor"] in g)))
    return out


def merge(divs: list[Division], label: str | None, now: datetime) -> Division:
    agents = sorted({a for d in divs for a in d.agents})
    return Division(id=_did("merged", "|".join(d.id for d in divs)), label=label or " + ".join(d.label for d in divs[:3]),
                    kind="merged", agents=agents, resources=sorted({r for d in divs for r in d.resources})[:60],
                    families=sorted({f for d in divs for f in d.families}), events=sum(d.events for d in divs),
                    created=now, pinned=True)
