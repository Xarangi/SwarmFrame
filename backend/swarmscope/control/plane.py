"""Control plane for live swarms.

Every tool request from a managed agent goes through decide(): paused agents are held,
the pack's control policy may deny or hold for a human, otherwise it is allowed. Operator
actions (pause, resume, message, interrupt, kill, budget, allow, deny) are ControlActions,
logged to the briefing and sent to the runner (or the in-process simulator).
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any

from swarmscope.core.models import BriefingEntry, ControlAction, new_id
from swarmscope.sources.claude_code import map_hook


class ControlPlane:
    def __init__(self, engine):
        self.engine = engine
        self.agents: dict[str, dict[str, Any]] = {}
        self.pending: dict[str, dict[str, Any]] = {}
        self.runner_queues: list[asyncio.Queue] = []
        self.sim = None
        pol = engine.pack.source.get("control_policy") or {}
        self.deny = [(r["tool"], re.compile(r["pattern"], re.I), r.get("message", "Denied by policy.")) for r in pol.get("deny", [])]
        self.ask = [(r["tool"], re.compile(r["pattern"], re.I)) for r in pol.get("ask", [])]
        self.ask_timeout = float(pol.get("ask_timeout_s", 60))
        self.ask_default = pol.get("ask_default", "deny")
        self.policy_enabled = True
        self._ents: dict[str, Any] = {}
        self._arts: list = []
        self._evs: list = []
        self._known: set[str] = set()
        self._flusher: asyncio.Task | None = None

    def start(self) -> None:
        if self._flusher is None:
            self._flusher = asyncio.create_task(self._flush_loop())

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(0.4)
            self.flush()

    def flush(self) -> int:
        """Write buffered live evidence in one bulk insert per table."""
        if not (self._ents or self._arts or self._evs):
            return 0
        ents, arts, evs = list(self._ents.values()), self._arts, self._evs
        self._ents, self._arts, self._evs = {}, [], []
        st = self.engine.store
        st.add_entities(ents)
        st.add_artifacts(arts)
        st.add_events(evs)
        self.engine.scale.add_texts([(a.id, t) for a, t in arts])
        return len(evs)

    # ------------------------------------------------------------ ingest
    def ingest(self, payload: dict[str, Any]) -> int:
        a = payload.get("swarm_agent_id")
        meta = self.agents.get(a, {}) if a else {}
        ents, arts, evs = map_hook(payload, team=meta.get("group"), label=meta.get("label"), now=datetime.utcnow())
        for e in ents:
            if e.id not in self._known:
                self._known.add(e.id)
                self._ents[e.id] = e
        self._arts.extend(arts)
        self._evs.extend(evs)
        for e in evs:
            ag = self.agents.setdefault(e.actor, {"id": e.actor, "label": ents[0].label, "group": ents[0].group,
                                                  "status": "running", "cost_usd": 0.0, "tool_calls": 0, "pending": 0,
                                                  "started": e.ts})
            ag["last"] = e.ts
            if e.action == "tool.invoke":
                ag["tool_calls"] += 1
            if e.action == "agent.stop":
                ag["status"] = "done" if ag["status"] == "running" else ag["status"]
                ag["cost_usd"] = float(e.attributes.get("cost_usd") or ag["cost_usd"] or 0)
        return len(evs)

    def register(self, agent_id: str, label: str, group: str | None, task: str) -> None:
        self.agents.setdefault(agent_id, {"id": agent_id, "label": label, "group": group, "status": "running",
                                          "cost_usd": 0.0, "tool_calls": 0, "pending": 0, "task": task[:200],
                                          "started": datetime.utcnow()})

    # ------------------------------------------------------------ decisions
    async def decide(self, agent_id: str, tool: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        ag = self.agents.setdefault(agent_id, {"id": agent_id, "label": agent_id, "status": "running", "tool_calls": 0,
                                               "pending": 0, "cost_usd": 0.0})
        # paused agents are held until resumed or killed
        waited = 0.0
        while ag.get("status") == "paused" and waited < 600:
            await asyncio.sleep(0.5)
            waited += 0.5
        if ag.get("status") == "killed":
            return {"behavior": "deny", "message": "Agent stopped by operator.", "interrupt": True}
        text = tool_input.get("command") or tool_input.get("url") or tool_input.get("file_path") or str(tool_input)
        if self.policy_enabled:
            for t, pat, msg in self.deny:
                if t == tool and pat.search(str(text)):
                    self._denied(agent_id, tool, tool_input, msg)
                    return {"behavior": "deny", "message": msg}
            for t, pat in self.ask:
                if t == tool and pat.search(str(text)):
                    return await self._hold(agent_id, tool, tool_input, str(text))
        return {"behavior": "allow"}

    async def _hold(self, agent_id: str, tool: str, tool_input: dict[str, Any], text: str) -> dict[str, Any]:
        rid = new_id("req")
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.pending[rid] = {"id": rid, "agent": agent_id, "label": self.agents.get(agent_id, {}).get("label", agent_id),
                             "tool": tool, "input": text[:300], "ts": datetime.utcnow(), "future": fut,
                             "timeout_s": self.ask_timeout, "default": self.ask_default}
        self.agents[agent_id]["pending"] = self.agents[agent_id].get("pending", 0) + 1
        self.engine.store.put(BriefingEntry(ts=self.engine.now(), kind="CONTROL", level="ALERT",
                                            text=f"{self.pending[rid]['label']} wants to run {tool}: {text[:120]}. Waiting for a human."))
        self.engine.broadcast()
        try:
            decision = await asyncio.wait_for(fut, timeout=self.ask_timeout)
        except asyncio.TimeoutError:
            decision = self.ask_default
        self.pending.pop(rid, None)
        self.agents[agent_id]["pending"] = max(0, self.agents[agent_id].get("pending", 1) - 1)
        self.engine.broadcast()
        if decision == "allow":
            return {"behavior": "allow"}
        self._denied(agent_id, tool, tool_input, "Denied by the operator.")
        return {"behavior": "deny", "message": "The operator denied this action."}

    def _denied(self, agent_id: str, tool: str, tool_input: dict[str, Any], msg: str) -> None:
        self.ingest({"hook_event_name": "Denied", "swarm_agent_id": agent_id, "session_id": agent_id, "tool_name": tool,
                     "tool_input": tool_input, "reason": msg})

    # ------------------------------------------------------------ operator actions
    async def act(self, kind: str, target: str, payload: dict[str, Any] | None = None, actor: str = "human") -> ControlAction:
        payload = payload or {}
        act = ControlAction(ts=self.engine.now(), actor=actor, target=target, kind=kind, payload=payload)
        targets = self._targets(target)
        if kind in ("allow", "deny"):
            req = self.pending.get(target) or self.pending.get(payload.get("request", ""))
            if req and not req["future"].done():
                req["future"].set_result(kind)
                act.result = f"{kind} {req['tool']} for {req['label']}"
            else:
                act.result = "no such pending request"
        else:
            for a in targets:
                ag = self.agents.get(a)
                if not ag:
                    continue
                if kind == "pause" and ag["status"] == "running":
                    ag["status"] = "paused"
                elif kind == "resume" and ag["status"] == "paused":
                    ag["status"] = "running"
                elif kind == "kill":
                    ag["status"] = "killed"
                elif kind == "budget":
                    ag["budget_usd"] = payload.get("usd")
            await self._send({"kind": kind, "targets": targets, **payload})
            act.result = f"{kind} sent to {len(targets)} agent{'s' if len(targets) != 1 else ''}"
            if kind in ("pause", "kill"):
                from swarmscope.core.models import EvidenceEvent
                self.engine.store.add_events([EvidenceEvent(
                    id=new_id("ev"), ts=datetime.utcnow(), source="claude_code", actor="operator",
                    action="environment.operator_stop" if kind == "kill" else "control.pause", object=a,
                    attributes={"family": "control", "target_agent": a}, locator="control") for a in targets])
        self.engine.store.put(act)
        self.engine.store.put(BriefingEntry(ts=self.engine.now(), kind="CONTROL", level="INFO",
                                            text=f"Operator {kind}: {act.result}."))
        self.engine.broadcast()
        return act

    def _targets(self, target: str) -> list[str]:
        if target == "swarm":
            return list(self.agents)
        if target.startswith("group:"):
            g = target.split(":", 1)[1]
            return [a for a, m in self.agents.items() if m.get("group") == g]
        return [target]

    async def _send(self, cmd: dict[str, Any]) -> None:
        for q in list(self.runner_queues):
            q.put_nowait(cmd)
        if self.sim:
            self.sim.command(cmd)

    # ------------------------------------------------------------ views
    def summary(self) -> dict[str, Any]:
        statuses: dict[str, int] = {}
        for a in self.agents.values():
            statuses[a["status"]] = statuses.get(a["status"], 0) + 1
        return {"agents": len(self.agents), "statuses": statuses, "runner_connected": bool(self.runner_queues),
                "simulated": self.sim is not None, "policy_enabled": self.policy_enabled,
                "pending": [{k: v for k, v in p.items() if k != "future"} for p in self.pending.values()],
                "actions": [a.model_dump(mode="json") for a in sorted(self.engine.store.all("ControlAction"),
                                                                       key=lambda a: a.ts)[-15:]],
                "spent_usd": round(sum(a.get("cost_usd") or 0 for a in self.agents.values()), 4)}

    async def close(self) -> None:
        if self._flusher:
            self._flusher.cancel()
        if self.sim:
            self.sim.stop()
        for p in self.pending.values():
            if not p["future"].done():
                p["future"].set_result("deny")
