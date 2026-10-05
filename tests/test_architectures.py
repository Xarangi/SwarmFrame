"""Oversight architectures (docs/OVERSIGHT_ARCHITECTURES.md): the topology grammar, the static library, per-pack
oversight.yaml, the selector's explained choice, field partitions, standing roles and record-batch cadence."""
from __future__ import annotations

import asyncio
import copy

import pytest

from swarmscope.agents.spec import TopologyError, from_dict, list_topologies, load_topology

FAST = {"investigations.node_delay_s": 0, "agents.stub_delay_s": 0, "llm.mode": "stub"}


def windows(e, n: int) -> None:
    async def go():
        for _ in range(n):
            w = e.clock.next_window()
            if w is None:
                break
            await e.process(w)
    asyncio.run(go())


def test_library_has_the_planned_shapes_and_the_grammar_aliases_hold():
    ids = {t["id"] for t in list_topologies()}
    assert {"triage_tree", "desks", "board_watch", "catalog_review"} <= ids
    d = load_topology("desks")
    assert d.partition["by"] == "group" and d.divisions["strategy"] == "by_group"
    assert {s["role"] for s in d.standing} == {"auditor", "diarist", "integrity_specialist", "goals_specialist"}
    assert d.questions["*"] == "specialist" and d.human["interrupt_at"] == "ALERT" and d.roles["director"].model.startswith("claude-sonnet")
    b = load_topology("board_watch")
    assert b.divisions["strategy"] == "by_field" and b.divisions["field"] == "family"
    assert b.maintain["sector_role"] == "sector_lead" and b.maintain["sector_span"] == 6     # levels[0] drives sectors
    c = load_topology("catalog_review")
    assert c.cadence == {"kind": "records", "every": 500} and c.root == "curator"
    for t in ("desks", "board_watch", "catalog_review"):
        for r in load_topology(t).roles.values():
            assert r.prompt_text() and not r.prompt_text().startswith("(missing")


def test_grammar_validation():
    base = load_topology("desks").to_dict()
    for mutate, msg in [
        (lambda d: d["partition"].update(by="astrology"), "partition.by"),
        (lambda d: d.update(partition={"by": "field"}), "partition.field"),
        (lambda d: d.update(levels=[{"role": "ghost", "span": 5}]), "levels"),
        (lambda d: d.update(standing=[{"role": "ghost"}]), "standing"),
        (lambda d: d["questions"].update(identity="ghost"), "questions"),
        (lambda d: d.update(cadence={"kind": "moons"}), "cadence.kind"),
        (lambda d: d["human"].update(interrupt_at="LOUD"), "interrupt_at"),
    ]:
        x = copy.deepcopy(base)
        mutate(x)
        with pytest.raises(TopologyError, match=msg):
            from_dict(x, "x")


def test_packs_name_their_team_and_the_engine_builds_it():
    from swarmscope.engine import Engine
    # the default team is the lead analyst with explorers; the pack names a preset that suits it
    d = Engine("german_wiki", "default", slice_override={"groups": 24}, overrides=FAST)
    assert d.agent_org.topology.id == "lead" and d.team_choice["by"] == "default" and d.pack.oversight["preset"] == "board_watch"
    e = Engine("german_wiki", "default", slice_override={"groups": 24}, overrides={**FAST, "agents.topology": "board_watch"})
    assert e.team_choice["by"] == "override" and e.agent_org.topology.id == "board_watch"
    t = e.team_summary()
    assert t["partition"]["field"] == "family" and t["reasons"] and t["shape"]["identity"] == "partial"
    windows(e, 12)
    kinds = {d.kind for d in e.agent_org.divisions.values()}
    assert kinds == {"field"} and len(e.agent_org.divisions) >= 2            # one division per namespace
    roles = {n.role for n in e.agent_org.active()}
    assert {"director", "namespace_analyst", "auditor"} <= roles                 # standing auditor, analysts covering namespaces
    # a session override wins over the pack
    e2 = Engine("german_wiki", "default", slice_override={"groups": 12}, overrides={**FAST, "agents.topology": "flat_pool"})
    assert e2.team_choice["by"] == "override" and e2.agent_org.topology.id == "flat_pool"


def test_catalog_review_partitions_targets_and_cycles_on_records():
    from swarmscope.engine import Engine
    e = Engine("transluce", "default", path="synthetic", overrides={**FAST, "agents.topology": "catalog_review"})
    assert e.agent_org.topology.id == "catalog_review"
    windows(e, 20)
    divs = list(e.agent_org.divisions.values())
    assert divs and all(d.kind == "field" and not d.agents and d.resources for d in divs)   # identity-free: targets, not agents
    roles = {n.role for n in e.agent_org.active()}
    assert {"curator", "grade_auditor", "chronicler"} <= roles
    assert e.agent_org.cycle_index >= 1 and getattr(e.agent_org, "last_cycle_events", 0) > 0


def test_the_selector_explains_itself_on_a_stream_without_a_named_team():
    from swarmscope.agents.selector import select
    sh = {"identity": "strong", "population": 20, "cohorts": 3, "catalog": False, "communication": True, "groups": True,
          "environment": True, "resources": True, "axes": [{"field": "family", "distinct": 5, "share": 1.0}]}
    r = select(sh, {"desks", "triage_tree", "board_watch", "catalog_review"})
    assert r["topology"] == "desks" and r["partition"]["by"] == "group" and "agents" in r["reasons"][0]
    sh.update(population=4000, cohorts=70)
    assert select(sh, {"desks", "triage_tree"})["topology"] == "triage_tree"
    sh.update(identity="partial", population=300)
    assert select(sh, {"desks", "triage_tree", "board_watch"})["topology"] == "board_watch"
    sh.update(catalog=True)
    assert select(sh, {"catalog_review", "triage_tree"})["topology"] == "catalog_review"
    r = select({"identity": "strong", "population": 300, "cohorts": 4, "catalog": False, "communication": False, "groups": False,
                "environment": False, "resources": False, "axes": [{"field": "repo", "distinct": 9, "share": None}]}, {"triage_tree"})
    assert r["topology"] == "triage_tree" and "repo" not in str(r["partition"])   # population > 60 → the tree, by cohort


def test_village_gets_desks_with_standing_specialists():
    from swarmscope.engine import Engine
    e = Engine("ai_village", "default", path="synthetic", overrides={**FAST, "agents.topology": "desks"})
    assert e.agent_org.topology.id == "desks"
    windows(e, 14)
    roles = {n.role for n in e.agent_org.active()}
    assert {"director", "desk_analyst", "diarist", "auditor", "integrity_specialist"} <= roles
    snap = e.snapshot()
    assert snap["team"]["topology"] == "desks" and snap["team"]["roles"]["director"]["model"].startswith("claude-sonnet")
