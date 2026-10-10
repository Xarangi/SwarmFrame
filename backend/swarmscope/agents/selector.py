"""Choosing a team shape for a stream (docs/OVERSIGHT_ARCHITECTURES.md §6.1–6.2).

Order of authority: a session override (`agents.topology`) > the source pack's `oversight.yaml` > the selector >
the org config's default. The selector is deterministic and explained: it computes a *shape vector* from the stream
(identity strength, population, rate, cohorts, capabilities, candidate partition axes, catalog) and walks a decision
table; the row that matched and its reasons are shown on the Compose and Organization screens. A pack's
`oversight.yaml` may name a topology (`topology: desks`), ask for the selector (`topology: auto`), and override any
topology field for that source (`overrides: {...}`, deep-merged).
"""
from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from swarmscope.agents.spec import Topology, from_dict, list_topologies, load_topology

if TYPE_CHECKING:
    from swarmscope.engine import Engine

CORE_AXES = ("family",)                      # core columns that work as partition axes without an attribute lookup
SMALL_POPULATION = 60
MANY_COHORTS = 12


def shape(engine: "Engine") -> dict[str, Any]:
    """Structure only: nothing here is agent-written text."""
    caps = engine.profile.capabilities
    cap = lambda k: caps.get(k)  # noqa: E731
    ident = cap("identities")
    identity = "absent" if not ident or not ident.present or ident.quality == "absent" else \
        "partial" if ident.quality in ("partial", "weak", "derived") else "strong"
    st = engine.store
    lo, hi = st.time_range()
    hours = max(1.0, ((hi - lo).total_seconds() / 3600) if lo and hi else 1.0)
    total = st.count_events()
    unit = (engine.scale.cfg or {}).get("unit", "actor")
    col = "actor" if unit == "actor" else "object"
    population = int(st.scalar(f"SELECT count(DISTINCT {col}) FROM events WHERE {col} IS NOT NULL") or 0)
    axes: list[dict[str, Any]] = []
    fams = st.sql("SELECT family AS v, count(*) AS n FROM events WHERE family IS NOT NULL GROUP BY family ORDER BY n DESC")
    if 2 <= len(fams) <= 60:
        axes.append({"field": "family", "distinct": len(fams), "share": round(sum(r["n"] for r in fams) / max(1, total), 3)})
    try:
        from swarmscope.dashboard.profile import attribute_shapes
        for k, v in attribute_shapes(engine).items():
            if v.get("usable_in_views") and 2 <= int(v.get("distinct_in_sample", 0)) <= 60 and k not in ("family",):
                axes.append({"field": k, "distinct": int(v["distinct_in_sample"]), "share": None})
    except Exception:
        pass
    cohorts = 0
    try:
        cohorts = len(getattr(engine.scale, "cohorts", {}) or {})
    except Exception:
        pass
    present = lambda k: bool(cap(k) and cap(k).present)  # noqa: E731
    return {"identity": identity, "unit": unit, "population": population, "events": total,
            "rate_per_hour": round(total / hours, 1), "cohorts": cohorts,
            "catalog": bool(engine.pack.source.get("catalog")), "live": bool(engine.profile.live),
            "communication": present("communication"), "self_reports": present("self_reports"),
            "environment": present("environment"), "groups": present("groups"), "stated_goals": present("stated_goals"),
            "tool_calls": present("tool_calls"), "control": present("control"),
            "resources": bool(cap("resources") and cap("resources").present and cap("resources").quality == "strong"),
            "axes": axes}


def _axis(sh: dict[str, Any], prefer: tuple[str, ...] = (), max_distinct: int | None = None) -> str | None:
    axes = [a for a in sh["axes"] if max_distinct is None or a["distinct"] <= max_distinct]
    for p in prefer:
        for a in axes:
            if a["field"] == p:
                return p
    axes.sort(key=lambda a: (-(a["share"] or 0), a["distinct"]))
    return axes[0]["field"] if axes else None


def select(sh: dict[str, Any], available: set[str]) -> dict[str, Any]:
    """The decision table. Returns {"topology", "reasons", "partition"}; the first matching row wins."""
    rows: list[tuple[bool, str, str, dict[str, Any] | None]] = [
        (sh["catalog"], "catalog_review",
         "a catalog of records about targets, not a live population: cycles follow the record, nobody has an identity",
         {"by": "field", "field": _axis(sh, ("family", "method", "technique")) or "family", "span": 8}),
        (sh["identity"] == "absent", "triage_tree",
         "no persistent identities: the unit is the target, cohorts group targets",
         {"by": "cohort"}),
        (sh["identity"] == "partial" and sh["resources"] and sh["environment"], "board_watch",
         "partial identities on shared places with an environment that acts (moderation): partition by namespace, "
         "resolve identities as questions",
         {"by": "field", "field": _axis(sh, ("family", "namespace"), max_distinct=12) or "family", "span": 4}),
        (sh["identity"] == "strong" and sh["population"] <= SMALL_POPULATION and sh["communication"], "desks",
         f"{sh['population']} agents with identities and a shared conversation: desks per group, standing specialists, "
         "a diarist for each agent's story",
         {"by": "group" if sh["groups"] else "family", "span": 6}),
        (sh["population"] > SMALL_POPULATION or sh["cohorts"] > MANY_COHORTS, "triage_tree",
         f"{sh['population']} units ({sh['cohorts']} cohorts): attention must follow structure; code compresses, "
         "a triage allocator spends a bounded reading budget",
         {"by": "cohort"}),
    ]
    for ok, tid, why, part in rows:
        if ok and tid in available:
            return {"topology": tid, "reasons": [why], "partition": part}
    ax = _axis(sh)
    return {"topology": "triage_tree" if "triage_tree" in available else sorted(available)[0],
            "reasons": ["no library shape matched this stream; the triage tree is the safe default"
                        + (f", partitioned on {ax}" if ax else "")],
            "partition": {"by": "field", "field": ax, "span": 6} if ax else {"by": "cohort"}}


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def build(tid: str, overrides: dict[str, Any] | None = None, partition: dict[str, Any] | None = None) -> Topology:
    d = load_topology(tid).to_dict()
    d.pop("id", None)
    if partition and not (overrides or {}).get("partition") and not d.get("partition"):
        d["partition"] = partition
    if overrides:
        d = _merge(d, overrides)
    return from_dict(d, tid)


def choose_topology(engine: "Engine", explicit: str | dict[str, Any] | None = None) -> dict[str, Any]:
    """Returns {"topology": Topology, "by": override|pack|selector|default, "reasons": [...], "shape": {...},
    "alternatives": [...]}. Never raises: any failure falls back to the org config's default."""
    available = {t["id"] for t in list_topologies()}
    ov = (engine.pack.oversight or {}) if hasattr(engine.pack, "oversight") else {}
    default = engine.org.get("agents", {}).get("topology", "lead")
    sh: dict[str, Any] = {}
    try:
        sh = shape(engine)
    except Exception as exc:                       # a stream with no events yet, or a store without the columns
        sh = {"error": str(exc)[:200], "axes": [], "identity": "unknown", "population": 0, "cohorts": 0,
              "catalog": bool(engine.pack.source.get("catalog")), "communication": False, "environment": False,
              "resources": False, "groups": False}
    picked = select(sh, available) if sh.get("identity") != "unknown" else None
    try:
        if explicit == "composed":
            from swarmscope.agents.composer import compose
            c = compose(engine)
            t, by, reasons = c["topology"], "composer", [c["summary"]] + [f"{p['title']}: {p['reason']}" for p in c["parts"] if p["how"] != "off"]
            engine.composition = c
        elif explicit:
            tid = explicit if isinstance(explicit, str) else explicit.get("id", "custom")
            t = build(tid, ov.get("overrides") if tid in (ov.get("topology"), ov.get("preset")) else None) if isinstance(explicit, str) \
                else from_dict(explicit, tid)
            by, reasons = "override", ["chosen for this session"]
        elif ov.get("topology") and ov["topology"] != "auto":
            t = build(ov["topology"], ov.get("overrides"))
            by, reasons = "pack", [ov.get("reason") or f"the {engine.pack.id} pack's oversight.yaml names this team"]
        elif ov.get("topology") == "auto" and picked:
            t = build(picked["topology"], ov.get("overrides"), picked["partition"])
            by, reasons = "selector", picked["reasons"]
            if getattr(getattr(engine, "router", None), "mode", "stub") != "stub" or ov.get("scout"):
                t = with_scout(t)                   # models on: a Scout reviews the pick and proposes refinements
                reasons = reasons + ["a Scout runs once to review this choice"]
        else:
            t = build(default, ov.get("overrides") if default in (ov.get("topology"), ov.get("preset")) else None)
            by, reasons = "default", [f"the org config's default ({default})"]
    except Exception as exc:
        t = load_topology(default if default in available else "triage_tree")
        by, reasons = "default", [f"fell back to {t.id}: {str(exc)[:160]}"]
    alts = []
    for a in list_topologies():
        if a["id"] != t.id:
            alts.append({"id": a["id"], "title": a["title"]})
    return {"topology": t, "by": by, "reasons": reasons, "shape": sh,
            "would_pick": picked["topology"] if picked else None,
            "would_pick_reasons": picked["reasons"] if picked else [], "alternatives": alts}


SCOUT_ROLE: dict[str, Any] = {
    "title": "Scout", "kind": "scout",
    "description": "Reads the stream's shape once and proposes the team: base topology, partition, standing roles, new roles.",
    "prompt": "prompts/scout.md", "model": "claude-sonnet-5-5", "effort": "low", "max_turns": 8,
    "tools": ["evidence.population_digest", "evidence.cohorts", "evidence.templates", "evidence.observations",
              "org.org_status", "org.list_roles", "org.cases"],
    "output": "architecture_proposal", "memory": "none", "scope": "population", "refresh_every_cycles": 0,
    "skills": ["swarm-oversight"], "skill_refs": ["team_shaping", "reading_compressed_views"]}


def with_scout(t: Topology) -> Topology:
    """The same team, plus a standing Scout that runs once and proposes refinements (§6.3)."""
    d = t.to_dict()
    tid = d.pop("id", t.id)
    if "scout" in d["roles"]:
        return t
    d["roles"]["scout"] = copy.deepcopy(SCOUT_ROLE)
    root = d["roles"][d["root"]]
    root["can_spawn"] = sorted(set(root.get("can_spawn", [])) | {"scout"})
    d.setdefault("standing", []).append({"role": "scout", "scope": "population",
                                         "brief": "Read the stream's shape and propose the team as data."})
    return from_dict(d, tid)


def team_summary(choice: dict[str, Any]) -> dict[str, Any]:
    t: Topology = choice["topology"]
    return {"topology": t.id, "title": t.title, "description": t.description, "by": choice["by"],
            "reasons": choice["reasons"], "would_pick": choice.get("would_pick"),
            "would_pick_reasons": choice.get("would_pick_reasons", []),
            "shape": {k: v for k, v in choice.get("shape", {}).items() if k != "axes"},
            "axes": choice.get("shape", {}).get("axes", [])[:8],
            "partition": t.partition, "levels": t.levels, "standing": t.standing, "questions": t.questions,
            "cadence": t.cadence, "human": t.human, "authority": t.authority,
            "roles": {rid: {"title": r.title, "model": r.model, "effort": r.effort, "scope": r.scope,
                            "description": r.description} for rid, r in t.roles.items()},
            "alternatives": choice.get("alternatives", [])}
