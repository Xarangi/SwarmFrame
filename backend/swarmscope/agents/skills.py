"""Skills: the doctrine that instructs organization roles, kept as real Claude Code skills.

Skills live in `<project>/.claude/skills/<id>/SKILL.md` (with optional `references/*.md`), so the same files serve
two readers: SwarmFrame's own agents (the runner puts SKILL.md and the role's references into the system prompt, and
offers the rest through a `read_reference` tool), and an interactive Claude Code session opened in the project, which
discovers them natively.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from swarmscope.ingest.packs import ROOT

SKILLS_DIR = ROOT / ".claude" / "skills"
_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def _split(text: str) -> tuple[dict[str, str], str]:
    m = _FRONT.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        if v:
            meta[k.strip()] = v.strip()
    return meta, text[m.end():]


def list_skills() -> list[dict[str, Any]]:
    out = []
    if not SKILLS_DIR.exists():
        return out
    for d in sorted(SKILLS_DIR.iterdir()):
        f = d / "SKILL.md"
        if f.exists():
            meta, _ = _split(f.read_text(encoding="utf-8"))
            refs = sorted(p.stem for p in (d / "references").glob("*.md")) if (d / "references").exists() else []
            out.append({"id": d.name, "name": meta.get("name", d.name), "description": meta.get("description", ""),
                        "references": refs})
    return out


def skill_body(sid: str) -> str:
    f = SKILLS_DIR / sid / "SKILL.md"
    return _split(f.read_text(encoding="utf-8"))[1].strip() if f.exists() else ""


def reference(sid: str, name: str) -> str | None:
    name = Path(name).stem
    if not re.fullmatch(r"[\w-]+", name):
        return None
    f = SKILLS_DIR / sid / "references" / f"{name}.md"
    return f.read_text(encoding="utf-8").strip() if f.exists() else None


def compose(skills: list[str], refs: list[str]) -> str:
    """System-prompt text for a role: each skill's body, then the references named for the role."""
    parts = []
    for sid in skills:
        body = skill_body(sid)
        if not body:
            continue
        parts.append(f"<skill name=\"{sid}\">\n{body}\n</skill>")
        for r in refs:
            txt = reference(sid, r)
            if txt:
                parts.append(f"<skill_reference skill=\"{sid}\" name=\"{r}\">\n{txt}\n</skill_reference>")
    return "\n\n".join(parts)


def mcp_server(skills: list[str]):
    """A tiny MCP server with `read_reference`, for references not already in the system prompt."""
    import json

    from claude_agent_sdk import create_sdk_mcp_server, tool
    avail = {s["id"]: s["references"] for s in list_skills() if s["id"] in skills}

    async def read_reference(args: dict[str, Any]) -> dict[str, Any]:
        sid = args.get("skill") or (skills[0] if skills else "")
        txt = reference(sid, str(args.get("name", "")))
        if txt is None:
            return {"content": [{"type": "text", "text": "unknown reference; available: " + json.dumps(avail)}],
                    "is_error": True}
        return {"content": [{"type": "text", "text": txt}]}

    t = tool("read_reference", "Read one reference document of your skill. Available: " + json.dumps(avail),
             {"type": "object", "properties": {"skill": {"type": "string"}, "name": {"type": "string"}},
              "required": ["name"]})(read_reference)
    return create_sdk_mcp_server(name="skill", version="1.0.0", tools=[t]), ["mcp__skill__read_reference"]
