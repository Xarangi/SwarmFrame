"""WorldSpec: what the World draws for one stream (docs/WORLD_PLAN.md §14-17), composed from the premade library
plus any models the designer made for this stream (world/models.py).

The designer (free or Claude) and people edit it with validated, atomic, versioned ops, the same discipline as
dashboard specs. Presets live in packs/<id>/world.yaml; streams without one get a composed default.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, Field

from swarmscope.ingest.packs import ROOT
from swarmscope.world.features import FEATURES, QUANTITY_NEEDS, available, quantity_ok, quantity_status
from swarmscope.world.models import ModelDef, ModelError, Scenery, check_model, kit, validate_models
from swarmscope.world.scene import (ASSETS, GROUNDS, LIBRARY, PROP_AT, STEPS, WHEN, ZONE_STYLES, Behaviour,
                                    Environment, Prop, SceneError, Zone, drop_unavailable, validate_scene)

if TYPE_CHECKING:
    from swarmscope.engine import Engine

WORLD_DIR = ROOT / "data" / "worlds"

# ---------------------------------------------------------------- the fixed library (§14), as data
UNIT_MODELS = {
    "sprite": "an agent with a stable identity: a small character, tinted by workstream, posed by state",
    "plinth": "a unit that is a place rather than an actor (a target, a page): a column whose height is activity",
}
CHARACTERS = {
    "newt": "the default agent character", "human": "a mini scientist", "frog": "a round frog", "owl": "a little owl",
    "fox": "a fox with a scarf", "robot": "a boxy toy robot",
}
STATES = ["idle", "active", "talking", "working", "blocked", "paused", "stopped"]
ATTACHMENTS = {
    "ring": "severity of the finding the unit is part of (ACT / LOOK / WATCH); nothing else may use it",
    "trail": "where the unit has been over the last windows (behaviour change)",
    "bubble": "a message was sent (its shape class on hover, never its words)",
    "label": "the unit's id or label, near zoom only",
    "banner": "a cohort's task label; always translucent when inferred",
    "badge": "a boolean the stream states (new this window, merged identity)",
    "tether": "two identities that may be the same agent",
}
ARCHETYPES = {
    "slab": "a document, file, page or sheet", "tower": "an external endpoint: host, site, API",
    "plaza": "a place where units talk: channel, room", "kiosk": "a board, queue, dataset or anything else",
    "road": "a method or route (worlds where units are places)", "gate": "where new units enter a territory",
    "district": "a grouping of landmarks",
}
RELATIONS = {
    "arc_touch": "co-touched the same place this window (derived)",
    "arc_reply": "one replied to the other (derived, or hatched when inferred)",
    "arc_lineage": "content one posted and the other reused (solid with exposure, dashed without)",
    "beam": "an operator or environment action on a unit (observed)",
}
CHANNELS = ["position", "height", "colour", "alpha", "material", "state", "ring", "trail", "bubble", "banner", "badge",
            "size", "heat", "width", "age", "arc", "beam", "fog", "territory"]
RESERVED = {"colour": {"family_dominant", "action_dominant", "group"},
            "ring": {"severity"},
            "height": {"activity", "activity_z", "landmark_distinct_z", "landmark_events", "grade", "volume"},
            "alpha": {"identity_confidence", "grade"}, "material": {"grade", "identity_confidence"}}
UNIT_CHANNELS = {"height", "colour", "alpha", "material", "state", "ring", "bubble", "banner", "badge", "size"}
GROUND_CHANNELS = {"heat", "fog", "territory", "width", "age"}
TRANSFORMS = ("linear", "log", "zscore", "rank", "clamp")
SHAPES = ("swarm", "swarm_control", "village", "wiki", "targets", "stripped", "custom")
TIERS = {
    "auto": "characters when few units are in view, pawns for hundreds, dots beyond a couple of thousand",
    "characters": "full characters for every unit (only sensible below ~80 units)",
    "pawns": "instanced capsule pawns (hundreds to ~2,000 units at 60 fps)",
    "dots": "instanced dots and cohort blobs (thousands of units)",
}
CAMERAS = ("overview", "follow", "at", "region", "sweep", "top")
ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


class Binding(BaseModel):
    channel: str
    quantity: str
    transform: str = "linear"
    status: str = "derived"            # filled by validation from the availability table
    legend: str = ""


class LandmarkRule(BaseModel):
    match: dict[str, Any] = Field(default_factory=dict)   # {family: x} | {prefix: x} | {kind: other}
    archetype: str = "kiosk"
    label: str = "place"
    reason: str = ""
    model: str | None = None            # a landmark model made for this stream; the archetype stays its meaning


class Scene(BaseModel):
    id: str
    title: str
    camera: str = "overview"            # overview | follow | at | region | sweep | top
    target: str | None = None           # unit / landmark / cohort id, or a feature name for `top`
    question: str = ""
    finding_kind: str | None = None
    filter: dict[str, Any] = Field(default_factory=dict)
    opening: bool = False


class WorldSpec(BaseModel):
    source: str
    version: int = 0
    shape: str = "swarm"
    unit: dict[str, Any] = Field(default_factory=lambda: {"model": "sprite", "of": "actor", "alpha_by": None})
    render: dict[str, Any] = Field(default_factory=lambda: {"tier": "auto", "max_characters": 80,
                                                            "character_by": "group", "character": "newt"})
    metric: dict[str, Any] = Field(default_factory=lambda: {
        "sentence": "Distance: how differently they behave and how little they interact.",
        "forces": {"anchor": 0.3, "landmark": 1.0, "interact": 0.8, "similar": 0.5, "repel": 0.6, "max_step": 0.08},
        "interactions": ["co_touch", "reply", "lineage", "shape"], "trail_windows": 12})
    landmarks: list[LandmarkRule] = Field(default_factory=list)
    landmarks_from: str = "object"       # object (resources are places) | family (methods are roads, targets worlds)
    models: list[ModelDef] = Field(default_factory=list)      # made for this stream (world/models.py)
    scenery: list[Scenery] = Field(default_factory=list)
    environment: Environment = Field(default_factory=Environment)    # ground, zones, props (world/scene.py)
    behaviours: list[Behaviour] = Field(default_factory=list)       # activity rules, first match wins
    territories: dict[str, Any] = Field(default_factory=lambda: {"by": "group"})
    bindings: list[Binding] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=lambda: ["arc_touch", "arc_reply", "arc_lineage", "beam"])
    coverage_fog: bool = True
    null_model: dict[str, Any] = Field(default_factory=lambda: {"windows": 24, "quantile": 0.95})
    scenes: list[Scene] = Field(default_factory=list)
    control: dict[str, Any] = Field(default_factory=lambda: {"enabled": False})
    annotations: list[dict[str, Any]] = Field(default_factory=list)
    availability: dict[str, dict[str, str]] = Field(default_factory=dict)
    reasons: dict[str, str] = Field(default_factory=dict)
    open_questions: list[str] = Field(default_factory=list)
    by: str = "default"
    rationale: str = ""
    updated: str | None = None


class WorldError(ValueError):
    pass


# ---------------------------------------------------------------- validation (§16, §17)
def validate(spec: WorldSpec, table: dict[str, dict[str, str]]) -> list[str]:
    """Raise WorldError on a hard violation; return soft warnings. Fills each binding's status from the table."""
    if spec.shape not in SHAPES:
        raise WorldError(f"shape must be one of {SHAPES}")
    model = spec.unit.get("model", "sprite")
    if model not in UNIT_MODELS:
        raise WorldError(f"unit.model must be one of {list(UNIT_MODELS)}")
    if model == "sprite" and table and not available(table, "identity"):
        raise WorldError("a sprite world needs identities; this stream has none, so units must be plinths")
    if spec.render.get("tier", "auto") not in TIERS:
        raise WorldError(f"render.tier must be one of {list(TIERS)}")
    unit_models = {m.id for m in spec.models if m.kind == "unit"}
    char = spec.render.get("character", "newt")
    if char not in CHARACTERS and char not in unit_models:
        raise WorldError(f"render.character must be one of {list(CHARACTERS)} or a unit model made for this stream")
    cast = spec.render.get("cast") or []
    for c in cast:
        if c not in CHARACTERS and c not in unit_models:
            raise WorldError(f"render.cast: {c!r} is neither a premade character nor a unit model")
    if spec.render.get("character_by", "group") not in ("group", "unit", "fixed", "none"):
        raise WorldError("render.character_by is group (one cast member per team), unit (per agent) or fixed "
                         "(everyone is render.character)")
    if spec.control.get("enabled") and table and not available(table, "control"):
        raise WorldError("control can only be enabled when the stream has a control plane")
    if spec.landmarks_from not in ("object", "family"):
        raise WorldError("landmarks_from is object or family")
    for r in spec.landmarks:
        if r.archetype not in ARCHETYPES:
            raise WorldError(f"landmark archetype {r.archetype!r}; archetypes: {', '.join(ARCHETYPES)}")
    uses = {"landmark": [r.model for r in spec.landmarks if r.model],
            "unit": [c for c in [char, *cast] if c not in CHARACTERS],
            "prop": [p.asset for p in spec.environment.props if p.asset not in ASSETS and p.asset in {m.id for m in spec.models}]}
    try:
        model_warnings = validate_models(spec.models, spec.scenery, uses)
    except ModelError as exc:
        raise WorldError(str(exc)) from exc
    for r in spec.relations:
        if r not in RELATIONS:
            raise WorldError(f"relation {r!r}; relations: {', '.join(RELATIONS)}")
    seen_q, seen_c = set(), set()
    if len([b for b in spec.bindings if b.channel != "trail"]) > 10:
        raise WorldError("at most 10 bindings (the trail shares position's quantity and is not counted)")
    for b in spec.bindings:
        if b.channel not in CHANNELS:
            raise WorldError(f"channel {b.channel!r}; channels: {', '.join(CHANNELS)}")
        if b.quantity not in QUANTITY_NEEDS:
            raise WorldError(f"quantity {b.quantity!r}; quantities: {', '.join(QUANTITY_NEEDS)}")
        base = b.transform.split("(")[0]
        if base not in TRANSFORMS:
            raise WorldError(f"transform {b.transform!r}; transforms: {', '.join(TRANSFORMS)}")
        if b.channel in RESERVED and b.quantity not in RESERVED[b.channel]:
            raise WorldError(f"{b.channel} is reserved for {', '.join(sorted(RESERVED[b.channel]))}; "
                             f"{b.quantity} cannot use it")
        if b.channel != "position" and (b.channel in seen_c):
            raise WorldError(f"channel {b.channel} is used twice")
        if b.quantity in seen_q and b.channel not in ("trail", "position"):
            raise WorldError(f"quantity {b.quantity} is encoded twice")
        seen_c.add(b.channel)
        seen_q.add(b.quantity)
        if table:
            ok, missing = quantity_ok(table, b.quantity)
            if not ok:
                raise WorldError(f"binding {b.channel} <- {b.quantity} needs {', '.join(missing)}, which this stream "
                                 f"does not have")
            b.status = quantity_status(table, b.quantity)
            if b.channel == "position" and b.status == "inferred":
                raise WorldError("position may only use derived features; inferred features label, never move")
        if not b.legend.strip():
            raise WorldError(f"binding {b.channel} <- {b.quantity} needs a legend sentence")
    if not any(s.opening for s in spec.scenes) and spec.scenes:
        spec.scenes[0].opening = True
    for s in spec.scenes:
        if s.camera not in CAMERAS:
            raise WorldError(f"scene {s.id}: camera must be one of {CAMERAS}")
        if not s.question.strip():
            raise WorldError(f"scene {s.id}: every scene answers a question")
    if len([s for s in spec.scenes if not s.opening]) > 4:
        raise WorldError("at most four scenes besides the opening one")
    try:
        warnings = list(model_warnings) + validate_scene(spec, table)
    except SceneError as exc:
        raise WorldError(str(exc)) from exc
    if uses["unit"] and spec.unit.get("model") == "plinth":
        warnings.append("custom unit models are not drawn in a plinth world")
    # what one glyph carries is what a person must decode at a glance; the ground and the layout are read separately
    on_unit = [b for b in spec.bindings if b.channel in UNIT_CHANNELS]
    on_ground = [b for b in spec.bindings if b.channel in GROUND_CHANNELS]
    if len(on_unit) > 6:
        warnings.append(f"{len(on_unit)} encodings on each unit; keep at most six ({', '.join(b.channel for b in on_unit)})")
    if len(on_ground) > 4:
        warnings.append(f"{len(on_ground)} encodings on the ground; keep at most four")
    if not spec.metric.get("sentence"):
        raise WorldError("metric.sentence: say what distance means, in the source's nouns")
    for k, v in (spec.metric.get("forces") or {}).items():
        lo, hi = FORCE_RANGES.get(k, (None, None))
        if lo is None:
            raise WorldError(f"force {k!r}; forces: {', '.join(FORCE_RANGES)}")
        if not lo <= float(v) <= hi:
            raise WorldError(f"force {k} must be between {lo} and {hi}")
    return warnings


FORCE_RANGES = {"anchor": (0.05, 1.0), "landmark": (0.0, 2.0), "interact": (0.0, 2.0), "similar": (0.0, 1.5),
                "repel": (0.2, 1.5), "max_step": (0.02, 0.2)}


def catalog() -> dict[str, Any]:
    return {"unit_models": UNIT_MODELS, "characters": CHARACTERS, "states": STATES, "attachments": ATTACHMENTS,
            "archetypes": ARCHETYPES, "relations": RELATIONS, "channels": CHANNELS,
            "reserved_channels": {k: sorted(v) for k, v in RESERVED.items()}, "quantities": QUANTITY_NEEDS,
            "transforms": list(TRANSFORMS), "shapes": list(SHAPES), "render_tiers": TIERS, "cameras": list(CAMERAS),
            "force_ranges": FORCE_RANGES, "features": FEATURES, "model_kit": kit(),
            "scene": {"grounds": list(GROUNDS), "zone_styles": list(ZONE_STYLES), "prop_at": list(PROP_AT),
                      "assets": list(ASSETS), "behaviour_when": list(WHEN), "behaviour_library": list(LIBRARY),
                      "steps": list(STEPS), "more": "world_asset_catalog and world_behaviour_catalog have the details"},
            "ops": OPS, "rules": [
                "Prefer the premade library. When no character or archetype says what a thing is, make a model from "
                "the model_kit (check it with world_model_check first); you cannot add textures, code or channels.",
                "Positions use derived features only; inferred features may label, tint or hatch, never move.",
                "Colour is a category, ring is severity, height is activity-like, alpha/material are certainty.",
                "Every binding needs a legend sentence in the source's nouns; every scene answers a question.",
                "For thousands of units use render.tier auto or dots: characters only below ~80 units in view.",
                "Design the scene (ground, zones, props) and the activity rules (behaviours): props never encode data; "
                "a behaviour is an excursion that returns to the measured position, with a legend sentence."]}


# ---------------------------------------------------------------- ops
OPS = ["set_shape", "set_unit", "set_render", "set_metric", "set_landmarks_from", "add_landmark", "update_landmark",
       "remove_landmark", "add_model", "update_model", "remove_model", "add_scenery", "remove_scenery", "set_territories", "add_binding", "update_binding",
       "remove_binding", "set_relations", "set_fog", "set_null_model", "add_scene", "update_scene", "move_scene",
       "remove_scene", "set_opening", "add_annotation", "remove_annotation", "set_control", "set_reason",
       "set_environment", "add_zone", "remove_zone", "place_props", "remove_props", "add_behaviour", "update_behaviour",
       "move_behaviour", "remove_behaviour", "reset_world"]


def _apply(engine: "Engine", spec: WorldSpec, op: dict[str, Any]) -> str:
    k = op.get("op")
    if k == "set_shape":
        spec.shape = op["shape"]
        return f"shape {spec.shape}"
    if k == "set_unit":
        spec.unit.update({x: op[x] for x in ("model", "of", "alpha_by") if x in op})
        return "unit updated"
    if k == "set_render":
        spec.render.update({x: op[x] for x in ("tier", "max_characters", "character_by", "character", "cast") if x in op})
        return "render updated"
    if k == "set_metric":
        if "sentence" in op:
            spec.metric["sentence"] = str(op["sentence"])[:240]
        if "forces" in op:
            spec.metric["forces"] = {**spec.metric.get("forces", {}), **op["forces"]}
        for x in ("interactions", "trail_windows"):
            if x in op:
                spec.metric[x] = op[x]
        return "metric updated"
    if k == "set_landmarks_from":
        spec.landmarks_from = op["value"]
        return f"landmarks from {spec.landmarks_from}"
    if k == "add_landmark":
        spec.landmarks.insert(int(op.get("at", len(spec.landmarks))), LandmarkRule(**op["landmark"]))
        return "landmark rule added"
    if k == "update_landmark":
        i = int(op["index"])
        spec.landmarks[i] = LandmarkRule(**{**spec.landmarks[i].model_dump(), **op["changes"]})
        return f"landmark rule {i} updated"
    if k == "remove_landmark":
        spec.landmarks.pop(int(op["index"]))
        return "landmark rule removed"
    if k in ("add_model", "update_model"):
        d = dict(op["model"])
        d.setdefault("by", op.get("by", "designer"))
        m = ModelDef(**d)
        check_model(m)
        i = next((i for i, x in enumerate(spec.models) if x.id == m.id), None)
        if k == "add_model" and i is not None:
            raise WorldError(f"model {m.id} exists; use update_model")
        if k == "update_model" and i is None:
            raise WorldError(f"no model {m.id}; use add_model")
        if i is None:
            spec.models.append(m)
        else:
            spec.models[i] = m
        return f"model {m.id} {'added' if k == 'add_model' else 'updated'} ({m.kind}, {len(m.parts)} parts)"
    if k == "remove_model":
        mid = op["id"]
        used = [r.label for r in spec.landmarks if r.model == mid] +             [x for x in [spec.render.get("character"), *(spec.render.get("cast") or [])] if x == mid] +             [s.at for s in spec.scenery if s.model == mid] + [f"props {p.at}" for p in spec.environment.props if p.asset == mid]
        if used:
            raise WorldError(f"model {mid} is still used ({', '.join(map(str, used))}); change those first")
        spec.models = [m for m in spec.models if m.id != mid]
        return f"model {mid} removed"
    if k == "add_scenery":
        spec.scenery.append(Scenery(**op["scenery"]))
        return f"scenery {op['scenery'].get('model')} at {op['scenery'].get('at', 'rim')}"
    if k == "remove_scenery":
        if "index" in op:
            spec.scenery.pop(int(op["index"]))
        else:
            spec.scenery = [s for s in spec.scenery if s.model != op["model"]]
        return "scenery removed"
    if k == "set_territories":
        spec.territories = {"by": op.get("by", "none")}
        return f"territories by {spec.territories['by']}"
    if k == "add_binding":
        spec.bindings.append(Binding(**op["binding"]))
        return f"binding {op['binding'].get('channel')} added"
    if k == "update_binding":
        i = next((i for i, b in enumerate(spec.bindings) if b.channel == op["channel"]), None)
        if i is None:
            raise WorldError(f"no binding on {op['channel']}")
        spec.bindings[i] = Binding(**{**spec.bindings[i].model_dump(), **op["changes"]})
        return f"binding {op['channel']} updated"
    if k == "remove_binding":
        spec.bindings = [b for b in spec.bindings if b.channel != op["channel"]]
        return f"binding {op['channel']} removed"
    if k == "set_relations":
        spec.relations = list(op["relations"])
        return "relations set"
    if k == "set_fog":
        spec.coverage_fog = bool(op.get("on", True))
        return "fog " + ("on" if spec.coverage_fog else "off")
    if k == "set_null_model":
        spec.null_model.update({x: op[x] for x in ("windows", "quantile") if x in op})
        return "null model updated"
    if k == "add_scene":
        sc = Scene(**op["scene"])
        if not ID.match(sc.id) or any(s.id == sc.id for s in spec.scenes):
            raise WorldError(f"scene id {sc.id!r} is invalid or exists")
        spec.scenes.append(sc)
        return f"scene {sc.id} added"
    if k == "update_scene":
        s = next((s for s in spec.scenes if s.id == op["id"]), None)
        if s is None:
            raise WorldError(f"no scene {op['id']}")
        i = spec.scenes.index(s)
        spec.scenes[i] = Scene(**{**s.model_dump(), **op["changes"]})
        return f"scene {op['id']} updated"
    if k == "move_scene":
        i = next(i for i, s in enumerate(spec.scenes) if s.id == op["id"])
        s = spec.scenes.pop(i)
        spec.scenes.insert(max(0, min(len(spec.scenes), int(op["to"]))), s)
        return f"scene {op['id']} moved"
    if k == "remove_scene":
        spec.scenes = [s for s in spec.scenes if s.id != op["id"]]
        return f"scene {op['id']} removed"
    if k == "set_opening":
        for s in spec.scenes:
            s.opening = s.id == op["id"]
        return f"opening scene {op['id']}"
    if k == "add_annotation":
        a = {"id": op.get("id") or f"pin{len(spec.annotations) + 1}", "at": op["at"], "text": str(op.get("text", ""))[:200],
             "by": op.get("by", "human"), "ts": datetime.utcnow().isoformat(timespec="seconds")}
        spec.annotations = [x for x in spec.annotations if x["id"] != a["id"]] + [a]
        spec.annotations = spec.annotations[-60:]
        return f"pinned {a['at']}"
    if k == "remove_annotation":
        spec.annotations = [x for x in spec.annotations if x["id"] != op["id"]]
        return "pin removed"
    if k == "set_control":
        spec.control = {"enabled": bool(op.get("enabled"))}
        return "control " + ("on" if spec.control["enabled"] else "off")
    if k == "set_reason":
        spec.reasons[str(op["key"])[:40]] = str(op["reason"])[:300]
        return "reason recorded"
    if k == "set_environment":
        if "ground" in op:
            spec.environment.ground = str(op["ground"])
        return f"ground {spec.environment.ground}"
    if k == "add_zone":
        z = Zone(**op["zone"])
        spec.environment.zones = [x for x in spec.environment.zones if x.name != z.name] + [z]
        return f"zone {z.name}"
    if k == "remove_zone":
        spec.environment.zones = [x for x in spec.environment.zones if x.name != op["name"]]
        spec.environment.props = [p for p in spec.environment.props if p.near.get("zone") != op["name"]]
        return f"zone {op['name']} removed"
    if k == "place_props":
        new = [Prop(**p) for p in (op.get("props") or [op["prop"]])]
        spec.environment.props += new
        return f"{len(new)} prop placement{'s' if len(new) != 1 else ''}"
    if k == "remove_props":
        if op.get("all"):
            spec.environment.props = []
        elif "index" in op:
            spec.environment.props.pop(int(op["index"]))
        else:
            spec.environment.props = [p for p in spec.environment.props if p.asset != op["asset"]]
        return "props removed"
    if k == "add_behaviour":
        b = Behaviour(**op["behaviour"])
        b.id = b.id or f"{b.when}-{b.do}"[:32].replace("_", "-")
        if any(x.id == b.id for x in spec.behaviours):
            raise WorldError(f"behaviour {b.id} exists; use update_behaviour")
        spec.behaviours.insert(int(op.get("at", len(spec.behaviours))), b)
        return f"behaviour {b.id}: when {b.when}, {b.do}"
    if k in ("update_behaviour", "move_behaviour", "remove_behaviour"):
        i = next((i for i, x in enumerate(spec.behaviours) if x.id == op["id"]), None)
        if i is None:
            raise WorldError(f"no behaviour {op['id']}; behaviours: {', '.join(x.id for x in spec.behaviours) or 'none'}")
        if k == "update_behaviour":
            spec.behaviours[i] = Behaviour(**{**spec.behaviours[i].model_dump(), **op["changes"]})
        elif k == "move_behaviour":
            b = spec.behaviours.pop(i)
            spec.behaviours.insert(max(0, min(len(spec.behaviours), int(op["to"]))), b)
        else:
            spec.behaviours.pop(i)
        return f"behaviour {op['id']} {k.split('_')[0]}d"
    if k == "reset_world":
        from swarmscope.world.designer import compose_world
        fresh = preset_world(engine) or compose_world(engine)[0]
        for f in WorldSpec.model_fields:
            if f not in ("version", "source"):
                setattr(spec, f, getattr(fresh, f))
        return "reset to the source's default world"
    raise WorldError(f"unknown op {k!r}; ops: {', '.join(OPS)}")


class WorldStore:
    """One WorldSpec per source with a version history (undo); persisted under data/worlds/ only from the API."""

    def __init__(self, source: str, path: Path | None | bool = None):
        self.source = source
        self.path = None if path is False else (path or WORLD_DIR / f"{source}.json")
        self.spec = WorldSpec(source=source)
        self.history: list[dict[str, Any]] = []
        if self.path is not None and self.path.exists():
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
                self.spec = WorldSpec(**d["spec"])
                self.history = d.get("history", [])[-30:]
            except Exception:
                pass

    @property
    def empty(self) -> bool:
        return self.spec.version == 0

    def save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"spec": self.spec.model_dump(), "history": self.history[-30:]}, indent=1),
                                 encoding="utf-8")
        except OSError:
            pass

    def _commit(self, new: WorldSpec, by: str, rationale: str) -> dict[str, Any]:
        self.history.append({"version": self.spec.version, "spec": self.spec.model_dump(), "by": self.spec.by,
                             "rationale": self.spec.rationale})
        new.version = self.spec.version + 1
        new.by, new.rationale = by, rationale
        new.updated = datetime.utcnow().isoformat(timespec="seconds")
        self.spec = new
        self.save()
        return {"spec": self.spec.model_dump(), "version": new.version}

    def apply_ops(self, engine: "Engine", ops: list[dict[str, Any]], by: str = "human", rationale: str = "") -> dict[str, Any]:
        new = copy.deepcopy(self.spec)
        applied = []
        for op in ops[:40]:
            try:
                applied.append(_apply(engine, new, op))
            except (WorldError, KeyError, TypeError, ValueError, IndexError, StopIteration) as exc:
                raise WorldError(f"op {len(applied) + 1} ({op.get('op')}): {exc}") from exc
        new.availability = engine.world.table() if getattr(engine, "world", None) else new.availability
        warnings = validate(new, new.availability)
        res = self._commit(new, by, rationale or "; ".join(applied)[:400])
        return {**res, "applied": applied, "warnings": warnings}

    def replace(self, spec: WorldSpec, by: str, rationale: str) -> dict[str, Any]:
        validate(spec, spec.availability)
        return self._commit(spec, by, rationale)

    def undo(self) -> dict[str, Any]:
        if not self.history:
            raise WorldError("nothing to undo")
        prev = self.history.pop()
        v = self.spec.version
        self.spec = WorldSpec(**prev["spec"])
        self.spec.version = v + 1
        self.save()
        return {"spec": self.spec.model_dump(), "version": self.spec.version}


def preset_hash(engine: "Engine") -> str:
    import hashlib
    f = engine.pack.dir / "world.yaml"
    return hashlib.sha1(f.read_bytes()).hexdigest()[:12] if f.exists() else ""


def preset_world(engine: "Engine") -> WorldSpec | None:
    """The source pack's hand-tuned World (packs/<id>/world.yaml), validated against this stream's features."""
    f = engine.pack.dir / "world.yaml"
    if not f.exists():
        return None
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)          # the C parser: the pure-Python one is slow
    d = yaml.load(f.read_text(encoding="utf-8"), Loader=loader) or {}
    d["source"] = engine.profile.source
    spec = WorldSpec(**d)
    spec.availability = engine.world.table() if getattr(engine, "world", None) else {}
    # a preset is written for the full source; drop bindings this run cannot support (e.g. models off)
    keep = []
    for b in spec.bindings:
        ok, _ = quantity_ok(spec.availability, b.quantity) if spec.availability else (True, [])
        if ok:
            keep.append(b)
        else:
            spec.reasons[f"dropped:{b.channel}"] = f"{b.quantity} is not available in this run"
    spec.bindings = keep
    if spec.availability:
        drop_unavailable(spec, spec.availability)
    if spec.control.get("enabled") and spec.availability and not available(spec.availability, "control"):
        spec.control = {"enabled": False}
    spec.by = "pack"
    spec.reasons["preset_hash"] = preset_hash(engine)
    return spec
