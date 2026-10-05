"""The analyst organization: topology validation, spawning and scaling, scoped evidence, deterministic cycles,
topology editing over the API, and the timed simulator controls."""
from __future__ import annotations

import asyncio
import copy
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from swarmscope.agents.spec import TopologyError, from_dict, list_topologies, load_topology


def test_all_shipped_topologies_validate():
    ids = {t["id"] for t in list_topologies()}
    assert {"hierarchical_divisions", "flat_pool", "single_agent", "sdk_native"} <= ids
    for i in ids:
        t = load_topology(i)
        assert t.root in t.roles
        for r in t.roles.values():
            assert r.schema()["type"] == "object"
            assert r.prompt_text()


def test_validation_catches_bad_topologies():
    base = load_topology("hierarchical_divisions").to_dict()
    for mutate, msg in [
        (lambda d: d.update(root="nobody"), "root role"),
        (lambda d: d["roles"]["director"].update(can_spawn=["ghost"]), "unknown role"),
        (lambda d: d["roles"]["director"].update(tools=["evidence.teleport"]), "unknown tool"),
        (lambda d: d["roles"]["director"].update(output="poem"), "unknown output"),
        (lambda d: d["roles"]["division_analyst"].update(native_subagents=["nope"]), "native subagent"),
        (lambda d: d["divisions"].update(strategy="astrology"), "divisions.strategy"),
    ]:
        d = copy.deepcopy(base)
        mutate(d)
        with pytest.raises(TopologyError, match=msg):
            from_dict(d, "x")


def test_tool_globs_and_raw_access():
    t = load_topology("hierarchical_divisions")
    analyst, specialist, director = t.roles["division_analyst"], t.roles["specialist"], t.roles["director"]
    assert "read_raw" not in analyst.evidence_tools() and "read_raw" in specialist.evidence_tools()
    assert "spawn_agent" in director.org_tools() and "spawn_agent" in analyst.org_tools()
    assert specialist.org_tools() == ["escalate_finding", "cases"]      # a specialist tracks and escalates, never spawns


def _engine(topology="hierarchical_divisions", **ov):
    from swarmscope.engine import Engine
    return Engine("ai_village", "default", path="synthetic",
                  overrides={"investigations.node_delay_s": 0, "agents.stub_delay_s": 0, "agents.topology": topology, **ov})


@pytest.fixture(scope="module")
def org_run():
    e = _engine()
    asyncio.run(e.run_to_end())
    return e


def test_cycle_builds_a_team_over_divisions(org_run):
    o = org_run.agent_org
    roles = [n.role for n in o.active()]
    assert roles.count("director") == 1
    assert roles.count("division_analyst") >= len(o.divisions) - 1 >= 2
    assert any(n.role == "specialist" for n in o.nodes.values()), "analyst recommendations should spawn specialists"
    assert org_run.exec_state.strategy.startswith("agent_org")
    for n in o.active():
        if n.role == "division_analyst":
            assert n.runs >= 2 and n.notes and n.last_report and n.last_report.get("status")


def test_children_are_scoped_and_claims_grounded(org_run):
    o = org_run.agent_org
    analyst = next(n for n in o.active() if n.role == "division_analyst" and n.runs)
    agents, resources = o.scope_tuple(analyst.scope)
    from swarmscope.llm.evidence_tools import EvidenceTools
    t = EvidenceTools(org_run.store, org_run.now, "ai_village", scope=(agents, resources))
    rows = t.query_events(limit=200)
    assert rows and all(r["actor_id"] in agents or r["object_id"] in resources for r in rows)
    for cid in analyst.last_report["claim_ids"]:
        c = org_run.store.get("Claim", cid)
        if c.status.value in ("OBSERVED", "DERIVED"):
            assert c.support


def test_spawn_caps_depth_and_permissions():
    e = _engine()
    asyncio.run(e.run_to_end(10))
    o = e.agent_org
    root = o.nodes[o.root_id]
    ok, why = o.can_spawn(root, "director")
    assert not ok and "may not spawn" in why
    o.topology.scaling["max_agents"] = len(o.active())
    ok, why = o.can_spawn(root, "division_analyst")
    assert not ok and "max_agents" in why
    o.topology.scaling["max_agents"] = 99
    o.topology.scaling["max_depth"] = 1
    analyst = next(n for n in o.active() if n.role == "division_analyst")
    ok, why = o.can_spawn(analyst, "specialist")
    assert not ok and "max_depth" in why


def test_org_tools_spawn_run_and_retire():
    from swarmscope.agents.org_tools import OrgTools

    async def go():
        e = _engine()
        await e.run_to_end(14)
        o = e.agent_org
        root = o.nodes[o.root_id]
        tools = OrgTools(o, root)
        div = next(iter(o.divisions))
        reps = await tools.spawn_agents([{"role": "division_analyst", "scope": f"division:{div}", "brief": "a"},
                                         {"role": "director", "scope": "population", "brief": "b"}])
        assert any("error" in r for r in reps) and any(r.get("agent_id") for r in reps)
        new = next(r["agent_id"] for r in reps if r.get("agent_id"))
        assert o.nodes[new].parent == root.id and o.nodes[new].runs == 1
        again = await tools.run_agent(new, "sharper task")
        assert again["agent_id"] == new and o.nodes[new].runs == 2
        assert tools.retire_agent(new)["ok"] and o.nodes[new].status == "retired"
        assert "error" in tools.retire_agent(o.root_id)
        status = tools.org_status()
        assert status["divisions"] and all("covered_by" in d for d in status["divisions"])
    asyncio.run(go())


def test_nested_spawning_does_not_deadlock():
    """A parent waiting on children releases its slot: depth-3 nesting with a single concurrency slot completes."""
    from swarmscope.agents.org_tools import OrgTools

    async def go():
        e = _engine()
        await e.run_to_end(14)
        o = e.agent_org
        o._sem = asyncio.Semaphore(1)
        root = o.nodes[o.root_id]
        div = next(iter(o.divisions))
        analyst = o.spawn("division_analyst", f"division:{div}", "nested", root, "test")

        async def analyst_turn():
            # the analyst, while running (holding a slot), spawns a specialist
            async with o.slot(analyst):
                return await OrgTools(o, analyst).spawn_agent("specialist", analyst.scope, "[timeline] x")

        async with o.slot(root):                      # the root is mid-run
            async with o.yielded(root):               # ...and waits on its child
                sub = await asyncio.wait_for(analyst_turn(), timeout=10)
        assert sub.get("agent_id") and o.nodes[sub["agent_id"]].depth == 2
    asyncio.run(go())


def test_split_and_merge_reassign_agents():
    e = _engine()
    asyncio.run(e.run_to_end(30))
    o = e.agent_org
    big = max(o.divisions.values(), key=lambda d: len(d.agents))
    parts = o.split_division(big.id, "test") if len(big.agents) >= 4 else None
    if parts and len(parts) > 1:
        for p in parts:
            assert any(n.scope == f"division:{p.id}" for n in o.active())
        m = o.merge_divisions([p.id for p in parts], "rejoined", "test")
        assert m.id in o.divisions and any(n.scope == f"division:{m.id}" for n in o.active())


def test_other_topologies_run():
    for topo, expect in [("flat_pool", "generalist"), ("single_agent", None)]:
        e = _engine(topo)
        asyncio.run(e.run_to_end())
        roles = {n.role for n in e.agent_org.active()}
        assert "director" in roles
        if expect:
            assert expect in roles
        else:
            assert roles == {"director"}


def test_topology_api_and_timed_controls():
    from swarmscope.api.app import app

    with TestClient(app) as c:
        c.post("/api/session", json={"source": "ai_village", "path": "synthetic",
                                     "overrides": {"agents.stub_delay_s": 0, "investigations.node_delay_s": 0,
                                                   "agents.topology": "desks"}})
        topo = c.get("/api/agents/topologies").json()
        cur = topo["current"]
        assert cur["id"] == "desks" and cur["roles"]["director"]["prompt_text"].startswith("You direct")   # the preset chosen
        assert topo["pack_defaults"]["ai_village"]["preset"] == "desks" and topo["pack_defaults"]["ai_village"]["topology"] == "lead"
        bad = copy.deepcopy(cur)
        bad["roles"]["director"]["can_spawn"] = ["ghost"]
        assert c.post("/api/agents/topology", json={"topology": bad}).status_code == 422
        good = copy.deepcopy(cur)
        good["roles"]["desk_analyst"]["max_turns"] = 3
        good["roles"]["desk_analyst"]["prompt_text"] = "Custom analyst prompt."
        r = c.post("/api/agents/topology", json={"topology": good})
        assert r.status_code == 200 and r.json()["topology"]["roles"]["desk_analyst"]["prompt"] == "Custom analyst prompt."
        assert c.post("/api/agents/topology", json={"select": "flat_pool"}).json()["topology"]["root"] == "director"
        # timed simulator: time scale, jump forward with catch-up
        snap = c.get("/api/snapshot").json()
        c.post("/api/clock", json={"action": "scale", "value": 600})
        assert abs(c.get("/api/snapshot").json()["clock"]["time_scale"] - 600) < 1
        from datetime import datetime
        start = datetime.fromisoformat(snap["clock"]["start"])
        target = (start + timedelta(days=1)).isoformat()
        c.post("/api/clock", json={"action": "jump", "to": target})
        for _ in range(60):
            cl = c.get("/api/snapshot").json()["clock"]
            if not cl["catching_up"] and cl["now"] >= target[:19]:
                break
            import time
            time.sleep(0.5)
        assert cl["now"] >= target[:19]
        org = c.get("/api/agents").json()
        assert org["cycle"] >= 1 and org["nodes"]
        node = org["nodes"][0]["id"]
        assert c.get(f"/api/agents/node/{node}").status_code == 200
        assert c.post("/api/agents/action", json={"action": "run", "agent_id": node, "task": "check"}).status_code == 200
