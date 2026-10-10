"""Read a dump: any folder or file of agent logs, after the fact.

`detect(path)` looks at what is there without reading content into the report: file names, formats, row counts, the
field names, and a guess at which field is the time, who acted, what they did, what they acted on, their group and
any agent-written text. A folder that matches a source SwarmFrame knows (the collusion.wiki export, the Transluce
catalog, the AI Village export) is read with that source's own adapter; anything else is read by `DumpAdapter` with
the guessed (or corrected) mapping. Text goes behind the evidence boundary like every other source.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from swarmscope.core.models import Entity, EvidenceEvent
from swarmscope.ingest.adapter import Batch, _readable, iter_records, make_artifact, parse_ts

ROLES = ["ts", "actor", "action", "object", "group", "family", "text", "id"]
# field names that usually mean each role, best first
NAMES: dict[str, list[str]] = {
    "ts": ["ts", "timestamp", "time", "created_at", "createdat", "datetime", "date", "when", "event_time", "request_time",
           "write_date", "sent_at", "start_time", "started_at", "updated_at"],
    "actor": ["actor", "actor_label", "agent", "agent_id", "agent_name", "author", "user", "user_id", "username",
              "sender", "from", "handle", "label", "speaker", "model", "bot", "worker", "account"],
    "action": ["action", "event_type", "event", "type", "kind", "op", "operation", "verb", "tool", "tool_name",
               "method", "activity", "status"],
    "object": ["object", "target", "resource", "page", "page_key", "page_id", "page_title", "title", "room", "channel",
               "thread", "file", "path", "url", "domain", "host", "repo", "document", "doc", "subject", "to"],
    "group": ["group", "team", "cohort", "org", "organization", "squad", "role", "model_family", "provider", "lab"],
    "family": ["family", "category", "workstream", "area", "topic", "namespace", "section"],
    "text": ["text", "body", "content", "message", "msg", "prompt", "response", "output", "reasoning", "comment",
             "summary", "note", "description"],
    "id": ["id", "event_id", "rev_id", "revision_id", "uuid", "record_id", "message_id", "_id"],
}
KNOWN = {
    "german_wiki": ("The collusion.wiki export", lambda names: "revisions.jsonl.gz" in names or "revisions.jsonl" in names),
    "transluce": ("The Transluce urlquery catalog", lambda names: any(n.startswith("urlquery-agent-activity") for n in names)),
    "ai_village": ("The AI Village export", lambda names: "chat_messages.jsonl.gz" in names or "agents.jsonl.gz" in names),
}
SAMPLE = 400


def _files(p: Path) -> list[Path]:
    if p.is_file():
        return [p]
    return [f for f in sorted(p.rglob("*")) if f.is_file() and (_readable(f.name) or f.name.lower().endswith(".zip"))
            and not f.name.startswith(".")][:60]


def _norm(k: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", k.lower().replace("-", "_").replace(" ", "_"))


def _flat(r: dict[str, Any], prefix: str = "", depth: int = 0) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in r.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and depth < 1:
            out.update(_flat(v, key + ".", depth + 1))
        else:
            out[key] = v
    return out


def guess(rows: list[dict[str, Any]]) -> dict[str, str | None]:
    """Which field plays each role, from field names and the shape of the values (never their meaning)."""
    if not rows:
        return {r: None for r in ROLES}
    keys = Counter(k for r in rows for k in r)
    common = [k for k, n in keys.most_common() if n >= 0.5 * len(rows)]
    stats: dict[str, dict[str, Any]] = {}
    for k in common:
        vals = [r.get(k) for r in rows if r.get(k) not in (None, "")]
        strs = [v for v in vals if isinstance(v, str)]
        stats[k] = {"n": len(vals), "distinct": len({str(v) for v in vals}),
                    "avg_len": (sum(len(s) for s in strs) / len(strs)) if strs else 0,
                    "ts_ok": sum(1 for v in vals[:60] if parse_ts(v) is not None) / max(1, min(60, len(vals))),
                    "scalar": all(isinstance(v, (str, int, float, bool)) for v in vals)}
    used: set[str] = set()
    out: dict[str, str | None] = {}

    def pick(role: str, ok) -> str | None:
        by_name = {_norm(k.split(".")[-1]): k for k in common}
        for name in NAMES[role]:
            k = by_name.get(name)
            if k and k not in used and ok(stats[k]):
                used.add(k)
                return k
        return None

    n = len(rows)
    out["ts"] = pick("ts", lambda s: s["ts_ok"] >= 0.8)
    if out["ts"] is None:                                         # any field that parses as a time
        for k in common:
            if k not in used and stats[k]["ts_ok"] >= 0.9 and stats[k]["distinct"] > 1:
                out["ts"] = k
                used.add(k)
                break
    out["id"] = pick("id", lambda s: s["scalar"] and s["distinct"] >= 0.9 * s["n"])
    out["text"] = pick("text", lambda s: s["avg_len"] >= 24)
    out["action"] = pick("action", lambda s: s["scalar"] and 1 <= s["distinct"] <= max(60, n // 4) and s["avg_len"] < 60)
    out["actor"] = pick("actor", lambda s: s["scalar"] and s["distinct"] >= 2 and s["avg_len"] < 120)
    out["object"] = pick("object", lambda s: s["scalar"] and s["distinct"] >= 2 and s["avg_len"] < 300)
    out["group"] = pick("group", lambda s: s["scalar"] and 2 <= s["distinct"] <= 200)
    out["family"] = pick("family", lambda s: s["scalar"] and 2 <= s["distinct"] <= 200)
    return out


def detect(path: str) -> dict[str, Any]:
    """What is in a dump: files, formats, rows, fields and the guessed mapping per file. Structure only."""
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"nothing at {path}")
    files = _files(p)
    names = {f.name for f in files}
    known = next((k for k, (_, test) in KNOWN.items() if test(names)), None)
    out: list[dict[str, Any]] = []
    for f in files:
        rows: list[dict[str, Any]] = []
        total = 0
        try:
            for i, (_, r) in enumerate(iter_records(f)):
                total += 1
                if len(rows) < SAMPLE and isinstance(r, dict):
                    rows.append(_flat(r))
                if total >= 200000:
                    break
        except Exception as exc:                                   # unreadable file: say so, keep going
            out.append({"file": str(f.relative_to(p)) if p.is_dir() else f.name, "rows": 0, "error": str(exc)[:200]})
            continue
        m = guess(rows)
        fields = sorted(Counter(k for r in rows for k in r).keys())[:60]
        out.append({"file": str(f.relative_to(p)) if p.is_dir() else f.name, "size": f.stat().st_size, "rows": total,
                    "rows_capped": total >= 200000, "fields": fields, "mapping": m,
                    "usable": bool(m.get("ts") and (m.get("action") or m.get("actor") or m.get("object")))})
    return {"path": str(p), "known": known, "known_title": KNOWN[known][0] if known else None, "files": out,
            "rows": sum(f.get("rows", 0) for f in out), "usable": any(f.get("usable") for f in out) or bool(known)}


def _hid(prefix: str, s: str) -> str:
    return f"{prefix}{hashlib.sha1(s.encode()).hexdigest()[:10]}"


class DumpAdapter:
    """Reads any dump with a per-file mapping (from `detect`, or corrected by the person). Files without a time field
    are not events; they are listed in the report as not used."""
    id = "dump"

    def __init__(self, pack: Any):
        self.pack = pack

    def capabilities(self):
        return self.pack.capabilities

    def load(self, path: str | None = None, slice_override: dict[str, Any] | None = None) -> Batch:
        if not path:
            return Batch()
        p = Path(path).expanduser()
        maps: dict[str, dict[str, str | None]] = dict((slice_override or {}).get("mapping") or {})
        if not maps:
            maps = {f["file"]: f["mapping"] for f in detect(str(p))["files"] if f.get("usable")}
        b = Batch()
        ents: dict[str, Entity] = {}
        used, skipped = [], []
        for f in _files(p):
            rel = str(f.relative_to(p)) if p.is_dir() else f.name
            m = maps.get(rel)
            if not m or not m.get("ts"):
                skipped.append(rel)
                continue
            used.append(rel)
            stem = re.sub(r"(\.jsonl|\.json|\.ndjson|\.csv|\.gz|\.zip)+$", "", f.name.lower()) or "events"
            for loc, raw in iter_records(f):
                if not isinstance(raw, dict):
                    continue
                r = _flat(raw)
                ts = parse_ts(r.get(m["ts"]))
                if ts is None:
                    continue
                ts = ts.replace(tzinfo=None)
                actor = r.get(m["actor"]) if m.get("actor") else None
                actor = str(actor)[:120] if actor not in (None, "") else None
                obj = r.get(m["object"]) if m.get("object") else None
                obj = str(obj)[:300] if obj not in (None, "") else None
                act = str(r.get(m["action"]) if m.get("action") and r.get(m["action"]) not in (None, "") else "record")[:60]
                fam = str(r.get(m["family"]) if m.get("family") and r.get(m["family"]) not in (None, "") else stem)[:60]
                action = act if "." in act else f"{stem}.{act}"
                aid = f"a:{actor}" if actor else None
                if aid and aid not in ents:
                    grp = r.get(m["group"]) if m.get("group") else None
                    ents[aid] = Entity(id=aid, type="agent", source="dump", label=actor[:80],
                                       group=str(grp)[:60] if grp not in (None, "") else None)
                oid = f"o:{obj}" if obj else None
                if oid and oid not in ents:
                    ents[oid] = Entity(id=oid, type="resource", source="dump", label=obj[:120], group=fam)
                art = None
                txt = r.get(m["text"]) if m.get("text") else None
                if isinstance(txt, str) and txt.strip():
                    a, clean = make_artifact(_hid("dump_art_", loc), txt[:20000], ts, aid, "agent_text")
                    b.artifacts.append((a, clean))
                    art = a.id
                rid = r.get(m["id"]) if m.get("id") else None
                attrs = {"family": fam, "file": stem}
                for k, v in r.items():
                    if k in m.values() or not isinstance(v, (str, int, float, bool)) or len(attrs) > 12:
                        continue
                    if isinstance(v, str) and len(v) > 40:
                        continue
                    attrs[re.sub(r"[^a-z0-9_]", "_", k.lower())[:40]] = v
                b.events.append(EvidenceEvent(id=f"ev:{stem}:{rid}" if rid not in (None, "") else f"ev:{_hid('', loc)}",
                                              ts=ts, source="dump", actor=aid, action=action, object=oid, artifact=art,
                                              locator=loc, attributes=attrs))
        b.events.sort(key=lambda e: e.ts)
        b.entities = list(ents.values())
        b.meta = {"synthetic": False, "files_used": used, "files_skipped": skipped, "dump_name": p.name,
                  "goal_text": f"a dump of {len(used)} file{'s' if len(used) != 1 else ''}: {len(b.events)} records"}
        return b


def write_sample(dest: Path, n_agents: int = 120, hours: float = 24) -> Path:
    """A synthetic dump to try the analysis on: a planted swarm (neutral placeholder text) written as a gzipped
    JSON-lines log in an everyday shape, plus a small CSV without times (which the reader leaves out)."""
    import gzip
    import json
    from swarmscope.sources.swarm_scale import generate
    b = generate(n_agents=n_agents, hours=hours, seed=7)
    ents = {e.id: e for e in b.entities}
    texts = {a.id: t for a, t in b.artifacts}
    dest.mkdir(parents=True, exist_ok=True)
    with gzip.open(dest / "agent_activity.jsonl.gz", "wt", encoding="utf-8") as f:
        for i, e in enumerate(b.events):
            who, what = ents.get(e.actor), ents.get(e.object)
            f.write(json.dumps({"event_id": f"evt-{i:06d}", "created_at": e.ts.isoformat() + "Z",
                                "agent_name": who.label if who else e.actor, "team": who.group if who else None,
                                "event_type": e.action, "target": what.label if what else e.object,
                                "message": texts.get(e.artifact, "") if e.artifact else ""}) + "\n")
    (dest / "teams.csv").write_text("team,owner\n" + "".join(f"team-{i:02d},ops\n" for i in range(8)), encoding="utf-8")
    return dest


def iter_sample(path: str, n: int = 5) -> Iterator[dict[str, Any]]:      # used by tests
    for i, (_, r) in enumerate(iter_records(path)):
        if i >= n:
            return
        yield r


def first_ts(b: Batch) -> datetime | None:
    return b.events[0].ts if b.events else None
