"""The scene a stream lives in, and what its units do each window (docs/WORLD_PLAN.md, "Environment and activity").

environment  ground style, zones (soft tinted regions around matching places, with a label) and props placed from the
             generic asset library (world/assets.py) or from prop models made for this stream. Decoration that
             orients and makes places legible; it never encodes a measured value and is drawn muted.
behaviours   activity rules: `when` a condition the server computes per unit per window, `do` a choreography from a
             fixed library (go_to, gather, wander, ...) or a designer-composed sequence of library steps. No code.

Positions stay measurements: a behaviour is a temporary excursion over the window's playback that ends back at the
unit's measured position, and its `meaning` sentence goes in the legend ("walks to a page when it edits it").
"""
from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from swarmscope.world.assets import ASSETS, asset_catalog
from swarmscope.world.features import available

if TYPE_CHECKING:
    from swarmscope.world.spec import WorldSpec

ID = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

# ---------------------------------------------------------------- environment vocabulary
GROUNDS = {
    "paper": "the plain dashboard page with a faint polar grid (abstract worlds)",
    "grass": "a soft green lawn (villages, campuses)",
    "stone": "warm grey paving (towns, wikis)",
    "plaza_tiles": "square paving tiles (offices, workshops)",
    "grid": "a technical grid (machine swarms, infrastructure)",
    "water_edge": "land ringed by water at the world's edge (islands, closed worlds)",
    "sand": "pale sand (catalogs, open fields)",
}
ZONE_STYLES = {
    "lawn": "leaf", "paving": "stone", "tiles": "cool", "sand": "warm", "water": "water", "wood": "wood",
    "dark": "shadow", "plain": "paper",
}
ZONE_AROUND = {
    "family": "every landmark of this family (e.g. chat)", "archetype": "every landmark of this archetype (plaza, slab ...)",
    "label": "every landmark whose rule label is this (e.g. room)", "group": "a team's territory, or `all` for every team",
}
PROP_AT = {
    "centre": "one at the middle of the world",
    "rim": "`count` (<= 32) evenly around the edge",
    "territories": "one beside each team's territory (<= 24)",
    "landmarks": "`count` (1-4) around each place matching `near` ({family|archetype|label: x})",
    "zones": "`count` (1-6) inside each region of the zone `near: {zone: name}`",
    "scatter": "`count` (<= 60) scattered over the open ground (deterministic)",
}
MAX_ZONES = 8
MAX_PROP_RULES = 16
MAX_PROP_INSTANCES = 480

# ---------------------------------------------------------------- activity vocabulary
WHEN = {
    "active": "it did anything this window",
    "acted_on_landmark": "it acted on a place this window (filter: family, action prefix)",
    "talked": "it sent a message this window",
    "idle": "it is on the map but did nothing this window",
    "new": "it appeared for the first time in the last two windows",
    "stopped": "it is stopped (control plane or an operator stop)",
    "paused": "it is paused, waiting for approval, or denied",
    "flagged": "it is part of an open finding (it has a ring)",
    "surge": "its activity jumped far above its own usual (activity z >= 2)",
    "environment_hit": "an operator or the environment acted on it (moderation, stop, deny); filter: kind",
    "reused_content": "it reused content another unit posted (lineage)",
}
WHEN_BIT = {k: 1 << i for i, k in enumerate(WHEN)}
WHEN_NEEDS = {"acted_on_landmark": ["resources"], "talked": ["messages"], "stopped": ["state_fine"],
              "paused": ["state_fine"], "environment_hit": ["operator"], "reused_content": ["lineage"]}
STEPS = {
    "go_to": "walk to the place it acted on",
    "gather": "walk to the nearest plaza (a place for talking)",
    "follow": "walk toward its most frequent partner this window",
    "scatter": "step away from the place it was hit at (or its group's centre)",
    "wander": "a small loop around where it stands",
    "return": "walk back to its measured position",
    "work": "the working pose, where it is",
    "talk": "the talking pose, where it is",
    "wait": "stand still",
    "pulse": "a ring pulses under it",
    "glow": "it glows softly",
    "carry": "a small token travels from it to the place it acted on (from the origin to it, for reused content)",
    "fade": "it fades to faint",
}
MOVES = {"go_to", "gather", "follow", "scatter", "wander", "return"}
LIBRARY: dict[str, tuple[str, list[tuple[str, float]]]] = {
    "go_to": ("walk to the place it acted on, work there, walk back", [("go_to", 0.32), ("work", 0.36), ("return", 0.32)]),
    "gather": ("walk to the nearest plaza, talk there, walk back", [("gather", 0.3), ("talk", 0.4), ("return", 0.3)]),
    "follow": ("walk toward its main partner, talk, walk back", [("follow", 0.35), ("talk", 0.3), ("return", 0.35)]),
    "scatter": ("step away from where it was hit, wait, come back", [("scatter", 0.22), ("wait", 0.48), ("return", 0.3)]),
    "wander": ("drift in a small loop around its spot", [("wander", 1.0)]),
    "pulse": ("a ring pulses under it", [("pulse", 1.0)]),
    "glow": ("it glows softly", [("glow", 1.0)]),
    "carry": ("a token travels from it to the place (or from the origin to it)", [("carry", 0.7)]),
    "stay_home": ("stays where it is (an explicit 'nothing')", []),
    "fade": ("fades to faint for the window", [("fade", 1.0)]),
}
PARAMS = {"reach": (0.2, 1.0, "how far toward the target it walks (1 = all the way)"),
          "radius": (0.2, 3.0, "wander and scatter distance, in world units")}
MAX_BEHAVIOURS = 8
MAX_STEPS = 8


class Zone(BaseModel):
    name: str
    around: dict[str, Any]
    style: str = "paving"
    label: str = ""


class Prop(BaseModel):
    asset: str
    at: str = "rim"
    near: dict[str, Any] = Field(default_factory=dict)
    count: int = 1
    meaning: str = "decoration"


class Environment(BaseModel):
    ground: str = "paper"
    zones: list[Zone] = Field(default_factory=list)
    props: list[Prop] = Field(default_factory=list)


class Step(BaseModel):
    do: str
    dur: float = 0.3


class Behaviour(BaseModel):
    id: str = ""
    when: str
    filter: dict[str, Any] = Field(default_factory=dict)       # {family: x | [x, y], action: prefix, kind: stop|pause|message}
    do: str                                                    # a LIBRARY entry, or "sequence" with `steps`
    steps: list[Step] = Field(default_factory=list)
    params: dict[str, float] = Field(default_factory=dict)
    meaning: str = ""


class SceneError(ValueError):
    pass


def plan(b: Behaviour) -> list[dict[str, Any]]:
    """The step list the renderer plays: the library expansion, or the designer's own sequence."""
    steps = [(s.do, s.dur) for s in b.steps] if b.do == "sequence" else LIBRARY.get(b.do, ("", []))[1]
    return [{"do": d, "dur": round(float(t), 3)} for d, t in steps]


# ---------------------------------------------------------------- validation
def validate_scene(spec: "WorldSpec", table: dict[str, dict[str, str]]) -> list[str]:
    env = spec.environment
    warnings: list[str] = []
    if env.ground not in GROUNDS:
        raise SceneError(f"ground {env.ground!r}; grounds: {', '.join(GROUNDS)}")
    if len(env.zones) > MAX_ZONES:
        raise SceneError(f"at most {MAX_ZONES} zones")
    names = set()
    for z in env.zones:
        if not ID.match(z.name) or z.name in names:
            raise SceneError(f"zone name {z.name!r} is invalid or used twice (lowercase id)")
        names.add(z.name)
        if z.style not in ZONE_STYLES:
            raise SceneError(f"zone {z.name}: style must be one of {list(ZONE_STYLES)}")
        if len(z.around) != 1 or next(iter(z.around)) not in ZONE_AROUND:
            raise SceneError(f"zone {z.name}: around is one of {{{', '.join(ZONE_AROUND)}: value}}")
        if len(z.label) > 40:
            raise SceneError(f"zone {z.name}: a label is a few words in the source's nouns")
        if "group" in z.around and table and not available(table, "groups"):
            raise SceneError(f"zone {z.name}: this stream has no groups")
    props = {m.id for m in spec.models if m.kind == "prop"}
    if len(env.props) > MAX_PROP_RULES:
        raise SceneError(f"at most {MAX_PROP_RULES} prop placements")
    for p in env.props:
        if p.asset not in ASSETS and p.asset not in props:
            raise SceneError(f"prop {p.asset!r} is neither a library asset ({', '.join(ASSETS)}) nor a prop model "
                             f"made for this stream")
        if p.at not in PROP_AT:
            raise SceneError(f"prop {p.asset}: at must be one of {list(PROP_AT)}")
        if p.at in ("landmarks", "zones") and not p.near:
            raise SceneError(f"prop {p.asset}: at {p.at} needs `near`")
        if p.at == "zones" and p.near.get("zone") not in names:
            raise SceneError(f"prop {p.asset}: no zone {p.near.get('zone')!r}")
        if p.at == "landmarks" and (len(p.near) != 1 or next(iter(p.near)) not in ("family", "archetype", "label")):
            raise SceneError(f"prop {p.asset}: near is {{family|archetype|label: value}}")
        lim = {"landmarks": 4, "zones": 6, "rim": 32, "scatter": 60}.get(p.at, 24)
        if not 1 <= int(p.count) <= lim:
            raise SceneError(f"prop {p.asset}: count for at {p.at} is 1 to {lim}")
        if len(p.meaning.strip()) < 4:
            raise SceneError(f"prop {p.asset}: a meaning ('decoration' if it encodes nothing)")
    # behaviours
    if len(spec.behaviours) > MAX_BEHAVIOURS:
        raise SceneError(f"at most {MAX_BEHAVIOURS} behaviours")
    plinth = spec.unit.get("model") == "plinth"
    ids = set()
    for i, b in enumerate(spec.behaviours):
        tag = f"behaviour {b.id or i}"
        if b.id and (not ID.match(b.id) or b.id in ids):
            raise SceneError(f"{tag}: id is a lowercase id, unique")
        ids.add(b.id)
        if b.when not in WHEN:
            raise SceneError(f"{tag}: when {b.when!r}; conditions: {', '.join(WHEN)}")
        missing = [f for f in WHEN_NEEDS.get(b.when, []) if table and not available(table, f)]
        if missing:
            raise SceneError(f"{tag}: when {b.when} needs {', '.join(missing)}, which this stream does not have")
        bad = set(b.filter) - {"family", "action", "kind"}
        if bad:
            raise SceneError(f"{tag}: filter keys are family, action, kind (not {', '.join(sorted(bad))})")
        if b.do == "sequence":
            if not b.steps or len(b.steps) > MAX_STEPS:
                raise SceneError(f"{tag}: a sequence has 1 to {MAX_STEPS} steps")
            for s in b.steps:
                if s.do not in STEPS:
                    raise SceneError(f"{tag}: step {s.do!r}; steps: {', '.join(STEPS)}")
                if not 0.02 <= float(s.dur) <= 1.0:
                    raise SceneError(f"{tag}: a step lasts 0.02 to 1 (a share of the window's playback)")
            if sum(float(s.dur) for s in b.steps) > 1.0001:
                raise SceneError(f"{tag}: step durations add up to more than the window (1.0)")
            away = False
            for s in b.steps:
                away = (s.do in MOVES - {"return", "wander"}) or (away and s.do != "return")
            if away:
                raise SceneError(f"{tag}: a sequence that walks away must end with `return`: positions are measurements")
        elif b.do not in LIBRARY:
            raise SceneError(f"{tag}: do {b.do!r}; library: {', '.join(LIBRARY)}, or `sequence` with steps")
        elif b.steps:
            raise SceneError(f"{tag}: steps are only for do: sequence")
        for k, v in b.params.items():
            if k not in PARAMS:
                raise SceneError(f"{tag}: params are {', '.join(PARAMS)}")
            lo, hi, _ = PARAMS[k]
            if not lo <= float(v) <= hi:
                raise SceneError(f"{tag}: {k} must be between {lo} and {hi}")
        if plinth and any(p["do"] in MOVES for p in plan(b)):
            raise SceneError(f"{tag}: units are places in a plinth world and cannot walk; use pulse, glow, carry or fade")
        if len(b.meaning.strip()) < 8:
            raise SceneError(f"{tag}: a meaning sentence for the legend, in the source's nouns")
    used = {b.when for b in spec.behaviours}
    if spec.behaviours and not used & {"acted_on_landmark", "active", "talked"}:
        warnings.append("no behaviour shows units doing their work (acted_on_landmark, talked or active)")
    return warnings


def drop_unavailable(spec: "WorldSpec", table: dict[str, dict[str, str]]) -> None:
    """A preset is written for the full source: drop behaviours and zones this run cannot support, with a reason."""
    keep = []
    for b in spec.behaviours:
        missing = [f for f in WHEN_NEEDS.get(b.when, []) if not available(table, f)]
        if missing:
            spec.reasons[f"dropped:behaviour:{b.id or b.when}"] = f"{b.when} needs {', '.join(missing)}"
        else:
            keep.append(b)
    spec.behaviours = keep
    if not available(table, "groups"):
        spec.environment.zones = [z for z in spec.environment.zones if "group" not in z.around]


# ---------------------------------------------------------------- geometry (per state, server side)
def _h01(s: str) -> float:
    h = 2166136261
    for ch in s.encode():
        h = ((h ^ ch) * 16777619) & 0xFFFFFFFF
    return h / 4294967296


def _matches(lm: dict[str, Any], near: dict[str, Any]) -> bool:
    k, v = next(iter(near.items()))
    if k == "family":
        return lm.get("fam") == v or (isinstance(v, list) and lm.get("fam") in v)
    if k == "archetype":
        return lm.get("arch") == v
    if k == "label":
        return lm.get("kind") == v
    return False


def zone_regions(env: Environment, landmarks: list[dict[str, Any]], territories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each zone as soft discs (x, z, r) around what it matches, plus where its label goes (its busiest disc)."""
    out = []
    for z in env.zones:
        discs: list[tuple[float, float, float, float]] = []
        if "group" in z.around:
            g = z.around["group"]
            for t in territories:
                if g in ("all", "*") or t["id"] == g:
                    discs.append((t["x"], t["z"], t["r"] + 0.6, t.get("n", 1)))
        else:
            for lm in landmarks:
                if _matches(lm, z.around):
                    r = 1.6 + min(1.6, math.log1p(lm.get("events", 0) + lm.get("usual", 0)) / 2.5)
                    discs.append((lm["x"], lm["z"], r, lm.get("events", 0) + 1))
        if not discs:
            continue
        discs = sorted(discs, key=lambda d: -d[3])[:30]
        out.append({"name": z.name, "label": z.label or z.name.replace("_", " "), "style": z.style,
                    "discs": [[round(x, 2), round(zz, 2), round(r, 2)] for x, zz, r, _ in discs],
                    "lx": round(discs[0][0], 2), "lz": round(discs[0][1], 2)})
    return out


def place_props(env: Environment, landmarks: list[dict[str, Any]], territories: list[dict[str, Any]],
                zones: list[dict[str, Any]], scale: float) -> dict[str, list[float]]:
    """Prop instances as {asset: [x, z, yaw, ...]}, deterministic for the same landmarks; capped in total."""
    out: dict[str, list[float]] = {}
    total = 0
    zmap = {z["name"]: z for z in zones}
    for k, p in enumerate(env.props):
        spots: list[tuple[float, float, float]] = []
        n = max(1, int(p.count))
        if p.at == "centre":
            spots.append((0.0, 0.0, 0.0))
        elif p.at == "rim":
            for i in range(min(32, n)):
                a = 2 * math.pi * (i + 0.5 * _h01(f"{k}")) / n
                spots.append((math.cos(a) * scale * 1.12, math.sin(a) * scale * 1.12, -a - math.pi / 2))
        elif p.at == "territories":
            for t in territories[:24]:
                d = math.hypot(t["x"], t["z"]) or 1.0
                r = min(t["r"], scale * 0.45) + 0.9
                spots.append((t["x"] + t["x"] / d * r, t["z"] + t["z"] / d * r, -math.atan2(t["z"], t["x"]) - math.pi / 2))
        elif p.at == "landmarks":
            for lm in [x for x in landmarks if _matches(x, p.near)][:40]:
                base = _h01(f"{lm['id']}:{p.asset}") * 2 * math.pi
                size = 0.7 + min(1.6, math.log1p(lm.get("events", 0)) / 3)
                for i in range(min(4, n)):
                    a = base + 2 * math.pi * i / max(n, 1)
                    r = 1.25 * size + 0.55
                    x, z = lm["x"] + math.cos(a) * r, lm["z"] + math.sin(a) * r
                    spots.append((x, z, -a + math.pi / 2))          # facing the place
        elif p.at == "zones":
            reg = zmap.get(str(p.near.get("zone")))
            for x0, z0, r0 in (reg["discs"] if reg else [])[:12]:
                for i in range(min(6, n)):
                    a = _h01(f"{p.asset}:{x0}:{z0}:{i}") * 2 * math.pi
                    rr = r0 * (0.55 + 0.35 * _h01(f"r{i}:{x0}"))
                    spots.append((x0 + math.cos(a) * rr, z0 + math.sin(a) * rr, _h01(f"y{i}{x0}") * 6.28))
        elif p.at == "scatter":
            for i in range(min(60, n)):
                a = _h01(f"s{k}:{i}") * 2 * math.pi
                r = scale * (0.35 + 0.7 * math.sqrt(_h01(f"t{k}:{i}")))
                spots.append((math.cos(a) * r, math.sin(a) * r, _h01(f"u{k}:{i}") * 6.28))
        room = MAX_PROP_INSTANCES - total
        if room <= 0:
            break
        spots = spots[:room]
        if not spots:
            continue
        total += len(spots)
        arr = out.setdefault(p.asset, [])
        for x, z, yaw in spots:
            arr += [round(x, 2), round(z, 2), round(yaw, 2)]
    return out


# ---------------------------------------------------------------- catalogs for the designer
def behaviour_catalog() -> dict[str, Any]:
    return {
        "when": WHEN, "when_needs": WHEN_NEEDS,
        "library": {k: {"is": v[0], "steps": [{"do": d, "dur": t} for d, t in v[1]]} for k, v in LIBRARY.items()},
        "steps": STEPS, "params": {k: {"min": lo, "max": hi, "is": why} for k, (lo, hi, why) in PARAMS.items()},
        "max_behaviours": MAX_BEHAVIOURS,
        "rules": [
            "Rules are checked in order; the first that matches a unit decides what it does this window.",
            "Choose from the library first; compose a `sequence` of steps only when no entry says it.",
            "A walk is an excursion over the window's playback: a sequence that walks away must `return`. Positions "
            "stay measurements.",
            "Every behaviour has a meaning sentence for the legend, in the source's nouns ('walks to a page when it "
            "edits it').",
            "Plinth worlds (units are places) cannot walk: pulse, glow, carry, fade.",
            "Choreography is drawn for characters and pawns; dots stay still, so behaviours cost nothing at scale."],
        "example": [
            {"op": "add_behaviour", "behaviour": {"id": "edit", "when": "acted_on_landmark", "filter": {"family": "docs"},
                                                  "do": "go_to", "meaning": "Walks to a document when it edits it."}},
            {"op": "add_behaviour", "behaviour": {"id": "visit", "when": "talked", "do": "sequence", "steps": [
                {"do": "gather", "dur": 0.25}, {"do": "talk", "dur": 0.2}, {"do": "go_to", "dur": 0.2},
                {"do": "work", "dur": 0.15}, {"do": "return", "dur": 0.2}],
                "meaning": "Talks in the square, then goes to the place it works on."}}],
    }


def asset_catalog_full() -> dict[str, Any]:
    from swarmscope.world.models import check_model
    assets = {}
    for k, m in ASSETS.items():
        r = check_model(m, strict=False)
        assets[k] = {"is": asset_catalog()[k], "bounds": r.get("bounds"), "parts": len(m.parts)}
    return {"grounds": GROUNDS, "zone_styles": ZONE_STYLES, "zone_around": ZONE_AROUND, "prop_at": PROP_AT,
            "assets": assets, "max_zones": MAX_ZONES, "max_prop_rules": MAX_PROP_RULES,
            "max_prop_instances": MAX_PROP_INSTANCES,
            "rules": [
                "Design the scene: a ground, zones that match the places (squares around plazas, desks around "
                "documents), props that make the places legible, a rim that frames the world.",
                "Props are decoration: muted, never `tint`, never tied to a measured value. Use the library; make a "
                "prop model (add_model kind prop) only when no asset says what the place is.",
                "Fewer, well-placed props beat many: a viewer must still see the units first."],
            "example": [
                {"op": "set_environment", "ground": "grass"},
                {"op": "add_zone", "zone": {"name": "square", "around": {"family": "chat"}, "style": "paving",
                                            "label": "the square"}},
                {"op": "place_props", "props": [
                    {"asset": "bench", "at": "landmarks", "near": {"family": "chat"}, "count": 2,
                     "meaning": "decoration: benches around each room"},
                    {"asset": "tree", "at": "rim", "count": 16, "meaning": "decoration: the village edge"}]}]}


def scene_legend(spec: "WorldSpec") -> dict[str, Any]:
    """What the legend's 'What you are seeing' section says about the scene and the activity rules."""
    env = spec.environment
    props = []
    for p in env.props:
        name = ASSETS[p.asset].meaning.split(":", 1)[1].split("(")[0].strip() if p.asset in ASSETS else p.asset
        props.append(name)
    return {"ground": GROUNDS.get(env.ground, env.ground),
            "zones": [{"name": z.name, "label": z.label or z.name, "style": z.style} for z in env.zones],
            "props": list(dict.fromkeys(props)),
            "behaviours": [{"id": b.id, "when": b.when, "do": b.do, "meaning": b.meaning} for b in spec.behaviours]}
