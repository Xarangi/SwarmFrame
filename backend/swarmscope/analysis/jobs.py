"""Post-analysis jobs: a dump in, a report out, without live monitoring.

A job builds an engine over the dump (with a known source's adapter when the dump is one SwarmFrame knows, else the
generic dump reader), reads the whole record as fast as it can through the same watchers and analyst team the live
dashboard uses (fixed rules, so it is free and repeatable), builds the report, and optionally has Claude write it up
from that evidence. The finished engine can then be opened in the full dashboard to explore.
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
    engine: Any = None
    report: dict[str, Any] | None = None
    markdown: str = ""
    written: str = ""                 # Claude's write-up, when asked for
    writer: dict[str, Any] | None = None
    error: str = ""
    task: asyncio.Task | None = None

    def public(self) -> dict[str, Any]:
        from swarmscope.analysis.report import word_count
        return {"id": self.id, "path": self.path, "source": self.source, "status": self.status,
                "progress": round(self.progress, 3), "message": self.message, "error": self.error,
                "seconds": round((self.finished or time.time()) - self.started, 1), "options": self.options,
                "has_report": self.report is not None, "words": word_count(self.markdown) if self.markdown else 0,
                "written_words": word_count(self.written) if self.written else 0, "writer": self.writer}


def start(path: str, options: dict[str, Any] | None = None) -> Job:
    from swarmscope.analysis.dump import detect
    options = dict(options or {})
    d = detect(path)
    source = options.get("source") or d["known"] or "dump"
    if source == "dump" and not d["usable"] and not options.get("mapping"):
        raise ValueError("no file in the dump has a time field SwarmFrame can read; map one by hand")
    jid = f"an_{int(time.time() * 1000) % 10 ** 10:010d}"
    job = Job(id=jid, path=d["path"], source=source, options=options)
    JOBS[jid] = job
    job.task = asyncio.create_task(_run(job))
    return job


async def _run(job: Job) -> None:
    from swarmscope.engine import Engine
    try:
        job.status, job.message = "loading", "reading the files"
        o = job.options
        overrides = {"llm.mode": "stub", "investigations.node_delay_s": 0, "agents.stub_delay_s": 0}
        slice_override = None
        if job.source == "dump" and o.get("mapping"):
            slice_override = {"mapping": o["mapping"]}
        elif job.source == "german_wiki":
            slice_override = {"full": True}               # a dump is read whole
        loop = asyncio.get_running_loop()
        e: Engine = await loop.run_in_executor(None, lambda: Engine(job.source, "default", path=job.path, overrides=overrides,
                                                                    slice_override=slice_override, persist_dashboard=False))
        if job.source == "dump":
            from swarmscope.sources.generic_stream import infer_capabilities
            infer_capabilities(e)
        for drop in o.get("ignore_files") or []:          # e.g. analysis labels shipped with a benchmark's data
            e.meta.setdefault("files_skipped", []).append(drop)
        job.engine = e
        job.status = "reading"
        c = e.clock
        span = max(1.0, (c.end - c.start).total_seconds())
        n = 0
        while (w := c.next_window()) is not None:
            await e.process(w)
            n += 1
            job.progress = min(0.99, (c.now() - c.start).total_seconds() / span)
            job.message = f"{c.now():%Y-%m-%d %H:%M} · {n:,} windows · {e.events_seen:,} records read"
            if n % 4 == 0:
                await asyncio.sleep(0)
        for t in list(e.investigations.tasks.values()):
            try:
                await asyncio.wait_for(t, timeout=60)
            except Exception:
                pass
        job.status, job.message = "reporting", "writing the report"
        from swarmscope.analysis.report import build_report, to_markdown
        job.report = build_report(e, o.get("title") or "")
        job.markdown = to_markdown(job.report)
        if o.get("write") == "claude":
            job.status, job.message = "writing", "Claude is writing the report from the evidence"
            from swarmscope.analysis.writer import write_report
            res = await write_report(e, job.report, model=o.get("model", "claude-sonnet-5-5"), effort=o.get("effort", "low"),
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
        job.message = traceback.format_exc(limit=3)[-600:]
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
    except OSError:
        pass


async def run_blocking(path: str, options: dict[str, Any] | None = None) -> Job:
    """For the CLI and tests: start a job and wait for it."""
    job = start(path, options)
    await job.task
    return job


def stamp() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
