"""LLM layer. Every unit of cognition goes through the router, which picks a backend
per role from the org config and records an AttentionRecord for the call.

Backends:
  stub          deterministic: the caller's `stub()` produces the result (no model)
  claude_code   Claude Agent SDK driving the locally logged-in Claude Code CLI
  messages_api  Anthropic Messages API (needs ANTHROPIC_API_KEY)
  external      any program speaking one JSON object per line on stdin/stdout
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from swarmscope.config import role_llm
from swarmscope.core.models import AttentionRecord
from swarmscope.ingest.boundary import UNTRUSTED_NOTICE
from swarmscope.llm.evidence_tools import EvidenceTools


def find_claude_cli() -> str | None:
    for c in (os.environ.get("CLAUDE_CLI"), shutil.which("claude"),
              str(Path.home() / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude"))):
        if c and Path(c).exists():
            return c
    return None


@dataclass
class CallResult:
    data: dict[str, Any]
    backend: str
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class LLMRouter:
    def __init__(self, org: dict[str, Any], record: Callable[[AttentionRecord], None],
                 now: Callable[[], datetime]):
        self.org = org
        self.record = record
        self.now = now
        self.sem = asyncio.Semaphore(int(org.get("llm", {}).get("max_concurrency", 3)))
        self.spent_usd = 0.0
        self.errors: list[str] = []

    @property
    def mode(self) -> str:
        return self.org.get("llm", {}).get("mode", "stub")

    async def json(self, role: str, *, system: str, prompt: str, schema: dict[str, Any], owner: str,
                   owner_kind: str, scope: str | None = None, stub: Callable[[], dict[str, Any]],
                   stub_delay: float = 0.0) -> CallResult:
        return await self._call(role, system, prompt, schema, None, owner, owner_kind, scope, stub, stub_delay)

    async def agent(self, role: str, *, system: str, prompt: str, schema: dict[str, Any], tools: EvidenceTools,
                    owner: str, owner_kind: str, scope: str | None = None,
                    stub: Callable[[], dict[str, Any]], stub_delay: float = 0.0) -> CallResult:
        return await self._call(role, system, prompt, schema, tools, owner, owner_kind, scope, stub, stub_delay)

    async def _call(self, role, system, prompt, schema, tools, owner, owner_kind, scope, stub, stub_delay) -> CallResult:
        cfg = role_llm(self.org, role)
        backend = cfg.get("backend", "stub")
        cap = float(self.org.get("budgets", {}).get("max_usd_per_hour", 5.0))
        if backend != "stub" and self.spent_usd >= cap:
            backend = "stub"
            self.errors.append(f"budget cap ${cap} reached; {role} fell back to deterministic")
        t0 = time.time()
        async with self.sem:
            try:
                if backend == "stub":
                    if stub_delay:
                        await asyncio.sleep(stub_delay)
                    res = CallResult(data=stub(), backend="stub", tokens_in=len(prompt) // 4)
                elif backend == "claude_code":
                    res = await _claude_code(cfg, system, prompt, schema, tools)
                elif backend == "messages_api":
                    res = await _messages_api(cfg, system, prompt, schema)
                elif backend == "external":
                    res = await _external(cfg, role, system, prompt, schema)
                else:
                    raise ValueError(f"unknown backend {backend}")
            except Exception as exc:  # degrade to deterministic, keep the system running
                self.errors.append(f"{role} via {backend}: {type(exc).__name__}: {str(exc)[:200]}")
                res = CallResult(data=stub(), backend="stub", error=str(exc)[:300], tokens_in=len(prompt) // 4)
        res.seconds = time.time() - t0
        self.spent_usd += res.cost_usd
        self.record(AttentionRecord(owner=owner, owner_kind=owner_kind, scope=scope, ts=self.now(),
                                    tokens_in=res.tokens_in, tokens_out=res.tokens_out, cost_usd=res.cost_usd,
                                    calls=1, backend=res.backend, model=res.model))
        return res


# ------------------------------------------------------------------ backends

async def _claude_code(cfg: dict[str, Any], system: str, prompt: str, schema: dict[str, Any],
                       tools: EvidenceTools | None) -> CallResult:
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    cli = find_claude_cli()
    mcp, allowed = ({}, [])
    if tools is not None:
        server, allowed = tools.mcp_server()
        mcp = {"evidence": server}
    opts = ClaudeAgentOptions(
        system_prompt=system + "\n\n" + UNTRUSTED_NOTICE,
        model=cfg.get("model") or "claude-sonnet-5-5",
        effort=cfg.get("effort") or "low",
        max_turns=int(cfg.get("max_turns", 6 if tools else 2)),
        tools=[],                      # no built-in tools: no files, shell or web
        allowed_tools=allowed,
        mcp_servers=mcp,
        output_format={"type": "json_schema", "schema": schema},
        setting_sources=[],            # do not load the user's settings, hooks or CLAUDE.md
        cli_path=cli,
        # Spend is capped by the router (budgets.max_usd_per_hour) and max_turns. The CLI's per-call
        # max_budget_usd misfired on multi-turn tool use in testing, so it is only set when configured.
        max_budget_usd=float(cfg["max_budget_usd"]) if cfg.get("max_budget_usd") else None,
        cwd=str(Path.cwd()),
    )
    result: ResultMessage | None = None
    async for msg in query(prompt=prompt, options=opts):
        if isinstance(msg, ResultMessage):
            result = msg
    if result is None or result.is_error:
        raise RuntimeError(f"claude_code call failed: {getattr(result, 'subtype', 'no result')}")
    data = result.structured_output
    if data is None and result.result:
        data = _parse_json(result.result)
    usage = result.usage or {}
    return CallResult(data=data or {}, backend="claude_code", model=cfg.get("model"),
                      tokens_in=int(usage.get("input_tokens", 0)) + int(usage.get("cache_read_input_tokens", 0)),
                      tokens_out=int(usage.get("output_tokens", 0)), cost_usd=float(result.total_cost_usd or 0),
                      tool_calls=list(tools.calls) if tools else [])


async def _messages_api(cfg: dict[str, Any], system: str, prompt: str, schema: dict[str, Any]) -> CallResult:
    import anthropic

    client = anthropic.AsyncAnthropic()
    resp = await client.beta.messages.create(
        model=cfg.get("model") or "claude-opus-5-5",
        max_tokens=16000,
        system=[{"type": "text", "text": system + "\n\n" + UNTRUSTED_NOTICE, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": cfg.get("effort") or "medium",
                       "format": {"type": "json_schema", "schema": _strict(schema)}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("model declined the request")
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    u = resp.usage
    return CallResult(data=json.loads(text), backend="messages_api", model=resp.model, tokens_in=u.input_tokens,
                      tokens_out=u.output_tokens)


async def _external(cfg: dict[str, Any], role: str, system: str, prompt: str, schema: dict[str, Any]) -> CallResult:
    proc = await asyncio.create_subprocess_exec(*cfg["command"], stdin=asyncio.subprocess.PIPE,
                                                stdout=asyncio.subprocess.PIPE)
    line = json.dumps({"role": role, "system": system, "prompt": prompt, "schema": schema}) + "\n"
    out, _ = await asyncio.wait_for(proc.communicate(line.encode()), timeout=float(cfg.get("timeout", 120)))
    return CallResult(data=json.loads(out.decode().strip().splitlines()[-1]), backend="external")


def _parse_json(text: str) -> dict[str, Any] | None:
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e < 0:
        return None
    try:
        return json.loads(text[s:e + 1])
    except json.JSONDecodeError:
        return None


def _strict(schema: dict[str, Any]) -> dict[str, Any]:
    """Structured outputs need additionalProperties: false and every property required."""
    s = dict(schema)
    if s.get("type") == "object":
        props = {k: _strict(v) for k, v in s.get("properties", {}).items()}
        s.update(properties=props, required=list(props), additionalProperties=False)
    elif s.get("type") == "array" and "items" in s:
        s["items"] = _strict(s["items"])
    return s
