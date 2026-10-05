"""The World (docs/WORLD_PLAN.md): availability grading, the layout, the null model, the spec grammar, presets,
composition for poor streams, and the feedback into analysts."""
from __future__ import annotations

import asyncio

import numpy as np
import pytest

from swarmscope.engine import Engine
from swarmscope.world.spec import WorldError, validate

FAST = {"investigations.node_delay_s": 0, "agents.stub_delay_s": 0, "llm.mode": "stub"}


def run(coro):
    return asyncio.run(coro)


def windows(e: Engine, n: int) -> None:
    async def go():
        for _ in range(n):
            w = e.clock.next_window()
            if w is None:
                break
            await e.process(w)
    run(go())


@pytest.fixture(scope="module")
def swarm():
    e = Engine("swarm_scale", "default", slice_override={"agents": 400, "hours": 12}, overrides=FAST)
    run(e.run_to_end())
    return e


def test_availability_grades_each_stream_honestly():
    t = Engine("transluce", "default", path="synthetic", overrides=FAST)
    windows(t, 4)
    tab = t.world.table()
    assert tab["identity"]["status"] == "absent" and tab["control"]["status"] == "absent"
    assert tab["grade"]["status"] == "observed" and tab["activity"]["status"] == "derived"
    v = Engine("ai_village", "default", path="synthetic", overrides=FAST)
    windows(v, 4)
    vt = v.world.table()
    assert vt["identity"]["status"] == "observed" and vt["messages"]["status"] == "observed"
    assert vt["task"]["status"] in ("observed", "absent")            # stated goals, or nothing with models off
    assert vt["control"]["status"] == "absent"


def test_presets_load_and_drop_what_a_run_cannot_support(swarm):
    s = swarm.world.spec
    assert s.by == "pack" and s.shape == "swarm" and s.unit["model"] == "sprite"
    assert {"position", "height", "colour", "ring"} <= {b.channel for b in s.bindings}
    assert all(b.status in ("observed", "derived", "inferred") for b in s.bindings)
    t = Engine("transluce", "default", path="synthetic", overrides=FAST)
    windows(t, 3)
    t.world.ensure_spec()
    assert t.world.spec.shape == "targets" and t.world.spec.unit["model"] == "plinth"
    assert t.world.spec.landmarks_from == "family"


def test_layout_is_deterministic_and_separates_beyond_chance(swarm):
    again = Engine("swarm_scale", "default", slice_override={"agents": 400, "hours": 12}, overrides=FAST)
    run(again.run_to_end())
    a, b = swarm.world.layout, again.world.layout
    assert a.ids == b.ids and np.allclose(a.pos, b.pos)           # same stream, same map
    pv = swarm.world.preview()
    assert pv["separates_beyond_chance"] and pv["separation"] > pv["separation_null"]
    assert pv["recommended_tier"] == "pawns"


def test_state_is_compact_and_complete(swarm):
    st = swarm.world.state()
    assert st["n"] == len(st["ids"]) and st["tier"] in ("characters", "pawns", "dots")
    x = np.frombuffer(__import__("base64").b64decode(st["units"]["x"]), dtype=np.float32)
    assert len(x) == st["n"] and np.isfinite(x).all()
    assert st["landmarks"] and all("crowding" in lm and "arch" in lm for lm in st["landmarks"])
    assert st["cohorts"] and all(c["task"] for c in st["cohorts"][:3])  # analysts' labels (derived with models off)
    assert all(c["task_status"] in (None, "derived", "inferred") for c in st["cohorts"])


def test_grammar_rejects_misuse(swarm):
    t = swarm.world.table()
    from swarmscope.world.spec import Binding
    base = swarm.world.spec.model_copy(deep=True)
    for bad, why in [
        (Binding(channel="colour", quantity="severity", legend="x"), "reserved"),
        (Binding(channel="ring", quantity="activity", legend="x"), "reserved"),
        (Binding(channel="material", quantity="grade", legend="x"), "does not have"),     # no grades in this stream
        (Binding(channel="height", quantity="activity_z", legend=""), "legend"),
    ]:
        s = base.model_copy(deep=True)
        s.bindings = [b for b in s.bindings if b.channel != bad.channel] + [bad]
        with pytest.raises(WorldError, match=why):
            validate(s, t)
    s = base.model_copy(deep=True)
    s.control = {"enabled": True}
    with pytest.raises(WorldError, match="control"):
        validate(s, t)
    s = base.model_copy(deep=True)
    s.unit = {"model": "sprite", "of": "actor"}
    with pytest.raises(WorldError, match="identities"):
        validate(s, {**t, "identity": {"status": "absent", "why": ""}})


def test_ops_are_versioned_and_undoable(swarm):
    st = swarm.world.store
    v0 = st.spec.version
    st.apply_ops(swarm, [{"op": "set_render", "tier": "dots"},
                         {"op": "remove_scene", "id": "operator"},
                         {"op": "add_scene", "scene": {"id": "mine", "title": "Mine", "question": "What is here?"}},
                         {"op": "add_annotation", "at": "agent:x", "text": "look here"}])
    assert st.spec.render["tier"] == "dots" and st.spec.version == v0 + 1 and st.spec.annotations
    with pytest.raises(WorldError):
        st.apply_ops(swarm, [{"op": "add_scene", "scene": {"id": "bad", "title": "No question"}}])
    with pytest.raises(WorldError, match="four scenes"):
        st.apply_ops(swarm, [{"op": "add_scene", "scene": {"id": "fifth", "title": "Too many", "question": "?"}}])
    st.undo()
    assert st.spec.render["tier"] != "dots"


def test_a_stripped_stream_still_gets_a_world():
    """actor + action only: positions from the behaviour signature, no landmarks, the legend lists the unknowns."""
    e = Engine("generic_stream", "default", overrides=FAST)
    e.stream.ingest([{"actor": f"a{i % 12}", "action": ["tool.run", "tool.read", "plan"][i % 3]} for i in range(240)])
    e.stream.flush()
    from swarmscope.sources.generic_stream import infer_capabilities
    infer_capabilities(e)
    windows(e, 3)
    from swarmscope.world.designer import compose_world
    e.world._table = None
    spec, why = compose_world(e)
    assert spec.shape == "stripped" and not spec.landmarks[:-1]
    assert spec.metric["forces"]["landmark"] == 0.0
    assert any("not in this stream" in u for u in e.world.spec_public()["unavailable"])


def test_spatial_features_feed_the_analysts(swarm):
    from swarmscope.llm.evidence_tools import EvidenceTools
    w = swarm.world
    unit = w.layout.ids[0]
    f = w.features_for(f"agent:{unit}")
    assert {"drift", "isolation", "nearest", "null_quantile"} <= set(f)
    tools = swarm.tools("division_analyst")
    assert isinstance(tools, EvidenceTools) and "drift" in tools.world_features(f"agent:{unit}")
    cid = swarm.scale.unit_cohort.get(unit)
    assert "spread" in w.features_for(f"cohort:{cid}")
    sel = w.selection_scope(w.layout.ids[:20])
    assert sel["units"] == 20 and sel["cohorts"]


RACK = {"id": "server-rack", "kind": "landmark", "meaning": "A host the agents call, drawn as a rack of servers.",
        "parts": [{"shape": "box", "size": [0.9, 1.8, 0.7], "at": [0, 0.9, 0], "colour": "metal", "material": "metal"},
                  {"shape": "box", "size": [0.8, 0.08, 0.04], "at": [0, 1.0, 0.36], "colour": "tint", "material": "glow"},
                  {"shape": "dome", "size": [0.25], "at": [-0.2, 1.8, 0], "colour": "stone", "anim": "spin"}]}
DRONE = {"id": "drone", "kind": "unit", "meaning": "An agent, drawn as a small drone.",
         "parts": [{"shape": "capsule", "size": [0.18, 0.3], "at": [0, 0.5, 0], "colour": "tint", "material": "gloss"},
                   {"shape": "cylinder", "size": [0.3, 0.3, 0.02], "at": [0, 0.85, 0], "colour": "ink", "anim": "spin"},
                   {"shape": "cylinder", "size": [0.03, 0.03, 0.3], "at": [0, 0.15, 0], "colour": "metal"}]}
TREE = {"id": "pine", "kind": "prop", "meaning": "Decoration: a pine tree at the edge of the world.",
        "parts": [{"shape": "cylinder", "size": [0.08, 0.1, 0.5], "at": [0, 0.25, 0], "colour": "wood"},
                  {"shape": "cone", "size": [0.5, 1.2], "at": [0, 1.1, 0], "colour": "leaf"}]}


def test_model_check_reports_and_draws():
    from swarmscope.world.models import check_model
    r = check_model(RACK, strict=False)
    assert r["ok"] and r["triangles"] < 4000 and len(r["front"]) >= 4 and "a" in "".join(r["front"])
    bad = {**DRONE, "parts": [{**DRONE["parts"][0], "colour": "metal", "material": "glass"},
                              {**DRONE["parts"][1], "anim": "bob"}]}
    errs = " ".join(check_model(bad, strict=False)["errors"])
    assert "glass" in errs and "bob" in errs and "tint" in errs            # unit rules: no glass, no bob, needs tint
    assert not check_model({**TREE, "parts": [{**TREE["parts"][0], "colour": "tint"}]}, strict=False)["ok"]
    tall = {**RACK, "parts": [{"shape": "box", "size": [0.5, 9, 0.5], "at": [0, 4.5, 0]}]}
    assert any("too tall" in e for e in check_model(tall, strict=False)["errors"])
    low = {**RACK, "parts": [{"shape": "box", "size": [0.5, 1, 0.5], "at": [0, 0, 0]}]}
    assert any("below the ground" in e for e in check_model(low, strict=False)["errors"])


def test_models_are_used_through_ops_and_reach_the_renderer(swarm):
    st = swarm.world.store
    v0 = st.spec.version
    st.apply_ops(swarm, [{"op": "add_model", "model": RACK}, {"op": "add_model", "model": DRONE},
                         {"op": "add_model", "model": TREE},
                         {"op": "add_landmark", "at": 0, "landmark": {"match": {"family": "web"}, "archetype": "tower",
                                                                      "label": "host", "model": "server-rack"}},
                         {"op": "set_render", "cast": ["newt", "drone"]},
                         {"op": "add_scenery", "scenery": {"model": "pine", "at": "rim", "count": 12, "meaning": "decoration"}}])
    assert st.spec.version == v0 + 1 and len(st.spec.models) == 3
    lms = swarm.world.state()["landmarks"]
    assert any(lm["model"] == "server-rack" for lm in lms) and all("fam" in lm for lm in lms)
    with pytest.raises(WorldError, match="still used"):
        st.apply_ops(swarm, [{"op": "remove_model", "id": "server-rack"}])
    with pytest.raises(WorldError, match="neither a premade"):
        st.apply_ops(swarm, [{"op": "set_render", "cast": ["pine"]}])
    with pytest.raises(WorldError, match="scenery instances"):
        st.apply_ops(swarm, [{"op": "add_scenery", "scenery": {"model": "pine", "at": "rim", "count": 24, "meaning": "decoration"}}] * 6)
    from swarmscope.world.designer import WorldTools
    chk = WorldTools(lambda: swarm).world_model_check({**RACK, "id": "Bad Id"})
    assert not chk["ok"] and "id" in chk["errors"][0]
    st.undo()
    assert not st.spec.models


# ---------------------------------------------------------------- environment and activity rules (world/scene.py)
def test_scene_grammar_accepts_library_and_composed_behaviours_and_rejects_the_rest(swarm):
    t = swarm.world.table()
    base = swarm.world.spec.model_copy(deep=True)
    from swarmscope.world.scene import Behaviour, Prop, Zone
    ok = base.model_copy(deep=True)
    ok.behaviours = [Behaviour(id="edit", when="acted_on_landmark", filter={"family": "files"}, do="go_to",
                               meaning="Walks to the file it edits."),
                     Behaviour(id="visit", when="talked", do="sequence", meaning="Talks at a board, then goes to work.",
                               steps=[{"do": "gather", "dur": 0.25}, {"do": "talk", "dur": 0.2}, {"do": "go_to", "dur": 0.2},
                                      {"do": "work", "dur": 0.15}, {"do": "return", "dur": 0.2}])]
    ok.environment.zones = [Zone(name="boards", around={"family": "chat"}, style="paving", label="boards")]
    ok.environment.props = [Prop(asset="bench", at="landmarks", near={"family": "chat"}, count=2, meaning="decoration")]
    validate(ok, t)
    for mutate, why in [
        (lambda s: s.behaviours.append(Behaviour(when="talked", do="teleport", meaning="Goes somewhere else.")), "library"),
        (lambda s: s.behaviours.append(Behaviour(when="sneezed", do="pulse", meaning="Pulses when it sneezes.")), "conditions"),
        (lambda s: s.behaviours.append(Behaviour(when="talked", do="sequence", meaning="Walks away for good.",
                                                 steps=[{"do": "go_to", "dur": 0.5}, {"do": "work", "dur": 0.3}])), "return"),
        (lambda s: s.behaviours.append(Behaviour(when="talked", do="sequence", meaning="Runs a script.",
                                                 steps=[{"do": "eval", "dur": 0.5}])), "steps"),
        (lambda s: s.behaviours.append(Behaviour(when="talked", do="gather", meaning="")), "meaning"),
        (lambda s: s.behaviours.append(Behaviour(when="idle", do="wander", params={"radius": 9}, meaning="Wanders far.")), "radius"),
        (lambda s: s.environment.props.append(Prop(asset="spaceship", at="rim", count=3)), "library asset"),
        (lambda s: setattr(s.environment, "ground", "lava"), "ground"),
        (lambda s: s.environment.zones.append(Zone(name="x", around={"colour": "red"}, style="paving")), "around"),
    ]:
        s = ok.model_copy(deep=True)
        mutate(s)
        with pytest.raises(WorldError, match=why):
            validate(s, t)
    s = ok.model_copy(deep=True)                       # a condition the stream cannot compute is refused
    with pytest.raises(WorldError, match="does not have"):
        validate(s, {**t, "messages": {"status": "absent", "why": ""}})
    s = ok.model_copy(deep=True)                       # places cannot walk
    s.unit = {"model": "plinth", "of": "object"}
    with pytest.raises(WorldError, match="cannot walk"):
        validate(s, {})


def test_every_library_asset_passes_the_model_check():
    from swarmscope.world.assets import ASSETS
    from swarmscope.world.models import check_model
    assert len(ASSETS) >= 19
    for need in ("tree", "bush", "rock", "bench", "lamp", "desk", "chair", "bookshelf", "notice_board", "server_rack",
                 "terminal", "signpost", "fence", "small_house", "office_block", "tower_block", "fountain",
                 "crate_stack", "path_tiles"):
        assert need in ASSETS
    for k, m in ASSETS.items():
        r = check_model(m, strict=False)
        assert r["ok"], (k, r["errors"])
        assert not any(p.colour == "tint" for p in m.parts) and "encodes nothing" in m.meaning


@pytest.mark.parametrize("pack,kw", [("swarm_scale", {"slice_override": {"agents": 120, "hours": 6}}),
                                     ("ai_village", {"path": "synthetic"}), ("transluce", {"path": "synthetic"}),
                                     ("german_wiki", {"path": "synthetic", "slice_override": {"groups": 24}}),
                                     ("claude_code", {})])
def test_every_preset_has_a_scene_and_activity_rules(pack, kw):
    from swarmscope.world.spec import preset_world
    e = Engine(pack, "default", overrides=FAST, **kw)
    windows(e, 6)
    spec = preset_world(e)
    validate(spec, spec.availability)
    assert spec.environment.ground != "paper" and spec.environment.props and spec.behaviours
    assert all(b.meaning for b in spec.behaviours)
    if spec.unit["model"] == "plinth":
        assert {b.do for b in spec.behaviours} <= {"pulse", "glow", "carry", "fade", "stay_home"}
    st = e.world.state()
    if not st.get("empty"):
        assert {"ground", "zones", "props"} <= set(st["env"]) and "beh" in st["acts"]
        pub = e.world.spec_public()
        assert all(b["plan"] is not None for b in pub["behaviours"]) and pub["asset_defs"]


def test_acts_are_sent_and_bounded_at_two_thousand_units():
    import base64
    e = Engine("swarm_scale", "default", slice_override={"agents": 2000, "hours": 3}, overrides=FAST)
    windows(e, 6)
    st = e.world.state()
    n = st["n"]
    beh = np.frombuffer(base64.b64decode(st["acts"]["beh"]), dtype=np.uint8)
    lm = np.frombuffer(base64.b64decode(st["acts"]["lm"]), dtype=np.int16)
    partner = np.frombuffer(base64.b64decode(st["acts"]["partner"]), dtype=np.int32)
    assert n > 1500 and len(beh) == len(lm) == len(partner) == n
    from swarmscope.world.engine import MAX_CHOREO
    assert 0 < st["acts"]["n"] <= MAX_CHOREO and (beh != 255).sum() == st["acts"]["n"]
    assert lm.max() < len(st["landmarks"]) and partner.max() < n
    assert sum(len(v) for v in st["env"]["props"].values()) // 3 <= 480
    size = sum(len(v) for v in st["acts"].values() if isinstance(v, str))
    assert size < 40 * n                                # a few bytes per unit, base64


def test_compose_world_picks_a_scene_and_behaviours(swarm):
    from swarmscope.world.designer import WorldTools, compose_world
    spec, _ = compose_world(swarm)
    whens = [b.when for b in spec.behaviours]
    assert "acted_on_landmark" in whens and whens[-1] == "idle" and spec.environment.props
    assert spec.environment.ground == "grid" and spec.environment.zones
    tools = WorldTools(lambda: swarm)
    assert "go_to" in tools.world_behaviour_catalog()["library"] and "bench" in tools.world_asset_catalog()["assets"]
    st = swarm.world.store
    v0 = st.spec.version
    st.apply_ops(swarm, [{"op": "set_environment", "ground": "grass"},
                         {"op": "add_zone", "zone": {"name": "boards", "around": {"family": "chat"}, "style": "paving"}},
                         {"op": "place_props", "props": [{"asset": "fountain", "at": "centre", "meaning": "decoration"}]},
                         {"op": "add_behaviour", "at": 0, "behaviour": {"id": "spike", "when": "surge", "do": "glow",
                                                                        "meaning": "Glows when its activity jumps."}}])
    assert st.spec.version == v0 + 1 and st.spec.behaviours[0].id == "spike"
    with pytest.raises(WorldError, match="no behaviour"):
        st.apply_ops(swarm, [{"op": "remove_behaviour", "id": "nope"}])
    st.undo()
