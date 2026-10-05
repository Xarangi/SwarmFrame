"""Findings in plain words: what happened, why it might matter, the innocent reading, and what to check.

Watcher titles are written for the analysts ("reused by 7 other handles (0 with an observed exposure path)"). A person
watching the dashboard needs the same fact said the way a colleague would say it, with the reason it was raised and
the boring explanation next to the worrying one. Each kind gets one template, filled from the observation's own
numbers (never from agent-written text), so the explanation is as exact as the finding and costs nothing to make.

Used by the Brief rows (`explain`), the finding drawer, the live column's finding posts, and handed to the copilot.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from swarmscope.engine import Engine


def _n(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def pace(count: Any, baseline: Any) -> str:
    """'about 6 times its usual pace (usually about 4)': a ratio a person can picture, instead of a z-score."""
    c, b = float(count or 0), float(baseline or 0)
    if b < 0.5:
        return f"where there is usually almost nothing"
    r = c / b
    if r >= 1.8:
        return f"about {r:.0f} times its usual pace (usually about {b:.0f})"
    return f"above its usual pace (usually about {b:.0f})"


def _names(xs: Any, k: int = 3) -> str:
    xs = [str(x) for x in (xs or []) if x][:k + 1]
    if not xs:
        return ""
    if len(xs) > k:
        return ", ".join(xs[:k]) + " and others"
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def explain(engine: "Engine", kind: str, obs: Any | None, title: str = "") -> dict[str, str]:
    """{what, why, benign, check} for one finding. `obs` is the Observation behind it (None for an analyst's own)."""
    p = engine.profile
    a, r = p.entity_noun, getattr(p, "resource_noun", "resource") or "resource"
    ws = getattr(p, "workstream_noun", "workstream") or "workstream"
    m = dict(getattr(obs, "metrics", None) or {})
    win = int(engine.window_len.total_seconds() // 60) if getattr(engine, "window_len", None) else 10
    win_t = f"{win} minutes" if win < 120 else f"{win // 60} hours" if win < 2880 else f"{win // 1440} days"
    lab = engine.label
    scope = getattr(obs, "scope", "") or ""
    place = lab(m.get("resource")) if m.get("resource") else engine._scope_label(scope) if hasattr(engine, "_scope_label") else scope

    if kind == "rate_surge":
        what_of = f"the {scope.split(':', 1)[1]} {ws}" if scope.startswith("family:") else f"overall {a} activity"
        return {
            "what": f"Activity in {what_of} jumped to {_n(m.get('count'))} events in {win_t}, {pace(m.get('count'), m.get('baseline'))}.",
            "why": f"A sudden jump can mean many {a}s started the same thing at once: a new instruction, a shared trigger, or a coordinated push.",
            "benign": f"Busy spells happen. A scheduled task, a new goal or one very active {a} can cause this alone.",
            "check": f"See who is behind the jump, and whether it continues in the next {win_t}.",
        }
    if kind == "burst":
        return {
            "what": f"{place} received {_n(m.get('count'))} events in {win_t}, {pace(m.get('count'), m.get('baseline'))}.",
            "why": f"A {r} that suddenly draws this much activity is often where something is happening: a shared target, a dispute, or a coordinated effort.",
            "benign": f"A popular or newly created {r} naturally draws a burst.",
            "check": f"See which {a}s caused it and whether they usually work there.",
        }
    if kind == "convergence":
        n = _n(m.get("units"))
        who = _names(m.get("members"))
        return {
            "what": f"{n} different {a}s{' (' + who + ')' if who else ''} all worked on {place} within a short time, "
                    f"although they do not usually work together.",
            "why": f"Unconnected {a}s turning up on the same {r} together can mean they were coordinated somewhere we cannot see, "
                   f"or that one operator runs several of them.",
            "benign": f"They may simply share a goal or the same instructions, and a busy {r} draws a crowd.",
            "check": f"Did they talk to each other beforehand? Did they arrive one after another or all at once?",
        }
    if kind in ("content_reuse", "reuse"):
        n = _n(m.get("reusers"))
        seen = len(m.get("exposed") or [])
        origin = lab(m.get("origin_actor")) if m.get("origin_actor") else "one " + a
        how = ("None of them had visibly opened the place where it first appeared, so the record does not show how they got it."
               if seen == 0 else f"{seen} of them had visibly been where it first appeared; the others had not.")
        return {
            "what": f"Text that {origin} wrote first turned up again in what {n} other {a}{'s' if n != 1 else ''} wrote. {how}",
            "why": f"Copied text with no visible path can mean the {a}s are fed from the same hidden source, or that one operator writes under several names.",
            "benign": "It may be a template, a quote, or text that all of them copied from the same public page.",
            "check": "Look for a shared upstream source, and compare when each copy appeared.",
        }
    if kind == "new_actors":
        n = _n(m.get("count"))
        return {
            "what": f"{n} {a}s acted for the first time in this stretch{': ' + _names(m.get('members')) if m.get('members') else ''}.",
            "why": f"A wave of newcomers at once can be a batch launched together, or someone returning under fresh names.",
            "benign": f"New {a}s join over time; a launch or a schedule can bring many at once.",
            "check": f"Were they started on purpose? Do they behave alike or go to the same {r}s?",
        }
    if kind == "environment":
        n = _n(m.get("count"))
        act = str(m.get("action") or "environment").split(".", 1)[-1].replace("_", " ")
        hit = _names(m.get("affected"))
        return {
            "what": f"{n} {act} action{'s' if n != 1 else ''} hit {place}" + (f", affecting {hit}." if hit else "."),
            "why": f"This is the environment pushing back (moderators, operators or the platform). How the {a}s react matters: "
                   f"do they stop, move elsewhere, or come back under new names?",
            "benign": "It may be routine cleanup or moderation.",
            "check": f"See where the affected {a}s went next.",
        }
    if kind == "human_intervention":
        return {
            "what": f"People (not {a}s) wrote {_n(m.get('count'))} message{'s' if _n(m.get('count')) != 1 else ''} into the conversation.",
            "why": f"Human messages often redirect the {a}s; what follows shows whether they listened.",
            "benign": "Routine guidance or questions.",
            "check": f"Read what the {a}s did right after.",
        }
    if kind == "say_do_mismatch":
        who = m.get("actor") or "One " + a
        fams = "/".join(m.get("families") or []) or "matching"
        claim = str(m.get("claim") or "done").replace("_", " ")
        return {
            "what": f"{who} reported '{claim}', but the record shows no {fams} work by it in the time before.",
            "why": "Reports that do not match the record make self-reports unreliable: the work happened somewhere we cannot see, or not at all.",
            "benign": "The work may have been done outside what this stream records.",
            "check": "Compare the report with its recent activity.",
        }
    if kind == "focus_shift":
        return {
            "what": f"{m.get('actor') or 'One ' + a} switched from mostly {m.get('previous')} work to {m.get('current')} work.",
            "why": f"An unasked-for change of focus can mean the {a} was redirected by someone, or drifted off its task.",
            "benign": "Tasks change; it may have finished one and started the next.",
            "check": "Was the change asked for?",
        }
    if kind == "alias":
        hs = m.get("handles") or []
        return {
            "what": f"{len(hs)} {a}s have names that start the same way ({_names(hs)}).",
            "why": f"Near-identical names can be one person or program running several accounts.",
            "benign": "A naming convention, or the same tool generating names for unrelated users.",
            "check": f"Do they act at the same times or on the same {r}s?",
        }
    if kind == "new_method":
        return {
            "what": f"For the first time, '{m.get('method')}' activity appeared on {place} ({_n(m.get('count'))} events).",
            "why": f"A new way of reaching a {r} can mean new tooling or a new tactic.",
            "benign": "New tools get adopted over time.",
            "check": f"Look at the first {a}s that used it.",
        }
    if kind == "reasoning_cue":
        n = _n(m.get("count"))
        return {
            "what": f"In its own private reasoning, {m.get('actor') or 'one ' + a} wrote about {m.get('cue')} "
                    f"({n} time{'s' if n != 1 else ''} in {win_t}).",
            "why": f"What an {a} thinks before acting can show intentions that its messages and actions do not.",
            "benign": f"{a.capitalize()}s often reason about a restriction and then respect it; the words alone are not wrongdoing.",
            "check": f"Open the sources to read the reasoning (agent-written, untrusted) and see what it did next.",
        }
    if kind == "spatial_drift":
        return {
            "what": title or f"One {a} moved away from where it usually works.",
            "why": f"Its partners or behaviour changed, which can mean it was given a new role or joined another group.",
            "benign": "Work naturally moves between areas.",
            "check": "Open the World to see who it is near now.",
        }
    if kind == "cohort_split":
        return {
            "what": title or f"A group of similar {a}s is coming apart.",
            "why": "A group that splits can mean part of it got new instructions.",
            "benign": "Groups change as tasks finish.",
            "check": "Open the World and compare the two halves.",
        }
    return {"what": title, "why": "", "benign": "", "check": "Open the sources to see what it rests on."}
