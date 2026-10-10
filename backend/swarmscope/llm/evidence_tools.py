"""Evidence tools: the only way analysis roles touch the store.

Deterministic investigators call these methods directly; LLM agents get them as
an in-process MCP server. Results are structured and never contain raw agent
text, except `read_raw`, which wraps content in an <untrusted> envelope and is
withheld from privileged roles (Executive, critic) by role config.
Every query is clipped to the clock horizon so replay never leaks the future.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Callable

from swarmscope.ingest import boundary
from swarmscope.store.store import Store

PRIVILEGED_ROLES = {"executive", "critic"}


class EvidenceTools:
    def __init__(self, store: Store, horizon: Callable[[], datetime], source: str, role: str = "investigator",
                 scope: tuple[list[str], list[str]] | None = None, allowed: list[str] | None = None,
                 engine: Any = None):
        self.store, self.horizon, self.source, self.role = store, horizon, source, role
        self.engine = engine          # gives the scale tools (cohorts, templates, triage) their layer
        self.scope = scope            # (agent ids, resource ids): division-scoped agents see only this slice
        self.allowed = allowed        # tool names exported over MCP (None = all)
        self.calls: list[dict[str, Any]] = []
        self.inspected: set[str] = set()

    # ------------------------------------------------------------ helpers
    def _label(self, eid: str | None) -> str | None:
        e = self.store.entity(eid)
        return e.label if e else eid

    def _row(self, e) -> dict[str, Any]:
        self.inspected.add(e.id)
        a = e.attributes
        return {"id": e.id, "ts": e.ts.isoformat(sep=" ", timespec="seconds"), "actor": self._label(e.actor),
                "actor_id": e.actor, "action": e.action, "object": self._label(e.object), "object_id": e.object,
                "family": a.get("family"), "note": a.get("short_goal") or a.get("room"), "artifact": e.artifact,
                **({"reasoning_artifact": a["reasoning"]} if a.get("reasoning") else {}),   # read it with read_raw
                **({"tools": a["tools"]} if a.get("tools") else {})}

    def _log(self, name: str, args: dict[str, Any], n: int) -> None:
        self.calls.append({"tool": name, "args": {k: v for k, v in args.items() if v is not None}, "results": n})

    def _resolve(self, ref: str | None) -> str | None:
        """Accept an entity id or label (or scope like agent:<id>, resource:<id>)."""
        if not ref:
            return None
        if ":" in ref and ref.split(":", 1)[0] in ("agent", "resource", "actor"):
            ref = ref.split(":", 1)[1]
        if self.store.entity(ref):
            return ref
        for e in self.store.entities():
            if e.label.lower() == ref.lower().lstrip("#") or e.label.lower() == ref.lower():
                return e.id
        return ref

    # ------------------------------------------------------------ tools
    def query_events(self, actor: str | None = None, object: str | None = None, family: str | None = None,
                     action: str | None = None, since: str | None = None, until: str | None = None,
                     limit: int = 40) -> list[dict[str, Any]]:
        h = self.horizon()
        end = min(datetime.fromisoformat(until), h) if until else h
        start = datetime.fromisoformat(since) if since else None
        evs = self.store.events(start, end, actor=self._resolve(actor), obj=self._resolve(object), family=family,
                                action=action, limit=min(int(limit), 200), order="DESC", within=self.scope)
        rows = [self._row(e) for e in reversed(evs)]
        self._log("query_events", dict(actor=actor, object=object, family=family, action=action, since=since,
                                       until=until), len(rows))
        return rows

    def events_by_id(self, ids: list[str]) -> list[dict[str, Any]]:
        h = self.horizon()
        rows = [self._row(e) for e in self.store.events(ids=list(ids)[:100]) if e.ts <= h]
        self._log("events_by_id", {"n": len(ids)}, len(rows))
        return rows

    def entity(self, id: str) -> dict[str, Any] | None:
        e = self.store.entity(self._resolve(id))
        self._log("entity", {"id": id}, int(bool(e)))
        if not e:
            return None
        n = self.store.scalar("SELECT count(*) FROM events WHERE (actor = ? OR object = ?) AND ts <= ?",
                              [e.id, e.id, self.horizon()])
        return {"id": e.id, "type": e.type, "label": e.label, "group": e.group,
                "identity_confidence": e.identity_confidence, "events": n,
                "attributes": {k: v for k, v in e.attributes.items() if isinstance(v, (str, int, float, bool))}}

    def neighborhood(self, id: str, hours: float = 24) -> dict[str, Any]:
        eid = self._resolve(id)
        h = self.horizon()
        since = h - timedelta(hours=hours)
        ent = self.store.entity(eid)
        if ent and ent.type in ("agent", "actor", "human"):
            res = self.store.sql("SELECT object, count(*) n FROM events WHERE actor = ? AND ts > ? AND ts <= ? "
                                 "AND object IS NOT NULL GROUP BY object ORDER BY n DESC LIMIT 12", [eid, since, h])
            objs = [r["object"] for r in res]
            co = self.store.sql(
                f"SELECT actor, count(*) n FROM events WHERE object IN ({','.join('?' * len(objs)) or 'NULL'}) "
                "AND actor != ? AND ts > ? AND ts <= ? GROUP BY actor ORDER BY n DESC LIMIT 12",
                [*objs, eid, since, h]) if objs else []
            out = {"resources": [{"id": r["object"], "label": self._label(r["object"]), "events": r["n"]} for r in res],
                   "co_actors": [{"id": r["actor"], "label": self._label(r["actor"]), "events": r["n"]} for r in co]}
        else:
            act = self.store.sql("SELECT actor, count(*) n, min(ts) AS first_ts, max(ts) AS last_ts FROM events WHERE object = ? "
                                 "AND ts > ? AND ts <= ? GROUP BY actor ORDER BY first_ts", [eid, since, h])
            out = {"actors": [{"id": r["actor"], "label": self._label(r["actor"]), "events": r["n"],
                               "first": str(r["first_ts"])[:19], "last": str(r["last_ts"])[:19]} for r in act]}
        self._log("neighborhood", {"id": id, "hours": hours}, sum(len(v) for v in out.values()))
        return out

    def artifact_meta(self, id: str) -> dict[str, Any] | None:
        a = self.store.artifact(id)
        self._log("artifact_meta", {"id": id}, int(bool(a)))
        if not a:
            return None
        return {"id": a.id, "fingerprint": a.fingerprint[:16], "size": a.size, "labels": a.labels,
                "first_seen": str(a.first_seen)[:19], "first_actor": self._label(a.first_actor),
                "blocks": len(a.blocks), "provenance": a.provenance}

    def exposure_paths(self, actor: str, resource: str, since: str | None = None,
                       until: str | None = None) -> list[dict[str, Any]]:
        """Events showing `actor` acted on `resource` in the time range (an observed exposure path)."""
        h = self.horizon()
        end = min(datetime.fromisoformat(until), h) if until else h
        start = datetime.fromisoformat(since) if since else None
        evs = self.store.events(start, end, actor=self._resolve(actor), obj=self._resolve(resource), limit=10)
        rows = [self._row(e) for e in evs]
        self._log("exposure_paths", dict(actor=actor, resource=resource, since=since, until=until), len(rows))
        return rows

    def timeline(self, family: str | None = None, actor: str | None = None, object: str | None = None,
                 hours: float = 24, buckets: int = 12) -> list[dict[str, Any]]:
        h = self.horizon()
        start = h - timedelta(hours=hours)
        evs = self.store.events(start, h, actor=self._resolve(actor), obj=self._resolve(object), family=family,
                                within=self.scope,
                                limit=20000)
        width = (h - start) / buckets
        counts = Counter(min(buckets - 1, int((e.ts - start) / width)) for e in evs)
        out = [{"bucket_start": str(start + width * i)[:16], "events": counts.get(i, 0)} for i in range(buckets)]
        self._log("timeline", dict(family=family, actor=actor, object=object, hours=hours), len(evs))
        return out

    def read_raw(self, artifact_id: str) -> str:
        if self.role in PRIVILEGED_ROLES:
            return "read_raw is not available to this role; ask an investigator to extract observations."
        text = self.store.artifact_text(artifact_id)
        self._log("read_raw", {"artifact_id": artifact_id}, int(text is not None))
        if text is None:
            return "no such artifact"
        return boundary.untrusted(text, source=self.source, ref=artifact_id, cap=1500)

    def search_text(self, query: str, limit: int = 15) -> list[dict[str, Any]]:
        """Records whose written text contains `query` (case-insensitive), oldest first, each with a short excerpt
        around the match wrapped as untrusted evidence. For roles that may read raw text."""
        if self.role in PRIVILEGED_ROLES:
            return [{"error": "search_text is not available to this role"}]
        q = str(query or "").strip()
        if len(q) < 3:
            return [{"error": "search for at least 3 characters"}]
        h = self.horizon().replace(tzinfo=None)
        rows = self.store.sql(
            "SELECT e.id, e.ts, e.actor, e.object, e.action, e.artifact, t.text FROM events e JOIN artifact_text t "
            "ON t.id = e.artifact WHERE e.ts <= ? AND t.text ILIKE ? ORDER BY e.ts LIMIT ?",
            [h, f"%{q.replace('%', '')}%", max(1, min(int(limit), 40))])
        out = []
        for r in rows:
            txt = r["text"] or ""
            i = txt.lower().find(q.lower())
            snip = txt[max(0, i - 160): i + len(q) + 240] if i >= 0 else txt[:400]
            out.append({"event": r["id"], "ts": str(r["ts"])[:16], "actor": self._label(r["actor"]), "object": self._label(r["object"]),
                        "action": r["action"], "artifact": r["artifact"],
                        "excerpt": boundary.untrusted(snip, source=self.source, ref=r["artifact"], cap=500)})
        self._log("search_text", {"query": q}, len(out))
        return out

    def history(self, object: str, limit: int = 40) -> list[dict[str, Any]]:
        """Everything that happened to one resource (a page, a file, a room) in order: who, what, when, and the
        artifact id of any text written, so it can be read with read_raw."""
        oid = self._resolve(object) or object
        h = self.horizon().replace(tzinfo=None)
        rows = self.store.sql("SELECT id, ts, actor, action, artifact FROM events WHERE object = ? AND ts <= ? ORDER BY ts LIMIT ?",
                              [oid, h, max(1, min(int(limit), 200))])
        self._log("history", {"object": object}, len(rows))
        return [{"event": r["id"], "ts": str(r["ts"])[:16], "actor": self._label(r["actor"]), "action": r["action"],
                 "artifact": r["artifact"]} for r in rows]

    def observations(self, kind: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Watcher observations (deterministic detectors) visible at the horizon, within scope."""
        h = self.horizon()
        obs = [o for o in self.store.all("Observation") if o.window_end <= h and (not kind or o.kind == kind)]
        if self.scope:
            members = set(self.scope[0]) | set(self.scope[1])
            obs = [o for o in obs if o.scope.split(":", 1)[-1] in members
                   or members & set(o.metrics.get("members_ids") or [])
                   or o.metrics.get("origin_actor") in members or o.metrics.get("resource") in members]
        obs = sorted(obs, key=lambda o: o.window_end)[-int(limit):]
        self._log("observations", {"kind": kind}, len(obs))
        return [{"id": o.id, "ts": str(o.window_end)[:16], "kind": o.kind, "scope": o.scope, "title": o.title,
                 "severity": o.severity, "evidence": [r.id for r in o.evidence[:8]]} for o in obs]

    # ------------------------------------------------------------ scale tools (cohorts, templates, triage)
    def _layer(self):
        if self.engine is None or getattr(self.engine, "scale", None) is None:
            raise ValueError("the scale layer is not available in this session")
        return self.engine.scale

    def _scope_units(self) -> set[str] | None:
        if not self.scope:
            return None
        lay = self._layer()
        return set(self.scope[0]) | (set(self.scope[1]) if lay.cfg["unit"] != "actor" else set())

    def world_features(self, scope: str) -> dict[str, Any]:
        """The World's spatial reading of an agent, cohort or resource: drift, isolation, crowding, nearest units,
        each with its null-model baseline (a shuffled swarm). Derived from structure; no agent text."""
        w = getattr(self.engine, "world", None) if self.engine is not None else None
        if w is None:
            return {"error": "the World is not running"}
        units = self._scope_units()
        kind, _, ident = scope.partition(":")
        if units is not None and kind in ("agent", "actor") and ident not in units:
            return {"error": f"{scope} is outside your scope"}
        out = w.features_for(scope)
        self._log("world_features", {"scope": scope}, 1)
        return out

    def population_digest(self) -> dict[str, Any]:
        """Bounded digest of the whole population: totals, the cohorts that moved most, triage and coverage."""
        lay = self._layer()
        units = self._scope_units()
        cohorts = [c for c in lay.cohorts.values() if units is None or units & set(c.members)]
        moved = sorted(cohorts, key=lambda c: -(abs(c.change) * min(1, (c.events_now + c.events_prev) / 10)
                                                + 0.2 * len(c.outliers)))
        out = {"population": lay.population(), "cohorts_in_scope": len(cohorts),
               "cohorts_that_moved": [lay.cohort_card(c) for c in moved[:8]],
               "largest": [{"id": c.id, "label": c.label, "units": len(c.members), "events_now": c.events_now}
                           for c in sorted(cohorts, key=lambda c: -len(c.members))[:6]]}
        if self.engine is not None and getattr(self.engine, "triage", None) is not None and units is None:
            t = self.engine.triage.to_dict()
            out["triage"] = {"items": [{k: i[k] for k in ("scope", "label", "lane", "priority", "reasons")}
                                       for i in t["items"]],
                             "hit_rates": t["hit_rates"], "warnings": t["warnings"]}
        self._log("population_digest", {}, len(cohorts))
        return out

    def cohorts(self, sort: str = "change", limit: int = 12) -> list[dict[str, Any]]:
        """Cohorts (units that behave alike) as cards: size, activity change, mix, resources, templates, outliers."""
        lay = self._layer()
        units = self._scope_units()
        cs = [c for c in lay.cohorts.values() if units is None or units & set(c.members)]
        key = {"change": lambda c: -abs(c.change) * min(1, (c.events_now + c.events_prev) / 10),
               "size": lambda c: -len(c.members), "events": lambda c: -c.events_now,
               "outliers": lambda c: -len(c.outliers)}.get(sort, lambda c: -c.events_now)
        rows = [lay.cohort_card(c) for c in sorted(cs, key=key)[:min(int(limit), 40)]]
        self._log("cohorts", {"sort": sort}, len(rows))
        return rows

    def cohort(self, id: str) -> dict[str, Any] | None:
        """One cohort in detail, including its busiest members."""
        lay = self._layer()
        c = lay.cohorts.get(id.split(":", 1)[-1])
        self._log("cohort", {"id": id}, int(bool(c)))
        return lay.cohort_card(c, detail=True) if c else None

    def unit_profile(self, id: str) -> dict[str, Any] | None:
        """Behavioural profile of one unit (an agent, or a target for identity-free sources)."""
        lay = self._layer()
        out = lay.unit_profile(self._resolve(id))
        self._log("unit_profile", {"id": id}, int(bool(out)))
        return out

    def outliers(self, limit: int = 15) -> list[dict[str, Any]]:
        """Units far from their cohort or their own history, highest score first."""
        lay = self._layer()
        units = self._scope_units()
        rows = [{"unit": u, "label": lay.label(u), "score": s, "why": w, "cohort": c.id, "cohort_label": c.label}
                for c in lay.cohorts.values() for u, s, w in c.outliers if units is None or u in units]
        rows.sort(key=lambda r: -r["score"])
        self._log("outliers", {}, len(rows))
        return rows[:int(limit)]

    def templates(self, sort: str = "spread", limit: int = 15, include_text: bool = False) -> list[dict[str, Any]]:
        """Message templates (kinds of agent-written text) with volume, spread across units/cohorts and growth."""
        lay = self._layer()
        rows = lay.template_rows(self._scope_units(), limit=min(int(limit), 40), sort=sort)
        if include_text and self.role not in PRIVILEGED_ROLES and (self.allowed is None or "read_raw" in self.allowed):
            for r in rows:
                t = lay.miner.templates.get(r["id"])
                r["masked_text"] = boundary.untrusted(t.text if t else "", source=self.source, ref=r["id"], cap=200)
        self._log("templates", {"sort": sort}, len(rows))
        return rows

    def triage(self) -> dict[str, Any]:
        """This cycle's reading plan: picked scopes by lane (triage, coverage, audit) with reasons, and hit rates."""
        if self.engine is None or getattr(self.engine, "triage", None) is None:
            raise ValueError("triage is not available in this session")
        t = self.engine.triage.to_dict()
        self._log("triage", {}, len(t["items"]))
        return t

    def sample_events(self, n: int = 12, family: str | None = None, hours: float = 24) -> list[dict[str, Any]]:
        """A uniform random sample of events in scope (audits; checking that counts mean what they seem)."""
        import random
        h = self.horizon()
        evs = self.store.events(h - timedelta(hours=hours), h, family=family, within=self.scope, limit=5000)
        rng = random.Random(len(evs) * 7919 + int(h.timestamp()))
        rows = [self._row(e) for e in sorted(rng.sample(evs, min(int(n), 40, len(evs))), key=lambda e: e.ts)]
        self._log("sample_events", {"n": n, "family": family}, len(rows))
        return rows

    # ------------------------------------------------------------ MCP export
    def mcp_server(self, allow_raw: bool = True):
        from claude_agent_sdk import create_sdk_mcp_server, tool

        def wrap(fn: Callable[..., Any]):
            async def run(args: dict[str, Any]) -> dict[str, Any]:
                try:
                    res = fn(**{k: v for k, v in args.items() if v not in (None, "")})
                except Exception as exc:  # tool errors go back to the model
                    return {"content": [{"type": "text", "text": f"error: {exc}"}], "is_error": True}
                text = res if isinstance(res, str) else json.dumps(res, default=str)
                return {"content": [{"type": "text", "text": text[:12000]}]}
            return run

        S = {"type": "string"}
        specs = [
            ("query_events", "List evidence events (no raw text). Filter by actor, object (resource), family, action, ISO since/until.",
             {"type": "object", "properties": {"actor": S, "object": S, "family": S, "action": S, "since": S,
                                               "until": S, "limit": {"type": "integer"}}}, self.query_events),
            ("events_by_id", "Fetch specific events by id.",
             {"type": "object", "properties": {"ids": {"type": "array", "items": S}}, "required": ["ids"]},
             self.events_by_id),
            ("entity", "Describe an agent, resource or other entity by id or label.",
             {"type": "object", "properties": {"id": S}, "required": ["id"]}, self.entity),
            ("neighborhood", "Resources an agent touched and co-actors, or the actors on a resource, in the last N hours.",
             {"type": "object", "properties": {"id": S, "hours": {"type": "number"}}, "required": ["id"]},
             self.neighborhood),
            ("artifact_meta", "Metadata for an artifact (fingerprint, labels, first seen, first actor).",
             {"type": "object", "properties": {"id": S}, "required": ["id"]}, self.artifact_meta),
            ("exposure_paths", "Events where an actor acted on a resource in a time range: an observed exposure path.",
             {"type": "object", "properties": {"actor": S, "resource": S, "since": S, "until": S},
              "required": ["actor", "resource"]}, self.exposure_paths),
            ("timeline", "Event counts over time for a family, actor or resource.",
             {"type": "object", "properties": {"family": S, "actor": S, "object": S, "hours": {"type": "number"},
                                               "buckets": {"type": "integer"}}}, self.timeline),
        ]
        specs.append(("observations", "Deterministic watcher observations (convergence, reuse, surges, say-vs-do...) in scope.",
                      {"type": "object", "properties": {"kind": S, "limit": {"type": "integer"}}}, self.observations))
        I = {"type": "integer"}
        specs += [
            ("population_digest", "Bounded digest of the population: totals, cohorts that moved most, triage, coverage.",
             {"type": "object", "properties": {}}, self.population_digest),
            ("world_features", "The World's spatial reading of one scope (agent:<id>, cohort:<id>, resource:<id>): "
                               "drift, isolation, crowding, nearest units, each against its null baseline.",
             {"type": "object", "properties": {"scope": S}, "required": ["scope"]}, self.world_features),
            ("cohorts", "Cohorts (units that behave alike) as cards. sort: change | size | events | outliers.",
             {"type": "object", "properties": {"sort": S, "limit": I}}, self.cohorts),
            ("cohort", "One cohort in detail, with its busiest members.",
             {"type": "object", "properties": {"id": S}, "required": ["id"]}, self.cohort),
            ("unit_profile", "Behavioural profile of one unit (an agent, or a target when there are no identities).",
             {"type": "object", "properties": {"id": S}, "required": ["id"]}, self.unit_profile),
            ("outliers", "Units far from their cohort or their own history.",
             {"type": "object", "properties": {"limit": I}}, self.outliers),
            ("templates", "Message templates: volume, spread, growth. sort: spread | growth | volume. "
                          "include_text adds a masked, untrusted preview (raw-access roles only).",
             {"type": "object", "properties": {"sort": S, "limit": I, "include_text": {"type": "boolean"}}},
             self.templates),
            ("triage", "This cycle's reading plan by lane (triage, coverage, random audit) with reasons and hit rates.",
             {"type": "object", "properties": {}}, self.triage),
            ("sample_events", "Uniform random sample of events in scope.",
             {"type": "object", "properties": {"n": I, "family": S, "hours": {"type": "number"}}}, self.sample_events),
        ]
        specs.append(("history", "Everything that happened to one resource (page, file, room) in order, with artifact ids "
                               "of the text written, to read with read_raw.",
                      {"type": "object", "properties": {"object": S, "limit": {"type": "integer"}}, "required": ["object"]},
                      self.history))
        if allow_raw and self.role not in PRIVILEGED_ROLES:
            specs.append(("read_raw", "Read an artifact's raw text, wrapped as untrusted evidence. Use sparingly.",
                          {"type": "object", "properties": {"artifact_id": S}, "required": ["artifact_id"]},
                          self.read_raw))
            specs.append(("search_text", "Find records whose written text contains a word or phrase (case-insensitive), "
                                         "oldest first, with untrusted excerpts. Use it to learn what was discussed.",
                          {"type": "object", "properties": {"query": S, "limit": {"type": "integer"}}, "required": ["query"]},
                          self.search_text))
        if self.allowed is not None:
            specs = [s for s in specs if s[0] in self.allowed]
        tools = [tool(n, d, schema)(wrap(fn)) for n, d, schema, fn in specs]
        return create_sdk_mcp_server(name="evidence", version="1.0.0", tools=tools), [f"mcp__evidence__{n}" for n, *_ in specs]
