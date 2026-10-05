"""Proposals, the envelope and approvals: how a team changes its own shape (docs/OVERSIGHT_ARCHITECTURES.md §6.3–6.6).

A director or the Scout may *propose*: a new role (`propose_role`), a change to the grammar blocks (`propose_change`:
partition, levels, standing, questions, cadence, human, authority, triage), or a different base topology. Every
proposal is data validated against the topology grammar; nothing in it is an instruction to the system.

The **envelope** (topology.envelope, with defaults below) says what applies without a person: a reading-only role
whose tools are a subset of the director's, without raw access, on a model no stronger than the cap, at most N new
roles per cycle. Everything else waits in the **approvals queue** on the Brief. Applied proposals are reversible for
one cycle (`revert`). A person may **promote** the running team to a preset: the topology is saved under the
source's name and the pack's `oversight.yaml` points at it, so an improvised team becomes a library entry.

Proposals are applied between cycles (`apply_due`), never while agents hold slots.
"""
from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import yaml
from pydantic import BaseModel, Field

from swarmscope.agents.spec import TOPOLOGY_DIR, Topology, TopologyError, from_dict, save_topology
from swarmscope.core.models import new_id

if TYPE_CHECKING:
    from swarmscope.agents.runtime import AgentNode
    from swarmscope.engine import Engine

DEFAULT_ENVELOPE: dict[str, Any] = {
    "may_define_roles": True, "tools_subset_of": None, "raw_access": False, "max_model": "claude-sonnet-5-5",
    "budget_share_max": 0.3, "max_new_roles_per_cycle": 1, "approval": "auto_within_envelope"}
DEFAULT_APPROVALS = ["raw_access", "partition_change", "topology_change", "human_contract", "budget_over"]
CHANGE_BLOCKS = ("partition", "levels", "standing", "questions", "cadence", "human", "authority", "triage")
TIER = ["haiku", "sonnet", "opus", "fable"]


def tier(model: str | None) -> int:
    m = (model or "").lower()
    return next((i for i, t in enumerate(TIER) if t in m), 1)


class Proposal(BaseModel):
    id: str = Field(default_factory=lambda: new_id("prop"))
    ts: datetime
    by: str                                           # agent title, "scout", "human"
    kind: Literal["role", "change", "topology"]
    payload: dict[str, Any]
    reasons: list[str] = Field(default_factory=list)
    status: Literal["pending", "approved", "applied", "declined", "failed", "reverted"] = "pending"
    note: str = ""                                    # why it was auto-approved, held for a person, or failed
    needs: list[str] = Field(default_factory=list)    # the approval keys it touched (raw_access, partition_change, ...)
    applied_ts: datetime | None = None
    previous: dict[str, Any] | None = None            # the topology before it applied (for revert)
    title: str = ""


def describe(p: Proposal) -> str:
    if p.kind == "role":
        r = p.payload
        return f"a new role: {r.get('title') or r.get('id')} ({r.get('model', 'sonnet').split('-')[1] if '-' in r.get('model', '') else r.get('model', '')}, {r.get('scope', 'any')})"
    if p.kind == "topology":
        return f"switch the team to {p.payload.get('topology')}"
    keys = ", ".join(k for k in p.payload if k in CHANGE_BLOCKS)
    return f"change {keys or 'the team'}"


class Approvals:
    """The queue and its rules. Lives on the engine as `engine.approvals`."""

    def __init__(self, engine: "Engine"):
        self.engine = engine
        self.items: list[Proposal] = []
        self.roles_this_cycle = 0

    # ------------------------------------------------------------------ envelope
    def envelope(self) -> dict[str, Any]:
        return {**DEFAULT_ENVELOPE, **(self.engine.agent_org.topology.envelope or {})}

    def approvals_needed(self) -> list[str]:
        h = self.engine.agent_org.topology.human or {}
        return list(h.get("approvals", DEFAULT_APPROVALS))

    def check(self, p: Proposal) -> tuple[bool, str, list[str]]:
        """(auto, note, needs): may this apply without a person?"""
        env, need, t = self.envelope(), [], self.engine.agent_org.topology
        if p.by == "human":
            return True, "a person asked for it", []
        if env.get("approval") == "always_human":
            return False, "this team's envelope sends every proposal to a person", ["always_human"]
        if p.kind == "topology":
            need.append("topology_change")
        elif p.kind == "change":
            if any(k in p.payload for k in ("partition", "levels")):
                need.append("partition_change")
            if "human" in p.payload:
                need.append("human_contract")
            if "authority" in p.payload or ("triage" in p.payload and "reads_per_cycle" in (p.payload.get("triage") or {})):
                need.append("budget_over")
        else:
            r = p.payload
            if not env.get("may_define_roles", True):
                return False, "this team's envelope does not allow new roles", ["new_role"]
            if r.get("raw_access") and not env.get("raw_access"):
                need.append("raw_access")
            if tier(r.get("model")) > tier(env.get("max_model")):
                need.append("model_above_cap")
            ref = env.get("tools_subset_of") or t.root
            if ref in t.roles:
                allowed = set(t.roles[ref].evidence_tools()) | set(t.roles[ref].org_tools())
                try:
                    probe = from_dict({**t.to_dict(), "roles": {**t.to_dict()["roles"], "_probe": _role_dict(r, t)}}, "probe")
                    mine = set(probe.roles["_probe"].evidence_tools()) | set(probe.roles["_probe"].org_tools())
                except TopologyError as exc:
                    return False, f"invalid role: {exc}", ["invalid"]
                if not mine <= allowed:
                    need.append("tools_beyond_" + ref)
            if self.roles_this_cycle >= int(env.get("max_new_roles_per_cycle", 1)):
                need.append("roles_per_cycle")
        gated = [n for n in need if n in self.approvals_needed() or n in ("model_above_cap", "roles_per_cycle", "invalid")
                 or n.startswith("tools_beyond_")]
        if gated:
            return False, "needs a person: " + ", ".join(gated), gated
        return True, "within the envelope", need

    # ------------------------------------------------------------------ queue
    def add(self, kind: str, payload: dict[str, Any], by: str, reasons: list[str], title: str = "") -> Proposal:
        p = Proposal(ts=self.engine.now(), by=by, kind=kind, payload=payload, reasons=reasons[:6], title=title)
        auto, note, needs = self.check(p)
        p.note, p.needs = note, needs
        p.status = "approved" if auto else "pending"
        if auto and kind == "role":
            self.roles_this_cycle += 1
        self.items.append(p)
        self.items = self.items[-200:]
        self.engine.agent_org.event("proposal", None, by, f"Proposed {describe(p)}: {p.note}")
        self.engine.delegations.record(kind="proposal", by=by, target=describe(p), why="; ".join(reasons[:3]), outcome=p.note)
        self.engine._notify("proposal", p.model_dump(mode="json"))
        return p

    def get(self, pid: str) -> Proposal | None:
        return next((p for p in self.items if p.id == pid), None)

    def approve(self, pid: str, by: str = "human") -> Proposal:
        p = self.get(pid)
        if p is None:
            raise KeyError(pid)
        if p.status == "pending":
            p.status, p.note = "approved", f"approved by {by}"
            self.engine.agent_org.event("proposal", None, by, f"Approved {describe(p)}")
        return p

    def decline(self, pid: str, by: str = "human", reason: str = "") -> Proposal:
        p = self.get(pid)
        if p is None:
            raise KeyError(pid)
        if p.status in ("pending", "approved"):
            p.status, p.note = "declined", reason or f"declined by {by}"
            self.engine.agent_org.event("proposal", None, by, f"Declined {describe(p)}" + (f": {reason}" if reason else ""))
        return p

    def pending(self) -> list[Proposal]:
        return [p for p in self.items if p.status == "pending"]

    def new_cycle(self) -> None:
        self.roles_this_cycle = 0

    # ------------------------------------------------------------------ applying
    def apply_due(self) -> list[Proposal]:
        """Apply approved proposals; called between cycles, never while agents hold slots."""
        org = self.engine.agent_org
        if org.cycle_running:
            return []
        done = []
        for p in [x for x in self.items if x.status == "approved"]:
            try:
                before = org.topology.to_dict()
                t = self.build(p)
                org.set_topology(t, by=p.by if p.by != "human" else "human")
                p.status, p.applied_ts, p.previous = "applied", self.engine.now(), before
                org.event("proposal", None, p.by, f"Applied {describe(p)}")
                done.append(p)
            except (TopologyError, KeyError, ValueError) as exc:
                p.status, p.note = "failed", f"could not apply: {str(exc)[:300]}"
                org.event("proposal", None, p.by, f"Failed to apply {describe(p)}: {str(exc)[:160]}")
        if done:
            self.engine.broadcast()
        return done

    def revert(self, pid: str, by: str = "human") -> Proposal:
        p = self.get(pid)
        if p is None or p.status != "applied" or not p.previous:
            raise ValueError("only an applied proposal can be reverted")
        prev = dict(p.previous)
        tid = prev.pop("id", self.engine.agent_org.topology.id)
        self.engine.agent_org.set_topology(from_dict(prev, tid), by=by)
        p.status, p.note = "reverted", f"reverted by {by}"
        self.engine.agent_org.event("proposal", None, by, f"Reverted {describe(p)}")
        return p

    def build(self, p: Proposal) -> Topology:
        t = self.engine.agent_org.topology
        d = t.to_dict()
        tid = d.pop("id", t.id)
        if p.kind == "topology":
            from swarmscope.agents.selector import build
            return build(p.payload["topology"], p.payload.get("overrides"), p.payload.get("partition"))
        if p.kind == "role":
            r = p.payload
            rid = str(r.get("id") or r.get("title", "role")).lower().replace(" ", "_").replace("-", "_")
            if rid in d["roles"]:
                raise TopologyError(f"role {rid!r} already exists")
            d["roles"][rid] = _role_dict(r, t)
            root = d["roles"][d["root"]]
            root["can_spawn"] = sorted(set(root.get("can_spawn", [])) | {rid})
            if r.get("standing"):
                d.setdefault("standing", []).append({"role": rid, "scope": r.get("scope_id") or "population",
                                                     "brief": r.get("brief", "")})
            for k in (r.get("question_kinds") or []):
                d.setdefault("questions", {})[k] = rid
            return from_dict(d, tid)
        for k, v in p.payload.items():
            if k not in CHANGE_BLOCKS:
                continue
            if isinstance(v, dict) and isinstance(d.get(k), dict):
                d[k] = {**d[k], **v}
            else:
                d[k] = v
        return from_dict(d, tid)

    # ------------------------------------------------------------------ the Scout's output
    def absorb(self, node: "AgentNode", data: dict[str, Any]) -> list[Proposal]:
        """Turn an `architecture_proposal` report into proposals: a base switch, grammar changes, new roles."""
        org = self.engine.agent_org
        out: list[Proposal] = []
        reasons = [str(r) for r in (data.get("reasons") or [])][:6]
        base = data.get("base")
        if base and base != org.topology.id and (TOPOLOGY_DIR / f"{base}.yaml").exists():
            out.append(self.add("topology", {"topology": base, "partition": data.get("partition") or None}, node.title,
                                reasons, title=f"switch to {base}"))
        else:
            change = {k: data[k] for k in ("partition", "standing", "questions", "human") if data.get(k)}
            if change.get("partition") == org.topology.partition:
                change.pop("partition")
            if change.get("standing"):
                have = {(s.get("role"), s.get("scope", "population")) for s in org.topology.standing}
                change["standing"] = org.topology.standing + [s for s in change["standing"]
                                                              if (s.get("role"), s.get("scope", "population")) not in have]
            if change:
                out.append(self.add("change", change, node.title, reasons, title="refine the team"))
        for r in (data.get("new_roles") or [])[:3]:
            if isinstance(r, dict) and r.get("prompt"):
                out.append(self.add("role", r, node.title, reasons + [str(r.get("reason", ""))], title=r.get("title", "")))
        return out

    def summary(self) -> dict[str, Any]:
        pend = self.pending()
        return {"pending": [{**p.model_dump(mode="json"), "describe": describe(p)} for p in pend],
                "recent": [{**p.model_dump(mode="json"), "describe": describe(p)} for p in self.items[-12:]],
                "count": len(pend), "envelope": self.envelope(), "approvals_needed": self.approvals_needed()}


def _role_dict(r: dict[str, Any], t: Topology) -> dict[str, Any]:
    from swarmscope.agents.deterministic import BEHAVIOURS
    from swarmscope.agents.schemas import SCHEMAS
    kind = r.get("kind") if r.get("kind") in BEHAVIOURS else "generic"
    return {"title": str(r.get("title") or r.get("id") or "New role")[:60], "kind": kind,
            "description": str(r.get("description", ""))[:300], "prompt": str(r.get("prompt", ""))[:4000],
            "model": r.get("model", "claude-sonnet-5-5"), "effort": r.get("effort", "low"),
            "max_turns": int(r.get("max_turns", 8)), "tools": list(r.get("tools") or ["evidence.observations", "evidence.timeline"]),
            "raw_access": bool(r.get("raw_access", False)), "can_spawn": [],
            "output": r.get("output") if r.get("output") in SCHEMAS else "finding", "memory": r.get("memory", "none"),
            "scope": r.get("scope", "any"), "refresh_every_cycles": int(r.get("refresh_every_cycles", 0)),
            "skills": ["swarm-oversight"], "skill_refs": list(r.get("skill_refs") or ["specialist", "report_contract"])}


def promote_preset(engine: "Engine", name: str | None = None, packs_dir: Path | None = None) -> dict[str, Any]:
    """Save the running team as a topology and point the source pack's oversight.yaml at it."""
    from swarmscope.ingest.packs import PACKS_DIR
    t = engine.agent_org.topology
    tid = (name or f"{engine.pack.id}_team").lower().replace(" ", "_").replace("-", "_")
    path = save_topology(t, tid)
    team = engine.team_summary()
    reasons = "; ".join(team.get("reasons") or [])
    ov = {"topology": tid, "reason": f"promoted from a running session on {engine.now():%Y-%m-%d}"
                                     + (f"; {reasons}" if reasons else "")}
    pdir = (packs_dir or PACKS_DIR) / engine.pack.id
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "oversight.yaml").write_text(
        "# Written by promote_preset: the team that was running became this source's preset.\n"
        + yaml.safe_dump(ov, sort_keys=False, allow_unicode=True), encoding="utf-8")
    engine.pack.oversight = ov
    engine.agent_org.event("topology", None, "human", f"Promoted the running team to preset {tid}")
    return {"topology": tid, "path": str(path), "oversight": str(pdir / "oversight.yaml")}
