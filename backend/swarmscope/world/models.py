"""Models Claude makes for a stream: new 3D objects built from a part kit, validated, budgeted and checkable.

The premade library (characters, pawns, dots, plinths, archetypes) covers most streams. When it does not, for
example a stream whose places are server racks, mailboxes or lab benches, or whose agents are best shown as drones,
the designer writes a ModelDef: a list of parts (box, cylinder, sphere, lathe, ...) with positions, rotations,
theme colour tokens, a material and an optional gentle animation. The renderer compiles each model once and draws it
instanced, so a custom landmark costs the same as a premade one.

Why parts and not code: a part list cannot run in the viewer's browser, it is cheap to validate (size, triangle
budget, reserved meanings) and it renders in the dashboard's own style in light and dark themes.

Rules that keep a model honest (the same grammar as the rest of the World):
  - every model has a one-sentence meaning in the stream's nouns; the legend shows it
  - colour token `tint` is the only data colour: a unit's workstream, a landmark's kind; scenery may not use it
  - units may not be glass (translucency means uncertain identity) and may not bob (bobbing is the "active" pose)
  - scenery encodes nothing, is muted, and is capped at a few dozen instances
"""
from __future__ import annotations

import math
import re
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

KINDS = {
    "landmark": "a place units act on (a file, host, room, target); used by a landmark rule's `model`",
    "unit": "an agent character for the characters tier (a few dozen agents in view); tinted by workstream, posed by state",
    "prop": "scenery placed by `scenery` or environment props (centre, rim, landmarks, zones ...); encodes nothing, muted",
}
# shape -> (parameter names, one-line meaning). All shapes are centred on `at` unless noted.
SHAPES: dict[str, tuple[list[str], str]] = {
    "box": (["width", "height", "depth"], "a cuboid"),
    "cylinder": (["radius_top", "radius_bottom", "height"], "a cylinder or truncated cone (upright)"),
    "cone": (["radius", "height"], "a cone, point up"),
    "sphere": (["radius"], "a sphere"),
    "dome": (["radius"], "a half sphere, flat face down; `at` is the centre of the flat face"),
    "capsule": (["radius", "length"], "a pill, upright; total height is length + 2*radius"),
    "torus": (["radius", "tube", "arc_degrees"], "a ring in the x-y plane (stands up); arc 180 makes an arch; "
                                                 "rotate x by 90 to lay it flat"),
    "disc": (["radius"], "a thin flat circle (0.02 thick)"),
    "ring": (["inner_radius", "outer_radius"], "a thin flat annulus (0.02 thick)"),
    "prism": (["radius", "height", "sides"], "an upright prism with 3 to 8 sides (hexagonal posts, pyramids with sides=4 "
                                             "and a cone-like top are cylinders)"),
    "wedge": (["width", "height", "depth"], "a ramp: full height at -z, zero at +z"),
    "lathe": (["profile"], "a turned solid from 2 to 12 [radius, y] points, bottom to top (vases, bottles, towers); "
                           "`at` is the origin of the profile"),
}
COLOURS = {
    "tint": "the data colour: a unit's workstream, a landmark's kind (not allowed on scenery)",
    "ink": "near-black (dark theme: near-white)", "paper": "the page colour", "stone": "warm grey",
    "wood": "light brown", "metal": "cool grey", "glass": "pale blue-grey", "leaf": "muted green",
    "water": "muted blue", "warm": "sand", "cool": "slate", "accent": "the dashboard's clay accent (use sparingly)",
    "shadow": "a darker neutral for undersides and openings",
}
MATERIALS = {"matte": "rough, the default", "gloss": "smooth and slightly shiny", "metal": "metallic",
             "glass": "translucent (not on units: translucency means uncertain identity)",
             "glow": "softly emissive (screens, lamps); stronger at night"}
ANIMS = {"spin": "turns slowly about its vertical axis (fans, dishes, rotors)",
         "sway": "rocks a few degrees (antennae, flags, plants)",
         "bob": "rises and falls slightly (floating things; not on units, whose bob means 'active')"}
LIMITS = {
    "unit": {"parts": 16, "tris": 2500, "x": 0.5, "y": 1.3},
    "landmark": {"parts": 24, "tris": 4000, "x": 1.6, "y": 4.0},
    "prop": {"parts": 32, "tris": 4000, "x": 3.0, "y": 6.0},
}
MAX_MODELS = 10
MAX_SCENERY_INSTANCES = 120     # rim and centre scenery; environment props have their own budget (scene.py)
SCENERY_AT = {"centre": "one at the middle of the world", "rim": "`count` copies evenly around the edge (<= 24)",
              "territories": "one beside each group's territory (<= 24)"}
ID = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")


class Part(BaseModel):
    shape: str
    size: list[Any]
    at: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rot: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])     # degrees, applied x then y then z
    colour: str = "stone"
    material: str = "matte"
    anim: str | None = None
    name: str = ""


class ModelDef(BaseModel):
    id: str
    kind: str
    meaning: str
    parts: list[Part]
    by: str = "designer"


class Scenery(BaseModel):
    model: str
    at: str = "rim"
    count: int = 8
    meaning: str = ""


class ModelError(ValueError):
    pass


# ------------------------------------------------------------------ geometry for checks (not for rendering)
def _params(p: Part) -> list[float]:
    names = SHAPES[p.shape][0]
    if p.shape == "lathe":
        prof = p.size[0] if len(p.size) == 1 and isinstance(p.size[0], list) and p.size[0] and isinstance(p.size[0][0], list) else p.size
        if not (2 <= len(prof) <= 12) or any(not isinstance(q, (list, tuple)) or len(q) != 2 for q in prof):
            raise ModelError("lathe: size is a profile of 2 to 12 [radius, y] points")
        if any(float(r) < 0 for r, _ in prof):
            raise ModelError("lathe: radii must be >= 0")
        return [float(v) for q in prof for v in q]
    if p.shape == "torus" and len(p.size) == 2:
        p.size = [*p.size, 360]
    if len(p.size) != len(names):
        raise ModelError(f"{p.shape}: size is [{', '.join(names)}]")
    vals = [float(v) for v in p.size]
    if p.shape == "prism":
        if not 3 <= int(vals[2]) <= 8:
            raise ModelError("prism: sides must be 3 to 8")
        vals[2] = int(vals[2])
    if p.shape == "torus" and not 10 <= vals[2] <= 360:
        raise ModelError("torus: arc_degrees must be 10 to 360")
    if p.shape == "ring" and not 0 <= vals[0] < vals[1]:
        raise ModelError("ring: inner_radius must be below outer_radius")
    dims = vals[:2] if p.shape in ("torus", "prism") else vals
    if any(v <= 0 for v in dims if p.shape != "cylinder") or (p.shape == "cylinder" and (vals[2] <= 0 or max(vals[:2]) <= 0)):
        raise ModelError(f"{p.shape}: sizes must be positive")
    if max(dims) > 12:
        raise ModelError(f"{p.shape}: a size above 12 is outside any model's bounds")
    return vals


def _tris(p: Part, v: list[float]) -> int:
    return {"box": 12, "cylinder": 64, "cone": 32, "sphere": 336, "dome": 168, "capsule": 320, "torus": 192,
            "disc": 64, "ring": 64, "prism": 4 * int(v[2]) if p.shape == "prism" else 0, "wedge": 8,
            "lathe": 36 * (len(v) // 2 - 1)}[p.shape]


def _grid(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    A, B = np.meshgrid(a, b)
    return A.ravel(), B.ravel()


def _lin(lo: float, hi: float, res: float, cap: int = 100) -> np.ndarray:
    return np.linspace(lo, hi, int(min(cap, max(2, math.ceil(abs(hi - lo) / res) + 1))))


def _revolve(rs: np.ndarray, ys: np.ndarray, res: float, sides: int | None = None) -> np.ndarray:
    """Surface of a solid of revolution: the side wall plus top and bottom caps."""
    rmax = float(max(np.max(rs), 1e-3))
    k = sides or int(min(72, max(16, math.ceil(2 * math.pi * rmax / res))))
    ang = np.linspace(0, 2 * np.pi, k + 1)
    pts = []
    for i in range(len(rs) - 1):
        n = int(min(40, max(2, math.ceil(math.hypot(rs[i + 1] - rs[i], ys[i + 1] - ys[i]) / res) + 1)))
        for t in np.linspace(0, 1, n):
            r, y = rs[i] + (rs[i + 1] - rs[i]) * t, ys[i] + (ys[i + 1] - ys[i]) * t
            if sides:   # flat faces between corners
                c = np.stack([np.cos(ang), np.sin(ang)], 1) * r
                e = np.concatenate([np.linspace(c[j], c[j + 1], 8) for j in range(k)], 0)
                pts.append(np.stack([e[:, 0], np.full(len(e), y), e[:, 1]], 1))
            else:
                pts.append(np.stack([np.cos(ang) * r, np.full_like(ang, y), np.sin(ang) * r], 1))
    for r, y in ((rs[0], ys[0]), (rs[-1], ys[-1])):
        for f in _lin(0, r, res, 30)[:-1]:
            pts.append(np.stack([np.cos(ang) * f, np.full_like(ang, y), np.sin(ang) * f], 1))
    return np.concatenate(pts, 0)


def _samples(p: Part, v: list[float]) -> np.ndarray:
    """Points on the part's surface, in model space: enough to draw silhouettes and to bound it."""
    s = p.shape
    big = max([abs(float(x)) for x in v] + [0.1])
    res = max(0.008, big / 80)
    pts: list[np.ndarray] = []
    if s in ("box", "wedge"):
        w, h, d = v
        xs, ys, zs = _lin(-w / 2, w / 2, res), _lin(-h / 2, h / 2, res), _lin(-d / 2, d / 2, res)
        X, Y = _grid(xs, ys)
        for z in (-d / 2, d / 2):
            pts.append(np.stack([X, Y, np.full_like(X, z)], 1))
        Y, Z = _grid(ys, zs)
        for x in (-w / 2, w / 2):
            pts.append(np.stack([np.full_like(Y, x), Y, Z], 1))
        X, Z = _grid(xs, zs)
        for y in (-h / 2, h / 2):
            pts.append(np.stack([X, np.full_like(X, y), Z], 1))
        P = np.concatenate(pts, 0)
        if s == "wedge":       # full height at -z, zero at +z: keep what is under the ramp, add the ramp
            top = h * (0.5 - P[:, 2] / d) - h / 2
            P = P[P[:, 1] <= top + 1e-6]
            P = np.concatenate([P, np.stack([X, h * (0.5 - Z / d) - h / 2, Z], 1)], 0)
        pts = [P]
    elif s == "cylinder":
        rt, rb, h = v
        pts.append(_revolve(np.array([rb, rt]), np.array([-h / 2, h / 2]), res))
    elif s == "prism":
        r, h, k = v
        pts.append(_revolve(np.array([r, r]), np.array([-h / 2, h / 2]), res, int(k)))
    elif s == "cone":
        r, h = v
        pts.append(_revolve(np.array([r, 0.0]), np.array([-h / 2, h / 2]), res))
    elif s in ("sphere", "dome"):
        r = v[0]
        th = np.linspace(0 if s == "dome" else -np.pi / 2, np.pi / 2, 24)
        pts.append(_revolve(r * np.cos(th), r * np.sin(th), res))
    elif s == "capsule":
        r, ln = v
        lo_t, hi_t = np.linspace(-np.pi / 2, 0, 12), np.linspace(0, np.pi / 2, 12)
        rs = np.concatenate([r * np.cos(lo_t), r * np.cos(hi_t)])
        ys = np.concatenate([-ln / 2 + r * np.sin(lo_t), ln / 2 + r * np.sin(hi_t)])
        pts.append(_revolve(rs, ys, res))
    elif s == "torus":
        R, tube, arc = v
        A, B = _grid(np.linspace(0, math.radians(arc), int(max(12, min(120, math.ceil(R * math.radians(arc) / res))))),
                     np.linspace(0, 2 * np.pi, 20))
        pts.append(np.stack([(R + tube * np.cos(B)) * np.cos(A), (R + tube * np.cos(B)) * np.sin(A), tube * np.sin(B)], 1))
    elif s in ("disc", "ring"):
        r0, r1 = (0.0, v[0]) if s == "disc" else (v[0], v[1])
        ang = np.linspace(0, 2 * np.pi, int(min(96, max(24, 2 * math.pi * r1 / res))))
        for f in _lin(r0, r1, res, 40):
            for y in (-0.01, 0.01):
                pts.append(np.stack([np.cos(ang) * f, np.full_like(ang, y), np.sin(ang) * f], 1))
    elif s == "lathe":
        prof = np.array(v, dtype=float).reshape(-1, 2)
        pts.append(_revolve(prof[:, 0], prof[:, 1], res))
    P = np.concatenate(pts, 0)
    rx, ry, rz = (math.radians(x) for x in (list(p.rot) + [0, 0, 0])[:3])
    Rx = np.array([[1, 0, 0], [0, math.cos(rx), -math.sin(rx)], [0, math.sin(rx), math.cos(rx)]])
    Ry = np.array([[math.cos(ry), 0, math.sin(ry)], [0, 1, 0], [-math.sin(ry), 0, math.cos(ry)]])
    Rz = np.array([[math.cos(rz), -math.sin(rz), 0], [math.sin(rz), math.cos(rz), 0], [0, 0, 1]])
    R = Rz @ Ry @ Rx       # three.js Euler 'XYZ'
    return P @ R.T + np.array((list(p.at) + [0, 0, 0])[:3], dtype=float)


def _silhouette(clouds: list[np.ndarray], u_ax: int, u_sign: int, v_ax: int, v_sign: int, depth_ax: int,
                w: int, h: int, lo: np.ndarray, hi: np.ndarray) -> list[str]:
    """ASCII view: each cell shows the letter of the nearest part (a, b, c ...), '.' where empty.
    u runs left to right, v bottom to top; larger values on depth_ax are nearer the viewer."""
    P = np.concatenate(clouds, 0)
    k = np.concatenate([np.full(len(c), i) for i, c in enumerate(clouds)])
    span = np.maximum(hi - lo, 1e-6)

    def norm(ax: int, sign: int, n: int) -> np.ndarray:
        t = (P[:, ax] - lo[ax]) / span[ax]
        return ((t if sign > 0 else 1 - t) * (n - 1)).round().astype(int)
    u, vv = norm(u_ax, u_sign, w), norm(v_ax, v_sign, h)
    cell = (h - 1 - vv) * w + u
    order = np.lexsort((P[:, depth_ax], cell))     # by cell, then depth: the last in each cell is the nearest
    cs = cell[order]
    last = np.r_[cs[1:] != cs[:-1], True]
    grid = np.full(w * h, ".", dtype="<U1")
    letters = np.array([chr(ord("a") + i) if i < 26 else "#" for i in range(len(clouds))])
    grid[cs[last]] = letters[k[order][last]]
    return ["".join(r) for r in grid.reshape(h, w)]


# ------------------------------------------------------------------ validation and the check tool
def check_model(m: ModelDef | dict[str, Any], strict: bool = True) -> dict[str, Any]:
    """Validate one model and describe it: bounds, triangle estimate, warnings, and three ASCII silhouettes.
    With strict=True a violation raises ModelError; the check tool reports it instead."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        md = m if isinstance(m, ModelDef) else ModelDef(**m)
    except Exception as exc:          # pydantic: report, do not crash the tool
        if strict:
            raise ModelError(f"model: {exc}") from exc
        return {"ok": False, "errors": [f"model: {exc}"]}
    if not ID.match(md.id):
        errors.append("id: lowercase letters, digits, - or _, 2 to 32 characters, starting with a letter")
    if md.kind not in KINDS:
        errors.append(f"kind must be one of {list(KINDS)}")
    if len(md.meaning.strip()) < 8:
        errors.append("meaning: one sentence, in the stream's nouns, saying what this object stands for")
    lim = LIMITS.get(md.kind, LIMITS["prop"])
    if not md.parts:
        errors.append("a model needs at least one part")
    if len(md.parts) > lim["parts"]:
        errors.append(f"{md.kind} models have at most {lim['parts']} parts")
    clouds, tris = [], 0
    for i, p in enumerate(md.parts):
        tag = f"part {chr(ord('a') + i)}{' (' + p.name + ')' if p.name else ''}"
        if p.shape not in SHAPES:
            errors.append(f"{tag}: shape must be one of {list(SHAPES)}")
            continue
        if p.colour not in COLOURS:
            errors.append(f"{tag}: colour must be a theme token: {', '.join(COLOURS)}")
        if p.material not in MATERIALS:
            errors.append(f"{tag}: material must be one of {list(MATERIALS)}")
        if p.anim is not None and p.anim not in ANIMS:
            errors.append(f"{tag}: anim must be one of {list(ANIMS)} or null")
        if md.kind == "prop" and p.colour == "tint":
            errors.append(f"{tag}: scenery encodes nothing, so it may not use the data colour `tint`")
        if md.kind == "unit" and p.material == "glass":
            errors.append(f"{tag}: units may not be glass; translucency means an uncertain identity")
        if md.kind == "unit" and p.anim == "bob":
            errors.append(f"{tag}: units may not bob; bobbing is the 'active' pose")
        if len(p.at) != 3 or len(p.rot) not in (0, 3):
            errors.append(f"{tag}: at is [x, y, z] and rot is [x, y, z] degrees")
            continue
        try:
            v = _params(p)
        except ModelError as exc:
            errors.append(f"{tag}: {exc}")
            continue
        tris += _tris(p, v)
        clouds.append(_samples(p, v))
    if md.kind == "unit" and not any(p.colour == "tint" for p in md.parts):
        errors.append("a unit model needs at least one `tint` part: the workstream colour is how the World encodes it")
    if tris > lim["tris"]:
        errors.append(f"about {tris} triangles; {md.kind} models stay under {lim['tris']} (spheres and capsules are "
                      f"the expensive parts)")
    out: dict[str, Any] = {"id": md.id, "kind": md.kind, "parts": len(md.parts), "triangles": tris}
    if clouds:
        allp = np.concatenate(clouds, 0)
        lo, hi = allp.min(0), allp.max(0)
        out["bounds"] = {"min": [round(float(x), 2) for x in lo], "max": [round(float(x), 2) for x in hi]}
        if max(abs(lo[0]), abs(hi[0]), abs(lo[2]), abs(hi[2])) > lim["x"] + 1e-6:
            errors.append(f"too wide: {md.kind} models stay within ±{lim['x']} in x and z")
        if hi[1] > lim["y"] + 1e-6:
            errors.append(f"too tall: {md.kind} models stay below y = {lim['y']}")
        if lo[1] < -0.05:
            errors.append(f"part of the model is below the ground (min y {lo[1]:.2f}); the ground is y = 0")
        if lo[1] > 0.05:
            warnings.append(f"the lowest point is at y = {lo[1]:.2f}: the model floats above the ground")
        # parts that touch nothing: a likely mistake (a hat floating above a head)
        boxes = [(c.min(0) - 0.02, c.max(0) + 0.02) for c in clouds]
        for i, (a0, a1) in enumerate(boxes):
            grounded = a0[1] <= 0.05
            touches = any(np.all(a0 <= b1) and np.all(b0 <= a1) for j, (b0, b1) in enumerate(boxes) if j != i)
            if not grounded and not touches and len(boxes) > 1:
                warnings.append(f"part {chr(ord('a') + i)} touches no other part and not the ground")
        # draw: front (x right, y up, viewer at +z), side (z right, y up, viewer at +x), top (x right, z down)
        lo3, hi3 = lo.copy(), hi.copy()
        side = max(hi3[0] - lo3[0], hi3[2] - lo3[2], 1e-3)
        h_front = max(4, min(18, round(14 * (hi3[1] - lo3[1]) / side)))
        out["front"] = _silhouette(clouds, 0, 1, 1, 1, 2, 32, h_front, lo3, hi3)      # from +z: x right, y up
        out["side"] = _silhouette(clouds, 2, -1, 1, 1, 0, 32, h_front, lo3, hi3)      # from +x: -z right, y up
        out["top"] = _silhouette(clouds, 0, 1, 2, -1, 1, 32, 14, lo3, hi3)            # from above, front at the bottom
        out["views"] = "front: seen from +z (x right, y up); side: seen from +x; top: from above, the front at the bottom"
        out["legend"] = {chr(ord("a") + i): f"{p.shape}{' ' + p.name if p.name else ''} ({p.colour}, {p.material})"
                         for i, p in enumerate(md.parts[:26])}
    out["errors"], out["warnings"] = errors, warnings
    out["ok"] = not errors
    if strict and errors:
        raise ModelError(f"model {md.id}: " + "; ".join(errors[:4]))
    return out


def validate_models(models: list[ModelDef], scenery: list[Scenery], uses: dict[str, list[str]]) -> list[str]:
    """Spec-level checks: unique ids, budgets, and that every reference points at a model of the right kind."""
    if len(models) > MAX_MODELS:
        raise ModelError(f"at most {MAX_MODELS} models per World")
    ids = [m.id for m in models]
    if len(set(ids)) != len(ids):
        raise ModelError("model ids must be unique")
    kinds = {m.id: m.kind for m in models}
    for m in models:
        check_model(m)
    for kind, refs in uses.items():
        for r in refs:
            if r not in kinds:
                raise ModelError(f"no model {r!r}; add it with add_model first")
            if kinds[r] != kind:
                raise ModelError(f"model {r!r} is a {kinds[r]}, but is used as a {kind}")
    total = 0
    for s in scenery:
        if s.model not in kinds or kinds[s.model] != "prop":
            raise ModelError(f"scenery uses {s.model!r}, which is not a prop model")
        if s.at not in SCENERY_AT:
            raise ModelError(f"scenery at must be one of {list(SCENERY_AT)}")
        if len(s.meaning.strip()) < 4:
            raise ModelError("scenery needs a meaning (say 'decoration' if it encodes nothing)")
        total += 1 if s.at == "centre" else max(1, min(24, int(s.count)))
    if total > MAX_SCENERY_INSTANCES:
        raise ModelError(f"at most {MAX_SCENERY_INSTANCES} scenery instances")
    warnings = []
    unused = set(ids) - {r for refs in uses.values() for r in refs} - {s.model for s in scenery}
    if unused:
        warnings.append(f"models not used anywhere yet: {', '.join(sorted(unused))}")
    return warnings


def kit() -> dict[str, Any]:
    """What the designer reads before making a model."""
    return {"kinds": KINDS, "shapes": {k: {"size": v[0], "is": v[1]} for k, v in SHAPES.items()}, "colours": COLOURS,
            "materials": MATERIALS, "anims": ANIMS, "limits": LIMITS, "max_models": MAX_MODELS,
            "scenery_at": SCENERY_AT, "max_scenery_instances": MAX_SCENERY_INSTANCES,
            "space": "y is up, the ground is y = 0, +z faces the viewer; sizes are in world units (a premade agent is "
                     "about 1 tall, a slab landmark 1.3 wide). Parts are centred on `at` unless the shape says otherwise.",
            "rules": [
                "Make a model only when no premade character or archetype says what the thing is; say why in set_reason.",
                "Every model has a one-sentence meaning; the legend shows it.",
                "`tint` is the only data colour; units need at least one tint part; scenery may not use it.",
                "Units: no glass, no bob. They are posed by state like the premade cast.",
                "Check every model with world_model_check before adding it; read the silhouettes.",
                "Custom units are drawn only in the characters tier; pawns and dots stay as they are for speed."]}
