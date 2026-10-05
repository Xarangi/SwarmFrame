"""What's going on: continuous, severity-free oversight of the whole population.

Findings answer "what needs attention". This answers the other question a supervisor always has: what is everyone
doing right now, and what is new? For each group (a team, a model family, a handle group; workstreams when the
stream has no identities) it says how many are active, what kind of work, where, toward what stated goal, and
whether that is rising, new or going quiet. Then it lists what is emerging: places used for the first time, kinds of
work that are new or rising, groups that changed what they work on. Deterministic, recomputed once per window, and
every line cites a few of the events it rests on.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from swarmscope.engine import Engine

NOT_WORK = {"idle", "summary", "goal", "control", "lifecycle", "narration"}


def _span(engine: "Engine") -> timedelta:
    w = engine.window_len
    return min(max(w * 6, timedelta(minutes=10)), timedelta(hours=6))


def plural(w: str) -> str:
    return w[:-1] + "ies" if w.endswith("y") and w[-2:-1] not in "aeiou" else w + ("es" if w.endswith(("s", "sh", "ch")) else "s")


def _fmt(td: timedelta) -> str:
    m = int(td.total_seconds() // 60)
    return f"{m} min" if m < 120 else f"{m // 60} h"


def overview(engine: "Engine") -> dict[str, Any]:
    cache = engine.__dict__.setdefault("_overview_cache", {})
    key = (engine.clock.index, getattr(engine, "events_seen", 0))
    if key in cache:
        return cache[key]
    out = _overview(engine)
    cache.clear()
    cache[key] = out
    return out


def _overview(engine: "Engine") -> dict[str, Any]:
    from swarmscope.dashboard.cites import cite
    now = engine.now()
    span = _span(engine)
    p = engine.profile
    noun, gnoun = p.entity_noun, getattr(p, "group_noun", "group") or "group"
    wsn = getattr(p, "workstream_noun", "workstream") or "workstream"
    recent = engine.store.events(now - span, now, limit=60000)
    before = engine.store.events(now - 2 * span, now - span, limit=60000)
    seen_before = {e.object for e in engine.store.events(None, now - span, limit=200000) if e.object} if recent else set()

    ent = engine.store.entity
    group_of: dict[str, str] = {}
    members: Counter = Counter()
    for x in engine.store.entities():
        if x.type in ("agent", "actor") and x.group:
            group_of[x.id] = x.group
            members[x.group] += 1
    by_identity = bool(group_of)

    def gkey(e) -> str | None:
        if not e.actor:
            return None
        if by_identity:
            return group_of.get(e.actor)
        return None

    def fam(e) -> str:
        return e.attributes.get("family") or "other"

    groups: list[dict[str, Any]] = []
    if by_identity:
        now_g: dict[str, list] = defaultdict(list)
        prev_g: dict[str, list] = defaultdict(list)
        for e in recent:
            g = gkey(e)
            if g:
                now_g[g].append(e)
        for e in before:
            g = gkey(e)
            if g:
                prev_g[g].append(e)
        for g in sorted(set(now_g) | set(prev_g), key=lambda g: -len(now_g.get(g, []))):
            evs, prev = now_g.get(g, []), prev_g.get(g, [])
            work = [e for e in evs if fam(e) not in NOT_WORK]
            fams = Counter(fam(e) for e in work)
            places = Counter(e.object for e in work if e.object and fam(e) != "chat") or                 Counter(e.object for e in work if e.object)            # where the work is, before where the talk is
            goals = Counter((e.attributes.get("short_goal") or "").strip() for e in evs if e.attributes.get("short_goal"))
            talk = sum(1 for e in evs if fam(e) == "chat")
            active = len({e.actor for e in evs})
            n, m = len(work), len([e for e in prev if fam(e) not in NOT_WORK])
            trend = ("quiet" if not evs else "new" if not prev else "rising" if n > 1.6 * m + 3 else
                     "falling" if n < 0.6 * m - 3 else "steady")
            prev_top = Counter(fam(e) for e in prev if fam(e) not in NOT_WORK).most_common(1)
            top = fams.most_common(2)
            doing = " and ".join(f for f, _ in top) if top else ("talking" if talk else "idle")
            shifted = bool(prev_top and top and prev_top[0][0] != top[0][0] and top[0][1] >= 3)
            sample = [e.id for e in (work or evs)[-2:]]
            groups.append({
                "group": g, "active": active, "members": members.get(g, active), "events": len(evs), "work": n,
                "doing": doing, "families": [[f, k] for f, k in fams.most_common(4)], "messages": talk,
                "where": engine.label(places.most_common(1)[0][0]) if places else None,
                "goal": (goals.most_common(1)[0][0][:90] if goals else None), "trend": trend,
                "shifted_from": prev_top[0][0] if shifted else None,
                "cites": cite(engine, (), events=sample) if sample else [],
            })
    groups = groups[:12]

    # emerging: severity-free novelty
    emerging: list[dict[str, Any]] = []
    first = defaultdict(list)
    for e in recent:
        if e.object and e.object not in seen_before:
            first[e.object].append(e)
    for obj, evs in sorted(first.items(), key=lambda kv: -len({e.actor for e in kv[1]})):
        who = {e.actor for e in evs if e.actor}
        if len(evs) >= 3 or len(who) >= 2:
            emerging.append({"kind": "new_place", "text": f"{engine.label(obj)} was used for the first time "
                             f"({len(evs)} events by {len(who)} {noun}{'s' if len(who) != 1 else ''})",
                             "cites": cite(engine, (), events=[e.id for e in evs[:2]])})
        if len(emerging) >= 4:
            break
    fn, fp = Counter(fam(e) for e in recent if fam(e) not in NOT_WORK), Counter(fam(e) for e in before if fam(e) not in NOT_WORK)
    for f, k in fn.most_common():
        if k < 5:
            break
        ex = [e.id for e in recent if fam(e) == f][-2:]
        if fp.get(f, 0) == 0 and before:
            emerging.append({"kind": "new_work", "text": f"New {wsn}: {f} ({k} events, none in the {_fmt(span)} before)",
                             "cites": cite(engine, (), events=ex)})
        elif k >= 2 * fp.get(f, 0) + 4:
            emerging.append({"kind": "rising", "text": f"{f} is rising: {k} events, up from {fp.get(f, 0)}",
                             "cites": cite(engine, (), events=ex)})
    for g in groups:
        if g["shifted_from"]:
            emerging.append({"kind": "shift", "text": f"{g['group']} moved from mostly {g['shifted_from']} to {g['doing']}",
                             "cites": g["cites"]})
        elif g["trend"] == "new":
            emerging.append({"kind": "group_active", "text": f"{g['group']} became active ({g['active']} {noun}s)",
                             "cites": g["cites"]})
    emerging = emerging[:8]

    act = [g for g in groups if g["active"]]
    if act:
        lead = act[0]
        summary = (f"In the last {_fmt(span)}: {len(act)} of {len(groups)} {plural(gnoun)} active. "
                   f"{lead['group']} is busiest ({lead['active']} {noun}s, mostly {lead['doing']}"
                   + (f", on {lead['where']}" if lead["where"] else "") + ")."
                   + (f" Emerging: {emerging[0]['text']}." if emerging else ""))
    else:
        tot = Counter(fam(e) for e in recent if fam(e) not in NOT_WORK)
        summary = (f"In the last {_fmt(span)}: {len(recent)} events, mostly " + ", ".join(f for f, _ in tot.most_common(3))
                   + "." if recent else f"Nothing in the last {_fmt(span)}.")
    return {"span": _fmt(span), "group_noun": gnoun, "group_plural": plural(gnoun), "groups": groups, "emerging": emerging, "summary": summary,
            "by_identity": by_identity}
