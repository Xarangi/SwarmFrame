"""Run a swarm of real Claude Code agents under SwarmFrame oversight.

Each agent is a ClaudeSDKClient session driving the locally logged-in Claude Code CLI.
  hooks         PreToolUse / PostToolUse / UserPromptSubmit / Stop -> POST /ingest/claude-code
  can_use_tool  every permission request -> POST /api/control/decide (policy, pause, human approval)
  narration     assistant text -> Narration event (untrusted self-report)
  commands      WebSocket /ws/runner: message, interrupt, kill, pause/resume (pause is enforced in decide)

Usage:  swarmscope run-swarm runner/scenarios/tiny.yaml --server http://127.0.0.1:8765
"""
from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from swarmscope.ingest.packs import ROOT
from swarmscope.llm.router import find_claude_cli


class ManagedAgent:
    def __init__(self, spec: dict[str, Any], scenario: dict[str, Any], workdir: Path, server: str, http: httpx.AsyncClient):
        self.spec, self.scenario, self.workdir, self.server, self.http = spec, scenario, workdir, server, http
        self.id = f"run:{spec['label'].lower()}-{uuid.uuid4().hex[:4]}"
        self.client = None
        self.done = asyncio.Event()
        self.cost = 0.0

    def _base(self) -> dict[str, Any]:
        return {"swarm_agent_id": self.id, "swarm_label": self.spec["label"], "swarm_team": self.spec.get("team"),
                "swarm_task": self.spec["task"], "session_id": self.id, "cwd": str(self.workdir)}

    async def post(self, payload: dict[str, Any]) -> None:
        try:
            await self.http.post(f"{self.server}/ingest/claude-code", json={**self._base(), **payload}, timeout=10)
        except Exception:
            pass

    async def _hook(self, input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
        await self.post({k: v for k, v in dict(input_data).items() if k in (
            "hook_event_name", "tool_name", "tool_input", "tool_response", "prompt")})
        return {}

    async def _can_use_tool(self, tool_name: str, tool_input: dict[str, Any], context: Any):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
        try:
            r = await self.http.post(f"{self.server}/api/control/decide",
                                     json={"agent": self.id, "tool": tool_name, "input": tool_input}, timeout=660)
            d = r.json()
        except Exception as exc:
            d = {"behavior": "deny", "message": f"oversight unavailable: {exc}"}
        if d.get("behavior") == "allow":
            return PermissionResultAllow(updated_input=tool_input)
        return PermissionResultDeny(message=d.get("message", "Denied by oversight."), interrupt=bool(d.get("interrupt")))

    async def run(self) -> None:
        from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, HookMatcher, ResultMessage,
                                      TextBlock)
        sc = self.scenario
        hooks = {ev: [HookMatcher(hooks=[self._hook])] for ev in ("PreToolUse", "PostToolUse", "UserPromptSubmit")}
        opts = ClaudeAgentOptions(
            system_prompt={"type": "preset", "preset": "claude_code",
                           "append": sc.get("system_append", "") + f"\nYou are {self.spec['label']} on team "
                                                                    f"{self.spec.get('team', 'none')}."},
            model=sc.get("model", "claude-sonnet-5-5"), effort=sc.get("effort", "low"),
            max_turns=int(sc.get("max_turns", 6)),
            # opt-in: the CLI's cost estimate for some model ids runs high, so a tight cap can stop agents early
            max_budget_usd=float(sc["max_budget_usd_per_agent"]) if sc.get("max_budget_usd_per_agent") else None,
            cwd=str(self.workdir), tools=sc.get("tools", ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]),
            permission_mode="default", can_use_tool=self._can_use_tool, hooks=hooks, setting_sources=[],
            cli_path=find_claude_cli())
        await self.post({"hook_event_name": "SessionStart", "prompt": self.spec["task"]})
        async with ClaudeSDKClient(options=opts) as client:
            self.client = client
            await client.query(self.spec["task"])
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    text = " ".join(b.text for b in msg.content if isinstance(b, TextBlock)).strip()
                    if text:
                        await self.post({"hook_event_name": "Narration", "text": text[:4000]})
                elif isinstance(msg, ResultMessage):
                    self.cost = float(msg.total_cost_usd or 0)
        await self.post({"hook_event_name": "Stop", "cost_usd": self.cost})
        self.done.set()

    async def command(self, cmd: dict[str, Any]) -> None:
        if not self.client:
            return
        kind = cmd.get("kind")
        if kind in ("interrupt", "kill"):
            try:
                await self.client.interrupt()
            except Exception:
                pass
        elif kind == "message":
            try:
                await self.client.query(f"[Message from the human operator] {cmd.get('text', '')}")
            except Exception:
                pass


def load_scenario(path: str) -> dict[str, Any]:
    sc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    agents = list(sc.get("agents", []))
    for g in sc.get("generate", []):
        for i in range(int(g["count"])):
            agents.append({"label": g["label"].format(i=i + 1), "team": g.get("team"),
                           "task": g["task"].format(i=i + 1)})
    sc["agents"] = agents
    return sc


async def run_swarm(scenario_path: str, server: str = "http://127.0.0.1:8765") -> list[dict[str, Any]]:
    sc = load_scenario(scenario_path)
    run_id = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    root = ROOT / "data" / "runs" / run_id
    shared = root / "shared"
    shared.mkdir(parents=True, exist_ok=True)
    for rel, content in (sc.get("files") or {}).items():
        p = shared / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    async with httpx.AsyncClient() as http:
        agents = []
        for spec in sc["agents"]:
            wd = shared if sc.get("shared_workdir", True) else root / spec["label"]
            if not sc.get("shared_workdir", True):
                shutil.copytree(shared, wd, dirs_exist_ok=True)
            a = ManagedAgent(spec, sc, wd, server, http)
            agents.append(a)
            await http.post(f"{server}/api/control/register", json={"agent": a.id, "label": spec["label"],
                                                                    "team": spec.get("team"), "task": spec["task"]})
        listener = asyncio.create_task(_listen(server, {a.id: a for a in agents}))
        conc = asyncio.Semaphore(int(sc.get("concurrency", 4)))

        async def guarded(a: ManagedAgent):
            async with conc:
                try:
                    await a.run()
                except Exception as exc:
                    await a.post({"hook_event_name": "Narration", "text": f"[runner] agent failed: {type(exc).__name__}"})
                    await a.post({"hook_event_name": "Stop", "cost_usd": a.cost})
        await asyncio.gather(*(guarded(a) for a in agents))
        listener.cancel()
    return [{"agent": a.spec["label"], "cost_usd": a.cost} for a in agents]


async def _listen(server: str, agents: dict[str, ManagedAgent]) -> None:
    import websockets
    url = server.replace("http", "ws", 1) + "/ws/runner"
    while True:
        try:
            async with websockets.connect(url) as ws:
                async for raw in ws:
                    cmd = json.loads(raw)
                    for t in cmd.get("targets", []):
                        if t in agents:
                            await agents[t].command(cmd)
        except asyncio.CancelledError:
            return
        except Exception:
            await asyncio.sleep(2)
