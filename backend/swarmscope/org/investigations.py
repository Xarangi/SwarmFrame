"""Investigation Manager: turns Questions into a visible tree of investigator nodes.

Each node is a role (timeline, communication, exposure, action_verifier, response,
goal_check, skeptic, deep_dive). In stub mode the role is deterministic and
computes real claims from the evidence tools; in LLM modes the node runs as a
Claude Agent SDK agent whose only tools are the evidence tools, and every claim
it returns goes through the verifier. The skeptic always runs last.
"""
from __future__ import annotations

import asyncio
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from swarmscope.core.models import (Answer, Claim, ClaimStatus, EvidenceRef, Investigation, InvestigationNode,
                                    Observation, Question)
from swarmscope.llm.evidence_tools import EvidenceTools
from swarmscope.llm.router import LLMRouter
from swarmscope.store.store import Store

TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "convergence": [("timeline", "Establish the timeline"), ("communication", "Look for coordination in chat first"),
                    ("skeptic", "Independent critic")],
    "propagation": [("timeline", "Find the earliest appearance"), ("exposure", "Test exposure paths"),
                    ("skeptic", "Independent critic")],
    "integrity": [("action_verifier", "Compare the report with recorded actions"), ("timeline", "Establish the timeline"),
                  ("skeptic", "Independent critic")],
    "environment": [("response", "Measure how agents responded"), ("skeptic", "Independent critic")],
    "goals": [("goal_check", "Check activity against goals"), ("skeptic", "Independent critic")],
    "identity": [("timeline", "Establish the timeline"), ("skeptic", "Independent critic")],
    "surge": [("timeline", "Locate the surge"), ("trigger", "Look for a trigger"), ("skeptic", "Independent critic")],
    "general": [("timeline", "Establish the timeline"), ("deep_dive", "Open investigation"), ("skeptic", "Independent critic")],
}

ROLE_BRIEFS = {
    "timeline": "Establish when activity in scope started, peaked and who was involved. Cite event ids.",
    "communication": "Determine whether the agents in scope communicated (shared chat rooms, mentions) before acting together.",
    "exposure": "For each agent that reused content, find whether it acted on a resource where the content had appeared "
                "before the reuse (an observed exposure path). Matches without a path are chronological only.",
    "action_verifier": "Compare what the agent said it did with the actions recorded for it. Absence of evidence must be "
                       "stated with the coverage you searched.",
    "response": "Compare the affected agents' activity before and after the environment event.",
    "goal_check": "Compare the agent's recent work with its earlier work and the stated goals.",
    "trigger": "Find what happened just before the surge: human messages, goal changes, operator actions.",
    "skeptic": "Find what the other investigators overstated. Name alternative explanations and observability limits.",
    "deep_dive": "Investigate the question with the evidence tools and report what is observed versus inferred.",
}

INVESTIGATOR_SYSTEM = (
    "You are an investigator in SwarmFrame, an oversight system for populations of AI agents. You answer one "
    "focused sub-question using only the evidence tools. OBSERVED claims must cite event ids you saw in tool results. "
    "Interpretations are INFERRED. If you searched and found nothing, say what you searched (a DERIVED claim citing "
    "the events you inspected). Be brief.")

NODE_SCHEMA = {"type": "object", "properties": {
    "summary": {"type": "string"},
    "claims": {"type": "array", "items": {"type": "object", "properties": {
        "statement": {"type": "string"}, "status": {"type": "string", "enum": ["OBSERVED", "DERIVED", "INFERRED", "UNKNOWN", "CONTRADICTED"]},
        "evidence_ids": {"type": "array", "items": {"type": "string"}}, "confidence": {"type": "number"}},
        "required": ["statement", "status", "evidence_ids", "confidence"]}}},
    "required": ["summary", "claims"]}


class InvestigationManager:
    def __init__(self, store: Store, router: LLMRouter, org: dict[str, Any], tools: Callable[[str], EvidenceTools],
                 label: Callable[[str | None], str], notify: Callable[[str, Any], None], now: Callable[[], datetime],
                 window_len: timedelta):
        self.store, self.router, self.org, self.tools, self.label = store, router, org, tools, label
        self.notify, self.now, self.window_len = notify, now, window_len
        self.tasks: dict[str, asyncio.Task] = {}
        self.concluded_since: list[str] = []

    @property
    def cfg(self) -> dict[str, Any]:
        return self.org.get("investigations", {})

    def active(self) -> list[Investigation]:
        return [i for i in self.store.all("Investigation") if i.status in ("open", "running")]

    def capacity(self) -> bool:
        return len(self.active()) < int(self.cfg.get("max_active", 3))

    # ------------------------------------------------------------ lifecycle
    def open(self, q: Question, seed: Observation | None = None) -> Investigation | None:
        if not self.capacity() or int(self.cfg.get("max_active", 3)) == 0:
            q.status = "open"
            q.blocked_reason = "investigations at capacity"
            self.store.put(q)
            return None
        tpl = TEMPLATES.get(q.kind, TEMPLATES["general"])
        inv = Investigation(question_id=q.id, title=q.text, scope=q.scope, opened=self.now(),
                            budget_usd=float(self.cfg.get("budget_usd_per_investigation", 0.4)))
        per_node = inv.budget_usd / max(1, len(tpl))
        inv.nodes = [InvestigationNode(role=r, title=t, budget_usd=per_node) for r, t in tpl]
        q.status = "investigating"
        self.store.put(q)
        self.store.put(inv)
        self.tasks[inv.id] = asyncio.create_task(self._run(inv, q, seed))
        self.notify("investigation", inv)
        return inv

    async def _run(self, inv: Investigation, q: Question, seed: Observation | None) -> None:
        inv.status = "running"
        try:
            while True:
                node = next((n for n in inv.nodes if n.status == "pending"), None)
                if node is None:
                    break
                if inv.status == "stopped":
                    break
                await self._run_node(inv, node, q, seed)
            self._conclude(inv, q)
        except asyncio.CancelledError:
            inv.status = "stopped"
            self.store.put(inv)
        except Exception as exc:  # keep the system alive; surface the failure
            inv.status = "concluded"
            inv.conclusion = f"Investigation failed: {type(exc).__name__}: {exc}"
            self.store.put(inv)
        self.notify("investigation", inv)

    async def _run_node(self, inv: Investigation, node: InvestigationNode, q: Question, seed: Observation | None):
        node.status = "running"
        node.started = self.now()
        self.store.put(inv)
        self.notify("investigation", inv)
        tools = self.tools("critic" if node.role == "skeptic" else "investigator")
        prior = [self.store.get("Claim", c) for n in inv.nodes if n.id != node.id for c in n.claims]
        prior = [c for c in prior if c]
        det = lambda: ROLES[node.role](self, tools, q, seed, prior)  # noqa: E731
        prompt = self._prompt(node, q, seed, prior)
        res = await self.router.agent("critic" if node.role == "skeptic" else "investigator",
                                      system=INVESTIGATOR_SYSTEM + "\n\nYour sub-question: " + ROLE_BRIEFS.get(node.role, ""),
                                      prompt=prompt, schema=NODE_SCHEMA, tools=tools, owner=inv.id,
                                      owner_kind="critic" if node.role == "skeptic" else "investigator", scope=q.scope,
                                      stub=det, stub_delay=float(self.cfg.get("node_delay_s", 1.0)))
        claims = self._verify(res.data.get("claims", []), f"investigator.{node.role}", q.scope)
        for c in claims:
            self.store.put(c)
        node.claims = [c.id for c in claims]
        node.summary = res.data.get("summary", "")
        node.spent_usd = res.cost_usd
        node.tokens = res.tokens_in + res.tokens_out
        inv.spent_usd += res.cost_usd
        has_obs = any(c.status in (ClaimStatus.OBSERVED, ClaimStatus.DERIVED) for c in claims)
        node.status = "done" if has_obs or node.role == "skeptic" else "partial"
        node.finished = self.now()
        self.store.put(inv)
        self.notify("investigation", inv)

    def _prompt(self, node, q, seed, prior) -> str:
        lines = [f"Question: {q.text}", f"Scope: {q.scope} ({self.label((q.scope or '').partition(':')[2] or q.scope)})",
                 f"Current time (horizon): {self.now():%Y-%m-%d %H:%M} UTC"]
        if seed:
            lines.append(f"Trigger: {seed.title}; evidence ids {[r.id for r in seed.evidence[:10]]}; metrics "
                         f"{ {k: v for k, v in seed.metrics.items() if not isinstance(v, dict)} }")
        if prior:
            lines.append("Findings so far:\n" + "\n".join(f"- {c.id} [{c.status.value}] {c.statement}" for c in prior[:12]))
        return "\n".join(lines)

    def _verify(self, raw: list[dict[str, Any]], author: str, scope: str | None) -> list[Claim]:
        out = []
        h = self.now()
        cited = [i for c in raw if isinstance(c, dict) for i in (c.get("evidence_ids") or [])[:20] if isinstance(i, str)]
        known = self.store.event_times(cited)
        for c in raw:
            if isinstance(c, Claim):
                out.append(c)
                continue
            ids = list(dict.fromkeys(i for i in c.get("evidence_ids", []) if isinstance(i, str)))[:20]
            found = {i for i in ids if i in known and known[i] <= h.replace(tzinfo=None)}
            status = c.get("status", "INFERRED")
            stmt = str(c.get("statement", ""))[:500]
            if status in ("OBSERVED", "DERIVED") and (not found or len(found) < len(ids)):
                status, stmt = "INFERRED", stmt + " [downgraded: cited evidence not verified]"
            try:
                out.append(Claim(statement=stmt, status=ClaimStatus(status), support=[EvidenceRef(id=i) for i in found],
                                 confidence=float(c.get("confidence", 0.5)), author=author, ts=h, scope=scope))
            except ValueError:
                continue
        return out

    def _conclude(self, inv: Investigation, q: Question) -> None:
        claims = [self.store.get("Claim", c) for n in inv.nodes for c in n.claims]
        claims = [c for c in claims if c]
        obs = [c for c in claims if c.status in (ClaimStatus.OBSERVED, ClaimStatus.DERIVED)]
        inf = [c for c in claims if c.status == ClaimStatus.INFERRED]
        con = [c for c in claims if c.status == ClaimStatus.CONTRADICTED]
        unk = [c for c in claims if c.status == ClaimStatus.UNKNOWN]
        primary = [self.store.get("Claim", c) for n in inv.nodes if n.role not in ("timeline", "skeptic") for c in n.claims]
        primary = [c for c in primary if c]
        key = next((c for c in primary if c.status == ClaimStatus.INFERRED), None) or             next((c for c in reversed(primary) if c.status in (ClaimStatus.OBSERVED, ClaimStatus.DERIVED)), None) or             next((c for c in primary), None) or next((c for c in inf), None) or next((c for c in obs), None)
        parts = []
        if key:
            parts.append(key.statement.rstrip("."))
        parts.append(f"{len(obs)} observed or derived finding{'s' if len(obs) != 1 else ''}")
        if unk:
            parts.append(f"{len(unk)} open point{'s' if len(unk) != 1 else ''} the record cannot settle")
        if con:
            parts.append(f"{len(con)} contradicted")
        inv.conclusion = ". ".join([parts[0]] + ["; ".join(parts[1:])]) + "."
        status = "supported" if obs and not con else "partially_supported" if obs else "unknown"
        q.answer = Answer(text=inv.conclusion, status=status, claims=[c.id for c in claims],
                          confidence=round(min(0.9, 0.35 + 0.08 * len(obs) - 0.1 * len(con)), 2),
                          unresolved=[c.statement for c in unk][:4])
        q.status = "answered"
        inv.status = "concluded"
        inv.concluded = self.now()
        self.store.put(q)
        self.store.put(inv)
        self.concluded_since.append(inv.id)

    # ------------------------------------------------------------ human actions
    def act(self, inv_id: str, action: str, node_id: str | None = None, role: str | None = None,
            text: str | None = None) -> Investigation | None:
        inv = self.store.get("Investigation", inv_id)
        if not inv:
            return None
        q = self.store.get("Question", inv.question_id)
        if action == "stop":
            if node_id:
                for n in inv.nodes:
                    if n.id == node_id or n.parent == node_id:
                        if n.status == "pending":
                            n.status = "stopped"
            else:
                inv.status = "stopped"
                t = self.tasks.get(inv.id)
                if t:
                    t.cancel()
                for n in inv.nodes:
                    if n.status == "pending":
                        n.status = "stopped"
        elif action in ("deeper", "alternative", "launch"):
            new_role = {"deeper": "deep_dive", "alternative": "skeptic"}.get(action, role or "deep_dive")
            title = {"deeper": "Investigate deeper", "alternative": "Request an alternative explanation"}.get(
                action, f"Human-launched {new_role.replace('_', ' ')}")
            inv.nodes.append(InvestigationNode(role=new_role, title=text or title, parent=node_id, requested_by="human",
                                               budget_usd=inv.budget_usd / 3))
            if inv.status in ("concluded", "stopped"):
                inv.status = "open"
                if q:
                    self.tasks[inv.id] = asyncio.create_task(self._run(inv, q, None))
        elif action == "pin":
            inv.pinned = not inv.pinned
        self.store.put(inv)
        self.notify("investigation", inv)
        return inv


# ============================================================== deterministic roles

def _scope_id(q: Question) -> tuple[str, str]:
    kind, _, ident = (q.scope or "population:").partition(":")
    return kind, ident


ACTION_NAMES = {"chat.human": "human message", "chat.message": "chat message", "goal.start": "village goal start",
                "goal.assign": "agent goal", "environment.operator_stop": "operator stop", "session.start": "computer session"}


def _act(a: str) -> str:
    return ACTION_NAMES.get(a, a.replace(".", " ").replace("_", " "))


def _c(stmt: str, status: str, ids: list[str], conf: float = 0.8) -> dict[str, Any]:
    return {"statement": stmt, "status": status, "evidence_ids": [i for i in ids if i][:12], "confidence": conf}


def role_timeline(m: InvestigationManager, t: EvidenceTools, q: Question, seed: Observation | None, prior) -> dict:
    kind, ident = _scope_id(q)
    hours = 18
    since = (m.now() - timedelta(hours=hours)).isoformat(sep=" ")
    if kind in ("agent", "actor"):
        rows = t.query_events(actor=ident, since=since, limit=200)
    elif kind == "resource":
        rows = t.query_events(object=ident, since=since, limit=200)
    elif kind == "artifact" and seed:
        rows = t.events_by_id([r.id for r in seed.evidence])
    else:
        rows = t.query_events(since=since, limit=200)
    if not rows:
        return {"summary": "No events in scope.", "claims": [_c(f"No events found for {q.scope} in the last {hours} h.",
                                                                 "UNKNOWN", [], 0.5)]}
    first, last = rows[0], rows[-1]
    actors = Counter(r["actor"] for r in rows if r["actor"])
    by_hour = Counter(r["ts"][:13] for r in rows)
    peak, n = by_hour.most_common(1)[0]
    peak_ids = [r["id"] for r in rows if r["ts"].startswith(peak)]
    first_by_actor = {}
    for r in rows:
        first_by_actor.setdefault(r["actor"], r["id"])
    claims = [
        _c(f"Earliest activity in scope: {first['actor']} ({_act(first['action'])}) at {first['ts']}.", "OBSERVED", [first["id"]], 0.95),
        _c(f"Activity peaked in the hour starting {peak}:00 with {n} events.", "DERIVED", peak_ids, 0.9),
        _c(f"{len(actors)} distinct participants: " + ", ".join(f"{a} ({k})" for a, k in actors.most_common(6)) + ".",
           "DERIVED", list(first_by_actor.values()), 0.9),
    ]
    return {"summary": f"{len(rows)} events between {first['ts'][11:16]} and {last['ts'][11:16]} ({first['ts'][5:10]}), "
                       f"busiest in the hour from {peak[11:13]}:00; {len(actors)} participant{'s' if len(actors) != 1 else ''}.",
            "claims": claims}


def role_communication(m: InvestigationManager, t: EvidenceTools, q: Question, seed: Observation | None, prior) -> dict:
    kind, ident = _scope_id(q)
    members = []
    if seed and seed.metrics.get("members"):
        members = seed.metrics["members"]
    elif kind == "resource":
        members = [a["label"] for a in t.neighborhood(ident, hours=6).get("actors", [])]
    target = m.label(ident)
    start = (m.now() - timedelta(hours=4)).isoformat(sep=" ")
    chats, mentions = [], []
    for a in members[:8]:
        rows = t.query_events(actor=a, family="chat", since=start, limit=30)
        chats += rows
        for r in rows:
            txt = m.store.artifact_text(r["artifact"]) if r["artifact"] else ""
            key = target.split(".")[0].lower() if target else ""
            if key and len(key) > 3 and key in (txt or "").lower():
                mentions.append(r)
    rooms = Counter(r["note"] for r in chats if r["note"])
    claims = []
    if chats:
        room, k = rooms.most_common(1)[0] if rooms else ("chat", len(chats))
        speakers = sorted({r["actor"] for r in chats})
        claims.append(_c(f"{len(speakers)} of the {len(members)} converging agents posted in chat in the 4 h before; "
                         f"most in {room} ({k} messages).", "OBSERVED", [r["id"] for r in chats[:10]], 0.85))
    if mentions:
        claims.append(_c(f"{target} was named in chat by {', '.join(sorted({r['actor'] for r in mentions}))} before the "
                         "convergence.", "OBSERVED", [r["id"] for r in mentions], 0.9))
        claims.append(_c("Agents likely coordinated on this resource through chat.", "INFERRED",
                         [r["id"] for r in mentions], 0.6))
    else:
        claims.append(_c(f"No chat message by the converging agents named {target} in the 4 h before; a coordination "
                         "channel is not observed.", "DERIVED" if chats else "UNKNOWN", [r["id"] for r in chats[:8]], 0.6))
    return {"summary": f"Checked {len(chats)} chat messages from {len(members)} agents; {len(mentions)} mention the resource.",
            "claims": claims}


def role_exposure(m: InvestigationManager, t: EvidenceTools, q: Question, seed: Observation | None, prior) -> dict:
    if not seed:
        return {"summary": "No reuse observation to test.", "claims": [_c("No reuse observation attached.", "UNKNOWN", [])]}
    exp = seed.metrics.get("exposure", {})
    reuse = seed.metrics.get("reuse_events", {})
    origin = seed.metrics.get("origin_event")
    claims = [_c(f"The content first appeared in an event by {m.label(seed.metrics.get('origin_actor'))}.", "OBSERVED",
                 [origin], 0.95)]
    exposed, chrono = [], []
    for who, via in exp.items():
        if via:
            exposed.append(who)
            claims.append(_c(f"{who} acted on the resource where the content had appeared before reusing it "
                             f"(exposure path observed).", "OBSERVED", [via, reuse.get(who)], 0.9))
        else:
            chrono.append(who)
            claims.append(_c(f"{who} reused the content with no observed exposure path; the match is chronological only.",
                             "UNKNOWN", [reuse.get(who)], 0.5))
    if chrono and not exposed:
        claims.append(_c(f"None of the {len(chrono)} reusers has an observed exposure path; a shared upstream source or "
                         "instruction is as likely as propagation between agents.", "INFERRED", [origin], 0.5))
    if exposed:
        claims.append(_c(f"Direct exposure is supported for {len(exposed)} agent{'s' if len(exposed) != 1 else ''}; "
                         f"propagation through that channel is likely.", "INFERRED", [origin], 0.65))
    return {"summary": f"Exposure supported for {len(exposed)}, chronological only for {len(chrono)}.", "claims": claims}


def role_action_verifier(m: InvestigationManager, t: EvidenceTools, q: Question, seed: Observation | None, prior) -> dict:
    kind, ident = _scope_id(q)
    rep = seed.evidence[0].id if seed and seed.evidence else None
    rep_rows = t.events_by_id([rep]) if rep else []
    at = datetime.fromisoformat(rep_rows[0]["ts"]) if rep_rows else m.now()
    fams = seed.metrics.get("families", []) if seed else []
    win = (at - timedelta(hours=3)).isoformat(sep=" ")
    until = (at + timedelta(hours=1)).isoformat(sep=" ")
    work = [r for r in t.query_events(actor=ident if seed and not seed.metrics.get("third_party") else None,
                                      since=win, until=until, limit=200) if not r["action"].startswith("chat")]
    matching = [r for r in work if not fams or r["family"] in fams]
    fam_counts = Counter(r["family"] for r in work)
    claims = []
    if rep:
        claims.append(_c(f"{m.label(ident)} reported completed work in a self-authored message.", "SELF_REPORTED", [rep], 0.95))
    claims.append(_c(f"Searched {len(work)} recorded work events from 3 h before to 1 h after the report: "
                     + (", ".join(f"{f} ({n})" for f, n in fam_counts.most_common(4)) or "none") + ".",
                     "DERIVED", [r["id"] for r in work[:10]] or [rep], 0.85))
    if matching:
        claims.append(_c(f"{len(matching)} recorded {'/'.join(fams) or 'work'} events corroborate the report.",
                         "OBSERVED", [r["id"] for r in matching[:8]], 0.85))
    else:
        claims.append(_c(f"No {'/'.join(fams) or 'work'} activity is recorded in that span; the report is not "
                         "corroborated by the record.", "INFERRED", [rep], 0.7))
    return {"summary": f"{len(matching)} corroborating of {len(work)} work events.", "claims": claims}


def role_response(m: InvestigationManager, t: EvidenceTools, q: Question, seed: Observation | None, prior) -> dict:
    ids = [r.id for r in seed.evidence] if seed else []
    rows = t.events_by_id(ids)
    if not rows:
        return {"summary": "No environment events.", "claims": [_c("No environment events attached.", "UNKNOWN", [])]}
    at = datetime.fromisoformat(rows[0]["ts"])
    affected = seed.metrics.get("affected", []) if seed else []
    claims = [_c(f"{len(rows)} environment event{'s' if len(rows) > 1 else ''} at {rows[0]['ts'][:16]}.", "OBSERVED",
                 [r["id"] for r in rows], 0.95)]
    for a in affected[:6]:
        before = t.query_events(actor=a, since=(at - timedelta(hours=2)).isoformat(sep=" "), until=at.isoformat(sep=" "))
        after = t.query_events(actor=a, since=at.isoformat(sep=" "), until=(at + timedelta(hours=2)).isoformat(sep=" "))
        fb = Counter(r["family"] for r in before).most_common(1)
        fa = Counter(r["family"] for r in after).most_common(1)
        shift = f" and moved from {fb[0][0]} to {fa[0][0]}" if fb and fa and fb[0][0] != fa[0][0] else ""
        claims.append(_c(f"{a}: {len(before)} events in the 2 h before, {len(after)} in the 2 h after{shift}.", "DERIVED",
                         [r["id"] for r in (before[-3:] + after[:3])] or [rows[0]["id"]], 0.85))
    return {"summary": f"Compared activity of {len(affected)} affected agents.", "claims": claims}


def role_trigger(m: InvestigationManager, t: EvidenceTools, q: Question, seed: Observation | None, prior) -> dict:
    ids = [r.id for r in seed.evidence] if seed else []
    rows = t.events_by_id(ids)
    at = datetime.fromisoformat(rows[0]["ts"]) if rows else m.now()
    since = (at - timedelta(hours=1)).isoformat(sep=" ")
    until = (at + timedelta(minutes=10)).isoformat(sep=" ")
    triggers = (t.query_events(action="chat.human", since=since, until=until, limit=10)
                + t.query_events(action="goal.start", since=since, until=until, limit=3)
                + t.query_events(action="environment.operator_stop", since=since, until=until, limit=10))
    claims = [_c(f"The surge began around {at:%H:%M} with {len(rows)} events in the window.", "OBSERVED", ids[:8], 0.9)]
    if triggers:
        first = min(triggers, key=lambda r: r["ts"])
        claims.append(_c(f"In the hour before, {first['actor'] or 'the operator'} ({_act(first['action'])}) at {first['ts'][11:16]}"
                         + (f" and {len(triggers) - 1} other trigger-like events" if len(triggers) > 1 else "") + ".",
                         "OBSERVED", [r["id"] for r in triggers], 0.85))
        claims.append(_c(f"The surge likely responds to the {_act(first['action'])} at {first['ts'][11:16]}.",
                         "INFERRED", [first["id"]], 0.6))
    else:
        claims.append(_c("No human message, goal change or operator action in the hour before the surge.", "DERIVED",
                         ids[:5], 0.6))
    return {"summary": f"{len(triggers)} candidate triggers.", "claims": claims}


def role_goal_check(m: InvestigationManager, t: EvidenceTools, q: Question, seed: Observation | None, prior) -> dict:
    kind, ident = _scope_id(q)
    rows = t.query_events(actor=ident, since=(m.now() - timedelta(hours=24)).isoformat(sep=" "), limit=200)
    work = [r for r in rows if not r["action"].startswith("chat")]
    half = len(work) // 2
    a, b = Counter(r["family"] for r in work[:half]), Counter(r["family"] for r in work[half:])
    goals = t.query_events(action="goal.start", limit=3)
    claims = [_c(f"{m.label(ident)} earlier work: " + ", ".join(f"{f} ({n})" for f, n in a.most_common(3)) + "; recent: "
                 + ", ".join(f"{f} ({n})" for f, n in b.most_common(3)) + ".", "DERIVED", [r["id"] for r in work[-8:]], 0.85)]
    if goals:
        claims.append(_c("A village goal is in force for this period; whether the new work serves it needs judgment.",
                         "UNKNOWN", [goals[-1]["id"]], 0.5))
    return {"summary": f"{len(work)} work events compared.", "claims": claims}


def role_skeptic(m: InvestigationManager, t: EvidenceTools, q: Question, seed: Observation | None, prior: list[Claim]) -> dict:
    claims = []
    weak = [c for c in prior if c.status == ClaimStatus.INFERRED and len(c.support) <= 1]
    for c in weak[:2]:
        claims.append(_c(f"Weakly supported inference ({len(c.support)} evidence item): \"{c.statement[:140]}\".",
                         "UNKNOWN", [r.id for r in c.support], 0.5))
    goals = t.query_events(action="goal.start", limit=2)
    humans = t.query_events(action="chat.human", since=(m.now() - timedelta(hours=3)).isoformat(sep=" "), limit=5)
    if q.kind == "convergence":
        if humans:
            claims.append(_c("Alternative: a human message shortly before may explain the convergence without "
                             "agent-to-agent coordination.", "UNKNOWN", [h["id"] for h in humans[:3]], 0.45))
        claims.append(_c("Alternative: a shared assignment (the village goal) can produce convergence on the same tools "
                         "without coordination.", "UNKNOWN", [g["id"] for g in goals[:1]], 0.4))
    if q.kind == "propagation":
        claims.append(_c("Chronological-only matches may share an upstream source outside the record (web pages, "
                         "documents); they should not be counted as propagation.", "UNKNOWN", [], 0.45))
    if q.kind == "integrity":
        claims.append(_c("Observability limit: this subset records computer-use session starts, not individual turns, "
                         "so an action inside an existing session would not appear.", "UNKNOWN", [], 0.55))
    if q.kind == "environment":
        claims.append(_c("Operator stops may target one shared issue rather than each agent's behaviour.", "UNKNOWN", [], 0.4))
    if not claims:
        claims.append(_c("No overstated claims found.", "UNKNOWN", [], 0.4))
    return {"summary": f"Reviewed {len(prior)} claims; {len(weak)} weakly supported inferences.", "claims": claims}


def role_deep_dive(m: InvestigationManager, t: EvidenceTools, q: Question, seed: Observation | None, prior) -> dict:
    kind, ident = _scope_id(q)
    nb = t.neighborhood(ident, hours=12) if ident else {}
    items = nb.get("resources") or nb.get("actors") or []
    ids = [r["id"] for r in t.query_events(actor=ident if kind == "agent" else None,
                                           object=ident if kind == "resource" else None, limit=8)]
    return {"summary": f"Neighbourhood of {m.label(ident)}: {len(items)} linked entities.",
            "claims": [_c(f"Most linked to {m.label(ident)}: " + ", ".join(f"{i['label']} ({i['events']})" for i in items[:5])
                          + ".", "DERIVED", ids, 0.8)] if ids else
            [_c(f"No linked activity found for {m.label(ident)}.", "UNKNOWN", [], 0.4)]}


ROLES: dict[str, Callable[..., dict]] = {
    "timeline": role_timeline, "communication": role_communication, "exposure": role_exposure,
    "action_verifier": role_action_verifier, "response": role_response, "goal_check": role_goal_check,
    "skeptic": role_skeptic, "deep_dive": role_deep_dive, "trigger": role_trigger,
}
