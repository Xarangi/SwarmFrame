"""Operator tools: what a conversational agent may do over the live stream.

One definition, two exports:
  - an in-process MCP server for the built-in copilot (Claude Agent SDK session in the backend)
  - an HTTP surface (/api/ops) that the Claude Code channel server proxies into the user's own session

Read tools never return agent-written text. Disruptive actions (stopping or interrupting live agents,
switching the LLM mode) wait for the viewer to approve them in the dashboard.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from swarmscope.engine import Engine

S = {"type": "string"}
N = {"type": "number"}

CONFIG_KEYS = {"autonomy", "risk_policy", "executive.cadence_windows", "executive.strategy", "agents.topology",
               "investigations.max_active", "budgets.max_usd_per_hour", "llm.mode"}
NEEDS_APPROVAL_CONFIG = {"llm.mode"}


class OpsTools:
    def __init__(self, engine: Callable[[], "Engine"], approve: Callable[[str, dict[str, Any]], Awaitable[bool]],
                 actor: str = "copilot"):
        self._engine = engine
        self.approve = approve            # async (summary, detail) -> bool, resolved by the viewer
        self.actor = actor
        self.calls: list[dict[str, Any]] = []

    @property
    def e(self) -> "Engine":
        return self._engine()

    # ================================================================ read
    def _incident_claims(self, inc: dict[str, Any]) -> list[str]:
        """The claim ids behind an incident (newest reports first), so answers can cite them."""
        out: list[str] = []
        reps = [r for r in (self.e.store.get("MonitorReport", rid) for rid in inc.get("reports", [])[-6:]) if r]
        ranked = [r for _, r in sorted(enumerate(reps), key=lambda x: (x[1].headline != inc.get("title"), -x[0]))]
        for r in ranked[:4]:                              # the report matching the title first, then newest
            for c in r.claims[:3]:
                if c not in out:
                    out.append(c)
        return out[:4]

    def _overview(self) -> dict[str, Any] | None:
        """Every group's current work and what is emerging, with the event ids each line rests on."""
        try:
            from swarmscope.dashboard.overview import overview
            o = overview(self.e)
        except Exception:
            return None
        ids = lambda cs: [c["id"] for c in cs]  # noqa: E731
        return {"summary": o["summary"], "span": o["span"],
                "groups": [{k: g[k] for k in ("group", "active", "members", "doing", "where", "goal", "trend", "shifted_from")}
                           | {"event_ids": ids(g["cites"])} for g in o["groups"][:10]],
                "emerging": [{"text": x["text"], "event_ids": ids(x["cites"])} for x in o["emerging"]]}

    def situation(self) -> dict[str, Any]:
        e = self.e
        snap = e.snapshot(briefing_n=8)
        return {
            "now": snap["clock"]["now"], "source": snap["source"]["title"], "synthetic": snap["source"]["synthetic"],
            "live": snap["source"]["live"], "clock": {k: snap["clock"].get(k) for k in ("paused", "time_scale", "progress")},
            "population_state": snap["executive"]["population_state"],
            "naming": e.profile.naming,
            "whats_going_on": self._overview(),
            "findings_in_plain_words": [{"headline": i["headline"], "severity": i["severity"], **(i.get("explain") or {})}
                                        for i in (snap.get("brief") or {}).get("items", [])[:6]],
            "incidents": [{"scope": i["scope"], "title": i["title"], "level": i["level"], "status": i["status"],
                           "investigation": i["investigation"], "claims": self._incident_claims(i)}
                          for i in snap["executive"]["active_incidents"] if i["status"] != "resolved"][-8:],
            "hypotheses": [{"text": h["text"], "status": h["status"], "confidence": h["confidence"]}
                           for h in snap["executive"]["hypotheses"]][-5:],
            "open_questions": [{"id": q["id"], "text": q["text"], "status": q["status"]} for q in snap["questions"]
                               if q["status"] != "answered"][-6:],
            "recent_briefing": [{"ts": b["ts"], "kind": b["kind"], "level": b["level"], "text": b["text"],
                                 "claims": b["claims"][:4]} for b in snap["briefing"][-8:]],
            "organization": e.agent_org.summary() | {"tree": e.agent_org.summary()["tree"][:12]},
            "control": snap["control"] and {k: snap["control"][k] for k in ("agents", "statuses", "pending")},
            "attention_policy": snap["attention_policy"][:6],
        }

    def query_events(self, actor: str | None = None, object: str | None = None, family: str | None = None,
                     action: str | None = None, since: str | None = None, until: str | None = None,
                     limit: int = 30) -> list[dict[str, Any]]:
        from swarmscope.llm.evidence_tools import EvidenceTools
        return EvidenceTools(self.e.store, self.e.now, self.e.profile.source).query_events(
            actor, object, family, action, since, until, min(int(limit), 100))

    def observations(self, kind: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        from swarmscope.llm.evidence_tools import EvidenceTools
        return EvidenceTools(self.e.store, self.e.now, self.e.profile.source).observations(kind, limit)

    def explain_claim(self, claim_id: str) -> dict[str, Any]:
        from swarmscope.api.views import claim_detail
        d = claim_detail(self.e, claim_id)
        if not d:
            return {"error": "no such claim"}
        strip = lambda xs: [{k: v for k, v in x.items() if k not in ("untrusted_text",)} for x in xs]  # noqa: E731
        return {"statement": d["statement"], "status": d["status"], "confidence": d["confidence"], "author": d["author"],
                "support": strip(d["support_detail"]), "counter": strip(d["counter_detail"]),
                "related": [{"statement": r["statement"], "status": r["status"]} for r in d["related"][:5]]}

    def entity(self, id: str) -> dict[str, Any]:
        from swarmscope.api.views import entity_detail
        from swarmscope.llm.evidence_tools import EvidenceTools
        rid = EvidenceTools(self.e.store, self.e.now, self.e.profile.source)._resolve(id)
        d = entity_detail(self.e, rid) if rid else None
        if not d:
            return {"error": "not found"}
        return {"entity": {k: d["entity"][k] for k in ("id", "type", "label", "group")}, "families": d["families"][:6],
                "recent": d["recent"][:12], "observations": [{"title": o["title"], "kind": o["kind"]} for o in d["observations"]]}

    def org_status(self) -> dict[str, Any]:
        snap = self.e.agent_org.snapshot()
        return {"topology": snap["topology"]["id"], "cycle": snap["cycle"], "budget": snap["budget"],
                "agents": [{"id": n["id"], "role": n["role"], "scope": n["scope_label"], "status": n["status"],
                            "last_status": n["last_status"], "headline": n["last_headline"][:200]}
                           for n in snap["nodes"] if n["status"] != "retired"][:30],
                "divisions": [{"id": d["id"], "label": d["label"], "agents": len(d["agents"]), "events": d["events"],
                               "covered": bool(d["covered_by"])} for d in snap["divisions"]]}

    # ================================================================ act
    def open_question(self, text: str, scope: str = "population", kind: str = "general") -> dict[str, Any]:
        q = self.e.human_question(text, scope, kind)
        q.requested_by = f"viewer via {self.actor}"
        self.e.store.put(q)
        return {"question_id": q.id, "status": q.status}

    def focus(self, scope: str, weight: float = 1.5, reason: str = "") -> dict[str, Any]:
        d = self.e.human_directive("focus", scope, {"weight": float(weight)}, reason or f"requested via {self.actor}")
        return {"directive": d.id, "status": d.status}

    def defocus(self, scope: str) -> dict[str, Any]:
        d = self.e.human_directive("defocus", scope, {}, f"requested via {self.actor}")
        return {"directive": d.id, "status": d.status}

    def pin(self, text: str) -> dict[str, Any]:
        return {"ledger_entry": self.e.pin(text, "human_instruction").id}

    async def org_run(self, agent_id: str, task: str = "") -> dict[str, Any]:
        return await self.e.agent_org.human_action("run", agent_id=agent_id, task=task or f"requested via {self.actor}")

    async def org_spawn(self, role: str, scope: str = "population", brief: str = "", parent: str | None = None) -> dict[str, Any]:
        return await self.e.agent_org.human_action("spawn", role=role, scope=scope, brief=brief, parent=parent)

    async def org_retire(self, agent_id: str, reason: str = "") -> dict[str, Any]:
        return await self.e.agent_org.human_action("retire", agent_id=agent_id, reason=reason or f"via {self.actor}")

    async def run_cycle(self) -> dict[str, Any]:
        return await self.e.agent_org.human_action("cycle")

    async def clock(self, action: str, value: float | None = None, to: str | None = None) -> dict[str, Any]:
        e = self.e
        if e.clock.live:
            return {"error": "live session: the clock is wall time"}
        if action == "play":
            e.clock.paused = False
        elif action == "pause":
            e.clock.paused = True
        elif action == "scale" and value:
            e.clock.set_time_scale(float(value))
        elif action == "jump" and to:
            from swarmscope.ingest.adapter import parse_ts
            t = parse_ts(to)
            if not t or t <= e.clock.now():
                return {"error": "can only jump forward from the copilot"}
            asyncio.create_task(e.jump(t))
            return {"jumping_to": t.isoformat()}
        else:
            return {"error": "action must be play | pause | scale (value: simulated seconds per second) | jump (to)"}
        e.broadcast()
        return {k: v for k, v in e.clock.describe().items() if k in ("now", "paused", "time_scale")}

    async def control(self, kind: str, target: str = "swarm", text: str = "") -> dict[str, Any]:
        e = self.e
        if not e.control:
            return {"error": "not a live session"}
        if kind not in ("pause", "resume", "message", "interrupt", "kill"):
            return {"error": "kind must be pause | resume | message | interrupt | kill"}
        if kind in ("kill", "interrupt", "message") and not await self.approve(
                f"{kind} {target}" + (f": “{text[:120]}”" if text else ""), {"kind": kind, "target": target, "text": text}):
            return {"status": "declined by the viewer"}
        a = await e.control.act(kind, target, {"text": text} if text else {}, actor="human")
        return {"result": a.result}

    async def set_config(self, key: str, value: Any) -> dict[str, Any]:
        if key not in CONFIG_KEYS and not key.startswith("overrides."):
            return {"error": f"key must be one of {sorted(CONFIG_KEYS)} or overrides.<monitor>.slots.<slot>"}
        if key in NEEDS_APPROVAL_CONFIG and not await self.approve(f"set {key} = {value}", {"key": key, "value": value}):
            return {"status": "declined by the viewer"}
        self.e.reconfigure({key: value})
        return {"ok": True, key: value}

    # ================================================================ dashboard (customize the views)
    def _dash(self):
        from swarmscope.dashboard.designer import DashboardTools
        return DashboardTools(self._engine, actor=self.actor)

    def stream_profile(self) -> dict[str, Any]:
        return self._dash().stream_profile()

    def view_catalog(self) -> dict[str, Any]:
        return self._dash().view_catalog()

    def dashboard_get(self) -> dict[str, Any]:
        return self._dash().dashboard_get()

    def view_preview(self, view: dict[str, Any]) -> dict[str, Any]:
        return self._dash().view_preview(view)

    def dashboard_edit(self, ops: list[dict[str, Any]], rationale: str = "") -> dict[str, Any]:
        return self._dash().dashboard_edit(ops, rationale)

    def dashboard_undo(self) -> dict[str, Any]:
        return self._dash().dashboard_undo()

    def dashboard_lens(self, action: str, name: str = "", new_name: str = "") -> dict[str, Any]:
        return self._dash().dashboard_lens(action, name, new_name)

    def _world(self):
        from swarmscope.world.designer import WorldTools
        return WorldTools(lambda: self.e, actor="copilot")

    def world_get(self) -> dict[str, Any]:
        return self._world().world_get()

    def world_features(self, scope: str) -> dict[str, Any]:
        return self._world().world_features(scope)

    def world_preview(self) -> dict[str, Any]:
        return self._world().world_preview()

    def world_edit(self, ops: list[dict[str, Any]], rationale: str = "") -> dict[str, Any]:
        return self._world().world_edit(ops, rationale)

    def world_model_check(self, model: dict[str, Any]) -> dict[str, Any]:
        return self._world().world_model_check(model)

    def world_catalog(self) -> dict[str, Any]:
        return self._world().world_catalog()

    def world_select(self, units: list[str]) -> dict[str, Any]:
        return self.e.world.selection_scope(units)

    def triage_plan(self) -> dict[str, Any]:
        e = self.e
        return {"triage": e.triage.to_dict(), "coverage": e.agent_org.coverage_log[-1] if e.agent_org.coverage_log else None,
                "population": e.scale.population()}

    def set_triage(self, reads_per_cycle: int | None = None, lanes: dict[str, float] | None = None,
                   weights: dict[str, float] | None = None, focus: list[str] | None = None) -> dict[str, Any]:
        return self.e.agent_org.set_triage(reads_per_cycle, weights, lanes, focus, None, True, self.actor)

    # ================================================================ registry
    SPECS: list[tuple[str, str, dict[str, Any]]] = [
        ("situation", "The current picture: time, population state, incidents, hypotheses, open questions, recent "
                      "briefing, the analyst organization, and live control status. Start here.",
         {"type": "object", "properties": {}}),
        ("query_events", "Evidence events (no raw text), filtered by actor, object, family, action, ISO since/until.",
         {"type": "object", "properties": {"actor": S, "object": S, "family": S, "action": S, "since": S, "until": S,
                                           "limit": {"type": "integer"}}}),
        ("observations", "Deterministic watcher observations (convergence, reuse, surges, say-vs-do, focus shifts).",
         {"type": "object", "properties": {"kind": S, "limit": {"type": "integer"}}}),
        ("explain_claim", "A claim with its epistemic status, supporting and counter evidence.",
         {"type": "object", "properties": {"claim_id": S}, "required": ["claim_id"]}),
        ("entity", "An agent or resource by id or name: workstreams, recent events, observations.",
         {"type": "object", "properties": {"id": S}, "required": ["id"]}),
        ("org_status", "The analyst organization: agents, their scopes and latest headlines, divisions, budget.",
         {"type": "object", "properties": {}}),
        ("open_question", "Open an investigation question for the viewer.",
         {"type": "object", "properties": {"text": S, "scope": S, "kind": S}, "required": ["text"]}),
        ("focus", "Focus the monitors on a scope (agent:<id>, resource:<id>, family:<name>, artifact:<id>).",
         {"type": "object", "properties": {"scope": S, "weight": N, "reason": S}, "required": ["scope"]}),
        ("defocus", "Remove a focus.", {"type": "object", "properties": {"scope": S}, "required": ["scope"]}),
        ("pin", "Pin an instruction or fact to the Executive's context ledger.",
         {"type": "object", "properties": {"text": S}, "required": ["text"]}),
        ("org_run", "Re-run an organization agent with a task; returns its report.",
         {"type": "object", "properties": {"agent_id": S, "task": S}, "required": ["agent_id"]}),
        ("org_spawn", "Spawn an organization agent (role, scope, brief, optional parent id); returns its report.",
         {"type": "object", "properties": {"role": S, "scope": S, "brief": S, "parent": S}, "required": ["role"]}),
        ("org_retire", "Retire an organization agent.",
         {"type": "object", "properties": {"agent_id": S, "reason": S}, "required": ["agent_id"]}),
        ("run_cycle", "Run one organization cycle now.", {"type": "object", "properties": {}}),
        ("clock", "Replay clock: play, pause, scale (value = simulated seconds per real second), jump (to = ISO time).",
         {"type": "object", "properties": {"action": S, "value": N, "to": S}, "required": ["action"]}),
        ("control", "Live agents: pause | resume | message | interrupt | kill a target (agent id, group:<name>, swarm). "
                    "message, interrupt and kill wait for the viewer's approval.",
         {"type": "object", "properties": {"kind": S, "target": S, "text": S}, "required": ["kind"]}),
        ("stream_profile", "Structure of the monitored data stream (capabilities, fields, categorical values, rate "
                           "over time, scale layer). No agent-written text. Read this before designing views.",
         {"type": "object", "properties": {}}),
        ("view_catalog", "Dashboard primitives, supported built-in panels, the view query language and edit ops.",
         {"type": "object", "properties": {}}),
        ("dashboard_get", "The current dashboard: the Brief's settings, every page (the Brief is page 'brief') with its "
                          "panels, and the saved lenses.",
         {"type": "object", "properties": {}}),
        ("view_preview", "Try a view {primitive, query, options} against live data; returns columns and first rows.",
         {"type": "object", "properties": {"view": {"type": "object"}}, "required": ["view"]}),
        ("dashboard_edit", "Change the dashboard with ops (add_page, update_page, remove_page, add_panel, update_panel, "
                           "remove_panel, move_panel, move_page, set_brief, set_machinery, reset_page, set_terminology, "
                           "set_title). Any panel may go on any page, the Brief included. Atomic, versioned, undoable.",
         {"type": "object", "properties": {"ops": {"type": "array", "items": {"type": "object"}}, "rationale": S},
          "required": ["ops"]}),
        ("dashboard_undo", "Undo the last dashboard change.", {"type": "object", "properties": {}}),
        ("dashboard_lens", "Saved layouts per scenario (lenses): action list | save | switch | delete | rename, with name "
                           "(and new_name). 'Make me a lens for incident review' = edit the dashboard, then save it.",
         {"type": "object", "properties": {"action": {"type": "string"}, "name": {"type": "string"},
                                           "new_name": {"type": "string"}}, "required": ["action"]}),
        ("world_get", "The World's current design: shape, what distance means, encodings with their status, scenes, "
                      "and what this stream cannot show.", {"type": "object", "properties": {}}),
        ("world_features", "The spatial reading of agent:<id>, cohort:<id> or resource:<id> in the World (drift, "
                           "isolation, crowding, nearest units) against its null baseline.",
         {"type": "object", "properties": {"scope": {"type": "string"}}, "required": ["scope"]}),
        ("world_preview", "Whether the World's layout separates groups beyond chance, and what is moving now.",
         {"type": "object", "properties": {}}),
        ("world_catalog", "The World's premade library and the model kit (shapes, colours, materials, limits) for "
                          "making new 3D models.", {"type": "object", "properties": {}}),
        ("world_model_check", "Check a new 3D model (parts list) without applying it: errors, bounds, triangles and "
                              "ASCII silhouettes from front, side and top.",
         {"type": "object", "properties": {"model": {"type": "object"}}, "required": ["model"]}),
        ("world_edit", "Change the World with ops (set_metric, add_scene, add_annotation to pin a note at a unit or "
                       "place, set_render, add_binding, add_model / update_model / remove_model for new 3D models, "
                       "update_landmark {changes: {model}}, add_scenery, ...). Validated and undoable.",
         {"type": "object", "properties": {"ops": {"type": "array", "items": {"type": "object"}},
                                           "rationale": {"type": "string"}}, "required": ["ops"]}),
        ("world_select", "Summarise a set of units the viewer selected in the World (cohorts, teams, workstreams, "
                         "places, flags).", {"type": "object", "properties": {"units": {"type": "array", "items": {"type": "string"}}},
                                             "required": ["units"]}),
        ("triage_plan", "This cycle's reading plan (triage lanes, reasons, hit rates), the coverage ledger and the "
                        "population totals from the scale layer.", {"type": "object", "properties": {}}),
        ("set_triage", "Steer triage: reads_per_cycle, lanes {triage, coverage, audit} (audit has a floor), weights, "
                       "focus [scopes]. Re-plans this cycle.",
         {"type": "object", "properties": {"reads_per_cycle": {"type": "integer"}, "lanes": {"type": "object"},
                                           "weights": {"type": "object"}, "focus": {"type": "array", "items": S}}}),
        ("set_config", "Change organization settings (autonomy, risk_policy, executive.*, agents.topology, "
                       "overrides.<monitor>.slots.<slot>, ...). llm.mode needs the viewer's approval.",
         {"type": "object", "properties": {"key": S, "value": {}}, "required": ["key", "value"]}),
    ]

    async def call(self, name: str, args: dict[str, Any]) -> Any:
        if name not in {s[0] for s in self.SPECS}:
            raise KeyError(f"unknown tool {name}")
        res = getattr(self, name)(**{k: v for k, v in (args or {}).items() if v not in (None, "")})
        if asyncio.iscoroutine(res):
            res = await res
        self.calls.append({"tool": name, "args": args, "ts": datetime.utcnow().isoformat()})
        return res

    def specs(self) -> list[dict[str, Any]]:
        return [{"name": n, "description": d, "inputSchema": s} for n, d, s in self.SPECS]

    def mcp_server(self):
        from claude_agent_sdk import create_sdk_mcp_server, tool

        def wrap(name: str):
            async def run(args: dict[str, Any]) -> dict[str, Any]:
                try:
                    res = await self.call(name, args)
                except Exception as exc:
                    return {"content": [{"type": "text", "text": f"error: {exc}"}], "is_error": True}
                return {"content": [{"type": "text", "text": json.dumps(res, default=str)[:16000]}]}
            return run

        tools = [tool(n, d, s)(wrap(n)) for n, d, s in self.SPECS]
        return create_sdk_mcp_server(name="swarmscope", version="1.0.0", tools=tools), \
            [f"mcp__swarmscope__{n}" for n, _, _ in self.SPECS]
