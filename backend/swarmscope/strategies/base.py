"""Shared types for strategy slots. A monitor is retrieval -> summarization -> evaluation ->
escalation -> critique; each slot is a registered, swappable implementation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable

from swarmscope.core.models import (AttentionFocus, CapabilityProfile, Claim, EvidenceEvent, Observation,
                                    OperationalState, Question, RiskVector, TimeWindow)
from swarmscope.llm.evidence_tools import EvidenceTools
from swarmscope.llm.router import LLMRouter
from swarmscope.store.store import Store


@dataclass
class MonitorContext:
    monitor_id: str
    store: Store
    window: TimeWindow
    window_len: timedelta
    profile: CapabilityProfile
    pack: dict[str, Any]
    router: LLMRouter
    focuses: list[AttentionFocus]
    params: dict[str, Any]
    questions: list[dict[str, Any]]          # pack question templates
    tools: Callable[[str], EvidenceTools]    # role -> tools bound to horizon
    population: int
    prior_summary: str = ""
    investigations_busy: bool = False
    budget_left: float = 1.0

    def label(self, eid: str | None) -> str:
        e = self.store.entity(eid)
        return e.label if e else (eid or "unknown")


@dataclass
class EvidenceSlice:
    observations: list[Observation]
    events: list[EvidenceEvent] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    raw_samples: list[tuple[str, str]] = field(default_factory=list)   # (artifact id, untrusted-wrapped text)


@dataclass
class Fact:
    text: str
    evidence: list[str]                       # event ids
    status: str = "OBSERVED"                  # OBSERVED | DERIVED | SELF_REPORTED


@dataclass
class Summary:
    text: str
    facts: list[Fact]
    cost_usd: float = 0.0
    tokens: int = 0


@dataclass
class Evaluation:
    claims: list[Claim]
    questions: list[Question]
    headline: str
    disagreement: float | None = None
    cost_usd: float = 0.0
    tokens: int = 0


@dataclass
class EscalationDecision:
    level: OperationalState
    reason: str
    risk: RiskVector


CLAIMS_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "claims": {"type": "array", "items": {"type": "object", "properties": {
            "statement": {"type": "string"},
            "status": {"type": "string", "enum": ["OBSERVED", "DERIVED", "INFERRED", "UNKNOWN"]},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"}}, "required": ["statement", "status", "evidence_ids", "confidence"]}},
        "questions": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "kind": {"type": "string"},
            "priority": {"type": "string", "enum": ["low", "medium", "high", "critical"]}},
            "required": ["text", "kind", "priority"]}},
    },
    "required": ["headline", "claims", "questions"],
}
