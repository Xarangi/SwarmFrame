"""Structured output schemas for organization roles. Roles pick one by name, or define a custom one."""
from __future__ import annotations

from typing import Any

from swarmscope.org.executive import EXEC_SCHEMA

_CLAIM = {"type": "object", "properties": {
    "statement": {"type": "string"},
    "status": {"type": "string", "enum": ["OBSERVED", "DERIVED", "SELF_REPORTED", "INFERRED", "CONTRADICTED", "UNKNOWN"]},
    "evidence_ids": {"type": "array", "items": {"type": "string"}},
    "confidence": {"type": "number"}}, "required": ["statement", "status", "evidence_ids", "confidence"]}

_FLAG = {"type": "object", "properties": {
    "kind": {"type": "string", "enum": ["convergence", "propagation", "integrity", "environment", "goals", "surge", "general"]},
    "scope": {"type": "string"}, "text": {"type": "string"},
    "priority": {"type": "string", "enum": ["low", "medium", "high", "critical"]}},
    "required": ["kind", "scope", "text", "priority"]}

_ORG_ACTION = {"type": "object", "properties": {
    "action": {"type": "string", "enum": ["spawn", "run", "retire", "split", "merge", "set_triage"]},
    "role": {"type": "string"}, "scope": {"type": "string"}, "agent_id": {"type": "string"},
    "brief": {"type": "string"}, "divisions": {"type": "array", "items": {"type": "string"}},
    "triage": {"type": "object"}},
    "required": ["action"]}

DIRECTOR = {**EXEC_SCHEMA, "properties": {**EXEC_SCHEMA["properties"],
            "org_actions": {"type": "array", "items": _ORG_ACTION},
            "org_rationale": {"type": "string"}}}

_LOOKED = {"type": "object", "properties": {
    "scope": {"type": "string"}, "status": {"type": "string", "enum": ["nothing_notable", "notable", "concerning"]},
    "finding": {"type": "string"}}, "required": ["scope", "status", "finding"]}

DIVISION_REPORT = {"type": "object", "properties": {
    "headline": {"type": "string"},
    "summary": {"type": "string"},
    "status": {"type": "string", "enum": ["quiet", "normal", "notable", "concerning"]},
    "claims": {"type": "array", "items": _CLAIM},
    "flags": {"type": "array", "items": _FLAG},
    "recommend": {"type": "object", "properties": {
        "split": {"type": "boolean"}, "specialist": {"type": "string"}, "retire": {"type": "boolean"},
        "reason": {"type": "string"}}, "required": ["split", "retire"]},
    "looked_at": {"type": "array", "items": _LOOKED},
    "blind_spots": {"type": "array", "items": {"type": "string"}},
    "cohort_labels": {"type": "array", "items": {"type": "object", "properties": {
        "cohort": {"type": "string"}, "task": {"type": "string"},
        "state": {"type": "string", "enum": ["working", "talking", "blocked", "idle", "mixed"]},
        "confidence": {"type": "number"}}, "required": ["cohort", "task", "confidence"]}},
    "notes_for_next_time": {"type": "string"}},
    "required": ["headline", "summary", "status", "claims", "flags", "recommend", "notes_for_next_time"]}

FINDING = {"type": "object", "properties": {
    "headline": {"type": "string"},
    "verdict": {"type": "string", "enum": ["supported", "partially_supported", "unsupported", "unknown"]},
    "claims": {"type": "array", "items": _CLAIM},
    "open_points": {"type": "array", "items": {"type": "string"}},
    "notes_for_next_time": {"type": "string"}},
    "required": ["headline", "verdict", "claims", "open_points", "notes_for_next_time"]}

_NEW_ROLE = {"type": "object", "properties": {
    "id": {"type": "string"}, "title": {"type": "string"}, "description": {"type": "string"},
    "kind": {"type": "string"}, "prompt": {"type": "string"},
    "tools": {"type": "array", "items": {"type": "string"}}, "raw_access": {"type": "boolean"},
    "model": {"type": "string"}, "effort": {"type": "string"}, "max_turns": {"type": "integer"},
    "output": {"type": "string"}, "scope": {"type": "string"}, "memory": {"type": "string"},
    "standing": {"type": "boolean"}, "question_kinds": {"type": "array", "items": {"type": "string"}},
    "reason": {"type": "string"}},
    "required": ["id", "title", "prompt", "tools", "reason"]}

# The Scout's report (docs/OVERSIGHT_ARCHITECTURES.md §6.3): a team shape as data, validated before anything applies.
ARCHITECTURE_PROPOSAL = {"type": "object", "properties": {
    "headline": {"type": "string"},
    "base": {"type": "string", "description": "a library topology id to build on"},
    "partition": {"type": "object", "properties": {"by": {"type": "string"}, "field": {"type": "string"}, "span": {"type": "integer"}}},
    "standing": {"type": "array", "items": {"type": "object", "properties": {"role": {"type": "string"}, "scope": {"type": "string"}, "brief": {"type": "string"}}, "required": ["role"]}},
    "new_roles": {"type": "array", "items": _NEW_ROLE},
    "questions": {"type": "object"},
    "human": {"type": "object", "properties": {"interrupt_at": {"type": "string"}, "briefing_every": {"type": "string"}}},
    "reasons": {"type": "array", "items": {"type": "string"}},
    "blind_spots": {"type": "array", "items": {"type": "string"}}},
    "required": ["headline", "base", "reasons", "blind_spots"]}

SCHEMAS: dict[str, dict[str, Any]] = {"director": DIRECTOR, "division_report": DIVISION_REPORT, "finding": FINDING,
                                      "architecture_proposal": ARCHITECTURE_PROPOSAL}
