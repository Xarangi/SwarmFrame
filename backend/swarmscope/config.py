"""Organization config: orgs/<name>.yaml, merged with the active Source Pack's monitor defaults
and runtime overrides from the UI. Dotted keys ("propagation.slots.evaluation") address nested values."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from swarmscope.ingest.packs import ROOT

ORGS_DIR = ROOT / "orgs"


def list_orgs() -> list[dict[str, str]]:
    out = []
    for p in sorted(ORGS_DIR.glob("*.yaml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        out.append({"id": p.stem, "name": d.get("name", p.stem), "description": d.get("description", "")})
    return out


def load_org(name: str = "default") -> dict[str, Any]:
    base = yaml.safe_load((ORGS_DIR / "default.yaml").read_text(encoding="utf-8"))
    if name != "default":
        deep_merge(base, yaml.safe_load((ORGS_DIR / f"{name}.yaml").read_text(encoding="utf-8")) or {})
    base["id"] = name
    return base


def deep_merge(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_merge(dst[k], v)
        else:
            dst[k] = copy.deepcopy(v)
    return dst


def set_dotted(d: dict[str, Any], key: str, value: Any) -> None:
    parts = key.split(".")
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = value


def get_dotted(d: dict[str, Any], key: str, default: Any = None) -> Any:
    for p in key.split("."):
        if not isinstance(d, dict) or p not in d:
            return default
        d = d[p]
    return d


# Roles that act for the person directly: the lead of the analyst team and the helpers in the dashboard. In the
# "custom" mode they run on the primary model; everything the lead spawns runs on the sub-agent model.
PRIMARY_ROLES = {"executive", "director", "copilot", "designer"}

MODELS = [
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5", "note": "strongest reasoning; highest cost"},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "note": "balanced; the usual choice"},
    {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5", "note": "fastest and cheapest"},
    {"id": "claude-fable-5-1", "label": "Claude Fable 5.1", "note": "newest family member"},
]
EFFORTS = ["low", "medium", "high"]


def custom_llm(org: dict[str, Any], primary: bool) -> dict[str, Any]:
    """The model picker's choice for a primary or a sub-agent role: {backend, model, effort}."""
    llm = org.get("llm", {})
    p = {"backend": "claude_code", "model": "claude-sonnet-5-5", "effort": "low", **(llm.get("primary") or {})}
    if primary:
        return p
    return {"backend": p["backend"], "model": "claude-sonnet-5-5", "effort": "low", **(llm.get("subagents") or {})}


def _model_name(mid: str | None) -> str:
    return next((m["label"].replace("Claude ", "") for m in MODELS if m["id"] == mid), mid or "?")


def llm_label(org: dict[str, Any]) -> dict[str, str]:
    """How the reading is done, for people: {short, long}."""
    llm = org.get("llm", {})
    mode = llm.get("mode", "stub")
    if mode == "stub":
        return {"short": "rules only", "long": "Fixed rules; no model calls."}
    if mode == "custom":
        p, s = custom_llm(org, True), custom_llm(org, False)
        return {"short": f"{_model_name(p['model'])} · {p['effort']}",
                "long": f"Lead and helper on {_model_name(p['model'])} ({p['effort']} effort); explorers and other "
                        f"sub-agents on {_model_name(s['model'])} ({s['effort']})."}
    if mode == "cheap":
        c = llm.get("cheap", {})
        return {"short": f"{_model_name(c.get('model'))} · {c.get('effort', 'low')}",
                "long": f"Every role on {_model_name(c.get('model'))} ({c.get('effort', 'low')} effort)."}
    return {"short": "Claude · per role", "long": "Each role on the model set in the organization config."}


def role_llm(org: dict[str, Any], role: str) -> dict[str, Any]:
    """Resolve backend/model/effort for a role given the global mode."""
    llm = org.get("llm", {})
    mode = llm.get("mode", "stub")
    if mode == "stub":
        return {"backend": "stub", "model": None, "effort": None}
    if mode == "custom":
        return {**custom_llm(org, role in PRIMARY_ROLES), "max_turns": llm.get("roles", {}).get(role, {}).get("max_turns", 8)}
    if mode == "cheap":
        return {**llm.get("cheap", {}), "max_turns": llm.get("roles", {}).get(role, {}).get("max_turns", 6)}
    return {"backend": "claude_code", **llm.get("roles", {}).get(role, {})}


def save_org(org: dict[str, Any], name: str) -> Path:
    p = ORGS_DIR / f"{name}.yaml"
    p.write_text(yaml.safe_dump({k: v for k, v in org.items() if k != "id"}, sort_keys=False), encoding="utf-8")
    return p
