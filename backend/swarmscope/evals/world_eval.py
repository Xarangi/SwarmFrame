"""World evaluation (docs/WORLD_PLAN.md §10, H1 and H3): does position carry the planted behaviours, beyond chance?

For each planted behaviour in the swarm_scale generator, in the windows after its onset:
  auc_<feature>   how well a spatial feature ranks planted agents above the others (0.5 = chance), best window
  tightening      how much closer the planted agents stand to each other than before onset, against a random
                  control set of the same size (ratio < 1 means they gathered; planted vs control)
  flagged         share of planted agents that received a spatial flag (above the null's family-wise threshold)
and before any behaviour starts:
  false_flags_per_window   spatial flags per window when nothing is planted (H3: should be near zero)
"""
from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime
from typing import Any

import numpy as np


def _auc(pos: np.ndarray, neg: np.ndarray) -> float:
    if not len(pos) or not len(neg):
        return float("nan")
    allv = np.concatenate([pos, neg])
    ranks = allv.argsort().argsort().astype(float) + 1
    rp = ranks[: len(pos)].sum()
    return float((rp - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def _mean_pair(P: np.ndarray) -> float:
    if len(P) < 2:
        return float("nan")
    d = np.linalg.norm(P[:, None] - P[None, :], axis=2)
    return float(d[np.triu_indices(len(P), 1)].mean())


def evaluate_world(agents: int = 1000, hours: float = 36, seed: int = 7) -> dict[str, Any]:
    from swarmscope.engine import Engine
    fast = {"investigations.node_delay_s": 0, "agents.stub_delay_s": 0, "llm.mode": "stub"}
    e = Engine("swarm_scale", "default", slice_override={"agents": agents, "hours": hours, "seed": seed}, overrides=fast)
    W = e.world
    frames: list[dict[str, Any]] = []
    times: list[float] = []
    orig = W._step

    def hooked(widx, events):
        t0 = time.perf_counter()
        orig(widx, events)
        times.append(time.perf_counter() - t0)
        L = W.layout
        if not L.ids:
            return
        f = L.features()
        frames.append({"w": widx, "end": e.now(), "ids": list(L.ids), "pos": L.pos.copy(), "drift": f["drift"].copy(),
                       "iso": f["isolation"].copy(), "recent": f["recent"].copy(),
                       "flags": {k: set(v) for k, v in W.flags.items()}, "beams": {b["unit"] for b in W.beams},
                       "still": {L.ids[i] for i in np.where(f["still_talking"])[0]}})
    W._step = hooked
    asyncio.run(e.run_to_end())
    gt = e.ground_truth
    onsets = {g["id"]: datetime.fromisoformat(str(g["ts"])[:19]) for g in gt}
    first = min(onsets.values())
    pre = [fr for fr in frames if fr["end"] < first]
    false_flags = float(np.mean([len(fr["flags"].get("drift", set()) | fr["flags"].get("isolation", set())) for fr in pre[4:]])) \
        if len(pre) > 4 else None
    rng = random.Random(seed)
    out: dict[str, Any] = {"agents": agents, "windows": len(frames), "layout_ms_mean": round(1000 * float(np.mean(times)), 1),
                           "layout_ms_p95": round(1000 * float(np.percentile(times, 95)), 1),
                           "false_flags_per_window_before_any_behaviour": false_flags, "behaviours": {}}
    for g in gt:
        units = set(g.get("units") or [])
        w0 = next((i for i, fr in enumerate(frames) if fr["end"] >= onsets[g["id"]]), None)
        if w0 is None or not units:
            out["behaviours"][g["id"]] = {"note": "onset not reached in this run"}
            continue
        best = {"auc_drift": 0.5, "auc_isolation": 0.5}
        flagged, beamed, still, still_other, crowd_hit = set(), set(), set(), set(), False
        for fr in frames[w0: w0 + 12]:
            ids = fr["ids"]
            m = np.array([u in units for u in ids]) & fr["recent"]
            o = ~np.array([u in units for u in ids]) & fr["recent"]
            for feat, key in (("drift", "auc_drift"), ("iso", "auc_isolation")):
                a = _auc(fr[feat][m], fr[feat][o])
                if not np.isnan(a):
                    best[key] = max(best[key], a)
            flagged |= (fr["flags"].get("drift", set()) | fr["flags"].get("isolation", set())) & units
            beamed |= fr["beams"] & units
            still |= fr["still"] & units
            still_other |= fr["still"] - units
            scope_res = str(g.get("scope", "")).partition(":")[2]
            if scope_res and scope_res in fr["flags"].get("crowding", set()):
                crowd_hit = True
        before = frames[max(0, w0 - 1)]
        after = frames[min(len(frames) - 1, w0 + 6)]
        idx_b = {u: i for i, u in enumerate(before["ids"])}
        idx_a = {u: i for i, u in enumerate(after["ids"])}
        common = [u for u in units if u in idx_b and u in idx_a][:80]
        others = [u for u in after["ids"] if u in idx_b and u not in units]
        ctrl = rng.sample(others, min(len(others), len(common)))
        def ratio(us):
            pb = before["pos"][[idx_b[u] for u in us]]
            pa = after["pos"][[idx_a[u] for u in us]]
            return _mean_pair(pa) / max(1e-6, _mean_pair(pb))
        out["behaviours"][g["id"]] = {
            "kind": g.get("kind"), "units": len(units), **{k: round(v, 3) for k, v in best.items()},
            "tightening_planted": round(ratio(common), 3) if len(common) >= 2 else None,
            "tightening_control": round(ratio(ctrl), 3) if len(ctrl) >= 2 else None,
            "flagged_share": round(len(flagged) / len(units), 3),
            "operator_beam_share": round(len(beamed) / len(units), 3),
            "still_talking_share": round(len(still) / len(units), 3),
            "still_talking_share_others": round(len(still_other) / max(1, len(frames[w0]["ids"]) - len(units)), 3),
            "crowd_ring_on_scope": crowd_hit}
    pv = W.preview()
    out["separation"], out["separation_null"] = pv["separation"], pv["separation_null"]

    def team_sep(layout) -> float:
        """How legible teams are: mean distance between team centroids / mean spread within a team."""
        groups: dict[str, list[int]] = {}
        for i, u in enumerate(layout.ids):
            p = e.scale.profiles.get(u)
            if p and p.group:
                groups.setdefault(p.group, []).append(i)
        cents, spreads = [], []
        for idx in groups.values():
            if len(idx) >= 3:
                P = layout.pos[idx]
                cents.append(P.mean(axis=0))
                spreads.append(float(np.linalg.norm(P - P.mean(axis=0), axis=1).mean()))
        if len(cents) < 2:
            return float("nan")
        C = np.stack(cents)
        d = np.linalg.norm(C[:, None] - C[None, :], axis=2)
        return float(d[np.triu_indices(len(C), 1)].mean() / (np.mean(spreads) + 1e-6))
    out["team_separation"] = round(team_sep(W.layout), 2)
    out["team_separation_null"] = round(team_sep(W.null.layout), 2)
    return out


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(evaluate_world(int(sys.argv[1]) if len(sys.argv) > 1 else 1000), indent=1, default=str))
