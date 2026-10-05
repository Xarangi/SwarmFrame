"""The delegation log: managed spawns, re-runs and retirements, escalations, agent notes, and native Task calls
captured from a session stream, all land in one per-session JSON-lines file and in the API."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from swarmscope.agents.delegation import capture_task_blocks
from swarmscope.agents.org_tools import OrgTools
from swarmscope.engine import Engine

FAST = {"investigations.node_delay_s": 0, "agents.stub_delay_s": 0, "llm.mode": "stub"}


def engine():
    return Engine("swarm_scale", "default", slice_override={"agents": 60, "hours": 2}, overrides={**FAST, "agents.topology": "triage_tree"})


def test_managed_delegations_escalations_and_notes_are_logged_to_a_file():
    e = engine()

    async def go():
        for _ in range(2):
            await e.process(e.clock.next_window())
    asyncio.run(go())
    kinds = {r["kind"] for r in e.delegations.tail}
    assert "managed" in kinds and all(r["why"] for r in e.delegations.tail if r["kind"] == "managed")
    root = e.agent_org.nodes[e.agent_org.root_id]
    tools = OrgTools(e.agent_org, root)
    tools.log_decision("not delegating the ops cohort: its analyst's last report covers it", kind="skip", target="cohort:ops")
    aid = e.store.sql("SELECT actor FROM events WHERE actor IS NOT NULL LIMIT 1")[0]["actor"]
    tools.escalate_finding(scope=f"agent:{aid}", title="t", level="INVESTIGATE", reason="two stories")
    kid = next(n for n in e.agent_org.active() if n.id != root.id)
    asyncio.run(tools.run_agent(kid.id, "look again at the newest template"))
    tools.retire_agent(kid.id, "quiet")
    kinds = [r["kind"] for r in e.delegations.tail]
    assert {"note", "escalation", "rerun", "retire"} <= set(kinds)
    rerun = next(r for r in e.delegations.tail if r["kind"] == "rerun")
    assert rerun["by"] == root.title and rerun["why"].startswith("look again")
    lines = [json.loads(x) for x in e.delegations.path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == len(e.delegations.tail) and lines[-1]["kind"] == "retire" and lines[-1]["why"] == "quiet"
    assert e.delegations.path.name == "delegations.jsonl" and e.delegations.path.parent.name.startswith("swarm_scale_")
    mine = tools.delegations(10)["entries"]
    assert mine and all(r["node"] == root.id for r in mine)


def test_native_task_calls_are_captured_from_the_stream():
    e = engine()
    log = e.delegations
    use = SimpleNamespace(name="Task", id="tu_1", input={"subagent_type": "reader", "description": "which agents touched host X before 14:00",
                                                           "prompt": "Objective: ... Output: event ids ..."})
    capture_task_blocks(SimpleNamespace(content=[use], parent_tool_use_id=None), log, by="Director", role="director", node="ag_1")
    assert "tu_1" in log.pending and not [r for r in log.tail if r["kind"] == "native"]
    res = SimpleNamespace(tool_use_id="tu_1", content="3 of 9 agents: evt_1, evt_4, evt_9", is_error=False)
    capture_task_blocks(SimpleNamespace(content=[res], parent_tool_use_id=None), log, by="Director", role="director", node="ag_1")
    nat = [r for r in log.tail if r["kind"] == "native"]
    assert len(nat) == 1 and nat[0]["target"] == "reader" and nat[0]["why"].startswith("which agents") \
        and nat[0]["outcome"].startswith("3 of 9")
    # a nested sub-agent's own tool uses are not the parent's delegations
    capture_task_blocks(SimpleNamespace(content=[SimpleNamespace(name="Task", id="tu_2", input={})], parent_tool_use_id="tu_1"),
                        log, by="Director", role="director", node="ag_1")
    assert "tu_2" not in log.pending
    # an async sub-agent: the launch confirmation is not the outcome; the task notification is
    capture_task_blocks(SimpleNamespace(content=[SimpleNamespace(name="Task", id="tu_a", input={"description": "async q", "prompt": "p"})],
                                        parent_tool_use_id=None), log, by="D", role="director", node="ag_1")
    capture_task_blocks(SimpleNamespace(content=[SimpleNamespace(tool_use_id="tu_a", content=[{"type": "text", "text": "Async agent launched successfully."}], is_error=False)],
                                        parent_tool_use_id=None), log, by="D", role="director", node="ag_1")
    assert "tu_a" in log.pending and not [r for r in log.tail if r["why"] == "async q"]
    capture_task_blocks(SimpleNamespace(tool_use_id="tu_a", summary="2 of 9 agents; evt_3", status="completed"), log, by="D", role="director", node="ag_1")
    assert [r for r in log.tail if r["why"] == "async q"][0]["outcome"] == "2 of 9 agents; evt_3"
    log.task_started("tu_3", by="D", role="director", node="ag_1", inputs={"description": "lost"})
    log.flush_pending()
    assert [r for r in log.tail if r["why"] == "lost"][0]["outcome"] == "no result captured"


def test_roles_that_delegate_and_the_api_surface():
    from fastapi.testclient import TestClient
    from swarmscope.agents.spec import load_topology
    from swarmscope.api.app import S, app
    for tid in ("triage_tree", "desks", "board_watch", "catalog_review"):
        t = load_topology(tid)
        assert t.roles[t.root].delegate and "delegation" in t.roles[t.root].skill_refs
        assert "log_decision" in t.roles[t.root].org_tools()
    e = engine()
    S.engine = e
    with TestClient(app) as c:
        asyncio.run(e.process(e.clock.next_window()))
        d = c.get("/api/agents/delegations?n=5").json()
        assert d["total"] >= 1 and d["path"].endswith("delegations.jsonl") and len(d["recent"]) <= 5
        assert c.get("/api/snapshot").json()["delegations"]["by_kind"].get("managed", 0) >= 1
