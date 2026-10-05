"""Replay slices for AI Village: one per village goal, with activity counts. Structure only, cached."""
from __future__ import annotations

import bisect
import gzip
import json
from datetime import datetime, timedelta
from typing import Any

from swarmscope.ingest.adapter import parse_ts
from swarmscope.ingest.packs import ROOT


def village_slices() -> list[dict[str, Any]]:
    root = ROOT / "data" / "ai_village"
    cache = root / "_slices.json"
    if cache.exists():
        return json.loads(cache.read_text())
    if not (root / "village_goals.jsonl.gz").exists():
        return []

    def rows(name):
        f = root / name
        return (json.loads(l) for l in gzip.open(f, "rt", encoding="utf-8")) if f.exists() else iter(())

    goals = list(rows("village_goals.jsonl.gz"))
    chat = sorted(parse_ts(r["created_at"]) for r in rows("chat_messages.jsonl.gz"))
    ses = sorted((parse_ts(r["created_at"]), r["agent_id"]) for r in rows("computer_use_sessions.jsonl.gz"))
    sts = [s[0] for s in ses]
    out = []
    for g in sorted(goals, key=lambda g: g["start_time"]):
        a = parse_ts(g["start_time"])
        b = parse_ts(g.get("end_time")) or (chat[-1] if chat else a + timedelta(days=7))
        i, j = bisect.bisect(chat, a), bisect.bisect(chat, b)
        k, l = bisect.bisect(sts, a), bisect.bisect(sts, b)
        out.append({"goal": g["id"], "start": a.isoformat(sep=" "), "end": b.isoformat(sep=" "),
                    "days": round((b - a).total_seconds() / 86400, 1), "chat": j - i, "sessions": l - k,
                    "agents": len({s[1] for s in ses[k:l]}), "title": (g.get("goal") or "")[:140]})
    cache.write_text(json.dumps(out))
    return out
