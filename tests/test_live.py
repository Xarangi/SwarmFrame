"""Live source: hook mapping, control policy, pause/approval, simulator, API."""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from swarmscope.sources.claude_code import map_hook


def test_hook_mapping_files_and_artifacts():
    ents, arts, evs = map_hook({"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "Write",
                                "tool_input": {"file_path": "/work/notes/a.md", "content": "hello world, a long enough line"},
                                "cwd": "/work"})
    assert evs[0].action == "tool.request" and evs[0].object == "file:notes/a.md"
    assert arts and evs[0].artifact == arts[0][0].id
    _, _, evs2 = map_hook({"hook_event_name": "Narration", "session_id": "s1", "text": "All tests pass."})
    assert evs2[0].action == "narration"


def _engine():
    from swarmscope.engine import Engine
    return Engine("claude_code", "default")


def test_policy_denies_and_holds_for_humans():
    async def go():
        eng = _engine()
        cp = eng.control
        d = await cp.decide("a1", "Bash", {"command": "rm -rf /tmp/x"})
        assert d["behavior"] == "deny"
        d = await cp.decide("a1", "WebFetch", {"url": "https://not-allowed.example.net/x"})
        assert d["behavior"] == "deny"
        d = await cp.decide("a1", "Read", {"file_path": "/work/x"})
        assert d["behavior"] == "allow"
        held = asyncio.create_task(cp.decide("a1", "Bash", {"command": "pip install thing"}))
        await asyncio.sleep(0.05)
        assert cp.pending
        rid = next(iter(cp.pending))
        await cp.act("allow", rid)
        assert (await held)["behavior"] == "allow"
        cp.flush()
        assert eng.store.scalar("SELECT count(*) FROM events WHERE action = 'environment.denied'") == 2
    asyncio.run(go())


def test_pause_holds_tool_requests_until_resume():
    async def go():
        eng = _engine()
        cp = eng.control
        cp.register("a2", "A2", "alpha", "task")
        await cp.act("pause", "group:alpha")
        t = asyncio.create_task(cp.decide("a2", "Read", {"file_path": "/x"}))
        await asyncio.sleep(0.7)
        assert not t.done()
        await cp.act("resume", "a2")
        assert (await asyncio.wait_for(t, 2))["behavior"] == "allow"
    asyncio.run(go())


def test_simulator_detects_planted_behaviour():
    from swarmscope.control.sim import SwarmSimulator

    async def go():
        eng = _engine()
        eng.org["investigations"]["node_delay_s"] = 0
        sim = SwarmSimulator(eng.control, 60, rate=20.0)
        eng.control.sim = sim
        sim.start()
        eng.start()
        deadline = asyncio.get_running_loop().time() + 25
        kinds: set[str] = set()
        while asyncio.get_running_loop().time() < deadline and not {"convergence", "content_reuse", "say_do_mismatch"} <= kinds:
            await asyncio.sleep(1)
            for rid in list(eng.control.pending):
                await eng.control.act("deny", rid)
            kinds = {o.kind for o in eng.store.all("Observation")}
        await eng.stop()
        assert {"convergence", "content_reuse", "say_do_mismatch"} <= kinds
    asyncio.run(go())


def test_api_smoke():
    from swarmscope.api.app import app

    with TestClient(app) as c:
        assert c.get("/api/snapshot").status_code == 200
        r = c.post("/api/session", json={"source": "ai_village", "path": "synthetic"})
        assert r.status_code == 200
        for _ in range(12):
            c.post("/api/clock", json={"action": "step"})
        snap = c.get("/api/snapshot").json()
        assert snap["clock"]["index"] >= 12 and snap["source"]["synthetic"]
        reg = c.get("/api/registry").json()
        assert any(m["id"] == "integrity" and m["available"] for m in reg["monitors"])
        assert c.post("/api/config", json={"overrides.coordination.slots.retrieval": "random_sample"}).status_code == 200
        assert c.post("/api/question", json={"text": "What is Ash doing?", "scope": "population"}).status_code == 200
        for v in ("activity_timeline", "actor_resource_graph", "say_vs_do", "artifact_lineage"):
            assert c.get(f"/api/views/{v}").status_code == 200
