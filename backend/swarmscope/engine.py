"""The engine: one monitoring session over one source with one organization.

Per window:  events -> watchers -> monitors (bottom-up reports)
             -> Executive on cadence or escalation -> directives, questions (top-down)
             -> investigations (async) -> results feed the next Executive step
Everything is persisted in the store and broadcast to the UI as a compact snapshot.
"""
from __future__ import annotations

import asyncio
import copy
import random
import time
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable

from swarmscope.clock import ReplayClock, WallClock
from swarmscope.config import llm_label, deep_merge, get_dotted, load_org, set_dotted
from swarmscope.core.models import (AttentionRecord, BriefingEntry, Claim, ContextLedger, Directive, ExecutiveState,
                                    Investigation, LedgerEntry, MonitorReport, Observation, OperationalState, Question)
from swarmscope.ingest.adapter import Batch
from swarmscope.ingest.packs import SourcePack, load_pack
from swarmscope.llm.evidence_tools import EvidenceTools
from swarmscope.llm.router import LLMRouter
from swarmscope.org.directives import AttentionPolicy, DirectiveApplier
from swarmscope.org.executive import ExecInput, ExecutiveRole
from swarmscope.org.investigations import InvestigationManager
from swarmscope.org.monitor import Monitor, load_manifests
from swarmscope.org.risk import LEVEL_ORDER, at_least
from swarmscope.org.watchers import WATCHERS, WatchContext
from swarmscope.store.store import Store
from swarmscope.strategies.base import MonitorContext


class Engine:
    def __init__(self, source: str = "ai_village", org: str | dict[str, Any] = "default", path: str | None = None,
                 overrides: dict[str, Any] | None = None, slice_override: dict[str, Any] | None = None,
                 db_path: str | None = None, persist_dashboard: bool = False, live_stretch: bool = False):
        self.pack: SourcePack = load_pack(source)
        # "Watch live": replay the source's busiest real stretch at real time, in short windows, after a fast warm-up
        self.live_replay: dict[str, Any] | None = None
        ls = self.pack.source.get("live_stretch") if live_stretch else None
        if ls:
            from swarmscope.ingest.adapter import parse_ts as _pt
            self.live_replay = {"at": _pt(ls["start"]), "end": _pt(ls["end"]), "label": ls.get("label", ""),
                                "window_s": int(ls.get("window_seconds", 30)), "warmup_min": int(ls.get("warmup_minutes", 120)),
                                "on": False}
        self.org = load_org(org) if isinstance(org, str) else copy.deepcopy(org)
        pack_mon = self.pack.monitors or {}
        if pack_mon.get("enabled") and not (overrides or {}).get("monitors"):
            self.org["monitors"] = [m for m in pack_mon["enabled"] if m in self.org.get("monitors", pack_mon["enabled"])] \
                if self.org.get("id") not in (None, "default") else list(pack_mon["enabled"])
        for k, v in (pack_mon.get("overrides") or {}).items():
            self.org.setdefault("overrides", {}).setdefault(k, v)
        for k, v in (overrides or {}).items():
            set_dotted(self.org, k, v) if "." in k else self.org.__setitem__(k, v)
        self.profile = self.pack.capabilities
        self.store = Store(db_path)
        self.subscribers: list[asyncio.Queue] = []
        self.task: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self.window_len = timedelta(minutes=int(self.pack.source.get("window_minutes", 10)))
        if self.live_replay:
            self.window_len = timedelta(seconds=self.live_replay["window_s"])
        self.ground_truth: list[dict[str, Any]] = []
        self.meta: dict[str, Any] = {}
        self.started_wall = time.time()
        from swarmscope.scale.layer import ScaleLayer
        from swarmscope.scale.triage import Triage
        scfg = {**(self.pack.source.get("scale") or {}), **(self.org.get("scale") or {})}
        self.scale = ScaleLayer({k: v for k, v in scfg.items() if k not in ("triage",)}, label=self.label,
                                entity=self.store.entity, identities=self.profile.has("identities"))
        self.triage = Triage(scfg.get("triage") or {})

        # ---- load evidence
        if self.profile.live:
            self.clock = WallClock(timedelta(seconds=int(self.pack.source.get("window_seconds", 5))))
            self.window_len = self.clock.window
        else:
            adapter = self.pack.adapter()
            batch: Batch = _cached_load(self.pack, adapter, path, slice_override)
            self.meta = batch.meta
            self._ingest(batch)
            start, end = batch.meta.get("slice_start"), batch.meta.get("slice_end")
            lo, hi = self.store.time_range()
            start = max(start or lo, lo) if lo else start
            end = min(end or hi, hi + self.window_len) if hi else end
            ts = [e.ts for e in batch.events]
            self.clock = ReplayClock(start - self.window_len, end, self.window_len, speed=2.0,
                                     nonempty=ts if self.pack.source.get("skip_empty_windows") or self.live_replay else None)
            if self.live_replay and not (self.clock.start <= self.live_replay["at"] < self.clock.end):
                self.live_replay = None                     # the stretch is not in the loaded period: a normal replay
                self.window_len = timedelta(minutes=int(self.pack.source.get("window_minutes", 10)))
                self.clock = ReplayClock(start - self.window_len, end, self.window_len, speed=2.0,
                                         nonempty=ts if self.pack.source.get("skip_empty_windows") else None)
            if self.live_replay:
                lr = self.live_replay
                warm = lr["at"] - timedelta(minutes=lr["warmup_min"])
                self.clock.cursor = max(self.clock.start, warm)
                self.clock.start = self.clock.cursor
                self.clock.end = min(self.clock.end, lr["end"]) if lr["end"] else self.clock.end
                self.clock.set_time_scale(1e12)            # catch up to the live point as fast as the analysts allow
                # (the top bar's live badge shows the catch-up; the clock's own catching_up is for jumps)
            self.ground_truth = list(batch.meta.get("ground_truth") or [])
            gt = (batch.meta.get("root") or "")
            try:
                import json
                from pathlib import Path
                p = Path(gt) / "ground_truth.json"
                if p.exists():
                    self.ground_truth = json.loads(p.read_text())["incidents"]
            except Exception:
                pass

        # ---- organization
        self.manifests = load_manifests()
        self.watchers = {wid: cls() for wid, cls in WATCHERS.items()}
        if self.live_replay and "new_actor_burst" in self.watchers:
            # a live replay starts mid-record: everyone who acted before the warm-up already existed, so not "new"
            try:
                before = self.store.sql("SELECT DISTINCT actor FROM events WHERE ts < ? AND actor IS NOT NULL",
                                        [self.clock.cursor])
                st = self.watchers["new_actor_burst"].state
                st["seen"] = {r["actor"] for r in before}
                st["warm"] = bool(before)
            except Exception:
                pass
        self.monitors: dict[str, Monitor] = {}
        self._build_monitors()
        self.policy = AttentionPolicy()
        self.router = LLMRouter(self.org, self._record_attention, self.now)
        self.executive = ExecutiveRole(self.router, self.org.get("executive", {}).get("strategy", "structured_state"))
        self.exec_state = ExecutiveState(strategy=self.executive.strategy)
        self.dismissed: set[str] = set()
        from swarmscope.org.cases import DEFAULT_AUTHORITY
        self.authority: dict[str, Any] = dict(DEFAULT_AUTHORITY, alerts_used=0)   # the cases ledger's budget, per executive cycle
        self.escalation_pending = False                                         # an agent escalated between cycles: run the executive now
        self.ledger = ContextLedger()
        self.investigations = InvestigationManager(self.store, self.router, self.org, self.tools, self.label,
                                                   self._notify, self.now, self.window_len)
        self.applier = DirectiveApplier(self.org, self.policy, window_len=self.window_len,
                                        set_monitor=self.set_monitor, tunables=self._tunables,
                                        open_question=self._open_question)
        self.proposals: list[Question] = []
        from swarmscope.agents.runtime import AgentOrg
        from swarmscope.agents.selector import choose_topology
        self.team_choice = choose_topology(self, explicit=(overrides or {}).get("agents.topology"))
        self.agent_org = AgentOrg(self, self.team_choice["topology"])
        from swarmscope.agents.proposals import Approvals
        self.approvals = Approvals(self)
        from swarmscope.agents.delegation import DelegationLog
        self.delegations = DelegationLog(self)
        self.executive.agent_org = self.agent_org
        self.pending_reports: list[MonitorReport] = []
        self.human_inputs: list[Directive] = []
        self.last_exec_index = -10 ** 6
        self.windows_processed = 0
        self.inspected: set[str] = set()
        self.events_seen = 0
        self.exec_meta: dict[str, Any] = {}
        self.attention_total = Counter()
        self.control = None
        from swarmscope.dashboard.spec import DashboardStore
        self.dashboard = DashboardStore(self.profile.source, None if persist_dashboard else False)
        self.stream = None
        if self.pack.source.get("infer_capabilities"):
            from swarmscope.sources.generic_stream import StreamIngest
            self.stream = StreamIngest(self)
        if not self.dashboard.empty and self.dashboard.spec.by == "pack":
            try:                                          # an unedited pack default follows its pack file
                from swarmscope.dashboard.spec import builtin_spec, pack_hash
                if self.dashboard.spec.pack_hash != pack_hash(self):
                    spec = builtin_spec(self)
                    if spec is not None:
                        self.dashboard.replace(spec, "pack", "the source's default views (updated)")
            except Exception as exc:
                self.router.errors.append(f"dashboard: {type(exc).__name__}: {exc}")
        if self.dashboard.empty:
            try:
                from swarmscope.dashboard.spec import builtin_spec, default_spec
                spec, by, why = builtin_spec(self), "pack", "the source's default views"
                if spec is None and self.stream:
                    spec, by, why = default_spec(self), "default", "an empty Brief until the stream is composed"
                elif spec is None:
                    from swarmscope.dashboard.designer import auto_design
                    (spec, why), by = auto_design(self), "auto"
                self.dashboard.replace(spec, by, why)
                self.dashboard.history = []
            except Exception as exc:                      # a dashboard problem must never stop a session
                self.router.errors.append(f"dashboard: {type(exc).__name__}: {exc}")
        if self.profile.live and self.pack.source.get("control", True):
            from swarmscope.control.plane import ControlPlane
            self.control = ControlPlane(self)
        # ---- the World: a spatial model of the swarm, stepped every window after the scale layer
        from swarmscope.world.engine import WorldEngine
        self.world = WorldEngine(self, persist=persist_dashboard)
        if "spatial_drift" in self.watchers:
            self.watchers["spatial_drift"].engine = self

    # ================================================================ setup helpers
    def _ingest(self, b: Batch) -> None:
        self.store.add_entities(b.entities)
        self.store.add_artifacts(b.artifacts)
        self.store.add_events(b.events)
        self.scale.add_texts([(a.id, t) for a, t in b.artifacts])

    def _build_monitors(self) -> None:
        self.monitors = {}
        for mid in self.org.get("monitors", []):
            man = self.manifests.get(mid)
            if not man:
                continue
            ok, _ = man.satisfiable(self.profile)
            if not ok:
                continue
            slots = {s: get_dotted(self.org, f"overrides.{mid}.slots.{s}") or self.org.get("overrides", {}).get(f"{mid}.slots.{s}")
                     for s in man.slots}
            slots = {k: v for k, v in slots.items() if v}
            params = {k.split(".", 2)[2]: v for k, v in self.org.get("overrides", {}).items()
                      if k.startswith(f"{mid}.params.")}
            params["risk_policy"] = self.org.get("risk_policy", "research_default")
            self.monitors[mid] = Monitor(man, slots, params)

    def _tunables(self) -> dict[str, dict[str, list[float]]]:
        return {m.id: m.manifest.tunables for m in self.monitors.values()}

    def set_monitor(self, mid: str, on: bool) -> bool:
        man = self.manifests.get(mid)
        if not man or not man.satisfiable(self.profile)[0]:
            return False
        mons = self.org.setdefault("monitors", [])
        if on and mid not in mons:
            mons.append(mid)
        if not on and mid in mons:
            mons.remove(mid)
        self._build_monitors()
        return True

    def now(self) -> datetime:
        return self.clock.now()

    def _lasting(self, inc: Any) -> bool:
        """Findings that do not fade with quiet: what someone said or thought against what they did, operator actions."""
        from swarmscope.dashboard.brief import _observation
        reps = [r for r in (self.store.get("MonitorReport", rid) for rid in inc.reports[-4:]) if r is not None]
        o = _observation(self, reps, inc.scope)
        return bool(o and o.kind in ("say_do_mismatch", "reasoning_cue", "environment", "human_intervention", "alias"))

    def label(self, eid: str | None) -> str:
        e = self.store.entity(eid)
        return e.label if e else (eid or "unknown")

    def tools(self, role: str) -> EvidenceTools:
        return EvidenceTools(self.store, self.now, self.profile.source, role, engine=self)

    def _record_attention(self, rec: AttentionRecord) -> None:
        self.store.put(rec)
        self.attention_total[rec.owner_kind] += rec.tokens_in + rec.tokens_out

    def _notify(self, kind: str, obj: Any) -> None:
        msg = {"type": kind, "data": obj.model_dump(mode="json") if hasattr(obj, "model_dump") else obj}
        for q in list(self.subscribers):
            if q.qsize() < 200:
                q.put_nowait(msg)

    # ================================================================ loop
    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._loop())
        if self.control:
            self.control.start()

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
        for t in self.investigations.tasks.values():
            t.cancel()
        await self.executive.close()
        if self.control:
            await self.control.close()
        if self.stream:
            self.stream.stop()

    async def _loop(self) -> None:
        while True:
            try:
                if self.clock.paused:
                    if getattr(self, "_bcast_pending", False):
                        self.broadcast(force=True)
                    await asyncio.sleep(0.1)
                    continue
                t0 = time.time()
                if self.clock.live:
                    await asyncio.sleep(self.clock.window.total_seconds())
                if getattr(self, "_bcast_pending", False) and time.time() - getattr(self, "_bcast_at", 0.0) >= 0.7:
                    self.broadcast(force=True)
                w = self.clock.next_window()
                if w is None:
                    self.clock.paused = True
                    self.broadcast(force=True)
                    continue
                async with self.lock:
                    await self.process(w)
                lr = self.live_replay
                if lr and not lr["on"] and self.clock.now() >= lr["at"]:
                    lr["on"] = True                       # the live point: real time from here, silences included
                    self.clock.set_time_scale(1.0)
                    self.clock.skip_gaps = False
                    self.clock.catching_up = None
                    self.broadcast()
                if not self.clock.live:
                    # wait in small steps so pause, speed changes and jumps take effect immediately
                    while not self.clock.paused and time.time() - t0 < 1.0 / max(self.clock.speed, 1e-4):
                        await asyncio.sleep(min(0.2, max(0.01, 1.0 / max(self.clock.speed, 1e-4) - (time.time() - t0))))
            except asyncio.CancelledError:
                raise
            except Exception:
                self.router.errors.append(traceback.format_exc(limit=3)[-600:])
                await asyncio.sleep(0.5)

    async def jump(self, to: datetime) -> None:
        """Timed simulator: catch up to `to` deterministically and fast, then hand back to the configured LLMs."""
        if self.clock.live or to <= self.clock.now():
            raise ValueError("can only jump forward in a replay")
        saved = (self.org.get("llm", {}).get("mode"), self.org.get("investigations", {}).get("node_delay_s"),
                 self.org.get("agents", {}).get("stub_delay_s"))
        was_paused = self.clock.paused
        self.clock.paused = True
        self.org.setdefault("llm", {})["mode"] = "stub"
        self.org.setdefault("investigations", {})["node_delay_s"] = 0
        self.org.setdefault("agents", {})["stub_delay_s"] = 0
        start = self.clock.now()
        self.clock.catching_up = {"from": start.isoformat(), "to": to.isoformat(), "progress": 0.0}
        try:
            async with self.lock:
                n = 0
                while self.clock.now() < to and (w := self.clock.next_window()) is not None:
                    await self.process(w)
                    n += 1
                    if n % 6 == 0:
                        self.clock.catching_up["progress"] = round(
                            (self.clock.now() - start) / max(to - start, timedelta(seconds=1)), 3)
                        self.broadcast()
                        await asyncio.sleep(0)
                for t in list(self.investigations.tasks.values()):
                    if not t.done():
                        try:
                            await asyncio.wait_for(t, timeout=30)
                        except Exception:
                            pass
        finally:
            self.org["llm"]["mode"], self.org["investigations"]["node_delay_s"], self.org["agents"]["stub_delay_s"] = saved
            self.clock.catching_up = None
            self.clock.paused = was_paused
            self.broadcast()

    async def run_to_end(self, max_windows: int | None = None) -> None:
        """Headless replay for tests and evals."""
        n = 0
        while (w := self.clock.next_window()) is not None:
            await self.process(w)
            n += 1
            # let running investigations progress at replay speed (bounded)
            for _ in range(400):
                if all(t.done() for t in self.investigations.tasks.values()):
                    break
                await asyncio.sleep(0)
            if max_windows and n >= max_windows:
                break
        for t in list(self.investigations.tasks.values()):
            try:
                await asyncio.wait_for(t, timeout=120)
            except Exception:
                pass
        if self.investigations.concluded_since:
            await self.run_executive(force=True)

    # ================================================================ one window
    async def process(self, w) -> None:
        if self.control:
            self.control.flush()
        if self.stream:
            self.stream.flush()
            if self.windows_processed % 12 == 0:            # a linked stream declares itself as it arrives
                from swarmscope.sources.generic_stream import infer_capabilities
                infer_capabilities(self)
        events = self.store.events(w.start, w.end, limit=200000)
        self.events_seen += len(events)
        self._digest(w, events)
        self.scale.observe_window(w.index, events)
        self.world.step(w.index, events)
        ctx = WatchContext(store=self.store, window=w, events=events, profile=self.profile, pack=self.pack.source,
                           focuses=self.policy.active(w.end), tunes=self.policy.tunes, window_len=self.window_len)
        # watchers owned by active monitors
        by_monitor: dict[str, list[Observation]] = defaultdict(list)
        active_watchers = {wid: [m for m in self.monitors.values() if wid in m.manifest.watchers]
                           for wid in self.watchers}
        all_obs: list[Observation] = []
        for wid, mons in active_watchers.items():
            if not mons:
                continue
            wt = self.watchers[wid]
            if any(not self.profile.has(r) for r in wt.requires):
                continue
            for k, v in mons[0].params.items():
                if k.startswith(f"{wid}."):
                    wt.params[k.split(".", 1)[1]] = v
            for k, v in self.org.get("overrides", {}).items():
                if k.startswith(f"{mons[0].id}.params.") and k.split(".", 2)[2] in wt.params:
                    wt.params[k.split(".", 2)[2]] = v
            obs = wt.observe(ctx)
            for o in obs:
                self.store.put(o)
                for m in mons:
                    by_monitor[m.id].append(o)
            all_obs += obs
        self._run_audits(ctx)

        # monitors (bottom-up)
        reports: list[MonitorReport] = []
        population = len({e.actor for e in self.store.events(w.end - self.window_len * 12, w.end, limit=20000) if e.actor})
        mctx_base = dict(store=self.store, window=w, window_len=self.window_len, profile=self.profile,
                         pack=self.pack.source, router=self.router, focuses=self.policy.active(w.end), params={},
                         questions=self.pack.questions, tools=self.tools, population=max(population, 1),
                         investigations_busy=not self.investigations.capacity(),
                         budget_left=max(0.0, 1 - self.router.spent_usd / max(0.01, float(self.org.get("budgets", {}).get("max_usd_per_hour", 5)))))

        async def run_mon(m: Monitor, obs: list[Observation]):
            mctx = MonitorContext(monitor_id=m.id, **mctx_base)
            rep, claims, qs = await m.run(mctx, obs)
            return rep, claims, qs

        results = await asyncio.gather(*(run_mon(self.monitors[mid], obs) for mid, obs in by_monitor.items()
                                         if mid in self.monitors and obs), return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                self.router.errors.append(f"monitor error: {type(r).__name__}: {r}")
                continue
            rep, claims, qs = r
            for c in claims:
                self.store.put(c)
            for q in qs:
                self.proposals.append(q)
            self.store.put(rep)
            reports.append(rep)
            self._notify("report", rep)
        for o in all_obs:
            for ref in o.evidence:
                self.inspected.add(ref.id)
        self.pending_reports += reports
        self.windows_processed += 1

        # Executive (top-down) on cadence or escalation
        cadence = int(self.org.get("executive", {}).get("cadence_windows", 6))
        escalated = any(at_least(r.escalation, OperationalState.INVESTIGATE) for r in reports)
        self.cases().age(self.window_len, self._lasting)  # quiet cases fade with a trail; ALERT and PAGE never do
        if self.org.get("executive", {}).get("enabled", True) and (
                escalated or self.escalation_pending or self.investigations.concluded_since or self.human_inputs
                or w.index - self.last_exec_index >= cadence):
            await self.run_executive()
        self._retry_blocked()
        self._expire_ledger()
        self.store.flush_docs()
        self.broadcast()

    def _retry_blocked(self) -> None:
        """Questions the Executive asked while investigations were at capacity open when a slot frees up."""
        if self.org.get("autonomy") == "observe":
            return
        blocked = sorted([q for q in self.store.all("Question") if q.status == "open" and q.blocked_reason],
                         key=lambda q: ["low", "medium", "high", "critical"].index(q.priority.value), reverse=True)
        for q in blocked:
            if not self.investigations.capacity():
                break
            q.blocked_reason = None
            self._open_question(q.id)

    def _run_audits(self, ctx: WatchContext) -> None:
        while self.policy.audits:
            scope = self.policy.audits.pop(0)
            fam = scope.split(":", 1)[1] if scope.startswith("family:") else None
            evs = [e for e in ctx.events if not fam or e.attributes.get("family") == fam]
            sample = random.Random(ctx.window.index).sample(evs, min(12, len(evs)))
            for e in sample:
                self.inspected.add(e.id)
            o = Observation(watcher="audit", kind="audit", window_end=ctx.window.end, scope=scope,
                            title=f"Coverage audit sampled {len(sample)} of {len(evs)} events in {fam or 'population'}",
                            severity=0.05, metrics={"sampled": len(sample), "population": len(evs)})
            self.store.put(o)

    # ================================================================ executive
    def population_stats(self, hours_windows: int = 6) -> dict[str, Any]:
        now = self.now()
        span = self.window_len * hours_windows
        cur = self.store.sql("SELECT family, count(*) n, count(DISTINCT actor) a FROM events WHERE ts > ? AND ts <= ? "
                             "GROUP BY family ORDER BY n DESC", [now - span, now])
        prev = {r["family"]: r["n"] for r in self.store.sql(
            "SELECT family, count(*) n FROM events WHERE ts > ? AND ts <= ? GROUP BY family", [now - 2 * span, now - span])}
        active = self.store.scalar("SELECT count(DISTINCT actor) FROM events WHERE ts > ? AND ts <= ? AND actor IS NOT NULL "
                                   "AND actor NOT IN ('operator','summarizer') AND actor NOT LIKE 'human:%'",
                                   [now - span, now]) or 0
        fams = [{"family": r["family"] or "other", "now": r["n"], "prev": prev.get(r["family"], 0), "actors": r["a"]}
                for r in cur if r["family"] not in ("summary", "goal")]
        return {"active": active, "hours": span.total_seconds() / 3600, "families": fams,
                "total_events_seen": self.events_seen}

    def monitor_health(self) -> dict[str, Any]:
        total = max(1, self.events_seen)
        dis = [r.disagreement for r in self.pending_reports if r.disagreement is not None]
        return {
            "coverage": round(min(1.0, len(self.inspected) / total), 3),
            "inspected_events": len(self.inspected), "events_seen": self.events_seen,
            "disagreement": round(sum(dis) / len(dis), 2) if dis else None,
            "blind_spots": len(self.exec_state.blind_spots),
            "errors": self.router.errors[-5:],
            "monitors": {m.id: {"reports": m.reports, "level": m.last_level, "spent_usd": round(m.spent_usd, 4),
                                "tokens": m.tokens, "slots": m.slots} for m in self.monitors.values()},
            "llm_mode": self.router.mode, "spent_usd": round(self.router.spent_usd, 4),
        }

    async def run_executive(self, force: bool = False) -> None:
        concluded = [self.store.get("Investigation", i) for i in self.investigations.concluded_since]
        self.investigations.concluded_since = []
        claims = {c.id: c for c in self.store.all("Claim")}
        x = ExecInput(now=self.now(), state=self.exec_state, ledger=self.ledger, reports=self.pending_reports,
                      claims=claims, questions=self.proposals,
                      open_questions=[q for q in self.store.all("Question") if q.status in ("open", "investigating")],
                      investigations=[i for i in concluded if i], running=self.investigations.active(),
                      human=self.human_inputs, population=self.population_stats(), focuses=self.policy.table(self.now()),
                      monitor_health=self.monitor_health(), entity_noun=self.profile.entity_noun, workstream_noun=self.profile.workstream_noun,
                      source_title=self.profile.title, label=self.label, window_len=self.window_len,
                      asked={(q.kind, q.scope) for q in self.store.all("Question")},
                      authority=self.authority, exists=self.evidence_exists)
        if self.executive.strategy == "global_summary":
            evs = self.store.events(self.now() - self.window_len * 6, self.now(), limit=120)
            x.raw_digest = "\n".join(f"{e.id} {e.ts:%H:%M} {self.label(e.actor)} {e.action} {self.label(e.object)}"
                                     for e in evs)
        step, meta = await self.executive.step(x)
        self.exec_meta = meta
        self.last_exec_index = self.clock.index
        self.pending_reports, self.proposals, self.human_inputs = [], [], []
        self.escalation_pending = False
        self.authority["alerts_used"] = 0                   # a fresh authority budget each cycle
        self.approvals.new_cycle()
        self.approvals.apply_due()                           # proposals apply between cycles, never during
        # state, ledger, briefing
        self.exec_state = step.state
        for inc in self.exec_state.active_incidents:     # a person's dismissal survives a cycle that ran meanwhile
            if inc.id in self.dismissed:
                inc.status = "resolved"
        self.store.put(step.state, "ExecutiveState")
        self._apply_ledger(step)
        for b in step.briefing:
            self.store.put(b)
            self._notify("briefing", b)
        for q in step.questions:
            q.created = q.created or self.now()
            self.store.put(q)
        for d in step.directives:
            d.executive_version = step.state.version
            d = self.applier.submit(d, self.now())
            self.store.put(d)
        # link investigations to incidents
        for inc in self.exec_state.active_incidents:
            if not inc.investigation:
                inv = next((i for i in self.store.all("Investigation") if i.scope == inc.scope), None)
                if inv:
                    inc.investigation = inv.id

    def team_summary(self) -> dict[str, Any]:
        from swarmscope.agents.selector import team_summary
        ch = dict(self.team_choice)
        ch["topology"] = self.agent_org.topology           # the live one, which a person may have switched
        if self.agent_org.topology.id != self.team_choice["topology"].id:
            ch["by"], ch["reasons"] = "human", ["switched on the Organization page"]
        return team_summary(ch)

    # ================================================================ cases (the findings ledger)
    def cases(self):
        from swarmscope.org.cases import Cases
        t = getattr(getattr(self, "agent_org", None), "topology", None)
        for k, v in (getattr(t, "authority", None) or {}).items():
            if k != "alerts_used":
                self.authority[k] = v
        return Cases(self.exec_state, self.now(), budget=self.authority, exists=self.evidence_exists)

    def evidence_exists(self, eid: str) -> bool:
        if not eid:
            return False
        if self.store.get("Claim", eid) is not None:
            return True
        try:
            return bool(self.store.events_by_id([eid]))
        except Exception:
            return False

    def escalate(self, *, scope: str, title: str, level: str, by: str, view: str, reason: str = "",
                 evidence: list[str] | None = None, case_id: str | None = None) -> dict[str, Any]:
        """The live path: an agent (or a person) escalates between executive cycles. The ledger applies its rules;
        if the case reached ALERT or above the UI hears now and the executive runs at the next window."""
        from swarmscope.org.cases import rank
        res = self.cases().record(scope=scope, title=title, level=level, by=by, view=view, reason=reason,
                                  evidence=evidence or [], case_id=case_id)
        inc = res["case"]
        if inc is None:
            return {"ok": False, "note": "nothing below INVESTIGATE opens a case", "level": res["level"]}
        self.store.put(self.exec_state, "ExecutiveState")
        if res["rose"] or res["new"]:
            self.store.put(BriefingEntry(ts=self.now(), kind="NEW" if res["new"] else "UPDATE", level=inc.level.value,
                                         text=(f"{by}: {title}" if res["new"] else f"Escalated to {inc.level.value} by {by}: {title}"),
                                         claims=[e for e in (evidence or []) if e.startswith("clm")][:4]))
        self.delegations.record(kind="escalation", by=by, role=view, target=scope, why=reason or title,
                                outcome=(f"held at {inc.level.value}: {res['held']}" if res["held"] else f"{inc.level.value}"))
        if rank(inc.level) >= rank("ALERT") and (res["rose"] or res["new"]):
            self.escalation_pending = True
            self._notify("escalation", {"id": inc.id, "level": inc.level.value, "title": title, "scope": scope, "by": by})
        self.broadcast()
        return {"ok": True, "case": inc.id, "level": inc.level.value, "rose": res["rose"], "new": res["new"],
                "held": res["held"], "views": inc.views,
                "note": (f"held at {inc.level.value}: {res['held']}" if res["held"] else
                         f"case {'opened' if res['new'] else 'updated'} at {inc.level.value}")}

    def _apply_ledger(self, step) -> None:
        texts = {e.text: e for e in self.ledger.entries}
        for e in step.ledger_add:
            if e.text in texts:
                texts[e.text].refreshed = self.now()
            else:
                self.ledger.entries.append(e)
                texts[e.text] = e
        self.ledger.entries = [e for e in self.ledger.entries if e.id not in set(step.ledger_expire)]
        budget = int(self.org.get("executive", {}).get("ledger_token_budget", 6000))
        while sum(e.tokens for e in self.ledger.entries) > budget:
            victim = next((e for e in self.ledger.entries if not e.sticky), None)
            if not victim:
                break
            self.ledger.entries.remove(victim)
        self.ledger.version += 1
        self.store.put(self.ledger, "ContextLedger")

    def _expire_ledger(self) -> None:
        now = self.now()
        keep = []
        for e in self.ledger.entries:
            age = (now - (e.refreshed or e.created or now)) / self.window_len
            if e.sticky or e.ttl_windows is None or age <= e.ttl_windows:
                keep.append(e)
        self.ledger.entries = keep

    def _open_question(self, qid: str) -> None:
        q = self.store.get("Question", qid)
        if not q or q.status not in ("open",):
            return
        seed = self._seed_for(q)
        inv = self.investigations.open(q, seed)
        if inv:
            for inc in self.exec_state.active_incidents:
                if inc.scope == q.scope and not inc.investigation:
                    inc.investigation = inv.id
            self.store.put(BriefingEntry(ts=self.now(), kind="UPDATE", level="INVESTIGATE",
                                         text=f"An investigation has opened: {q.text}"))

    def _seed_for(self, q: Question) -> Observation | None:
        obs = [o for o in self.store.all("Observation") if o.scope == q.scope]
        return max(obs, key=lambda o: (o.window_end, o.severity)) if obs else None

    # ================================================================ human inputs
    def human_question(self, text: str, scope: str | None, kind: str = "general") -> Question:
        q = Question(text=text, scope=scope or "population", kind=kind, requested_by="human", created=self.now())
        q.priority = q.priority.__class__("high")
        self.store.put(q)
        d = Directive(ts=self.now(), kind="ask", scope=q.scope, payload={"question": q.id, "text": text},
                      reason="asked by a human", set_by="human")
        self.store.put(self.applier.submit(d, self.now()))
        self.human_inputs.append(d)
        self.store.put(BriefingEntry(ts=self.now(), kind="HUMAN", level="INFO", text=f"Human asked: {text}"))
        self.broadcast()
        return q

    def human_directive(self, kind: str, scope: str | None, payload: dict[str, Any], reason: str = "") -> Directive:
        d = Directive(ts=self.now(), kind=kind, scope=scope, payload=payload, reason=reason or "set by a human",
                      set_by="human")
        d = self.applier.submit(d, self.now())
        self.store.put(d)
        self.human_inputs.append(d)
        self.broadcast()
        return d

    def approve_directive(self, did: str, approve: bool) -> Directive | None:
        d = self.store.get("Directive", did)
        if not d or d.status != "proposed":
            return d
        if approve:
            d = self.applier.apply(d, self.now())
        else:
            d.status = "rejected"
        self.store.put(d)
        self.broadcast()
        return d

    def pin(self, text: str, kind: str = "pinned_fact", evidence: list[str] | None = None) -> LedgerEntry:
        from swarmscope.core.models import EvidenceRef
        e = LedgerEntry(kind=kind, text=text, pinned_by="human", sticky=True, created=self.now(), refreshed=self.now(),
                        evidence=[EvidenceRef(kind="claim", id=i) for i in (evidence or [])])
        self.ledger.entries.append(e)
        self.ledger.version += 1
        self.store.put(self.ledger, "ContextLedger")
        self.broadcast()
        return e

    def unpin(self, entry_id: str) -> None:
        self.ledger.entries = [e for e in self.ledger.entries if e.id != entry_id]
        self.ledger.version += 1
        self.broadcast()

    def reconfigure(self, changes: dict[str, Any]) -> dict[str, Any]:
        for k, v in changes.items():
            if k == "monitors":
                self.org["monitors"] = list(v)
            elif "." in k:
                set_dotted(self.org, k, v) if not k.startswith("overrides.") else \
                    self.org.setdefault("overrides", {}).__setitem__(k[len("overrides."):], v)
            else:
                self.org[k] = v
        self._build_monitors()
        self.executive.strategy = self.org.get("executive", {}).get("strategy", self.executive.strategy)
        if "agents.topology" in changes and changes["agents.topology"] != self.agent_org.topology.id:
            self.agent_org.set_topology(changes["agents.topology"])
        self.router.org = self.org
        self.investigations.org = self.org
        self.applier.org = self.org
        self.broadcast()
        return self.org

    # ================================================================ snapshot
    def _digest(self, w, events) -> None:
        """What happened in one window, as counts and labels only (never agent text): the narrator's raw material."""
        from collections import deque
        if not hasattr(self, "digests"):
            self.digests = deque(maxlen=600)
        fam, res, env = Counter(), Counter(), Counter()
        actors, msgs, ex = set(), 0, {}
        for e in events:
            f = e.attributes.get("family") or "other"
            if e.action.startswith(("environment.", "control.")):
                env[e.action.split(".", 1)[1].replace("_", " ")] += 1
                continue
            fam[f] += 1
            ex.setdefault(f, e.id)                         # one citable event per workstream
            if e.actor:
                actors.add(e.actor)
            if e.object:
                res[e.object] += 1
            if f == "chat" or e.action.startswith(("chat.", "message")):
                msgs += 1
        self.digests.append({"i": w.index, "start": w.start, "end": w.end, "n": sum(fam.values()), "actors": actors,
                             "fam": fam, "res": res, "env": env, "msgs": msgs, "ex": ex})

    def broadcast(self, force: bool = False) -> None:
        if not self.subscribers:
            return
        # a fast replay (catching up, "as fast as possible") would rebuild the whole snapshot every window; send at
        # most ~1.4 a second and flush the last one from the loop, so the browser never misses the final state
        now_w = time.time()
        fast = not self.clock.paused and not self.clock.live and getattr(self.clock, "speed", 0) > 1.5
        if fast and not force and now_w - getattr(self, "_bcast_at", 0.0) < 0.7:
            self._bcast_pending = True
            return
        self._bcast_at, self._bcast_pending = now_w, False
        snap = self.snapshot()
        for q in list(self.subscribers):
            if q.qsize() > 50:
                continue
            q.put_nowait({"type": "snapshot", "data": snap})

    def snapshot(self, briefing_n: int = 60) -> dict[str, Any]:
        now = self.now()
        dump = lambda xs: [x.model_dump(mode="json") for x in xs]  # noqa: E731
        briefing = sorted(self.store.all("BriefingEntry"), key=lambda b: b.ts)[-briefing_n:]
        reports = sorted(self.store.all("MonitorReport"), key=lambda r: r.window_end)[-40:]
        claim_ids = {c for b in briefing for c in b.claims} | {c for r in reports[-15:] for c in r.claims}
        invs = sorted(self.store.all("Investigation"), key=lambda i: i.opened or now)[-12:]
        claim_ids |= {c for i in invs for n in i.nodes for c in n.claims}
        claims = {cid: self.store.get("Claim", cid).model_dump(mode="json") for cid in claim_ids if self.store.get("Claim", cid)}
        questions = sorted(self.store.all("Question"), key=lambda q: q.created or now)[-20:]
        directives = sorted(self.store.all("Directive"), key=lambda d: d.ts)[-30:]
        attention = self._attention_summary()
        scopes = {d.scope for d in directives if d.scope} | {f.scope for f in self.policy.active(now)} |             {i.scope for i in self.exec_state.active_incidents} | {i.scope for i in invs if i.scope} |             {q.scope for q in questions if q.scope}
        return {
            "scope_labels": {sc: self._scope_label(sc) for sc in scopes},
            "source": {"id": self.profile.source, "title": self.profile.title, "noun": self.profile.entity_noun,
                       "synthetic": self.profile.synthetic, "live": self.profile.live,
                       "goal": (self.meta.get("goal_text") or "")[:400] if self.meta else ""},
            "clock": self.clock.describe(),
            "org": {"id": self.org.get("id"), "name": self.org.get("name"), "autonomy": self.org.get("autonomy"),
                    "llm_mode": self.router.mode, "llm_label": llm_label(self.org), "executive_strategy": self.executive.strategy,
                    "monitors": list(self.monitors)},
            "executive": {**self.exec_state.model_dump(mode="json"), "meta": self.exec_meta,
                          "last_run_index": self.last_exec_index},
            "ledger": self.ledger.model_dump(mode="json"),
            "briefing": dump(briefing),
            "reports": dump(reports),
            "claims": claims,
            "questions": dump(questions),
            "investigations": dump(invs),
            "directives": dump(directives),
            "attention_policy": self.policy.table(now),
            "attention": attention,
            "health": self.monitor_health(),
            "population": self.population_stats(),
            "control": self.control.summary() if self.control else None,
            "agents": self.agent_org.summary(),
            "scale": self.scale_snapshot(),
            "session_id": f"{self.profile.source}:{int(self.started_wall)}",
            "stream": {"received": self.stream.received, "feed": self.stream.feed_info} if self.stream else None,
            "dashboard_version": self.dashboard.spec.version,
            "lens": self.dashboard.lens,
            "world": {"version": self.world.spec.version, "window": self.world.layout.window, "shape": self.world.spec.shape,
                      "flags": {k: len(v) for k, v in self.world.flags.items()}},
            "brief": self._brief(),
            "cases": self.cases().summary(self.window_len),
            "team": self.team_summary(),
            "approvals": self.approvals.summary(),
            "delegations": self.delegations.summary(),
            "autoplay": getattr(self, "autoplay_override", None) or self.pack.source.get("autoplay"),
            "speeds": self.pack.source.get("speeds") or [],
            "live_stretch": self.pack.source.get("live_stretch"),
            "live_replay": ({**self.live_replay, "at": self.live_replay["at"].isoformat(),
                             "end": self.live_replay["end"].isoformat() if self.live_replay["end"] else None}
                            if self.live_replay else None),
            "replay_hours": (self.pack.source.get("replay_hours_synthetic") if self.profile.synthetic else None)
                            or ((self.pack.source.get("replay_hours_full") if not self.meta.get("slice") else None))
                            or self.pack.source.get("replay_hours"),
        }

    def _brief(self) -> dict[str, Any]:
        from swarmscope.dashboard.brief import brief_digest
        try:
            return brief_digest(self)
        except Exception as exc:                          # the Brief must never take the snapshot down
            self.router.errors.append(f"brief: {type(exc).__name__}: {exc}")
            return {"status": self.exec_state.population_state, "items": [], "changes": [], "glance": {},
                    "counts": {"ACT": 0, "LOOK": 0, "WATCH": 0}, "attention_line": "", "terms": {}}

    def scale_snapshot(self) -> dict[str, Any]:
        lay, org = self.scale, self.agent_org
        cs = sorted(lay.cohorts.values(), key=lambda c: -(c.events_now + 3 * len(c.outliers)))
        return {"population": lay.population(),
                "cohorts": [lay.cohort_card(c) for c in cs[:16]],
                "templates": lay.template_rows(limit=10, sort="spread"),
                "triage": self.triage.to_dict(),
                "coverage": org.coverage_log[-1] if org.coverage_log else None,
                "coverage_history": [{k: c.get(k) for k in ("cycle", "share_of_activity_looked_at_now",
                                                           "cohorts_looked_at_now", "random_audits_now",
                                                           "stale_cohorts_total", "agent_runs_now")}
                                     for c in org.coverage_log[-40:]],
                "sectors": len(org.sectors), "divisions": len(org.divisions)}

    def _attention_summary(self) -> dict[str, Any]:
        recs = self.store.all("AttentionRecord")
        by_scope: dict[str, dict[str, Any]] = defaultdict(lambda: {"monitors": set(), "investigators": 0, "calls": 0,
                                                                     "tokens": 0, "cost_usd": 0.0})
        by_owner: Counter = Counter()
        for r in recs[-3000:]:
            s = by_scope[r.scope or "population"]
            if r.owner_kind in ("monitor", "extractor", "critic") and not r.owner.startswith("inv_"):
                s["monitors"].add(r.owner)
            if r.owner_kind == "investigator" or r.owner.startswith("inv_"):
                s["investigators"] += 1
            s["calls"] += r.calls
            s["tokens"] += r.tokens_in + r.tokens_out
            s["cost_usd"] += r.cost_usd
            by_owner[r.owner_kind] += r.tokens_in + r.tokens_out
        focus = {f.scope: f.weight for f in self.policy.active(self.now())}
        rows = []
        for scope, s in by_scope.items():
            rows.append({"scope": scope, "label": self._scope_label(scope), "monitors": sorted(s["monitors"]),
                         "investigators": s["investigators"], "calls": s["calls"], "tokens": s["tokens"],
                         "cost_usd": round(s["cost_usd"], 4), "focus": focus.get(scope, 0)})
        for scope, wgt in focus.items():
            if scope not in by_scope:
                rows.append({"scope": scope, "label": self._scope_label(scope), "monitors": [], "investigators": 0,
                             "calls": 0, "tokens": 0, "cost_usd": 0, "focus": wgt})
        rows.sort(key=lambda r: (-(r["focus"] > 0), -r["tokens"], -r["calls"]))
        return {"by_scope": rows[:14], "by_role": dict(by_owner), "records": len(recs)}

    def _scope_label(self, scope: str) -> str:
        kind, _, ident = scope.partition(":")
        if kind in ("agent", "resource", "actor"):
            return self.label(ident)
        if kind == "artifact":
            a = self.store.artifact(ident)
            return f"content from {self.label(a.first_actor)}" if a else ident
        if kind == "family":
            return f"{ident} workstream"
        return scope


def _cached_load(pack: Any, adapter: Any, path: Any, slice_override: Any) -> "Batch":
    """Parse a recorded source once and keep the result on disk (data/cache). The key covers the source, path, slice
    and every data file's size and modified time, so a new download or another slice parses afresh."""
    import hashlib
    import pickle
    from swarmscope.ingest.packs import ROOT

    def load():
        return adapter.load(path, slice_override) if "slice_override" in adapter.load.__code__.co_varnames \
            else adapter.load(path)
    from pathlib import Path
    root = Path(path) if path and path != "synthetic" and Path(path).exists() else \
        ROOT / str(pack.source.get("default_path") or f"data/{pack.id}")
    if path == "synthetic" or not root.exists() or pack.source.get("analysis_only"):
        return load()
    files = sorted((str(f.relative_to(root)), f.stat().st_size, int(f.stat().st_mtime)) for f in
                   (root.rglob("*") if root.is_dir() else [root]) if f.is_file() and not f.name.startswith("_"))
    key = hashlib.sha1(repr((pack.id, path, slice_override, files,
                             (pack.dir / "source.yaml").stat().st_mtime)).encode()).hexdigest()[:16]
    cache = ROOT / "data" / "cache" / f"{pack.id}-{key}.pkl"
    if cache.exists():
        try:
            return pickle.loads(cache.read_bytes())
        except Exception:
            pass
    batch = load()
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        for old in cache.parent.glob(f"{pack.id}-*.pkl"):
            old.unlink()
        cache.write_bytes(pickle.dumps(batch, protocol=pickle.HIGHEST_PROTOCOL))
    except Exception:
        pass
    return batch
