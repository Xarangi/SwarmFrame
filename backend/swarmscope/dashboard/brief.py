"""The Brief: what a person needs in the first ten seconds, computed from the Executive's state.

Incidents are deduplicated and grouped (many "N agents converged on X" become one row with a count), banded into
three severities a person can act on (ACT / LOOK / WATCH), and given a recommended next step. The status sentence is
kept consistent with what is open, and recent briefing entries are grouped into a short "what changed" list.

This runs for every snapshot and in every LLM mode, so the dashboard's first screen never depends on how the
Executive phrased its headlines.
"""
from __future__ import annotations

import re
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from swarmscope.engine import Engine

from swarmscope.dashboard.explain import explain

SEVERITIES = ("ACT", "LOOK", "WATCH")
_LEVEL = ["NONE", "INFO", "WATCH", "INVESTIGATE", "ALERT", "PAGE"]

# kind -> (group headline, plain verb for one, next step when nothing is investigating yet)
KINDS: dict[str, dict[str, str]] = {
    "convergence": {"many": "{n} shared {resource}s drew a crowd", "next": "Check whether these {agent}s were meant to work together",
                    "next_control": "Check whether these {agent}s were meant to work together; pause them if not"},
    "reuse": {"many": "{n} pieces of content reused without a visible source", "next": "Look for a shared upstream source"},
    "rate_surge": {"many": "{n} workstreams surged", "next": "Watch; investigate if it lasts another window"},
    "burst": {"many": "{n} {resource}s saw a burst of activity", "next": "Watch; investigate if it lasts another window"},
    "new_method": {"many": "{n} {resource}s saw a method for the first time", "next": "Look at what the first {agent}s describe"},
    "new_actors": {"many": "{n} waves of new {agent}s", "next": "Confirm the new {agent}s were launched on purpose"},
    "say_do_mismatch": {"many": "{n} cases where {agent}s said one thing and did another",
                        "next": "Verify the claims against the activity record"},
    "environment": {"many": "{n} operator or environment events", "next": "Review the operator action and how the swarm responded"},
    "human_intervention": {"many": "{n} human interventions", "next": "Review the intervention and the response"},
    "focus_shift": {"many": "{n} {agent}s changed focus", "next": "Check whether the change of focus was asked for"},
    "alias": {"many": "{n} possible duplicate identities", "next": "Check whether these identities are the same {agent}"},
    "spatial_drift": {"many": "{n} {agent}s drifting away from where they usually work",
                      "next": "Open the World to see where it went and who it is near now"},
    "cohort_split": {"many": "{n} groups coming apart", "next": "Open the World and compare the two halves"},
    "reasoning_cue": {"many": "{n} agents whose private reasoning is worth reading",
                      "next": "Read the cited reasoning and what the {agent} did next"},
    "other": {"many": "{n} other findings", "next": "Open the evidence"},
}
_HEADLINE_KIND = [
    (re.compile(r"converged on", re.I), "convergence"), (re.compile(r"reused by", re.I), "reuse"),
    (re.compile(r"surged", re.I), "rate_surge"), (re.compile(r"^burst on", re.I), "burst"),
    (re.compile(r"^first '", re.I), "new_method"), (re.compile(r"new \w+s? appeared", re.I), "new_actors"),
    (re.compile(r"said|claim", re.I), "say_do_mismatch"), (re.compile(r"operator|stop|denied", re.I), "environment"),
]
_SIGMA = re.compile(r"\(?\s*(\d+(?:\.\d+)?)σ\s*\)?")
_CHANGE_TEXT = {"NEW": "New finding", "UPDATE": "Updated", "REVISED": "Revised assessment", "STATUS": "Status",
                "CONTROL": "Control", "HUMAN": "You"}


def plain(text: str) -> str:
    """Rewrite statistical shorthand into words: '(53.0σ)' -> '(far above usual)'. A z-score is not a ratio, so it
    is never shown as 'N× usual'; the explanation gives the real ratio from the counts."""
    def rep(m: re.Match) -> str:
        v = float(m.group(1))
        return "(far above usual)" if v >= 6 else "(well above usual)" if v >= 3 else "(above usual)"
    return _SIGMA.sub(rep, text).replace("against a usual", "vs a usual")


_KIND_ALIAS = {"content_reuse": "reuse"}           # watcher kind -> Brief kind


def _observation(engine: "Engine", reports: list[Any], scope: str) -> Any | None:
    """The observation behind an incident: the most severe one about its own scope (a report can carry several)."""
    obs = []
    for r in reports:
        for oid in (r.observations or [])[:12]:
            o = engine.store.get("Observation", oid)
            if o is not None and _KIND_ALIAS.get(o.kind, o.kind) in KINDS:
                obs.append(o)
    own = [o for o in obs if o.scope == scope] or obs
    return max(own, key=lambda o: o.severity) if own else None


def _kind(engine: "Engine", reports: list[Any], title: str, scope: str, obs: Any | None = None) -> str:
    """The finding's kind: from its observation, else from the wording of its title."""
    o = obs if obs is not None else _observation(engine, reports, scope)
    if o is not None:
        return _KIND_ALIAS.get(o.kind, o.kind)
    for rx, k in _HEADLINE_KIND:
        if rx.search(title):
            return k
    return "other"


def _evidence(engine: "Engine", reports: list[Any]) -> str:
    seen = set()
    for r in reports[-4:]:
        for cid in r.claims[:8]:
            c = engine.store.get("Claim", cid)
            if c is not None:
                seen.add(c.status.value if hasattr(c.status, "value") else str(c.status))
    if "OBSERVED" in seen:
        return "observed"
    if "DERIVED" in seen:
        return "derived"
    if "SELF_REPORTED" in seen:
        return "claimed"
    return "inferred" if seen else "observed"


def _cites(engine: "Engine", inc: Any, reports: list[Any]) -> list[dict[str, Any]]:
    """The sources behind one finding: the newest reports' claims, then the events under them; for a finding raised
    without monitor reports (an analyst's escalation), the evidence its escalation history cites. Cached per state."""
    from swarmscope.dashboard.cites import cite
    # the report whose headline is the finding's title first, so source [1] is about what the row says
    ranked = sorted(reports[-6:], key=lambda r: (getattr(r, "headline", None) != inc.title, -reports.index(r)))
    ids = list(dict.fromkeys(c for r in ranked[:4] for c in r.claims[:4]))
    extra: list[str] = []
    for h in reversed(getattr(inc, "history", None) or []):
        for x in getattr(h, "evidence", None) or []:
            (ids if str(x).startswith("clm_") else extra).append(x)
    ids = list(dict.fromkeys(ids))
    extra = list(dict.fromkeys(extra))[:4]
    cache = engine.__dict__.setdefault("_cite_cache", {})
    key = (inc.id, tuple(ids), tuple(extra))
    if key not in cache:
        if len(cache) > 4000:
            cache.clear()
        cache[key] = cite(engine, ids, events=extra, max_claims=3, events_per_claim=2)
    return cache[key]


_INNOCENT = re.compile(r"corroborate the report|corroborated by the record|no sign of coordination|"
                       r"common upstream source|shared assignment|is the innocent reading|coordinated on this \w+ through chat",
                       re.I)


def _explained_away(inv: Any) -> bool:
    """An investigation concluded and found the innocent reading (the report is backed by the record, and so on)."""
    return bool(inv is not None and inv.status == "concluded" and inv.conclusion and _INNOCENT.search(inv.conclusion))


LASTING = {"say_do_mismatch", "environment", "human_intervention", "alias", "convergence", "reuse"}


def _severity(inc: Any, inv: Any, kind: str) -> str:
    lvl = _LEVEL.index(inc.level.value if hasattr(inc.level, "value") else str(inc.level))
    r = inc.risk
    score = max(r.impact, r.scope, r.coordination_evidence, r.external_capability) * 0.6 + r.evidence_strength * 0.4
    if inv is not None and inv.status in ("running", "open"):
        return "ACT" if lvl >= 5 else "LOOK"
    if inc.status == "open":
        if lvl >= 5 or (lvl >= 4 and score >= 0.5):
            return "ACT"
        return "LOOK" if lvl >= 3 else "WATCH"
    # monitoring: an investigation concluded. Findings that do not fade with time (a false report, an operator
    # action, coordination) stay worth a look until a person dismisses them; rate changes drop to watching.
    if lvl >= 4 or (lvl >= 3 and kind in LASTING):
        return "LOOK"
    return "WATCH"


def _fresh(now: datetime, opened: datetime, last: datetime, window: timedelta) -> tuple[str, str]:
    if now - opened <= 2 * window:
        return "new", "new"
    if now - last <= 3 * window:
        return "updated", "updated"
    q = now - last
    h = q.total_seconds() / 3600
    return "quiet", (f"quiet {h / 24:.0f} d" if h >= 48 else f"quiet {h:.0f} h" if h >= 1 else f"quiet {max(1, round(h * 60))} min")


def _first_sentence(s: str, n: int = 150) -> str:
    s = (s or "").strip().split(". ")[0].rstrip(".")
    return (s[: n - 1] + "…") if len(s) > n else s


def swap_words(text: str, words: dict[str, str]) -> str:
    """Show the viewer's own nouns (Settings > Words): replace whole words, keeping plural and capitals."""
    import re
    for src, dst in words.items():
        if not src or not dst or src == dst:
            continue
        def sub(m: "re.Match[str]") -> str:
            w = m.group(0)
            out = dst + ("s" if w.lower().endswith("s") and not src.endswith("s") else "")
            return out[0].upper() + out[1:] if w[0].isupper() else out
        text = re.sub(rf"\b{re.escape(src)}s?\b", sub, text, flags=re.IGNORECASE)
        art = "an" if dst[:1].lower() in "aeiou" else "a"           # "an agent" -> "a bot"
        text = re.sub(rf"\b([Aa])n? ({re.escape(dst)})\b",
                      lambda m: (art.capitalize() if m.group(1) == "A" else art) + " " + m.group(2), text)
    return text


def catalog_summary(engine: "Engine", noun: str, rnoun: str) -> dict[str, Any] | None:
    """For historical catalogs (source.yaml `catalog: true`): the whole record so far, not the last few windows.
    Counts only, from the event table, clipped to the replay clock; no record text is read."""
    now = engine.now()
    q = engine.store.scalar
    try:
        total = int(q("SELECT count(*) FROM events WHERE ts <= ?", [now]) or 0)
        if not total:
            return None
        first = q("SELECT min(ts) FROM events WHERE ts <= ?", [now])
        d90, d180, d30 = now - timedelta(days=90), now - timedelta(days=180), now - timedelta(days=30)
        r90 = int(q("SELECT count(*) FROM events WHERE ts > ? AND ts <= ?", [d90, now]) or 0)
        p90 = int(q("SELECT count(*) FROM events WHERE ts > ? AND ts <= ?", [d180, d90]) or 0)
        r30 = int(q("SELECT count(*) FROM events WHERE ts > ? AND ts <= ?", [d30, now]) or 0)
        p30 = int(q("SELECT count(*) FROM events WHERE ts > ? AND ts <= ?", [d30 - timedelta(days=30), d30]) or 0)
        targets = int(q("SELECT count(DISTINCT object) FROM events WHERE ts <= ? AND object IS NOT NULL", [now]) or 0)
        top = engine.store.sql("SELECT object, count(*) AS n FROM events WHERE ts <= ? AND object IS NOT NULL "
                               "GROUP BY object ORDER BY n DESC LIMIT 3", [now])
        fams = engine.store.sql("SELECT family, count(*) AS n, count(*) FILTER (WHERE ts > ?) AS recent, "
                                "count(*) FILTER (WHERE ts > ? AND ts <= ?) AS before FROM events WHERE ts <= ? "
                                "GROUP BY family ORDER BY n DESC", [d180, d180 - timedelta(days=180), d180, now])
        sig = int(q("SELECT count(*) FROM events WHERE ts <= ? AND json_extract_string(attributes, '$.confidence') = "
                    "'significant'", [now]) or 0)
    except Exception:
        return None
    label = engine.label if hasattr(engine, "label") else (lambda x: x)
    span = f"{first:%b %Y} to {now:%b %Y}" if first else f"to {now:%b %Y}"
    parts = [f"{total:,} {noun}s, {span}."]
    if p90 >= 20:
        ratio = r90 / p90
        trend = (f"up from {p90:,} in the 90 days before" if ratio >= 1.3 else
                 f"down from {p90:,} in the 90 days before" if ratio <= 0.77 else
                 f"about the same as the 90 days before ({p90:,})")
        parts.append(f"The last 90 days had {r90:,}, {trend}.")
    if top:
        tops = ", ".join(f"{label(t['object'])} ({100 * t['n'] / total:.0f}%)" for t in top)
        parts.append(f"Most targeted: {tops}.")
    if fams:
        f0 = fams[0]
        line = f"{str(f0['family']).replace('_', ' ')} is the most common method ({100 * f0['n'] / total:.0f}%)"
        best = None
        for f in fams:
            rt, bt = sum(x["recent"] for x in fams), sum(x["before"] for x in fams)
            if rt >= 30 and bt >= 30:
                a, b = 100 * f["before"] / bt, 100 * f["recent"] / rt
                if abs(b - a) >= 5 and (best is None or abs(b - a) > abs(best[2] - best[1])):
                    best = (f["family"], a, b)
        if best:
            line += f"; {str(best[0]).replace('_', ' ')} went from {best[1]:.0f}% to {best[2]:.0f}% of {noun}s over the last six months"
        parts.append(line[:1].upper() + line[1:] + ".")
    sig_pct = round(100 * sig / total)
    parts.append(f"{sig_pct}% are graded significant by the source; the rest only suggestive.")
    field = [{"family": f["family"], "actors": int(f["recent"] or f["n"])} for f in fams[:8]]
    head = parts[:2] if p90 >= 20 else parts[:1]
    return {"status": " ".join(head), "detail": " ".join(parts[len(head):]), "total": total, "r30": r30, "p30": p30, "targets": targets, "sig_pct": sig_pct,
            "field": {"families": field, "active": min(420, max(60, r90))}}


def brief_digest(engine: "Engine") -> dict[str, Any]:
    out = _brief_digest(engine)
    if (getattr(engine, "pack", None) is not None and engine.pack.source.get("catalog")):
        c = catalog_summary(engine, out["terms"]["agent"], out["terms"]["resource"])
        if c:
            out["catalog"] = True
            out["status"] = c["status"]
            out["status_detail"] = c["detail"]
            noun = out["terms"]["agent"]
            ch = (c["r30"] - c["p30"]) / c["p30"] * 100 if c["p30"] else None
            extra = {
                "total": {"value": c["total"], "label": f"{noun}s so far", "sub": "the whole record"},
                "recent": {"value": c["r30"], "label": "last 30 days",
                           "sub": (f"{ch:+.0f}% on the 30 before" if ch is not None else "no earlier month")},
                "targets": {"value": c["targets"], "label": f"{out['terms']['resource']}s reached", "sub": "distinct"},
                "significant": {"value": c["sig_pct"], "unit": "%", "label": "graded significant", "sub": "by the source"},
            }
            hist = _history(engine)
            for k, g in extra.items():
                g["series"] = [h[1].get(k, 0) for h in list(hist)[-24:]]
                if hist:
                    hist[-1][1][k] = g["value"]
            out["glance"].update(extra)
            out["field"] = c["field"]
    custom = getattr(engine.dashboard.spec, "terminology", None) or {}
    words = {out["terms"][k]: v.strip() for k, v in custom.items() if k in out["terms"] and v.strip()}
    if not words:
        return out
    sw = lambda t: swap_words(t, words) if isinstance(t, str) else t      # noqa: E731
    out["status"], out["attention_line"] = sw(out["status"]), sw(out["attention_line"])
    if out.get("status_detail"):
        out["status_detail"] = sw(out["status_detail"])
    for it in out["items"]:
        for k in ("headline", "detail", "next"):
            if k in it:
                it[k] = sw(it[k])
    for c in out["changes"]:
        c["text"] = sw(c["text"])
    for g in out["glance"].values():
        g["label"], g["sub"] = sw(g["label"]), sw(g["sub"])
    out["terms"] = {k: custom.get(k, "").strip() or v for k, v in out["terms"].items()}
    return out


def _brief_digest(engine: "Engine") -> dict[str, Any]:
    st, now = engine.exec_state, engine.now()
    noun = engine.profile.entity_noun
    rnoun = getattr(engine.profile, "resource_noun", "resource") or "resource"
    terms = {"agent": noun, "resource": rnoun}
    settings = engine.dashboard.spec.brief if hasattr(engine.dashboard.spec, "brief") else None
    snoozed = set(getattr(settings, "snoozed", []) or [])
    pinned = list(getattr(settings, "pinned", []) or [])
    window = getattr(engine.clock, "window", timedelta(minutes=10))
    has_control = getattr(engine, "control", None) is not None
    ledger = engine.cases() if hasattr(engine, "cases") else None
    human = getattr(getattr(getattr(engine, "agent_org", None), "topology", None), "human", None) or {}
    interrupt = _LEVEL.index(human.get("interrupt_at", "ALERT")) if human.get("interrupt_at", "ALERT") in _LEVEL else 4
    invs = {i.id: i for i in engine.store.all("Investigation")}

    # ---------------------------------------------------------------- one row per incident
    rows: list[dict[str, Any]] = []
    for inc in st.active_incidents:
        if inc.status == "resolved" or inc.id in snoozed or inc.id in getattr(engine, "dismissed", ()):
            continue
        reports = [r for r in (engine.store.get("MonitorReport", rid) for rid in inc.reports[-8:]) if r is not None]
        inv = invs.get(inc.investigation) if inc.investigation else None
        obs = _observation(engine, reports, inc.scope)
        kind = _kind(engine, reports, inc.title, inc.scope, obs)
        last = max([r.window_end for r in reports] or [inc.opened])
        fresh, fresh_text = _fresh(now, inc.opened, last, window)
        sev = _severity(inc, inv, kind)
        explained = _explained_away(inv)
        if explained:
            sev = "WATCH"                                  # the check found the innocent reading: keep it, quietly
        overdue = bool(ledger and ledger.overdue(inc, window)) and not explained   # checked and innocent: no alarm
        if overdue:
            sev = "ACT"                                  # an unacknowledged ALERT past its SLA leads the Brief
        k = KINDS.get(kind, KINDS["other"])
        if inv is not None and inv.status in ("running", "open"):
            nxt = "Open the investigation (running)"
            action = "investigation"
        elif inv is not None and inv.conclusion and explained:
            nxt = "Checked: " + _first_sentence(inv.conclusion).rstrip(".") + ". That is the innocent reading, so it stays on watch."
            action = "investigation"
        elif inv is not None and inv.conclusion:
            nxt = "Finding: " + _first_sentence(inv.conclusion)
            action = "investigation"
        else:
            nxt = (k.get("next_control") if has_control and "next_control" in k else k["next"]).format(**terms)
            action = "investigate"
        r = inc.risk
        rows.append({
            "id": inc.id, "kind": kind, "severity": sev, "headline": plain(inc.title), "scope": inc.scope,
            "label": engine._scope_label(inc.scope) if hasattr(engine, "_scope_label") else inc.scope,
            "fresh": fresh, "fresh_text": fresh_text, "opened": inc.opened.isoformat(), "last": last.isoformat(),
            "evidence": _evidence(engine, reports), "cites": _cites(engine, inc, reports), "explain": explain(engine, obs.kind if obs else kind, obs, plain(inc.title)), "next": nxt, "action": action,
            "investigation": inc.investigation, "investigation_status": inv.status if inv else None,
            "status": inc.status, "level": inc.level.value if hasattr(inc.level, "value") else str(inc.level),
            "reports": len(inc.reports), "pinned": inc.id in pinned,
            "axes": {"coordination": r.coordination_evidence, "impact": r.impact, "scope": r.scope,
                     "external": r.external_capability, "novelty": r.novelty, "evidence": r.evidence_strength},
            # the ledger: who saw it, how it got here, whether a person has taken receipt
            "views": list(inc.views), "owner": inc.owner, "pending_level": inc.pending_level,
            "acknowledged": inc.acknowledged.isoformat() if inc.acknowledged else None,
            "acknowledged_by": inc.acknowledged_by, "overdue": overdue,
            "needs_ack": _LEVEL.index(inc.level.value if hasattr(inc.level, "value") else str(inc.level)) >= interrupt
                         and inc.acknowledged is None and inc.status != "resolved",
            "history": [{"ts": h.ts.isoformat(), "level": h.level, "by": h.by, "reason": plain(h.reason),
                         "held": h.held, "evidence": h.evidence} for h in inc.history[-12:]],
        })

    by_id = {i.id: i for i in st.active_incidents}
    for x in rows:                                        # an analyst's own finding: say who raised it and why it shows
        inc = by_id.get(x["id"])
        if x["kind"] == "other" and inc is not None and inc.history:
            who = inc.history[0].by
            x["explain"] = {**x["explain"],
                            "why": f"An analyst ({who}) flagged {x['label']} as worth attention while reading it; this is "
                                   f"its summary, not a fixed rule.",
                            "check": "Open the sources, or ask the live column what the analyst saw."}

    # ---------------------------------------------------------------- group duplicates by kind
    order = {s: i for i, s in enumerate(SEVERITIES)}
    by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for x in rows:
        by_kind[x["kind"]].append(x)
    items: list[dict[str, Any]] = []
    for kind, xs in by_kind.items():
        xs.sort(key=lambda x: (order[x["severity"]], x["last"]), reverse=False)
        loose = [x for x in xs if x["pinned"]]
        rest = [x for x in xs if not x["pinned"]]
        if len(rest) >= 3:
            top = sorted(rest, key=lambda x: (order[x["severity"]], -_n(x["headline"]), x["last"]))[0]
            sev = min((x["severity"] for x in rest), key=lambda s: order[s])
            fresh = "new" if any(x["fresh"] == "new" for x in rest) else "updated" if any(
                x["fresh"] == "updated" for x in rest) else "quiet"
            running = [x for x in rest if x["investigation_status"] in ("running", "open")]
            items.append({
                **top, "id": f"group:{kind}", "group": True, "count": len(rest), "members": [x["id"] for x in rest],
                "member_rows": rest[:30], "severity": sev, "fresh": fresh,
                "fresh_text": fresh if fresh != "quiet" else top["fresh_text"],
                "headline": KINDS.get(kind, KINDS["other"])["many"].format(n=len(rest), **terms),
                "detail": f"Most serious: {top['explain']['what'] if top.get('explain', {}).get('what') else top['headline']}",
                "next": KINDS.get(kind, KINDS["other"])["next"].format(**terms).rstrip(".") + (f" ({len(running)} already being investigated)" if running
                                        else " (start with the most serious)"),
                "action": "group", "pinned": f"group:{kind}" in pinned,
            })
        else:
            loose += rest
        for x in loose:
            items.append({**x, "group": False, "count": 1, "members": [x["id"]]})
    items.sort(key=lambda x: (not x.get("overdue"), not x.get("needs_ack"), not x.get("pinned"), order[x["severity"]],
                              {"new": 0, "updated": 1, "quiet": 2}[x["fresh"]], -x["count"]))
    counts = {s: sum(1 for x in items if x["severity"] == s) for s in SEVERITIES}
    raw = {s: sum(1 for x in rows if x["severity"] == s) for s in SEVERITIES}

    # ---------------------------------------------------------------- status sentence, kept consistent
    status = st.population_state or ""
    pop = engine.population_stats()
    open_n = len(items)
    if open_n and status.lower().startswith("no "):
        status = (f"Quiet in the most recent windows; {open_n} open finding{'s' if open_n != 1 else ''}"
                  + (f" ({len(rows)} before grouping)." if len(rows) > open_n else "."))
    elif not status:
        status = "Nothing observed yet." if not pop.get("total_events_seen") else ""
    if counts["ACT"]:
        attention_line = (f"{counts['ACT']} finding{'s' if counts['ACT'] != 1 else ''} need{'s' if counts['ACT'] == 1 else ''} "
                          f"a decision" + (f", {counts['LOOK']} more worth a look." if counts["LOOK"] else "."))
    elif counts["LOOK"]:
        attention_line = f"Nothing needs a decision; {counts['LOOK']} finding{'s are' if counts['LOOK'] != 1 else ' is'} worth a look."
    elif rows:
        attention_line = "Nothing needs attention; the open findings are being watched."
    else:
        attention_line = "Nothing needs attention."

    # ---------------------------------------------------------------- what changed, grouped
    briefing = sorted(engine.store.all("BriefingEntry"), key=lambda b: b.ts)[-40:]
    changes: list[dict[str, Any]] = []
    for b in reversed(briefing):
        kind = b.kind.value if hasattr(b.kind, "value") else str(b.kind)
        if changes and changes[-1]["kind"] == kind and changes[-1]["ts"][:16] == b.ts.isoformat()[:16]:
            changes[-1]["n"] += 1
            continue
        if len(changes) >= 6:
            break
        changes.append({"ts": b.ts.isoformat(), "kind": kind, "label": _CHANGE_TEXT.get(kind, kind.title()),
                        "text": plain(b.text), "n": 1, "id": b.id})
    plural = {"NEW": "new findings", "UPDATE": "updates", "REVISED": "revised assessments", "STATUS": "status notes",
              "CONTROL": "control events"}
    for c in changes:
        if c["n"] > 1 and c["kind"] in plural:
            c["text"] = f"{c['n']} {plural[c['kind']]} · latest: {c['text']}"

    # ---------------------------------------------------------------- glance numbers, with history for sparklines
    health = engine.monitor_health()
    cov = health.get("coverage", 0.0) or 0.0
    running = sum(1 for i in invs.values() if i.status in ("running", "open"))
    ident = engine.profile.capabilities.get("identities")
    hrs = pop.get("hours", 0) or 0
    span = f"{hrs:.0f} h" if hrs >= 1 else f"{max(1, round(hrs * 60))} min"
    recent_events = sum(f.get("now", 0) for f in pop.get("families", []))
    glance = {
        "active": {"value": pop.get("active", 0) if (ident and ident.present) else recent_events,
                   "label": f"{noun}s active" if (ident and ident.present) else f"{noun}s", "sub": f"last {span}"},
        "attention": {"value": counts["ACT"] + counts["LOOK"], "label": "need attention",
                      "sub": (f"{counts['ACT']} act · {counts['LOOK']} look" if counts["ACT"] + counts["LOOK"]
                              else "all clear")},
        "watching": {"value": counts["WATCH"], "label": "being watched", "sub": "no action needed"},
        "investigating": {"value": running, "label": "being looked into", "sub": "investigations running"},
        "coverage": {"value": round(cov * 100), "unit": "%", "label": "read closely",
                     "sub": "thin" if cov < 0.15 else "fair" if cov < 0.4 else "good"},
        "events": {"value": pop.get("total_events_seen", 0), "label": "events so far", "sub": "since the start"},
    }
    if getattr(engine, "control", None) is not None:
        glance["approvals"] = {"value": len(engine.control.summary().get("pending", [])), "label": "awaiting you",
                               "sub": "approvals"}
    hist = _history(engine)
    idx = getattr(engine.clock, "index", 0)
    if not hist or hist[-1][0] != idx:
        hist.append((idx, {k: v["value"] for k, v in glance.items()}))
    for k in glance:
        glance[k]["series"] = [h[1].get(k, 0) for h in list(hist)[-24:]]

    cases = ledger.summary(window) if ledger else {}
    return {"status": status, "attention_line": attention_line, "updated": st.ts.isoformat() if st.ts else None,
            "version": st.version, "counts": counts, "raw_counts": raw, "items": items, "changes": changes, "glance": glance,
            "terms": terms, "identities": bool(ident and ident.present), "cases": cases, "overview": _safe_overview(engine)}


def _safe_overview(engine: "Engine") -> dict[str, Any] | None:
    """What everyone is doing and what is emerging, whatever the severity (dashboard/overview.py)."""
    try:
        from swarmscope.dashboard.overview import overview
        return overview(engine)
    except Exception as exc:                           # never let the overview break the Brief
        engine.router.errors.append(f"overview: {type(exc).__name__}: {exc}")
        return None


def _n(headline: str) -> int:
    m = re.match(r"\D*(\d+)", headline)
    return int(m.group(1)) if m else 0


def _history(engine: "Engine") -> deque:
    if not hasattr(engine, "_glance_hist"):
        engine._glance_hist = deque(maxlen=60)
    return engine._glance_hist


def incident_detail(engine: "Engine", inc_id: str) -> dict[str, Any] | None:
    """Everything the drawer needs for one finding (or a grouped finding)."""
    d = brief_digest(engine)
    for it in d["items"]:
        if it["id"] == inc_id or inc_id in it["members"]:
            row = it if it["id"] == inc_id else next((m for m in it.get("member_rows", []) if m["id"] == inc_id), it)
            inc = next((i for i in engine.exec_state.active_incidents if i.id == row["id"]), None)
            claims = []
            if inc is not None:
                for rid in inc.reports[-6:]:
                    r = engine.store.get("MonitorReport", rid)
                    if r is None:
                        continue
                    for cid in r.claims[:6]:
                        c = engine.store.get("Claim", cid)
                        if c is not None and all(x["id"] != c.id for x in claims):
                            claims.append({"id": c.id, "statement": plain(c.statement),
                                           "status": c.status.value if hasattr(c.status, "value") else str(c.status)})
            inv = engine.store.get("Investigation", row.get("investigation")) if row.get("investigation") else None
            return {**row, "claims": claims[:12],
                    "investigation_detail": {"id": inv.id, "title": inv.title, "status": inv.status,
                                             "conclusion": inv.conclusion} if inv else None,
                    "group_rows": it.get("member_rows") if it.get("group") and it["id"] == inc_id else None}
    return None
