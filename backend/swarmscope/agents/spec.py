"""Topology specification: the fully customizable definition of the analyst organization.

A topology (agents/topologies/<id>.yaml) declares:
  root            the role that runs every cycle (the main agent)
  roles           every role an agent can take: prompt, model, effort, tools, output schema,
                  memory mode, scope kind, which roles it may spawn, deterministic fallback
  helpers         native Claude Code subagents (AgentDefinition) a role can call through the Task tool
  divisions       how the population is partitioned for division-scoped agents
  scaling         caps on agents, depth, concurrency and spend
  cycle           the phases of one cycle (refresh_children, root, maintain)
  maintain        automatic coverage/refresh/retire policy applied after the root runs

Everything is validated on load; the Organization screen edits the same structure.
"""
from __future__ import annotations

import copy
import fnmatch
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from swarmscope.agents.schemas import SCHEMAS

TOPOLOGY_DIR = Path(__file__).parent / "topologies"
EVIDENCE_TOOLS = ["world_features", "query_events", "events_by_id", "entity", "neighborhood", "artifact_meta", "exposure_paths",
                  "timeline", "observations", "read_raw", "population_digest", "cohorts", "cohort", "unit_profile",
                  "outliers", "templates", "triage", "sample_events"]
ORG_TOOLS = ["org_status", "list_roles", "spawn_agent", "spawn_agents", "run_agent", "get_report", "retire_agent",
             "split_division", "merge_divisions", "define_division", "ask_question", "set_triage",
             "escalate_finding", "cases", "propose_role", "propose_change", "log_decision", "delegations"]
SCOPE_KINDS = ["population", "sector", "division", "cohort", "agent", "resource", "question", "audit", "any"]
MEMORY_MODES = ["none", "notes", "session", "state"]
DIVISION_STRATEGIES = ["by_cohort", "by_resource_cluster", "by_family", "by_group", "by_field", "none", "llm"]
PARTITION_KINDS = ["cohort", "field", "resource_cluster", "group", "family", "none"]
CADENCE_KINDS = ["windows", "records", "events"]
LEVEL_NAMES = ["WATCH", "INVESTIGATE", "ALERT", "PAGE"]


@dataclass
class RoleSpec:
    id: str
    title: str
    kind: str                                   # deterministic behaviour key (director, analyst, integrity, ...)
    description: str = ""
    prompt: str = ""                            # inline text, or a path relative to topologies/
    model: str = "claude-sonnet-5-5"
    effort: str = "low"
    max_turns: int = 8
    tools: list[str] = field(default_factory=lambda: ["evidence.*"])
    raw_access: bool = False                    # may call read_raw (untrusted text)
    can_spawn: list[str] = field(default_factory=list)
    output: str = "division_report"             # schema name in SCHEMAS, or "custom"
    output_schema: dict[str, Any] | None = None
    memory: str = "notes"
    scope: str = "division"
    refresh_every_cycles: int = 1               # how often maintain re-runs this role's agents
    native_subagents: list[str] = field(default_factory=list)
    backend: str | None = None                  # override: claude_code | stub | external
    command: list[str] | None = None            # for backend: external
    skills: list[str] = field(default_factory=list)       # skills injected into the system prompt (.claude/skills/<id>)
    skill_refs: list[str] = field(default_factory=list)   # references of those skills always included for this role
    delegate: bool = False                      # may fire its own sub-agents (a self-briefed reader) with the Task tool; every call is logged

    def prompt_text(self) -> str:
        p = self.prompt.strip()
        if p.endswith(".md") and "\n" not in p:
            f = TOPOLOGY_DIR / p
            return f.read_text(encoding="utf-8") if f.exists() else f"(missing prompt file {p})"
        return p

    def schema(self) -> dict[str, Any]:
        if self.output == "custom" and self.output_schema:
            return self.output_schema
        return SCHEMAS[self.output]

    def evidence_tools(self) -> list[str]:
        names = [t.split(".", 1)[1] for t in self.tools if t.startswith("evidence.")]
        out = [n for n in EVIDENCE_TOOLS if any(fnmatch.fnmatch(n, pat) for pat in names)]
        return [n for n in out if n != "read_raw" or self.raw_access]

    def org_tools(self) -> list[str]:
        names = [t.split(".", 1)[1] for t in self.tools if t.startswith("org.")]
        out = [n for n in ORG_TOOLS if any(fnmatch.fnmatch(n, pat) for pat in names)]
        if not self.can_spawn:
            out = [n for n in out if n not in ("spawn_agent", "spawn_agents", "split_division", "merge_divisions",
                                               "define_division")]
        return out


@dataclass
class HelperSpec:
    id: str
    description: str
    prompt: str
    tools: list[str] = field(default_factory=lambda: ["evidence.query_events"])
    model: str = "sonnet"
    max_turns: int = 4
    effort: str = "low"


@dataclass
class Topology:
    id: str
    title: str
    description: str
    root: str
    roles: dict[str, RoleSpec]
    helpers: dict[str, HelperSpec] = field(default_factory=dict)
    divisions: dict[str, Any] = field(default_factory=lambda: {"strategy": "by_resource_cluster", "max": 8,
                                                              "min_events": 6, "lookback_windows": 18})
    scaling: dict[str, Any] = field(default_factory=lambda: {"max_agents": 20, "max_depth": 3,
                                                            "max_concurrent_runs": 4, "budget_usd_per_cycle": 1.0,
                                                            "budget_usd_total": 5.0, "stale_after_windows": 12})
    cycle: list[str] = field(default_factory=lambda: ["refresh_children", "root", "maintain"])
    maintain: dict[str, Any] = field(default_factory=lambda: {"cover_divisions_with": None, "retire_quiet_cycles": 4,
                                                             "split_when_events_over": 400})
    triage: dict[str, Any] = field(default_factory=dict)  # reads_per_cycle, weights, lanes, coverage_every_cycles
    authority: dict[str, Any] = field(default_factory=dict)  # alerts_per_cycle, interrupts_per_day, ack_sla_windows, quiet_windows
    # the grammar of docs/OVERSIGHT_ARCHITECTURES.md §4; all optional, today's behaviour when absent
    partition: dict[str, Any] = field(default_factory=dict)  # by: cohort|field|resource_cluster|group|family|none, field, span, min_events
    levels: list[dict[str, Any]] = field(default_factory=list)  # [{role, span}]: readers inserted while span is exceeded (first level = sectors)
    standing: list[dict[str, Any]] = field(default_factory=list)  # [{role, scope, brief}]: spawned at start and kept
    questions: dict[str, str] = field(default_factory=dict)  # pack question kind -> role that answers it; '*' is the fallback
    cadence: dict[str, Any] = field(default_factory=dict)  # kind: windows|records|events, every
    human: dict[str, Any] = field(default_factory=dict)  # briefing_every, interrupt_at, approvals
    envelope: dict[str, Any] = field(default_factory=dict)  # what the director may improvise alone (§6.6)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["roles"] = {k: asdict(v) for k, v in self.roles.items()}
        d["helpers"] = {k: asdict(v) for k, v in self.helpers.items()}
        return d


class TopologyError(ValueError):
    pass


def from_dict(d: dict[str, Any], tid: str | None = None) -> Topology:
    d = copy.deepcopy(d)
    roles = {}
    for rid, r in (d.get("roles") or {}).items():
        r = dict(r)
        pt = r.pop("prompt_text", None)
        if pt is not None and pt.strip() and pt.strip() != RoleSpec(id=rid, title="", kind="", prompt=r.get("prompt", "")).prompt_text().strip():
            r["prompt"] = pt                    # edited in the UI: store inline
        r.setdefault("title", rid.replace("_", " ").title())
        r.setdefault("kind", rid)
        roles[rid] = RoleSpec(id=rid, **{k: v for k, v in r.items() if k != "id"})
    helpers = {hid: HelperSpec(id=hid, **{k: v for k, v in h.items() if k != "id"})
               for hid, h in (d.get("helpers") or {}).items()}
    base = Topology(id=tid or d.get("id", "custom"), title=d.get("title", tid or "Custom"),
                    description=d.get("description", ""), root=d.get("root", ""), roles=roles, helpers=helpers)
    for k in ("divisions", "scaling", "maintain", "triage", "authority", "partition", "questions", "cadence", "human", "envelope"):
        if d.get(k):
            getattr(base, k).update(d[k])
    for k in ("levels", "standing"):
        if d.get(k):
            setattr(base, k, list(d[k]))
    _aliases(base)
    if d.get("cycle"):
        base.cycle = list(d["cycle"])
    validate(base)
    return base


def _aliases(t: Topology) -> None:
    """The partition and levels blocks drive the older divisions/maintain keys, so the runtime has one source of truth."""
    by = t.partition.get("by")
    if by:
        t.divisions["strategy"] = {"cohort": "by_cohort", "field": "by_field", "resource_cluster": "by_resource_cluster",
                                   "group": "by_group", "family": "by_family", "none": "none"}.get(by, t.divisions.get("strategy"))
        if t.partition.get("field"):
            t.divisions["field"] = t.partition["field"]
        if t.partition.get("span"):
            t.divisions["cohorts_per_division"] = int(t.partition["span"])
            t.divisions["span"] = int(t.partition["span"])
        if "min_events" in t.partition:
            t.divisions["min_events"] = int(t.partition["min_events"])
    if t.levels and not t.maintain.get("sector_role"):
        t.maintain["sector_role"] = t.levels[0].get("role")
        t.maintain["sector_span"] = int(t.levels[0].get("span", 6))


def validate(t: Topology) -> None:
    errs = []
    by = t.partition.get("by")
    if by and by not in PARTITION_KINDS:
        errs.append(f"partition.by must be one of {PARTITION_KINDS}")
    if by == "field" and not t.partition.get("field"):
        errs.append("partition.by field needs partition.field")
    for i, lv in enumerate(t.levels):
        if lv.get("role") not in t.roles:
            errs.append(f"levels[{i}] references unknown role {lv.get('role')!r}")
    for i, st in enumerate(t.standing):
        if st.get("role") not in t.roles:
            errs.append(f"standing[{i}] references unknown role {st.get('role')!r}")
    for k, rid in t.questions.items():
        if rid not in t.roles:
            errs.append(f"questions[{k!r}] references unknown role {rid!r}")
    if t.cadence.get("kind") and t.cadence["kind"] not in CADENCE_KINDS:
        errs.append(f"cadence.kind must be one of {CADENCE_KINDS}")
    if t.human.get("interrupt_at") and t.human["interrupt_at"] not in LEVEL_NAMES:
        errs.append(f"human.interrupt_at must be one of {LEVEL_NAMES}")
    if t.root not in t.roles:
        errs.append(f"root role {t.root!r} is not defined")
    for r in t.roles.values():
        for s in r.can_spawn:
            if s not in t.roles:
                errs.append(f"{r.id}: can_spawn references unknown role {s!r}")
        if r.output != "custom" and r.output not in SCHEMAS:
            errs.append(f"{r.id}: unknown output schema {r.output!r} (known: {', '.join(SCHEMAS)}, or custom)")
        if r.output == "custom" and not r.output_schema:
            errs.append(f"{r.id}: output 'custom' needs output_schema")
        if r.memory not in MEMORY_MODES:
            errs.append(f"{r.id}: memory must be one of {MEMORY_MODES}")
        if r.scope not in SCOPE_KINDS:
            errs.append(f"{r.id}: scope must be one of {SCOPE_KINDS}")
        for tool in r.tools:
            ns, _, name = tool.partition(".")
            pool = EVIDENCE_TOOLS if ns == "evidence" else ORG_TOOLS if ns == "org" else None
            if pool is None or not any(fnmatch.fnmatch(n, name) for n in pool):
                errs.append(f"{r.id}: unknown tool {tool!r}")
        for h in r.native_subagents:
            if h not in t.helpers:
                errs.append(f"{r.id}: native subagent {h!r} is not defined under helpers")
        if r.backend == "external" and not r.command:
            errs.append(f"{r.id}: backend external needs command")
    if t.divisions.get("strategy") not in DIVISION_STRATEGIES:
        errs.append(f"divisions.strategy must be one of {DIVISION_STRATEGIES}")
    for key in ("sector_role", "audit_with"):
        if t.maintain.get(key) and t.maintain[key] not in t.roles:
            errs.append(f"maintain.{key} references unknown role {t.maintain[key]!r}")
    from swarmscope.agents.skills import list_skills
    known = {s["id"] for s in list_skills()}
    for r in t.roles.values():
        for sk in r.skills:
            if sk not in known:
                errs.append(f"{r.id}: unknown skill {sk!r} (known: {', '.join(sorted(known)) or 'none'})")
    cover = t.maintain.get("cover_divisions_with")
    if cover and cover not in t.roles:
        errs.append(f"maintain.cover_divisions_with references unknown role {cover!r}")
    for p in t.cycle:
        if p not in ("refresh_children", "root", "maintain"):
            errs.append(f"unknown cycle phase {p!r}")
    if errs:
        raise TopologyError("; ".join(errs))


def load_topology(tid: str) -> Topology:
    p = TOPOLOGY_DIR / f"{tid}.yaml"
    if not p.exists():
        raise FileNotFoundError(f"no topology {tid!r} in {TOPOLOGY_DIR}")
    return from_dict(yaml.safe_load(p.read_text(encoding="utf-8")), tid)


def list_topologies() -> list[dict[str, str]]:
    out = []
    for p in sorted(TOPOLOGY_DIR.glob("*.yaml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        out.append({"id": p.stem, "title": d.get("title", p.stem), "description": d.get("description", ""),
                    "roles": len(d.get("roles") or {})})
    return out


def save_topology(t: Topology, tid: str) -> Path:
    if not tid.replace("_", "").replace("-", "").isalnum():
        raise TopologyError("topology id may contain letters, digits, - and _ only")
    d = t.to_dict()
    d.pop("id", None)
    p = TOPOLOGY_DIR / f"{tid}.yaml"
    p.write_text(yaml.safe_dump(d, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return p
