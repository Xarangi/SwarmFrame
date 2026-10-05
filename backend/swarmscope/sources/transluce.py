"""Transluce agent-activity adapter (URLQuery reports attributed to autonomous agents).

The public package (transluce.org/agent-activity) holds report links and research metadata only: no report bodies,
responses or payloads. Columns used (all-reports.csv, report-sources.csv):

  report_id, report_date_utc     -> one event per report, at second resolution
  broad_class                    -> the method class (source_request | custom_program | indirection): action + family
  confidence                     -> the source's own grade (significant | suggestive | blank); kept as an attribute,
                                    never upgraded by volume
  disposition                    -> included | background | review_required
  data_source (report-sources)   -> the targeted data source: a target entity, the unit of this pack
  why_included                   -> the curators' short description of the evidence: an untrusted artifact
                                    (fingerprinted, stored behind a reference, never shown to privileged roles)

There are no persistent agent identities: individual agents are largely distinct. The pack's unit is the target.

Without the download, `path="synthetic"` generates the same schema with neutral placeholder text and planted
episodes (ground truth in batch.meta).
"""
from __future__ import annotations

import csv
import io
import random
import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from swarmscope.core.models import Entity, EvidenceEvent
from swarmscope.ingest.adapter import Batch, make_artifact
from swarmscope.ingest.packs import ROOT, SourcePack


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "unknown"


class TransluceAdapter:
    id = "transluce"

    def __init__(self, pack: SourcePack):
        self.pack = pack
        self.cfg = pack.source

    def capabilities(self):
        return self.pack.capabilities

    # ------------------------------------------------------------ io
    def _find(self, path: str | None) -> Path | None:
        p = Path(path) if path else ROOT / self.cfg.get("default_path", "data/transluce")
        if not p.is_absolute():
            p = ROOT / p
        if not p.exists():
            return None
        if p.is_file() and p.suffix == ".zip":
            return p
        if (p / "all-reports.csv").exists():
            return p
        hits = sorted(p.rglob("all-reports.csv"))
        if hits:
            return hits[0].parent
        zips = sorted(p.glob("*.zip"))
        return zips[-1] if zips else None

    def _csv(self, root: Path, name: str) -> Iterator[dict[str, str]]:
        if root.is_file():
            with zipfile.ZipFile(root) as z:
                member = next((n for n in z.namelist() if n.endswith("/" + name) or n == name), None)
                if member is None:
                    return iter(())
                data = z.read(member).decode("utf-8")
            return iter(list(csv.DictReader(io.StringIO(data))))
        f = root / name
        if not f.exists():
            return iter(())
        with open(f, newline="", encoding="utf-8") as fh:
            return iter(list(csv.DictReader(fh)))

    # ------------------------------------------------------------ load
    def load(self, path: str | None = None, slice_override: dict[str, Any] | None = None) -> Batch:
        sl = {**(self.cfg.get("slice") or {}), **(slice_override or {})}
        if path == "synthetic":
            self.pack.capabilities.synthetic = True
            return synthetic(seed=int(sl.get("seed", 5)))
        root = self._find(path)
        if root is None:
            self.pack.capabilities.synthetic = True
            return synthetic(seed=int(sl.get("seed", 5)))
        include = set(sl.get("dispositions") or ["included"])
        sources = {r["report_id"]: r for r in self._csv(root, "report-sources.csv")}
        b = Batch()
        targets: dict[str, str] = {}
        start = datetime.fromisoformat(sl["start"]) if sl.get("start") else None
        end = datetime.fromisoformat(sl["end"]) if sl.get("end") else None
        for r in self._csv(root, "all-reports.csv"):
            if r.get("disposition") not in include:
                continue
            ts = datetime.fromisoformat(r["report_date_utc"].replace("Z", "+00:00")).replace(tzinfo=None)
            if (start and ts < start) or (end and ts > end):
                continue
            src = sources.get(r["report_id"], {})
            target = src.get("data_source") or "Unassigned"
            tid = f"target:{_slug(target)}"
            targets[tid] = target
            klass = r.get("broad_class") or "unknown"
            art = None
            text = r.get("why_included") or ""
            if text:
                a, clean = make_artifact(f"why:{r['report_id']}", text, ts, None, "curator_description")
                b.artifacts.append((a, clean))
                art = a.id
            b.events.append(EvidenceEvent(
                id=f"tl:{r['report_id']}", ts=ts, source="transluce", actor=None, action=f"scan.{klass}", object=tid,
                artifact=art, locator=r.get("report_url"),
                attributes={"family": klass, "confidence": r.get("confidence") or "ungraded",
                            "disposition": r.get("disposition"), "source_basis": src.get("source_basis") or "none"}))
        for tid, label in targets.items():
            b.entities.append(Entity(id=tid, type="resource", source="transluce", label=label, group="target"))
        b.events.sort(key=lambda e: e.ts)
        if b.events:
            b.meta = {"slice_start": b.events[0].ts, "slice_end": b.events[-1].ts, "root": str(root),
                      "goal_text": f"{len(b.events)} URLQuery reports attributed to autonomous agents, "
                                   f"{len(targets)} targeted data sources"}
        return b


# ------------------------------------------------------------------ synthetic (same schema, neutral text)

SYN_TARGETS = ["Stats Portal A", "Open Data Hub B", "Library Archive C", "Health Data D", "Trade Tables E",
               "School Reports F", "Budget Documents G", "Map Imagery H", "Survey Counts I", "Energy Charts J"]
CLASSES = ["source_request", "custom_program", "indirection"]


def synthetic(seed: int = 5, days: int = 120) -> Batch:
    """Planted episodes: a burst on one target, a method new to a target, and a slow ramp across several targets."""
    rng = random.Random(seed)
    b = Batch()
    start = datetime(2026, 1, 1)
    tids = {t: f"target:{_slug(t)}" for t in SYN_TARGETS}
    for t, tid in tids.items():
        b.entities.append(Entity(id=tid, type="resource", source="transluce", label=t, group="target"))
    base = {t: rng.uniform(0.5, 6) for t in SYN_TARGETS}
    n = 0

    def report(ts: datetime, target: str, klass: str, conf: str) -> None:
        nonlocal n
        n += 1
        rid = f"syn-{n:06d}"
        a, clean = make_artifact(f"why:{rid}", f"[[marker:{klass}]] request pattern matched for {target.lower()}",
                                 ts, None, "curator_description")
        b.artifacts.append((a, clean))
        b.events.append(EvidenceEvent(id=f"tl:{rid}", ts=ts, source="transluce", actor=None, action=f"scan.{klass}",
                                      object=tids[target], artifact=a.id,
                                      attributes={"family": klass, "confidence": conf, "disposition": "included",
                                                  "source_basis": "source_method"}))

    for d in range(days):
        day = start + timedelta(days=d)
        for t in SYN_TARGETS:
            lam = base[t]
            if t == "Library Archive C" and 60 <= d < 62:
                lam *= 12                                           # burst
            if t in ("Trade Tables E", "Energy Charts J", "Survey Counts I") and d >= 80:
                lam *= 1 + (d - 80) / 10                            # slow ramp across targets
            for _ in range(_pois(rng, lam)):
                klass = "source_request" if rng.random() < 0.8 else "custom_program"
                if t == "Library Archive C" and 60 <= d < 62 and rng.random() < 0.5:
                    klass = "custom_program"
                report(day + timedelta(seconds=rng.randint(0, 86399)), t, klass,
                       "significant" if rng.random() < 0.15 else "suggestive")
        if d in (95, 96):                                           # a method new to this target
            for _ in range(6):
                report(day + timedelta(seconds=rng.randint(0, 86399)), "Health Data D", "indirection", "significant")
    b.events.sort(key=lambda e: e.ts)
    b.meta = {"slice_start": start, "slice_end": start + timedelta(days=days), "synthetic": True,
              "goal_text": "Synthetic scan reports in the Transluce schema (neutral placeholders)",
              "ground_truth": [
                  {"id": "gt_burst", "kind": "burst", "ts": str(start + timedelta(days=60)),
                   "scope": f"resource:{tids['Library Archive C']}", "units": [tids["Library Archive C"]],
                   "detail": "Two-day burst on Library Archive C, half custom programs"},
                  {"id": "gt_new_method", "kind": "new_method", "ts": str(start + timedelta(days=95)),
                   "scope": f"resource:{tids['Health Data D']}", "units": [tids["Health Data D"]],
                   "detail": "First indirection reports on Health Data D"},
                  {"id": "gt_ramp", "kind": "rate", "ts": str(start + timedelta(days=80)), "scope": "family:source_request",
                   "units": [tids[t] for t in ("Trade Tables E", "Energy Charts J", "Survey Counts I")],
                   "detail": "Slow ramp on three targets at once"}]}
    return b


def _pois(rng: random.Random, lam: float) -> int:
    import math
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1
