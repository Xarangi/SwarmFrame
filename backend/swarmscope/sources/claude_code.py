"""Live Claude Code source: hook events -> evidence.

Hook payloads (from the SwarmFrame runner or any Claude Code session's settings.json hooks)
carry session_id, hook_event_name, tool_name, tool_input, tool_response, prompt, cwd.
One session = one agent. File paths become resources; written content becomes artifacts;
assistant narration is a self-report artifact (untrusted).
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import PurePath
from typing import Any

from swarmscope.core.models import Entity, EvidenceEvent
from swarmscope.ingest.adapter import Batch, make_artifact
from swarmscope.ingest.packs import SourcePack

TOOL_FAMILY = {"Read": "files", "Write": "files", "Edit": "files", "MultiEdit": "files", "NotebookEdit": "files",
               "Glob": "search", "Grep": "search", "Bash": "shell", "WebFetch": "web", "WebSearch": "web",
               "Task": "delegation", "Agent": "delegation", "TodoWrite": "planning"}
_URL = re.compile(r"https?://([^/\s]+)")


class ClaudeCodeAdapter:
    id = "claude_code"

    def __init__(self, pack: SourcePack):
        self.pack = pack

    def capabilities(self):
        return self.pack.capabilities

    def load(self, path: str | None) -> Batch:
        return Batch()     # live source: evidence arrives through ingest


def _short(v: Any, n: int = 160) -> str:
    s = v if isinstance(v, str) else json.dumps(v, default=str)
    return s[:n]


def _resource(tool: str, inp: dict[str, Any], cwd: str | None) -> tuple[str | None, str, str]:
    """(resource id, label, family)."""
    fam = TOOL_FAMILY.get(tool, "mcp" if tool.startswith("mcp__") else "other")
    fp = inp.get("file_path") or inp.get("notebook_path") or inp.get("path")
    if fp:
        p = str(fp)
        if cwd and p.startswith(cwd):
            p = p[len(cwd):].lstrip("/\\")
        name = PurePath(p).as_posix()
        return f"file:{name}", name, fam
    if tool in ("WebFetch", "WebSearch"):
        m = _URL.search(str(inp.get("url", "")))
        host = m.group(1) if m else (inp.get("query", "search")[:30])
        return f"host:{host}", host, fam
    if tool == "Bash":
        cmd = str(inp.get("command", "")).strip().split()
        head = cmd[0] if cmd else "sh"
        if head in ("python", "python3", "uv", "pytest", "node", "npm") and len(cmd) > 1:
            head = f"{head} {cmd[1]}"
        return f"cmd:{head}", head, fam
    if tool in ("Glob", "Grep"):
        return f"search:{inp.get('pattern', '')[:30]}", f"{tool} {inp.get('pattern', '')[:24]}", fam
    return None, tool, fam


def map_hook(payload: dict[str, Any], *, team: str | None = None, label: str | None = None,
             now: datetime | None = None) -> tuple[list[Entity], list, list[EvidenceEvent]]:
    now = now or datetime.utcnow()
    sid = str(payload.get("session_id") or payload.get("agent_id") or "unknown")
    agent_id = payload.get("swarm_agent_id") or f"cc:{sid[:12]}"
    name = payload.get("hook_event_name") or payload.get("event") or "Unknown"
    tool = payload.get("tool_name") or ""
    inp = payload.get("tool_input") or {}
    cwd = payload.get("cwd")
    ents = [Entity(id=agent_id, type="agent", source="claude_code", label=label or payload.get("swarm_label") or agent_id,
                   group=team or payload.get("swarm_team"), identity_confidence="strong",
                   attributes={"session_id": sid, "task": _short(payload.get("swarm_task", ""), 200)})]
    arts, evs = [], []
    eid = payload.get("event_id") or "ev:" + hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]
    base = dict(id=eid, ts=now, source="claude_code", actor=agent_id)
    if name in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
        rid, rlabel, fam = _resource(tool, inp, cwd)
        if rid:
            ents.append(Entity(id=rid, type="resource", source="claude_code", label=rlabel, group=fam,
                               attributes={"family": fam}))
        art_id = None
        if name == "PreToolUse" and tool in ("Write", "Edit", "MultiEdit"):
            text = inp.get("content") or inp.get("new_string") or ""
            if text:
                a, t = make_artifact(f"art:{eid}", str(text), now, agent_id, f"{tool}:{rlabel}")
                arts.append((a, t))
                art_id = a.id
        action = {"PreToolUse": "tool.request", "PostToolUse": "tool.invoke",
                  "PostToolUseFailure": "environment.error"}[name]
        resp = payload.get("tool_response")
        evs.append(EvidenceEvent(**base, action=action, object=rid, artifact=art_id,
                                 attributes={"family": fam, "tool": tool, "input": _short(inp),
                                             "ok": None if resp is None else not (isinstance(resp, dict) and resp.get("is_error"))},
                                 locator=f"hook:{name}"))
    elif name in ("SessionStart", "UserPromptSubmit"):
        prompt = payload.get("prompt") or payload.get("swarm_task") or ""
        art_id = None
        if prompt:
            a, t = make_artifact(f"art:{eid}", str(prompt), now, agent_id, "task prompt")
            arts.append((a, t))
            art_id = a.id
        evs.append(EvidenceEvent(**base, action="goal.assign", object=f"goal:{agent_id}", artifact=art_id,
                                 attributes={"family": "goal"}, locator=f"hook:{name}"))
    elif name == "Narration":
        a, t = make_artifact(f"art:{eid}", str(payload.get("text", "")), now, agent_id, "assistant narration")
        arts.append((a, t))
        evs.append(EvidenceEvent(**base, action="narration", object=None, artifact=a.id,
                                 attributes={"family": "narration"}, locator="assistant"))
    elif name in ("Stop", "SubagentStop", "SessionEnd"):
        evs.append(EvidenceEvent(**base, action="agent.stop", attributes={"family": "lifecycle",
                                                                          "cost_usd": payload.get("cost_usd")},
                                 locator=f"hook:{name}"))
    elif name == "Denied":
        rid, rlabel, fam = _resource(tool, inp, cwd)
        evs.append(EvidenceEvent(**base, action="environment.denied", object=rid,
                                 attributes={"family": fam, "tool": tool, "reason": payload.get("reason", ""),
                                             "target_agent": agent_id}, locator="control"))
    return ents, arts, evs
