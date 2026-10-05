"""Remember what was composed for each source, so opening a source again reuses its views instead of recomputing them.

Composing (the dashboard designer, then the World designer) is the one step that costs model calls and time. Once a
source has been composed, its dashboard and World are already saved (data/dashboards/<source>.json and
data/worlds/<source>.json); this ledger records when and how, so compose mode can say "using the views saved for
this source" and skip the designers. A person can always recompose; a focus instruction also recomposes, since it
asks for something new.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from swarmscope.ingest.packs import ROOT

LEDGER = ROOT / "data" / "composed.json"


def _read() -> dict[str, Any]:
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def get(source: str, kind: str) -> dict[str, Any] | None:
    return (_read().get(source) or {}).get(kind)


def mark(source: str, kind: str, **info: Any) -> dict[str, Any]:
    d = _read()
    rec = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **info}
    d.setdefault(source, {})[kind] = rec
    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text(json.dumps(d, indent=1), encoding="utf-8")
    except OSError:
        pass
    return rec


def forget(source: str) -> None:
    d = _read()
    if d.pop(source, None) is not None:
        LEDGER.write_text(json.dumps(d, indent=1), encoding="utf-8")
