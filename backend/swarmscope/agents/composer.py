"""The strategy composer: a team assembled for this data, from parts, each with its reason.

The selector (agents/selector.py) picks one of the library's preset teams. The composer instead builds a team from
the parts those presets are made of, so a stream gets exactly the readers and specialists its records call for:

  1. a **lead**, always: it watches everything and sends **explorers** wherever a finding rises (lead.yaml);
  2. **readers**, only when the population is too big for one lead to follow: one reader per slice of the stream,
     cut along the best partition axis (groups, a categorical field such as a page family, or cohorts of units that
     behave alike), with **sector leads** above them when there are many slices (triage_tree.yaml);
  3. **specialists**, each switched on by evidence measured in the records (never by the source's name): an
     integrity checker when agents describe their own work, a propagation specialist when the same text turns up
     from several authors, a moderation-response watcher when the environment acts on agents, an identity resolver
     when names are partial and look alike, a diarist for a small named cast, a goals specialist when agents state
     goals, a chronicler and grade auditor for catalogs. Strong evidence makes a specialist standing (spawned at the
     start and kept); weaker evidence makes it on call (the lead or a question can send it);
  4. **an auditor** reading a random slice, so coverage is never only where the detectors point;
  5. question routing (which role answers which kind of question), cadence and budgets scaled to the population.

Every part records why it is there and the numbers behind it. The result goes through the same validation as a
hand-written topology, can be edited on the Organization screen, compared against the presets on the same data, and
saved as a new preset. A model can compose too (`compose_with_claude`), but only by choosing among these parts and
their parameters; the assembly and the checks stay here.
"""
from __future__ import annotations

import copy
import json
import re
from collections import Counter
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import yaml

from swarmscope.agents.spec import TOPOLOGY_DIR, Topology, from_dict

if TYPE_CHECKING:
    from swarmscope.engine import Engine

# where each part's role definition comes from in the library
PARTS: dict[str, dict[str, Any]] = {
    "lead": {"from": ("lead", "lead"), "title": "Lead analyst",
             "does": "watches everything and sends explorers wherever a finding rises"},
    "explorer": {"from": ("lead", "explorer"), "title": "Explorers",
                 "does": "look into one area the lead or a finding points at, and are let go when it goes quiet"},
    "reader": {"from": ("triage_tree", "division_analyst"), "title": "Readers",
               "does": "one per slice of the stream, each reads its slice closely every cycle"},
    "sector_lead": {"from": ("triage_tree", "sector_lead"), "title": "Sector leads",
                    "does": "summarise a group of readers for the lead when there are many slices"},
    "auditor": {"from": ("triage_tree", "auditor"), "title": "Auditor",
                "does": "reads a random slice the detectors did not point at, so coverage is not only where the alarms are"},
    "integrity": {"from": ("desks", "integrity_specialist"), "title": "Integrity specialist", "question": "integrity",
                  "does": "checks whether what agents say they did matches what they did"},
    "goals": {"from": ("desks", "goals_specialist"), "title": "Goals specialist", "question": "goals",
              "does": "follows stated goals: who holds which, and whether work drifts from them"},
    "propagation": {"from": ("board_watch", "propagation_specialist"), "title": "Propagation specialist",
                    "question": "propagation", "does": "follows text that turns up from several authors, and whether they could have seen it"},
    "environment": {"from": ("board_watch", "moderation_response"), "title": "Environment specialist",
                    "question": "environment", "does": "watches what the environment does to agents (deletions, stops, denials) and how they respond"},
    "identity": {"from": ("board_watch", "identity_resolver"), "title": "Identity resolver", "question": "identity",
                 "does": "works out which look-alike names may be the same writer, as questions, never as facts"},
    "diarist": {"from": ("desks", "diarist"), "title": "Diarist",
                "does": "keeps one neutral paragraph per agent per day, so each agent's story can be read"},
    "chronicler": {"from": ("catalog_review", "chronicler"), "title": "Chronicler",
                   "does": "keeps the catalog's timeline: what was reported when, and what changed"},
    "grade_auditor": {"from": ("catalog_review", "grade_auditor"), "title": "Grade auditor",
                      "does": "checks the catalog's own confidence labels against the evidence"},
    "new_method": {"from": ("catalog_review", "new_method_specialist"), "title": "New-method specialist",
                   "question": "surge", "does": "looks into methods or kinds of record seen for the first time"},
}
SPECIALISTS = ["integrity", "goals", "propagation", "environment", "identity", "diarist", "chronicler", "grade_auditor",
               "new_method"]
SPAN = 6                      # slices a sector lead can summarise
ONE_READER = 40               # units one lead can follow without readers


@lru_cache(maxsize=None)
def _library(tid: str) -> dict[str, Any]:
    return yaml.safe_load((TOPOLOGY_DIR / f"{tid}.yaml").read_text(encoding="utf-8")) or {}


def _role(part: str) -> dict[str, Any]:
    tid, rid = PARTS[part]["from"]
    r = copy.deepcopy(_library(tid)["roles"][rid])
    r["title"] = PARTS[part]["title"].rstrip("s") if part in ("explorer", "reader") else PARTS[part]["title"]
    r["can_spawn"] = []
    return r


def _helpers(roles: dict[str, Any]) -> dict[str, Any]:
    """Native sub-agent definitions the copied roles refer to, from the presets they came from."""
    out: dict[str, Any] = {}
    for part, r in roles.items():
        tid = PARTS[part]["from"][0]
        for h in r.get("native_subagents") or []:
            hd = (_library(tid).get("helpers") or {}).get(h)
            if hd is not None:
                out[h] = copy.deepcopy(hd)
            else:
                r["native_subagents"] = [x for x in r["native_subagents"] if x != h]
    return out


# ------------------------------------------------------------------ what the records show (structure only, cheap SQL)
def measure(engine: "Engine") -> dict[str, Any]:
    """Counts the composer reasons from. No agent-written text is read: shares, counts and distinct values only."""
    from swarmscope.agents.selector import shape
    sh = shape(engine)
    st = engine.store
    q = lambda sql, p=None: st.sql(sql, p or [])  # noqa: E731
    n = max(1, sh["events"])
    m: dict[str, Any] = {"shape": sh}
    acts = {r["action"]: r["n"] for r in q("SELECT action, count(*) n FROM events GROUP BY action")}
    m["self_report_events"] = sum(v for a, v in acts.items() if a in ("chat.message", "narration", "summary.generated",
                                                                      "memory.update", "memory.checkpoint", "report")
                                  or a.startswith(("reasoning", "memory.", "summary")))
    m["environment_events"] = sum(v for a, v in acts.items() if a.startswith(("environment.", "control.")))
    m["goal_events"] = sum(v for a, v in acts.items() if "goal" in a)
    # the same text from several authors: fingerprints shared by more than one first author
    try:
        dup = q("SELECT count(*) n FROM (SELECT fingerprint FROM artifacts WHERE fingerprint IS NOT NULL "
                "GROUP BY fingerprint HAVING count(DISTINCT first_actor) > 1)")[0]["n"]
        texts = q("SELECT count(*) n FROM artifacts")[0]["n"]
    except Exception:
        dup, texts = 0, 0
    m["shared_texts"], m["texts"] = int(dup or 0), int(texts or 0)
    # look-alike names: actor labels that share a stem with others
    labels = [e.label for e in st.entities() if e.type in ("agent", "actor")][:20000]
    stems = Counter(re.sub(r"[\d_\-.]+$", "", (l or "").lower())[:8] for l in labels if l)
    m["lookalike_names"] = sum(c for s, c in stems.items() if s and c >= 3)
    m["actors"] = len(labels)
    groups = q("SELECT count(DISTINCT actor_group) g FROM events WHERE actor_group IS NOT NULL")[0]["g"]
    m["groups"] = int(groups or 0)
    m["events_per_unit"] = round(n / max(1, sh["population"]), 1)
    conf = q("SELECT count(*) n FROM events WHERE json_extract_string(attributes, '$.confidence') IS NOT NULL")[0]["n"]
    m["graded_events"] = int(conf or 0)
    m["events"] = n
    return m


def _share(x: int, n: int) -> str:
    return f"{x:,} of {n:,} records ({x / max(1, n):.0%})"


# ------------------------------------------------------------------ assembly
def compose(engine: "Engine", choices: dict[str, Any] | None = None) -> dict[str, Any]:
    """{"topology": Topology, "parts": [{part, how, reason, evidence}], "summary", "measures"}. `choices` may force
    parts on or off ({"integrity": "standing" | "on_call" | "off"}) and set {"partition": {...}, "budget": ...};
    a model's composition is passed the same way."""
    choices = dict(choices or {})
    m = measure(engine)
    sh = m["shape"]
    n = m["events"]
    pop = sh["population"]
    a = engine.profile.entity_noun
    parts: list[dict[str, Any]] = []
    roles: dict[str, Any] = {}

    def add(part: str, how: str, reason: str, evidence: str = "") -> None:
        forced = choices.get(part)
        if forced in ("off", "standing", "on_call"):
            how = forced
            reason = f"{reason} (changed for this variant)" if forced != "off" else "turned off for this variant"
        if choices.get("demote_specialists") and how == "standing" and part in SPECIALISTS:
            how, reason = "on_call", f"{reason} (on call rather than standing in this variant)"
        parts.append({"part": part, "title": PARTS[part]["title"], "does": PARTS[part]["does"], "how": how,
                      "reason": reason, "evidence": evidence})
        if how != "off":
            roles[part] = _role(part)

    # 1. the lead and its explorers
    add("lead", "root", "every team has one place where the picture comes together")
    add("explorer", "on_call", "the team should grow only where something is happening", "sent for findings at investigate or above")

    # 2. readers, when the population is too big for one lead
    partition: dict[str, Any] = choices.get("partition") or {}
    slices = 0
    if not partition:
        if pop > ONE_READER or sh.get("cohorts", 0) > 12:
            if sh["identity"] == "absent" or not (m["groups"] or sh["axes"]):
                partition = {"by": "cohort", "span": SPAN}
                why = f"{pop:,} units and no better axis: readers each take a set of units that behave alike"
            elif m["groups"] and sh["identity"] == "strong" and 2 <= m["groups"] <= 60:
                partition = {"by": "group", "span": SPAN}
                why = f"{pop:,} {a}s in {m['groups']} groups: one reader per group"
            else:
                import math
                # the axis that cuts the records into a workable number of slices (about 8; 3 to 40)
                fit = [x for x in sh["axes"] if 3 <= x["distinct"] <= 40]
                ax = min(fit, key=lambda x: abs(math.log(x["distinct"] / 8)) - 0.5 * (x["share"] or 0)) if fit else                     (sh["axes"][0] if sh["axes"] else None)
                partition = {"by": "field", "field": ax["field"], "span": 4} if ax else {"by": "cohort", "span": SPAN}
                why = (f"{pop:,} units; '{ax['field']}' cuts the records into {ax['distinct']} parts: one reader per part"
                       if ax else f"{pop:,} units: readers by cohort")
            slices = int((next((x["distinct"] for x in sh["axes"] if x["field"] == partition.get("field")), 0)
                          if partition.get("by") == "field" else m["groups"] if partition.get("by") == "group"
                          else max(1, sh.get("cohorts", 0))) or 0)
            add("reader", "standing", why, f"{pop:,} units, {m['events_per_unit']} records each")
        else:
            add("reader", "off", f"{pop:,} units: one lead can follow them all")
    else:
        add("reader", "standing", "a partition was asked for")
    if slices > 2 * SPAN and "reader" in roles:
        add("sector_lead", "standing", f"{slices} slices are too many for the lead to read: sector leads summarise "
            f"about {SPAN} each")

    # 3. specialists, by evidence
    def strength(x: int, standing_at: float, on_call_at: float) -> str:
        share = x / max(1, n)
        return "standing" if share >= standing_at else "on_call" if share >= on_call_at or x >= 5 else "off"

    sr = m["self_report_events"]
    if sh.get("self_reports") or sr:
        add("integrity", strength(sr, 0.05, 0.005), f"{a}s describe their own work, so claims can be checked against actions",
            _share(sr, n))
    if sh.get("stated_goals") or m["goal_events"]:
        add("goals", "standing" if m["goal_events"] >= 10 else "on_call", f"{a}s state goals", _share(m["goal_events"], n))
    if m["texts"]:
        how = "standing" if m["shared_texts"] >= 10 else "on_call" if m["shared_texts"] else "off"
        add("propagation", how, "the same text turns up from different authors" if how != "off" else "no text is shared between authors",
            f"{m['shared_texts']:,} of {m['texts']:,} texts were also written by another author")
    ev = m["environment_events"]
    if ev:
        add("environment", strength(ev, 0.02, 0.0005), "the environment acts on the agents (deletions, stops, denials)", _share(ev, n))
    if sh["identity"] == "partial" and m["lookalike_names"]:
        add("identity", "standing" if m["lookalike_names"] >= 30 else "on_call",
            "names are partial identities and many look alike", f"{m['lookalike_names']:,} names share a stem with two or more others")
    if sh["identity"] == "strong" and 2 <= pop <= 40:
        add("diarist", "standing", f"a small named cast ({pop} {a}s): a diary per {a} makes each story readable")
    if sh.get("catalog"):
        add("chronicler", "standing", "a catalog: someone keeps its timeline")
        if m["graded_events"]:
            add("grade_auditor", "standing", "the catalog grades its own evidence", _share(m["graded_events"], n))
        add("new_method", "on_call", "new kinds of record are worth a look when they first appear")

    # 4. the auditor
    if n >= 200:
        add("auditor", "standing", "a random slice is read every few cycles, so the team does not only look where the detectors point")

    # parts a caller (a person or a model) turned on that the evidence did not call for
    have = {p["part"] for p in parts}
    for part, how in choices.items():
        if part in PARTS and part not in have and how in ("standing", "on_call") and part not in ("lead", "sector_lead"):
            if part == "reader" and not partition:
                partition = {"by": "cohort", "span": SPAN}
            add(part, how, "asked for, although the records do not call for it strongly")

    # ---------------------------------------------------------------- the topology
    for p in parts:
        if p["part"] in roles and p["part"] != "lead":
            roles["lead"]["can_spawn"].append(p["part"])
    if "reader" in roles:
        roles["reader"]["can_spawn"] = [s for s in ("explorer",) if s in roles]
        if "sector_lead" in roles:
            roles["sector_lead"]["can_spawn"] = ["explorer"]
    standing = [{"role": p["part"], "scope": "audit" if p["part"] == "auditor" else "population",
                 "brief": f"[{PARTS[p['part']].get('question', 'general')}] {PARTS[p['part']]['does'][0].upper()}{PARTS[p['part']]['does'][1:]}."}
                for p in parts if p["how"] == "standing" and p["part"] in SPECIALISTS + ["auditor"]]
    questions = {PARTS[p["part"]]["question"]: p["part"] for p in parts
                 if p["how"] in ("standing", "on_call") and PARTS[p["part"]].get("question")}
    questions["*"] = "explorer"
    budget = choices.get("budget") or ("thorough" if pop <= ONE_READER else "economical")
    agents = 2 + len(standing) + (min(12, max(2, slices or 4)) if "reader" in roles else 0) + 4
    d: dict[str, Any] = {
        "title": "Composed for this data",
        "description": "Assembled by the composer from what the records show: " + "; ".join(
            f"{p['title'].lower()} ({p['how'].replace('_', ' ')})" for p in parts if p["how"] != "off") + ".",
        "root": "lead", "roles": roles, "helpers": _helpers(roles),
        "divisions": {"strategy": "none"} if "reader" not in roles else {"max": 12, "min_events": 6, "lookback_windows": 18},
        "partition": partition if "reader" in roles else {},
        "levels": [{"role": "sector_lead", "span": SPAN}] if "sector_lead" in roles else [],
        "standing": standing, "questions": questions,
        "cadence": {"kind": "windows", "every": 3 if pop <= ONE_READER else 6},
        "scaling": {"max_agents": agents, "max_depth": 3 if "sector_lead" in roles else 2, "max_concurrent_runs": 4,
                    "budget_usd_per_cycle": 1.0 if budget == "thorough" else 0.5,
                    "budget_usd_total": 8.0 if budget == "thorough" else 4.0},
        "cycle": ["refresh_children", "root", "maintain"],
        "maintain": {"cover_divisions_with": "reader" if "reader" in roles else None, "retire_quiet_cycles": 4,
                     "split_when_events_over": None, "explore_with": "explorer", "explore_min_level": "INVESTIGATE",
                     "explore_max": 4, "explore_ttl_cycles": 4,
                     **({"audit_with": "auditor"} if "auditor" in roles else {})},
    }
    t = from_dict(d, "composed")
    on = [p for p in parts if p["how"] != "off"]
    bits = ["a lead with explorers"]
    if "reader" in roles:
        bits.append(f"readers by {partition.get('field') or partition.get('by')}")
    if "sector_lead" in roles:
        bits.append("sector leads")
    bits += [f"{p['title'].lower()} ({p['how'].replace('_', ' ')})" for p in on if p["part"] in SPECIALISTS]
    if "auditor" in roles:
        bits.append("an auditor")
    summary = (bits[0][0].upper() + bits[0][1:] + (", " + ", ".join(bits[1:-1]) + " and " + bits[-1] if len(bits) > 2
               else " and " + bits[1] if len(bits) == 2 else "") + ".")
    return {"topology": t, "parts": parts, "summary": summary, "measures": {k: v for k, v in m.items() if k != "shape"},
            "shape": {k: v for k, v in sh.items() if k != "axes"}, "axes": sh.get("axes", [])[:8]}


def describe(c: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe view of a composition, for the API and reports."""
    t: Topology = c["topology"]
    return {"summary": c["summary"], "parts": c["parts"], "measures": c["measures"], "shape": c["shape"],
            "axes": c["axes"], "topology": {"title": t.title, "description": t.description, "roles": list(t.roles),
                                             "partition": t.partition, "standing": [s["role"] for s in t.standing],
                                             "questions": t.questions, "levels": t.levels}}


# ------------------------------------------------------------------ a model composes, within the same parts
CHOICES_SCHEMA = {"type": "object", "properties": {
    "parts": {"type": "object", "additionalProperties": {"type": "string", "enum": ["standing", "on_call", "off"]}},
    "partition": {"type": "object", "properties": {"by": {"type": "string", "enum": ["cohort", "field", "group", "none"]},
                                                     "field": {"type": "string"}, "span": {"type": "integer"}}},
    "budget": {"type": "string", "enum": ["economical", "thorough"]},
    "reasons": {"type": "object", "additionalProperties": {"type": "string"}}},
    "required": ["parts", "reasons"]}


async def compose_with_claude(engine: "Engine", model: str = "claude-sonnet-5-5", effort: str = "low",
                              focus: str = "") -> dict[str, Any]:
    """Claude chooses among the parts (on call, standing or off), the partition and the budget, from the same
    measures; the assembly and validation are `compose`'s. Returns the composition plus Claude's reasons."""
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    from swarmscope.llm.router import find_claude_cli
    base = compose(engine)
    catalog = {k: {"title": v["title"], "does": v["does"]} for k, v in PARTS.items() if k not in ("lead",)}
    prompt = ("You compose the analyst team that will read a stream of agent activity. Choose, for each part, "
              "standing (spawned at the start and kept), on_call (available when needed) or off; choose the partition "
              "for readers (or none) and the budget. Use the measures; they are counts and shares, never agent text. "
              "The default composition below was made by fixed rules; keep what is right and change what is not, "
              "with one short reason per change." + (f" The person cares most about: {focus}." if focus else "") +
              "\n\nParts: " + json.dumps(catalog) + "\n\nMeasures: " + json.dumps(base["measures"]) +
              "\nShape: " + json.dumps(base["shape"]) + "\nPartition axes: " + json.dumps(base["axes"]) +
              "\n\nDefault composition: " + json.dumps({p["part"]: p["how"] for p in base["parts"]}) +
              " partition " + json.dumps(base["topology"].partition))
    opts = ClaudeAgentOptions(system_prompt="You design oversight teams. Answer only with the requested JSON.",
                              model=model, effort=effort, max_turns=2, tools=[], allowed_tools=[], setting_sources=[],
                              output_format={"type": "json_schema", "schema": CHOICES_SCHEMA}, cli_path=find_claude_cli())
    result = None
    async for msg in query(prompt=prompt, options=opts):
        if isinstance(msg, ResultMessage):
            result = msg
    if result is None or result.is_error or not result.structured_output:
        return {**base, "by": "rules", "note": "the model did not answer; the rules' composition stands"}
    out = result.structured_output
    ch: dict[str, Any] = {k: v for k, v in (out.get("parts") or {}).items() if k in PARTS and k != "lead"}
    part = out.get("partition") or {}
    if part.get("by") and part["by"] != "none":
        if part["by"] == "field" and part.get("field") not in {a["field"] for a in base["axes"]}:
            part = {}
        ch["partition"] = {k: v for k, v in part.items() if v} if part else None
        if not ch["partition"]:
            ch.pop("partition")
    elif part.get("by") == "none":
        ch["reader"] = "off"
    if out.get("budget"):
        ch["budget"] = out["budget"]
    c = compose(engine, ch)
    reasons = out.get("reasons") or {}
    for p in c["parts"]:
        if p["part"] in reasons:
            p["reason"] = str(reasons[p["part"]])[:300]
    engine.router.spent_usd += float(result.total_cost_usd or 0)
    return {**c, "by": "claude", "cost_usd": round(float(result.total_cost_usd or 0), 4)}
