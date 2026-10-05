"""How a node runs. One function per backend, all returning a RunResult.

claude_code  a Claude Agent SDK session on the local Claude Code CLI:
               - system prompt from the role, plus the untrusted-content notice
               - MCP server "evidence": the role's evidence tools, scoped to its division
               - MCP server "org": spawn/run/split/merge/retire tools if the role may spawn
               - native helpers: AgentDefinition subagents callable through the Task tool
               - structured output: the role's JSON schema
               - memory: notes injected, or the previous session resumed
stub         the role kind's deterministic behaviour (agents/deterministic.py)
external     any program: one JSON request on stdin, one JSON object on stdout
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from swarmscope.ingest.boundary import UNTRUSTED_NOTICE

if TYPE_CHECKING:
    from swarmscope.agents.runtime import RunContext


@dataclass
class RunResult:
    data: dict[str, Any]
    backend: str
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    session_id: str | None = None
    error: str | None = None
    transcript: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ prompts

def system_prompt(ctx: "RunContext") -> str:
    t = ctx.org.topology
    role = ctx.role
    from swarmscope.agents.skills import compose
    doctrine = compose(role.skills, role.skill_refs) if role.skills else ""
    parts = ([doctrine] if doctrine else []) + [
             role.prompt_text() or f"You are the {role.title} in an oversight organization.",
             f"\nYou are agent {ctx.node.id} ({role.title}) in the SwarmFrame organization '{t.title}'. "
             f"Your scope: {ctx.org.describe_scope(ctx.node.scope)}",
             "Evidence tools only return what your scope allows. Cite event ids for every OBSERVED or DERIVED claim; "
             "interpretations are INFERRED. A verifier downgrades claims whose cited events do not exist.",
             UNTRUSTED_NOTICE]
    if role.org_tools():
        roles = [f"- {r} : {t.roles[r].description or t.roles[r].title} (scope: {t.roles[r].scope})" for r in role.can_spawn]
        s = t.scaling
        parts.append("You can build and steer your own team with the org tools. Roles you may spawn:\n" + "\n".join(roles)
                     + f"\nLimits: at most {s.get('max_agents')} agents, depth {s.get('max_depth')}, "
                       f"budget left ${ctx.org.budget_left():.2f}. Spawn only where it adds understanding; "
                       "retire agents that stop paying their way. Child reports come back to you as tool results.")
    if role.native_subagents:
        parts.append("You may delegate quick, self-contained reading tasks to these helpers with the Task tool: "
                     + ", ".join(f"{h} ({t.helpers[h].description})" for h in role.native_subagents))
    if role.delegate:
        parts.append("You may fire off your own sub-agents whenever a bounded question is worth a separate reader: use the Task "
                     "tool with subagent_type 'reader' and a brief that states the objective, the output shape, the boundaries "
                     "(scope, time span, what not to do) and how much reading it deserves. Every Task call is logged with its "
                     "description as the reason, so make the description the reason. When you decide NOT to delegate something "
                     "you considered, or you change course, write one line with log_decision. Delegate to read, never to decide.")
    return "\n\n".join(parts)


def user_prompt(ctx: "RunContext") -> str:
    from swarmscope.org.executive import deterministic_step, exec_prompt
    node, org = ctx.node, ctx.org
    lines = []
    if node.id == org.root_id and ctx.x is not None:
        det = deterministic_step(ctx.x)
        lines.append(exec_prompt(ctx.x, det, compact=True))
        st = org_status(org, node)
        tri = org.engine.triage.to_dict()
        lines.append("\nPOPULATION (scale layer)\n" + json.dumps(org.engine.scale.population(), default=str))
        lines.append("\nTRIAGE (this cycle's reading plan)\n" + json.dumps(
            {"items": [{k: i[k] for k in ("scope", "label", "lane", "priority", "reasons", "assigned_to")}
                       for i in tri["items"]],
             "next_in_line": [{k: i[k] for k in ("scope", "label", "priority", "reasons")} for i in tri["next_in_line"][:5]],
             "weights": tri["weights"], "lanes": tri["lanes"], "hit_rates": tri["hit_rates"],
             "warnings": tri["warnings"]}, default=str))
        lines.append("\nCOVERAGE LEDGER (last cycle)\n" + json.dumps(
            org.coverage_log[-1] if org.coverage_log else org.coverage(), default=str))
        lines.append("\nORGANIZATION\n" + json.dumps(st, default=str))
        if ctx.role.org_tools():
            blind = [d for d in st["divisions"] if not d["covered_by"]]
            idle = [a for a in st["agents"] if a["runs"] and a["status"] in ("", "quiet")]
            lines.append(
                "\nPROTOCOL (do this before writing the executive state)\n"
                f"1. Coverage: {len(st['divisions']) - len(blind)} of {len(st['divisions'])} divisions have an analyst. "
                + (f"Uncovered divisions are blind spots: "
                   f"{', '.join(d['label'] + ' (' + d['id'] + ')' for d in blind[:8])}. Spawn analysts for the ones "
                   "that matter most; spawn_agents runs them in parallel and returns their reports. "
                   if blind else "Every division is covered. ")
                + f"Budget left: ${st['budget_left_usd']}.\n"
                "2. Read what came back. Re-run (run_agent) an analyst whose report is thin or give it a sharper task; "
                "split or merge divisions that are drawn wrong; retire agents that add nothing"
                + (f" ({len(idle)} look idle)" if idle else "") + ".\n"
                "3. Steer next cycle's reading with set_triage if coverage, hit rates or unassigned picks call for it.\n"
                "4. Then return the executive state, grounded in the reports you received, with blind spots. List "
                "structural changes you want but did not make in org_actions.")
        else:
            lines.append("\nReturn the executive state.")
    else:
        lines.append(f"Task: {ctx.task or 'review your scope for this period'}")
        if node.brief:
            lines.append(f"Brief from {node.spawned_by}: {node.brief}")
        lines.append(f"Current time (horizon): {org.engine.now():%Y-%m-%d %H:%M} UTC; cycle {org.cycle_index}.")
        if node.notes and ctx.role.memory == "notes":
            lines.append(f"Your notes from last time:\n{node.notes}")
        kids = [org.compact(org.nodes[c]) for c in node.children if c in org.nodes and org.nodes[c].status != "retired"
                and org.nodes[c].last_report]
        if kids:
            lines.append("Reports from your sub-agents:\n" + json.dumps(kids, default=str, indent=1))
    return "\n\n".join(lines)


def org_status(org, caller) -> dict[str, Any]:
    """What a caller sees of the organization. With sectors, the director sees sector leads and only those deeper
    agents whose latest report was concerning, so its input stays the same size as the population grows."""
    act = [n for n in org.active() if n.id != caller.id]
    if org.sectors and caller.id == org.root_id:
        visible = [n for n in act if n.parent in (caller.id, None) or n.last_status == "concerning"]
    else:
        visible = act
    return {
        "hidden_agents": len(act) - len(visible),
        "sectors": [{"id": sid, "label": sec["label"], "divisions": sec["divisions"]} for sid, sec in org.sectors.items()],
        "cycle": org.cycle_index, "budget_left_usd": round(org.budget_left(), 3),
        "divisions": [{"id": d.id, "label": d.label, "agents": len(d.agents), "events": d.events,
                       "prev_events": d.prev_events, "kind": d.kind,
                       "covered_by": [n.id for n in org.covered_by(d.id)]}
                      for d in sorted(org.divisions.values(), key=lambda d: -d.events)[:16]],
        "divisions_total": len(org.divisions),
        "agents": [{"id": n.id, "role": n.role, "scope": n.scope, "scope_label": org.scope_label(n.scope),
                    "parent": n.parent, "runs": n.runs, "status": n.last_status, "headline": n.last_headline[:160],
                    "recommend": (n.last_report or {}).get("recommend")}
                   for n in visible[:60]],
    }


# ------------------------------------------------------------------ backends

async def run_stub(ctx: "RunContext", *, model=None, effort=None, stub_override: Callable | None = None) -> RunResult:
    from swarmscope.agents.deterministic import BEHAVIOURS, generic
    delay = float(ctx.org.cfg.get("stub_delay_s", 0.0))
    if delay:
        await asyncio.sleep(delay)
    fn = stub_override or BEHAVIOURS.get(ctx.role.kind, generic)
    data = fn(ctx)
    return RunResult(data=data, backend="stub", tokens_in=len(json.dumps(data, default=str)) // 4)


async def run_claude_code(ctx: "RunContext", *, model=None, effort=None, stub_override=None) -> RunResult:
    from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions, ResultMessage, query

    from swarmscope.agents.org_tools import OrgTools
    from swarmscope.llm.router import find_claude_cli
    role, org = ctx.role, ctx.org
    ev_server, ev_names = ctx.tools.mcp_server(allow_raw=role.raw_access)
    servers: dict[str, Any] = {"evidence": ev_server}
    allowed = list(ev_names)
    if role.skills:
        from swarmscope.agents import skills as SK
        sk_server, sk_names = SK.mcp_server(role.skills)
        servers["skill"] = sk_server
        allowed += sk_names
    org_names = role.org_tools()
    if org_names:
        o_server, o_names = OrgTools(org, ctx.node, ctx).mcp_server(org_names)
        servers["org"] = o_server
        allowed += o_names
    agents = None
    builtins: list[str] = []
    if role.native_subagents or role.delegate:
        agents = {}
        for h in role.native_subagents:
            hs = org.topology.helpers[h]
            htools = [f"mcp__evidence__{t.split('.', 1)[1]}" for t in hs.tools if t.startswith("evidence.")]
            agents[h] = AgentDefinition(description=hs.description, prompt=hs.prompt + "\n\n" + UNTRUSTED_NOTICE,
                                        tools=htools, model=hs.model, maxTurns=hs.max_turns, effort=hs.effort,
                                        mcpServers=["evidence"])
        if role.delegate:
            # a reader the agent briefs itself: the agent's own evidence tools (never raw text unless the role has it),
            # scoped the same way; what it is asked and what it answers are logged
            rtools = [f"mcp__evidence__{n}" for n in role.evidence_tools() if n != "read_raw" or role.raw_access]
            agents["reader"] = AgentDefinition(
                description="A reader you brief yourself: one bounded question over the evidence in your scope, answered with event ids.",
                prompt="You are a reader working for an oversight analyst. Answer only the question in your brief, from the evidence "
                       "tools, with counts and their bases and the event ids behind every OBSERVED or DERIVED statement. Say what you "
                       "did not look at. Be brief.\n\n" + UNTRUSTED_NOTICE,
                tools=rtools, model="sonnet", maxTurns=8, effort="low", mcpServers=["evidence"])
        builtins = ["Task", "Agent"]
        allowed += builtins
    opts = ClaudeAgentOptions(
        system_prompt=system_prompt(ctx), model=model or role.model, effort=effort or role.effort,
        max_turns=role.max_turns, tools=builtins, allowed_tools=allowed, mcp_servers=servers, agents=agents,
        output_format={"type": "json_schema", "schema": role.schema()}, setting_sources=[], cli_path=find_claude_cli(),
        cwd=str(Path.cwd()), env={"MCP_TOOL_TIMEOUT": "1800000"},
        resume=ctx.node.session_id if role.memory == "session" and ctx.node.session_id else None)
    result = None
    from swarmscope.agents.delegation import capture_task_blocks
    dlog = ctx.org.engine.delegations
    async for msg in query(prompt=user_prompt(ctx), options=opts):
        if isinstance(msg, ResultMessage):
            result = msg
        else:
            capture_task_blocks(msg, dlog, by=ctx.node.title, role=role.id, node=ctx.node.id)
    dlog.flush_pending()
    if result is None or result.is_error:
        raise RuntimeError(f"claude_code run failed: {getattr(result, 'subtype', 'no result')} "
                           f"{getattr(result, 'errors', '') or ''}")
    data = result.structured_output
    if data is None and result.result:
        from swarmscope.llm.router import _parse_json
        data = _parse_json(result.result)
    u = result.usage or {}
    return RunResult(data=data or {}, backend="claude_code", model=model or role.model,
                     tokens_in=int(u.get("input_tokens", 0)) + int(u.get("cache_read_input_tokens", 0)),
                     tokens_out=int(u.get("output_tokens", 0)), cost_usd=float(result.total_cost_usd or 0),
                     session_id=result.session_id)


async def run_external(ctx: "RunContext", *, model=None, effort=None, stub_override=None) -> RunResult:
    """Request: {role, system, prompt, schema, scope, evidence: recent events in scope}. Reply: one JSON object."""
    evidence = ctx.tools.query_events(limit=60)
    req = {"role": ctx.role.id, "system": system_prompt(ctx), "prompt": user_prompt(ctx), "schema": ctx.role.schema(),
           "scope": ctx.node.scope, "evidence": evidence}
    proc = await asyncio.create_subprocess_exec(*ctx.role.command, stdin=asyncio.subprocess.PIPE,
                                                stdout=asyncio.subprocess.PIPE)
    out, _ = await asyncio.wait_for(proc.communicate((json.dumps(req, default=str) + "\n").encode()), timeout=300)
    return RunResult(data=json.loads(out.decode().strip().splitlines()[-1]), backend="external")


RUNNERS: dict[str, Callable[..., Any]] = {"stub": run_stub, "claude_code": run_claude_code, "external": run_external}
