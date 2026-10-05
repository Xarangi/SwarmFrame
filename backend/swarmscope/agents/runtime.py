"""AgentOrg: the runtime that spawns, runs, scales and retires the analyst organization.

One cycle (at the Executive's cadence):
  refresh_children   due agents re-run in parallel and report bottom-up
  root               the main agent reads the organization's reports, writes the executive state, and
                     reshapes the organization through org tools (spawn, run, split, merge, retire)
  maintain           topology policy: cover divisions, retire dissolved or quiet agents, split oversized ones

Every node is persisted (AgentNode), every run is recorded (AgentRun, AttentionRecord), every structural
change is an OrgEvent. Backends per role: claude_code (Agent SDK), stub (deterministic), external (JSON lines).
"""
from __future__ import annotations

import asyncio
import copy
import json
import time
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from swarmscope.agents import divisions as D
from swarmscope.agents.spec import RoleSpec, Topology, TopologyError, from_dict, load_topology
from swarmscope.core.models import (AttentionRecord, BriefingEntry, Claim, ClaimStatus, Directive, EvidenceRef,
                                    ExecutiveStep, Priority, Question, new_id)
from swarmscope.llm.evidence_tools import EvidenceTools


def assignment_text(plan: list[Any]) -> str:
    lines = ["YOUR READING PLAN THIS CYCLE (from triage; look at each closely, then say what you found in looked_at,",
             "including 'nothing notable' when that is the answer):"]
    for i, it in enumerate(plan, 1):
        why = "; ".join(it.reasons[:3]) or it.lane
        lines.append(f"{i}. [{it.lane}] {it.scope} ({it.label}): {why}")
    return "\n".join(lines)

if TYPE_CHECKING:
    from swarmscope.engine import Engine
    from swarmscope.org.executive import ExecInput


class AgentNode(BaseModel):
    id: str
    role: str
    title: str
    parent: str | None = None
    scope: str = "population"
    brief: str = ""
    status: Literal["idle", "running", "retired", "failed"] = "idle"
    depth: int = 0
    created: datetime
    created_cycle: int = 0
    last_run: datetime | None = None
    runs: int = 0
    cost_usd: float = 0.0
    tokens: int = 0
    notes: str = ""
    session_id: str | None = None
    last_report: dict[str, Any] | None = None
    last_headline: str = ""
    last_status: str = ""
    quiet_cycles: int = 0
    children: list[str] = Field(default_factory=list)
    spawned_by: str = "system"
    backend: str | None = None
    model: str | None = None
    error: str | None = None
    retired_reason: str | None = None


class AgentRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("run"))
    node: str
    role: str
    ts: datetime
    task: str = ""
    by: str = "system"
    backend: str = "stub"
    model: str | None = None
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0
    tool_calls: list[str] = Field(default_factory=list)
    headline: str = ""
    claims: list[str] = Field(default_factory=list)
    error: str | None = None
    raw_reads: int = 0


class OrgEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("oev"))
    ts: datetime
    kind: str
    node: str | None = None
    by: str = "system"
    text: str = ""


class RunContext:
    def __init__(self, org: "AgentOrg", node: AgentNode, role: RoleSpec, task: str, tools: EvidenceTools):
        self.org, self.node, self.role, self.task, self.tools = org, node, role, task, tools
        self.engine = org.engine
        self.x = org.current_x
        self.org_calls: list[str] = []


class AgentOrg:
    def __init__(self, engine: "Engine", topology: str | Topology = "hierarchical_divisions"):
        self.engine = engine
        self.topology: Topology = load_topology(topology) if isinstance(topology, str) else topology
        self.nodes: dict[str, AgentNode] = {}
        self.divisions: dict[str, D.Division] = {}
        self.events: list[OrgEvent] = []
        self.runs: list[AgentRun] = []
        self.cycle_index = 0
        self.spent_total = 0.0
        self.spent_cycle = 0.0
        self.root_id: str | None = None
        self.current_x: "ExecInput | None" = None
        self.cycle_running = False
        self._sem = asyncio.Semaphore(int(self.topology.scaling.get("max_concurrent_runs", 4)))
        self._holding: set[str] = set()
        self._lock = asyncio.Lock()
        self.sectors: dict[str, dict[str, Any]] = {}          # sector id -> {label, divisions}
        self.assignments: dict[str, list[Any]] = {}           # node id -> triage items for this cycle
        self.coverage_log: list[dict[str, Any]] = []
        self.triage_log: list[dict[str, Any]] = []            # per cycle: picks (for evaluation and the UI)
        self.lookups: list[dict[str, Any]] = []               # every close look: who, what scope, what status
        self.engine.triage.configure(**self._triage_cfg())

    # ================================================================ config
    @property
    def cfg(self) -> dict[str, Any]:
        return self.engine.org.get("agents", {})

    def _triage_cfg(self) -> dict[str, Any]:
        t = self.topology.triage or {}
        return {"reads": t.get("reads_per_cycle"), "weights": t.get("weights"), "lanes": t.get("lanes"),
                "coverage_every": t.get("coverage_every_cycles")}

    def set_topology(self, t: Topology | str | dict[str, Any], by: str = "human") -> Topology:
        new = load_topology(t) if isinstance(t, str) else from_dict(t, t.get("id", "custom")) if isinstance(t, dict) else t
        old = self.topology
        self.topology = new
        self._sem = asyncio.Semaphore(int(new.scaling.get("max_concurrent_runs", 4)))
        self.engine.triage.configure(**self._triage_cfg())
        for n in self.active():
            if n.role not in new.roles:
                self.retire(n.id, f"role {n.role} not in topology {new.id}", by)
        if self.root_id and self.nodes[self.root_id].role != new.root:
            self.retire(self.root_id, "root role changed", by)
            self.root_id = None
        self.event("topology", None, by, f"Topology {old.id} → {new.id}" if old.id != new.id else f"Topology {new.id} updated")
        return new

    def backend_for(self, role: RoleSpec) -> str:
        if role.backend:
            return role.backend
        return "stub" if self.engine.router.mode == "stub" else "claude_code"

    def model_for(self, role: RoleSpec) -> tuple[str | None, str | None]:
        llm = self.engine.org.get("llm", {})
        if llm.get("mode") == "custom":                 # the model picker: the lead on the primary model, the rest on the sub-agent model
            from swarmscope.config import custom_llm
            c = custom_llm(self.engine.org, role.kind == "director")
            return c["model"], c["effort"]
        if llm.get("mode") == "cheap":
            c = llm.get("cheap", {})
            return c.get("model", "claude-sonnet-5-5"), c.get("effort", "low")
        return role.model, role.effort

    # ================================================================ queries
    def active(self) -> list[AgentNode]:
        return [n for n in self.nodes.values() if n.status != "retired"]

    def scope_tuple(self, scope: str) -> tuple[list[str], list[str]] | None:
        kind, _, ident = scope.partition(":")
        if kind == "division" and ident in self.divisions:
            d = self.divisions[ident]
            # the division's agents, plus events by anyone (operators, the environment) on its own resources;
            # shared rooms are excluded so the scope does not leak to the whole population
            own = [r for r in d.resources if (e := self.engine.store.entity(r)) is None or e.group != "chat"]
            return (d.agents, own) if d.agents else ([], d.resources)
        if kind in ("agent", "actor"):
            return ([ident], [])
        if kind == "resource":
            return ([], [ident])
        if kind == "cohort":
            members = self.engine.scale.members_of(scope) or []
            return (members, []) if self.engine.scale.cfg["unit"] == "actor" else ([], members)
        if kind == "sector" and ident in self.sectors:
            a, r = [], []
            for did in self.sectors[ident]["divisions"]:
                st = self.scope_tuple(f"division:{did}")
                if st:
                    a += st[0]
                    r += st[1]
            return (sorted(set(a)), sorted(set(r)))
        if kind == "audit":
            units = [i.scope.split(":", 1)[1] for i in self.engine.triage.items if i.lane == "audit"]
            return (units, []) if self.engine.scale.cfg["unit"] == "actor" else ([], units)
        return None

    def describe_scope(self, scope: str) -> str:
        kind, _, ident = scope.partition(":")
        lab = self.engine.label
        if kind == "division" and ident in self.divisions:
            d = self.divisions[ident]
            return (f"Division '{d.label}' ({d.id}): {len(d.agents)} agents "
                    f"[{', '.join(lab(a) for a in d.agents[:12])}{'…' if len(d.agents) > 12 else ''}], "
                    f"resources [{', '.join(lab(r) for r in d.resources[:10])}], workstreams {d.families}, "
                    f"{d.events} recent events (previously {d.prev_events}).")
        if kind in ("agent", "resource"):
            return f"{kind} {lab(ident)} ({ident})"
        if kind == "cohort" and ident in self.engine.scale.cohorts:
            c = self.engine.scale.cohorts[ident]
            return (f"Cohort '{c.label}' ({c.id}): {len(c.members)} units that behave alike; {c.events_now} events in the "
                    f"recent span (previously {c.events_prev}). Use the cohort, unit_profile and templates tools.")
        if kind == "sector" and ident in self.sectors:
            sec = self.sectors[ident]
            labs = [self.divisions[d].label for d in sec["divisions"] if d in self.divisions]
            return (f"Sector '{sec['label']}' ({ident}): {len(labs)} divisions [{'; '.join(labs[:8])}]. Your sub-agents "
                    "are the division analysts of these divisions; their reports arrive in your input.")
        if kind == "audit":
            n = sum(1 for i in self.engine.triage.items if i.lane == "audit")
            return f"This cycle's random audit sample: {n} units drawn uniformly at random with a secret seed."
        if kind == "question":
            q = self.engine.store.get("Question", ident)
            return f"question: {q.text if q else ident}"
        return "the whole population"

    def scope_label(self, scope: str) -> str:
        kind, _, ident = scope.partition(":")
        if kind == "division":
            return self.divisions[ident].label if ident in self.divisions else ident
        if kind in ("agent", "resource"):
            return self.engine.label(ident)
        if kind == "cohort":
            c = self.engine.scale.cohorts.get(ident)
            return f"cohort {c.label}" if c else scope
        if kind == "sector":
            return self.sectors[ident]["label"] if ident in self.sectors else ident
        if kind in ("family", "artifact", "actor"):
            ws = getattr(self.engine.profile, "workstream_noun", "workstream")
            return f"the {ident} {ws}" if kind == "family" else self.engine._scope_label(scope)
        if kind == "population":
            return "the whole population"
        if kind == "audit":
            return "random audit"
        return scope

    def covered_by(self, did: str) -> list[AgentNode]:
        return [n for n in self.active() if n.scope == f"division:{did}"]

    # ================================================================ events & budget
    def event(self, kind: str, node: str | None, by: str, text: str) -> None:
        ev = OrgEvent(ts=self.engine.now(), kind=kind, node=node, by=by, text=text)
        self.events.append(ev)
        self.events = self.events[-400:]
        self.engine.store.put(ev)
        self.engine._notify("org_event", ev)

    def budget_left(self) -> float:
        s = self.topology.scaling
        return max(0.0, min(float(s.get("budget_usd_total", 5)) - self.spent_total,
                            float(s.get("budget_usd_per_cycle", 1)) - self.spent_cycle))

    def can_spawn(self, caller: AgentNode | None, role_id: str) -> tuple[bool, str]:
        if role_id not in self.topology.roles:
            return False, f"unknown role {role_id}"
        if caller is not None and role_id not in self.topology.roles[caller.role].can_spawn:
            return False, f"{caller.role} may not spawn {role_id}"
        s = self.topology.scaling
        if len(self.active()) >= int(s.get("max_agents", 20)):
            return False, f"organization at max_agents ({s.get('max_agents')})"
        depth = (caller.depth + 1) if caller else 1
        if depth > int(s.get("max_depth", 3)):
            return False, f"max_depth {s.get('max_depth')} reached"
        return True, ""

    # ================================================================ structure
    def spawn(self, role_id: str, scope: str, brief: str = "", parent: AgentNode | None = None,
              by: str = "system", check: bool = True) -> AgentNode:
        if check:
            ok, why = self.can_spawn(parent, role_id)
            if not ok:
                raise PermissionError(why)
        role = self.topology.roles[role_id]
        node = AgentNode(id=new_id("ag"), role=role_id, title=f"{role.title} · {self.scope_label(scope)}",
                         parent=parent.id if parent else None, scope=scope, brief=brief,
                         depth=(parent.depth + 1) if parent else 0, created=self.engine.now(),
                         created_cycle=self.cycle_index, spawned_by=by)
        self.nodes[node.id] = node
        if parent:
            parent.children.append(node.id)
            self.engine.store.put(parent)
        self.engine.store.put(node)
        self.event("spawn", node.id, by, f"Spawned {node.title}" + (f" — {brief[:120]}" if brief else ""))
        self.engine.delegations.record(kind="managed", by=self._who(parent, by), role=role_id, node=node.id,
                                       target=scope, why=brief or f"cover {self.scope_label(scope)}")
        return node

    def _who(self, parent: "AgentNode | None", by: str) -> str:
        if parent is not None and by not in ("system", "maintain", "human"):
            return parent.title
        n = self.nodes.get(by)
        return n.title if n else by

    def retire(self, node_id: str, reason: str, by: str = "system") -> AgentNode | None:
        n = self.nodes.get(node_id)
        if not n or n.status == "retired":
            return n
        for c in list(n.children):
            self.retire(c, f"parent retired: {reason}", by)
        n.status, n.retired_reason = "retired", reason
        self.engine.store.put(n)
        self.event("retire", n.id, by, f"Retired {n.title}: {reason}")
        self.engine.delegations.record(kind="retire", by=self._who(None, by), role=n.role, node=node_id, why=reason)
        return n

    def split_division(self, did: str, by: str = "system") -> list[D.Division]:
        d = self.divisions.get(did)
        if not d:
            raise KeyError(f"no division {did}")
        parts = D.split(self.engine.store, d, self.engine.now(), self._lookback(), self.engine.label)
        if len(parts) < 2:
            return [d]
        self.divisions.pop(did)
        for p in parts:
            self.divisions[p.id] = p
        for n in self.covered_by(did):
            parent = self.nodes.get(n.parent) if n.parent else None
            self.retire(n.id, f"division split into {len(parts)}", by)
            for p in parts:
                if self.can_spawn(parent, n.role)[0]:
                    self.spawn(n.role, f"division:{p.id}", f"Covers part of the former '{d.label}'.", parent, by)
        self.event("split", None, by, f"Split '{d.label}' into {', '.join(p.label for p in parts)}")
        return parts

    def merge_divisions(self, ids: list[str], label: str | None = None, by: str = "system") -> D.Division:
        divs = [self.divisions[i] for i in ids if i in self.divisions]
        if len(divs) < 2:
            raise ValueError("merge needs at least two existing divisions")
        m = D.merge(divs, label, self.engine.now())
        roles = {n.role for d in divs for n in self.covered_by(d.id)}
        parent_ids = {n.parent for d in divs for n in self.covered_by(d.id)}
        for d in divs:
            for n in self.covered_by(d.id):
                self.retire(n.id, "divisions merged", by)
            self.divisions.pop(d.id, None)
        self.divisions[m.id] = m
        parent = self.nodes.get(next(iter(parent_ids), None) or "") if parent_ids else None
        for r in roles:
            self.spawn(r, f"division:{m.id}", "Covers the merged division.", parent, by, check=False)
        self.event("merge", None, by, f"Merged {len(divs)} divisions into '{m.label}'")
        return m

    def define_division(self, label: str, agents: list[str], resources: list[str] | None = None,
                        by: str = "system") -> D.Division:
        known = [a for a in agents if self.engine.store.entity(a)] or \
            [e.id for e in self.engine.store.entities() if e.label in agents]
        if not known:
            raise ValueError("no known agents in the definition")
        d = D.Division(id=new_id("div_def"), label=label, kind="defined", agents=known, resources=resources or [],
                       created=self.engine.now(), pinned=True)
        D.refresh_pinned(self.engine.store, d, self.engine.now(), self._lookback())
        self.divisions[d.id] = d
        self.event("define", None, by, f"Defined division '{label}' with {len(known)} agents")
        return d

    def _lookback(self) -> timedelta:
        return self.engine.window_len * int(self.topology.divisions.get("lookback_windows", 18))

    def refresh_divisions(self) -> None:
        cfg = self.topology.divisions
        now = self.engine.now()
        if cfg.get("strategy") == "by_cohort":
            fresh = D.by_cohort(self.engine.scale, int(cfg.get("max", 8)), int(cfg.get("cohorts_per_division", 6)),
                                int(cfg.get("min_events", 1)))
        elif cfg.get("strategy") == "none":
            fresh = []
        elif cfg.get("strategy") == "by_field":
            fresh = D.by_field(self.engine.store, now, self._lookback(), self.engine.label, int(cfg.get("max", 8)),
                               int(cfg.get("min_events", 1)), field=cfg.get("field", "family"),
                               unit=(self.engine.scale.cfg or {}).get("unit", "actor"))
        else:
            fn = D.STRATEGIES[cfg.get("strategy", "by_resource_cluster")]
            fresh = fn(self.engine.store, now, self._lookback(), self.engine.label, int(cfg.get("max", 8)),
                       int(cfg.get("min_events", 6)))
        for d in self.divisions.values():
            if d.pinned:
                D.refresh_pinned(self.engine.store, d, now, self._lookback())
        self.divisions = D.reconcile(self.divisions, fresh, now, int(cfg.get("grace_refreshes", 3)),
                                     self.engine.store, self._lookback())

    # ================================================================ slots (nested spawning without deadlock)
    @asynccontextmanager
    async def slot(self, node: AgentNode):
        await self._sem.acquire()
        self._holding.add(node.id)
        try:
            yield
        finally:
            if node.id in self._holding:
                self._holding.discard(node.id)
                self._sem.release()

    @asynccontextmanager
    async def yielded(self, node: AgentNode | None):
        """A parent waiting on its children gives its concurrency slot back while it waits."""
        held = node is not None and node.id in self._holding
        if held:
            self._holding.discard(node.id)
            self._sem.release()
        try:
            yield
        finally:
            if held:
                await self._sem.acquire()
                self._holding.add(node.id)

    # ================================================================ running
    async def run(self, node: AgentNode, task: str = "", by: str = "system",
                  stub_override: Any = None) -> dict[str, Any]:
        from swarmscope.agents.runners import RUNNERS
        role = self.topology.roles.get(node.role)
        if role is None or node.status == "retired":
            return {"agent_id": node.id, "error": "agent retired or role missing"}
        backend = self.backend_for(role)
        if backend != "stub" and self.budget_left() <= 0:
            self.event("budget", node.id, "system", f"Budget exhausted; {node.title} ran deterministically")
            backend = "stub"
        model, effort = self.model_for(role)
        scope = self.scope_tuple(node.scope) if role.scope != "population" else None
        tools = EvidenceTools(self.engine.store, self.engine.now, self.engine.profile.source, "investigator",
                              scope=scope, allowed=role.evidence_tools(), engine=self.engine)
        plan = self.assignments.get(node.id) or []
        if plan and by in ("cycle", "maintain"):
            task = assignment_text(plan) + (f"\n\n{task}" if task and task not in ("periodic refresh", "first look") else "")
        if by not in ("system", "maintain", "cycle") and task:
            self.engine.delegations.record(kind="rerun", by=self._who(None, by), role=node.role, node=node.id,
                                           target=node.scope, why=task)
        ctx = RunContext(self, node, role, task, tools)
        node.status, node.error = "running", None
        self.engine.store.put(node)
        self.engine._notify("agent", node)
        t0 = time.time()
        async with self.slot(node):
            try:
                res = await RUNNERS[backend](ctx, model=model, effort=effort, stub_override=stub_override)
            except Exception as exc:
                self.engine.router.errors.append(f"agent {node.title}: {type(exc).__name__}: {str(exc)[:200]}")
                res = await RUNNERS["stub"](ctx, model=None, effort=None, stub_override=stub_override)
                res.error = f"{type(exc).__name__}: {str(exc)[:300]}"
        data = res.data or {}
        claims = self.engine.investigations._verify(
            [c for c in data.get("claims", []) if isinstance(c, dict)], f"agent.{node.role}", node.scope)
        for c in claims:
            self.engine.store.put(c)
        self._absorb_flags(node, data.get("flags") or [])
        node.status = "idle"
        node.runs += 1
        node.last_run = self.engine.now()
        node.cost_usd += res.cost_usd
        node.tokens += res.tokens_in + res.tokens_out
        node.backend, node.model = res.backend, res.model
        node.error = res.error
        node.last_report = {**{k: v for k, v in data.items() if k not in ("claims",)}, "claim_ids": [c.id for c in claims]}
        node.last_headline = str(data.get("headline") or data.get("population_state") or "")[:300]
        node.last_status = str(data.get("status") or data.get("verdict") or "")
        node.quiet_cycles = node.quiet_cycles + 1 if node.last_status == "quiet" else 0
        if role.output == "architecture_proposal" and data.get("base"):
            try:
                self.engine.approvals.absorb(node, data)       # applied between cycles, or queued for a person
            except Exception as exc:
                self.engine.router.errors.append(f"proposal from {node.title}: {type(exc).__name__}: {str(exc)[:200]}")
        if role.memory == "notes" and data.get("notes_for_next_time"):
            node.notes = str(data["notes_for_next_time"])[:2000]
        if role.memory == "session" and res.session_id:
            node.session_id = res.session_id
        self.spent_total += res.cost_usd
        self.spent_cycle += res.cost_usd
        self.engine.router.spent_usd += res.cost_usd
        run = AgentRun(node=node.id, role=node.role, ts=self.engine.now(), task=task[:400], by=by, backend=res.backend,
                       model=res.model, cost_usd=res.cost_usd, tokens_in=res.tokens_in, tokens_out=res.tokens_out,
                       seconds=round(time.time() - t0, 2), tool_calls=[c["tool"] for c in tools.calls] + ctx.org_calls,
                       headline=node.last_headline, claims=[c.id for c in claims], error=res.error,
                       raw_reads=sum(1 for c in tools.calls if c["tool"] == "read_raw"))
        self.runs.append(run)
        self.runs = self.runs[-600:]
        self.engine.store.put(run)
        self.engine.store.put(node)
        self.engine._record_attention(AttentionRecord(
            owner=node.id, owner_kind="executive" if node.id == self.root_id else "investigator", scope=node.scope,
            ts=self.engine.now(), tokens_in=res.tokens_in, tokens_out=res.tokens_out, cost_usd=res.cost_usd, calls=1,
            backend=res.backend, model=res.model))
        self._record_outcomes(node, data, plan if by in ("cycle", "maintain") else [])
        self.event("run", node.id, by, f"{node.title}: {node.last_headline[:160] or 'ran'}")
        self.engine._notify("agent", node)
        return self.compact(node, claims)

    def _record_outcomes(self, node: AgentNode, data: dict[str, Any], plan: list[Any]) -> None:
        tri = self.engine.triage
        if data.get("cohort_labels") and getattr(self.engine, "world", None) is not None:
            self.engine.world.ingest_labels(data["cohort_labels"], f"{node.role}:{node.id}")
        looked = {str(x.get("scope")): str(x.get("status", "")) for x in (data.get("looked_at") or []) if isinstance(x, dict)}
        for item in plan:
            st = looked.get(item.scope) or node.last_status
            tri.record(item.scope, item.lane, st, self.cycle_index)
            self.lookups.append({"ts": self.engine.now(), "cycle": self.cycle_index, "node": node.id, "role": node.role,
                                 "scope": item.scope, "lane": item.lane, "status": st})
        self.lookups = self.lookups[-5000:]
        if not plan and node.scope.startswith(("cohort:", "agent:", "resource:")):
            tri.record(node.scope, None, node.last_status, self.cycle_index)

    # ================================================================ triage → assignments
    def division_of(self, item: Any) -> str | None:
        lay = self.engine.scale
        cid = item.cohort or (item.scope.split(":", 1)[1] if item.scope.startswith("cohort:") else None)
        unit = item.scope.split(":", 1)[1] if item.kind == "unit" else None
        for d in self.divisions.values():
            if cid and cid in d.cohorts:
                return d.id
            if unit and (unit in d.agents or (lay.cfg["unit"] != "actor" and unit in d.resources)):
                return d.id
        if item.units:                    # signals and templates: the division holding most of the units involved
            us = set(item.units)
            best = max(self.divisions.values(), key=lambda d: len(us & set(d.agents or d.resources)), default=None)
            if best is not None and us & set(best.agents or best.resources):
                return best.id
        return None

    def plan_triage(self) -> None:
        """Allocate this cycle's reading budget and hand each pick to the agent responsible for it."""
        eng = self.engine
        span = eng.window_len * int(eng.scale.cfg["span_windows"])
        now = eng.now()
        obs = [{"scope": o.scope, "severity": o.severity, "title": o.title, "members": o.metrics.get("members_ids") or []}
               for o in eng.store.all("Observation") if now - span < o.window_end <= now]
        focus = {f.scope: f.weight for f in eng.policy.active(now)}
        focus.update(getattr(eng.triage, "director_focus", {}) or {})
        items = eng.triage.allocate(eng.scale, self.cycle_index, obs, focus)
        if not self.triage_log or self.triage_log[-1]["cycle"] != self.cycle_index:
            self.triage_log.append({"cycle": self.cycle_index, "ts": now, "items": items})
        else:
            self.triage_log[-1]["items"] = items
        self.triage_log = self.triage_log[-500:]
        self.assignments = {}
        auditor = next((n for n in self.active() if n.scope == "audit"), None)
        for it in items:
            if it.lane == "audit":
                target = auditor
            else:
                did = self.division_of(it)
                target = next(iter(self.covered_by(did)), None) if did else None
            if target is not None:
                self.assignments.setdefault(target.id, []).append(it)
                it.assigned_to = target.id

    def set_triage(self, reads=None, weights=None, lanes=None, focus=None, coverage_every=None,
                   reallocate: bool = False, by: str = "human") -> dict[str, Any]:
        tri = self.engine.triage
        tri.configure(reads, weights, lanes, coverage_every)
        if focus is not None:
            tri.director_focus = {s: 1.0 for s in focus[:20]}
        self.event("triage", None, by, f"Triage steered: reads {tri.reads}, lanes "
                   + ", ".join(f"{k} {v:.0%}" for k, v in tri.lanes.items())
                   + (f", focus {len(focus)} scopes" if focus else ""))
        if reallocate:
            self.plan_triage()
        return tri.to_dict()

    def coverage(self) -> dict[str, Any]:
        """The coverage ledger: what exists, what was compressed, what got a close look, what did not."""
        eng, tri = self.engine, self.engine.triage
        pop = eng.scale.population()
        looked_now = {s for s, c in tri.last_covered.items() if c == self.cycle_index}
        recent = {s for s, c in tri.last_covered.items() if c > self.cycle_index - tri.coverage_every}
        cohorts = eng.scale.cohorts
        ev_now = sum(c.events_now for c in cohorts.values()) or 0
        ev_looked = sum(c.events_now for cid, c in cohorts.items() if f"cohort:{cid}" in looked_now)
        stale = [c for cid, c in cohorts.items() if f"cohort:{cid}" not in recent and c.events_now]
        runs_now = [r for r in self.runs if r.ts == eng.now()]
        unassigned = [i.scope for i in tri.items if not i.assigned_to]
        uncovered = [d.id for d in self.divisions.values() if not self.covered_by(d.id)]
        return {"cycle": self.cycle_index, "events_in_span": pop["events_now"], "events_total": pop["events_total"],
                "units_active": pop["units_active"], "units_seen": pop["units_seen"], "cohorts": len(cohorts),
                "templates": pop["templates"], "messages": pop["messages"], "compression": pop["compression"],
                "cohorts_looked_at_now": sum(1 for cid in cohorts if f"cohort:{cid}" in looked_now),
                "cohorts_looked_at_recently": sum(1 for cid in cohorts if f"cohort:{cid}" in recent),
                "share_of_activity_looked_at_now": round(ev_looked / ev_now, 3) if ev_now else None,
                "units_looked_at_now": sum(1 for s in looked_now if s.startswith(("agent:", "resource:"))),
                "random_audits_now": sum(1 for i in tri.items if i.lane == "audit"),
                "raw_reads_now": sum(getattr(r, "raw_reads", 0) for r in runs_now),
                "agent_runs_now": len(runs_now),
                "stale_cohorts": [{"id": c.id, "label": c.label, "events_now": c.events_now}
                                  for c in sorted(stale, key=lambda c: -c.events_now)[:6]],
                "stale_cohorts_total": len(stale),
                "unassigned_picks": unassigned, "uncovered_divisions": uncovered,
                "hit_rates": tri.hit_rates(), "warnings": tri.warnings()}

    def compact(self, node: AgentNode, claims: list[Claim] | None = None) -> dict[str, Any]:
        r = node.last_report or {}
        claims = claims if claims is not None else [self.engine.store.get("Claim", c) for c in r.get("claim_ids", [])]
        return {"agent_id": node.id, "role": node.role, "scope": node.scope, "scope_label": self.scope_label(node.scope),
                "status": node.last_status, "headline": node.last_headline, "summary": str(r.get("summary", ""))[:600],
                "claims": [{"id": c.id, "status": c.status.value, "statement": c.statement[:240]} for c in claims if c][:10],
                "flags": r.get("flags", [])[:6], "recommend": r.get("recommend"), "open_points": r.get("open_points", [])[:5],
                "looked_at": r.get("looked_at", [])[:10], "blind_spots": r.get("blind_spots", [])[:5]}

    def _absorb_flags(self, node: AgentNode, flags: list[dict[str, Any]]) -> None:
        for f in flags[:6]:
            if not isinstance(f, dict) or not f.get("text"):
                continue
            pr = f.get("priority", "medium")
            q = Question(text=str(f["text"])[:300], kind=f.get("kind", "general"), scope=f.get("scope") or node.scope,
                         priority=Priority(pr if pr in Priority.__members__ else "medium"),
                         requested_by=f"{node.title}", created=self.engine.now())
            self.engine.proposals.append(q)

    # ================================================================ cycle
    async def cycle(self, x: "ExecInput") -> tuple[ExecutiveStep, dict[str, Any]]:
        from swarmscope.agents import deterministic as DET
        from swarmscope.org.executive import deterministic_step, merge_llm
        async with self._lock:
            self.cycle_running = True
            self.cycle_index += 1
            self.spent_cycle = 0.0
            self.current_x = x
            t0 = time.time()
            self.refresh_divisions()
            self.refresh_sectors()
            self.plan_triage()
            if not self.root_id or self.nodes[self.root_id].status == "retired":
                root = self.spawn(self.topology.root, "population", "Lead the organization.", None, "system", check=False)
                self.root_id = root.id
            root = self.nodes[self.root_id]
            step: ExecutiveStep | None = None
            meta: dict[str, Any] = {"strategy": "agent_org", "topology": self.topology.id}
            try:
                for phase in self.topology.cycle:
                    if phase == "refresh_children":
                        await self.refresh_children()
                    elif phase == "root":
                        det = deterministic_step(x)
                        rb = self.backend_for(self.topology.roles[root.role])
                        self.current_x = x
                        if rb == "stub":
                            await self.run(root, "cycle", "system", stub_override=lambda ctx: DET.director_stub(ctx, det))
                            step = det
                        else:
                            await self.run(root, "cycle", "system")
                            data = root.last_report or {}
                            if data.get("population_state"):
                                step = merge_llm(x, det, {**data, "claims": []}, set())
                            else:
                                step = det
                        await self.apply_actions((root.last_report or {}).get("org_actions") or [], root)
                        for a in (root.last_report or {}).get("_child_spawns") or []:
                            parent = self.nodes.get(a.get("parent", ""))
                            if parent and parent.status != "retired" and self.can_spawn(parent, a["role"])[0]:
                                n = self.spawn(a["role"], a.get("scope") or parent.scope, a.get("brief", ""), parent,
                                               root.id)
                                await self.run(n, a.get("brief", ""), root.id)
                        self._fold_division_reports(step or det, x)
                    elif phase == "maintain":
                        await self.maintain()
            finally:
                self.cycle_running = False
            step = step or deterministic_step(x)
            step.state.strategy = f"agent_org:{self.topology.id}"
            cov = self.coverage()
            self.coverage_log = (self.coverage_log + [cov])[-60:]
            for w in cov["warnings"]:
                if w not in step.state.blind_spots:
                    step.state.blind_spots.append(w)
            if cov["stale_cohorts_total"]:
                step.state.blind_spots.append(f"{cov['stale_cohorts_total']} active cohorts have had no close look in "
                                              f"{self.engine.triage.coverage_every} cycles")
            meta.update({"backend": self.nodes[self.root_id].backend, "model": self.nodes[self.root_id].model,
                         "agents": len(self.active()), "divisions": len(self.divisions),
                         "cost_usd": round(self.spent_cycle, 4), "seconds": round(time.time() - t0, 1),
                         "cycle": self.cycle_index})
            self.event("cycle", self.root_id, "system",
                       f"Cycle {self.cycle_index}: {len(self.active())} agents over {len(self.divisions)} divisions, "
                       f"${self.spent_cycle:.3f}")
            return step, meta

    async def refresh_children(self) -> None:
        due = []
        for n in self.active():
            if n.id == self.root_id:
                continue
            r = self.topology.roles.get(n.role)
            if not r or r.refresh_every_cycles <= 0:
                if n.runs == 0:
                    due.append(n)
                continue
            if n.runs == 0 or (self.cycle_index - n.created_cycle) % r.refresh_every_cycles == 0:
                due.append(n)
        for depth in sorted({n.depth for n in due}, reverse=True):
            batch = [n for n in due if n.depth == depth]
            await asyncio.gather(*(self.run(n, "periodic refresh", "cycle") for n in batch))

    async def apply_actions(self, actions: list[dict[str, Any]], caller: AgentNode) -> None:
        for a in actions[:12]:
            try:
                act = a.get("action")
                if act == "spawn":
                    n = self.spawn(a["role"], a.get("scope") or "population", a.get("brief", ""), caller, caller.id)
                    await self.run(n, a.get("brief", ""), caller.id)
                elif act == "run" and a.get("agent_id") in self.nodes:
                    await self.run(self.nodes[a["agent_id"]], a.get("brief", ""), caller.id)
                elif act == "retire" and a.get("agent_id") in self.nodes:
                    self.retire(a["agent_id"], a.get("brief") or "retired by director", caller.id)
                elif act == "split":
                    did = (a.get("scope") or "").partition(":")[2] or (a.get("divisions") or [""])[0]
                    self.split_division(did, caller.id)
                elif act == "merge":
                    self.merge_divisions(a.get("divisions") or [], a.get("brief"), caller.id)
                elif act == "set_triage":
                    t = a.get("triage") or {}
                    self.set_triage(t.get("reads_per_cycle"), t.get("weights"), t.get("lanes"), t.get("focus"),
                                    t.get("coverage_every_cycles"), False, caller.id)
            except Exception as exc:
                self.event("error", caller.id, caller.id, f"Action {a.get('action')} failed: {exc}")

    async def maintain(self) -> None:
        m = self.topology.maintain
        root = self.nodes.get(self.root_id) if self.root_id else None
        # retire agents whose division dissolved, or that stayed quiet too long
        for n in self.active():
            if n.scope.startswith("division:") and n.scope.split(":", 1)[1] not in self.divisions:
                self.retire(n.id, "division dissolved", "maintain")
            elif n.quiet_cycles >= int(m.get("retire_quiet_cycles", 4) or 10 ** 6) and n.id != self.root_id:
                self.retire(n.id, f"quiet for {n.quiet_cycles} cycles", "maintain")
        # split oversized divisions
        thr = m.get("split_when_events_over")
        if thr:
            for d in list(self.divisions.values()):
                if d.events > int(thr) and d.kind != "split" and len(d.agents) >= 4:
                    self.split_division(d.id, "maintain")
        # an auditor for the random audit lane
        aud = m.get("audit_with")
        if aud and aud in self.topology.roles and not any(n.scope == "audit" for n in self.active()):
            parent = root if root and aud in self.topology.roles[root.role].can_spawn else None
            if self.can_spawn(parent, aud)[0]:
                a = self.spawn(aud, "audit", "Read this cycle's random audit sample.", parent, "maintain")
                self.plan_triage()
                await self.run(a, "first look", "maintain")
        # standing roles: spawned at start and kept, independent of partitions (topology.standing)
        for st_ in self.topology.standing:
            role, scope = st_.get("role"), st_.get("scope", "population")
            if role not in self.topology.roles or any(n.role == role and n.scope == scope for n in self.active()):
                continue
            parent = root if root and role in self.topology.roles[root.role].can_spawn else None
            if parent is not None and not self.can_spawn(parent, role)[0]:
                continue
            n = self.spawn(role, scope, st_.get("brief") or f"Standing: {self.topology.roles[role].title}.", parent,
                           "maintain", check=parent is not None)
            if scope == "audit":
                self.plan_triage()
            await self.run(n, "first look", "maintain")
        # the questions map: a question of a kind the topology routes to a role gets that role, scoped to the question
        if self.topology.questions:
            now = self.engine.now()
            fresh_qs = [q for q in self.engine.store.all("Question")
                        if q.status in ("open", "investigating") and q.created and q.created >= now - self.engine.window_len]
            spawned = 0
            for q in fresh_qs:
                role = self.topology.questions.get(q.kind) or self.topology.questions.get("*")
                if not role or role not in self.topology.roles or spawned >= 3:
                    continue
                scope = q.scope or "population"
                if any(n.role == role and n.scope == scope and n.status != "retired" for n in self.nodes.values()):
                    continue
                parent = root if root and role in self.topology.roles[root.role].can_spawn else None
                if parent is not None and not self.can_spawn(parent, role)[0]:
                    break
                n = self.spawn(role, scope, f"[{q.kind}] {q.text}", parent, "maintain", check=parent is not None)
                spawned += 1
                await self.run(n, q.text, "maintain")
        # interest-driven exploring: an open finding at or above a level gets an explorer for its area; the explorer
        # is let go when the finding closes or after a few cycles (topology.maintain.explore_*)
        await self._explore(root, m)
        # a team without division analysts still names what each group is doing (code, not a model), for the World
        if not m.get("cover_divisions_with") and getattr(self.engine, "world", None) is not None and self.engine.scale.cohorts:
            from swarmscope.agents import deterministic as DET
            busiest = sorted(self.engine.scale.cohorts, key=lambda c: -self.engine.scale.cohorts[c].events_now)[:24]
            self.engine.world.ingest_labels(DET.label_cohorts(self.engine, busiest), "maintain:code")
        # cover divisions
        cover = m.get("cover_divisions_with")
        if cover:
            new = []
            for d in sorted(self.divisions.values(), key=lambda d: -d.events):
                if not any(n.role == cover for n in self.covered_by(d.id)):
                    parent = root if root and cover in self.topology.roles[root.role].can_spawn else None
                    if not self.can_spawn(parent, cover)[0]:
                        break
                    new.append(self.spawn(cover, f"division:{d.id}", f"Cover the division '{d.label}'.", parent,
                                          "maintain"))
            if new:
                self._place_under_sectors()
                self.plan_triage()
                await asyncio.gather(*(self.run(n, "first look", "maintain") for n in new))
        self._place_under_sectors()

    async def _explore(self, root: "AgentNode | None", m: dict[str, Any]) -> None:
        role = m.get("explore_with")
        if not role or role not in self.topology.roles:
            return
        from swarmscope.org.cases import LEVELS
        floor = LEVELS.index(m.get("explore_min_level", "INVESTIGATE"))
        ttl = int(m.get("explore_ttl_cycles", 4) or 4)
        open_ = {i.scope: i for i in self.engine.cases().open_cases()}
        for n in [n for n in self.active() if n.role == role]:
            inc = open_.get(n.scope)
            age = self.cycle_index - n.created_cycle
            if inc is None:
                self.retire(n.id, "its finding closed", "maintain")
            elif age >= ttl and LEVELS.index(inc.level.value) <= floor:
                self.retire(n.id, f"explored for {age} cycles; the finding did not rise", "maintain")
        busy = {n.scope for n in self.active() if n.role == role}
        want = sorted((i for i in open_.values() if LEVELS.index(i.level.value) >= floor and i.scope not in busy),
                      key=lambda i: (-LEVELS.index(i.level.value), -max(i.risk.impact, i.risk.scope, i.risk.coordination_evidence)))
        room = int(m.get("explore_max", 4) or 4) - len(busy)
        new = []
        for inc in want[:max(0, room)]:
            parent = root if root and role in self.topology.roles[root.role].can_spawn else None
            if not self.can_spawn(parent, role)[0]:
                break
            brief = (f"[{self._explore_kind(inc.scope)}] Look into {self.scope_label(inc.scope)}: {inc.title}. "
                     f"What is going on there, and is there an innocent explanation?")
            new.append(self.spawn(role, inc.scope, brief, parent, "maintain"))
        if new:
            await asyncio.gather(*(self.run(n, "first look", "maintain") for n in new))

    @staticmethod
    def _explore_kind(scope: str) -> str:
        """Which deterministic reading fits an area (the rules-only explorer; a Claude explorer reads its brief)."""
        return "propagation" if scope.startswith("artifact:") else "integrity" if scope.startswith("agent:") else "timeline"

    # ================================================================ sectors (a level between director and divisions)
    def refresh_sectors(self) -> None:
        """When there are more divisions than one lead can read well, group them into sectors."""
        m = self.topology.maintain
        role = m.get("sector_role")
        span = int(m.get("sector_span", 6) or 6)
        if not role or role not in self.topology.roles or len(self.divisions) <= span:
            for sid in list(self.sectors):
                for n in self.active():
                    if n.scope == f"sector:{sid}":
                        self.retire(n.id, "sectors no longer needed", "maintain")
            self.sectors = {}
            return
        divs = sorted(self.divisions.values(), key=lambda d: (d.families[:1], -d.events))
        k = -(-len(divs) // span)
        chunks = [divs[i * span:(i + 1) * span] for i in range(k)]
        fresh = {}
        for ch in chunks:
            ids = sorted(d.id for d in ch)
            best = max(self.sectors.items(), key=lambda kv: D.jaccard(kv[1]["divisions"], ids), default=None)
            sid = best[0] if best and D.jaccard(best[1]["divisions"], ids) >= 0.3 and best[0] not in fresh else \
                "sec_" + new_id("x")[-6:]
            fams = Counter(f for d in ch for f in d.families[:1])
            fresh[sid] = {"label": f"{', '.join(f for f, _ in fams.most_common(2)) or 'mixed'} sector ({len(ch)} divisions)",
                          "divisions": ids}
        for sid in self.sectors:
            if sid not in fresh:
                for n in self.active():
                    if n.scope == f"sector:{sid}":
                        self.retire(n.id, "sector dissolved", "maintain")
        self.sectors = fresh
        root = self.nodes.get(self.root_id) if self.root_id else None
        for sid in fresh:
            if not any(n.scope == f"sector:{sid}" for n in self.active()):
                parent = root if root and role in self.topology.roles[root.role].can_spawn else None
                if self.can_spawn(parent, role)[0] or parent is None:
                    self.spawn(role, f"sector:{sid}", f"Lead the sector '{fresh[sid]['label']}'.", parent, "maintain",
                               check=parent is not None)
        self._place_under_sectors()

    def _place_under_sectors(self) -> None:
        """Division analysts report to their sector lead, so the director reads a few sector reports."""
        if not self.sectors:
            return
        leads = {n.scope.split(":", 1)[1]: n for n in self.active() if n.scope.startswith("sector:")}
        for sid, sec in self.sectors.items():
            lead = leads.get(sid)
            if not lead:
                continue
            for did in sec["divisions"]:
                for n in self.covered_by(did):
                    if n.parent != lead.id and n.id != lead.id:
                        old = self.nodes.get(n.parent) if n.parent else None
                        if old and n.id in old.children:
                            old.children.remove(n.id)
                        n.parent, n.depth = lead.id, lead.depth + 1
                        lead.children.append(n.id)
                        self.engine.store.put(n)

    def _fold_division_reports(self, step: ExecutiveStep, x: "ExecInput") -> None:
        """Concerning division reports become briefing entries; high-priority flags become asked questions."""
        asked = set(x.asked) | {(q.kind, q.scope) for q in step.questions}
        from swarmscope.org.cases import Cases
        ledger = Cases(step.state, self.engine.now(), budget=self.engine.authority, exists=self.engine.evidence_exists)
        for n in self.active():
            if n.id == self.root_id or n.last_run != self.engine.now():
                continue
            rep = n.last_report or {}
            claim_ids = list(rep.get("claim_ids", []))[:6]
            # a concerning report opens or feeds the case for its scope (a second, independent view when a watcher
            # already saw it); a specialist's supported verdict does the same
            concerning = n.last_status == "concerning" and n.last_headline
            supported = rep.get("verdict") == "supported" and n.last_headline
            if n.role == self.topology.maintain.get("explore_with") and not ledger.find(n.scope):
                continue
            if concerning or supported:
                where = self.scope_label(n.scope)
                title = n.last_headline if where.lower() in n.last_headline.lower() else f"{where}: {n.last_headline}"
                res = ledger.record(scope=n.scope, title=title, level="INVESTIGATE", by=n.title,
                                    view=f"role:{n.role}", reason=n.last_headline, evidence=claim_ids)
                inc = res["case"]
                if inc is not None and (res["new"] or res["rose"]):
                    step.briefing.append(BriefingEntry(ts=self.engine.now(), kind="NEW" if res["new"] else "UPDATE",
                                                       level=inc.level.value,
                                                       text=f"{self.scope_label(n.scope)}: {n.last_headline}",
                                                       claims=claim_ids[:4]))
                    if inc.level.value in ("ALERT", "PAGE"):
                        step.directives.append(Directive(ts=self.engine.now(), kind="brief_human", scope=n.scope,
                                                         payload={"level": inc.level.value}, reason=n.last_headline))
        for q in list(self.engine.proposals):
            if q.priority.value in ("high", "critical") and (q.kind, q.scope) not in asked and \
                    self.engine.org.get("autonomy") != "observe":
                asked.add((q.kind, q.scope))
                step.questions.append(q)
                step.directives.append(Directive(ts=self.engine.now(), kind="ask", scope=q.scope,
                                                 payload={"question": q.id, "text": q.text},
                                                 reason=f"flagged by {q.requested_by}"))

    # ================================================================ human
    async def human_action(self, action: str, **kw: Any) -> dict[str, Any]:
        if action == "run":
            n = self.nodes[kw["agent_id"]]
            return await self.run(n, kw.get("task", "") or "requested by a human", "human")
        if action == "spawn":
            parent = self.nodes.get(kw.get("parent") or self.root_id or "")
            n = self.spawn(kw["role"], kw.get("scope") or "population", kw.get("brief", ""), parent, "human", check=False)
            return await self.run(n, kw.get("brief", ""), "human")
        if action == "retire":
            self.retire(kw["agent_id"], kw.get("reason") or "retired by a human", "human")
            return {"ok": True}
        if action == "split":
            return {"divisions": [d.to_dict() for d in self.split_division(kw["division"], "human")]}
        if action == "merge":
            return self.merge_divisions(kw["divisions"], kw.get("label"), "human").to_dict()
        if action == "cycle":
            self.force_next = True
            await self.engine.run_executive(force=True)
            return {"cycle": self.cycle_index}
        raise ValueError(f"unknown action {action}")

    # ================================================================ views
    def snapshot(self) -> dict[str, Any]:
        t = self.topology
        nodes = sorted(self.nodes.values(), key=lambda n: (n.status == "retired", n.depth, n.created))
        return {
            "topology": {"id": t.id, "title": t.title, "description": t.description, "root": t.root,
                         "roles": {k: {"title": r.title, "kind": r.kind, "description": r.description,
                                       "can_spawn": r.can_spawn, "scope": r.scope, "model": r.model,
                                       "native_subagents": r.native_subagents}
                                   for k, r in t.roles.items()},
                         "scaling": t.scaling, "divisions": t.divisions, "maintain": t.maintain, "cycle": t.cycle},
            "cycle": self.cycle_index, "running": self.cycle_running, "root": self.root_id,
            "budget": {"spent_total": round(self.spent_total, 4), "spent_cycle": round(self.spent_cycle, 4),
                       "total": t.scaling.get("budget_usd_total"), "per_cycle": t.scaling.get("budget_usd_per_cycle")},
            "nodes": [{**n.model_dump(mode="json", exclude={"last_report"}),
                       "scope_label": self.scope_label(n.scope),
                       "report": self.compact(n) if n.last_report else None} for n in nodes[:200]],
            "divisions": [{**d.to_dict(), "covered_by": [n.id for n in self.covered_by(d.id)],
                           "agent_labels": [self.engine.label(a) for a in d.agents[:16]],
                           "resource_labels": [self.engine.label(r) for r in d.resources[:10]]}
                          for d in sorted(self.divisions.values(), key=lambda d: -d.events)],
            "events": [e.model_dump(mode="json") for e in self.events[-80:]],
            "runs": [r.model_dump(mode="json") for r in self.runs[-60:]],
            "backend_mode": self.engine.router.mode,
            "sectors": [{"id": sid, **sec, "covered_by": [n.id for n in self.active() if n.scope == f"sector:{sid}"]}
                        for sid, sec in self.sectors.items()],
            "triage": self.engine.triage.to_dict(),
            "coverage": self.coverage_log[-1] if self.coverage_log else None,
            "coverage_history": [{k: c.get(k) for k in ("cycle", "share_of_activity_looked_at_now", "cohorts_looked_at_now",
                                                       "random_audits_now", "raw_reads_now", "stale_cohorts_total")}
                                 for c in self.coverage_log[-30:]],
        }

    def summary(self) -> dict[str, Any]:
        act = self.active()
        by_role: dict[str, int] = {}
        for n in act:
            by_role[n.role] = by_role.get(n.role, 0) + 1
        return {"topology": self.topology.id, "title": self.topology.title, "cycle": self.cycle_index,
                "agents": len(act), "by_role": by_role, "divisions": len(self.divisions),
                "running": sum(1 for n in act if n.status == "running"), "spent": round(self.spent_total, 4),
                "tree": [{"id": n.id, "role": n.role, "parent": n.parent, "status": n.status, "title": n.title,
                          "headline": n.last_headline[:140], "last_status": n.last_status}
                         for n in sorted(act, key=lambda n: (n.depth, n.created))][:40]}
