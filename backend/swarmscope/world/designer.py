"""Who designs the World for a stream.

compose_world      free and deterministic: the decision procedure of the world-designer skill (§18.2) as fixed rules.
                   Reads the availability table, picks the nearest shape, adapts its defaults, writes a reason for
                   every choice. Same input, same world.
run_world_designer one Claude Code session with the world tools and the world-designer skill; it reasons through the
                   same procedure, previews, and applies ops. Every op is validated and versioned.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Callable

from swarmscope.world.features import available, summary_lines
from swarmscope.world.scene import Behaviour, Environment, Prop, Zone, asset_catalog_full, behaviour_catalog
from swarmscope.world.spec import OPS, Binding, LandmarkRule, Scene, WorldError, WorldSpec, catalog

if TYPE_CHECKING:
    from swarmscope.engine import Engine


def pick_shape(t: dict[str, dict[str, str]], n_units: int) -> tuple[str, str]:
    """§18.2, first match wins."""
    st = lambda k: t.get(k, {}).get("status", "absent")  # noqa: E731
    if st("identity") == "absent" and st("resources") != "absent":
        return "targets", "no persistent identities, but places: units are places (plinths), methods are roads"
    if st("identity") == "absent":
        return "stripped", "neither identities nor places: only activity can be shown"
    if st("identity_partial") != "absent":
        return "wiki", "identities are partial (handles), so sprites are translucent and aliases are tethered"
    if st("control") == "observed":
        return "swarm_control", "a control plane is attached: the World offers the Control page's actions on click"
    if st("messages") != "absent" and n_units <= 60:
        return "village", "a small population that talks: rooms become plazas and every agent is a character"
    if st("resources") == "absent":
        return "stripped", "agents and actions only: position by behaviour signature, no landmarks"
    return "swarm", "a large population acting on shared places"


LANDMARKS = {
    "swarm": [("files", "slab", "file"), ("docs", "slab", "document"), ("data", "kiosk", "dataset"),
              ("web", "tower", "host"), ("search", "tower", "host"), ("chat", "plaza", "channel"),
              ("environment", "kiosk", "board")],
    "swarm_control": [("files", "slab", "file"), ("docs", "slab", "document"), ("web", "tower", "host"),
                      ("shell", "kiosk", "command target"), ("chat", "plaza", "channel")],
    "village": [("chat", "plaza", "room"), ("docs", "slab", "document"), ("sheets", "slab", "sheet"),
                ("web", "tower", "site"), ("research", "tower", "site"), ("computer", "kiosk", "app")],
    "wiki": [("docs", "slab", "page"), ("web", "tower", "cited site")],
    "stripped": [],
    "targets": [],
}


def compose_world(engine: "Engine", focus: str = "") -> tuple[WorldSpec, str]:
    t = engine.world.table() if getattr(engine, "world", None) else {}
    try:                                   # the population the stream will show, not just the first window's
        n = max(len(engine.scale.profiles), int(engine.store.scalar(
            "SELECT count(DISTINCT actor) FROM events WHERE actor IS NOT NULL") or 0))
    except Exception:
        n = len(engine.scale.profiles)
    shape, why_shape = pick_shape(t, n)
    has = lambda k: available(t, k)  # noqa: E731
    noun = engine.profile.entity_noun
    rnoun = getattr(engine.profile, "resource_noun", "resource") or "resource"
    reasons = {"shape": why_shape}
    spec = WorldSpec(source=engine.profile.source, shape=shape, availability=t)
    # unit
    if shape == "targets" or not has("identity"):
        spec.unit = {"model": "plinth", "of": "object", "alpha_by": "grade" if has("grade") else None}
        spec.landmarks_from = "family"
        spec.landmarks = [LandmarkRule(match={"kind": "other"}, archetype="road", label="method",
                                       reason="each method class is a road; targets stand along the roads that reach them")]
        spec.metric["sentence"] = f"Distance: {rnoun}s reached by the same methods in the same weeks stand together."
        spec.metric["interactions"] = []
        spec.territories = {"by": "none"}
        reasons["unit"] = f"no {noun} identities, so each {rnoun} is a plinth"
    else:
        spec.unit = {"model": "sprite", "of": "actor", "alpha_by": "identity_confidence" if shape == "wiki" else None}
        inter = [x for x, f in (("co_touch", "co_touch"), ("reply", "replies"), ("lineage", "lineage"),
                                ("shape", "lineage")) if has(f)]
        spec.metric["interactions"] = inter
        parts = []
        if has("resources"):
            parts.append(f"work on the same {rnoun}s")
        if "reply" in inter:
            parts.append("talk to each other")
        if "lineage" in inter:
            parts.append("reuse each other's content or post the same kind of message")
        parts.append("behave alike")
        spec.metric["sentence"] = f"Distance: {noun}s that {', '.join(parts[:-1]) + ' or ' + parts[-1] if len(parts) > 1 else parts[0]} stand together."
        spec.landmarks = [LandmarkRule(match={"family": f}, archetype=a, label=lab,
                                       reason=f"{f} places are {lab}s ({a})") for f, a, lab in LANDMARKS.get(shape, [])]
        spec.landmarks.append(LandmarkRule(match={"kind": "other"}, archetype="kiosk", label=rnoun,
                                           reason=f"any other {rnoun}, drawn small"))
        spec.territories = {"by": "group" if has("groups") else "none"}
        reasons["territories"] = "teams are territories, with a gate where new members arrive" if has("groups") \
            else "the stream has no groups, so there are no territories"
        if shape == "village":
            spec.metric["forces"] = {**spec.metric["forces"], "interact": 1.2, "landmark": 1.1, "similar": 0.3}
            reasons["forces"] = "a small population that talks: replies and rooms pull harder than behavioural similarity"
        if shape == "stripped":
            spec.metric["forces"] = {**spec.metric["forces"], "landmark": 0.0, "interact": 0.0, "similar": 0.9}
            reasons["forces"] = "no places or interactions: position comes from the behaviour signature alone"
    # render tier: dots for thousands, characters only for small populations
    spec.render = {"tier": "auto", "max_characters": 80, "character": "newt",
                   "character_by": "unit" if shape == "village" else "group" if has("groups") else "none"}
    reasons["render"] = (f"{n} units: " + ("each is a character" if n <= 80 else
                                           "instanced pawns, characters when zoomed in" if n <= 2000 else
                                           "dots and group blobs at a distance, pawns when zoomed in"))
    # bindings: the fixed set minus what is absent
    B = []
    B.append(Binding(channel="position", quantity="cohort", legend=spec.metric["sentence"]))
    B.append(Binding(channel="height", quantity="activity_z", transform="clamp(-1,3)",
                     legend=f"Height: how busy this {noun if shape != 'targets' else rnoun} is compared with its own usual."))
    B.append(Binding(channel="colour", quantity="family_dominant",
                     legend="Colour: the kind of work it mostly does." if shape != "targets" else "Cap colour: the method that reaches it most."))
    if shape != "targets":
        B.append(Binding(channel="state", quantity="state", legend="Pose: idle, active, talking, working, blocked, paused or stopped, as far as the stream says."))
    B.append(Binding(channel="ring", quantity="severity", legend="Ring: part of a finding (grey watch, amber look, red act)."))
    B.append(Binding(channel="trail", quantity="displacement", legend="Trail: where it has been; a long trail means its behaviour changed."))
    if has("messages") and shape != "targets":
        B.append(Binding(channel="bubble", quantity="messages", legend="Bubble: it sent a message (the words are never shown)."))
    if has("resources") and shape != "targets":
        B.append(Binding(channel="heat", quantity="landmark_distinct_z",
                         legend=f"Ground ring on a {rnoun}: more {noun}s than usual are on it (a crowd)."))
    if has("task"):
        B.append(Binding(channel="banner", quantity="task_label",
                         legend="Banner: what the group is probably doing (inferred by an analyst; translucent)."))
    if shape == "targets" and has("grade"):
        B.append(Binding(channel="material", quantity="grade", legend="Solid: the source rates the reports significant; glassy: only suggestive."))
    if shape == "wiki":
        B.append(Binding(channel="alpha", quantity="identity_confidence", legend="Translucent: a handle that may not be one agent."))
    B.append(Binding(channel="fog", quantity="coverage_age", legend="Fog: no analyst has read this group closely for a while."))
    spec.bindings = B
    spec.relations = [r for r, f in (("arc_touch", "co_touch"), ("arc_reply", "replies"), ("arc_lineage", "lineage"),
                                     ("beam", "operator")) if has(f)]
    spec.control = {"enabled": has("control")}
    reasons["control"] = "the control plane is attached" if has("control") else \
        "read-only: SwarmFrame observes these agents and cannot control them"
    # scenes
    sc = [Scene(id="overview", title="The whole swarm" if shape != "targets" else f"The map of {rnoun}s",
                camera="overview", question="Is anything out of shape?", opening=True)]
    if has("resources") and shape != "targets":
        sc.append(Scene(id="crowds", title=f"Crowded {rnoun}s", camera="top", target="crowding",
                        question=f"Which {rnoun}s draw more {noun}s than usual, and from which teams?", finding_kind="convergence"))
    if shape == "targets":
        sc.append(Scene(id="bursts", title="This week's bursts", camera="top", target="activity",
                        question=f"Which {rnoun}s spiked?", finding_kind="burst"))
    else:
        sc.append(Scene(id="drift", title="Who is drifting", camera="top", target="drift",
                        question=f"Which {noun}s are changing how they behave?"))
    if has("messages") and shape != "targets":
        sc.append(Scene(id="saydo", title="Talking, not moving", camera="region", target="still_talking",
                        question=f"Which {noun}s send messages without doing anything new?", finding_kind="say_do_mismatch"))
    if has("operator") and shape != "targets":
        sc.append(Scene(id="operator", title="Operator actions", camera="region", target="beams",
                        question="Where did operators step in, and what happened next?", finding_kind="environment"))
    spec.scenes = sc[:5]
    compose_scene(spec, has, shape, noun, rnoun, reasons)
    spec.reasons = reasons
    spec.open_questions = [] if t else ["the availability table was empty: compose again once events arrive"]
    from swarmscope.world.spec import validate
    validate(spec, t)
    unavailable = summary_lines(t)
    why = (f"{shape} world: {why_shape}. {spec.metric['sentence']} "
           + (f"Not shown: {len(unavailable)} feature{'s' if len(unavailable) != 1 else ''} this stream lacks." if unavailable else ""))
    return spec, why


GROUND_FOR = {"village": "grass", "wiki": "stone", "swarm_control": "plaza_tiles", "swarm": "grid", "targets": "sand",
              "stripped": "paper", "custom": "paper"}


def compose_scene(spec: WorldSpec, has: Callable[[str], bool], shape: str, noun: str, rnoun: str,
                  reasons: dict[str, str]) -> None:
    """The scene and the activity rules, from the stream's capabilities: a ground for the shape, a zone per kind of
    place, a few props that make those places legible, and one behaviour per thing the stream can say a unit did."""
    arch = {r.archetype: r.label for r in spec.landmarks if "family" in r.match}
    env = Environment(ground=GROUND_FOR.get(shape, "paper"))
    if shape == "targets":
        env.props = [Prop(asset="rock", at="rim", count=14, meaning="decoration: the edge of the map")]
    else:
        names = {"plaza": ("squares", "paving"), "slab": ("work", "wood"), "tower": ("outskirts", "dark"),
                 "kiosk": ("stalls", "sand")}
        for a, (name, style) in names.items():
            if a in arch:
                env.zones.append(Zone(name=name, around={"archetype": a}, style=style, label=f"{arch[a]}s"))
        tree = "tree" if shape in ("village", "wiki") else "pine"
        env.props.append(Prop(asset=tree, at="rim", count=20, meaning="decoration: the edge of the world"))
        if "plaza" in arch:
            env.props.append(Prop(asset="bench", at="landmarks", near={"archetype": "plaza"}, count=2,
                                  meaning=f"decoration: benches around each {arch['plaza']}"))
        if "slab" in arch:
            env.props.append(Prop(asset="desk", at="landmarks", near={"archetype": "slab"}, count=1,
                                  meaning=f"decoration: a desk beside each {arch['slab']}"))
        if any(r.match.get("family") == "data" for r in spec.landmarks):
            env.props.append(Prop(asset="server_rack", at="landmarks", near={"family": "data"}, count=1,
                                  meaning="decoration: racks beside datasets"))
        env.props.append(Prop(asset="lamp", at="scatter", count=10, meaning="decoration: lamps on open ground"))
    spec.environment = env
    B: list[Behaviour] = []
    if spec.unit.get("model") == "plinth":
        B.append(Behaviour(id="reported", when="active", do="pulse",
                           meaning=f"A ring pulses under a {rnoun} when new records name it this window."))
    else:
        if has("state_fine"):
            B.append(Behaviour(id="stopped", when="stopped", do="fade", meaning=f"A stopped {noun} fades."))
        if has("operator"):
            B.append(Behaviour(id="hit", when="environment_hit", do="scatter",
                               meaning=f"Steps away from where an operator or the environment acted on it, then returns."))
        if has("lineage"):
            B.append(Behaviour(id="reuse", when="reused_content", do="carry",
                               meaning="A token travels from the original poster to a unit that reuses its content."))
        if has("messages"):
            B.append(Behaviour(id="talk", when="talked", do="gather" if "plaza" in arch else "follow",
                               meaning=f"Walks to the nearest {arch['plaza']} when it sends a message, then back." if "plaza" in arch
                               else f"Walks toward the {noun} it talks with most, then back."))
        if has("resources"):
            B.append(Behaviour(id="work", when="acted_on_landmark", do="go_to",
                               meaning=f"Walks to the {rnoun} it acts on, works there, and walks back."))
        B.append(Behaviour(id="idle", when="idle", do="wander", meaning=f"An idle {noun} drifts around its spot."))
    spec.behaviours = B
    reasons["environment"] = (f"{env.ground} ground for a {shape} world; zones mark the kinds of place; props are "
                              f"decoration and encode nothing")
    reasons["behaviours"] = "one activity rule per thing this stream says a unit did; walks always return home"


# ------------------------------------------------------------------ tools shared by the designer agent and the copilot
class WorldTools:
    def __init__(self, engine: Callable[[], "Engine"], actor: str = "world-designer"):
        self._engine, self.actor = engine, actor

    @property
    def e(self) -> "Engine":
        return self._engine()

    def stream_profile(self) -> dict[str, Any]:
        from swarmscope.dashboard.profile import stream_profile
        return stream_profile(self.e)

    def world_features_available(self) -> dict[str, Any]:
        t = self.e.world.table()
        return {"table": t, "units": len(self.e.scale.profiles), "suggested_shape": pick_shape(t, len(self.e.scale.profiles)),
                "not_in_this_stream": summary_lines(t)}

    def world_catalog(self) -> dict[str, Any]:
        return catalog()

    def world_behaviour_catalog(self) -> dict[str, Any]:
        return behaviour_catalog()

    def world_asset_catalog(self) -> dict[str, Any]:
        return asset_catalog_full()

    def world_get(self) -> dict[str, Any]:
        return self.e.world.spec_public()

    def world_preview(self) -> dict[str, Any]:
        return self.e.world.preview()

    def world_features(self, scope: str) -> dict[str, Any]:
        return self.e.world.features_for(scope)

    def world_edit(self, ops: list[dict[str, Any]], rationale: str = "") -> dict[str, Any]:
        try:
            res = self.e.world.store.apply_ops(self.e, ops, by=self.actor, rationale=rationale)
        except WorldError as exc:
            return {"ok": False, "error": str(exc), "hint": "nothing was applied; fix the op and retry"}
        self.e._notify("world_spec", {"version": res["version"]})
        return {"ok": True, "version": res["version"], "applied": res["applied"], "warnings": res["warnings"]}

    def world_model_check(self, model: dict[str, Any]) -> dict[str, Any]:
        from swarmscope.world.models import check_model
        return check_model(model, strict=False)

    def world_undo(self) -> dict[str, Any]:
        try:
            res = self.e.world.store.undo()
        except WorldError as exc:
            return {"ok": False, "error": str(exc)}
        self.e._notify("world_spec", {"version": res["version"]})
        return {"ok": True, "version": res["version"]}

    SPECS: list[tuple[str, str, dict[str, Any]]] = [
        ("stream_profile", "Structure of the data stream: capabilities, fields, cardinalities, categorical values, rate. "
                           "No agent-written text.", {"type": "object", "properties": {}}),
        ("world_features_available", "For every World feature: observed, derived, inferred or absent in THIS stream, "
                                     "with why, plus the suggested shape. Read this first.", {"type": "object", "properties": {}}),
        ("world_catalog", "The fixed library: unit models, characters, states, attachments, landmark archetypes, relations, "
                          "channels (and which are reserved), quantities, transforms, render tiers, cameras, force ranges, ops.",
         {"type": "object", "properties": {}}),
        ("world_behaviour_catalog", "Activity rules: the `when` conditions computed per unit per window, the `do` "
                                    "library (go_to, gather, wander, scatter, follow, pulse, glow, carry, stay_home, fade), "
                                    "the steps for composing your own sequence, params and rules.",
         {"type": "object", "properties": {}}),
        ("world_asset_catalog", "The scene: ground styles, zone styles, prop placements and the generic prop library "
                                "(tree, bench, desk, bookshelf, server_rack, terminal, small_house, ...), with sizes.",
         {"type": "object", "properties": {}}),
        ("world_get", "The current WorldSpec, with what this stream cannot show.", {"type": "object", "properties": {}}),
        ("world_preview", "Statistics of the current layout against its null model: separation, units moving beyond chance, "
                          "crowding, recommended render tier.", {"type": "object", "properties": {}}),
        ("world_features", "The spatial reading of one scope (agent:<id>, cohort:<id>, resource:<id>) with null baselines.",
         {"type": "object", "properties": {"scope": {"type": "string"}}, "required": ["scope"]}),
        ("world_edit", "Apply WorldSpec ops atomically (validated, versioned, undoable): " + ", ".join(OPS) + ". "
                       "Models: {op: add_model, model: {id, kind: landmark|unit|prop, meaning, parts: [...]}}; use a "
                       "landmark model with update_landmark {index, changes: {model: id}}, a unit model with set_render "
                       "{character_by: fixed, character: id} or {cast: [ids]}, a prop with add_scenery "
                       "{scenery: {model, at: centre|rim|territories, count, meaning}}. Scene: set_environment {ground}, "
                       "add_zone {zone: {name, around: {family|archetype|label|group: x}, style, label}}, place_props "
                       "{props: [{asset, at, near, count, meaning}]}. Activity: add_behaviour {behaviour: {id, when, "
                       "filter, do, steps, params, meaning}}, update_behaviour {id, changes}, move_behaviour, remove_behaviour.",
         {"type": "object", "properties": {"ops": {"type": "array", "items": {"type": "object"}},
                                           "rationale": {"type": "string"}}, "required": ["ops"]}),
        ("world_model_check", "Check a model before adding it, without applying anything: errors, warnings, bounds, "
                              "triangle estimate and ASCII silhouettes from the front, side and top (each letter is a "
                              "part). The model_kit in world_catalog lists shapes, colours, materials and limits.",
         {"type": "object", "properties": {"model": {"type": "object"}}, "required": ["model"]}),
        ("world_undo", "Undo the last World change.", {"type": "object", "properties": {}}),
    ]

    def mcp_server(self):
        from claude_agent_sdk import create_sdk_mcp_server, tool

        def wrap(name):
            async def run(args: dict[str, Any]) -> dict[str, Any]:
                try:
                    res = getattr(self, name)(**{k: v for k, v in args.items() if v not in (None, "")})
                except Exception as exc:
                    return {"content": [{"type": "text", "text": f"error: {exc}"}], "is_error": True}
                return {"content": [{"type": "text", "text": json.dumps(res, default=str)[:14000]}]}
            return run
        tools = [tool(n, d, s)(wrap(n)) for n, d, s in self.SPECS]
        return create_sdk_mcp_server(name="world", version="1.0.0", tools=tools), [f"mcp__world__{n}" for n, _, _ in self.SPECS]


DESIGN_SCHEMA = {"type": "object", "properties": {
    "summary": {"type": "string"}, "shape": {"type": "string"},
    "critic": {"type": "array", "items": {"type": "object", "properties": {
        "check": {"type": "string"}, "pass": {"type": "boolean"}, "fix": {"type": "string"}}}},
    "open_questions": {"type": "array", "items": {"type": "string"}}}, "required": ["summary", "shape", "critic"]}


async def run_world_designer(engine: "Engine", instruction: str = "") -> dict[str, Any]:
    """Compose the World for this stream. Models off: the free composer. Models on: a Claude Code session."""
    if engine.router.mode == "stub":
        spec, why = compose_world(engine, instruction)
        cur = engine.world.store.spec
        if cur.by == "pack" and not instruction:
            return {"backend": "stub", "summary": "The source's preset world is in place.", "version": cur.version}
        spec.annotations = cur.annotations
        res = engine.world.store.replace(spec, "auto", why)
        engine._notify("world_spec", {"version": res["version"]})
        return {"backend": "stub", "summary": why, "version": res["version"], "shape": spec.shape}
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, ToolUseBlock, query

    from swarmscope.agents.skills import compose
    from swarmscope.llm.router import find_claude_cli
    tools = WorldTools(lambda: engine)
    server, names = tools.mcp_server()
    llm = engine.org.get("llm", {})
    role = (llm.get("roles") or {}).get("designer", {})
    model = llm.get("cheap", {}).get("model", "claude-sonnet-5-5") if llm.get("mode") == "cheap" else role.get("model", "claude-sonnet-5-5")
    effort = llm.get("cheap", {}).get("effort", "low") if llm.get("mode") == "cheap" else role.get("effort", "low")
    system = compose(["world-designer"], ["shapes", "primitives", "models", "environment", "behaviours"]) or \
        "You design the SwarmFrame World."
    cur = engine.world.store.spec
    prompt = ("Design the World for the stream SwarmFrame is watching. Follow the skill's procedure: survey (read "
              "world_features_available first), metric, vocabulary, scene and activity, encodings, scenes, preview, critic. "
              + (f"The source ships a preset ({cur.shape}); adapt it rather than starting over. " if cur.by == "pack" else "")
              + f"There are {len(engine.scale.profiles)} units: choose the render tier for that size (dots for thousands). "
              + (f"The viewer asked: {instruction}\n\n" if instruction else "\n")
              + "Design the scene the stream lives in (ground, zones that match the places, props that make the places "
              "legible) and the activity rules (what a unit does when it writes, talks, idles, gets stopped), from the "
              "libraries first (world_asset_catalog, world_behaviour_catalog). "
              + "If no premade character or archetype says what this stream's agents or places are, make a model "
              "(world_catalog.model_kit; world_model_check before world_edit add_model) and say why with set_reason. "
              + "Apply your changes with world_edit in one or two batches, then return the summary and your critic checklist.")
    opts = ClaudeAgentOptions(system_prompt=system, model=model, effort=effort, max_turns=int(role.get("max_turns", 30)),
                              tools=[], allowed_tools=names, mcp_servers={"world": server},
                              output_format={"type": "json_schema", "schema": DESIGN_SCHEMA}, setting_sources=[],
                              cli_path=find_claude_cli(), env={"MCP_TOOL_TIMEOUT": "600000"})
    result = None
    trace: list[str] = []                 # which tools it called, in order (shown in the chat and the run record)
    async for msg in query(prompt=prompt, options=opts):
        if isinstance(msg, AssistantMessage):
            trace += [b.name.removeprefix("mcp__world__") for b in msg.content if isinstance(b, ToolUseBlock)]
        if isinstance(msg, ResultMessage):
            result = msg
    if result is None or result.is_error:
        raise RuntimeError(f"world designer failed: {getattr(result, 'subtype', 'no result')} after {len(trace)} tool calls")
    data = result.structured_output or {}
    cost = float(result.total_cost_usd or 0)
    engine.router.spent_usd += cost
    if data.get("open_questions"):
        engine.world.store.spec.open_questions = list(data["open_questions"])[:8]
    return {"backend": "claude_code", "model": model, "summary": data.get("summary", ""), "shape": data.get("shape"),
            "critic": data.get("critic", []), "cost_usd": cost, "version": engine.world.store.spec.version,
            "trace": trace, "turns": result.num_turns}
