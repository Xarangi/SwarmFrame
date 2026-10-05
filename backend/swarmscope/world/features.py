"""What a stream can tell the World, graded the way every SwarmFrame claim is graded.

SwarmFrame observes; it does not instrument. Each World feature is therefore one of:
  observed  the stream states it (an operator stop event, a file path on a tool call)
  derived   code computes it from observed events (activity, co-touching a file in a window, a reply within a minute)
  inferred  a model has to read structure or samples to say it (what a group is working on); only with models on
  absent    the stream cannot support it; encodings that need it are refused and the legend says so

Positions use derived features only, so the map is the same with models on or off.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from swarmscope.engine import Engine

STATUSES = ("observed", "derived", "inferred", "absent")

# feature -> one-line meaning, used by the legend and by the designer's survey
FEATURES = {
    "identity": "each unit is a stable agent",
    "identity_partial": "units are handles or names that may not map one-to-one to agents",
    "activity": "how busy a unit is, from event timestamps",
    "signature": "the mix of workstreams, actions and places a unit uses",
    "resources": "the places units act on (files, pages, hosts, rooms, targets)",
    "resource_kinds": "what kind of place each resource is",
    "messages": "units send messages",
    "replies": "who answers whom",
    "co_touch": "units acting on the same place in the same window",
    "lineage": "content that one unit posted and another reused",
    "groups": "teams or other groupings of units",
    "state_fine": "working / blocked / paused / stopped, beyond active or idle",
    "operator": "operator or environment actions on units",
    "control": "SwarmFrame can pause, interrupt, message or stop units",
    "task": "what a unit or group is working on",
    "grade": "the source's own confidence in each record",
}

# quantity (in a binding) -> the features it needs (all must be available)
QUANTITY_NEEDS: dict[str, list[str]] = {
    "activity": ["activity"], "activity_z": ["activity"], "rate_change": ["activity"], "self_shift": ["signature"],
    "family_dominant": ["signature"], "action_dominant": ["signature"], "messages": ["messages"], "errors": [],
    "severity": [], "displacement": ["signature"], "isolation": ["signature"], "drift": ["signature"],
    "crowding": ["resources"], "approach": ["signature"], "landmark_events": ["resources"],
    "landmark_distinct_z": ["resources"], "coverage_age": [], "identity_confidence": [], "grade": ["grade"],
    "group": ["groups"], "cohort": ["signature"], "task_label": ["task"], "state": ["activity"],
    "since_last": ["activity"], "new_units": ["activity"], "road_age": ["resources"], "volume": ["activity"],
}


SAMPLE = "(SELECT * FROM events USING SAMPLE 20000 ROWS)"     # availability is a shape question: a sample answers it


def _count(engine: "Engine", where: str, params: list | None = None) -> int:
    try:
        return int(engine.store.scalar(f"SELECT count(*) FROM {SAMPLE} WHERE {where}", params or []) or 0)
    except Exception:
        return 0


def availability(engine: "Engine") -> dict[str, dict[str, str]]:
    """The per-stream table the designer, the validator and the legend read. Cheap: a few counts."""
    prof = engine.profile
    has = prof.has
    models_on = engine.router.mode != "stub"
    n = max(1, _count(engine, "true"))                       # all counts below are within the same-size sample
    msgs = _count(engine, "family = 'chat' OR action LIKE 'chat.%' OR action LIKE 'message%'")
    errs = _count(engine, "action LIKE '%error%' OR action LIKE '%denied%' OR action LIKE '%fail%' OR action LIKE '%blocked%'")
    goals = _count(engine, "family = 'goal'")
    grouped = _count(engine, "actor_group IS NOT NULL") if has("identities") else 0
    replies = _count(engine, "attributes LIKE '%reply_to%' OR attributes LIKE '%in_reply%'")
    partial = False
    try:
        partial = bool(engine.store.scalar("SELECT count(*) FROM entities WHERE identity_confidence = 'partial'"))
    except Exception:
        pass
    grade = has("evidence_grades") or _count(engine, "attributes LIKE '%\"confidence\"%' OR attributes LIKE '%\"grade\"%'") > 0.3 * n

    def st(s: str, why: str) -> dict[str, str]:
        return {"status": s, "why": why}

    out: dict[str, dict[str, str]] = {}
    ident = has("identities")
    out["identity"] = st("observed", "the stream names its agents") if ident and not partial else \
        st("derived", "names exist but some are partial (handles)") if ident else \
        st("absent", "no persistent agent identities: units are places (plinths)")
    out["identity_partial"] = st("observed", "some identities are marked partial") if partial else st("absent", "identities are not partial")
    out["activity"] = st("derived", "event timestamps")
    out["signature"] = st("derived", "actions and families per unit (the scale layer)")
    res = has("resources")
    out["resources"] = st("observed", "events name the place they act on") if res else st("absent", "events have no object")
    fam_known = _count(engine, "family IS NOT NULL AND family <> 'other'") > 0.5 * n
    out["resource_kinds"] = st("observed", "events carry a family") if fam_known and res else \
        st("inferred", "a model names kinds from the profile") if res and models_on else \
        st("derived", "kinds guessed from paths and URLs") if res else st("absent", "no resources")
    out["messages"] = st("observed", "message events in the stream") if msgs else st("absent", "no message events")
    out["replies"] = st("observed", "explicit reply fields") if replies else \
        st("derived", "same room within a minute") if msgs and res else \
        st("inferred", "an analyst reads samples") if msgs and models_on else st("absent", "no messages to reply to")
    out["co_touch"] = st("derived", "two units on one place in one window") if res and ident else st("absent", "needs identities and resources")
    out["lineage"] = st("derived", "the propagation watcher") if has("artifacts") and ident else st("absent", "needs agent text and identities")
    out["groups"] = st("observed", "the stream names teams") if grouped > 0.3 * n else \
        st("inferred", "analysts propose groupings") if ident and models_on else st("absent", "no groups")
    out["operator"] = st("observed", "environment events") if has("environment") else st("absent", "no operator events")
    out["control"] = st("observed", "a control plane is attached") if getattr(engine, "control", None) is not None else \
        st("absent", "read-only: SwarmFrame does not control these agents")
    out["state_fine"] = st("observed", "control statuses and denials") if out["control"]["status"] == "observed" else \
        st("observed", "operator events") if out["operator"]["status"] == "observed" else \
        st("derived", "error-like actions") if errs else \
        st("inferred", "analysts label states") if models_on and ident else st("absent", "only active / idle")
    out["task"] = st("observed", "stated goal events") if goals else \
        st("inferred", "division analysts label each group") if models_on else \
        st("absent", "models are off: groups are labelled by their behaviour signature only")
    out["grade"] = st("observed", "the source grades its own records") if grade else st("absent", "no confidence field")
    return out


def available(table: dict[str, dict[str, str]], feature: str) -> bool:
    return table.get(feature, {}).get("status", "absent") != "absent"


def quantity_ok(table: dict[str, dict[str, str]], quantity: str) -> tuple[bool, list[str]]:
    missing = [f for f in QUANTITY_NEEDS.get(quantity, []) if not available(table, f)]
    return not missing, missing


def quantity_status(table: dict[str, dict[str, str]], quantity: str) -> str:
    """The weakest status among the features a quantity needs (inferred beats derived beats observed)."""
    order = {"observed": 0, "derived": 1, "inferred": 2, "absent": 3}
    sts = [table.get(f, {}).get("status", "absent") for f in QUANTITY_NEEDS.get(quantity, [])] or ["derived"]
    return max(sts, key=lambda s: order[s])


def summary_lines(table: dict[str, dict[str, str]]) -> list[str]:
    """Plain lines for compose mode and the legend: what this stream cannot show."""
    return [f"{FEATURES[k]}: not in this stream ({v['why']})" for k, v in table.items()
            if v["status"] == "absent" and k in FEATURES and k not in ("identity_partial",)]
