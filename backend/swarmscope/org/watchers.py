"""Watchers: cheap, deterministic, incremental detectors that run every window.

They never call an LLM. Each emits Observations with evidence refs. The
Executive's AttentionPolicy reaches down to them: a focused scope gets a lower
threshold (more sensitive), and `tune` directives override parameters.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from swarmscope.core.models import (AttentionFocus, CapabilityProfile, EvidenceEvent, EvidenceRef, Observation,
                                    TimeWindow)
from swarmscope.store.store import Store

SELF_REPORT_ACTIONS = {"chat.message", "summary.generated", "memory.update", "narration"}
WORK_ACTIONS_PREFIX = ("session.", "computer.", "tool.", "resource.")


@dataclass
class WatchContext:
    store: Store
    window: TimeWindow
    events: list[EvidenceEvent]
    profile: CapabilityProfile
    pack: dict[str, Any]
    focuses: list[AttentionFocus]
    tunes: dict[str, dict[str, Any]]            # watcher id -> {param: value} or "<watcher>@<scope>" -> {...}
    window_len: timedelta

    def focus_weight(self, scope: str) -> float:
        w = 0.0
        for f in self.focuses:
            if f.scope == scope or (f.scope.endswith("*") and scope.startswith(f.scope[:-1])):
                w = max(w, f.weight)
        return w

    def sensitivity(self, scope: str) -> float:
        """Multiplier < 1 lowers thresholds for focused scopes."""
        return 1.0 / (1.0 + 0.6 * self.focus_weight(scope))

    def label(self, eid: str | None) -> str:
        e = self.store.entity(eid)
        return e.label if e else (eid or "unknown")


class Watcher:
    id = "watcher"
    title = "Watcher"
    requires: tuple[str, ...] = ()
    defaults: dict[str, Any] = {}

    def __init__(self) -> None:
        self.params = dict(self.defaults)
        self.state: dict[str, Any] = {}

    def p(self, ctx: WatchContext, key: str, scope: str | None = None) -> Any:
        if scope and f"{self.id}@{scope}" in ctx.tunes and key in ctx.tunes[f"{self.id}@{scope}"]:
            return ctx.tunes[f"{self.id}@{scope}"][key]
        return ctx.tunes.get(self.id, {}).get(key, self.params[key])

    def observe(self, ctx: WatchContext) -> list[Observation]:
        raise NotImplementedError

    def obs(self, ctx: WatchContext, kind: str, scope: str, title: str, severity: float,
            evidence: list[str], **metrics: Any) -> Observation:
        return Observation(watcher=self.id, kind=kind, window_end=ctx.window.end, scope=scope, title=title,
                           severity=round(max(0.0, min(1.0, severity)), 3), metrics=metrics,
                           evidence=[EvidenceRef(kind="event", id=e) for e in evidence[:25]])


def _fam(e: EvidenceEvent) -> str:
    return e.attributes.get("family") or "other"


# --------------------------------------------------------------------------- rate
class RateChange(Watcher):
    id, title = "rate_change", "Activity rate change"
    requires = ("timestamps",)
    defaults = {"z": 3.0, "min_events": 8, "alpha": 0.15, "warmup": 6}

    def observe(self, ctx: WatchContext) -> list[Observation]:
        out = []
        # pauses are not work: an agent choosing to wait never counts as a surge
        work = [e for e in ctx.events if _fam(e) != "idle"]
        counts: Counter[str] = Counter({"population": len(work)})
        for e in work:
            counts[f"family:{_fam(e)}"] += 1
        stats: dict[str, list[float]] = self.state.setdefault("stats", {})
        seen = self.state.setdefault("n", 0)
        for scope in set(counts) | set(stats):
            x = counts.get(scope, 0)
            mean, var = stats.get(scope, [float(x), 1.0])
            sd = max(math.sqrt(var), math.sqrt(max(mean, 1.0)), 1.0)
            z = (x - mean) / sd
            thr = self.p(ctx, "z", scope) * ctx.sensitivity(scope)
            if seen >= self.p(ctx, "warmup") and x >= self.p(ctx, "min_events") and z >= thr:
                ev = [e.id for e in ctx.events if scope == "population" or f"family:{_fam(e)}" == scope]
                name = "Population" if scope == "population" else scope.split(":", 1)[1]
                out.append(self.obs(ctx, "rate_surge", scope, f"{name} activity surged to {x} events ({z:.1f}σ)",
                                    0.25 + z / 12, ev, count=x, baseline=round(mean, 1), z=round(z, 2)))
            a = self.p(ctx, "alpha")
            nm = (1 - a) * mean + a * x
            stats[scope] = [nm, (1 - a) * (var + a * (x - mean) ** 2)]
        self.state["n"] = seen + 1
        return out


# --------------------------------------------------------------------------- convergence
class SharedResourceConvergence(Watcher):
    id, title = "shared_resource_convergence", "Shared-resource convergence"
    requires = ("timestamps", "resources")
    defaults = {"min_units": 3, "lookback_windows": 4, "cooldown_windows": 12, "unit": "actor",
                "exclude_families": ["chat", "summary", "goal", "computer"], "specific_only": True,
                "relative": 2.0, "alpha": 0.15, "warmup_windows": 0}
    # At scale a busy resource always has a crowd. A resource converges when its crowd is large in absolute terms
    # AND large against its own usual crowd (an EWMA of distinct units per lookback), so team files with eighty
    # regular users stay quiet while a file or host that suddenly draws many agents does not.

    def observe(self, ctx: WatchContext) -> list[Observation]:
        out = []
        recent: dict[str, deque] = self.state.setdefault("recent", defaultdict(deque))
        flagged: dict[str, int] = self.state.setdefault("flagged", {})
        lookback = ctx.window_len * self.p(ctx, "lookback_windows")
        unit_kind = self.p(ctx, "unit")
        excl = set(self.p(ctx, "exclude_families"))
        touched = set()
        for e in ctx.events:
            if not e.object or not e.actor or _fam(e) in excl or e.actor in ("operator", "summarizer"):
                continue
            if e.object.startswith("res:") and self.p(ctx, "specific_only"):
                continue          # a whole family ("docs") is not a shared resource
            if e.action.startswith("environment."):
                continue
            unit = e.actor
            if unit_kind == "group":
                ent = ctx.store.entity(e.actor)
                unit = (ent.group if ent and ent.group else e.actor)
            recent[e.object].append((e.ts, unit, e.id))
            touched.add(e.object)
        self.state["windows"] = self.state.get("windows", 0) + 1
        for obj in touched:
            q = recent[obj]
            while q and q[0][0] < ctx.window.end - lookback:
                q.popleft()
            units = {u for _, u, _ in q}
            scope = f"resource:{obj}"
            base = self.state.setdefault("base", {})
            usual = base.get(obj, 0.0)
            a_ = self.p(ctx, "alpha")
            base[obj] = (1 - a_) * usual + a_ * len(units)
            need = max(2, round(self.p(ctx, "min_units", scope) * ctx.sensitivity(scope)),
                       round(self.p(ctx, "relative") * usual * ctx.sensitivity(scope)) + 1)
            if self.state.get("windows", 0) < self.p(ctx, "warmup_windows"):
                continue                      # baselines first; a resource first seen after warm-up still fires
            last = flagged.get(obj, -10 ** 6)
            if len(units) >= need and ctx.window.index - last >= self.p(ctx, "cooldown_windows"):
                flagged[obj] = ctx.window.index
                names = sorted({ctx.label(u) for u in units})
                out.append(self.obs(ctx, "convergence", scope,
                                    f"{len(units)} {ctx.profile.entity_noun}s converged on {ctx.label(obj)}",
                                    0.3 + 0.12 * len(units), [i for _, _, i in q],
                                    units=len(units), members=names[:12], members_ids=sorted(units)[:40], resource=obj,
                                    family=(ctx.store.entity(obj).group if ctx.store.entity(obj) else None)))
        return out


# --------------------------------------------------------------------------- propagation
class ArtifactReuse(Watcher):
    """Block-level content reuse across actors, split into exposure-observed vs chronological-only."""
    id, title = "artifact_reuse", "Content reuse"
    requires = ("artifacts", "timestamps")
    defaults = {"exposure_window_h": 12, "max_blocks_per_event": 12, "min_reusers": 1}

    def observe(self, ctx: WatchContext) -> list[Observation]:
        occ: dict[str, list[tuple]] = self.state.setdefault("occ", defaultdict(list))   # block -> [(ts, actor, obj, ev, art)]
        out: list[Observation] = []
        cumulative: dict[str, dict[str, Any]] = self.state.setdefault("origins", {})
        per_origin: dict[str, dict[str, Any]] = {}
        # every actor's touches, in time order: (actor, object) -> [(ts, event id)]; exposure is checked in memory
        touches: dict[tuple, list] = self.state.setdefault("touches", defaultdict(list))
        objs: dict[str, set] = self.state.setdefault("occ_objs", {})
        for e in ctx.events:
            if not e.artifact or not e.actor or e.actor in ("summarizer",) or e.action.startswith("goal."):
                if e.actor and e.object:
                    touches[(e.actor, e.object)].append((e.ts, e.id))
                continue          # assignments from the operator are not agent-authored content
            art = ctx.store.artifact(e.artifact)
            if not art:
                continue
            for b in art.blocks[: self.p(ctx, "max_blocks_per_event")]:
                prev = occ[b]
                if prev and all(p[1] != e.actor for p in prev):
                    origin = prev[0]
                    g = cumulative.setdefault(origin[4], {"origin": origin, "reusers": {}, "events": [origin[3]]})
                    per_origin[origin[4]] = g
                    if e.actor not in g["reusers"]:                    # exposure only for a new reuser
                        exposed_via = self._exposure(ctx, e, prev, touches)
                        g["reusers"][e.actor] = {"event": e.id, "exposed_via": exposed_via, "block": b}
                        g["events"].append(e.id)
                seen_objs = objs.setdefault(b, set())
                if len(prev) < 400 or e.object not in seen_objs:            # a block repeated thousands of times
                    prev.append((e.ts, e.actor, e.object, e.id, e.artifact))  # keeps one entry per new place
                    seen_objs.add(e.object)
            if e.object:
                touches[(e.actor, e.object)].append((e.ts, e.id))
        for art_id, g in per_origin.items():
            origin = g["origin"]
            reusers = g["reusers"]
            exposed = [a for a, r in reusers.items() if r["exposed_via"]]
            chrono = [a for a in reusers if a not in exposed]
            scope = f"artifact:{art_id}"
            n = len(reusers)
            out.append(self.obs(
                ctx, "content_reuse", scope,
                f"Content first posted by {ctx.label(origin[1])} reused by {n} other {ctx.profile.entity_noun}"
                f"{'s' if n != 1 else ''} ({len(exposed)} with an observed exposure path)",
                0.3 + 0.1 * n + (0.1 if chrono else 0), g["events"],
                origin_actor=origin[1], origin_event=origin[3], origin_resource=origin[2],
                reusers=n, exposed=[ctx.label(a) for a in exposed], chronological_only=[ctx.label(a) for a in chrono],
                exposure={ctx.label(a): r["exposed_via"] for a, r in reusers.items()},
                reuse_events={ctx.label(a): r["event"] for a, r in reusers.items()}))
        return out

    def _exposure(self, ctx: WatchContext, e: EvidenceEvent, prev: list[tuple],
                  touches: dict[tuple, list] | None = None) -> str | None:
        """An exposure path exists if the reuser acted on a resource where the block appeared,
        between (appearance - window) and the reuse. Returns the event id proving it.
        With `touches` (every actor's (ts, id) per object, in time order) the check runs in memory; one appearance
        per object is enough, the earliest, since it gives the widest window."""
        import bisect
        span = timedelta(hours=self.p(ctx, "exposure_window_h"))
        visible = set(ctx.pack.get("exposure_families") or [])
        first: dict[str, Any] = {}
        for ts, actor, obj, ev, _ in prev:
            if obj and actor != e.actor and obj not in first:
                first[obj] = ts
        for obj, ts in first.items():
            if visible:
                ent = ctx.store.entity(obj)
                if not ent or (ent.group or ent.attributes.get("family")) not in visible:
                    continue      # content in a private channel (e.g. a session goal) is not visible to others
            if touches is not None:
                lst = touches.get((e.actor, obj)) or []
                i = bisect.bisect_left(lst, (ts - span, ""))
                if i < len(lst) and lst[i][0] < e.ts and lst[i][1] != e.id:
                    return lst[i][1]
                continue
            rows = ctx.store.sql("SELECT id FROM events WHERE actor = ? AND object = ? AND ts >= ? AND ts < ? "
                                 "AND id != ? ORDER BY ts LIMIT 1", [e.actor, obj, ts - span, e.ts, e.id])
            if rows:
                return rows[0]["id"]
        return None


# --------------------------------------------------------------------------- population
class NewActorBurst(Watcher):
    id, title = "new_actor_burst", "New actors"
    requires = ("identities",)
    defaults = {"min_new": 3, "warmup_windows": 6}

    def observe(self, ctx: WatchContext) -> list[Observation]:
        # the first windows of a record are everyone's first appearance; only count newcomers once the population
        # has been watched for a while (live mode seeds `seen` with earlier actors and sets warm directly)
        seen: set[str] = self.state.setdefault("seen", set())
        if ctx.events:
            self.state["active_windows"] = self.state.get("active_windows", 0) + 1
        new = []
        for e in ctx.events:
            if e.actor and e.actor not in seen:
                ent = ctx.store.entity(e.actor)
                if ent and ent.type in ("agent", "actor"):
                    new.append(e)
                seen.add(e.actor)
        if self.state.get("warm") and len(new) >= self.p(ctx, "min_new"):
            return [self.obs(ctx, "new_actors", "population", f"{len(new)} new {ctx.profile.entity_noun}s appeared",
                             0.3 + 0.05 * len(new), [e.id for e in new], count=len(new),
                             members=[ctx.label(e.actor) for e in new][:12])]
        if self.state.get("active_windows", 0) >= self.p(ctx, "warmup_windows"):
            self.state["warm"] = True
        return []


# --------------------------------------------------------------------------- environment
class EnvironmentResponse(Watcher):
    id, title = "environment_response", "Environment & operator events"
    requires = ("environment",)
    defaults = {"min_events": 1}

    def observe(self, ctx: WatchContext) -> list[Observation]:
        env_actions = set(ctx.pack.get("environment_actions") or [])
        groups: dict[str, list[EvidenceEvent]] = defaultdict(list)
        humans: list[EvidenceEvent] = []
        for e in ctx.events:
            if e.action in env_actions or e.action.startswith("environment."):
                groups[e.object or _fam(e)].append(e)
            elif e.action == "chat.human":
                humans.append(e)
        out = []
        for obj, evs in groups.items():
            if len(evs) < self.p(ctx, "min_events"):
                continue
            targets = sorted({ctx.label(e.attributes.get("target_agent")) for e in evs if e.attributes.get("target_agent")})
            kind = evs[0].action.split(".", 1)[-1].replace("_", " ")
            out.append(self.obs(ctx, "environment", f"resource:{obj}",
                                f"{len(evs)} {kind} event{'s' if len(evs) > 1 else ''} on {ctx.label(obj)}"
                                + (f" affecting {', '.join(targets[:4])}" if targets else ""),
                                0.35 + 0.12 * len(evs), [e.id for e in evs], count=len(evs), affected=targets,
                                action=evs[0].action,
                                members_ids=sorted({e.attributes.get("target_agent") for e in evs
                                                    if e.attributes.get("target_agent")})[:200]))
        if humans:
            rooms = Counter(e.attributes.get("room") or "chat" for e in humans)
            out.append(self.obs(ctx, "human_intervention", "humans",
                                f"{len(humans)} human message{'s' if len(humans) > 1 else ''} in "
                                f"{', '.join(rooms)}", 0.2 + 0.05 * len(humans), [e.id for e in humans],
                                count=len(humans)))
        return out


# --------------------------------------------------------------------------- integrity
class SelfReportMismatch(Watcher):
    """Narration vs action: agent reports of completed work without corroborating actions."""
    id, title = "self_report_mismatch", "Say vs do"
    requires = ("self_reports",)
    defaults = {"lookback_windows": 9, "min_lookback_minutes": 120}

    def observe(self, ctx: WatchContext) -> list[Observation]:
        claims = ctx.pack.get("self_report_claims") or {}
        pats = self.state.setdefault("pats", {k: re.compile(v["claim"], re.I) for k, v in claims.items()})
        ledger = self.state.setdefault("ledger", [])
        out = []
        # a report of finished work is checked against a fixed stretch of time, not a number of windows: in live mode a
        # window is 30 seconds, and nine of them is far too short to see the work behind a report
        look = max(ctx.window_len * self.p(ctx, "lookback_windows"), timedelta(minutes=self.p(ctx, "min_lookback_minutes")))
        for e in ctx.events:
            if e.action not in SELF_REPORT_ACTIONS or not e.artifact or not e.actor:
                continue
            text = ctx.store.artifact_text(e.artifact) or ""
            for name, pat in pats.items():
                if not pat.search(text):
                    continue
                corr = claims[name].get("corroborated_by") or {}
                fams = corr.get("families") or []
                who = None if e.action == "summary.generated" else e.actor
                q = ["SELECT id, action, family FROM events WHERE ts >= ? AND ts <= ?"]
                params: list[Any] = [e.ts - look, e.ts + ctx.window_len]
                if who:
                    q.append("AND actor = ?"); params.append(who)
                q.append("AND (" + " OR ".join(f"action LIKE '{p}%'" for p in WORK_ACTIONS_PREFIX) + ")")
                if fams:
                    q.append(f"AND family IN ({','.join('?' * len(fams))})"); params.extend(fams)
                rows = ctx.store.sql(" ".join(q) + " LIMIT 20", params)
                rec = {"event": e.id, "actor": e.actor, "claim": name, "ts": e.ts,
                       "corroborating": [r["id"] for r in rows], "third_party": who is None}
                ledger.append(rec)
                scope = f"agent:{e.actor}"
                if not rows:
                    who_l = "The village summary" if who is None else ctx.label(e.actor)
                    sev = 0.55 * (1 + ctx.focus_weight(scope) * 0.3) + (0.15 if who is None else 0.1)
                    out.append(self.obs(ctx, "say_do_mismatch", scope,
                                        f"{who_l} reports '{name.replace('_', ' ')}' with no corroborating "
                                        f"{'/'.join(fams) or 'work'} activity in the previous "
                                        f"{int(look.total_seconds() // 60)} min", sev, [e.id],
                                        claim=name, families=fams, actor=ctx.label(e.actor), third_party=who is None))
        return out


class FocusShift(Watcher):
    """An agent's dominant workstream changes to a family it rarely used."""
    id, title = "focus_shift", "Workstream shift"
    requires = ("identities", "resources")
    defaults = {"window_events": 6, "novelty": 0.15, "cooldown_windows": 18,
                "exclude_families": ["chat", "summary", "goal"]}

    def observe(self, ctx: WatchContext) -> list[Observation]:
        hist: dict[str, deque] = self.state.setdefault("hist", defaultdict(lambda: deque(maxlen=200)))
        last: dict[str, int] = self.state.setdefault("last", {})
        excl = set(self.p(ctx, "exclude_families"))
        out = []
        changed = set()
        for e in ctx.events:
            f = _fam(e)
            if e.actor and f not in excl and e.action.startswith(WORK_ACTIONS_PREFIX):
                hist[e.actor].append((f, e.id))
                changed.add(e.actor)
        k = self.p(ctx, "window_events")
        for a in changed:
            h = list(hist[a])
            if len(h) < 3 * k:
                continue
            recent, before = h[-k:], h[:-k]
            dom, n = Counter(f for f, _ in recent).most_common(1)[0]
            share_before = sum(1 for f, _ in before if f == dom) / len(before)
            if n >= k * 0.6 and share_before <= self.p(ctx, "novelty") and \
                    ctx.window.index - last.get(a, -10 ** 6) >= self.p(ctx, "cooldown_windows"):
                last[a] = ctx.window.index
                prev = Counter(f for f, _ in before).most_common(1)[0][0]
                out.append(self.obs(ctx, "focus_shift", f"agent:{a}",
                                    f"{ctx.label(a)} shifted from {prev} to {dom} work", 0.35 + 0.3 * (1 - share_before),
                                    [i for _, i in recent], actor=ctx.label(a), previous=prev, current=dom,
                                    share_before=round(share_before, 2)))
        return out


# --------------------------------------------------------------------------- identity
class AliasCollision(Watcher):
    """Distinct handles that normalize to the same stem. Only meaningful when identity is partial."""
    id, title = "alias_collision", "Identity aliasing"
    requires = ("identities",)
    defaults = {"min_aliases": 2}

    def observe(self, ctx: WatchContext) -> list[Observation]:
        cap = ctx.profile.capabilities.get("identities")
        if not cap or cap.quality == "strong":
            return []
        from swarmscope.sources.common import handle_stem
        stems: dict[str, set[str]] = self.state.setdefault("stems", defaultdict(set))
        reported: set[str] = self.state.setdefault("reported", set())
        out = []
        for e in ctx.events:
            ent = ctx.store.entity(e.actor)
            if ent:
                stems[handle_stem(ent.label)].add(ent.id)
        for stem, ids in stems.items():
            if len(ids) >= self.p(ctx, "min_aliases") and stem not in reported:
                reported.add(stem)
                out.append(self.obs(ctx, "alias", f"stem:{stem}", f"{len(ids)} handles share the stem '{stem}'",
                                    0.3, [], handles=[ctx.label(i) for i in ids][:10]))
        return out


# --------------------------------------------------------------------------- targets (identity-free)
class ResourceBurst(Watcher):
    """Per-resource bursts against the resource's own baseline, and methods new to a resource.

    Works without agent identities: the unit is the resource acted on (a target, a host, a file). A burst is a
    window whose count on one resource is far above that resource's EWMA; a new method is an event family seen on a
    resource for the first time after warm-up."""
    id, title = "resource_burst", "Resource bursts and new methods"
    requires = ("timestamps", "resources")
    defaults = {"z": 3.5, "min_events": 12, "alpha": 0.1, "warmup": 5, "new_method_min": 3,
                "exclude_families": ["chat", "summary", "goal", "narration", "control"]}

    def observe(self, ctx: WatchContext) -> list[Observation]:
        out = []
        excl = set(self.p(ctx, "exclude_families"))
        counts: Counter[str] = Counter()
        fams: dict[str, Counter] = defaultdict(Counter)
        ids: dict[str, list[str]] = defaultdict(list)
        for e in ctx.events:
            if not e.object or _fam(e) in excl:
                continue
            counts[e.object] += 1
            fams[e.object][_fam(e)] += 1
            if len(ids[e.object]) < 25:
                ids[e.object].append(e.id)
        stats: dict[str, list[float]] = self.state.setdefault("stats", {})
        seen_fams: dict[str, set] = self.state.setdefault("fams", {})
        windows: dict[str, int] = self.state.setdefault("windows", {})
        for obj in set(counts) | set(stats):
            x = counts.get(obj, 0)
            mean, var = stats.get(obj, [0.0, 1.0])
            n = windows.get(obj, 0)
            sd = max(math.sqrt(var), math.sqrt(max(mean, 1.0)), 1.0)
            z = (x - mean) / sd
            scope = f"resource:{obj}"
            thr = self.p(ctx, "z", scope) * ctx.sensitivity(scope)
            if n >= self.p(ctx, "warmup") and x >= self.p(ctx, "min_events") and z >= thr:
                out.append(self.obs(ctx, "burst", scope, f"Burst on {ctx.label(obj)}: {x} events against a usual "
                                                         f"{mean:.1f} ({z:.1f}σ)", 0.3 + min(0.5, z / 15), ids[obj],
                                    count=x, baseline=round(mean, 1), z=round(z, 2), resource=obj,
                                    families=dict(fams[obj].most_common(4))))
            if n >= self.p(ctx, "warmup"):
                for f, c in fams[obj].items():
                    if f not in seen_fams.setdefault(obj, set()) and c >= self.p(ctx, "new_method_min"):
                        out.append(self.obs(ctx, "new_method", scope, f"First '{f}' activity on {ctx.label(obj)} "
                                                                      f"({c} events)", 0.45, ids[obj],
                                            method=f, count=c, resource=obj))
            seen_fams.setdefault(obj, set()).update(fams[obj])
            a = self.p(ctx, "alpha")
            if obj in counts or obj in stats:
                stats[obj] = [(1 - a) * mean + a * x, (1 - a) * (var + a * (x - mean) ** 2)]
                windows[obj] = n + 1
        return out


class SpatialDrift(Watcher):
    """The World's spatial features, above their null model, as observations (docs/WORLD_PLAN.md §3.3, §5).

    An agent whose position moved further over the last six windows than 95% of agents in a shuffled swarm has
    changed how it behaves or whom it works with; a group whose spread jumps is coming apart. Positions use derived
    features only, so these are DERIVED observations with the agent's recent events as evidence. Sustained for two
    windows before reporting, so one noisy window does not page anyone."""
    id, title = "spatial_drift", "Spatial drift and splitting groups (the World)"
    requires = ("timestamps",)
    defaults = {"sustain": 2, "max_per_window": 6}
    engine = None                                  # set by the Engine (the World lives there)

    def observe(self, ctx: WatchContext) -> list[Observation]:
        eng = self.engine
        world = getattr(eng, "world", None) if eng else None
        if world is None or not world.flags:
            return []
        out = []
        streak = self.state.setdefault("streak", Counter())
        drift = set(world.flags.get("drift", []))
        for u in list(streak):
            if u not in drift:
                del streak[u]
        evs_by: dict[str, list[str]] = defaultdict(list)
        for e in ctx.events:
            if e.actor in drift:
                evs_by[e.actor].append(e.id)
        reported = self.state.setdefault("reported", {})
        for u in world.flags.get("drift", [])[:40]:
            streak[u] += 1
            last = reported.get(u, -99)
            if streak[u] >= int(self.p(ctx, "sustain")) and ctx.window.index - last >= 6 and evs_by.get(u):
                d = world.features_for(f"agent:{u}")
                sev = min(0.75, 0.35 + 2 * float(d.get("drift") or 0))
                out.append(self.obs(ctx, "spatial_drift", f"agent:{u}",
                                    f"{eng.label(u)} has moved away from where it usually works (behaviour or partners changed)",
                                    sev, evs_by[u][-12:], drift=d.get("drift"), drift_null=d.get("drift_null"),
                                    cohort=d.get("cohort")))
                reported[u] = ctx.window.index
            if len(out) >= int(self.p(ctx, "max_per_window")):
                break
        for cid in world.flags.get("split", [])[:3]:
            members = set(eng.scale.cohorts[cid].members) if cid in eng.scale.cohorts else set()
            ev = [e.id for e in ctx.events if e.actor in members][-12:]
            if ev and ctx.window.index - reported.get(cid, -99) >= 6:
                out.append(self.obs(ctx, "cohort_split", f"cohort:{cid}",
                                    f"The group {eng.scale.cohorts[cid].label} is coming apart (its spread jumped)",
                                    0.45, ev, cohort=cid))
                reported[cid] = ctx.window.index
        return out


# --------------------------------------------------------------------------- private reasoning
REASONING_CUES: dict[str, re.Pattern] = {
    # what an agent writes to itself before acting; each cue is a reason to read, never a verdict
    "working around a restriction": re.compile(r"\b(work ?around|bypass|circumvent|get around|sidestep)\b", re.I),
    "keeping something from people": re.compile(r"\b(without (telling|letting|informing) (anyone|them|the (humans?|team|others))|"
                                                r"hide (this|it|that) from|(don'?t|not) (mention|tell|disclose))\b", re.I),
    "credentials or sign-in": re.compile(r"\b(password|credentials?|2fa|captcha|log ?in as|sign ?in as)\b", re.I),
    "reporting work as done": re.compile(r"\b(pretend|claim (it|that) (is|was) (done|finished|complete)|"
                                         r"say (it|that) (is|was) (done|finished|complete)|mark (it|this) (as )?(done|complete))\b", re.I),
}


CUE_WEIGHT = {"keeping something from people": 0.62, "reporting work as done": 0.62,
              "working around a restriction": 0.4, "credentials or sign-in": 0.25}   # sign-ins are routine in the Village


class ReasoningCues(Watcher):
    """What agents think vs what they do: phrases in an agent's own private reasoning worth a person's look."""
    id, title = "reasoning_cues", "Private reasoning"
    requires = ("reasoning",)
    defaults = {"min_hits": 1, "cooldown_windows": 12}

    def observe(self, ctx: WatchContext) -> list[Observation]:
        last: dict[str, int] = self.state.setdefault("last", {})
        hits: dict[tuple[str, str], list[str]] = defaultdict(list)
        for e in ctx.events:
            art = e.attributes.get("reasoning")
            if not art or not e.actor:
                continue
            text = ctx.store.artifact_text(art) or ""
            for cue, rx in REASONING_CUES.items():
                if rx.search(text):
                    hits[(e.actor, cue)].append(e.id)
        out = []
        for (actor, cue), ids in hits.items():
            key = f"{actor}|{cue}"
            if len(ids) < self.p(ctx, "min_hits") or ctx.window.index - last.get(key, -999) < self.p(ctx, "cooldown_windows"):
                continue
            last[key] = ctx.window.index
            out.append(self.obs(ctx, "reasoning_cue", f"agent:{actor}",
                                f"{ctx.label(actor)}'s own reasoning mentions {cue} ({len(ids)} time{'s' if len(ids) != 1 else ''})",
                                CUE_WEIGHT.get(cue, 0.4) + 0.04 * min(4, len(ids) - 1), ids[:8], actor=ctx.label(actor),
                                cue=cue, count=len(ids)))
        return out


WATCHERS: dict[str, Callable[[], Watcher]] = {w.id: w for w in (ReasoningCues, ResourceBurst, SpatialDrift, 
    RateChange, SharedResourceConvergence, ArtifactReuse, NewActorBurst, EnvironmentResponse,
    SelfReportMismatch, FocusShift, AliasCollision)}
