"""Citations: the sources behind a finding, as a short numbered list a person can open.

A finding rests on claims (what a watcher or analyst asserted, with a status) and claims rest on events (what was
recorded). `cite` walks that chain and returns one entry per source, in reading order: each claim followed by the
first events that support it. Entries carry labels a dashboard already shows (names, actions, times), never the
text an agent wrote; opening an entry goes through the evidence drawer and its untrusted-text boundary.

Every place that reports a finding uses this: the Brief rows, the finding posts and narration in the live column,
and the copilot's answers (claim ids it mentions are resolved here and listed under the answer).
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from swarmscope.engine import Engine

CLAIM_RX = re.compile(r"\b(clm_[0-9a-f]{10})\b")
EVENT_RX = re.compile(r"\b(ev:[A-Za-z0-9:_-]{6,80})")


def _short(s: str, n: int = 120) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _status(c: Any) -> str:
    return c.status.value if hasattr(c.status, "value") else str(c.status)


def event_label(engine: "Engine", e: Any) -> str:
    who = engine.label(e.actor) if e.actor else "the environment"
    what = e.action.split(".", 1)[-1].replace("_", " ") if "." in e.action else e.action
    return f"{who} · {what}" + (f" → {engine.label(e.object)}" if e.object else "")


def cite(engine: "Engine", claim_ids: Iterable[str] = (), *, events: Iterable[str] = (),
         entities: Iterable[str] = (), max_claims: int = 3, events_per_claim: int = 2) -> list[dict[str, Any]]:
    """Numbered sources for a set of claims (plus any extra events or entities), visible at the replay horizon."""
    from swarmscope.dashboard.brief import plain
    now = engine.now()
    plan: list[tuple[str, Any]] = []
    want: list[str] = []
    for cid in list(dict.fromkeys(c for c in claim_ids if c))[:max_claims]:
        c = engine.store.get("Claim", cid)
        if c is None or (c.ts is not None and c.ts > now):
            continue
        plan.append(("claim", c))
        k = 0
        for r in c.support:
            if r.kind == "event" and k < events_per_claim:
                plan.append(("event", r.id)); want.append(r.id); k += 1
    for eid in events:
        if eid:
            plan.append(("event", eid)); want.append(eid)
    found = {e.id: e for e in engine.store.events(ids=list(dict.fromkeys(want)))} if want else {}

    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(d: dict[str, Any]) -> None:
        if d["id"] in seen:
            return
        seen.add(d["id"])
        out.append({"n": len(out) + 1, **d})

    for kind, x in plan:
        if kind == "claim":
            add({"kind": "claim", "id": x.id, "status": _status(x), "label": _short(plain(x.statement))})
        else:
            e = found.get(x)
            if e is not None and e.ts <= now:
                add({"kind": "event", "id": e.id, "ts": e.ts.isoformat(), "family": e.attributes.get("family"),
                     "label": _short(event_label(engine, e))})
    for eid in entities:
        ent = engine.store.entity(eid) if eid else None
        if ent is not None:
            add({"kind": "entity", "id": ent.id, "label": _short(ent.label, 60), "type": ent.type})
    return out


def cite_text(engine: "Engine", text: str, limit: int = 6) -> list[dict[str, Any]]:
    """Sources for the claim ids written into a message (the copilot cites by id); unknown ids are dropped."""
    ids = list(dict.fromkeys(CLAIM_RX.findall(text or "")))[:limit]
    evs = [x.rstrip(".,;)") for x in dict.fromkeys(EVENT_RX.findall(text or ""))][:limit]
    return cite(engine, ids, events=evs, max_claims=limit, events_per_claim=1) if ids or evs else []
