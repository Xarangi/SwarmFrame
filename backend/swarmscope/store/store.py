"""Evidence store.

Evidence (events, entities, artifacts, raw text) lives in append-only DuckDB
tables so monitors can run SQL over it. Analysis objects (claims, questions,
reports, directives, ...) are kept as typed in-memory documents with a
write-through JSON table, so they are replayable and inspectable.
"""
from __future__ import annotations

import json
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, TypeVar

import pyarrow as pa

try:                                 # duckdb probes for pandas on every parameterized query; when it is not
    import pandas  # noqa: F401       # installed, mark it absent once so the probe fails fast instead of
except ImportError:                  # searching the filesystem (two searches per query, slow on Windows).
    import sys
    pa.table({"_": [0]})              # let pyarrow look for pandas first: it caches the answer, and a None
    sys.modules.setdefault("pandas", None)   # placeholder would otherwise confuse its check
import duckdb
from pydantic import BaseModel

from swarmscope.core.models import Artifact, Entity, EvidenceEvent

T = TypeVar("T", bound=BaseModel)

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id VARCHAR PRIMARY KEY, ts TIMESTAMP, ts_unc DOUBLE, source VARCHAR, actor VARCHAR,
  action VARCHAR, object VARCHAR, artifact VARCHAR, attributes VARCHAR, locator VARCHAR, seq BIGINT,
  family VARCHAR, actor_group VARCHAR
);
CREATE TABLE IF NOT EXISTS entities (
  id VARCHAR PRIMARY KEY, type VARCHAR, source VARCHAR, label VARCHAR, identity_confidence VARCHAR,
  grp VARCHAR, attributes VARCHAR, aliases VARCHAR
);
CREATE TABLE IF NOT EXISTS artifacts (
  id VARCHAR PRIMARY KEY, fingerprint VARCHAR, mime VARCHAR, size BIGINT, first_seen TIMESTAMP,
  first_actor VARCHAR, provenance VARCHAR, blocks VARCHAR, labels VARCHAR
);
CREATE TABLE IF NOT EXISTS artifact_text (id VARCHAR PRIMARY KEY, text VARCHAR);
CREATE TABLE IF NOT EXISTS docs (kind VARCHAR, id VARCHAR, ts TIMESTAMP, body VARCHAR, PRIMARY KEY (kind, id));
"""


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path) if path else ":memory:"
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(self.path)
        self.con.execute(SCHEMA)
        self._lock = threading.RLock()
        self._docs: dict[str, dict[str, BaseModel]] = defaultdict(dict)
        self._entities: dict[str, Entity] = {}
        self._artifacts: dict[str, Artifact] = {}
        self._seq = 0
        self._pending_docs: dict[tuple[str, str], tuple] = {}

    # ------------------------------------------------------------ evidence writes
    def _bulk(self, table: str, cols: list[str], rows: list[tuple]) -> None:
        """Arrow bulk insert: orders of magnitude faster than executemany on DuckDB."""
        if not rows:
            return
        data = {c: [r[i] for r in rows] for i, c in enumerate(cols)}
        tbl = pa.table(data)
        with self._lock:
            self.con.register("_bulk_tbl", tbl)
            self.con.execute(f"INSERT OR REPLACE INTO {table} SELECT {', '.join(cols)} FROM _bulk_tbl")
            self.con.unregister("_bulk_tbl")

    def add_entities(self, ents: Iterable[Entity]) -> None:
        rows = []
        for e in ents:
            self._entities[e.id] = e
            rows.append((e.id, e.type, e.source, e.label, e.identity_confidence, e.group,
                         json.dumps(e.attributes, default=str), json.dumps(e.aliases)))
        self._bulk("entities", ["id", "type", "source", "label", "identity_confidence", "grp", "attributes", "aliases"], rows)

    def add_artifacts(self, arts: Iterable[tuple[Artifact, str | None]]) -> None:
        rows, texts = [], []
        for a, text in arts:
            self._artifacts[a.id] = a
            rows.append((a.id, a.fingerprint, a.mime, a.size, a.first_seen, a.first_actor, a.provenance,
                         json.dumps(a.blocks), json.dumps(a.labels)))
            if text is not None:
                texts.append((a.id, text))
        self._bulk("artifacts", ["id", "fingerprint", "mime", "size", "first_seen", "first_actor", "provenance", "blocks",
                                 "labels"], rows)
        self._bulk("artifact_text", ["id", "text"], texts)

    def add_events(self, evs: Iterable[EvidenceEvent]) -> int:
        rows = []
        for e in evs:
            self._seq += 1
            e.seq = e.seq or self._seq
            fam = e.attributes.get("family")
            grp = self._entities[e.actor].group if e.actor and e.actor in self._entities else None
            rows.append((e.id, e.ts.replace(tzinfo=None), e.ts_uncertainty_s, e.source, e.actor, e.action,
                         e.object, e.artifact, json.dumps(e.attributes, default=str), e.locator, e.seq, fam, grp))
        self._bulk("events", ["id", "ts", "ts_unc", "source", "actor", "action", "object", "artifact", "attributes",
                              "locator", "seq", "family", "actor_group"], rows)
        return len(rows)

    # ------------------------------------------------------------ evidence reads
    def sql(self, query: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        if self._pending_docs and "docs" in query:
            self.flush_docs()
        with self._lock:
            cur = self.con.execute(query, params or [])
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def scalar(self, query: str, params: list[Any] | None = None) -> Any:
        with self._lock:
            r = self.con.execute(query, params or []).fetchone()
        return r[0] if r else None

    def entity(self, eid: str | None) -> Entity | None:
        return self._entities.get(eid) if eid else None

    def entities(self, type_: str | None = None) -> list[Entity]:
        return [e for e in self._entities.values() if type_ is None or e.type == type_]

    def artifact(self, aid: str | None) -> Artifact | None:
        return self._artifacts.get(aid) if aid else None

    def artifacts(self) -> list[Artifact]:
        return list(self._artifacts.values())

    def artifact_text(self, aid: str) -> str | None:
        return self.scalar("SELECT text FROM artifact_text WHERE id = ?", [aid])

    def events(self, start: datetime | None = None, end: datetime | None = None, *, actor: str | None = None,
               obj: str | None = None, family: str | None = None, action: str | None = None,
               ids: list[str] | None = None, limit: int = 5000, order: str = "ASC",
               within: tuple[list[str], list[str]] | None = None) -> list[EvidenceEvent]:
        """`within=(actors, objects)` restricts to events by one of the actors or on one of the objects."""
        q, p = ["SELECT * FROM events WHERE 1=1"], []
        if within is not None:
            actors, objects = within
            parts = []
            if actors:
                parts.append(f"actor IN ({','.join('?' * len(actors))})"); p.extend(actors)
            if objects:
                parts.append(f"object IN ({','.join('?' * len(objects))})"); p.extend(objects)
            q.append("AND (" + (" OR ".join(parts) or "FALSE") + ")")
        if start is not None:
            q.append("AND ts > ?"); p.append(start)
        if end is not None:
            q.append("AND ts <= ?"); p.append(end)
        if actor:
            q.append("AND actor = ?"); p.append(actor)
        if obj:
            q.append("AND object = ?"); p.append(obj)
        if family:
            q.append("AND family = ?"); p.append(family)
        if action:
            q.append("AND action = ?"); p.append(action)
        if ids is not None:
            if not ids:
                return []
            q.append(f"AND id IN ({','.join('?' * len(ids))})"); p.extend(ids)
        q.append(f"ORDER BY ts {order}, seq {order} LIMIT {int(limit)}")
        return [self._row_to_event(r) for r in self.sql(" ".join(q), p)]

    @staticmethod
    def _row_to_event(r: dict[str, Any]) -> EvidenceEvent:
        return EvidenceEvent(id=r["id"], ts=r["ts"], ts_uncertainty_s=r["ts_unc"] or 0, source=r["source"],
                             actor=r["actor"], action=r["action"], object=r["object"], artifact=r["artifact"],
                             attributes=json.loads(r["attributes"] or "{}"), locator=r["locator"], seq=r["seq"])

    def time_range(self) -> tuple[datetime | None, datetime | None]:
        r = self.sql("SELECT min(ts) AS a, max(ts) AS b FROM events")[0]
        return r["a"], r["b"]

    def count_events(self) -> int:
        return int(self.scalar("SELECT count(*) FROM events") or 0)

    # ------------------------------------------------------------ documents
    def put(self, obj: T, kind: str | None = None) -> T:
        kind = kind or type(obj).__name__
        oid = getattr(obj, "id", None) or str(getattr(obj, "version", "0"))
        self._docs[kind][oid] = obj
        ts = getattr(obj, "ts", None) or getattr(obj, "created", None) or getattr(obj, "opened", None)
        # write-through is buffered: one bulk insert per flush instead of one statement per object
        self._pending_docs[(kind, oid)] = (kind, oid, ts.replace(tzinfo=None) if isinstance(ts, datetime) else None, obj)
        if len(self._pending_docs) >= 5000:
            self.flush_docs()
        return obj

    def flush_docs(self) -> int:
        if not self._pending_docs:
            return 0
        rows = [(k, i, ts, o.model_dump_json()) for k, i, ts, o in self._pending_docs.values()]
        self._pending_docs = {}
        self._bulk("docs", ["kind", "id", "ts", "body"], rows)
        return len(rows)

    def event_times(self, ids: list[str]) -> dict[str, datetime]:
        """Timestamps of the given event ids that exist (one query for a batch of citations)."""
        ids = list(dict.fromkeys(ids))
        if not ids:
            return {}
        rows = self.sql(f"SELECT id, ts FROM events WHERE id IN ({','.join('?' * len(ids))})", ids)
        return {r["id"]: r["ts"] for r in rows}

    def get(self, kind: str, oid: str) -> Any:
        return self._docs[kind].get(oid)

    def all(self, kind: str) -> list[Any]:
        return list(self._docs[kind].values())

    def delete(self, kind: str, oid: str) -> None:
        self._docs[kind].pop(oid, None)
        self._pending_docs.pop((kind, oid), None)
        with self._lock:
            self.con.execute("DELETE FROM docs WHERE kind = ? AND id = ?", [kind, oid])

    def close(self) -> None:
        self.flush_docs()
        with self._lock:
            self.con.close()
