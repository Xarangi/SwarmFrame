"""Source Pack loading.

A pack is a folder under packs/ with:
  source.yaml        identity, adapter import path, field mapping
  capabilities.yaml  what this source can and cannot tell us
  monitors.yaml      default monitors + slot overrides for this source
  questions.yaml     reusable investigation questions
  views.yaml         default ViewSpecs for the UI
  oversight.yaml     which team (topology) reads this source, and overrides for it
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from swarmscope.core.models import Capability, CapabilityProfile

ROOT = Path(__file__).resolve().parents[3]
PACKS_DIR = ROOT / "packs"


@dataclass
class SourcePack:
    id: str
    dir: Path
    source: dict[str, Any]
    capabilities: CapabilityProfile
    monitors: dict[str, Any] = field(default_factory=dict)
    questions: list[dict[str, Any]] = field(default_factory=list)
    views: list[dict[str, Any]] = field(default_factory=list)
    oversight: dict[str, Any] = field(default_factory=dict)

    def adapter(self) -> Any:
        mod, _, cls = self.source["adapter"].partition(":")
        return getattr(importlib.import_module(mod), cls)(self)


def _yaml(p: Path, default: Any) -> Any:
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else default


def load_pack(pack_id: str) -> SourcePack:
    d = PACKS_DIR / pack_id
    if not d.exists():
        raise FileNotFoundError(f"no source pack {pack_id!r} in {PACKS_DIR}")
    src = _yaml(d / "source.yaml", {})
    caps_raw = _yaml(d / "capabilities.yaml", {})
    caps = CapabilityProfile(
        source=pack_id, title=src.get("title", pack_id), description=src.get("description", ""),
        entity_noun=src.get("entity_noun", "actor"), resource_noun=src.get("resource_noun", "resource"),
        workstream_noun=src.get("workstream_noun", "workstream"), group_noun=src.get("group_noun", "group"), naming=" ".join(str(src.get("naming", "")).split()),
        live=bool(src.get("live", False)),
        capabilities={k: Capability(**v) for k, v in (caps_raw.get("capabilities") or {}).items()},
    )
    return SourcePack(id=pack_id, dir=d, source=src, capabilities=caps,
                      monitors=_yaml(d / "monitors.yaml", {}), questions=_yaml(d / "questions.yaml", []) or [],
                      views=_yaml(d / "views.yaml", []) or [], oversight=_yaml(d / "oversight.yaml", {}) or {})


def list_packs() -> list[SourcePack]:
    return [load_pack(p.name) for p in sorted(PACKS_DIR.iterdir()) if (p / "source.yaml").exists()]
