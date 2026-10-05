"""Budgeted subset fetch for large gated Hugging Face datasets.

Small tables are downloaded whole. Large gzipped JSONL tables are fetched as a
byte-range prefix and stream-decompressed; the trailing partial line is dropped
and the result is re-written as a valid .jsonl.gz. Nothing is printed except
file names, byte counts, row counts and timestamp ranges (structure only).

The token is read from HF_TOKEN and never written to disk.
"""
from __future__ import annotations

import gzip
import json
import os
import zlib
from pathlib import Path
from typing import Any

import httpx

BASE = "https://huggingface.co/datasets/{repo}/resolve/main/{path}"


def fetch_plan(repo: str, plan: list[dict[str, Any]], out_dir: Path, budget_mb: float) -> list[dict[str, Any]]:
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("Set HF_TOKEN to an access token for this gated dataset.")
    out_dir.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {token}"}
    planned = sum(p.get("mb", 0) for p in plan if p.get("mode") == "head")
    if planned > budget_mb:
        raise SystemExit(f"plan needs {planned} MB of head slices > budget {budget_mb} MB")
    report = []
    with httpx.Client(follow_redirects=True, timeout=120, headers=headers) as client:
        for item in plan:
            path, mode = item["file"], item.get("mode", "full")
            dest = out_dir / path
            if mode == "full":
                r = client.get(BASE.format(repo=repo, path=path))
                r.raise_for_status()
                dest.write_bytes(r.content)
                nbytes = len(r.content)
            else:
                limit = int(item["mb"] * 1_000_000)
                nbytes = _head_slice(client, BASE.format(repo=repo, path=path), dest, limit)
            report.append({"file": path, "mode": mode, "downloaded_mb": round(nbytes / 1e6, 2), **_shape(dest)})
    (out_dir / "_fetch_report.json").write_text(json.dumps(report, indent=2))
    return report


def _head_slice(client: httpx.Client, url: str, dest: Path, limit: int) -> int:
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    got = 0
    buf = b""
    with client.stream("GET", url, headers={"Range": f"bytes=0-{limit - 1}"}) as r:
        r.raise_for_status()
        with gzip.open(dest, "wb") as out:
            for chunk in r.iter_bytes():
                got += len(chunk)
                buf += d.decompress(chunk)
                cut = buf.rfind(b"\n")
                if cut >= 0:
                    out.write(buf[: cut + 1])
                    buf = buf[cut + 1:]
                if got >= limit:
                    break
    return got  # trailing partial line in `buf` is intentionally dropped


def _shape(dest: Path) -> dict[str, Any]:
    """Row count and created_at range only."""
    rows, lo, hi = 0, None, None
    with gzip.open(dest, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            rows += 1
            try:
                ts = json.loads(line).get("created_at")
            except json.JSONDecodeError:
                continue
            if ts:
                lo = ts if lo is None or ts < lo else lo
                hi = ts if hi is None or ts > hi else hi
    return {"rows": rows, "created_min": lo, "created_max": hi}
