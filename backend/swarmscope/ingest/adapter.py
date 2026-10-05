"""Source adapter protocol and shared helpers."""
from __future__ import annotations

import gzip
import io
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Protocol

from swarmscope.core.models import Artifact, CapabilityProfile, Entity, EvidenceEvent
from swarmscope.ingest import boundary


@dataclass
class Batch:
    """Everything an adapter yields. Entities first, then artifacts, then events (ordered by ts)."""
    entities: list[Entity] = field(default_factory=list)
    artifacts: list[tuple[Artifact, str | None]] = field(default_factory=list)
    events: list[EvidenceEvent] = field(default_factory=list)
    ground_truth: list[dict[str, Any]] = field(default_factory=list)   # synthetic sources only
    meta: dict[str, Any] = field(default_factory=dict)


class SourceAdapter(Protocol):
    id: str

    def capabilities(self) -> CapabilityProfile: ...
    def load(self, path: str | None) -> Batch: ...


def make_artifact(aid: str, text: str, ts: datetime | None, actor: str | None, provenance: str) -> tuple[Artifact, str]:
    clean = boundary.sanitize(text)
    return Artifact(id=aid, fingerprint=boundary.fingerprint(clean), size=len(clean), first_seen=ts,
                    first_actor=actor, provenance=provenance, blocks=boundary.blocks(clean),
                    labels=boundary.detect_techniques(clean)), clean


# ------------------------------------------------------------------ generic file readers

def iter_records(path: str | Path) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield (locator, record) from json / jsonl / jsonl.gz / csv / zip of those."""
    p = Path(path)
    if p.is_dir():
        for f in sorted(p.rglob("*")):
            if f.is_file() and _readable(f.name):
                yield from iter_records(f)
        return
    name = p.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(p) as z:
            for info in z.infolist():
                if _readable(info.filename):
                    with z.open(info) as fh:
                        yield from _iter_stream(info.filename, fh.read())
        return
    yield from _iter_stream(p.name, p.read_bytes())


def _readable(name: str) -> bool:
    n = name.lower()
    return n.endswith((".json", ".jsonl", ".jsonl.gz", ".ndjson", ".csv", ".json.gz"))


def _iter_stream(name: str, data: bytes) -> Iterator[tuple[str, dict[str, Any]]]:
    n = name.lower()
    if n.endswith(".gz"):
        data = gzip.decompress(data)
        n = n[:-3]
    text = data.decode("utf-8", errors="replace")
    if n.endswith((".jsonl", ".ndjson")):
        for i, line in enumerate(text.splitlines()):
            if line.strip():
                try:
                    yield f"{name}#L{i + 1}", json.loads(line)
                except json.JSONDecodeError:
                    continue
    elif n.endswith(".json"):
        obj = json.loads(text)
        if isinstance(obj, dict):
            # common shapes: {"items": [...]}, {"revisions": [...]}, or a single record
            lists = [v for v in obj.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
            if lists:
                for i, r in enumerate(max(lists, key=len)):
                    yield f"{name}#{i}", r
            else:
                yield name, obj
        elif isinstance(obj, list):
            for i, r in enumerate(obj):
                if isinstance(r, dict):
                    yield f"{name}#{i}", r
    elif n.endswith(".csv"):
        import csv
        for i, r in enumerate(csv.DictReader(io.StringIO(text))):
            yield f"{name}#R{i + 1}", r


def pick(rec: dict[str, Any], *names: str, default: Any = None) -> Any:
    """First present field among aliases (case-insensitive, dotted paths allowed)."""
    lower = {k.lower(): k for k in rec}
    for n in names:
        if "." in n:
            cur: Any = rec
            for part in n.split("."):
                cur = cur.get(part) if isinstance(cur, dict) else None
            if cur not in (None, ""):
                return cur
        k = lower.get(n.lower())
        if k is not None and rec[k] not in (None, ""):
            return rec[k]
    return default


def parse_ts(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    if isinstance(v, (int, float)):
        return datetime.utcfromtimestamp(v / 1000 if v > 1e11 else v)
    s = str(v).strip().replace("Z", "+00:00")
    for fmt in (None, "%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            d = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
            return d.replace(tzinfo=None)
        except ValueError:
            continue
    return None
