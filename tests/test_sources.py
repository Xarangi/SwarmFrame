"""Sources added or reshaped on 2026-10-04: the German message board pack, and catalog mode for Transluce."""
from __future__ import annotations

import asyncio

import numpy as np

from swarmscope.engine import Engine

FAST = {"investigations.node_delay_s": 0, "agents.stub_delay_s": 0, "llm.mode": "stub"}


def windows(e: Engine, n: int) -> None:
    async def go():
        for _ in range(n):
            w = e.clock.next_window()
            if w is None:
                break
            await e.process(w)
    asyncio.run(go())


def test_german_wiki_synthetic_has_the_documented_shape():
    from swarmscope.sources.german_wiki import synthesize
    b = synthesize(n_groups=30, seed=3)
    kinds = {g["kind"] for g in b.meta["ground_truth"]}
    assert kinds == {"convergence", "propagation", "rate", "environment", "identity"}
    acts = {e.action for e in b.events}
    assert {"resource.write", "chat.message", "environment.moderation_delete"} <= acts
    assert all(x.identity_confidence == "partial" for x in b.entities if x.type in ("actor", "moderator"))
    assert b.events == sorted(b.events, key=lambda e: e.ts)


def test_german_wiki_pack_composes_a_dashboard_and_world():
    e = Engine("german_wiki", "default", slice_override={"groups": 24}, overrides=FAST)
    assert {p.id for p in e.dashboard.spec.pages} >= {"brief", "board"}
    assert e.dashboard.spec.terminology == {"agent": "handle", "resource": "page"}
    windows(e, 40)
    e.world.ensure_spec()
    s = e.world.spec
    assert s.shape == "wiki" and s.by == "pack" and s.unit["model"] == "sprite"
    assert e.world.table()["identity_partial"]["status"] == "observed"


def test_transluce_is_a_catalog_with_a_whole_record_brief_and_a_mix_map():
    e = Engine("transluce", "default", path="synthetic", overrides=FAST)
    windows(e, 30)
    from swarmscope.dashboard.brief import brief_digest
    b = brief_digest(e)
    assert b.get("catalog") and "reports" in b["status"] and b["glance"]["total"]["value"] > 0
    assert {"total", "recent", "targets", "significant"} <= set(b["glance"]) and b.get("field")
    e.world.ensure_spec()
    assert e.world.spec.metric.get("layout") == "mix"
    st = e.world.state()
    assert st["catalog"] and st["n"] == len(e.world.layout.ids)          # every target, not only recent ones
    k = len(st["mix_families"])
    mix = np.frombuffer(__import__("base64").b64decode(st["units"]["mix"]), dtype=np.uint8).reshape(-1, k)
    assert mix.shape[0] == st["n"] and (abs(mix.sum(axis=1).astype(int) - 255) <= k).all()
    assert not any(e.world.flags.values())                                # no shuffled-swarm glow on a catalog map


def test_every_replay_offers_speeds_and_its_default_is_one_of_them():
    from swarmscope.ingest.packs import load_pack
    for sid in ("swarm_scale", "ai_village", "transluce", "german_wiki"):
        src = load_pack(sid).source
        assert src.get("speeds") and src.get("replay_hours"), sid
        assert src["autoplay"] in [s["v"] for s in src["speeds"]], sid


def test_watch_live_replays_the_busiest_stretch_in_short_windows_after_a_warm_up():
    from datetime import timedelta
    e = Engine("swarm_scale", "default", slice_override={"agents": 120, "hours": 36}, overrides=FAST, live_stretch=True)
    lr = e.live_replay
    assert lr and e.clock.window == timedelta(seconds=30) and not lr["on"]
    assert e.clock.cursor == lr["at"] - timedelta(minutes=lr["warmup_min"]) and e.clock.time_scale > 1000
    assert e.snapshot()["live_replay"]["label"]
    # a stretch outside the loaded data falls back to an ordinary replay
    v = Engine("ai_village", "default", path="synthetic", overrides=FAST, live_stretch=True)
    assert v.live_replay is None and v.clock.window == timedelta(minutes=20)


def test_the_live_column_narrates_each_beat_in_counts_only():
    from swarmscope.assistant.chat import ChatHub
    e = Engine("swarm_scale", "default", slice_override={"agents": 120, "hours": 6}, overrides=FAST)
    windows(e, 3)
    hub = ChatHub(lambda: e)
    hub.narrate["every_s"] = 0
    hub._narrate(e)
    lines = [m for m in hub.messages if m.role == "narration"]
    assert lines and "events by" in lines[-1].text and lines[-1].meta["windows"] == 3
    hub._narrate(e)                                       # nothing new: no repeat line
    assert len([m for m in hub.messages if m.role == "narration"]) == len(lines)


def test_findings_narration_and_answers_cite_their_sources():
    import asyncio
    from swarmscope.assistant.chat import ChatHub, ChatMessage
    from swarmscope.dashboard.brief import brief_digest
    e = Engine("swarm_scale", "default", slice_override={"agents": 120, "hours": 12}, overrides=FAST)
    windows(e, 40)
    items = brief_digest(e)["items"]
    assert items, "the planted swarm should raise findings"
    cited = [i for i in items if i["cites"]]
    assert len(cited) >= len(items) // 2
    for c in cited[0]["cites"]:
        assert c["kind"] in ("claim", "event", "entity") and c["n"] >= 1 and c["label"]
    assert [c["n"] for c in cited[0]["cites"]] == list(range(1, len(cited[0]["cites"]) + 1))
    assert any(c["kind"] == "event" for i in cited for c in i["cites"])     # claims resolve to recorded events

    hub = ChatHub(lambda: e)
    hub.narrate["every_s"] = 0
    hub._narrate(e)
    n = [m for m in hub.messages if m.role == "narration"][-1]
    assert n.meta["cites"] and n.meta["cites"][0]["kind"] in ("event", "entity")

    cid = next(c["id"] for i in cited for c in i["cites"] if c["kind"] == "claim")
    m = hub.post(ChatMessage(role="assistant", via="copilot", text=f"Two cohorts converged on one resource {cid}."))
    assert m.meta["cites"][0]["id"] == cid
    m = hub.post(ChatMessage(role="assistant", via="copilot", text="I think this looks fine overall " * 6))
    assert m.meta["cites"] == [] and m.meta["uncited"]
    assert asyncio.run(hub.copilot._stub("what needs my attention?")).count("clm_") >= 1


def test_findings_come_with_plain_explanations_and_names_are_explained():
    from swarmscope.dashboard.brief import brief_digest
    e = Engine("swarm_scale", "default", slice_override={"agents": 120, "hours": 12}, overrides=FAST)
    windows(e, 40)
    items = brief_digest(e)["items"]
    assert items and all(set(i["explain"]) >= {"what", "why", "benign", "check"} for i in items)
    for i in items:
        assert "σ" not in i["headline"] + i["explain"]["what"]          # no statistical shorthand reaches a person
        assert "exposure path" not in i["explain"]["what"]
    assert any(i["kind"] == "reuse" for i in items)                    # watcher kind content_reuse maps to the Brief's
    assert e.profile.naming and "team" in e.profile.naming
    assert all(x.label.startswith("team ") for x in e.store.entities("agent"))
    assert "workstreams" in (e.exec_state.population_state or "")


def test_the_lead_sends_explorers_where_findings_open_and_lets_them_go():
    e = Engine("swarm_scale", "default", slice_override={"agents": 120, "hours": 12}, overrides=FAST)
    assert e.agent_org.topology.id == "lead"
    windows(e, 40)
    org = e.agent_org
    roles = [n.role for n in org.active()]
    assert roles.count("lead") == 1 and 1 <= roles.count("explorer") <= 4
    open_scopes = {i.scope for i in e.cases().open_cases()}
    assert all(n.scope in open_scopes for n in org.active() if n.role == "explorer")


def test_the_model_picker_puts_the_lead_and_helpers_on_the_primary_model():
    from swarmscope.config import llm_label, role_llm
    org = {"llm": {"mode": "custom", "primary": {"model": "claude-opus-5-5", "effort": "medium"},
                   "subagents": {"model": "claude-haiku-4-5-20251001", "effort": "low"}}}
    assert role_llm(org, "copilot")["model"] == "claude-opus-5-5" and role_llm(org, "investigator")["model"].startswith("claude-haiku")
    assert "Opus 5.5" in llm_label(org)["short"]
    e = Engine("swarm_scale", "default", slice_override={"agents": 60, "hours": 2},
               overrides={**FAST, "llm.mode": "custom", "llm.primary": org["llm"]["primary"], "llm.subagents": org["llm"]["subagents"]})
    lead = e.agent_org.topology.roles["lead"]
    assert e.agent_org.model_for(lead) == ("claude-opus-5-5", "medium")
    assert e.agent_org.model_for(e.agent_org.topology.roles["explorer"])[0].startswith("claude-haiku")


def test_live_column_cadence_is_settable():
    from fastapi.testclient import TestClient
    from swarmscope.api.app import app
    with TestClient(app) as c:
        c.post("/api/session", json={"source": "swarm_scale", "slice": {"agents": 60, "hours": 2}, "overrides": FAST})
        st = c.post("/api/chat/settings", json={"narrate": {"every_s": 300}, "commentary": {"on": False}}).json()
        assert st["narrate"]["every_s"] == 300 and st["commentary"]["on"] is False
        opts = c.get("/api/llm/options").json()
        assert {p["id"] for p in opts["providers"]} == {"none", "claude_code", "anthropic_api"} and opts["models"]


def test_whats_going_on_summarises_every_group_whatever_the_severity():
    from swarmscope.dashboard.brief import brief_digest
    e = Engine("swarm_scale", "default", slice_override={"agents": 120, "hours": 6}, overrides=FAST)
    windows(e, 12)
    o = brief_digest(e)["overview"]
    assert o and o["groups"] and o["summary"].startswith("In the last")
    g = o["groups"][0]
    assert g["active"] > 0 and g["doing"] and g["cites"] and g["trend"] in ("new", "rising", "steady", "falling", "quiet")
    assert o["group_plural"] == "teams"


def test_reasoning_is_read_from_every_provider_shape():
    from swarmscope.sources.ai_village import reasoning_of
    anthropic = {"content": [{"type": "thinking", "thinking": "plan A"}, {"type": "tool_use", "name": "bash", "input": {}}]}
    openai_chat = {"content": "hi", "reasoning": "plan B", "tool_calls": [{"function": {"name": "click"}}]}
    responses = [{"type": "reasoning", "summary": [{"text": "plan C"}], "content": []}, {"type": "function_call", "name": "type"}]
    gemini = {"candidates": [{"content": {"parts": [{"thought": True, "text": "plan D"}, {"functionCall": {"name": "scroll"}}]}}]}
    assert reasoning_of(anthropic) == ("plan A", ["bash"])
    assert reasoning_of(openai_chat) == ("plan B", ["click"])
    assert reasoning_of(responses) == ("plan C", ["type"])
    assert reasoning_of(gemini) == ("plan D", ["scroll"])
