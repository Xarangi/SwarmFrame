"""SwarmFrame HTTP + WebSocket API. Serves the built dashboard from frontend/dist when present."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from swarmscope.agents.spec import TopologyError
from fastapi import Body, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from swarmscope.api import views as V
from swarmscope.config import list_orgs
from swarmscope.engine import Engine
from swarmscope.ingest.packs import ROOT, list_packs
from swarmscope.org.executive import ExecutiveRole
from swarmscope.org.monitor import load_manifests
from swarmscope.org.risk import POLICIES
from swarmscope.org.watchers import WATCHERS
from swarmscope.strategies.slots import SLOT_DOCS, SLOTS


def _default(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, set):
        return sorted(o)
    return str(o)


class J(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, default=_default).encode()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from swarmscope.assistant.chat import ChatHub
    S.hub = ChatHub(lambda: S.engine)
    S.hub.start()
    params = json.loads(os.environ.get("SWARMSCOPE_SESSION", "{}") or "{}")
    if params.get("source"):
        await _new_session(params)
    yield
    if S.engine:
        await S.engine.stop()


app = FastAPI(title="SwarmFrame", default_response_class=J, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class State:
    engine: Engine | None = None
    params: dict[str, Any] = {}
    hub: Any = None
    clients: list = []              # every connected dashboard; each new session broadcasts to all of them


S = State()


def eng() -> Engine:
    if S.engine is None:
        raise HTTPException(409, "no active session")
    return S.engine


async def _new_session(params: dict[str, Any]) -> Engine:
    if S.engine:
        await S.engine.stop()
    subs = S.clients
    source = params.get("source", "ai_village")
    slice_override = params.get("slice") or ({"goal": params["goal"]} if params.get("goal") else None)
    loop = asyncio.get_running_loop()
    e = await loop.run_in_executor(None, lambda: Engine(source, params.get("org", "default"), path=params.get("path"),
                                                        overrides=params.get("overrides"), slice_override=slice_override,
                                                        persist_dashboard=True, live_stretch=bool(params.get("live"))))
    e.subscribers = subs
    if e.clock is not None and params.get("speed"):
        e.clock.speed = float(params["speed"])
    if e.stream is not None and params.get("demo_feed"):
        f = params["demo_feed"] if isinstance(params["demo_feed"], dict) else {}
        e.stream.start_demo(int(f.get("agents", 300)), float(f.get("hours", 8)), float(f.get("speed", 120)))
    if e.control and params.get("simulate"):
        from swarmscope.control.sim import SwarmSimulator
        e.control.sim = SwarmSimulator(e.control, int(params["simulate"]), rate=float(params.get("sim_rate", 1.0)))
        e.control.sim.start()
    S.engine, S.params = e, params
    if S.hub is not None:
        S.hub.attach(e)
    e.clock.paused = not params.get("autoplay", False) and not e.profile.live and not e.live_replay
    if params.get("speed") not in (None, ""):                 # the replay speed chosen when composing
        e.autoplay_override = params["speed"]
    e.start()
    e.broadcast()
    return e


# ------------------------------------------------------------------ sessions & registry
@app.get("/api/sources")
def sources() -> list[dict[str, Any]]:
    out = []
    for p in list_packs():
        path = ROOT / p.source.get("default_path", f"data/{p.id}")
        out.append({"id": p.id, "title": p.capabilities.title, "description": p.capabilities.description,
                    "live": p.capabilities.live, "noun": p.capabilities.entity_noun,
                    "has_data": p.capabilities.live or path.exists(), "fetch_sets": list((p.source.get("fetch") or {}).get("sets", {})),
                    "speeds": p.source.get("speeds") or [], "autoplay": p.source.get("autoplay"),
                    "replay_hours": p.source.get("replay_hours"), "replay_hours_synthetic": p.source.get("replay_hours_synthetic"),
                    "replay_hours_full": p.source.get("replay_hours_full"), "slice": p.source.get("slice"),
                    "live_stretch": p.source.get("live_stretch"), "play_default": p.source.get("play_default", "live"),
                    "capabilities": {k: v.model_dump() for k, v in p.capabilities.capabilities.items()}})
    return out


@app.get("/api/sources/{sid}/slices")
def slices(sid: str) -> list[dict[str, Any]]:
    """Replay slices (village goals) with activity counts. Cached; structure only."""
    if sid != "ai_village":
        return []
    from swarmscope.sources.slices import village_slices
    return village_slices()


@app.get("/api/orgs")
def orgs() -> list[dict[str, str]]:
    return list_orgs()


@app.post("/api/session")
async def session(params: dict[str, Any] = Body(...)) -> dict[str, Any]:
    e = await _new_session(params)
    return {"ok": True, "source": e.profile.source, "events": e.store.count_events()}


@app.get("/api/snapshot")
def snapshot() -> dict[str, Any]:
    if S.engine is None:
        return {"empty": True}
    return eng().snapshot()


@app.get("/api/profile")
def profile() -> dict[str, Any]:
    return eng().profile.model_dump()


@app.get("/api/registry")
def registry() -> dict[str, Any]:
    e = S.engine
    mans = load_manifests()
    mons = []
    for m in mans.values():
        ok, missing = m.satisfiable(e.profile) if e else (True, [])
        mons.append({"id": m.id, "title": m.title, "description": m.description, "requires": m.requires,
                     "optional": m.optional, "watchers": m.watchers, "default_slots": m.slots, "tunables": m.tunables,
                     "available": ok, "missing": missing, "enabled": bool(e and m.id in e.monitors),
                     "slots": e.monitors[m.id].slots if e and m.id in e.monitors else m.slots})
    return {
        "monitors": mons,
        "slots": {s: [{"id": k, "doc": SLOT_DOCS.get(k, "")} for k in v] for s, v in SLOTS.items()},
        "watchers": [{"id": w.id, "title": w.title, "requires": list(w.requires), "defaults": w.defaults}
                     for w in (c() for c in WATCHERS.values())],
        "executive_strategies": ExecutiveRole.STRATEGIES,
        "risk_policies": list(POLICIES),
        "autonomy": ["observe", "assisted", "auto_investigate"],
        "llm_modes": ["stub", "cheap", "full", "custom"],
        "org": e.org if e else None,
        "profile": e.profile.model_dump() if e else None,
        "views": e.pack.views if e else [],
    }


@app.post("/api/config")
def config(changes: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return eng().reconfigure(changes)


@app.post("/api/clock")
async def clock(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    e = eng()
    act = body.get("action")
    if act == "play":
        e.clock.paused = False
    elif act == "pause":
        e.clock.paused = True
    elif act == "speed":
        e.clock.speed = max(1e-4, min(60.0, float(body.get("value", 2))))
    elif act == "scale" and hasattr(e.clock, "set_time_scale"):
        e.clock.set_time_scale(float(body.get("value", 60)))
    elif act == "skip_gaps" and hasattr(e.clock, "skip_gaps"):
        e.clock.skip_gaps = bool(body.get("value", True))
    elif act == "jump":
        from swarmscope.ingest.adapter import parse_ts
        to = parse_ts(body.get("to"))
        if to is None:
            raise HTTPException(400, "jump needs an ISO timestamp in 'to'")
        if to <= e.clock.now():
            # backwards: restart the session and catch up to the target
            params = dict(S.params)
            e = await _new_session(params)
        asyncio.create_task(e.jump(to))
        return {**e.clock.describe(), "jumping_to": to}
    elif act == "step":
        w = e.clock.next_window()
        if w:
            async with e.lock:
                await e.process(w)
    e.broadcast()
    return e.clock.describe()


# ------------------------------------------------------------------ views & evidence
@app.get("/api/views/{name}")
def view(name: str, hours: float | None = None, family: str | None = None, actor: str | None = None,
         n: int | None = None) -> dict[str, Any]:
    if name not in V.VIEWS:
        raise HTTPException(404, f"no view {name}")
    kw = {k: v for k, v in dict(hours=hours, family=family, actor=actor, n=n).items() if v is not None}
    return V.VIEWS[name](eng(), **kw)


@app.get("/api/claim/{cid}")
def claim(cid: str) -> dict[str, Any]:
    d = V.claim_detail(eng(), cid)
    if not d:
        raise HTTPException(404)
    return d


@app.get("/api/event/{eid:path}")
def event(eid: str) -> dict[str, Any]:
    d = V.event_detail(eng(), eid)
    if not d:
        raise HTTPException(404)
    return d


@app.get("/api/entity/{eid:path}")
def entity(eid: str) -> dict[str, Any]:
    d = V.entity_detail(eng(), eid)
    if not d:
        raise HTTPException(404)
    return d


@app.get("/api/observations")
def observations(scope: str | None = None, n: int = 50) -> list[dict[str, Any]]:
    obs = [o for o in eng().store.all("Observation") if not scope or o.scope == scope]
    return [o.model_dump(mode="json") for o in sorted(obs, key=lambda o: o.window_end)[-n:]]


@app.get("/api/attention/records")
def attention_records(n: int = 200) -> list[dict[str, Any]]:
    return [r.model_dump(mode="json") for r in eng().store.all("AttentionRecord")[-n:]]


@app.get("/api/executive/history")
def executive_history() -> list[dict[str, Any]]:
    rows = eng().store.sql("SELECT body FROM docs WHERE kind = 'ExecutiveState' ORDER BY ts")
    return [json.loads(r["body"]) for r in rows][-40:]


# ------------------------------------------------------------------ human inputs
@app.post("/api/question")
def question(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    q = eng().human_question(body["text"], body.get("scope"), body.get("kind", "general"))
    return q.model_dump(mode="json")


@app.post("/api/directive")
def directive(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    d = eng().human_directive(body["kind"], body.get("scope"), body.get("payload") or {}, body.get("reason", ""))
    return d.model_dump(mode="json")


@app.post("/api/directive/{did}/approve")
def approve(did: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    d = eng().approve_directive(did, bool(body.get("approve", True)))
    return d.model_dump(mode="json") if d else {}


@app.post("/api/ledger/pin")
def pin(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return eng().pin(body["text"], body.get("kind", "pinned_fact"), body.get("evidence")).model_dump(mode="json")


@app.delete("/api/ledger/{entry_id}")
def unpin(entry_id: str) -> dict[str, Any]:
    eng().unpin(entry_id)
    return {"ok": True}


@app.post("/api/investigation/{iid}/action")
def investigation_action(iid: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    inv = eng().investigations.act(iid, body["action"], body.get("node_id"), body.get("role"), body.get("text"))
    if not inv:
        raise HTTPException(404)
    return inv.model_dump(mode="json")


# ------------------------------------------------------------------ analyst organization
@app.get("/api/agents")
def agents_snapshot() -> dict[str, Any]:
    return eng().agent_org.snapshot()


@app.get("/api/agents/node/{nid}")
def agent_node(nid: str) -> dict[str, Any]:
    o = eng().agent_org
    n = o.nodes.get(nid)
    if not n:
        raise HTTPException(404)
    claims = [eng().store.get("Claim", c) for c in (n.last_report or {}).get("claim_ids", [])]
    return {"node": n.model_dump(mode="json"), "scope_label": o.scope_label(n.scope),
            "scope_description": o.describe_scope(n.scope), "role": o.topology.to_dict()["roles"].get(n.role),
            "report": n.last_report, "claims": [c.model_dump(mode="json") for c in claims if c],
            "runs": [r.model_dump(mode="json") for r in o.runs if r.node == nid][-20:],
            "children": [o.nodes[c].model_dump(mode="json", exclude={"last_report"}) for c in n.children if c in o.nodes]}


@app.post("/api/agents/action")
async def agents_action(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    action = body.pop("action")
    try:
        return await eng().agent_org.human_action(action, **body)
    except (KeyError, ValueError, PermissionError) as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/agents/delegations")
def delegations(n: int = 80, node: str | None = None) -> dict[str, Any]:
    """The delegation log: who fired off what, why, and what came back. Also a JSON-lines file (see `path`)."""
    d = eng().delegations
    return {**d.summary(), "recent": d.recent(int(n), node)}


@app.get("/api/agents/proposals")
def proposals() -> dict[str, Any]:
    return eng().approvals.summary()


@app.post("/api/agents/proposal/{pid}")
def proposal_action(pid: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """approve | decline {reason} | revert, for one proposal. Approved proposals apply between cycles."""
    e = eng()
    act = body.get("action")
    try:
        if act == "approve":
            p = e.approvals.approve(pid)
            e.approvals.apply_due()
        elif act == "decline":
            p = e.approvals.decline(pid, reason=body.get("reason", ""))
        elif act == "revert":
            p = e.approvals.revert(pid)
        else:
            raise HTTPException(400, "action is approve, decline or revert")
    except KeyError:
        raise HTTPException(404, "no such proposal")
    except (ValueError, TopologyError) as exc:
        raise HTTPException(400, str(exc))
    e.broadcast()
    return {"ok": True, "proposal": p.model_dump(mode="json")}


@app.post("/api/agents/promote")
def promote(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Save the running team as a topology and make it this source's preset (packs/<id>/oversight.yaml)."""
    from swarmscope.agents.proposals import promote_preset
    try:
        out = promote_preset(eng(), body.get("name"))
    except TopologyError as exc:
        raise HTTPException(400, str(exc))
    eng().broadcast()
    return out


@app.get("/api/agents/topologies")
def topologies() -> dict[str, Any]:
    from swarmscope.agents.schemas import SCHEMAS
    from swarmscope.agents.spec import (DIVISION_STRATEGIES, EVIDENCE_TOOLS, MEMORY_MODES, ORG_TOOLS, SCOPE_KINDS,
                                        list_topologies)
    from swarmscope.agents.deterministic import BEHAVIOURS
    cur = None
    if S.engine:
        t = eng().agent_org.topology
        cur = t.to_dict()
        for rid, r in t.roles.items():
            cur["roles"][rid]["prompt_text"] = r.prompt_text()
    from swarmscope.ingest.packs import list_packs
    defaults = {}
    for pk in list_packs():
        ov = pk.oversight or {}
        defaults[pk.id] = {"topology": ov.get("topology") or S_default_topology(), "preset": ov.get("preset"),
                           "reason": ov.get("reason", "")}
    return {"topologies": list_topologies(), "current": cur, "pack_defaults": defaults,
            "team": eng().team_summary() if S.engine else None,
            "vocab": {"evidence_tools": EVIDENCE_TOOLS, "org_tools": ORG_TOOLS, "schemas": list(SCHEMAS) + ["custom"],
                      "memory": MEMORY_MODES, "scopes": SCOPE_KINDS, "division_strategies": DIVISION_STRATEGIES,
                      "kinds": sorted(set(BEHAVIOURS) | {"director"}), "backends": ["claude_code", "stub", "external"],
                      "efforts": ["low", "medium", "high", "xhigh", "max"],
                      "models": ["claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1", "claude-haiku-4-5"]}}


@app.get("/api/llm/options")
def llm_options() -> dict[str, Any]:
    """What the model picker offers: providers (with whether each works on this machine), models, efforts."""
    import os
    from swarmscope.config import EFFORTS, MODELS
    from swarmscope.llm.router import find_claude_cli
    cli = bool(find_claude_cli())
    return {"providers": [
        {"id": "none", "label": "No model", "detail": "Fixed rules only. Free; nothing leaves this machine.", "available": True},
        {"id": "claude_code", "label": "Claude, through your Claude Code login",
         "detail": "Uses the Claude Code CLI on this machine; usage counts against that login.", "available": cli,
         "why_not": "" if cli else "Claude Code CLI not found on this machine."},
        {"id": "anthropic_api", "label": "Anthropic API key", "detail": "Bills the API key in ANTHROPIC_API_KEY.",
         "available": False, "why_not": "Not wired for the analyst team yet; the team runs through Claude Code."
         if os.environ.get("ANTHROPIC_API_KEY") else "No ANTHROPIC_API_KEY set."},
    ], "models": MODELS, "efforts": EFFORTS,
        "defaults": {"primary": {"model": "claude-sonnet-5-5", "effort": "medium"},
                     "subagents": {"model": "claude-sonnet-5-5", "effort": "low"}}}


def S_default_topology() -> str:
    from swarmscope.config import load_org
    return (load_org("default").get("agents") or {}).get("topology", "lead")


@app.post("/api/agents/topology")
def set_topology(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """{"select": id} switches; {"topology": {...}} validates and applies an edited topology;
    add {"save_as": id} to write it to agents/topologies/<id>.yaml."""
    from swarmscope.agents.spec import TopologyError, from_dict, save_topology
    o = eng().agent_org
    try:
        if body.get("select"):
            t = o.set_topology(body["select"])
        else:
            t = from_dict(body["topology"], body.get("save_as") or body["topology"].get("id") or "custom")
            if body.get("save_as"):
                save_topology(t, body["save_as"])
            o.set_topology(t)
    except (TopologyError, FileNotFoundError) as exc:
        raise HTTPException(422, str(exc))
    eng().org.setdefault("agents", {})["topology"] = t.id
    eng().broadcast()
    return {"ok": True, "topology": t.to_dict()}


# ------------------------------------------------------------------ conversation: copilot + Claude Code channel
def _hub():
    if S.hub is None:
        from swarmscope.assistant.chat import ChatHub
        S.hub = ChatHub(lambda: S.engine)
        S.hub.start()
    return S.hub


def _check_token(token: str | None) -> None:
    if not token or token != _hub().token:
        raise HTTPException(403, "bad channel token")


@app.get("/api/chat")
def chat_state() -> dict[str, Any]:
    from swarmscope.assistant.chat import TOKEN_FILE
    st = _hub().state()
    st["channel"]["command"] = "claude --dangerously-load-development-channels server:swarmscope"
    st["channel"]["mcp_json"] = str(ROOT / ".mcp.json")
    return st


@app.post("/api/chat")
async def chat_send(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    if body.get("target") in ("copilot", "channel"):
        _hub().target = body["target"]
    m = await _hub().viewer_says(str(body.get("text", "")), body.get("target"))
    return m.model_dump(mode="json")


@app.post("/api/chat/settings")
def chat_settings(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    h = _hub()
    if body.get("target") in ("copilot", "channel"):
        h.target = body["target"]
    if "watch" in body:
        h.watch.update({k: v for k, v in body["watch"].items() if k in h.watch})
    for k in ("narrate", "commentary"):                   # how often the live column speaks
        if isinstance(body.get(k), dict):
            cur = getattr(h, k)
            cur.update({x: v for x, v in body[k].items() if x in cur})
    if body.get("reset"):
        h.copilot.reset_soon()
        h.messages = [m for m in h.messages if m.role == "approval" and m.status == "pending"]
    return h.state()


@app.post("/api/chat/approval")
def chat_approval(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return {"ok": _hub().resolve(body["id"], bool(body.get("approve")))}


@app.post("/api/chat/channel")
def chat_from_channel(body: dict[str, Any] = Body(...), x_swarmscope_token: str | None = Header(None)) -> dict[str, Any]:
    _check_token(x_swarmscope_token)
    _hub().from_channel(body)
    return {"ok": True}


# ------------------------------------------------------------------ dashboard (agent-customizable views)
def _dash_state(e: Engine) -> dict[str, Any]:
    from swarmscope.dashboard.designer import supported
    from swarmscope.dashboard.spec import BUILTINS, GLANCE, MACHINERY, PRIMITIVES
    d = e.dashboard
    return {"spec": d.spec.model_dump(), "history": [{"version": h["version"], "by": h["by"], "rationale": h["rationale"]}
                                                     for h in d.history[-12:]],
            "builtins": {k: v for k, v in BUILTINS.items() if supported(e, k)}, "primitives": PRIMITIVES,
            "designing": bool(getattr(e, "_designing", False)), "lens": d.lens, "lenses": d.lens_names(),
            "glance": GLANCE, "machinery": MACHINERY}


@app.get("/api/dashboard")
def dashboard_get() -> dict[str, Any]:
    return _dash_state(eng())


@app.get("/api/compose/info")
def compose_info() -> dict[str, Any]:
    import sys
    return {"root": str(ROOT), "hook_script": str(ROOT / "scripts" / "swarmscope_hook.py"), "python": sys.executable,
            "url": "http://127.0.0.1:8765"}


@app.get("/api/dashboard/profile")
def dashboard_profile() -> dict[str, Any]:
    from swarmscope.dashboard.profile import stream_profile
    return stream_profile(eng())


@app.post("/api/dashboard/ops")
def dashboard_ops(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from swarmscope.dashboard.spec import SpecError
    e = eng()
    try:
        res = e.dashboard.apply_ops(e, body.get("ops") or [], by=body.get("by", "human"), rationale=body.get("rationale", ""))
    except SpecError as exc:
        raise HTTPException(400, str(exc))
    e._notify("dashboard", res["spec"])
    return _dash_state(e)


@app.post("/api/dashboard/restore")
def dashboard_restore() -> dict[str, Any]:
    """Bring back the source's built-in views (pages and room layout) next to whatever was composed."""
    return dashboard_ops({"ops": [{"op": "restore_builtin"}], "rationale": "restored the built-in views"})


@app.post("/api/stream/demo")
async def stream_demo() -> dict[str, Any]:
    """Play the sample swarm into a linked stream that has no events of its own yet."""
    e = eng()
    if e.stream is None:
        raise HTTPException(409, "the active session is not a linked stream")
    e.stream.start_demo(400, 10, 240)
    return {"ok": True, "feed": e.stream.feed_info}


@app.post("/ingest/events")
async def ingest_events(body: Any = Body(...)) -> dict[str, Any]:
    """Link any swarm stream: a JSON list of events, or {"events": [...]}. See sources/generic_stream.py."""
    e = eng()
    if e.stream is None:
        raise HTTPException(409, "the active session is not a linked stream; start one with source generic_stream")
    items = body.get("events", []) if isinstance(body, dict) else body
    return {"accepted": e.stream.ingest(items if isinstance(items, list) else []), "received": e.stream.received}


@app.post("/api/dashboard/undo")
def dashboard_undo() -> dict[str, Any]:
    from swarmscope.dashboard.spec import SpecError
    e = eng()
    try:
        res = e.dashboard.undo()
    except SpecError as exc:
        raise HTTPException(400, str(exc))
    e._notify("dashboard", res["spec"])
    return _dash_state(e)


@app.post("/api/dashboard/auto")
def dashboard_auto() -> dict[str, Any]:
    from swarmscope.dashboard.designer import auto_design
    e = eng()
    spec, why = auto_design(e)
    res = e.dashboard.replace(spec, "auto", why)
    e._notify("dashboard", res["spec"])
    return _dash_state(e)


@app.post("/api/dashboard/preview")
def dashboard_preview(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """The full result of a candidate view, so the builder can draw a real chart before it is added."""
    from swarmscope.dashboard.designer import DashboardTools
    return DashboardTools(lambda: eng()).view_data(body.get("view") or {})


@app.post("/api/dashboard/lens")
def dashboard_lens(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Saved layouts per scenario: {action: save|switch|delete|rename, name, new_name}."""
    from swarmscope.dashboard.designer import DashboardTools
    e = eng()
    res = DashboardTools(lambda: e, actor="human").dashboard_lens(body.get("action", "list"), body.get("name", ""),
                                                                 body.get("new_name", ""))
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "lens action failed"))
    e.broadcast()
    return _dash_state(e)


@app.get("/api/incident/{iid}")
def incident(iid: str) -> dict[str, Any]:
    from swarmscope.dashboard.brief import incident_detail
    d = incident_detail(eng(), iid)
    if d is None:
        raise HTTPException(404, "no such finding (it may have been resolved)")
    return d


@app.post("/api/incident/{iid}/action")
def incident_action(iid: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """investigate | watch | ack | escalate {level, reason} | lower {level, reason} | dismiss | pin | unpin | snooze | unsnooze,
    for one finding or a grouped one."""
    from swarmscope.dashboard.brief import brief_digest
    e = eng()
    act = body.get("action")
    item = next((x for x in brief_digest(e)["items"] if x["id"] == iid or iid in x["members"]), None)
    ids = item["members"] if item and item["id"] == iid else [iid]
    incs = [i for i in e.exec_state.active_incidents if i.id in ids]
    if act in ("pin", "unpin", "snooze", "unsnooze"):
        e.dashboard.apply_ops(e, [{"op": "set_brief", act: iid}], by="human", rationale=f"{act} {iid}")
        e._notify("dashboard", e.dashboard.spec.model_dump())
    elif not incs:
        raise HTTPException(404, "no such finding")
    elif act == "dismiss":
        for i in incs:
            i.status = "resolved"
            e.dismissed.add(i.id)
        from swarmscope.core.models import BriefingEntry
        e.store.put(BriefingEntry(ts=e.now(), kind="HUMAN", level="INFO",
                                  text=f"Dismissed: {incs[0].title}" + (f" (+{len(incs) - 1} similar)" if len(incs) > 1 else "")))
    elif act == "ack":
        led = e.cases()
        for i in incs:
            led.acknowledge(i.id, "human")
        e.store.put(e.exec_state, "ExecutiveState")
        e.broadcast()
    elif act == "escalate":
        lvl = str(body.get("level") or "ALERT").upper()
        if lvl not in ("INVESTIGATE", "ALERT", "PAGE"):
            raise HTTPException(400, "level is INVESTIGATE, ALERT or PAGE")
        top = incs[0]
        return e.escalate(scope=top.scope, title=top.title, level=lvl, by="human", view="human",
                          reason=body.get("reason") or "escalated from the Brief", case_id=top.id)
    elif act == "lower":
        lvl = str(body.get("level") or "WATCH").upper()
        led = e.cases()
        for i in incs:
            led.lower(i.id, lvl, "human", body.get("reason") or "lowered from the Brief")
        e.store.put(e.exec_state, "ExecutiveState")
        e.broadcast()
    elif act == "watch":
        for i in incs[:10]:
            e.human_directive("focus", i.scope, {"weight": 1.5}, "watched from the Brief")
    elif act == "investigate":
        top = incs[0]
        e.human_question(body.get("text") or f"What explains: {top.title}?", top.scope, "general")
    else:
        raise HTTPException(400, "action is investigate, watch, ack, escalate, lower, dismiss, pin, unpin, snooze or unsnooze")
    e.broadcast()
    return {"ok": True}


@app.get("/api/dashboard/data/{page}/{panel}")
def dashboard_data(page: str, panel: str) -> dict[str, Any]:
    from swarmscope.dashboard.query import QueryError
    from swarmscope.dashboard.spec import panel_data
    e = eng()
    p = e.dashboard.find_panel(page, panel)
    if p is None:
        raise HTTPException(404, "no such panel")
    try:
        return panel_data(e, p)
    except QueryError as exc:
        return {"columns": [], "rows": [], "meta": {"error": str(exc)}}


@app.get("/api/orientation")
def get_orientation() -> dict[str, Any]:
    """What SwarmFrame set up for this source and how to study it (the same content it posts in the live column)."""
    from swarmscope.assistant.orientation import orientation
    return orientation(eng())


@app.post("/api/dashboard/design")
async def dashboard_design(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Ask Claude to customize the dashboard. Runs in the background; progress and the summary go to the chat."""
    from swarmscope.dashboard.designer import run_designer
    e = eng()
    if getattr(e, "_designing", False):
        raise HTTPException(409, "a design run is already in progress")
    instruction = str(body.get("instruction", ""))[:600]
    hub = S.hub
    from swarmscope.assistant.chat import ChatMessage
    from swarmscope.dashboard import composed

    def say(role: str, text: str, via: str, **meta: Any) -> None:
        if hub:
            hub.post(ChatMessage(role=role, via=via, text=text, meta=meta))

    def orient() -> None:
        if body.get("orient", True):
            from swarmscope.assistant.orientation import orientation, orientation_text
            o = orientation(e)
            say("assistant", orientation_text(o), "copilot", orientation=o, cites=[])

    # a source composed before keeps its views: reuse them unless asked to recompose or given a new focus
    before = composed.get(e.profile.source, "dashboard") if e.dashboard.path else None
    if before and not body.get("force") and not instruction:
        if getattr(e.pack, "source", {}).get("infer_capabilities"):
            from swarmscope.sources.generic_stream import infer_capabilities
            infer_capabilities(e)
        say("system", f"Using the dashboard saved for this source (composed {before['at'][:10]}).", "system")
        orient()
        return {"started": False, "reused": before}

    async def go():
        e._designing = True
        e._notify("dashboard_designing", {"on": True})
        say("system", "Dashboard designer started" + (f": “{instruction}”" if instruction else "") + ".", "system")
        try:
            res = await run_designer(e, instruction)
            cost = f" (about ${res['cost_usd']:.2f})" if res.get("cost_usd") else ""
            say("assistant", f"Dashboard redesigned, version {res['version']}{cost}. {res['summary']}", "copilot",
                designer=True, backend=res["backend"])
            if e.dashboard.path:
                composed.mark(e.profile.source, "dashboard", mode=e.router.mode, version=res["version"],
                              instruction=instruction)
            orient()
        except Exception as exc:
            e.router.errors.append(f"designer: {type(exc).__name__}: {exc}")
            say("system", f"Dashboard designer failed: {type(exc).__name__}: {str(exc)[:200]}", "system")
        finally:
            e._designing = False
            e._notify("dashboard_designing", {"on": False})
            e._notify("dashboard", e.dashboard.spec.model_dump())

    asyncio.create_task(go())
    return {"started": True, "backend": "stub" if e.router.mode == "stub" else "claude_code"}


# ------------------------------------------------------------------ the World (docs/WORLD_PLAN.md)
@app.get("/api/world/state")
def world_state(ids: int = 1, labels: int = 0) -> dict[str, Any]:
    """Compact per-window state for the renderer: typed arrays as base64, landmarks, relations, cohorts.
    labels=1 adds every unit's label (the client asks once per change of the unit list)."""
    return eng().world.state(include_ids=bool(ids), labels=bool(labels))


@app.get("/api/world/spec")
def world_spec() -> dict[str, Any]:
    e = eng()
    e.world.ensure_spec()
    return {"spec": e.world.spec_public(), "history": [{"version": h["version"], "by": h["by"], "rationale": h["rationale"]}
                                                      for h in e.world.store.history[-12:]],
            "designing": bool(getattr(e, "_world_designing", False))}


@app.get("/api/world/catalog")
def world_catalog() -> dict[str, Any]:
    from swarmscope.world.spec import catalog
    return catalog()


@app.get("/api/world/unit/{uid:path}")
def world_unit(uid: str) -> dict[str, Any]:
    d = eng().world.unit_detail(uid)
    if d is None:
        raise HTTPException(404, "not on the map")
    return d


@app.get("/api/world/features")
def world_features(scope: str) -> dict[str, Any]:
    return eng().world.features_for(scope)


@app.get("/api/world/preview")
def world_preview() -> dict[str, Any]:
    return eng().world.preview()


@app.post("/api/world/ops")
def world_ops(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from swarmscope.world.spec import WorldError
    e = eng()
    try:
        res = e.world.store.apply_ops(e, body.get("ops") or [], by=body.get("by", "human"), rationale=body.get("rationale", ""))
    except WorldError as exc:
        raise HTTPException(400, str(exc))
    e._notify("world_spec", {"version": res["version"]})
    return {**world_spec(), "warnings": res.get("warnings", [])}


@app.post("/api/world/undo")
def world_undo() -> dict[str, Any]:
    from swarmscope.world.spec import WorldError
    e = eng()
    try:
        res = e.world.store.undo()
    except WorldError as exc:
        raise HTTPException(400, str(exc))
    e._notify("world_spec", {"version": res["version"]})
    return world_spec()


@app.post("/api/world/select")
def world_select(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """A lasso selection in the World, summarised (structure only) so the copilot can be asked about it."""
    return eng().world.selection_scope([str(u) for u in (body.get("units") or [])])


@app.post("/api/world/design")
async def world_design(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Compose the World for this stream: the free composer with models off, a Claude session with them on."""
    from swarmscope.world.designer import run_world_designer
    e = eng()
    if getattr(e, "_world_designing", False):
        raise HTTPException(409, "a world design run is already in progress")
    instruction = str(body.get("instruction", ""))[:600]
    hub = S.hub
    from swarmscope.assistant.chat import ChatMessage
    from swarmscope.dashboard import composed

    def say(role: str, text: str, via: str, **meta: Any) -> None:
        if hub:
            hub.post(ChatMessage(role=role, via=via, text=text, meta=meta))

    before = composed.get(e.profile.source, "world") if getattr(e.world.store, "path", None) else None
    if before and not body.get("force") and not instruction:
        e.world.ensure_spec()
        return {"started": False, "reused": before}

    async def go():
        e._world_designing = True
        e._notify("world_designing", {"on": True})
        try:
            e.world.ensure_spec()
            res = await run_world_designer(e, instruction)
            if getattr(e.world.store, "path", None):
                composed.mark(e.profile.source, "world", mode=e.router.mode, version=res.get("version"),
                              instruction=instruction)
            if res.get("backend") != "stub" or instruction:
                cost = f" (about ${res['cost_usd']:.2f})" if res.get("cost_usd") else ""
                made = [m for m in e.world.spec.models if m.by not in ("human",)]
                made_txt = (" Models made for this stream: " + "; ".join(f"{m.id} ({m.meaning})" for m in made) + "."
                            if made else "")
                say("assistant", f"World designed, version {res['version']}{cost}. {res['summary']}{made_txt}", "copilot",
                    designer=True, backend=res["backend"], trace=res.get("trace", []))
        except Exception as exc:
            e.router.errors.append(f"world designer: {type(exc).__name__}: {exc}")
            say("system", f"World designer failed: {type(exc).__name__}: {str(exc)[:200]}", "system")
        finally:
            e._world_designing = False
            e._notify("world_designing", {"on": False})
            e._notify("world_spec", {"version": e.world.spec.version})

    asyncio.create_task(go())
    return {"started": True, "backend": "stub" if e.router.mode == "stub" else "claude_code"}


@app.get("/api/ops")
def ops_specs() -> list[dict[str, Any]]:
    return _hub().copilot.ops.specs()


@app.post("/api/ops/{name}")
async def ops_call(name: str, body: dict[str, Any] = Body(default={}),
                   x_swarmscope_token: str | None = Header(None)) -> Any:
    _check_token(x_swarmscope_token)
    from swarmscope.assistant.ops import OpsTools
    h = _hub()
    ops = OpsTools(lambda: S.engine, lambda s, d: h.approve(s, d, "channel"), "your Claude Code session")
    try:
        return await ops.call(name, body)
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@app.websocket("/ws/channel")
async def ws_channel(ws: WebSocket, token: str = "") -> None:
    if token != _hub().token:
        await ws.close(code=4403)
        return
    await ws.accept()
    h = _hub()
    q: asyncio.Queue = asyncio.Queue()
    h.channel_connected(q)

    async def pump():
        while True:
            await ws.send_text(json.dumps(await q.get(), default=_default))
    sender = asyncio.create_task(pump())
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            if msg.get("type") != "hello":
                h.from_channel(msg)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        sender.cancel()
        h.channel_disconnected(q)


# ------------------------------------------------------------------ live control
@app.post("/ingest/claude-code")
def ingest_hook(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    e = eng()
    if not e.control:
        raise HTTPException(409, "the active session is not a live source")
    return {"events": e.control.ingest(payload)}


@app.post("/api/control/register")
def control_register(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    e = eng()
    if not e.control:
        raise HTTPException(409, "not a live session")
    e.control.register(body["agent"], body.get("label", body["agent"]), body.get("team"), body.get("task", ""))
    return {"ok": True}


@app.post("/api/control/decide")
async def control_decide(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    e = eng()
    if not e.control:
        return {"behavior": "allow"}
    return await e.control.decide(body["agent"], body["tool"], body.get("input") or {})


@app.post("/api/control/action")
async def control_action(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    e = eng()
    if not e.control:
        raise HTTPException(409, "not a live session")
    a = await e.control.act(body["kind"], body.get("target", "swarm"), body.get("payload"))
    return a.model_dump(mode="json")


@app.post("/api/control/policy")
def control_policy(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    e = eng()
    if e.control:
        e.control.policy_enabled = bool(body.get("enabled", True))
    return {"enabled": bool(e.control and e.control.policy_enabled)}


@app.websocket("/ws/runner")
async def ws_runner(ws: WebSocket) -> None:
    await ws.accept()
    e = eng()
    q: asyncio.Queue = asyncio.Queue()
    if e.control:
        e.control.runner_queues.append(q)
    try:
        while True:
            cmd = await q.get()
            await ws.send_text(json.dumps(cmd, default=_default))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if e.control and q in e.control.runner_queues:
            e.control.runner_queues.remove(q)


# ------------------------------------------------------------------ evaluation
@app.post("/api/eval")
async def run_eval(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    from swarmscope.evals.harness import compare
    orgs_ = body.get("orgs") or ["default", "baseline_deterministic", "baseline_uniform_local", "baseline_single_summarizer"]
    return await compare(orgs_, source=body.get("source", "ai_village"), path=body.get("path", "synthetic"))


# ------------------------------------------------------------------ live feed
@app.websocket("/ws")
async def ws_feed(ws: WebSocket) -> None:
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue()
    S.clients.append(q)               # the same list object is every engine's subscriber list
    q.put_nowait({"type": "snapshot", "data": S.engine.snapshot() if S.engine else {"empty": True}})
    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=15)
                await ws.send_text(json.dumps(msg, default=_default))
            except asyncio.TimeoutError:
                await ws.send_text('{"type":"ping"}')
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if q in S.clients:
            S.clients.remove(q)


DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        if path and f.is_file():
            return FileResponse(f)
        # the page itself is never cached, so a rebuilt dashboard shows up on the next load
        return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
