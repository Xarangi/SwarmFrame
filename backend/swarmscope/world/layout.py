"""The layout model: where a unit stands is a measurement.

Two levels (docs/WORLD_PLAN.md §3):
  1. Cohort anchors, deterministic. A cohort's signature (dominant family, action, group) fixes its anchor on a
     wheel: the family picks an angular sector from a fixed 16-slot order, the group picks a radial band and an
     offset inside the sector. "shell agents of team-07" therefore sit in the same region in every run.
  2. Units within and between anchors, by bounded incremental forces each window:
       anchor     spring to the cohort anchor (weak; keeps the map legible)
       landmark   pull toward the places the unit acted on this window (a convergence becomes a crowd)
       interact   pull along derived interaction edges (co-touch, replies, lineage)
       similar    pull toward the cohort centroid, scaled by how alike the unit is to its cohort
       repel      short-range push apart (grid hashing), so crowds stay readable
     The step is clamped, so speed itself is readable; units with no events this window do not move.

Only derived features move anything. The same model runs on a shuffled copy of each window (who-did-what
permuted, rates and places kept) to give the null distribution of every spatial feature; a feature glows only
above its null quantile.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

FAMILY_WHEEL = ["shell", "code", "files", "docs", "data", "sheets", "web", "search", "research", "computer",
                "chat", "mail", "social", "planning", "delegation", "narration"]
HISTORY = 24                     # windows of position history kept per unit (trails, drift)


def h01(s: str, salt: str = "") -> float:
    return int(hashlib.sha1((salt + "|" + s).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def family_slot(fam: str) -> int:
    return FAMILY_WHEEL.index(fam) if fam in FAMILY_WHEEL else int(h01(fam, "fam") * 16) % 16


def anchor_for(signature: tuple, scale: float, groups: list[str] | None = None) -> np.ndarray:
    """Deterministic anchor for a cohort signature (family, action, group, ...).

    With teams (groups), the team picks the sector (teams are where people look for each other) and the workstream
    picks the ring inside it; without teams, the workstream picks the sector on a fixed 16-slot wheel."""
    fam = str(signature[0]) if signature else "other"
    grp = str(signature[2]) if len(signature) > 2 else "none"
    rest = "|".join(map(str, signature[1:2] + signature[3:]))
    if groups and grp not in ("none", "ungrouped", "") and grp in groups:
        n = len(groups)
        width = 2 * math.pi / n
        sector = groups.index(grp) * width
        off = ((family_slot(fam) % 5) / 4 - 0.5) * 0.6 * width + (h01(rest, "rest") - 0.5) * 0.15 * width
        band = 0.42 + 0.14 * (family_slot(fam) % 4) + 0.05 * h01(rest, "r2")
    else:
        width = 2 * math.pi / 16
        sector = family_slot(fam) * width
        off = ((h01(grp, "grp") - 0.5) * 0.8 + (h01(rest, "rest") - 0.5) * 0.25) * width
        band = 0.45 + 0.5 * (int(h01(grp, "band") * 4) / 4) + 0.08 * h01(rest, "r2")
    r = band * scale
    a = sector + off
    return np.array([math.cos(a) * r, math.sin(a) * r], dtype=np.float32)


@dataclass
class Landmark:
    key: str
    kind: str                     # family of the resource, or "method" for targets worlds
    pos: np.ndarray
    created: int
    events: int = 0
    distinct: int = 0
    usual_distinct: float = 0.0
    usual_events: float = 0.0
    seen: int = 0
    teams: Counter = field(default_factory=Counter)

    crowd_now: float = 1.0                # distinct units now vs the usual crowd before this window

    @property
    def crowding(self) -> float:
        """Distinct units now vs this landmark's usual (the convergence quantity)."""
        return self.crowd_now


@dataclass
class WindowInput:
    """One window, reduced to what the layout needs (derived features only)."""
    index: int
    units: dict[str, dict[str, Any]]           # unit -> {n, res: Counter, msgs, errs, fam, group}
    edges: list[tuple[str, str, float, str]]    # (a, b, weight, kind) kind: co_touch | reply | lineage
    cohort_of: dict[str, str]
    cohort_sig: dict[str, tuple]
    similarity: dict[str, float]                # unit -> 1 - TV(unit mix, cohort mix), 0..1


class Layout:
    def __init__(self, forces: dict[str, float] | None = None, seed: int = 7):
        self.f = {"anchor": 0.3, "landmark": 1.0, "interact": 0.8, "similar": 0.5, "repel": 0.6, "max_step": 0.08,
                  **(forces or {})}
        self.seed = seed
        self.ids: list[str] = []
        self.index: dict[str, int] = {}
        self.pos = np.zeros((0, 2), dtype=np.float32)
        self.hist = np.zeros((0, HISTORY, 2), dtype=np.float32)
        self.last_active = np.zeros(0, dtype=np.int32)
        self.first_active = np.zeros(0, dtype=np.int32)
        self.n_now = np.zeros(0, dtype=np.int32)
        self.msgs_now = np.zeros(0, dtype=np.int32)
        self.errs_now = np.zeros(0, dtype=np.int32)
        self.rate_ewma = np.zeros(0, dtype=np.float32)
        self.rate_var = np.zeros(0, dtype=np.float32)
        self.cohort = np.zeros(0, dtype=np.int32)
        self.cohort_ids: list[str] = []
        self.cohort_index: dict[str, int] = {}
        self.anchors: dict[str, np.ndarray] = {}
        self.landmarks: dict[str, Landmark] = {}
        self.window = -1
        self.ptr = 0                                   # ring pointer into hist
        self.scale = 14.0
        self.spread_ewma: dict[str, float] = {}
        self.groups: list[str] = []
        self.expected_n = 0                     # the population the stream will show (sizes the world from the start)

    # ------------------------------------------------------------ bookkeeping
    def _grow(self, units: list[str], at: np.ndarray) -> None:
        """Add new units in one batch (positions `at`, shape (k, 2))."""
        k = len(units)
        if not k:
            return
        for u in units:
            self.index[u] = len(self.ids)
            self.ids.append(u)
        at = at.astype(np.float32)
        self.pos = np.concatenate([self.pos, at])
        self.hist = np.concatenate([self.hist, np.repeat(at[:, None, :], HISTORY, axis=1)])
        z = np.zeros(k, dtype=np.int32)
        self.last_active = np.concatenate([self.last_active, z])
        self.first_active = np.concatenate([self.first_active, np.full(k, -1, dtype=np.int32)])
        self.n_now = np.concatenate([self.n_now, z])
        self.msgs_now = np.concatenate([self.msgs_now, z])
        self.errs_now = np.concatenate([self.errs_now, z])
        self.cohort = np.concatenate([self.cohort, z])
        self.rate_ewma = np.concatenate([self.rate_ewma, np.zeros(k, dtype=np.float32)])
        self.rate_var = np.concatenate([self.rate_var, np.ones(k, dtype=np.float32)])

    def _cohort_idx(self, cid: str) -> int:
        if cid not in self.cohort_index:
            self.cohort_index[cid] = len(self.cohort_ids)
            self.cohort_ids.append(cid)
        return self.cohort_index[cid]

    def _spawn_point(self, unit: str, cid: str | None, group: str | None) -> np.ndarray:
        """New units walk in from their team's gate: just outside the anchor, along its radius."""
        a = self.anchors.get(cid) if cid else None
        if a is None:
            a = anchor_for(("other", "", group or "none"), self.scale)
        out = a / (np.linalg.norm(a) + 1e-6)
        jitter = np.array([h01(unit, "jx") - 0.5, h01(unit, "jy") - 0.5], dtype=np.float32) * 0.1 * self.scale
        if self.window < 10:                       # present from the start: begin at home, so the map reads at once
            return (a + jitter * 0.6).astype(np.float32)
        return (a + out * 0.18 * self.scale + jitter).astype(np.float32)   # later arrivals walk in from the gate

    # ------------------------------------------------------------ one window
    def step(self, w: WindowInput, landmark_kind: dict[str, str] | None = None) -> None:
        self.window = w.index
        n_units = max(len(self.ids), len(w.units), self.expected_n)
        self.scale = float(max(14.0, math.sqrt(max(1, n_units)) * 1.35))
        for cid, sig in w.cohort_sig.items():
            g = str(sig[2]) if len(sig) > 2 else ""
            if g and g not in ("none", "ungrouped") and g not in self.groups:
                self.groups.append(g)
                self.groups.sort()
        for cid, sig in w.cohort_sig.items():
            self.anchors[cid] = anchor_for(sig, self.scale, self.groups if len(self.groups) >= 2 else None)
        new = [u for u in w.units if u not in self.index]
        if new:
            self._grow(new, np.stack([self._spawn_point(u, w.cohort_of.get(u), w.units[u].get("group")) for u in new]))
        N = len(self.ids)
        if not N:
            return
        self.n_now[:] = 0
        self.msgs_now[:] = 0
        self.errs_now[:] = 0
        act = np.zeros(N, dtype=bool)
        for u, d in w.units.items():
            i = self.index[u]
            act[i] = True
            self.n_now[i] = d.get("n", 0)
            self.msgs_now[i] = d.get("msgs", 0)
            self.errs_now[i] = d.get("errs", 0)
            self.last_active[i] = w.index
            if self.first_active[i] < 0:
                self.first_active[i] = w.index
            cid = w.cohort_of.get(u)
            if cid:
                self.cohort[i] = self._cohort_idx(cid)
        # activity baseline (EWMA of events per window, per unit) for height
        x = self.n_now.astype(np.float32)
        delta = x - self.rate_ewma
        self.rate_ewma += 0.15 * delta
        self.rate_var = 0.85 * self.rate_var + 0.15 * delta * delta

        P = self.pos
        F = np.zeros_like(P)
        # anchor spring
        if self.cohort_ids:
            table = np.stack([self.anchors.get(cid, np.zeros(2, dtype=np.float32)) for cid in self.cohort_ids])
            anc = table[self.cohort]
        else:
            anc = P.copy()
        settling = np.where((self.first_active >= 0) & (w.index - self.first_active < 8), 3.0, 1.0).astype(np.float32)
        F += self.f["anchor"] * settling[:, None] * (anc - P) / self.scale
        # landmarks: create, then pull each active unit toward the places it touched (weighted mean)
        lm_pull = np.zeros_like(P)
        lm_w = np.zeros(N, dtype=np.float32)
        touch: dict[str, list[tuple[int, int]]] = {}
        pulls: list[tuple[int, str, float]] = []
        for u, d in w.units.items():
            i = self.index[u]
            for r, k in (d.get("res") or {}).items():
                touch.setdefault(r, []).append((i, k))
            for r, k in (d.get("pull") if d.get("pull") is not None else d.get("res") or {}).items():
                pulls.append((i, r, float(k)))
        for r, users in touch.items():
            if r not in self.landmarks:
                idx = np.array([i for i, _ in users])
                self.landmarks[r] = Landmark(key=r, kind=(landmark_kind or {}).get(r, "other"),
                                             pos=P[idx].mean(axis=0).astype(np.float32), created=w.index)
        for i, r, k in pulls:                      # pull: specificity-weighted (rare shared places pull hardest)
            lm = self.landmarks.get(r)
            if lm is not None and k > 0:
                lm_pull[i] += k * (lm.pos - P[i])
                lm_w[i] += k
        has = lm_w > 0
        spec_frac = np.array([min(1.0, w.units[u].get("pull_frac", 1.0)) if u in w.units else 0.0 for u in self.ids],
                             dtype=np.float32)
        F[has] += self.f["landmark"] * spec_frac[has, None] * (lm_pull[has] / lm_w[has, None]) / self.scale
        # interactions (derived edges): each kind normalised by its own degree, then weighted, so a few lineage
        # edges are not drowned by many co-touch edges
        KIND_W = {"co_touch": 0.6, "reply": 1.0, "lineage": 1.6, "shape": 1.2}
        by_kind: dict[str, list[tuple[int, int, float]]] = {}
        for a, b, x, kind in w.edges:
            ia, ib = self.index.get(a), self.index.get(b)
            if ia is not None and ib is not None and ia != ib:
                by_kind.setdefault(kind, []).append((ia, ib, x))
        for kind, es in by_kind.items():
            ia = np.array([e[0] for e in es])
            ib = np.array([e[1] for e in es])
            wt = np.array([e[2] for e in es], dtype=np.float32)
            pull = np.zeros_like(P)
            deg = np.zeros(N, dtype=np.float32)
            d = (P[ib] - P[ia]) * wt[:, None]
            np.add.at(pull, ia, d)
            np.add.at(pull, ib, -d)
            np.add.at(deg, ia, wt)
            np.add.at(deg, ib, wt)
            m = deg > 0
            F[m] += self.f["interact"] * KIND_W.get(kind, 1.0) * (pull[m] / deg[m, None]) / self.scale
        # similarity: toward the cohort centroid, scaled by how alike the unit is to its cohort
        if self.cohort_ids:
            C = len(self.cohort_ids)
            csum = np.zeros((C, 2), dtype=np.float32)
            ccount = np.zeros(C, dtype=np.float32)
            np.add.at(csum, self.cohort, P)
            np.add.at(ccount, self.cohort, 1)
            cent = csum / np.maximum(ccount, 1)[:, None]
            sim = np.array([w.similarity.get(u, 0.5) for u in self.ids], dtype=np.float32)
            F += self.f["similar"] * sim[:, None] * (cent[self.cohort] - P) / self.scale
        # short-range repulsion by grid hashing: push units apart from the mean of their cell
        cell = 0.9
        keys = np.floor(P / cell).astype(np.int64)
        kid = keys[:, 0] * 1_000_003 + keys[:, 1]
        uniq, inv, counts = np.unique(kid, return_inverse=True, return_counts=True)
        if (counts > 1).any():
            ms = np.zeros((len(uniq), 2), dtype=np.float32)
            np.add.at(ms, inv, P)
            mean = ms / counts[:, None]
            crowded = counts[inv] > 1
            away = P - mean[inv]
            # identical positions get a deterministic nudge
            zero = crowded & (np.abs(away).sum(axis=1) < 1e-4)
            if zero.any():
                ang = np.array([h01(self.ids[i], "nudge") * 2 * math.pi for i in np.where(zero)[0]])
                away[zero] = np.stack([np.cos(ang), np.sin(ang)], axis=1) * 0.05
            F[crowded] += self.f["repel"] * away[crowded] * 2.0 / cell
        # integrate: only active units move; bounded step
        F = np.nan_to_num(F, nan=0.0, posinf=0.0, neginf=0.0)
        step = F * 0.9 * self.scale * 0.12
        lim = self.f["max_step"] * self.scale
        norm = np.linalg.norm(step, axis=1)
        over = norm > lim
        step[over] *= (lim / norm[over])[:, None]
        step[~act] = 0
        self.pos = (P + step).astype(np.float32)
        # landmarks follow the units that use them (damped barycentre), and keep their baselines
        for r, users in touch.items():
            lm = self.landmarks[r]
            idx = np.array([i for i, _ in users])
            k = np.array([k for _, k in users], dtype=np.float32)
            home = (anc[idx] * k[:, None]).sum(axis=0) / max(1e-6, k.sum())   # between the groups that use it
            lm.pos = (0.85 * lm.pos + 0.15 * home).astype(np.float32)
        for r, lm in self.landmarks.items():
            users = touch.get(r, [])
            lm.events = int(sum(k for _, k in users))
            lm.distinct = len(users)
            # the usual crowd is a SLOW baseline, so a sustained new crowd stays a crowd for hours instead of
            # becoming "usual" within a few windows. Places present from the start learn it from their first windows;
            # a place that first appears mid-stream starts from zero (a new shared place is itself the signal).
            crowding_before = (lm.distinct + 1) / (lm.usual_distinct + 1)
            if lm.seen < 3 and lm.created <= 12:
                lm.usual_distinct = (lm.usual_distinct * lm.seen + lm.distinct) / (lm.seen + 1)
                lm.usual_events = (lm.usual_events * lm.seen + lm.events) / (lm.seen + 1)
            else:
                lm.usual_distinct = 0.97 * lm.usual_distinct + 0.03 * lm.distinct
                lm.usual_events = 0.97 * lm.usual_events + 0.03 * lm.events
            lm.crowd_now = crowding_before
            lm.seen += 1
        # landmarks repel each other a little so they do not stack
        if len(self.landmarks) > 1:
            L = list(self.landmarks.values())
            Q = np.stack([x.pos for x in L])
            d = Q[:, None, :] - Q[None, :, :]
            dist = np.maximum(np.linalg.norm(d, axis=2), 0.3)
            np.fill_diagonal(dist, np.inf)
            push = (d / dist[:, :, None] ** 2 * (dist < 2.5)[:, :, None]).sum(axis=1) * 0.15
            same = (np.linalg.norm(d, axis=2) < 1e-3) & ~np.eye(len(L), dtype=bool)
            if same.any():                                    # stacked landmarks: a deterministic nudge apart
                for i in np.where(same.any(axis=1))[0]:
                    a = h01(L[i].key, "lm") * 2 * math.pi
                    push[i] += np.array([math.cos(a), math.sin(a)]) * 0.4
            for lm, p in zip(L, push):
                lm.pos = (lm.pos + p).astype(np.float32)
        # history ring
        self.ptr = (self.ptr + 1) % HISTORY
        self.hist[:, self.ptr, :] = self.pos

    # ------------------------------------------------------------ spatial features
    def past(self, back: int) -> np.ndarray:
        return self.hist[:, (self.ptr - back) % HISTORY, :]

    def features(self, recent: int = 36) -> dict[str, np.ndarray]:
        """Per-unit spatial features for the current window (arrays aligned with self.ids)."""
        N = len(self.ids)
        if not N:
            return {k: np.zeros(0) for k in ("displacement", "drift", "isolation", "activity_z", "still_talking", "recent", "settled")}
        disp1 = np.linalg.norm(self.pos - self.past(1), axis=1) / self.scale
        drift = np.linalg.norm(self.pos - self.past(6), axis=1) / self.scale
        iso = np.zeros(N, dtype=np.float32)
        if self.cohort_ids:
            C = len(self.cohort_ids)
            csum = np.zeros((C, 2), dtype=np.float32)
            cnt = np.zeros(C, dtype=np.float32)
            np.add.at(csum, self.cohort, self.pos)
            np.add.at(cnt, self.cohort, 1)
            cent = csum / np.maximum(cnt, 1)[:, None]
            dist = np.linalg.norm(self.pos - cent[self.cohort], axis=1)
            mean = np.zeros(C, dtype=np.float32)
            np.add.at(mean, self.cohort, dist)
            mean = mean / np.maximum(cnt, 1)
            iso = dist / (mean[self.cohort] + 0.15 * self.scale / max(1.0, math.sqrt(N)) + 1e-6)
            iso[cnt[self.cohort] < 3] = 0
        az = (self.n_now - self.rate_ewma) / np.sqrt(self.rate_var + 1.0)
        still = (self.msgs_now > 0) & (np.linalg.norm(self.pos - self.past(3), axis=1) / self.scale < 0.004)
        recent_mask = self.last_active > self.window - recent
        settled = (self.first_active >= 0) & (self.window - self.first_active >= 8)   # walked in from the gate
        return {"displacement": disp1, "drift": drift, "isolation": iso.astype(np.float32),
                "activity_z": az.astype(np.float32), "still_talking": still, "recent": recent_mask, "settled": settled}

    def cohort_spread(self) -> dict[str, float]:
        out = {}
        for c, cid in enumerate(self.cohort_ids):
            m = self.cohort == c
            if m.sum() >= 4:
                out[cid] = float(np.linalg.norm(self.pos[m] - self.pos[m].mean(axis=0), axis=1).mean() / self.scale)
        return out

    def separation(self) -> float:
        """How well cohorts separate: mean inter-centroid distance / mean intra-cohort spread (higher = clearer)."""
        if len(self.cohort_ids) < 2 or not len(self.ids):
            return 0.0
        cents, spreads = [], []
        for c in range(len(self.cohort_ids)):
            m = self.cohort == c
            if m.sum() >= 3:
                p = self.pos[m]
                cents.append(p.mean(axis=0))
                spreads.append(np.linalg.norm(p - p.mean(axis=0), axis=1).mean())
        if len(cents) < 2:
            return 0.0
        Cn = np.stack(cents)
        d = np.linalg.norm(Cn[:, None] - Cn[None, :], axis=2)
        inter = d[np.triu_indices(len(Cn), 1)].mean()
        return float(inter / (np.mean(spreads) + 1e-6))


class NullModel:
    """The same layout on a shuffled copy of each window: rates and places are real, who-did-what is random.
    Keeps the recent distribution of each spatial feature; a real feature glows only above its null quantile."""

    def __init__(self, forces: dict[str, float] | None = None, keep: int = 24, every: int = 1):
        self.layout = Layout(forces, seed=11)
        self.samples: dict[str, deque] = {k: deque(maxlen=keep) for k in ("drift", "isolation", "crowding")}
        # per-window maxima: with thousands of units, a per-unit 95% threshold flags ~5% of them every window by
        # construction. Flags use the family-wise threshold: above what the shuffled swarm's *most extreme* unit
        # reaches in a typical window.
        self.maxima: dict[str, deque] = {k: deque(maxlen=keep) for k in ("drift", "isolation", "crowding")}
        self.every = every
        self.rng = np.random.default_rng(11)

    def step(self, w: WindowInput, landmark_kind: dict[str, str] | None = None) -> None:
        if w.index % self.every:
            return
        units = list(w.units)
        perm = list(units)
        self.rng.shuffle(perm)
        # each unit gets someone else's window: same activity and places in the population, random assignment
        shuffled = {u: w.units[v] for u, v in zip(units, perm)}
        to = dict(zip(perm, units))                  # the unit now carrying v's window
        sw = WindowInput(index=w.index, units=shuffled,
                         edges=[(to.get(a, a), to.get(b, b), x, k) for a, b, x, k in w.edges[:2000]],
                         cohort_of=w.cohort_of, cohort_sig=w.cohort_sig, similarity=w.similarity)
        self.layout.step(sw, landmark_kind)
        f = self.layout.features()
        rec = f.get("recent")
        if rec is not None:
            rec = rec & f["settled"]
        if rec is not None and rec.any():
            for k in ("drift", "isolation"):
                v = f[k][rec]
                self.samples[k].append(v)
                self.maxima[k].append(float(v.max()))
        cr = [lm.crowding for lm in self.layout.landmarks.values() if lm.seen > 3]
        if cr:
            self.samples["crowding"].append(np.array(cr, dtype=np.float32))
            self.maxima["crowding"].append(float(max(cr)))

    def quantile(self, feature: str, q: float) -> float | None:
        """Per-unit null quantile: how unusual one unit's value is."""
        xs = self.samples.get(feature)
        if not xs:
            return None
        allv = np.concatenate(list(xs))
        return float(np.quantile(allv, q)) if len(allv) >= 20 else None

    def family_threshold(self, feature: str, q: float) -> float | None:
        """Family-wise threshold: the q-quantile of the null's per-window maximum (corrects for many units)."""
        xs = self.maxima.get(feature)
        return float(np.quantile(np.array(xs), q)) if xs and len(xs) >= 4 else None
