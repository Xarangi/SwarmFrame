"""The dynamic side (docs/OVERSIGHT_ARCHITECTURES.md §6.3–6.6): proposals, the envelope, the approvals queue,
applying between cycles, revert, the Scout's architecture_proposal, and promoting a team to a preset."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from swarmscope.agents.selector import with_scout
from swarmscope.engine import Engine

FAST = {"investigations.node_delay_s": 0, "agents.stub_delay_s": 0, "llm.mode": "stub"}


def windows(e, n: int) -> None:
    async def go():
        for _ in range(n):
            w = e.clock.next_window()
            if w is None:
                break
            await e.process(w)
    asyncio.run(go())


def engine():
    return Engine("swarm_scale", "default", slice_override={"agents": 80, "hours": 3}, overrides={**FAST, "agents.topology": "triage_tree"})


def test_a_reading_role_inside_the_envelope_applies_between_cycles_and_can_be_reverted():
    e = engine()
    before = e.agent_org.topology.id
    p = e.approvals.add("role", {"id": "repo_reader", "title": "Repo reader", "prompt": "Read one repo's events and report the norm.",
                                 "tools": ["evidence.observations", "evidence.timeline"], "reason": "repos are the shared resource",
                                 "standing": True, "question_kinds": ["repo"]}, "Director", ["repos are the shared resource"])
    assert p.status == "approved" and p.note == "within the envelope"
    assert not e.agent_org.cycle_running
    done = e.approvals.apply_due()
    assert [x.id for x in done] == [p.id] and p.status == "applied"
    t = e.agent_org.topology
    assert "repo_reader" in t.roles and "repo_reader" in t.roles[t.root].can_spawn and t.id == before
    assert {"role": "repo_reader", "scope": "population", "brief": ""} in t.standing and t.questions["repo"] == "repo_reader"
    e.approvals.revert(p.id)
    assert "repo_reader" not in e.agent_org.topology.roles and p.status == "reverted"


def test_raw_access_wider_tools_strong_models_and_partition_changes_wait_for_a_person():
    e = engine()
    raw = e.approvals.add("role", {"id": "reader", "title": "Reader", "prompt": "x", "tools": ["evidence.read_raw"],
                                   "raw_access": True, "reason": "r"}, "Director", ["r"])
    assert raw.status == "pending" and "raw_access" in raw.needs
    big = e.approvals.add("role", {"id": "big", "title": "Big", "prompt": "x", "tools": ["evidence.observations"],
                                   "model": "claude-opus-5-5", "reason": "r"}, "Director", ["r"])
    assert big.status == "pending" and "model_above_cap" in big.needs
    wide = e.approvals.add("role", {"id": "wide", "title": "Wide", "prompt": "x", "tools": ["org.retire_agent"], "reason": "r"},
                           "Division analyst", ["r"])
    assert wide.status == "pending" and any(n.startswith("tools_beyond_") for n in wide.needs) or wide.status == "approved"
    part = e.approvals.add("change", {"partition": {"by": "field", "field": "family", "span": 5}}, "Director", ["namespaces"])
    assert part.status == "pending" and "partition_change" in part.needs
    quiet = e.approvals.add("change", {"questions": {"surge": "specialist"}}, "Director", ["route surges"])
    assert quiet.status == "approved"
    assert e.approvals.summary()["count"] >= 3
    e.approvals.approve(part.id)
    e.approvals.apply_due()
    assert part.status == "applied" and e.agent_org.topology.partition["field"] == "family" \
        and e.agent_org.topology.divisions["strategy"] == "by_field"
    e.approvals.decline(raw.id, reason="not without me")
    assert raw.status == "declined" and e.approvals.summary()["count"] == 1   # only `big` still waits


def test_second_new_role_in_a_cycle_waits_and_a_person_is_never_held():
    e = engine()
    a = e.approvals.add("role", {"id": "r1", "title": "R1", "prompt": "x", "tools": ["evidence.observations"], "reason": "r"}, "Director", ["r"])
    b = e.approvals.add("role", {"id": "r2", "title": "R2", "prompt": "x", "tools": ["evidence.observations"], "reason": "r"}, "Director", ["r"])
    assert a.status == "approved" and b.status == "pending" and "roles_per_cycle" in b.needs
    h = e.approvals.add("role", {"id": "r3", "title": "R3", "prompt": "x", "tools": ["evidence.read_raw"], "raw_access": True,
                                 "reason": "r"}, "human", ["r"])
    assert h.status == "approved" and h.note == "a person asked for it"
    e.approvals.new_cycle()
    c = e.approvals.add("role", {"id": "r4", "title": "R4", "prompt": "x", "tools": ["evidence.observations"], "reason": "r"}, "Director", ["r"])
    assert c.status == "approved"


def test_the_scout_runs_once_and_its_proposal_is_absorbed():
    e = engine()
    e.agent_org.set_topology(with_scout(e.agent_org.topology), by="test")
    t = e.agent_org.topology
    assert "scout" in t.roles and t.roles["scout"].output == "architecture_proposal" and {"role": "scout", "scope": "population",
                                                                                           "brief": "Read the stream's shape and propose the team as data."} in t.standing
    windows(e, 8)
    scouts = [n for n in e.agent_org.nodes.values() if n.role == "scout"]
    assert scouts and scouts[0].runs >= 1 and scouts[0].last_report and scouts[0].last_report.get("base")
    # the rules-only Scout proposes the selector's pick; on the planted swarm that is the triage tree the team already
    # runs, so the proposal is a refinement (or nothing) rather than a switch, and nothing waits for a person
    assert all(p.kind != "topology" for p in e.approvals.items)
    assert scouts[0].last_report["reasons"]


def test_promote_writes_a_topology_and_the_pack_preset(tmp_path=None):
    from swarmscope.agents.proposals import promote_preset
    from swarmscope.agents.spec import TOPOLOGY_DIR, load_topology
    e = engine()
    packs = Path(tempfile.mkdtemp())
    out = promote_preset(e, name="test_promoted_team", packs_dir=packs)
    try:
        assert load_topology("test_promoted_team").root == e.agent_org.topology.root
        text = (packs / "swarm_scale" / "oversight.yaml").read_text(encoding="utf-8")
        assert "topology: test_promoted_team" in text and "promoted from a running session" in text
        assert e.pack.oversight["topology"] == "test_promoted_team"
    finally:
        (TOPOLOGY_DIR / "test_promoted_team.yaml").unlink(missing_ok=True)


def test_api_surfaces_proposals_and_decisions():
    from fastapi.testclient import TestClient
    from swarmscope.api.app import S, app
    e = engine()
    S.engine = e
    with TestClient(app) as c:
        p = e.approvals.add("change", {"human": {"interrupt_at": "PAGE"}}, "Director", ["too many interrupts"])
        snap = c.get("/api/snapshot").json()
        assert snap["approvals"]["count"] == 1 and snap["approvals"]["pending"][0]["describe"].startswith("change human")
        assert snap["team"]["topology"] == e.agent_org.topology.id
        r = c.post(f"/api/agents/proposal/{p.id}", json={"action": "approve"})
        assert r.status_code == 200 and r.json()["proposal"]["status"] == "applied"
        assert e.agent_org.topology.human["interrupt_at"] == "PAGE"
        assert c.post("/api/agents/proposal/nope", json={"action": "approve"}).status_code == 404
        lib = c.get("/api/agents/topologies").json()
        assert lib["pack_defaults"]["ai_village"]["preset"] == "desks" and lib["pack_defaults"]["generic_stream"]["preset"] == "auto"
