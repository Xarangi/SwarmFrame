"""Org tools: how an agent builds and steers its own team. Exported as the in-process MCP server "org".

Every structural tool is checked against the topology (can_spawn, max_agents, max_depth, budget).
Spawning and running children awaits them and returns their structured reports; the calling agent
gives up its concurrency slot while it waits, so nesting cannot deadlock.
"""
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from swarmscope.agents.runners import org_status

if TYPE_CHECKING:
    from swarmscope.agents.runtime import AgentNode, AgentOrg, RunContext


class OrgTools:
    def __init__(self, org: "AgentOrg", caller: "AgentNode", ctx: "RunContext | None" = None):
        self.org, self.caller, self.ctx = org, caller, ctx

    def _log(self, name: str) -> None:
        if self.ctx is not None:
            self.ctx.org_calls.append(f"org.{name}")

    # ------------------------------------------------------------ read
    def org_status(self) -> dict[str, Any]:
        self._log("org_status")
        return org_status(self.org, self.caller)

    def list_roles(self) -> list[dict[str, Any]]:
        self._log("list_roles")
        t = self.org.topology
        return [{"role": r, "title": t.roles[r].title, "description": t.roles[r].description, "scope": t.roles[r].scope,
                 "allowed": self.org.can_spawn(self.caller, r)[0]} for r in t.roles[self.caller.role].can_spawn]

    def get_report(self, agent_id: str) -> dict[str, Any]:
        self._log("get_report")
        n = self.org.nodes.get(agent_id)
        return self.org.compact(n) if n and n.last_report else {"error": "no report yet"}

    # ------------------------------------------------------------ act
    async def spawn_agent(self, role: str, scope: str = "population", brief: str = "", run_now: bool = True) -> dict[str, Any]:
        self._log("spawn_agent")
        ok, why = self.org.can_spawn(self.caller, role)
        if not ok:
            return {"error": why}
        n = self.org.spawn(role, scope, brief, self.caller, self.caller.id)
        if not run_now:
            return {"agent_id": n.id, "status": "spawned"}
        async with self.org.yielded(self.caller):
            return await self.org.run(n, brief, self.caller.id)

    async def spawn_agents(self, agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Spawn several agents and run them in parallel."""
        self._log("spawn_agents")
        nodes, out = [], []
        for spec in agents[:12]:
            ok, why = self.org.can_spawn(self.caller, spec.get("role", ""))
            if not ok:
                out.append({"error": why, "spec": spec})
                continue
            nodes.append(self.org.spawn(spec["role"], spec.get("scope") or "population", spec.get("brief", ""),
                                        self.caller, self.caller.id))
        async with self.org.yielded(self.caller):
            out += await asyncio.gather(*(self.org.run(n, n.brief, self.caller.id) for n in nodes))
        return out

    async def run_agent(self, agent_id: str, task: str = "") -> dict[str, Any]:
        self._log("run_agent")
        n = self.org.nodes.get(agent_id)
        if not n or n.status == "retired":
            return {"error": "no such active agent"}
        async with self.org.yielded(self.caller):
            return await self.org.run(n, task, self.caller.id)

    def retire_agent(self, agent_id: str, reason: str = "") -> dict[str, Any]:
        self._log("retire_agent")
        n = self.org.nodes.get(agent_id)
        if not n or agent_id == self.org.root_id:
            return {"error": "cannot retire that agent"}
        self.org.retire(agent_id, reason or f"retired by {self.caller.id}", self.caller.id)
        return {"ok": True}

    def split_division(self, division_id: str) -> dict[str, Any]:
        self._log("split_division")
        parts = self.org.split_division(division_id, self.caller.id)
        return {"divisions": [{"id": d.id, "label": d.label, "agents": len(d.agents)} for d in parts]}

    def merge_divisions(self, division_ids: list[str], label: str = "") -> dict[str, Any]:
        self._log("merge_divisions")
        d = self.org.merge_divisions(division_ids, label or None, self.caller.id)
        return {"division": {"id": d.id, "label": d.label, "agents": len(d.agents)}}

    def define_division(self, label: str, agent_ids: list[str], resource_ids: list[str] | None = None) -> dict[str, Any]:
        self._log("define_division")
        d = self.org.define_division(label, agent_ids, resource_ids, self.caller.id)
        return {"division": {"id": d.id, "label": d.label, "agents": len(d.agents)}}

    def ask_question(self, text: str, scope: str = "population", kind: str = "general") -> dict[str, Any]:
        self._log("ask_question")
        q = self.org.engine.human_question(text, scope, kind)
        q.requested_by = self.caller.title
        self.org.engine.store.put(q)
        return {"question_id": q.id}

    def set_triage(self, reads_per_cycle: int | None = None, weights: dict[str, float] | None = None,
                   lanes: dict[str, float] | None = None, focus: list[str] | None = None,
                   coverage_every_cycles: int | None = None, reallocate: bool = False) -> dict[str, Any]:
        """Steer the triage allocator: reading budget, priority weights, lane shares, focus scopes."""
        self._log("set_triage")
        return self.org.set_triage(reads_per_cycle, weights, lanes, focus, coverage_every_cycles, reallocate,
                                   self.caller.id)

    # ------------------------------------------------------------ MCP
    def cases(self) -> dict[str, Any]:
        """The open cases (tracked findings) in the caller's scope, with level, views and history."""
        self._log("cases")
        eng = self.org.engine
        st = eng.agent_org.scope_tuple(self.caller.scope) if self.caller.scope != "population" else None
        out = []
        for inc in eng.cases().open_cases():
            if st is not None:
                a, r = st
                kind, _, ident = inc.scope.partition(":")
                if inc.scope != self.caller.scope and ident not in a and ident not in r:
                    continue
            out.append({"id": inc.id, "scope": inc.scope, "title": inc.title, "level": inc.level.value,
                        "status": inc.status, "views": inc.views, "pending_level": inc.pending_level,
                        "acknowledged": bool(inc.acknowledged),
                        "history": [{"ts": h.ts.isoformat(), "level": h.level, "by": h.by, "reason": h.reason,
                                     "held": h.held} for h in inc.history[-6:]]})
        return {"cases": out, "budget": eng.cases().summary(eng.window_len)}

    def escalate_finding(self, scope: str, title: str, level: str = "INVESTIGATE", reason: str = "",
                         evidence_ids: list[str] | None = None, case_id: str | None = None) -> dict[str, Any]:
        """Track a finding as a case, or raise an existing case's level. Levels: INVESTIGATE, ALERT, PAGE.
        ALERT and above need a second independent view and existing evidence, and draw on the cycle's authority
        budget; otherwise the case is held at INVESTIGATE with the reason, and promoted when the second view arrives."""
        self._log("escalate_finding")
        lvl = str(level).upper()
        if lvl not in ("INVESTIGATE", "ALERT", "PAGE"):
            raise ValueError("level must be INVESTIGATE, ALERT or PAGE")
        return self.org.engine.escalate(scope=scope, title=str(title)[:200], level=lvl, by=self.caller.title,
                                        view=f"role:{self.caller.role}", reason=str(reason)[:400],
                                        evidence=list(evidence_ids or [])[:12], case_id=case_id)

    def log_decision(self, text: str, kind: str = "note", target: str = "") -> dict[str, Any]:
        """Write one line to the delegation log: why you did or did not delegate, or why you changed course."""
        self._log("log_decision")
        e = self.org.engine.delegations.record(kind="note", by=self.caller.title, role=self.caller.role, node=self.caller.id,
                                               target=target, why=str(text)[:500], extra={"note_kind": str(kind)[:40]})
        return {"logged": e["ts"]}

    def delegations(self, n: int = 30) -> dict[str, Any]:
        """Your own recent delegations and notes (what you asked whom, and what came back)."""
        self._log("delegations")
        return {"entries": self.org.engine.delegations.recent(int(n), node=self.caller.id)}

    def propose_role(self, id: str, title: str, prompt: str, tools: list[str], reason: str, description: str = "",
                     kind: str = "generic", model: str = "claude-sonnet-5-5", effort: str = "low", max_turns: int = 8,
                     output: str = "finding", scope: str = "any", raw_access: bool = False, standing: bool = False,
                     question_kinds: list[str] | None = None) -> dict[str, Any]:
        """Propose a new reading role. Inside the envelope (tools within the director's, no raw access, model within
        the cap) it applies at the end of this cycle; otherwise it waits for a person on the Brief."""
        self._log("propose_role")
        p = self.org.engine.approvals.add("role", {"id": id, "title": title, "prompt": prompt, "tools": list(tools),
                                                   "description": description, "kind": kind, "model": model,
                                                   "effort": effort, "max_turns": int(max_turns), "output": output,
                                                   "scope": scope, "raw_access": bool(raw_access),
                                                   "standing": bool(standing), "question_kinds": list(question_kinds or []),
                                                   "reason": reason}, self.caller.title, [reason], title=title)
        return {"proposal": p.id, "status": p.status, "note": p.note}

    def propose_change(self, changes: dict[str, Any], reason: str) -> dict[str, Any]:
        """Propose a change to the team's grammar blocks: partition, levels, standing, questions, cadence, human,
        authority, triage. Partition, levels, the human contract and budgets wait for a person; the rest apply."""
        self._log("propose_change")
        p = self.org.engine.approvals.add("change", dict(changes), self.caller.title, [reason], title="refine the team")
        return {"proposal": p.id, "status": p.status, "note": p.note}

    def mcp_server(self, names: list[str]):
        from claude_agent_sdk import create_sdk_mcp_server, tool
        S = {"type": "string"}
        specs = {
            "org_status": ("Divisions, active agents, their latest headlines and recommendations, and budget left.",
                           {"type": "object", "properties": {}}),
            "list_roles": ("Roles you may spawn, with descriptions and whether caps allow it now.",
                           {"type": "object", "properties": {}}),
            "get_report": ("Latest structured report of an agent.", {"type": "object", "properties": {"agent_id": S},
                                                                     "required": ["agent_id"]}),
            "spawn_agent": ("Spawn one agent with a role, a scope (population | division:<id> | agent:<id> | "
                            "resource:<id>) and a brief. Runs it now and returns its structured report.",
                            {"type": "object", "properties": {"role": S, "scope": S, "brief": S,
                                                              "run_now": {"type": "boolean"}}, "required": ["role", "scope", "brief"]}),
            "spawn_agents": ("Spawn several agents and run them in parallel; returns their reports.",
                             {"type": "object", "properties": {"agents": {"type": "array", "items": {
                                 "type": "object", "properties": {"role": S, "scope": S, "brief": S},
                                 "required": ["role", "scope", "brief"]}}}, "required": ["agents"]}),
            "run_agent": ("Re-run an existing agent with a new task; returns its report.",
                          {"type": "object", "properties": {"agent_id": S, "task": S}, "required": ["agent_id"]}),
            "retire_agent": ("Retire an agent (and its sub-agents).",
                             {"type": "object", "properties": {"agent_id": S, "reason": S}, "required": ["agent_id"]}),
            "split_division": ("Split a division into sub-communities; its agents are re-spawned per part.",
                               {"type": "object", "properties": {"division_id": S}, "required": ["division_id"]}),
            "merge_divisions": ("Merge divisions into one.",
                                {"type": "object", "properties": {"division_ids": {"type": "array", "items": S}, "label": S},
                                 "required": ["division_ids"]}),
            "define_division": ("Define a division from agent ids (or labels) and optional resource ids.",
                                {"type": "object", "properties": {"label": S, "agent_ids": {"type": "array", "items": S},
                                                                  "resource_ids": {"type": "array", "items": S}},
                                 "required": ["label", "agent_ids"]}),
            "set_triage": ("Steer what gets read: reads_per_cycle, weights {severity, change, novelty, debt, focus}, "
                           "lanes {triage, coverage, audit} (audit has a floor), focus [scopes], coverage_every_cycles. "
                           "reallocate=true re-plans this cycle now and returns the plan.",
                           {"type": "object", "properties": {
                               "reads_per_cycle": {"type": "integer"}, "weights": {"type": "object"},
                               "lanes": {"type": "object"}, "focus": {"type": "array", "items": S},
                               "coverage_every_cycles": {"type": "integer"}, "reallocate": {"type": "boolean"}}}),
            "ask_question": ("Open a question for the investigation manager.",
                             {"type": "object", "properties": {"text": S, "scope": S, "kind": S}, "required": ["text"]}),
            "cases": ("The open cases (tracked findings) in your scope: level, who has seen them, their history.",
                      {"type": "object", "properties": {}}),
            "log_decision": ("Write one line to the delegation log: why you did or did not delegate, or why you changed course.",
                             {"type": "object", "properties": {"text": S, "kind": S, "target": S}, "required": ["text"]}),
            "delegations": ("Your recent delegations and notes: what you asked whom, and what came back.",
                            {"type": "object", "properties": {"n": {"type": "integer"}}}),
            "propose_role": ("Propose a new reading role (applies at cycle end if within the envelope, else a person decides). "
                             "Give id, title, prompt, tools (evidence.* / org.*), reason; optionally kind, model, effort, "
                             "max_turns, output (finding | division_report), scope, raw_access, standing, question_kinds.",
                             {"type": "object", "properties": {"id": S, "title": S, "prompt": S, "reason": S, "description": S,
                                                               "tools": {"type": "array", "items": S}, "kind": S, "model": S,
                                                               "effort": S, "max_turns": {"type": "integer"}, "output": S,
                                                               "scope": S, "raw_access": {"type": "boolean"},
                                                               "standing": {"type": "boolean"},
                                                               "question_kinds": {"type": "array", "items": S}},
                              "required": ["id", "title", "prompt", "tools", "reason"]}),
            "propose_change": ("Propose a change to the team: {partition, levels, standing, questions, cadence, human, "
                               "authority, triage} with a reason. Partition, levels, the human contract and budgets need a person.",
                               {"type": "object", "properties": {"changes": {"type": "object"}, "reason": S},
                                "required": ["changes", "reason"]}),
            "escalate_finding": ("Track a finding as a case or raise its level (INVESTIGATE | ALERT | PAGE). Give the scope "
                                 "(agent:<id> | resource:<id> | cohort:<id> | division:<id>), a headline with counts and bases, "
                                 "the reason, and the evidence ids (events or claims) that support it. ALERT needs a second "
                                 "independent view; until then the case is held at INVESTIGATE and promoted automatically.",
                                 {"type": "object", "properties": {"scope": S, "title": S, "level": S, "reason": S,
                                                                   "evidence_ids": {"type": "array", "items": S}, "case_id": S},
                                  "required": ["scope", "title", "level", "reason"]}),
        }

        def wrap(fn):
            async def run(args: dict[str, Any]) -> dict[str, Any]:
                try:
                    res = fn(**{k: v for k, v in args.items() if v not in (None, "")})
                    if asyncio.iscoroutine(res):
                        res = await res
                except Exception as exc:
                    return {"content": [{"type": "text", "text": f"error: {exc}"}], "is_error": True}
                return {"content": [{"type": "text", "text": json.dumps(res, default=str)[:16000]}]}
            return run

        tools = [tool(n, specs[n][0], specs[n][1])(wrap(getattr(self, n))) for n in names if n in specs]
        return create_sdk_mcp_server(name="org", version="1.0.0", tools=tools), [f"mcp__org__{n}" for n in names if n in specs]
