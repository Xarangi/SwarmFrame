"""The orientation: SwarmFrame explaining, in the live column, what it just set up and how to study this source.

Posted once a dashboard is composed (in every LLM mode, built from what the session already knows: the pack's
description and capabilities, the composed pages and their reasons, the chosen analyst team and why, the pack's
standing questions). It is the bridge between "pick a source" and "watch it": what is here, what I built for it,
who is reading it, and what to do first. Structure and counts only; no agent-written text.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from swarmscope.engine import Engine

CAP_WORDS = {
    "identities": "who did what", "timestamps": "when", "resources": "shared {resource}s", "artifacts": "copied content",
    "communication": "messages between {agent}s", "environment": "operator and environment actions",
    "self_reports": "what {agent}s say about themselves", "goals": "goals", "control": "a control plane (pause, message)",
}


def _q(text: str) -> str:
    """A pack question with its {scope} placeholder made generic."""
    return re.sub(r"\{scope\}", "the busiest one", text)


def orientation(engine: "Engine") -> dict[str, Any]:
    p = engine.profile
    noun, rnoun = p.entity_noun, getattr(p, "resource_noun", "resource") or "resource"
    fmt = {"agent": noun, "resource": rnoun}
    caps = getattr(p, "capabilities", {}) or {}
    have = [CAP_WORDS[k].format(**fmt) for k, c in caps.items() if c.present and k in CAP_WORDS]
    lack = [CAP_WORDS[k].format(**fmt) for k, c in caps.items() if not c.present and k in CAP_WORDS]
    lr = getattr(engine, "live_replay", None)
    how = ("live: events arrive as they happen" if p.live else
           f"watching {lr['label']} live, after a short catch-up" if lr else "a replay of the recording, sped up")

    spec = engine.dashboard.spec
    pages = [{"title": pg.title, "why": (pg.reason or pg.description or "").rstrip(".")}
             for pg in spec.pages if pg.id != "brief"][:5]
    tc = getattr(engine, "team_choice", None) or {}
    org = engine.agent_org.summary()
    topo = engine.agent_org.topology
    team = {"title": org.get("title") or org.get("topology"), "roles": [r.get("title", k) if isinstance(r, dict) else
            getattr(r, "title", k) for k, r in list(topo.roles.items())[:6]],
            "why": "; ".join((tc.get("reasons") or [])[:2])}
    from swarmscope.config import llm_label
    reader = llm_label(engine.org)["long"].rstrip(".")
    qs = [_q(q["text"]) for q in (engine.pack.questions or [])][:3]
    first = [
        "Read the Brief: the headline says what is going on; What's going on shows what every group is doing and what is "
        "emerging, whatever the severity; Needs attention ranks findings (act, look, watch).",
        "Every finding lists its sources as numbered marks; open one to see the claim and the recorded events under it.",
        "Open a finding and choose Investigate to send it to the analysts, or ask me about it here.",
        "The World shows who clusters with whom; the other pages each answer one question about this source.",
    ]
    return {"source": p.title, "description": (p.description or "").strip(), "how": how, "have": have, "lack": lack,
            "pages": pages, "team": team, "reader": reader, "questions": qs, "first": first,
            "synthetic": bool(p.synthetic), "naming": getattr(p, "naming", "")}


def orientation_text(o: dict[str, Any]) -> str:
    """The same, as plain text (what a connected Claude Code session receives)."""
    lines = [f"Here is how I set up {o['source']}{' (synthetic)' if o['synthetic'] else ''}: {o['how']}."]
    if o["have"]:
        lines.append("It records " + ", ".join(o["have"]) + (f"; it cannot show {', '.join(o['lack'])}." if o["lack"] else "."))
    if o["pages"]:
        lines.append("Pages: " + "; ".join(f"{x['title']}" + (f" ({x['why']})" if x["why"] else "") for x in o["pages"]) + ".")
    t = o["team"]
    lines.append(f"Reading it: the {t['title']} team ({', '.join(t['roles'])})" + (f", because {t['why']}" if t["why"] else "")
                 + f". Reading: {o['reader']}.")
    lines.append("I will post a line here every window and flag findings, with their sources, as they appear.")
    return " ".join(lines)
