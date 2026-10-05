"""Fetch the AI Village activity timeline (events.jsonl.gz) for a date range.

The full file is about 330 MB. This streams it and keeps only the rows between two dates, so the result for a week is
about 11 MB. Outreach recipients are real people outside the dataset, so they are kept as a domain and a hash only.

    HF_TOKEN=... python scripts/fetch_village_events.py 2026-06-28 2026-07-06

The token is read from HF_TOKEN and never written anywhere. Only counts are printed.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
import zlib
from collections import Counter
from pathlib import Path

import httpx

URL = "https://huggingface.co/datasets/aidigestorg/ai-village/resolve/main/events.jsonl.gz"
OUT = Path(__file__).resolve().parents[1] / "data" / "ai_village" / "events.jsonl.gz"


def main(lo: str, hi: str) -> None:
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("Set HF_TOKEN to a Hugging Face token with access to aidigestorg/ai-village.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    dec = zlib.decompressobj(16 + zlib.MAX_WBITS)
    buf, seen, kept, kinds = b"", 0, 0, Counter()
    part = OUT.with_suffix(".part")
    with httpx.Client(follow_redirects=True, timeout=600, headers={"Authorization": f"Bearer {token}"}) as client, \
            gzip.open(part, "wt", encoding="utf-8") as out, client.stream("GET", URL) as r:
        r.raise_for_status()
        for chunk in r.iter_bytes(1 << 20):
            buf += dec.decompress(chunk)
            *lines, buf = buf.split(b"\n")
            for line in lines:
                if not line.strip():
                    continue
                seen += 1
                row = json.loads(line)
                if not (lo <= str(row.get("created_at") or "")[:10] <= hi):
                    continue
                data = row.get("data") or {}
                if data.get("recipient"):
                    rc = str(data["recipient"]).strip().lower()
                    dom = rc.split("@", 1)[1] if "@" in rc else rc.split("/")[2] if rc.startswith("http") else ""
                    data["recipient"] = {"domain": dom[:80], "hash": hashlib.sha256(rc.encode()).hexdigest()[:12]}
                row.pop("updated_at", None)
                kinds[data.get("actionType")] += 1
                kept += 1
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(part, OUT)
    print(f"scanned {seen:,} rows, kept {kept:,} ({OUT.stat().st_size / 1e6:.1f} MB) in {OUT}")
    print("by type:", dict(kinds.most_common()))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
