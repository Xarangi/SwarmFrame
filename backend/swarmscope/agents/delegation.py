"""The delegation log: every time an agent fires off a sub-agent, re-tasks one, retires one, escalates, or decides
*not* to delegate, one line says who, what, and why.

Two kinds of delegation exist and both land here:
  * native     the agent's own Task-tool sub-agents (a self-briefed `reader`, or a topology helper); the runner
               captures the Task call's description and prompt from the session stream, and the result when it
               returns
  * managed    org-tool spawns, re-runs and retirements of persistent roles (spawn_agent, run_agent, retire_agent)
plus escalations through the cases ledger, proposals, and free-text `log_decision` notes ("not delegating because…").

The log is a plain JSON-lines file per session under data/runs/<source>_<started>/delegations.jsonl, so a person can
read it without the dashboard, and a tail is kept in memory for the API and the Organization page.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from swarmscope.ingest.packs import ROOT

if TYPE_CHECKING:
    from swarmscope.engine import Engine

KINDS = ("native", "managed", "rerun", "retire", "escalation", "proposal", "note")


class DelegationLog:
    def __init__(self, engine: "Engine", directory: Path | None = None, keep: int = 400):
        self.engine = engine
        self.dir = directory or (ROOT / "data" / "runs" / f"{engine.pack.id}_{time.strftime('%Y%m%d-%H%M%S', time.localtime(engine.started_wall))}")
        self.path = self.dir / "delegations.jsonl"
        self.tail: list[dict[str, Any]] = []
        self.keep = keep
        self.pending: dict[str, dict[str, Any]] = {}       # native Task tool_use_id -> entry awaiting its result
        self._ready = False

    def _ensure(self) -> None:
        if not self._ready:
            self.dir.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                self.path.write_text("", encoding="utf-8")
            self._ready = True

    def record(self, *, kind: str, by: str, role: str = "", node: str | None = None, target: str = "", why: str = "",
               brief: str = "", outcome: str = "", cost_usd: float = 0.0, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        if kind not in KINDS:
            kind = "note"
        entry = {"ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                 "stream_ts": self.engine.now().isoformat(timespec="minutes"),
                 "cycle": getattr(self.engine.agent_org, "cycle_index", 0), "kind": kind, "by": by, "role": role,
                 "node": node, "target": target, "why": str(why)[:500], "brief": str(brief)[:600],
                 "outcome": str(outcome)[:300], "cost_usd": round(float(cost_usd or 0), 4), **(extra or {})}
        self.tail.append(entry)
        self.tail = self.tail[-self.keep:]
        try:
            self._ensure()
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:                       # the log must never take an agent run down
            self.engine.router.errors.append(f"delegation log: {exc}")
        self.engine._notify("delegation", entry)
        return entry

    # ---------------------------------------------------------------- native Task calls, from the session stream
    def task_started(self, tool_use_id: str, *, by: str, role: str, node: str, inputs: dict[str, Any]) -> None:
        sub = str(inputs.get("subagent_type") or inputs.get("agent") or "reader")
        why = str(inputs.get("description") or "")[:200]
        self.pending[tool_use_id] = {"kind": "native", "by": by, "role": role, "node": node, "target": sub,
                                     "why": why, "brief": str(inputs.get("prompt") or "")[:600]}

    def task_finished(self, tool_use_id: str, content: Any, is_error: bool = False, final: bool = False) -> dict[str, Any] | None:
        e = self.pending.get(tool_use_id)
        if e is None:
            return None
        text = content if isinstance(content, str) else json.dumps(content, default=str) if content is not None else ""
        if not final and "launched successfully" in text:
            e["launched"] = True                      # an async sub-agent: the answer arrives as a task notification
            return None
        self.pending.pop(tool_use_id, None)
        e.pop("launched", None)
        return self.record(**e, outcome=("error: " if is_error else "") + text[:300])

    def flush_pending(self, outcome: str = "no result captured") -> None:
        for tid in list(self.pending):
            e = self.pending.pop(tid)
            self.record(**e, outcome=outcome)

    # ---------------------------------------------------------------- views
    def recent(self, n: int = 60, node: str | None = None) -> list[dict[str, Any]]:
        rows = [r for r in self.tail if node is None or r.get("node") == node]
        return rows[-n:]

    def summary(self) -> dict[str, Any]:
        by_kind: dict[str, int] = {}
        for r in self.tail:
            by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
        return {"path": str(self.path), "total": len(self.tail), "by_kind": by_kind, "recent": self.recent(40)}


def capture_task_blocks(msg: Any, log: DelegationLog, *, by: str, role: str, node: str) -> None:
    """Feed one SDK message; Task/Agent tool uses and their results become log entries."""
    try:
        from claude_agent_sdk import AssistantMessage, ToolResultBlock, ToolUseBlock, UserMessage
    except Exception:                                 # the SDK is optional in tests
        AssistantMessage = UserMessage = ToolUseBlock = ToolResultBlock = ()  # type: ignore[assignment]
    tid = getattr(msg, "tool_use_id", None)          # TaskNotificationMessage: an async sub-agent finished
    if tid and hasattr(msg, "summary") and str(tid) in log.pending:
        status = str(getattr(msg, "status", "") or "")
        log.task_finished(str(tid), getattr(msg, "summary", None) or status, is_error=status in ("failed", "error"), final=True)
        return
    content = getattr(msg, "content", None)
    if not isinstance(content, list):
        return
    for b in content:
        name = getattr(b, "name", None)
        if name in ("Task", "Agent") and hasattr(b, "input") and getattr(msg, "parent_tool_use_id", None) is None:
            log.task_started(str(getattr(b, "id", "")), by=by, role=role, node=node, inputs=dict(b.input or {}))
        elif hasattr(b, "tool_use_id") and str(getattr(b, "tool_use_id", "")) in log.pending:
            log.task_finished(str(b.tool_use_id), getattr(b, "content", None), bool(getattr(b, "is_error", False)))
