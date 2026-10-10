"""The report for a dump: what happened, when, who, and what stands out, with the records behind every claim.

`build_report(engine)` reads an engine that has been run over the whole record (every watcher, monitor and the
analyst team have seen it) and assembles a structured report from structure only: counts, times, names, the
watchers' observations and the analysts' findings. Agent-written text is never copied in; a model writing the report
(analysis/writer.py) may read it through the evidence tools, marked untrusted. `to_markdown` renders the report in the
shape incident reviewers expect: a short TL;DR, a timeline tied to record ids, then the analysis.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from swarmscope.engine import Engine

KIND_TITLE = {
    "rate_surge": "Surges in activity", "burst": "Bursts of activity", "convergence": "Many {a}s on the same {r}",
    "reuse": "Text that spread between {a}s", "content_reuse": "Text that spread between {a}s", "propagation": "Text that spread between {a}s", "new_actors": "Waves of new {a}s",
    "environment": "How the environment responded", "human_intervention": "People stepping in",
    "say_do_mismatch": "What was said against what was done", "focus_shift": "Changes of focus", "alias": "Look-alike names",
    "new_method": "First-time methods", "reasoning_cue": "Reasoning worth reading", "spatial_drift": "Drift away from their group",
    "cohort_split": "Groups splitting apart",
}


def _p(n: int, w: str) -> str:
    return f"{n:,} {w}" + ("" if n == 1 else ("es" if w.endswith(("s", "sh", "ch")) else "s"))


def _t(d: datetime | None) -> str:
    return d.strftime("%Y-%m-%d %H:%M") if d else "?"


def _day(d: datetime) -> str:
    return d.strftime("%b %d").replace(" 0", " ")


def build_report(engine: "Engine", title: str = "") -> dict[str, Any]:
    from swarmscope.dashboard.explain import explain
    st = engine.store
    p = engine.profile
    a, r = p.entity_noun, getattr(p, "resource_noun", "resource") or "resource"
    ws = getattr(p, "workstream_noun", "workstream") or "workstream"
    lo, hi = st.time_range()
    n = st.count_events()
    lab = engine.label
    q = st.sql
    tot = q("SELECT count(DISTINCT actor) a, count(DISTINCT object) o, count(DISTINCT family) f, count(artifact) t FROM events")[0]

    # ---------------------------------------------------------------- activity over time
    days = [(row["d"], row["n"]) for row in q("SELECT date_trunc('day', ts) d, count(*) n FROM events GROUP BY d ORDER BY d")]
    fams = [(row["family"] or "other", row["n"]) for row in q("SELECT family, count(*) n FROM events GROUP BY family ORDER BY n DESC LIMIT 12")]
    acts = [(row["action"], row["n"]) for row in q("SELECT action, count(*) n FROM events GROUP BY action ORDER BY n DESC LIMIT 12")]
    peak = sorted(days, key=lambda x: -x[1])[:5]
    mean = n / max(1, len(days))
    hours = [(row["h"], row["n"]) for row in q("SELECT date_trunc('hour', ts) h, count(*) n FROM events GROUP BY h ORDER BY n DESC LIMIT 5")]

    def day_mix(d: datetime) -> list[tuple[str, int]]:
        return [(row["family"] or "other", row["n"]) for row in q(
            "SELECT family, count(*) n FROM events WHERE date_trunc('day', ts) = ? GROUP BY family ORDER BY n DESC LIMIT 3", [d])]

    def first_events(where: str, params: list[Any], k: int = 3) -> list[str]:
        return [row["id"] for row in q(f"SELECT id FROM events WHERE {where} ORDER BY ts LIMIT {k}", params)]

    # ---------------------------------------------------------------- who and where
    top_actors = q("SELECT actor, count(*) n, count(DISTINCT object) o, min(ts) f, max(ts) l FROM events "
                   "WHERE actor IS NOT NULL GROUP BY actor ORDER BY n DESC LIMIT 12")
    top_objects = q("SELECT object, count(*) n, count(DISTINCT actor) a, min(ts) f, max(ts) l FROM events "
                    "WHERE object IS NOT NULL GROUP BY object ORDER BY a DESC, n DESC LIMIT 12")
    groups = q("SELECT actor_group g, count(*) n, count(DISTINCT actor) a, min(ts) f, max(ts) l FROM events "
               "WHERE actor_group IS NOT NULL GROUP BY g ORDER BY n DESC LIMIT 15")
    group_rows = []
    for g in groups:
        mix = q("SELECT family, count(*) n FROM events WHERE actor_group = ? GROUP BY family ORDER BY n DESC LIMIT 3", [g["g"]])
        where = q("SELECT object, count(*) n FROM events WHERE actor_group = ? AND object IS NOT NULL GROUP BY object "
                  "ORDER BY n DESC LIMIT 3", [g["g"]])
        group_rows.append({"group": g["g"], "events": g["n"], "members": g["a"], "first": _t(g["f"]), "last": _t(g["l"]),
                           "mostly": [(m["family"] or "other", m["n"]) for m in mix],
                           "where": [(lab(w["object"]), w["n"]) for w in where],
                           "cites": first_events("actor_group = ?", [g["g"]], 2)})

    # ---------------------------------------------------------------- the environment (moderators, operators, denials)
    env = q("SELECT actor, action, count(*) n, min(ts) f, max(ts) l FROM events WHERE action LIKE 'environment.%' "
            "GROUP BY actor, action ORDER BY n DESC LIMIT 10")
    env_days = q("SELECT date_trunc('day', ts) d, count(*) n FROM events WHERE action LIKE 'environment.%' GROUP BY d "
                 "ORDER BY n DESC LIMIT 6")

    # ---------------------------------------------------------------- what stands out: the watchers' observations
    obs = sorted(st.all("Observation"), key=lambda o: o.window_end)
    clusters: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for o in obs:
        if o.kind in ("audit",):                      # the team's own spot checks, not findings about the swarm
            continue
        clusters[(o.kind, o.scope)].append(o)
    found = []
    for (kind, scope), xs in clusters.items():
        top = max(xs, key=lambda o: o.severity)
        ex = explain(engine, kind, top, top.title)
        ev = []
        for o in sorted(xs, key=lambda o: -o.severity)[:4]:
            ev += [e.id for e in o.evidence if e.kind == "event"][:3]
        found.append({"kind": kind, "scope": scope, "where": engine._scope_label(scope), "title": top.title,
                      "what": ex.get("what") or top.title, "why": ex.get("why", ""), "benign": ex.get("benign", ""),
                      "check": ex.get("check", ""), "first": _t(xs[0].window_end), "last": _t(xs[-1].window_end),
                      "times": len(xs), "severity": round(max(o.severity for o in xs), 2),
                      "score": max(o.severity for o in xs) * (1 + min(len(xs), 20) / 10),
                      "evidence": list(dict.fromkeys(ev))[:8]})
    found.sort(key=lambda f: -f["score"])
    by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in found:
        by_kind[f["kind"]].append(f)

    # ---------------------------------------------------------------- the analysts' findings (cases)
    cases = []
    for i in list(engine.exec_state.active_incidents)[:30]:
        cases.append({"title": i.title, "level": i.level.value if hasattr(i.level, "value") else str(i.level),
                      "where": engine._scope_label(i.scope), "opened": _t(i.opened), "seen_by": i.views[:4],
                      "status": i.status})
    concluded = []
    for inv in st.all("Investigation")[:40] if hasattr(st, "all") else []:
        concl = getattr(inv, "conclusion", None) or getattr(inv, "summary", None)
        if concl:
            concluded.append({"question": getattr(inv, "question", "") or getattr(inv, "title", ""), "answer": str(concl)[:600]})

    # ---------------------------------------------------------------- the timeline: one line per notable moment
    timeline: list[dict[str, Any]] = []
    if lo:
        timeline.append({"ts": _t(lo), "text": f"First record. {_p(n, 'record')} follow over {_p((hi - lo).days + 1, 'day')}.",
                         "cites": first_events("1=1", [], 2)})
    if len(days) >= 3:
        for d, c in sorted(peak[:3], key=lambda x: x[0]):
            mix = ", ".join(f"{f} {v:,}" for f, v in day_mix(d))
            timeline.append({"ts": d.strftime("%Y-%m-%d"), "text": f"Busiest day: {c:,} records ({c / max(mean, 1):.1f}x the daily average), mostly {mix}.",
                             "cites": first_events("date_trunc('day', ts) = ?", [d], 2)})
    seen_kind: set[str] = set()
    per_kind: Counter = Counter()
    for f in sorted(found[:40], key=lambda f: (-f["score"]))[:30]:
        key = f"{f['kind']}|{f['where']}"
        if key in seen_kind or per_kind[f["kind"]] >= 3 or len(seen_kind) >= 14:
            continue
        seen_kind.add(key)
        per_kind[f["kind"]] += 1
        timeline.append({"ts": f["first"], "text": f["what"], "cites": f["evidence"][:2], "kind": f["kind"]})
    for e in env_days[:3]:
        if e["n"] >= 3:
            first = q("SELECT min(ts) t FROM events WHERE action LIKE 'environment.%' AND date_trunc('day', ts) = ?", [e["d"]])[0]["t"]
            timeline.append({"ts": _t(first), "text": f"{e['n']:,} environment actions that day (deletions, stops or denials), the first at this time.",
                             "cites": first_events("action LIKE 'environment.%' AND date_trunc('day', ts) = ?", [e["d"]], 2)})
    if hi:
        timeline.append({"ts": _t(hi), "text": "Last record.", "cites": [row["id"] for row in q("SELECT id FROM events ORDER BY ts DESC LIMIT 1")]})
    timeline.sort(key=lambda x: x["ts"] if len(x["ts"]) > 10 else x["ts"] + " 00:00")

    # ---------------------------------------------------------------- the short version
    caps = {k: c for k, c in p.capabilities.items()}
    has = [k.replace("_", " ") for k, c in caps.items() if c.present]
    lacks = [k.replace("_", " ") for k, c in caps.items() if not c.present]
    tldr = []
    if lo:
        tldr.append(f"{_p(n, 'record')} between {_t(lo)} and {_t(hi)} UTC"
                    + (f", from {_p(tot['a'] or 0, a)}" if tot["a"] else "")
                    + (f" acting on {_p(tot['o'] or 0, r)}" if tot["o"] else "") + ".")
    common = f"the most common {ws}s were " + ", ".join(f"{f} ({v:,})" for f, v in fams[:3])
    if peak and len(days) >= 3:
        d, c = peak[0]
        tldr.append(f"Activity peaked on {_day(d)} ({c:,} records, {c / max(mean, 1):.1f}x the daily average); {common}.")
    elif hours:
        h0, c = hours[0]
        tldr.append(f"The busiest hour was {h0:%H:00} on {_day(h0)} ({c:,} records); {common}.")
    if group_rows:
        g = group_rows[0]
        tldr.append(f"{len(group_rows)} groups are active; the busiest, {g['group']}, has {_p(g['members'], a)} and "
                    f"{_p(g['events'], 'record')}.")
    if found:
        kinds_seen, top = set(), []
        for f in found:
            if f["kind"] not in kinds_seen:
                kinds_seen.add(f["kind"])
                top.append(f)
            if len(top) == 2:
                break
        tldr.append("What stands out: " + "; ".join(f["what"].split(". ")[0].rstrip(".") for f in top) + ".")
    if env:
        e0 = env[0]
        tldr.append(f"The environment pushed back: {_p(sum(x['n'] for x in env), 'environment action')} "
                    f"(the most by {lab(e0['actor'])}, {e0['n']:,}).")
    tldr.append("This reading is rules-based: counts, timing and fixed detectors, not an understanding of what the "
                f"{a}s wrote. Confidence: high for the counts and times, medium for the patterns, low for any motive.")

    return {
        "title": title or (f"What happened in {engine.meta.get('dump_name')}" if engine.meta.get("dump_name") else f"What happened in {p.title}"), "source": p.title, "generated": datetime.utcnow().isoformat(timespec="seconds"),
        "span": {"start": _t(lo), "end": _t(hi), "days": ((hi - lo).days + 1) if lo else 0},
        "totals": {"records": n, "actors": tot["a"], "objects": tot["o"], "families": tot["f"], "texts": tot["t"]},
        "nouns": {"agent": a, "resource": r, "workstream": ws},
        "data": {"description": p.description, "has": has, "lacks": lacks, "naming": getattr(p, "naming", "") or "",
                 "files_used": engine.meta.get("files_used"), "files_skipped": engine.meta.get("files_skipped")},
        "tldr": tldr, "timeline": timeline,
        "activity": {"by_day": [(d.strftime("%Y-%m-%d"), c) for d, c in days], "peak_days": [(d.strftime("%Y-%m-%d"), c) for d, c in peak],
                     "peak_hours": [(h.strftime("%Y-%m-%d %H:00"), c) for h, c in hours], "by_family": fams, "by_action": acts,
                     "daily_mean": round(mean, 1)},
        "groups": group_rows,
        "actors": [{"name": lab(x["actor"]), "id": x["actor"], "events": x["n"], "objects": x["o"], "first": _t(x["f"]), "last": _t(x["l"])} for x in top_actors],
        "objects": [{"name": lab(x["object"]), "id": x["object"], "events": x["n"], "actors": x["a"], "first": _t(x["f"]), "last": _t(x["l"])} for x in top_objects],
        "environment": [{"by": lab(x["actor"]), "action": x["action"].split(".", 1)[1].replace("_", " "), "count": x["n"], "first": _t(x["f"]), "last": _t(x["l"])} for x in env],
        "findings": found[:40], "by_kind": {k: len(v) for k, v in by_kind.items()},
        "cases": cases, "investigations": concluded,
        "reading": {"windows": engine.windows_processed, "observations": len(obs), "llm": engine.router.mode,
                    "team": engine.team_choice.get("topology") if isinstance(engine.team_choice, dict) else None},
    }


def _cite(ids: list[str]) -> str:
    return " " + " ".join(f"`{i}`" for i in ids[:4]) if ids else ""


def to_markdown(rep: dict[str, Any]) -> str:
    nn = rep["nouns"]
    a, r = nn["agent"], nn["resource"]
    L: list[str] = [f"# {rep['title']}", ""]
    L += ["## TL;DR", "", " ".join(rep["tldr"]), ""]
    L += ["## Timeline", ""]
    for t in rep["timeline"]:
        L.append(f"- **{t['ts']}** {t['text']}{_cite(t.get('cites', []))}")
    L += ["", "## Analysis", ""]
    L += ["### The data", "",
          f"{rep['totals']['records']:,} records over {rep['span']['days']} days ({rep['span']['start']} to {rep['span']['end']} UTC): "
          f"{rep['totals']['actors'] or 0:,} {a}s, {rep['totals']['objects'] or 0:,} {r}s, {rep['totals']['families'] or 0} kinds of "
          f"activity, {rep['totals']['texts'] or 0:,} pieces of written text.", ""]
    if rep["data"]["has"]:
        L.append(f"It records {', '.join(rep['data']['has'])}." + (f" It cannot show {', '.join(rep['data']['lacks'])}." if rep["data"]["lacks"] else ""))
    if rep["data"].get("naming"):
        L += ["", f"About the names: {rep['data']['naming']}"]
    if rep["data"].get("files_skipped"):
        L += ["", f"Not used (no time field): {', '.join(rep['data']['files_skipped'])}."]
    L += ["", "### When it happened", "",
          f"On an average day there are {rep['activity']['daily_mean']:,} records. The busiest days:", ""]
    L += ["| Day | Records |", "| --- | ---: |"] + [f"| {d} | {c:,} |" for d, c in rep["activity"]["peak_days"]]
    L += ["", "The busiest hours: " + ", ".join(f"{h} ({c:,})" for h, c in rep["activity"]["peak_hours"]) + ".", ""]
    L += ["What the records are, by kind: " + ", ".join(f"{f} ({c:,})" for f, c in rep["activity"]["by_family"][:8]) + ".", ""]
    if rep["groups"]:
        L += ["### The groups", "", "| Group | Members | Records | Mostly | Where | Active |", "| --- | ---: | ---: | --- | --- | --- |"]
        for g in rep["groups"]:
            L.append(f"| {g['group']} | {g['members']} | {g['events']:,} | {', '.join(f for f, _ in g['mostly'])} | "
                     f"{', '.join(w for w, _ in g['where'])} | {g['first'][:10]} to {g['last'][:10]} |")
        L.append("")
    if rep["actors"]:
        L += [f"### The busiest {a}s", "", f"| {a.title()} | Records | {r.title()}s | Active |", "| --- | ---: | ---: | --- |"]
        L += [f"| {x['name']} | {x['events']:,} | {x['objects']:,} | {x['first'][:10]} to {x['last'][:10]} |" for x in rep["actors"][:10]]
        L.append("")
    if rep["objects"]:
        L += [f"### Where they converged", "", f"The {r}s the most {a}s acted on:", "",
              f"| {r.title()} | {a.title()}s | Records | Active |", "| --- | ---: | ---: | --- |"]
        L += [f"| {x['name']} | {x['actors']:,} | {x['events']:,} | {x['first'][:10]} to {x['last'][:10]} |" for x in rep["objects"][:10]]
        L.append("")
    if rep["environment"]:
        L += ["### How the environment responded", ""]
        L += [f"- {x['by']}: {x['count']:,} {x['action']} ({x['first']} to {x['last']})" for x in rep["environment"]]
        L.append("")
    if rep["findings"]:
        L += ["### What stands out", "", "Each item below was raised by a detector; the innocent reading is given beside it.", ""]
        kinds: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for f in rep["findings"]:
            kinds[f["kind"]].append(f)
        for kind, fs in sorted(kinds.items(), key=lambda kv: -max(f["score"] for f in kv[1])):
            L += [f"#### {KIND_TITLE.get(kind, kind.replace('_', ' ').title()).format(a=a, r=r)}", ""]
            for f in fs[:5]:
                conf = "High" if f["severity"] >= 0.75 and f["times"] >= 3 else "Medium" if f["severity"] >= 0.45 else "Low"
                L.append(f"- **{f['what']}** First seen {f['first']}, {_p(f['times'], 'time')} in all. "
                         f"{('Why it may matter: ' + f['why'] + ' ') if f['why'] else ''}"
                         f"{('Innocent reading: ' + f['benign'] + ' ') if f['benign'] else ''}Confidence: {conf}.{_cite(f['evidence'])}")
            if len(fs) > 5:
                L.append(f"- and {len(fs) - 5} more of this kind.")
            L.append("")
    if rep["cases"]:
        L += ["### What the analysts flagged", ""]
        L += [f"- {c['title']} ({c['level'].lower()}, {c['where']}, opened {c['opened']})" for c in rep["cases"][:12]]
        L.append("")
    if rep["investigations"]:
        L += ["### What the investigations concluded", ""]
        L += [f"- **{i['question']}** {i['answer']}" for i in rep["investigations"][:10]]
        L.append("")
    rd = rep["reading"]
    stg = rep.get("strategy") or {}
    comp = (stg.get("composition") or {})
    L += ["### How this was read", ""]
    if stg:
        L.append(f"The analyst team: **{stg.get('label') or stg.get('title')}**"
                 + (f". {comp['summary']}" if comp.get("summary") else f" ({', '.join(stg.get('roles') or [])}).") )
        for part in comp.get("parts") or []:
            if part["how"] != "off" and part["part"] not in ("lead",):
                L.append(f"- {part['title']} ({part['how'].replace('_', ' ')}): {part['reason']}"
                         + (f" ({part['evidence']})" if part.get("evidence") else ""))
        L.append("")
    L += [
          f"SwarmFrame replayed the whole record in {rd['windows']:,} windows through its watchers and analyst team "
          f"({'fixed rules' if rd['llm'] == 'stub' else 'with a model'}), which made {rd['observations']:,} observations. "
          "Record ids in backticks can be opened in SwarmFrame's evidence drawer. Counts and times are exact; patterns "
          "are detections with an innocent reading beside each; nothing here says why anyone did anything.", ""]
    return "\n".join(L)


def word_count(md: str) -> int:
    import re
    return len(re.sub(r"\[([^\]]*)\]\([^)]*\)", "", md).split())


def evidence_slice(rep: dict[str, Any], k: int = 40) -> list[str]:
    """The record ids a report rests on, most important first."""
    out: list[str] = []
    for f in rep.get("findings", []):
        out += f.get("evidence", [])
    for t in rep.get("timeline", []):
        out += t.get("cites", [])
    return list(dict.fromkeys(out))[:k]


def summary_counts(rep: dict[str, Any]) -> dict[str, Any]:
    """Structure only, for logs and tests."""
    return {"records": rep["totals"]["records"], "timeline": len(rep["timeline"]), "findings": len(rep["findings"]),
            "groups": len(rep["groups"]), "kinds": dict(Counter({k: v for k, v in rep["by_kind"].items()}))}

