"""Post-analysis jobs: a dump in, a report out, without live monitoring.

A job builds an engine over the dump (with a known source's adapter when the dump is one SwarmFrame knows, else the
generic dump reader), reads the whole record as fast as it can through the same watchers, monitors and analyst team
the live dashboard uses, builds the report, and optionally has Claude write it up from that evidence. The finished
engine can then be opened in the full dashboard to explore.

A job can read the same dump with several **strategies** (a team shape, from a preset or composed for the data, and
an organization config) and compare them. Without ground truth the comparison measures what can be measured: what
each strategy found, how many of the strategies agree on each finding, what only one strategy found, how much of
the record was read closely, how many of its claims rest on evidence, and what it cost.
"""
from __future__ import annotations

import asyncio
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from swarmscope.ingest.packs import ROOT

JOBS: dict[str, "Job"] = {}
DEFAULT_STRATEGY = {"team": "composed", "org": "default"}


@dataclass
class Run:
    label: str
    strategy: dict[str, Any]
    status: str = "waiting"
    seconds: float = 0.0
    engine: Any = None
    report: dict[str, Any] | None = None
    markdown: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    team: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def public(self) -> dict[str, Any]:
        return {"label": self.label, "strategy": self.strategy, "status": self.status, "seconds": round(self.seconds, 1),
                "metrics": self.metrics, "team": self.team, "error": self.error}


@dataclass
class Job:
    id: str
    path: str
    source: str
    options: dict[str, Any]
    status: str = "starting"          # starting | loading | reading | reporting | writing | done | error
    progress: float = 0.0
    message: str = ""
    started: float = field(default_factory=time.time)
    finished: float | None = None
    runs: list[Run] = field(default_factory=list)
    main: int = 0                     # the run whose report is shown (and opened in the dashboard)
    comparison: dict[str, Any] | None = None
    search: dict[str, Any] | None = None
    written: str = ""                 # Claude's write-up, when asked for
    writer: dict[str, Any] | None = None
    error: str = ""
    task: asyncio.Task | None = None

    @property
    def engine(self) -> Any:
        return self.runs[self.main].engine if self.runs else None

    @property
    def report(self) -> dict[str, Any] | None:
        return self.runs[self.main].report if self.runs else None

    @property
    def markdown(self) -> str:
        return self.runs[self.main].markdown if self.runs else ""

    def public(self) -> dict[str, Any]:
        from swarmscope.analysis.report import word_count
        return {"id": self.id, "path": self.path, "source": self.source, "status": self.status,
                "progress": round(self.progress, 3), "message": self.message, "error": self.error,
                "seconds": round((self.finished or time.time()) - self.started, 1), "options": self.options,
                "has_report": self.report is not None, "words": word_count(self.markdown) if self.markdown else 0,
                "written_words": word_count(self.written) if self.written else 0, "writer": self.writer,
                "runs": [r.public() for r in self.runs], "main": self.main, "comparison": self.comparison,
                "search": self.search}


def strategies_of(options: dict[str, Any]) -> list[dict[str, Any]]:
    """The strategies a job reads the dump with: `strategies` (a list, to compare) or `strategy` (one)."""
    xs = options.get("strategies") or [options.get("strategy") or {}]
    out = []
    for s in xs[:6]:
        s = {**DEFAULT_STRATEGY, **(s or {})}
        s.setdefault("label", label_of(s))
        out.append(s)
    return out


def label_of(s: dict[str, Any]) -> str:
    from swarmscope.agents.spec import list_topologies
    titles = {t["id"]: t["title"] for t in list_topologies()}
    team = {"composed": "Composed for this data", "auto": "Picked by the selector"}.get(s.get("team"), titles.get(s.get("team"), s.get("team")))
    return team + (f" · {s['org']}" if s.get("org") not in (None, "default") else "") + (" · Claude composer" if s.get("composer") == "claude" else "")


def start(path: str, options: dict[str, Any] | None = None) -> Job:
    from swarmscope.analysis.dump import detect
    options = dict(options or {})
    d = detect(path)
    source = options.get("source") or d["known"] or "dump"
    if source == "dump" and not d["usable"] and not options.get("mapping"):
        raise ValueError("no file in the dump has a time field SwarmFrame can read; map one by hand")
    jid = f"an_{int(time.time() * 1000) % 10 ** 10:010d}"
    job = Job(id=jid, path=d["path"], source=source, options=options)
    job.runs = [Run(label=s["label"], strategy=s) for s in strategies_of(options)]
    JOBS[jid] = job
    job.task = asyncio.create_task(_run(job))
    return job


async def _read(job: Job, run: Run, k: int, n_runs: int) -> None:
    """Build an engine for one strategy and read every window."""
    from swarmscope.engine import Engine
    o, s = job.options, run.strategy
    t0 = time.time()
    run.status = "loading"
    overrides = {"llm.mode": s.get("llm", "stub"), "investigations.node_delay_s": 0, "agents.stub_delay_s": 0}
    if s.get("team") and s["team"] != "auto" and s.get("composer") != "claude":
        overrides["agents.topology"] = s["team"]
    slice_override = None
    if job.source == "dump" and o.get("mapping"):
        slice_override = {"mapping": o["mapping"]}
    elif job.source == "german_wiki":
        slice_override = {"full": True}               # a dump is read whole
    loop = asyncio.get_running_loop()
    e: Any = await loop.run_in_executor(None, lambda: Engine(job.source, s.get("org", "default"), path=job.path,
                                                             overrides=overrides, slice_override=slice_override,
                                                             persist_dashboard=False))
    if job.source == "dump":
        from swarmscope.sources.generic_stream import infer_capabilities
        infer_capabilities(e)
        if s.get("team") == "composed":                  # capabilities are known only now: compose again
            _recompose(e)
    if s.get("choices") and s.get("team") == "composed":
        from swarmscope.agents.composer import compose
        _install(e, compose(e, s["choices"]))
    if s.get("composer") == "claude":
        from swarmscope.agents.composer import compose_with_claude
        c = await compose_with_claude(e, model=s.get("model", "claude-sonnet-5-5"), effort=s.get("effort", "low"),
                                      focus=o.get("focus", ""))
        _install(e, c)
    run.engine = e
    run.team = _team(e)
    run.status = "reading"
    c = e.clock
    span = max(1.0, (c.end - c.start).total_seconds())
    stop_at = c.start + (c.end - c.start) * float(s.get("fraction", 1.0)) if s.get("fraction") else None
    n = 0
    while (w := c.next_window()) is not None:
        await e.process(w)
        n += 1
        frac = min(0.99, (c.now() - c.start).total_seconds() / span)
        job.progress = (k + frac) / n_runs
        job.message = f"{run.label}: {c.now():%Y-%m-%d %H:%M} · {n:,} windows · {e.events_seen:,} records read"
        if n % 4 == 0:
            await asyncio.sleep(0)
        if stop_at and c.now() >= stop_at:
            break
    for t in list(e.investigations.tasks.values()):
        try:
            await asyncio.wait_for(t, timeout=60)
        except Exception:
            pass
    run.seconds = time.time() - t0
    run.metrics = metrics(e, run.seconds)
    from swarmscope.analysis.report import build_report, to_markdown
    run.report = build_report(e, o.get("title") or "")
    run.report["strategy"] = {"label": run.label, **run.team}
    run.markdown = to_markdown(run.report)
    run.status = "done"


def release(run: Run) -> None:
    """Keep a run's numbers and report, free its engine (a comparison would otherwise hold every record at once)."""
    e, run.engine = run.engine, None
    if e is not None:
        try:
            e.store.close()
        except Exception:
            pass


async def ensure_engine(job: Job, i: int | None = None) -> Any:
    """The engine of a run, reading the record again if a comparison released it (rules only, so the same)."""
    i = job.main if i is None else i
    run = job.runs[i]
    if run.engine is None:
        await _read(job, run, 0, 1)
    return run.engine


def _recompose(e: Any) -> None:
    from swarmscope.agents.composer import compose
    _install(e, compose(e))


def _install(e: Any, c: dict[str, Any]) -> None:
    """Swap the engine's team for a composition before anything has run."""
    from swarmscope.agents.runtime import AgentOrg
    e.composition = c
    e.team_choice = {**e.team_choice, "topology": c["topology"], "by": "composer" if c.get("by") != "claude" else "claude composer",
                     "reasons": [c["summary"]] + [f"{p['title']}: {p['reason']}" for p in c["parts"] if p["how"] != "off"]}
    e.agent_org = AgentOrg(e, c["topology"])
    e.executive.agent_org = e.agent_org


def _team(e: Any) -> dict[str, Any]:
    t = e.team_choice["topology"]
    out = {"topology": t.id, "title": t.title, "by": e.team_choice.get("by"), "roles": list(t.roles),
           "standing": [s["role"] for s in t.standing], "partition": t.partition}
    c = getattr(e, "composition", None)
    if c:
        from swarmscope.agents.composer import describe
        out["composition"] = describe(c)
    return out


def metrics(e: Any, seconds: float) -> dict[str, Any]:
    """What a strategy produced, measurable without ground truth."""
    from swarmscope.core.models import ClaimStatus
    incs = list(e.exec_state.active_incidents)
    claims = e.store.all("Claim")
    supported = [c for c in claims if c.support]
    unsupported = [c for c in claims if c.status == ClaimStatus.INFERRED and not c.support]
    invs = e.store.all("Investigation")
    recs = e.store.all("AttentionRecord")
    by_team = [i for i in incs if any(v.startswith("role:") for v in i.views)]
    lvl = lambda i: i.level.value if hasattr(i.level, "value") else str(i.level)  # noqa: E731
    return {
        "findings": sorted({f"{_kind(e, i)}|{e._scope_label(i.scope)}" for i in incs}),
        "cases": len(incs), "raised_by_team": len(by_team),
        "at_alert": sum(1 for i in incs if lvl(i) in ("ALERT", "PAGE")), "at_investigate": sum(1 for i in incs if lvl(i) == "INVESTIGATE"),
        "claims": len(claims), "supported_claims": len(supported),
        "unsupported_rate": round(len(unsupported) / max(1, len(claims)), 3),
        "investigations": len(invs), "concluded": sum(1 for i in invs if getattr(i, "status", "") == "concluded"),
        "coverage": round(len(_team_read(e)) / max(1, e.events_seen), 3), "records_read_closely": len(_team_read(e)),
        "watcher_coverage": e.monitor_health().get("coverage"),
        "agents_used": len(getattr(e.agent_org, "nodes", {}) or {}),
        "model_calls": sum(r.calls for r in recs if r.backend != "stub"), "cost_usd": round(float(e.router.spent_usd or 0), 4),
        "seconds": round(seconds, 1),
    }


def _team_read(e: Any) -> set[str]:
    """Records the team itself looked at: through its evidence tools, or cited as support for its claims."""
    out = set(getattr(e.agent_org, "read", set()) or set())
    for c in e.store.all("Claim"):
        if str(c.author or "").startswith(("agent.", "investigation", "inv")):
            out |= {r.id for r in (c.support or []) if getattr(r, "kind", "event") == "event"}
    return out


def _kind(e: Any, inc: Any) -> str:
    from swarmscope.dashboard.brief import _observation
    try:
        reps = [r for r in (e.store.get("MonitorReport", rid) for rid in inc.reports[-3:]) if r is not None]
        o = _observation(e, reps, inc.scope)
        return o.kind if o else "finding"
    except Exception:
        return "finding"


def compare(runs: list[Run]) -> dict[str, Any]:
    """Agreement between strategies: a finding most strategies raised is likelier to be real; one only a single
    strategy raised is worth a look, either as a discovery or as noise."""
    done = [r for r in runs if r.status == "done"]
    if len(done) < 2:
        return {}
    from collections import Counter
    # the same team reached two ways (e.g. the selector picking the lead) votes once
    sig = lambda r: (r.team.get("topology"), tuple(sorted(r.team.get("roles") or [])), str(r.team.get("partition")))  # noqa: E731
    voters: dict[Any, Run] = {}
    for r in done:
        voters.setdefault(sig(r), r)
    votes = Counter(f for r in voters.values() for f in set(r.metrics["findings"]))
    need = len(voters) / 2
    consensus = {f for f, v in votes.items() if v > need}
    rows = []
    for r in done:
        mine = set(r.metrics["findings"])
        twin = voters[sig(r)]
        rows.append({"label": r.label, "same_as": twin.label if twin is not r else None, "found": len(mine), "of_consensus": len(mine & consensus),
                     "consensus_recall": round(len(mine & consensus) / max(1, len(consensus)), 2),
                     "only_here": sorted(f for f in mine if votes[f] == 1)[:20],
                     "coverage": r.metrics["coverage"], "supported_claims": r.metrics["supported_claims"],
                     "unsupported_rate": r.metrics["unsupported_rate"], "concluded": r.metrics["concluded"],
                     "agents_used": r.metrics["agents_used"], "cost_usd": r.metrics["cost_usd"], "seconds": r.metrics["seconds"]})
    best = max(rows, key=lambda x: (x["consensus_recall"], x["coverage"] or 0, -x["cost_usd"], -x["seconds"]))
    return {"strategies": len(done), "distinct_teams": len(voters), "findings_in_all": len(votes), "consensus": sorted(consensus)[:60],
            "consensus_size": len(consensus), "rows": rows, "best": best["label"],
            "note": "Without ground truth: a finding most strategies raised counts as consensus. Recall against it, "
                    "coverage and supported claims favour a strategy; cost and time count against it."}


# variants of the composed team a search tries, beside the selector's pick
SEARCH_VARIANTS: list[tuple[str, dict[str, Any]]] = [
    ("Composed for this data", {}),
    ("Composed, readers by cohort", {"partition": {"by": "cohort", "span": 6}, "reader": "standing"}),
    ("Composed, specialists on call", {"demote_specialists": True}),
    ("Composed, lean (lead, explorers, auditor)", {k: "off" for k in ("reader", "integrity", "goals", "propagation",
                                                                      "environment", "identity", "diarist")}),
]


def score(row: dict[str, Any]) -> float:
    """How a strategy did on a trial, without ground truth: agreement with the other strategies, how much of the
    record the team read, and its claims, against what it cost in agents and time."""
    return round(0.5 * row["consensus_recall"] + 0.35 * (row["coverage"] or 0) + 0.1 * min(1.0, row["supported_claims"] / 500)
                 - 0.01 * row["agents_used"] - 0.2 * min(1.0, row["cost_usd"] / 2), 3)


async def _search(job: Job) -> None:
    """Try candidate teams on the first part of the record, keep the best, then read everything with it."""
    frac = float(job.options.get("search_fraction", 0.3))
    trials = [Run(label=lab, strategy={**DEFAULT_STRATEGY, "choices": ch, "fraction": frac, "label": lab})
              for lab, ch in SEARCH_VARIANTS]
    trials.append(Run(label="Picked by the selector", strategy={**DEFAULT_STRATEGY, "team": "auto", "fraction": frac,
                                                               "label": "Picked by the selector"}))
    for k, r in enumerate(trials):
        try:
            await _read(job, r, k, len(trials) + 1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            r.status, r.error = "error", f"{type(exc).__name__}: {exc}"
        release(r)                                       # trials are thrown away; keep only their numbers
    cmp_ = compare(trials) or {"rows": []}
    for row in cmp_.get("rows", []):
        row["score"] = score(row)
    rows = sorted(cmp_.get("rows", []), key=lambda r: -r["score"])
    best = next(t for t in trials if rows and t.label == rows[0]["label"]) if rows else trials[0]
    job.search = {"fraction": frac, "trials": rows, "picked": best.label,
                  "note": f"Each candidate read the first {frac:.0%} of the record; the best scored team then read all of it."}
    final = Run(label=f"{best.label} (picked by the search)", strategy={k: v for k, v in best.strategy.items() if k != "fraction"})
    job.runs = [final]
    await _read(job, final, len(trials), len(trials) + 1)


async def _run(job: Job) -> None:
    try:
        o = job.options
        job.status, job.message = "reading", "reading the files"
        if o.get("search"):
            await _search(job)
        for k, run in enumerate(job.runs):
            if run.status == "done":
                continue
            try:
                await _read(job, run, k, len(job.runs))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                run.status, run.error = "error", f"{type(exc).__name__}: {exc}"
                job.message = traceback.format_exc(limit=3)[-600:]
            if len(job.runs) > 1:
                release(run)
        ok = [i for i, r in enumerate(job.runs) if r.status == "done"]
        if not ok:
            raise RuntimeError(job.runs[0].error if job.runs else "nothing ran")
        job.comparison = compare(job.runs) or None
        if job.comparison:
            job.main = next(i for i, r in enumerate(job.runs) if r.label == job.comparison["best"])
        else:
            job.main = ok[0]
        if o.get("write") == "claude":
            job.status, job.message = "writing", "Claude is writing the report from the evidence"
            await ensure_engine(job)
            from swarmscope.analysis.writer import write_report
            res = await write_report(job.engine, job.report, model=o.get("model", "claude-sonnet-5-5"), effort=o.get("effort", "low"),
                                     words=o.get("words"), max_turns=int(o.get("max_turns", 40)),
                                     rounds=int(o.get("rounds", 3)))
            job.written, job.writer = res["markdown"], {k: v for k, v in res.items() if k != "markdown"}
        _save(job)
        job.status, job.progress, job.message = "done", 1.0, "done"
    except asyncio.CancelledError:
        job.status, job.error = "error", "stopped"
        raise
    except Exception as exc:
        job.status, job.error = "error", f"{type(exc).__name__}: {exc}"
        job.message = job.message or traceback.format_exc(limit=3)[-600:]
    finally:
        job.finished = time.time()


def _save(job: Job) -> None:
    """Keep each report on disk (data/reports/<job>.md) so it outlives the server."""
    try:
        d = ROOT / "data" / "reports"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{job.id}.md").write_text(job.markdown, encoding="utf-8")
        if job.written:
            (d / f"{job.id}.claude.md").write_text(job.written, encoding="utf-8")
        for i, r in enumerate(job.runs):
            if i != job.main and r.markdown:
                (d / f"{job.id}.{i}.md").write_text(r.markdown, encoding="utf-8")
    except OSError:
        pass


async def run_blocking(path: str, options: dict[str, Any] | None = None) -> Job:
    """For the CLI and tests: start a job and wait for it."""
    job = start(path, options)
    await job.task
    return job


def stamp() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
