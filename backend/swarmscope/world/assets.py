"""The generic prop library: scene-setting objects every World can place without making a model.

Each asset is a part list in the model kit (world/models.py), so adding one is data, not code: the renderer compiles it
like any other model and draws it instanced and muted. Props orient a viewer and make places legible (benches around
a square, desks beside documents, racks beside datasets); they never encode a measured value, and they may not use
the data colour `tint`. Every asset passes check_model (tests/test_world.py).
"""
from __future__ import annotations

from typing import Any

from swarmscope.world.models import ModelDef


def _p(shape: str, size: list[Any], at: list[float], colour: str = "stone", material: str = "matte",
       rot: list[float] | None = None, anim: str | None = None, name: str = "") -> dict[str, Any]:
    d: dict[str, Any] = {"shape": shape, "size": size, "at": at, "colour": colour, "material": material, "name": name}
    if rot:
        d["rot"] = rot
    if anim:
        d["anim"] = anim
    return d


def _legs(w: float, d: float, h: float, t: float = 0.05, colour: str = "metal") -> list[dict[str, Any]]:
    return [_p("box", [t, h, t], [x, h / 2, z], colour, name="leg") for x in (-w, w) for z in (-d, d)]


_BOOKS = ["warm", "cool", "stone", "leaf", "paper", "wood"]

# id -> (meaning, parts). Sizes are in world units: a premade agent is about 1 tall, a slab landmark 1.3 wide.
_LIB: dict[str, tuple[str, list[dict[str, Any]]]] = {
    "tree": ("a round tree", [
        _p("cylinder", [0.07, 0.1, 0.7], [0, 0.35, 0], "wood", name="trunk"),
        _p("sphere", [0.48], [0, 1.05, 0], "leaf", name="crown"),
        _p("sphere", [0.3], [0.22, 1.32, 0.08], "leaf", name="crown top")]),
    "pine": ("a pine tree", [
        _p("cylinder", [0.06, 0.09, 0.5], [0, 0.25, 0], "wood", name="trunk"),
        _p("cone", [0.55, 0.9], [0, 0.85, 0], "leaf", name="lower"),
        _p("cone", [0.4, 0.75], [0, 1.4, 0], "leaf", name="upper")]),
    "bush": ("a low bush", [
        _p("dome", [0.38], [0, 0, 0], "leaf", name="bush"),
        _p("dome", [0.26], [0.32, 0, 0.1], "leaf", name="bush")]),
    "rock": ("a rock", [
        _p("prism", [0.34, 0.26, 5], [0, 0.13, 0], "stone", name="rock"),
        _p("prism", [0.2, 0.34, 4], [0.24, 0.17, 0.1], "stone", rot=[0, 30, 0], name="rock")]),
    "bench": ("a park bench", [
        _p("box", [1.0, 0.06, 0.34], [0, 0.42, 0], "wood", name="seat"),
        _p("box", [1.0, 0.28, 0.05], [0, 0.62, -0.16], "wood", name="back"),
        _p("box", [0.06, 0.4, 0.3], [-0.42, 0.2, 0], "metal", "metal", name="leg"),
        _p("box", [0.06, 0.4, 0.3], [0.42, 0.2, 0], "metal", "metal", name="leg")]),
    "lamp": ("a street lamp", [
        _p("cylinder", [0.13, 0.15, 0.1], [0, 0.05, 0], "metal", "metal", name="base"),
        _p("cylinder", [0.035, 0.05, 1.75], [0, 0.9, 0], "metal", "metal", name="post"),
        _p("sphere", [0.12], [0, 1.86, 0], "warm", "glow", name="light"),
        _p("cone", [0.17, 0.12], [0, 2.0, 0], "metal", "metal", name="cap")]),
    "desk": ("a desk with a screen", [
        _p("box", [1.1, 0.05, 0.55], [0, 0.72, 0], "wood", name="top"),
        *_legs(0.5, 0.22, 0.7),
        _p("box", [0.04, 0.12, 0.04], [0, 0.8, -0.14], "metal", name="stand"),
        _p("box", [0.44, 0.28, 0.03], [0, 0.98, -0.14], "ink", name="monitor"),
        _p("box", [0.38, 0.22, 0.01], [0, 0.98, -0.12], "cool", "glow", name="screen")]),
    "chair": ("an office chair", [
        _p("disc", [0.2], [0, 0.01, 0], "metal", "metal", name="base"),
        _p("cylinder", [0.03, 0.03, 0.4], [0, 0.21, 0], "metal", "metal", name="column"),
        _p("box", [0.42, 0.06, 0.42], [0, 0.43, 0], "cool", name="seat"),
        _p("box", [0.42, 0.42, 0.05], [0, 0.66, -0.19], "cool", name="back")]),
    "bookshelf": ("a bookshelf", [
        _p("box", [0.9, 1.6, 0.32], [0, 0.8, 0], "wood", name="case"),
        *[_p("box", [0.78, 0.3, 0.04], [0, 0.3 + 0.45 * k, 0.17], _BOOKS[k % len(_BOOKS)], name="books") for k in range(3)],
        *[_p("box", [0.3, 0.26, 0.04], [0.22 - 0.4 * (k % 2), 0.32 + 0.45 * k, 0.19], _BOOKS[(k + 3) % len(_BOOKS)],
             name="books") for k in range(3)]]),
    "notice_board": ("a notice board", [
        _p("cylinder", [0.04, 0.04, 1.4], [-0.5, 0.7, 0], "wood", name="post"),
        _p("cylinder", [0.04, 0.04, 1.4], [0.5, 0.7, 0], "wood", name="post"),
        _p("box", [1.1, 0.7, 0.05], [0, 1.05, 0], "wood", name="board"),
        _p("box", [1.2, 0.05, 0.16], [0, 1.43, 0], "shadow", name="roof"),
        _p("box", [0.22, 0.28, 0.01], [-0.3, 1.08, 0.03], "paper", name="sheet"),
        _p("box", [0.22, 0.3, 0.01], [0.0, 1.1, 0.03], "paper", name="sheet"),
        _p("box", [0.22, 0.24, 0.01], [0.3, 1.02, 0.03], "warm", name="sheet")]),
    "server_rack": ("a rack of servers", [
        _p("box", [0.7, 1.6, 0.6], [0, 0.8, 0], "metal", "metal", name="cabinet"),
        *[_p("box", [0.6, 0.04, 0.02], [0, 0.35 + 0.3 * k, 0.31], "cool", "glow", name="lights") for k in range(4)]]),
    "terminal": ("a computer terminal", [
        _p("box", [0.5, 0.9, 0.4], [0, 0.45, 0], "metal", "metal", name="stand"),
        _p("wedge", [0.42, 0.06, 0.2], [0, 0.93, 0.08], "ink", name="keys"),
        _p("box", [0.46, 0.34, 0.08], [0, 1.1, -0.1], "metal", "metal", name="housing"),
        _p("box", [0.38, 0.26, 0.01], [0, 1.1, -0.055], "cool", "glow", name="screen")]),
    "signpost": ("a signpost", [
        _p("cylinder", [0.04, 0.05, 1.6], [0, 0.8, 0], "wood", name="post"),
        _p("box", [0.62, 0.14, 0.03], [0.22, 1.42, 0], "paper", name="sign"),
        _p("box", [0.56, 0.14, 0.03], [-0.18, 1.16, 0], "warm", rot=[0, 25, 0], name="sign")]),
    "fence": ("a short fence", [
        *[_p("box", [0.07, 0.6, 0.07], [x, 0.3, 0], "wood", name="post") for x in (-1.2, -0.4, 0.4, 1.2)],
        _p("box", [2.5, 0.06, 0.04], [0, 0.46, 0], "wood", name="rail"),
        _p("box", [2.5, 0.06, 0.04], [0, 0.2, 0], "wood", name="rail")]),
    "small_house": ("a small house", [
        _p("box", [1.4, 1.0, 1.2], [0, 0.5, 0], "paper", name="walls"),
        _p("wedge", [1.5, 0.6, 0.66], [0, 1.3, 0.33], "wood", name="roof"),
        _p("wedge", [1.5, 0.6, 0.66], [0, 1.3, -0.33], "wood", rot=[0, 180, 0], name="roof"),
        _p("box", [0.3, 0.5, 0.02], [0, 0.25, 0.61], "shadow", name="door"),
        _p("box", [0.26, 0.22, 0.02], [0.42, 0.62, 0.61], "glass", name="window"),
        _p("box", [0.15, 0.4, 0.15], [0.42, 1.5, -0.25], "stone", name="chimney")]),
    "office_block": ("an office building", [
        _p("box", [1.8, 2.2, 1.4], [0, 1.1, 0], "stone", name="body"),
        *[_p("box", [1.82, 0.14, 1.42], [0, y, 0], "glass", name="windows") for y in (0.7, 1.2, 1.7)],
        _p("box", [1.9, 0.1, 1.5], [0, 2.25, 0], "shadow", name="roof"),
        _p("box", [0.4, 0.5, 0.02], [0, 0.25, 0.71], "shadow", name="door")]),
    "tower_block": ("a tall tower", [
        _p("box", [1.0, 4.5, 1.0], [0, 2.25, 0], "cool", name="body"),
        *[_p("box", [1.02, 0.1, 1.02], [0, y, 0], "glass", name="windows") for y in (0.8, 1.6, 2.4, 3.2, 4.0)],
        _p("cylinder", [0.02, 0.03, 0.8], [0, 4.9, 0], "metal", "metal", name="antenna")]),
    "fountain": ("a fountain", [
        _p("cylinder", [0.95, 1.0, 0.3], [0, 0.15, 0], "stone", name="basin"),
        _p("disc", [0.86], [0, 0.31, 0], "water", "gloss", name="water"),
        _p("cylinder", [0.1, 0.13, 0.6], [0, 0.6, 0], "stone", name="column"),
        _p("cylinder", [0.36, 0.2, 0.12], [0, 0.94, 0], "stone", name="bowl"),
        _p("sphere", [0.09], [0, 1.08, 0], "water", "gloss", anim="bob", name="jet")]),
    "crate_stack": ("a stack of crates", [
        _p("box", [0.5, 0.5, 0.5], [0, 0.25, 0], "wood", name="crate"),
        _p("box", [0.5, 0.5, 0.5], [0.52, 0.25, 0.05], "wood", rot=[0, 10, 0], name="crate"),
        _p("box", [0.45, 0.45, 0.45], [0.26, 0.725, 0.02], "warm", rot=[0, -12, 0], name="crate")]),
    "path_tiles": ("a few paving stones", [
        _p("box", [0.5, 0.04, 0.42], [x, 0.02, z], "stone", rot=[0, r, 0], name="tile")
        for x, z, r in ((0, -0.9, 4), (0.08, -0.3, -6), (-0.04, 0.3, 3), (0.06, 0.9, -4))]),
    "planter": ("a planter with a shrub", [
        _p("box", [0.6, 0.35, 0.6], [0, 0.175, 0], "stone", name="box"),
        _p("dome", [0.3], [0, 0.35, 0], "leaf", name="shrub")]),
    "parasol": ("a café table with a parasol", [
        _p("cylinder", [0.3, 0.3, 0.04], [0, 0.72, 0], "paper", name="table"),
        _p("cylinder", [0.03, 0.03, 1.6], [0, 0.8, 0], "metal", "metal", name="pole"),
        _p("cone", [0.75, 0.3], [0, 1.6, 0], "warm", name="shade")]),
}

ASSETS: dict[str, ModelDef] = {
    k: ModelDef(id=k, kind="prop", meaning=f"Scenery: {meaning} (decoration; encodes nothing).", parts=parts, by="library")
    for k, (meaning, parts) in _LIB.items()
}


def asset_catalog() -> dict[str, str]:
    """id -> what it is, for the designer."""
    return {k: v[0] for k, v in _LIB.items()}
