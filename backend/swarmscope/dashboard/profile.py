"""The stream profile: what a dashboard-designing agent sees of a data stream before it composes views.

Structure only. Field names, types, cardinalities, rates over time, entity counts, and the most common values of
fields that are categorical and short. Free-text and high-cardinality attributes are reported by name and shape and
marked unusable in views. Agent-written text never appears.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from swarmscope.engine import Engine

MAX_CATEGORICAL = 60          # more distinct values than this: high-cardinality
MAX_VALUE_LEN = 40            # longer average values than this: text


def attribute_shapes(engine: "Engine", sample: int = 4000) -> dict[str, dict[str, Any]]:
    """Shapes come from a sample of the whole stream (structure); values shown only from what the clock has reached."""
    rows = engine.store.sql(f"SELECT attributes, ts FROM events USING SAMPLE {int(sample)} ROWS")
    now = engine.now().replace(tzinfo=None)
    visible: dict[str, Counter] = defaultdict(Counter)
    vals: dict[str, Counter] = defaultdict(Counter)
    lens: dict[str, list[int]] = defaultdict(list)
    types: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        try:
            a = json.loads(r["attributes"] or "{}")
        except Exception:
            continue
        for k, v in a.items():
            if k == "family":                    # a core field, profiled with the others
                continue
            types[k][type(v).__name__] += 1
            if isinstance(v, (str, int, float, bool)) or v is None:
                s = str(v)
                vals[k][s] += 1
                lens[k].append(len(s))
                if r["ts"] is not None and r["ts"] <= now:
                    visible[k][s] += 1
    out = {}
    for k in sorted(vals):
        card = len(vals[k])
        avg = sum(lens[k]) / max(1, len(lens[k]))
        text = avg > MAX_VALUE_LEN or (card > MAX_CATEGORICAL and avg > 12)
        out[k] = {"type": types[k].most_common(1)[0][0], "distinct_in_sample": card, "avg_len": round(avg, 1),
                  "usable_in_views": not text,
                  "top_values": [[v, n] for v, n in visible[k].most_common(8)] if not text and card <= MAX_CATEGORICAL else None,
                  "note": "text or high-cardinality: hidden, not usable in views" if text else
                          ("high-cardinality" if card > MAX_CATEGORICAL else "categorical")}
    for k in list(types):
        if k not in out:
            out[k] = {"type": types[k].most_common(1)[0][0], "usable_in_views": False, "note": "structured value"}
    return out


def text_attributes(engine: "Engine") -> set[str]:
    cache = getattr(engine, "_text_attrs", None)
    if cache is None or cache[0] != engine.store.count_events():
        shapes = attribute_shapes(engine)
        cache = (engine.store.count_events(), {k for k, v in shapes.items() if not v.get("usable_in_views")})
        engine._text_attrs = cache
    return cache[1]


def stream_profile(engine: "Engine", whole: bool | None = None) -> dict[str, Any]:
    """`whole`: for a replay, profile the whole recording (layout only; monitors still never see the future)."""
    st = engine.store
    whole = (not engine.profile.live) if whole is None else whole
    now = (st.time_range()[1] or engine.now()) if whole else engine.now()
    lo, hi = st.time_range()
    total = st.count_events()
    seen = int(st.scalar("SELECT count(*) FROM events WHERE ts <= ?", [now.replace(tzinfo=None)]) or 0)

    def top(col: str, n: int = 8) -> list[list[Any]]:
        rows = st.sql(f"SELECT {col} AS k, count(*) AS n FROM events WHERE ts <= ? AND {col} IS NOT NULL "
                      f"GROUP BY {col} ORDER BY n DESC LIMIT {n}", [now.replace(tzinfo=None)])
        return [[engine.label(r["k"]) if col in ("actor", "object") else r["k"], int(r["n"])] for r in rows]

    def card(col: str) -> int:
        return int(st.scalar(f"SELECT count(DISTINCT {col}) FROM events WHERE ts <= ?", [now.replace(tzinfo=None)]) or 0)

    ents = Counter(e.type for e in st.entities())
    groups = Counter(e.group for e in st.entities() if e.group)
    span = (hi - lo) if lo and hi else timedelta(0)
    bucket = "ts:hour" if span <= timedelta(days=3) else "ts:day" if span <= timedelta(days=120) else "ts:week"
    rate = st.sql(f"SELECT date_trunc('{bucket[3:]}', ts) AS b, count(*) AS n FROM events WHERE ts <= ? GROUP BY b "
                  f"ORDER BY b", [now.replace(tzinfo=None)])
    caps = engine.profile.capabilities
    lay = engine.scale.population()
    return {
        "source": {"id": engine.profile.source, "title": engine.profile.title, "description": engine.profile.description,
                   "entity_noun": engine.profile.entity_noun, "resource_noun": engine.profile.resource_noun,
                   "live": engine.profile.live, "synthetic": engine.profile.synthetic},
        "capabilities": {k: {"present": c.present, "quality": c.quality, "note": c.note} for k, c in caps.items()},
        "time": {"start": str(lo)[:19] if lo else None, "end": str(hi)[:19] if hi else None,
                 "now": str(engine.now())[:19], "profiled_through": str(now)[:19],
                 "note": "a replay is profiled over the whole recording to lay out views; views themselves fill in as "
                         "the replay clock advances" if whole and not engine.profile.live else "",
                 "window_minutes": int(engine.window_len.total_seconds() // 60), "suggested_bucket": bucket},
        "events": {"total": total, "visible_now": seen,
                   "rate": [[str(r["b"])[:16], int(r["n"])] for r in rate][-60:]},
        "fields": {
            "actor": {"distinct": card("actor"), "top": top("actor"), "meaning": f"the {engine.profile.entity_noun} acting"},
            "object": {"distinct": card("object"), "top": top("object"), "meaning": f"the {engine.profile.resource_noun} acted on"},
            "family": {"distinct": card("family"), "top": top("family", 12), "meaning": "workstream / method class"},
            "action": {"distinct": card("action"), "top": top("action", 12), "meaning": "what happened"},
            "group": {"distinct": card("actor_group"), "top": top("actor_group"), "meaning": "the actor's group"},
        },
        "attributes": attribute_shapes(engine),
        "entities": {"by_type": dict(ents), "groups": dict(groups.most_common(12))},
        "scale": {k: lay[k] for k in ("unit", "units_seen", "units_active", "cohorts", "templates", "compression",
                                      "outliers")},
        "watchers": sorted({o.kind for o in st.all("Observation")}),
        "monitors": list(engine.monitors),
    }
