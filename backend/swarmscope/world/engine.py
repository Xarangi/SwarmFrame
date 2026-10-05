"""WorldEngine: runs the layout every window and serves the World to the renderer, the analysts and the copilot."""
from __future__ import annotations

import base64
import math
from collections import Counter, defaultdict, deque
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import numpy as np

from swarmscope.scale.layer import tv
from swarmscope.world.features import FEATURES, availability, summary_lines
from swarmscope.world.layout import FAMILY_WHEEL, Layout, NullModel, WindowInput, h01
from swarmscope.world.scene import ASSETS, WHEN_BIT, place_props, plan, scene_legend, zone_regions
from swarmscope.world.spec import WorldError, WorldSpec, WorldStore, preset_world

if TYPE_CHECKING:
    from swarmscope.core.models import EvidenceEvent
    from swarmscope.engine import Engine

STATE_CODE = {s: i for i, s in enumerate(["idle", "active", "talking", "working", "blocked", "paused", "stopped"])}
SEV_CODE = {"WATCH": 1, "LOOK": 2, "ACT": 3}
MAX_LANDMARKS = 90
MAX_UNITS_SENT = 6000
MAX_CHOREO = 1500                  # units whose activity is choreographed per window (the busiest and the flagged)
MAX_CHOREO_DOTS = 400              # at dots scale only the nearest are ever drawn as pawns, so send fewer
LOOKBACK = 36                      # windows a unit stays on the map after its last event (then it fades out)


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def _msg(e: "EvidenceEvent") -> bool:
    a = e.action or ""
    return e.attributes.get("family") == "chat" or a.startswith(("chat.", "message"))


def _err(e: "EvidenceEvent") -> bool:
    a = e.action or ""
    return any(k in a for k in ("error", "denied", "fail", "blocked"))


class WorldEngine:
    def __init__(self, engine: "Engine", persist: bool = False):
        self.e = engine
        self.store = WorldStore(engine.profile.source, None if persist else False)
        self.layout = Layout()
        self.null = NullModel()
        self._table: dict[str, dict[str, str]] | None = None
        self._table_at = -99
        self.labels: dict[str, dict[str, Any]] = {}          # cohort -> {task, state, confidence, status, window, by}
        self.res_total: Counter = Counter()
        self.res_family: dict[str, str] = {}
        self.last: WindowInput | None = None
        self.beams: list[dict[str, Any]] = []
        self.lineage: list[tuple[str, str, bool]] = []
        self.flags: dict[str, list[str]] = {}
        self.ids_version = 0
        self._ids_len = 0
        self.spread_ewma: dict[str, float] = {}
        self.spread_seen: dict[str, int] = {}
        self.idf: dict[str, float] = {}
        self.sim_cache: dict[str, tuple[int, float]] = {}
        self._expected_at = -99
        self.errors: list[str] = []
        self.shape_users: dict[str, set] = defaultdict(set)             # template id -> every unit that posted it
        self.shape_recent: dict[str, Any] = defaultdict(lambda: deque(maxlen=40))
        # catalogs ("mix" layout): every unit's cumulative method mix and grades, over the whole record
        self.unit_mix: dict[str, Counter] = defaultdict(Counter)
        self.unit_grade: dict[str, Counter] = defaultdict(Counter)
        self.fam_total: Counter = Counter()

    # ------------------------------------------------------------ spec
    def table(self) -> dict[str, dict[str, str]]:
        idx = getattr(self.e.clock, "index", 0)
        if self._table is None or idx - self._table_at >= 12:
            self._table = availability(self.e)
            self._table_at = idx
        return self._table

    @property
    def spec(self) -> WorldSpec:
        return self.store.spec

    def ensure_spec(self) -> None:
        """Load the pack's preset, or compose a default from the availability table, once there is data. A saved
        World that is still exactly the pack's preset is refreshed when the preset file changes; edited ones stay."""
        if not self.store.empty:
            from swarmscope.world.spec import preset_hash
            cur = self.store.spec
            # composed before worlds had a scene and activity rules: nobody chose its absence, so bring it up to date
            sceneless = cur.by == "auto" and not cur.behaviours and not cur.environment.props
            if (cur.by == "pack" and cur.reasons.get("preset_hash") != preset_hash(self.e)) or sceneless:
                try:
                    from swarmscope.world.designer import compose_world
                    spec, by = preset_world(self.e), "pack"
                    if spec is None and sceneless:
                        spec, by = compose_world(self.e)[0], "auto"
                    if spec is not None:
                        spec.annotations = cur.annotations
                        self.store.replace(spec, by, "the source's preset world (updated)" if by == "pack"
                                           else "recomposed with a scene and activity rules")
                except WorldError as exc:
                    self.errors.append(f"world refresh: {exc}")
            return
        from swarmscope.world.designer import compose_world
        self._table = None
        try:
            spec = preset_world(self.e)
            by, why = ("pack", "the source's preset world") if spec else ("auto", "")
            if spec is None:
                spec, why = compose_world(self.e)
            self.store.replace(spec, by, why)
            self.store.history = []
        except WorldError as exc:
            self.errors.append(f"world spec: {exc}")
            try:
                spec, why = compose_world(self.e)
                self.store.replace(spec, "auto", why)
                self.store.history = []
            except WorldError as exc2:                   # nothing composable yet (no events): try again later
                self.errors.append(f"world compose: {exc2}")

    # ------------------------------------------------------------ one window
    def step(self, widx: int, events: list["EvidenceEvent"]) -> None:
        try:
            self._step(widx, events)
        except Exception as exc:                    # the World must never stop monitoring
            self.errors.append(f"world step: {type(exc).__name__}: {exc}")
            self.errors = self.errors[-10:]

    def _step(self, widx: int, events: list["EvidenceEvent"]) -> None:
        if self.store.empty and events:
            self.ensure_spec()
        if widx - self._expected_at >= 24 or not self.layout.expected_n:
            col = "actor" if self.e.scale.cfg.get("unit") == "actor" else "object"
            try:                                  # replays know their whole population; live streams grow into it
                n = int(self.e.store.scalar(f"SELECT count(DISTINCT {col}) FROM events WHERE {col} IS NOT NULL") or 0)
            except Exception:
                n = 0
            self.layout.expected_n = self.null.layout.expected_n = max(n, len(self.layout.ids))
            self._expected_at = widx
        spec = self.spec
        sc = self.e.scale
        lm_from = spec.landmarks_from
        units: dict[str, dict[str, Any]] = {}
        room_msgs: dict[str, list[tuple[Any, str]]] = defaultdict(list)
        shapes: dict[str, set] = defaultdict(set)              # template id -> units that posted it this window
        self.beams = []
        for e in events:
            fam = e.attributes.get("family") or "other"
            if e.action and e.action.startswith(("environment.", "control.")):
                target = e.attributes.get("target_agent")
                if target:
                    kind = "stop" if "stop" in e.action or "kill" in e.action else \
                        "pause" if "pause" in e.action or "deny" in e.action else "message"
                    self.beams.append({"unit": str(target), "kind": kind, "object": e.object})
                continue
            u = sc.unit_of(e)
            if u is None or fam in ("goal", "summary"):
                continue
            self.unit_mix[u][fam] += 1
            self.fam_total[fam] += 1
            g = e.attributes.get("confidence") or e.attributes.get("grade")
            if g:
                self.unit_grade[u][str(g)] += 1
            d = units.get(u)
            if d is None:
                p = sc.profiles.get(u)
                d = units[u] = {"n": 0, "res": Counter(), "msgs": 0, "errs": 0, "acts": set(),
                                "group": p.group if p else None, "fam": p.dominant("family") if p else fam}
            d["n"] += 1
            if e.action and len(d["acts"]) < 24:
                d["acts"].add(e.action)
            key = (e.object if lm_from == "object" else fam) if (e.object or lm_from == "family") else None
            if key and key != u:
                d["res"][key] += 1
                self.res_total[key] += 1
                self.res_family.setdefault(key, fam)
            if _msg(e):
                d["msgs"] += 1
                if e.object:
                    room_msgs[e.object].append((e.ts, u))
            if e.artifact:
                tpl = sc.miner.by_artifact.get(e.artifact)
                if tpl:
                    shapes[tpl].add(u)
            if _err(e):
                d["errs"] += 1
        # landmarks: the busiest places, plus any place shared this window by units from more than one group or
        # cohort (a low-volume place several unrelated units start using is exactly what a crowd forming looks like)
        sharers: dict[str, set] = defaultdict(set)
        for u, d in units.items():
            tag = d.get("group") or self.e.scale.unit_cohort.get(u) or u
            for r in d["res"]:
                sharers[r].add(tag)
        shared = {r for r, tags in sharers.items() if len(tags) >= 2 and sum(1 for d in units.values() if r in d["res"]) >= 3}
        keep = {k for k, _ in self.res_total.most_common(MAX_LANDMARKS)} | shared | set(self.layout.landmarks)
        if len(self.layout.landmarks) > 3 * MAX_LANDMARKS:              # evict places nobody has used for a long time
            top = {k for k, _ in self.res_total.most_common(MAX_LANDMARKS)}
            for k in [k for k, lm in self.layout.landmarks.items() if k not in top and lm.events == 0
                      and lm.seen > 36 and k not in shared][: len(self.layout.landmarks) - 2 * MAX_LANDMARKS]:
                self.layout.landmarks.pop(k, None)
            keep = top | shared | set(self.layout.landmarks)
        # specificity (inverse document frequency): a place everyone uses says nothing about who is alike, so its
        # pull and its co-touch edges fade; a place a few units share pulls hard. Uses this window's users and the
        # place's usual crowd, against the active population.
        users_now: Counter = Counter()
        for d in units.values():
            for r in d["res"]:
                users_now[r] += 1
        n_act = max(2, len(units))
        self.idf = {}
        for r in keep:
            lm = self.layout.landmarks.get(r)
            df = max(users_now.get(r, 0), lm.usual_distinct if lm else 0.0)
            self.idf[r] = max(0.0, math.log((n_act + 1) / (df + 1)) / math.log(n_act + 1))
        for d in units.values():
            d["res"] = Counter({k: v for k, v in d["res"].items() if k in keep})
            d["pull"] = {k: v * self.idf.get(k, 0.0) for k, v in d["res"].items() if self.idf.get(k, 0) > 0.05}
            raw = sum(d["res"].values())
            d["pull_frac"] = (sum(d["pull"].values()) / raw) if raw else 0.0     # how specific its places are
        # derived interaction edges
        edges: list[tuple[str, str, float, str]] = []
        inter = set(spec.metric.get("interactions") or [])
        if "co_touch" in inter:
            users: dict[str, list[tuple[int, str]]] = defaultdict(list)
            for u, d in units.items():
                for r, k in d["res"].items():
                    users[r].append((k, u))
            for r, us in users.items():
                if len(us) < 2 or self.idf.get(r, 0) < 0.3:         # common places are not interactions
                    continue
                us.sort(reverse=True)
                hub = us[0][1]
                for (k, u), (_, v) in zip(us[:40], us[1:41]):
                    edges.append((u, v, 0.5, "co_touch"))
                    if u != hub:
                        edges.append((hub, u, 0.25, "co_touch"))
        if "reply" in inter:
            for room, msgs in room_msgs.items():
                msgs.sort()
                for (t0, a), (t1, b) in zip(msgs, msgs[1:]):
                    if a != b and (t1 - t0) <= timedelta(seconds=60):
                        edges.append((b, a, 1.0, "reply"))
        if "shape" in inter and shapes:
            # a message shape (template id, never its words) spreading is a chain over time: each new poster of an
            # uncommon shape is pulled toward the most recent earlier posters (last 12 windows). Shapes that a large
            # share of all speakers use are chatter and pull nobody.
            for tpl, us in shapes.items():
                self.shape_users[tpl].update(us)
            speakers = len(set().union(*self.shape_users.values())) if self.shape_users else 1
            for tpl, us in shapes.items():
                if len(self.shape_users[tpl]) > max(6, 0.25 * speakers):
                    continue
                recent = self.shape_recent[tpl]
                prev = [u for wi, u in reversed(recent) if widx - wi <= 12]
                for u in sorted(us):
                    for v in [x for x in prev if x != u][:3]:
                        edges.append((u, v, 1.0, "shape"))
                for u in sorted(us):
                    recent.append((widx, u))
        self.lineage = []
        if "lineage" in inter:
            since = self.e.now() - self.e.window_len * 2           # watchers run after the layout: use the last windows
            for o in self.e.store.all("Observation"):
                if o.kind == "content_reuse" and o.window_end > since:
                    m = o.metrics or {}
                    origin = m.get("origin_actor")
                    for who in (m.get("reuse_events") or {}):
                        if origin and who != origin:
                            exposed = bool((m.get("exposure") or {}).get(who))
                            edges.append((origin, who, 1.5, "lineage"))
                            self.lineage.append((origin, who, exposed))
        # cohorts and similarity (derived)
        cohort_of = dict(sc.unit_cohort)
        cohort_sig = {cid: c.signature for cid, c in sc.cohorts.items()}
        span = int(sc.cfg.get("span_windows", 6))
        sim = {}
        for u in units:                                       # cached for 3 windows: it changes slowly
            cached = self.sim_cache.get(u)
            if cached and widx - cached[0] < 3:
                sim[u] = cached[1]
                continue
            p, cid = sc.profiles.get(u), cohort_of.get(u)
            c = sc.cohorts.get(cid) if cid else None
            sim[u] = 1 - tv(p.mix(sc.window_index, span), c.mix) if p and c and c.mix else 0.5
            self.sim_cache[u] = (widx, sim[u])
        w = WindowInput(index=widx, units=units, edges=edges, cohort_of=cohort_of, cohort_sig=cohort_sig, similarity=sim)
        forces = spec.metric.get("forces") or {}
        self.layout.f.update(forces)
        self.null.layout.f.update(forces)
        kinds = {k: self.res_family.get(k, "other") for k in keep}
        self.layout.step(w, kinds)
        if spec.metric.get("layout") == "mix":
            self._mix_layout()
        if spec.metric.get("places") == "districts":
            self._district_places()
        self.null.every = 1 if len(self.layout.ids) <= 2500 else 3
        self.null.step(w, kinds)
        self.last = w
        if len(self.layout.ids) != self._ids_len:
            self._ids_len = len(self.layout.ids)
            self.ids_version += 1
        self._glow()

    def _district_places(self) -> None:
        """Places stand still, in a district per kind (rooms together, documents together, the web at its own edge),
        so a village reads as a village and agents visibly walk out to what they work on. Only the places are fixed;
        where an agent stands is still measured (its own anchor, plus the pull of the places it used)."""
        import hashlib
        import math
        L = self.layout
        if not L.landmarks:
            return
        rules = self.spec.landmarks
        kind_of = {k: (self._archetype(k, lm.kind, rules)[1] or "place") for k, lm in L.landmarks.items()}
        kinds = sorted(set(kind_of.values()))
        width = 2 * math.pi / max(1, len(kinds))
        by_kind: dict[str, list[str]] = {}
        for k, kd in sorted(kind_of.items()):
            by_kind.setdefault(kd, []).append(k)
        for ki, kd in enumerate(kinds):
            keys = sorted(by_kind[kd], key=lambda k: hashlib.sha1(k.encode()).hexdigest())
            for j, k in enumerate(keys):
                n = len(keys)
                a = ki * width + width * (0.15 + 0.7 * (j + 0.5) / n)
                r = L.scale * (0.62 + 0.22 * ((j * 7) % 3) / 2)
                L.landmarks[k].pos = np.array([math.cos(a) * r, math.sin(a) * r], dtype=np.float32)

    def mix_families(self) -> list[str]:
        return [f for f, _ in self.fam_total.most_common(8)]

    def _mix_layout(self) -> None:
        """Catalog layout: each method class is a corner of the map, and each unit stands where its whole-record mix
        of methods puts it (all one method: at that corner; an even mix: between them). Deterministic and readable;
        units are then spread just enough that towers do not overlap. Method landmarks sit at their corners."""
        L = self.layout
        fams = self.mix_families()
        if not fams or not L.ids:
            return
        R = L.scale * 0.72
        k = len(fams)
        corner = {f: np.array([math.cos(-math.pi / 2 + 2 * math.pi * i / k), math.sin(-math.pi / 2 + 2 * math.pi * i / k)]) * R
                  for i, f in enumerate(fams)} if k > 1 else {fams[0]: np.zeros(2)}
        P = np.array(L.pos, dtype=np.float64)
        for u, i in L.index.items():
            m = self.unit_mix.get(u)
            tot = sum(c for f, c in (m or {}).items() if f in corner)
            if tot:
                P[i] = sum(corner[f] * c for f, c in m.items() if f in corner) / tot * 0.9
        n = len(P)
        for i, u in enumerate(L.ids):                                  # identical mixes: a deterministic nudge
            a = h01(u, "mix") * 2 * math.pi
            P[i] += np.array([math.cos(a), math.sin(a)]) * 0.05
        if n <= 900:
            gap = 1.25
            for _ in range(40):
                d = P[:, None, :] - P[None, :, :]
                dist = np.linalg.norm(d, axis=2)
                np.fill_diagonal(dist, np.inf)
                close = dist < gap
                if not close.any():
                    break
                push = (d / np.maximum(dist, 1e-3)[:, :, None] * ((gap - np.minimum(dist, gap)) * close)[:, :, None]).sum(axis=1)
                P += push * 0.5
        L.pos = P.astype(np.float32)
        L.hist[:, L.ptr, :] = L.pos
        for f in fams:
            lm = L.landmarks.get(f)
            if lm is not None:
                lm.pos = (corner[f] * 1.08).astype(np.float32)

    def _glow(self) -> None:
        """Spatial features above the null model's quantile: what may glow, and what feeds the analysts."""
        if self.spec.metric.get("layout") == "mix":
            # a catalog map is placed by method mix, not by forces, so the shuffled-swarm baseline does not apply
            self.flags = {k: [] for k in ("drift", "isolation", "crowding", "still_talking", "split")}
            return
        q = float(self.spec.null_model.get("quantile", 0.95))
        f = self.layout.features()
        if not len(self.layout.ids):
            self.flags = {}
            return
        rec = f["recent"] & f["settled"]                 # units still walking in from their gate are not drifting
        out: dict[str, list[str]] = {}
        qd, qi = self.null.family_threshold("drift", q), self.null.family_threshold("isolation", q)
        ids = self.layout.ids
        if qd is not None:
            hit = np.where(rec & (f["drift"] > max(qd, 0.02)))[0]
            out["drift"] = [ids[i] for i in hit[np.argsort(-f["drift"][hit])][:40]]
        if qi is not None:
            hit = np.where(rec & (f["isolation"] > max(qi, 1.5)))[0]
            out["isolation"] = [ids[i] for i in hit[np.argsort(-f["isolation"][hit])][:40]]
        qc = self.null.family_threshold("crowding", q)
        crowd = [(lm.crowding, k) for k, lm in self.layout.landmarks.items() if lm.seen > 3 and lm.distinct >= 3]
        out["crowding"] = [k for c, k in sorted(crowd, reverse=True) if qc is not None and c > max(qc, 1.5)][:20]
        out["still_talking"] = [ids[i] for i in np.where(f["still_talking"] & rec)[0][:40]]
        spread = self.layout.cohort_spread()
        split = []
        for cid, s in spread.items():
            prev = self.spread_ewma.get(cid)
            seen = self.spread_seen[cid] = self.spread_seen.get(cid, 0) + 1
            if prev is not None and seen > 8 and s > 1.8 * prev and s > 0.04:     # after a warm-up: a real jump
                split.append(cid)
            self.spread_ewma[cid] = s if prev is None else 0.85 * prev + 0.15 * s
        out["split"] = split[:10]
        self.flags = out

    # ------------------------------------------------------------ inferred labels (from the analysts)
    def ingest_labels(self, labels: list[dict[str, Any]], author: str) -> None:
        from swarmscope.core.models import Claim, ClaimStatus
        status = "inferred" if self.e.router.mode != "stub" else "derived"
        idx = getattr(self.e.clock, "index", 0)
        for x in labels[:24]:
            if not isinstance(x, dict) or not x.get("cohort") or not x.get("task"):
                continue
            cid = str(x["cohort"]).removeprefix("cohort:")
            conf = float(x.get("confidence", 0.6 if status == "inferred" else 0.9))
            self.labels[cid] = {"task": str(x["task"])[:90], "state": x.get("state"), "confidence": round(conf, 2),
                                "status": status, "window": idx, "by": author}
            if status == "inferred":
                self.e.store.put(Claim(statement=f"Group {cid} is probably {str(x['task'])[:90]}",
                                       status=ClaimStatus.INFERRED, confidence=conf, author=author,
                                       ts=self.e.now(), scope=f"cohort:{cid}"))

    # ------------------------------------------------------------ serialisation
    def _severities(self) -> tuple[dict[str, int], dict[str, str]]:
        """Unit rings and landmark severities from the Brief's findings (same words, same colours)."""
        unit_sev: dict[str, int] = {}
        res_sev: dict[str, str] = {}
        try:
            from swarmscope.dashboard.brief import brief_digest
            items = brief_digest(self.e)["items"]
        except Exception:
            return unit_sev, res_sev
        for it in items:
            for row in (it.get("member_rows") or [it]):
                kind, _, ident = str(row.get("scope", "")).partition(":")
                code = SEV_CODE.get(row.get("severity", "WATCH"), 1)
                if kind in ("agent", "actor"):
                    unit_sev[ident] = max(unit_sev.get(ident, 0), code)
                elif kind == "resource":
                    res_sev[ident] = row["severity"] if SEV_CODE.get(row["severity"], 0) > SEV_CODE.get(res_sev.get(ident, ""), 0) \
                        else res_sev.get(ident, row["severity"])
                    if self.e.scale.cfg.get("unit") == "object":
                        unit_sev[ident] = max(unit_sev.get(ident, 0), code)
        return unit_sev, res_sev

    def _states(self, ids: list[str]) -> np.ndarray:
        L = self.layout
        st = np.full(len(ids), STATE_CODE["idle"], dtype=np.uint8)
        idx = np.array([L.index[u] for u in ids], dtype=np.int64)
        n, m, er = L.n_now[idx], L.msgs_now[idx], L.errs_now[idx]
        st[n > 0] = STATE_CODE["active"]
        tool = self.e.profile.has("tool_calls")
        if tool:
            st[(n > 0) & (m == 0)] = STATE_CODE["working"]
        st[m > 0] = STATE_CODE["talking"]
        st[er >= 3] = STATE_CODE["blocked"]
        ctl = getattr(self.e, "control", None)
        if ctl is not None:
            pos = {u: i for i, u in enumerate(ids)}
            for a in ctl.agents.values():
                i = pos.get(a.get("id"))
                if i is None:
                    continue
                s = a.get("status", "")
                if s in ("paused", "waiting_approval"):
                    st[i] = STATE_CODE["paused"]
                elif s in ("killed", "stopped", "done"):
                    st[i] = STATE_CODE["stopped"]
        for b in self.beams:
            if b["kind"] == "stop" and b["unit"] in ids:
                st[ids.index(b["unit"])] = STATE_CODE["stopped"]
        return st

    def _fog(self) -> dict[str, float]:
        """Windows since an analyst read each cohort (or one of its members)."""
        org = getattr(self.e, "agent_org", None)
        wl = self.e.window_len.total_seconds() or 1
        now = self.e.now()
        last: dict[str, float] = {}
        if org is not None:
            unit_cohort = self.e.scale.unit_cohort
            for x in org.lookups[-4000:]:
                scope = str(x.get("scope", ""))
                kind, _, ident = scope.partition(":")
                cid = ident if kind == "cohort" else unit_cohort.get(ident) if kind in ("agent", "resource") else None
                if cid:
                    age = (now - x["ts"]).total_seconds() / wl
                    last[cid] = min(last.get(cid, 1e9), age)
        return last

    def state(self, include_ids: bool = True, labels: bool = False) -> dict[str, Any]:
        L, spec, sc = self.layout, self.spec, self.e.scale
        if not L.ids:
            return {"empty": True, "version": spec.version, "window": L.window,
                    "unavailable": summary_lines(self.table()), "spec": self.spec_public()}
        catalog = spec.metric.get("layout") == "mix"
        recent = np.arange(len(L.ids)) if catalog else np.where(L.last_active > L.window - LOOKBACK)[0]
        if len(recent) > MAX_UNITS_SENT:
            recent = recent[np.argsort(-L.last_active[recent])][:MAX_UNITS_SENT]
        recent = np.sort(recent)
        ids = [L.ids[i] for i in recent]
        f = L.features()
        unit_sev, res_sev = self._severities()
        states = self._states(ids)
        fams = list(FAMILY_WHEEL)
        fam_idx = np.zeros(len(ids), dtype=np.uint8)
        groups: list[str] = []
        group_idx = np.zeros(len(ids), dtype=np.uint16)
        for k, u in enumerate(ids):
            p = sc.profiles.get(u)
            fam = p.dominant("family") if p else "other"
            if fam not in fams:
                fams.append(fam)
            fam_idx[k] = fams.index(fam) if len(fams) < 255 else 255
            g = (p.group if p else None) or ""
            if g not in groups:
                groups.append(g)
            group_idx[k] = groups.index(g)
        h = np.clip(f["activity_z"][recent], -1.0, 3.0).astype(np.float32)
        ring = np.array([unit_sev.get(u, 0) for u in ids], dtype=np.uint8)
        quiet = (L.last_active[recent] < L.window).astype(np.uint8)
        flag = np.zeros(len(ids), dtype=np.uint8)
        pos_of = {u: k for k, u in enumerate(ids)}
        for bit, key in ((1, "drift"), (2, "isolation"), (4, "still_talking")):
            for u in self.flags.get(key, []):
                if u in pos_of:
                    flag[pos_of[u]] |= bit
        flag |= quiet * 16
        partial = set()
        try:
            partial = {r["id"] for r in self.e.store.sql("SELECT id FROM entities WHERE identity_confidence = 'partial'")}
        except Exception:
            pass
        alpha = np.array([140 if u in partial else 255 for u in ids], dtype=np.uint8)
        mix_fams: list[str] = []
        mix = np.zeros(0, dtype=np.uint8)
        if catalog:
            vol = np.array([sum(self.unit_mix.get(u, {}).values()) for u in ids], dtype=np.float64)
            top = math.log1p(max(1.0, float(vol.max()) if len(vol) else 1.0))
            h = (-1 + 4 * np.log1p(vol) / top).astype(np.float32)          # -1 (one report) to 3 (the most reported)
            def sig_share(u: str) -> float:
                g = self.unit_grade.get(u) or {}
                t = sum(g.values())
                return (g.get("significant", 0) / t) if t else 1.0
            alpha = np.array([255 if sig_share(u) >= 0.5 else 140 for u in ids], dtype=np.uint8)
            mix_fams = self.mix_families()[:4]
            rows = []
            for u in ids:
                m = self.unit_mix.get(u) or {}
                t = sum(m.get(f, 0) for f in mix_fams) or 1
                rows.append([round(255 * m.get(f, 0) / t) for f in mix_fams])
            mix = np.array(rows, dtype=np.uint8).reshape(-1)
        cohort_list = L.cohort_ids
        coh = L.cohort[recent].astype(np.uint16)
        trail_n = int(spec.metric.get("trail_windows", 12))
        disp = f["drift"][recent]
        flagged = {L.index[u] for k in ("drift", "isolation") for u in self.flags.get(k, []) if u in L.index}
        trail_units = list(dict.fromkeys([i for i in recent if i in flagged] + list(recent[np.argsort(-disp)][:30])))
        trails = {L.ids[i]: [[round(float(x), 2), round(float(z), 2)] for x, z in
                             (L.hist[i, (L.ptr - k) % L.hist.shape[1]] for k in range(min(trail_n, L.hist.shape[1]) - 1, -1, -1))]
                  for i in trail_units if f["drift"][i] > 0.01}
        # landmarks
        rules = spec.landmarks
        lms = []
        hot = set(self.flags.get("crowding", []))
        for key, lm in sorted(self.layout.landmarks.items(), key=lambda kv: -kv[1].usual_events - kv[1].events)[:MAX_LANDMARKS]:
            arch, lab, mdl = self._archetype(key, lm.kind, rules)
            team = Counter()
            if lm.distinct and self.last:
                for u, d in self.last.units.items():
                    if key in d["res"]:
                        team[d.get("group") or ""] += 1
            sev = res_sev.get(key) or ("LOOK" if key in hot else None)
            lms.append({"id": key, "label": self.e.label(key) if lm.kind != "method" else key, "arch": arch, "kind": lab, "model": mdl, "fam": lm.kind,
                        "x": round(float(lm.pos[0]), 2), "z": round(float(lm.pos[1]), 2), "events": lm.events,
                        "distinct": lm.distinct, "usual": round(lm.usual_distinct, 1), "crowding": round(lm.crowding, 2),
                        "sev": sev, "new": lm.created >= L.window - 2, "teams": [t for t, _ in team.most_common(3) if t]})
        # relations
        rel = []
        if self.last:
            seen = set()
            for a, b, wgt, kind in sorted(self.last.edges, key=lambda x: -x[2])[:400]:
                if a in pos_of and b in pos_of and (a, b, kind) not in seen and \
                        (kind != "co_touch" or "arc_touch" in spec.relations) and \
                        (kind != "reply" or "arc_reply" in spec.relations) and \
                        (kind != "lineage" or "arc_lineage" in spec.relations) and kind != "shape":
                    seen.add((a, b, kind))
                    rel.append({"t": kind, "a": pos_of[a], "b": pos_of[b], "w": wgt})
        exposed = {(a, b): x for a, b, x in self.lineage}
        for r in rel:
            if r["t"] == "lineage":
                r["exposed"] = exposed.get((ids[r["a"]], ids[r["b"]]), False)
        if "beam" in spec.relations:
            rel += [{"t": "beam", "a": pos_of[b["unit"]], "kind": b["kind"]} for b in self.beams if b["unit"] in pos_of]
        # cohorts, territories, fog
        fog = self._fog() if spec.coverage_fog else {}
        cohorts = []
        for c, cid in enumerate(cohort_list):
            m = np.where(L.cohort[recent] == c)[0]
            if not len(m) or cid not in sc.cohorts:
                continue
            pts = L.pos[recent[m]]
            lab = self.labels.get(cid)
            cohorts.append({"id": cid, "label": sc.cohorts[cid].label, "n": int(len(m)),
                            "x": round(float(pts[:, 0].mean()), 2), "z": round(float(pts[:, 1].mean()), 2),
                            "r": round(float(np.linalg.norm(pts - pts.mean(axis=0), axis=1).mean()) + 0.6, 2),
                            "task": lab["task"] if lab else None, "task_status": lab["status"] if lab else None,
                            "task_conf": lab["confidence"] if lab else None,
                            "stale": bool(lab and L.window - lab["window"] > 18),
                            "fog": round(min(30.0, fog.get(cid, 30.0)), 1) if spec.coverage_fog else 0,
                            "split": cid in self.flags.get("split", [])})
        territories = []
        if spec.territories.get("by") == "group":
            for gi, g in enumerate(groups):
                if not g:
                    continue
                m = np.where(group_idx == gi)[0]
                if len(m) >= 2:
                    pts = L.pos[recent[m]]
                    c0 = pts.mean(axis=0)
                    territories.append({"id": g, "x": round(float(c0[0]), 2), "z": round(float(c0[1]), 2),
                                        "r": round(min(float(np.percentile(np.linalg.norm(pts - c0, axis=1), 65)) + 0.8,
                                                       0.22 * L.scale), 2),
                                        "n": int(len(m))})
        q = float(spec.null_model.get("quantile", 0.95))
        zones = zone_regions(spec.environment, lms, territories)
        env = {"ground": spec.environment.ground, "zones": zones,
               "props": place_props(spec.environment, lms, territories, zones, L.scale)}
        acts = self._acts(ids, recent, states, ring, lms, f, pos_of)
        out = {
            "window": L.window, "now": str(self.e.now())[:19], "version": spec.version, "scale": round(L.scale, 2),
            "ids_version": self.ids_version, "n": len(ids),
            "units": {"x": b64(L.pos[recent, 0]), "z": b64(L.pos[recent, 1]), "h": b64(h), "fam": b64(fam_idx),
                      "group": b64(group_idx), "state": b64(states), "ring": b64(ring), "alpha": b64(alpha),
                      "cohort": b64(coh), "flag": b64(flag), **({"mix": b64(mix)} if catalog else {})},
            "mix_families": mix_fams, "catalog": catalog,
            "families": fams, "groups": groups, "cohort_ids": cohort_list,
            "landmarks": lms, "relations": rel, "cohorts": cohorts, "territories": territories, "trails": trails,
            "flags": {k: v[:20] for k, v in self.flags.items()},
            "null": {"quantile": q, "drift": self.null.family_threshold("drift", q),
                     "isolation": self.null.family_threshold("isolation", q),
                     "crowding": self.null.family_threshold("crowding", q)},
            "tier": self.recommended_tier(len(ids)),
            "env": env, "acts": acts,
        }
        if include_ids:
            out["ids"] = ids
            out["labels"] = {u: self.e.label(u) for u in ids} if (labels or len(ids) <= 600) else {}
        return out

    def _acts(self, ids: list[str], recent: np.ndarray, states: np.ndarray, ring: np.ndarray, lms: list[dict[str, Any]],
              f: dict[str, np.ndarray], pos_of: dict[str, int]) -> dict[str, Any]:
        """What each unit did this window, for the renderer to choreograph (world/scene.py): the conditions that hold
        (a bitmask over WHEN), the behaviour that applies (first match; 255 none), the place it goes to (an index into
        `landmarks`; -1 none) and its partner (an index into `ids`; -1 none). Bounded: one place and one partner per
        unit, and only the busiest MAX_CHOREO units (fewer at dots scale) are choreographed at all."""
        n = len(ids)
        L, spec = self.layout, self.spec
        when = np.zeros(n, dtype=np.uint16)
        beh = np.full(n, 255, dtype=np.uint8)
        lm_at = np.full(n, -1, dtype=np.int16)
        partner = np.full(n, -1, dtype=np.int32)
        if not n or not spec.behaviours:
            return {"when": b64(when), "beh": b64(beh), "lm": b64(lm_at), "partner": b64(partner), "n": 0}
        units = self.last.units if self.last else {}
        lm_idx = {lm["id"]: k for k, lm in enumerate(lms)}
        n_now = L.n_now[recent]
        az = f["activity_z"][recent]
        new = L.first_active[recent] >= L.window - 1
        reused = {who: origin for origin, who, _ in self.lineage}
        hit = {b["unit"]: b for b in self.beams}
        # most frequent partner this window, from the derived interaction edges
        pw: dict[str, Counter] = defaultdict(Counter)
        for a, b, wgt, _ in (self.last.edges if self.last else [])[:20000]:
            if a in pos_of and b in pos_of and a != b:
                pw[a][b] += wgt
                pw[b][a] += wgt
        cap = MAX_CHOREO_DOTS if self.recommended_tier(n) == "dots" else MAX_CHOREO
        order = np.lexsort((-n_now, -(ring > 0).astype(np.int8)))[:cap] if n > cap else range(n)
        for k in order:
            u = ids[k]
            d = units.get(u)
            bits = WHEN_BIT["active"] if n_now[k] > 0 else WHEN_BIT["idle"]
            cands = [r for r, _ in d["res"].most_common(6) if r in lm_idx] if d else []
            for cond, on in (("acted_on_landmark", bool(cands)), ("talked", bool(d and d["msgs"])), ("new", bool(new[k])),
                             ("stopped", states[k] == STATE_CODE["stopped"]), ("paused", states[k] == STATE_CODE["paused"]),
                             ("flagged", bool(ring[k])), ("surge", az[k] >= 2 and n_now[k] > 0),
                             ("environment_hit", u in hit), ("reused_content", u in reused)):
                if on:
                    bits |= WHEN_BIT[cond]
            when[k] = bits
            if u in reused and reused[u] in pos_of:
                partner[k] = pos_of[reused[u]]
            elif pw.get(u):
                partner[k] = pos_of[pw[u].most_common(1)[0][0]]
            for bi, b in enumerate(spec.behaviours):
                if not bits & WHEN_BIT[b.when]:
                    continue
                place = cands[0] if cands else None
                fl = b.filter
                if fl.get("family"):
                    fams = fl["family"] if isinstance(fl["family"], list) else [fl["family"]]
                    place = next((r for r in cands if lms[lm_idx[r]].get("fam") in fams), None)
                    if place is None:
                        continue
                if fl.get("action") and not any(str(a).startswith(str(fl["action"])) for a in (d["acts"] if d else ())):
                    continue
                if b.when == "environment_hit":
                    if fl.get("kind") and hit[u]["kind"] != fl["kind"]:
                        continue
                    if hit[u].get("object") in lm_idx:          # scatter from the page that was hit
                        place = hit[u]["object"]
                beh[k] = bi
                if place is not None:
                    lm_at[k] = lm_idx[place]
                break
        return {"when": b64(when), "beh": b64(beh), "lm": b64(lm_at), "partner": b64(partner),
                "n": int((beh != 255).sum())}

    def _archetype(self, key: str, kind: str, rules) -> tuple[str, str, str | None]:
        for r in rules:
            m = r.match
            if ("family" in m and m["family"] == kind) or ("prefix" in m and str(key).startswith(str(m["prefix"]))) \
                    or (m.get("kind") == "other"):
                return r.archetype, r.label, r.model
        return ("road", "method", None) if self.spec.landmarks_from == "family" else ("kiosk", "place", None)

    def recommended_tier(self, n: int) -> str:
        if self.spec.unit.get("model") == "plinth":
            return "plinths"
        t = self.spec.render.get("tier", "auto")
        if t != "auto":
            return t
        return "characters" if n <= int(self.spec.render.get("max_characters", 80)) else "pawns" if n <= 2000 else "dots"

    def spec_public(self) -> dict[str, Any]:
        s = self.spec.model_dump()
        s["unavailable"] = summary_lines(s.get("availability") or self.table())
        s["features"] = FEATURES
        # the renderer plays each behaviour's step list and compiles the library props it places (muted, instanced)
        for b, d in zip(self.spec.behaviours, s["behaviours"]):
            d["plan"] = plan(b)
        s["asset_defs"] = [ASSETS[a].model_dump() for a in dict.fromkeys(p.asset for p in self.spec.environment.props)
                           if a in ASSETS]
        s["scene_legend"] = scene_legend(self.spec)
        return s

    # ------------------------------------------------------------ details and tools
    def unit_detail(self, unit: str) -> dict[str, Any] | None:
        L = self.layout
        i = L.index.get(unit)
        if i is None:
            return None
        f = L.features()
        sc = self.e.scale
        p = sc.profiles.get(unit)
        cid = sc.unit_cohort.get(unit)
        d = np.linalg.norm(L.pos - L.pos[i], axis=1)
        d[i] = np.inf
        near = [L.ids[j] for j in np.argsort(d)[:6] if np.isfinite(d[j])]
        trail = [[round(float(x), 2), round(float(z), 2)] for x, z in
                 (L.hist[i, (L.ptr - k) % L.hist.shape[1]] for k in range(L.hist.shape[1] - 1, -1, -1))]
        q = float(self.spec.null_model.get("quantile", 0.95))
        qd, qi = self.null.family_threshold("drift", q), self.null.family_threshold("isolation", q)
        state = int(self._states([unit])[0])
        return {"unit": unit, "label": self.e.label(unit), "cohort": cid,
                "cohort_label": sc.cohorts[cid].label if cid in sc.cohorts else None,
                "task": self.labels.get(cid), "state": list(STATE_CODE)[state],
                "state_how": "control plane" if getattr(self.e, "control", None) else "derived from its events",
                "activity_now": int(L.n_now[i]), "activity_usual": round(float(L.rate_ewma[i]), 1),
                "activity_z": round(float(f["activity_z"][i]), 2),
                "drift": round(float(f["drift"][i]), 4), "drift_null": qd,
                "isolation": round(float(f["isolation"][i]), 2), "isolation_null": qi,
                "x": round(float(L.pos[i, 0]), 2), "z": round(float(L.pos[i, 1]), 2), "trail": trail,
                "nearest": [{"unit": u, "label": self.e.label(u)} for u in near],
                "places": [{"id": r, "label": self.e.label(r), "events": n} for r, n in (p.res.most_common(5) if p else [])],
                "flags": [k for k, v in self.flags.items() if unit in v]}

    def features_for(self, scope: str) -> dict[str, Any]:
        """For analysts and the copilot: the spatial reading of an agent, cohort or resource, with its null baseline."""
        kind, _, ident = scope.partition(":")
        q = float(self.spec.null_model.get("quantile", 0.95))
        base = {"null_quantile": q, "status": "derived", "note": "positions use derived features only; a feature "
                "matters when it exceeds its null value (a shuffled swarm)"}
        if kind in ("agent", "actor", "unit") or (kind == "resource" and ident in self.layout.index):
            d = self.unit_detail(ident)
            if d:
                d.pop("trail", None)
                recent = self.e.store.events(self.e.now() - self.e.window_len * 6, self.e.now(), limit=4000)
                d["evidence"] = [ev.id for ev in recent if ev.actor == ident or ev.object == ident][-8:]
                return {**base, **d}
        if kind == "resource":
            lm = self.layout.landmarks.get(ident)
            if lm:
                return {**base, "resource": ident, "label": self.e.label(ident), "events_now": lm.events,
                        "distinct_now": lm.distinct, "distinct_usual": round(lm.usual_distinct, 2),
                        "crowding": round(lm.crowding, 2), "crowding_null": self.null.family_threshold("crowding", q),
                        "above_null": ident in self.flags.get("crowding", [])}
        if kind == "cohort":
            spread = self.layout.cohort_spread().get(ident)
            return {**base, "cohort": ident, "spread": spread, "usual_spread": self.spread_ewma.get(ident),
                    "splitting": ident in self.flags.get("split", []), "label": self.labels.get(ident),
                    "drifting_members": [u for u in self.flags.get("drift", []) if self.e.scale.unit_cohort.get(u) == ident][:10]}
        return {**base, "error": f"nothing in the World for {scope}"}

    def preview(self) -> dict[str, Any]:
        """What the designer sees before committing: does the current metric separate anything beyond chance?"""
        L, N = self.layout, self.null.layout
        q = float(self.spec.null_model.get("quantile", 0.95))
        real, null = L.separation(), N.separation()
        f = L.features()
        qd = self.null.family_threshold("drift", q)
        moving = int(((f["drift"] > qd) & f["recent"]).sum()) if qd is not None and len(L.ids) else 0
        cr = [lm.crowding for lm in L.landmarks.values() if lm.seen > 3]
        n = int(f["recent"].sum()) if len(L.ids) else 0
        return {"units_on_map": n, "landmarks": len(L.landmarks), "cohorts": len(L.cohort_ids),
                "separation": round(real, 2), "separation_null": round(null, 2),
                "separates_beyond_chance": real > 1.15 * null if null else real > 1.5,
                "units_moving_beyond_null": moving, "crowding_max": round(max(cr), 2) if cr else None,
                "crowding_null": self.null.family_threshold("crowding", q), "recommended_tier": self.recommended_tier(n),
                "flags": {k: len(v) for k, v in self.flags.items()}, "window": L.window,
                "note": "separation = inter-cohort distance / intra-cohort spread; the null is the same layout on a "
                        "shuffled swarm. Forces you change apply from the next window."}

    def selection_scope(self, units: list[str]) -> dict[str, Any]:
        """A lasso selection, summarised for the copilot (structure only)."""
        sc = self.e.scale
        units = [u for u in units if u in self.layout.index][:400]
        coh = Counter(sc.unit_cohort.get(u) for u in units if sc.unit_cohort.get(u))
        groups = Counter((sc.profiles[u].group if u in sc.profiles else None) or "none" for u in units)
        fams = Counter(sc.profiles[u].dominant("family") for u in units if u in sc.profiles)
        places = Counter()
        for u in units:
            if u in sc.profiles:
                places.update(dict(sc.profiles[u].res.most_common(3)))
        return {"units": len(units), "sample": [self.e.label(u) for u in units[:12]],
                "cohorts": [{"id": c, "label": sc.cohorts[c].label if c in sc.cohorts else c, "n": n} for c, n in coh.most_common(6)],
                "groups": dict(groups.most_common(6)), "workstreams": dict(fams.most_common(6)),
                "places": [{"id": r, "label": self.e.label(r), "events": n} for r, n in places.most_common(6)],
                "flags": {k: len(set(v) & set(units)) for k, v in self.flags.items() if set(v) & set(units)}}

