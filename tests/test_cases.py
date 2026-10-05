"""The findings ledger (org/cases.py): tracking, the two-view rule, the authority budget, acknowledgement, aging,
the live escalation path from an agent tool, and the Brief and API surfaces."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from swarmscope.core.models import ExecutiveState, OperationalState
from swarmscope.org.cases import Cases

T0 = datetime(2026, 1, 1, 12, 0)
W = timedelta(minutes=10)


def ledger(**budget):
    st = ExecutiveState()
    b = {"alerts_per_cycle": 3, "alerts_used": 0, "ack_sla_windows": 3, "quiet_windows": 4, **budget}
    return st, Cases(st, T0, budget=b, exists=lambda e: e.startswith("evt") or e.startswith("clm"))


def test_a_case_opens_at_investigate_and_an_alert_waits_for_a_second_view():
    st, c = ledger()
    r = c.record(scope="agent:a1", title="a1 wrote the same block to 9 files", level="ALERT", by="watcher reuse",
                 view="monitor:reuse", evidence=["evt_1"])
    inc = r["case"]
    assert r["new"] and inc.level == OperationalState.INVESTIGATE and r["held"].startswith("awaiting")
    assert inc.pending_level == "ALERT" and inc.history[-1].held
    # the second view arrives at INVESTIGATE: the held ALERT is granted automatically
    r2 = c.record(scope="agent:a1", title="confirmed", level="INVESTIGATE", by="Division analyst", view="role:analyst",
                  evidence=["clm_2"])
    assert r2["rose"] and r2["case"].level == OperationalState.ALERT and r2["case"].pending_level is None
    assert [h.level for h in r2["case"].history if not h.held] == ["INVESTIGATE", "ALERT"]
    assert r2["case"].views == ["monitor:reuse", "role:analyst"]
    assert c.summary(W)["unacknowledged"] == 1


def test_evidence_must_exist_and_people_are_never_held():
    st, c = ledger()
    c.record(scope="agent:b", title="x", level="INVESTIGATE", by="m", view="monitor:m")
    r = c.record(scope="agent:b", title="x", level="ALERT", by="Specialist", view="role:specialist", evidence=["nope"])
    assert r["held"] == "cited evidence not found" and r["case"].level == OperationalState.INVESTIGATE
    r = c.record(scope="agent:b", title="x", level="PAGE", by="human", view="human")
    assert r["rose"] and r["case"].level == OperationalState.PAGE


def test_authority_budget_caps_alerts_per_cycle():
    st, c = ledger(alerts_per_cycle=1)
    for i in range(3):
        c.record(scope=f"agent:{i}", title=f"t{i}", level="INVESTIGATE", by="m", view="monitor:m")
        c.record(scope=f"agent:{i}", title=f"t{i}", level="ALERT", by="a", view="role:a", evidence=["evt_1"])
    levels = sorted(i.level.value for i in st.active_incidents)
    assert levels == ["ALERT", "INVESTIGATE", "INVESTIGATE"]
    held = [i for i in st.active_incidents if i.pending_level == "ALERT"]
    assert len(held) == 2 and all(h.history[-1].held.startswith("authority") for h in held)
    # next cycle the budget is fresh: the next sighting promotes a held case
    c.budget["alerts_used"] = 0
    r = c.record(scope=held[0].scope, title="again", level="INVESTIGATE", by="m", view="monitor:m")
    assert r["rose"] and r["case"].level == OperationalState.ALERT


def test_acknowledge_overdue_and_aging():
    st, c = ledger()
    c.record(scope="agent:z", title="z", level="INVESTIGATE", by="m", view="monitor:m")
    c.record(scope="agent:z", title="z", level="ALERT", by="a", view="role:a", evidence=["evt_9"])
    inc = st.active_incidents[0]
    later = Cases(st, T0 + 4 * W, budget=c.budget)
    assert later.overdue(inc, W) and later.summary(W)["overdue"] == 1
    later.acknowledge(inc.id, "human")
    assert not later.overdue(inc, W) and inc.acknowledged_by == "human" and inc.history[-1].reason == "acknowledged"
    # a quiet INVESTIGATE fades with a trail; the ALERT never does
    c.record(scope="agent:q", title="q", level="INVESTIGATE", by="m", view="monitor:m")
    far = Cases(st, T0 + 5 * W, budget=c.budget)
    changed = far.age(W)
    q = next(i for i in st.active_incidents if i.scope == "agent:q")
    assert q in changed and q.status == "monitoring" and inc.status == "open"
    farther = Cases(st, T0 + 9 * W, budget=c.budget)
    farther.age(W)
    assert q.status == "resolved" and q.history[-1].by == "ledger"
    # lowering is explicit and recorded
    farther.lower(inc.id, "WATCH", "human", "false alarm after review")
    assert inc.level == OperationalState.WATCH and inc.history[-1].reason.startswith("false alarm")


def test_an_agent_escalation_reaches_the_brief_and_the_executive_fast_path():
    from swarmscope.agents.org_tools import OrgTools
    from swarmscope.engine import Engine
    e = Engine("swarm_scale", "default", slice_override={"agents": 60, "hours": 2},
               overrides={"investigations.node_delay_s": 0, "agents.stub_delay_s": 0, "llm.mode": "stub",
                          "agents.topology": "triage_tree"})

    async def go():
        for _ in range(2):
            w = e.clock.next_window()
            await e.process(w)
    asyncio.run(go())
    root = e.agent_org.nodes[e.agent_org.root_id] if e.agent_org.root_id else e.agent_org.spawn("director", "population")
    tools = OrgTools(e.agent_org, root)
    aid = e.store.sql("SELECT actor FROM events WHERE actor IS NOT NULL LIMIT 1")[0]["actor"]
    heard: list = []
    q = asyncio.Queue()
    e.subscribers.append(q)
    r1 = tools.escalate_finding(scope=f"agent:{aid}", title="one agent, two stories", level="ALERT",
                                reason="says one thing, does another", evidence_ids=[])
    assert r1["ok"] and r1["level"] == "INVESTIGATE" and r1["held"].startswith("awaiting")
    assert not e.escalation_pending
    r2 = e.escalate(scope=f"agent:{aid}", title="one agent, two stories", level="INVESTIGATE", by="Auditor",
                    view="role:auditor")
    assert r2["level"] == "ALERT" and r2["rose"] and e.escalation_pending
    while not q.empty():
        heard.append(q.get_nowait()["type"])
    assert "escalation" in heard
    from swarmscope.dashboard.brief import brief_digest
    b = brief_digest(e)
    row = next(x for x in b["items"] if f"agent:{aid}" in (x["scope"], *[m for m in x["members"]]) or x["scope"] == f"agent:{aid}")
    assert row["needs_ack"] and row["views"] == ["role:director", "role:auditor"] and b["cases"]["unacknowledged"] >= 1
    assert any(h["level"] == "ALERT" for h in row["history"])
    # the executive runs at the next window because of the pending escalation, and the budget resets
    asyncio.run(e.process(e.clock.next_window()))
    assert not e.escalation_pending and e.authority["alerts_used"] == 0
    assert any(i.scope == f"agent:{aid}" and i.level == OperationalState.ALERT for i in e.exec_state.active_incidents)
