"""`swarmscope probe <path>`: describe an unknown source before writing or orienting a pack."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from swarmscope.ingest.adapter import iter_records, parse_ts


def probe(path: str, sample: int = 5000, show_values: bool = False) -> dict[str, Any]:
    """Structure-only by default: reports field names, types, presence, cardinality and value
    *shapes* (length, character classes). Record content is never printed unless show_values=True."""
    fields: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, list[str]] = defaultdict(list)
    distinct: dict[str, set[str]] = defaultdict(set)
    files: Counter[str] = Counter()
    n = 0
    for loc, rec in iter_records(path):
        files[loc.split("#")[0]] += 1
        n += 1
        for k, v in _flatten(rec).items():
            fields[k][type(v).__name__] += 1
            sv = str(v)
            if len(distinct[k]) < 2000:
                distinct[k].add(sv[:80])
            if len(examples[k]) < 3:
                examples[k].append(sv[:120] if show_values else _shape(sv))
        if n >= sample:
            break
    report = {"path": path, "records_sampled": n, "files": dict(files.most_common(20)), "fields": []}
    for k, types in sorted(fields.items(), key=lambda kv: -sum(kv[1].values())):
        count = sum(types.values())
        ex = examples[k]
        guess = _guess(k, ex, len(distinct[k]), count)
        report["fields"].append({"name": k, "present": round(count / max(n, 1), 3), "types": dict(types),
                                 "distinct_sampled": len(distinct[k]), "examples": ex, "role_guess": guess})
    return report


def _shape(v: str) -> str:
    kinds = []
    if any(c.isdigit() for c in v): kinds.append("digits")
    if any(c.isalpha() for c in v): kinds.append("letters")
    if any(c.isspace() for c in v): kinds.append("spaces")
    if parse_ts(v): kinds = ["timestamp-like"]
    return f"<len {len(v)}: {'+'.join(kinds) or 'symbols'}>"


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and len(v) < 30:
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


def _guess(name: str, ex: list[str], distinct: int, count: int) -> str:
    n = name.lower()
    if ex and all("timestamp-like" in e or parse_ts(e) for e in ex) and any(t in n for t in ("time", "ts", "date", "created", "at")):
        return "timestamp"
    if any(t in n for t in ("user", "actor", "author", "agent", "handle", "ip")):
        return "identity"
    if any(t in n for t in ("page", "title", "url", "domain", "host", "target")):
        return "resource"
    if any(t in n for t in ("sha", "hash", "digest")):
        return "fingerprint"
    if ex and any(e.startswith("<len ") and int(e[5:e.index(":")]) > 100 or len(e) > 100 for e in ex):
        return "text/artifact"
    if distinct < 30 and count > 50:
        return "category"
    return "attribute"
