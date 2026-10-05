"""Stable core data model.

These objects are the contract between sources, the monitoring organization,
the API and the UI. Strategies, monitors and views change; these should not.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------- evidence

class EvidenceRef(BaseModel):
    """Pointer to a concrete piece of evidence. Every OBSERVED claim needs one."""
    kind: Literal["event", "artifact", "entity", "claim", "observation", "query"] = "event"
    id: str
    note: str | None = None


class EvidenceEvent(BaseModel):
    id: str
    ts: datetime
    ts_uncertainty_s: float = 0.0
    source: str
    actor: str | None = None          # entity id (may be None: Transluce has no stable actors)
    action: str                       # resource.write, resource.delete, tool.invoke, chat.message, ...
    object: str | None = None         # entity id of resource / target
    artifact: str | None = None       # artifact id
    attributes: dict[str, Any] = Field(default_factory=dict)
    locator: str | None = None        # where in the raw source this came from
    seq: int = 0


class Entity(BaseModel):
    id: str
    type: str                         # actor | resource | target | technique | goal | session | agent | moderator
    source: str
    label: str
    identity_confidence: Literal["strong", "partial", "weak", "none"] = "strong"
    group: str | None = None          # cohort / family assigned by adapter or identity resolution
    attributes: dict[str, Any] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)


class Relation(BaseModel):
    src: str
    dst: str
    type: str
    status: ClaimStatus | None = None
    confidence: float = 1.0
    support: list[EvidenceRef] = Field(default_factory=list)


class Artifact(BaseModel):
    id: str
    fingerprint: str                  # sha256 of normalized content
    mime: str = "text/plain"
    size: int = 0
    first_seen: datetime | None = None
    first_actor: str | None = None
    provenance: str | None = None
    blocks: list[str] = Field(default_factory=list)   # fingerprints of normalized text blocks
    labels: list[str] = Field(default_factory=list)   # e.g. techniques detected deterministically


# ---------------------------------------------------------------- epistemics

class ClaimStatus(str, Enum):
    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    SELF_REPORTED = "SELF_REPORTED"
    INFERRED = "INFERRED"
    CONTRADICTED = "CONTRADICTED"
    UNKNOWN = "UNKNOWN"


Relation.model_rebuild()


class Claim(BaseModel):
    id: str = Field(default_factory=lambda: new_id("clm"))
    statement: str
    status: ClaimStatus
    support: list[EvidenceRef] = Field(default_factory=list)
    counter: list[EvidenceRef] = Field(default_factory=list)
    confidence: float = 0.5
    author: str = "system"
    ts: datetime | None = None
    supersedes: str | None = None
    scope: str | None = None

    @model_validator(mode="after")
    def _observed_needs_evidence(self) -> "Claim":
        if self.status in (ClaimStatus.OBSERVED, ClaimStatus.DERIVED) and not self.support:
            raise ValueError(f"{self.status.value} claim requires at least one EvidenceRef: {self.statement!r}")
        return self


class Observation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("obs"))
    watcher: str
    kind: str
    window_end: datetime
    scope: str                         # e.g. "family:Prüfung", "artifact:art_x", "target:aihw.gov.au"
    title: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    severity: float = 0.0              # 0..1
    evidence: list[EvidenceRef] = Field(default_factory=list)


class Priority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Question(BaseModel):
    id: str = Field(default_factory=lambda: new_id("q"))
    text: str
    priority: Priority = Priority.medium
    requested_by: str = "executive"
    required_capabilities: list[str] = Field(default_factory=list)
    scope: str | None = None
    kind: str = "general"              # convergence | propagation | identity | integrity | environment | general
    status: Literal["open", "investigating", "answered", "blocked", "dismissed"] = "open"
    created: datetime | None = None
    answer: "Answer | None" = None
    blocked_reason: str | None = None


class Answer(BaseModel):
    text: str
    status: Literal["supported", "partially_supported", "unsupported", "unknown"]
    claims: list[str] = Field(default_factory=list)      # claim ids
    confidence: float = 0.5
    unresolved: list[str] = Field(default_factory=list)


Question.model_rebuild()


NodeStatus = Literal["pending", "running", "done", "partial", "failed", "stopped"]


class InvestigationNode(BaseModel):
    id: str = Field(default_factory=lambda: new_id("node"))
    parent: str | None = None
    role: str                          # timeline | exposure | identity | skeptic | custom
    title: str
    status: NodeStatus = "pending"
    claims: list[str] = Field(default_factory=list)
    summary: str | None = None
    budget_usd: float = 0.0
    spent_usd: float = 0.0
    tokens: int = 0
    started: datetime | None = None
    finished: datetime | None = None
    requested_by: str = "manager"


class Investigation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("inv"))
    question_id: str
    title: str
    scope: str | None = None
    nodes: list[InvestigationNode] = Field(default_factory=list)
    status: Literal["open", "running", "concluded", "stopped"] = "open"
    budget_usd: float = 0.5
    spent_usd: float = 0.0
    opened: datetime | None = None
    concluded: datetime | None = None
    conclusion: str | None = None
    pinned: bool = False


class BriefingEntry(BaseModel):
    id: str = Field(default_factory=lambda: new_id("brf"))
    ts: datetime
    text: str
    kind: Literal["NEW", "UPDATE", "REVISED", "STATUS", "CONTROL", "HUMAN"] = "STATUS"
    claims: list[str] = Field(default_factory=list)
    supersedes: str | None = None
    confidence: float = 0.6
    level: Literal["WATCH", "INVESTIGATE", "ALERT", "PAGE", "INFO"] = "INFO"


class OperationalState(str, Enum):
    NONE = "NONE"
    WATCH = "WATCH"
    INVESTIGATE = "INVESTIGATE"
    ALERT = "ALERT"
    PAGE = "PAGE"


class RiskVector(BaseModel):
    impact: float = 0.0
    scope: float = 0.0
    coordination_evidence: float = 0.0
    external_capability: float = 0.0
    novelty: float = 0.0
    evidence_strength: float = 0.0
    monitor_integrity: float = 1.0
    uncertainty: float = 0.5

    def merge(self, other: "RiskVector") -> "RiskVector":
        d = {k: max(getattr(self, k), getattr(other, k)) for k in type(self).model_fields}
        d["monitor_integrity"] = min(self.monitor_integrity, other.monitor_integrity)
        return RiskVector(**d)


class MonitorReport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("rep"))
    monitor: str
    window_end: datetime
    scope: str
    headline: str
    observations: list[str] = Field(default_factory=list)   # observation ids
    claims: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    risk: RiskVector = Field(default_factory=RiskVector)
    escalation: OperationalState = OperationalState.NONE
    summary: str = ""
    strategies: dict[str, str] = Field(default_factory=dict)
    cost_usd: float = 0.0
    tokens: int = 0
    disagreement: float | None = None


class AttentionRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("att"))
    owner: str                       # monitor id, investigation id, executive
    owner_kind: Literal["watcher", "monitor", "executive", "investigator", "critic", "extractor", "orientation"]
    scope: str | None = None
    ts: datetime
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    calls: int = 0
    backend: str = "stub"
    model: str | None = None


# ---------------------------------------------------------------- top-down

DirectiveKind = Literal["ask", "focus", "defocus", "activate", "deactivate", "tune", "audit", "brief_human"]


class Directive(BaseModel):
    id: str = Field(default_factory=lambda: new_id("dir"))
    ts: datetime
    executive_version: int | None = None
    kind: DirectiveKind
    scope: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    set_by: Literal["executive", "human", "policy"] = "executive"
    status: Literal["proposed", "applied", "rejected", "expired"] = "proposed"


class AttentionFocus(BaseModel):
    scope: str
    weight: float = 1.0
    reason: str = ""
    set_by: Literal["executive", "human", "policy"] = "executive"
    expires: datetime | None = None
    directive: str | None = None


class LedgerEntry(BaseModel):
    id: str = Field(default_factory=lambda: new_id("led"))
    kind: Literal["pinned_fact", "key_entity", "key_artifact", "human_instruction",
                  "resolved_question", "standing_hypothesis"]
    text: str
    evidence: list[EvidenceRef] = Field(default_factory=list)
    pinned_by: Literal["executive", "human"] = "executive"
    sticky: bool = False
    ttl_windows: int | None = 24
    created: datetime | None = None
    refreshed: datetime | None = None

    @property
    def tokens(self) -> int:
        return max(1, len(self.text) // 4)


class ContextLedger(BaseModel):
    version: int = 0
    entries: list[LedgerEntry] = Field(default_factory=list)


class Hypothesis(BaseModel):
    id: str = Field(default_factory=lambda: new_id("hyp"))
    text: str
    status: Literal["candidate", "supported", "weakened", "rejected"] = "candidate"
    confidence: float = 0.4
    support: list[str] = Field(default_factory=list)   # claim ids
    against: list[str] = Field(default_factory=list)


class Workstream(BaseModel):
    id: str
    label: str
    actors: int = 0
    events: int = 0
    trend: Literal["rising", "steady", "falling", "new"] = "steady"
    note: str = ""


class LevelChange(BaseModel):
    """One step in a case's escalation history: who moved it, to what, why, on which evidence."""
    ts: datetime
    level: str
    by: str
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)
    held: str | None = None            # set when a higher level was asked for but not granted, and why


class Incident(BaseModel):
    """A tracked case: anything notable the organization knows about, whoever saw it first (a watcher, an analyst,
    a specialist, a person). One per scope while open. Levels only rise through `org.cases`; they fall only with a
    recorded reason."""
    id: str = Field(default_factory=lambda: new_id("inc"))
    title: str
    scope: str
    level: OperationalState
    opened: datetime
    reports: list[str] = Field(default_factory=list)
    investigation: str | None = None
    risk: RiskVector = Field(default_factory=RiskVector)
    status: Literal["open", "monitoring", "resolved"] = "open"
    history: list[LevelChange] = Field(default_factory=list)
    views: list[str] = Field(default_factory=list)       # independent sources that saw it: monitor:<id>, role:<id>, human
    owner: str | None = None                             # who is tracking it (an agent title or "human")
    last_seen: datetime | None = None
    pending_level: str | None = None                     # a higher level asked for and held back (see history[-1].held)
    acknowledged: datetime | None = None
    acknowledged_by: str | None = None


class ExecutiveState(BaseModel):
    version: int = 0
    ts: datetime | None = None
    population_state: str = "No activity observed yet."
    workstreams: list[Workstream] = Field(default_factory=list)
    important_changes: list[str] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)   # question ids
    active_incidents: list[Incident] = Field(default_factory=list)
    blind_spots: list[str] = Field(default_factory=list)
    monitor_health: dict[str, Any] = Field(default_factory=dict)
    strategy: str = "structured_state"


class ExecutiveStep(BaseModel):
    """What one Executive invocation returns."""
    state: ExecutiveState
    ledger_add: list[LedgerEntry] = Field(default_factory=list)
    ledger_expire: list[str] = Field(default_factory=list)
    briefing: list[BriefingEntry] = Field(default_factory=list)
    directives: list[Directive] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)


# ---------------------------------------------------------------- capability & control

class Capability(BaseModel):
    present: bool
    quality: Literal["strong", "partial", "weak", "derived", "absent"] = "strong"
    note: str = ""


class CapabilityProfile(BaseModel):
    source: str
    title: str
    description: str = ""
    capabilities: dict[str, Capability]
    entity_noun: str = "actor"       # what the population is made of: actor | episode | agent
    resource_noun: str = "resource"
    workstream_noun: str = "workstream"  # what a family of activity is called here: workstream | page family | method
    group_noun: str = "group"            # what an entity's group is here: team | model family | handle group
    naming: str = ""                     # how names in this source are formed, for people reading them
    live: bool = False
    synthetic: bool = False

    def has(self, name: str) -> bool:
        c = self.capabilities.get(name)
        return bool(c and c.present)


class ControlAction(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ctl"))
    ts: datetime
    actor: Literal["human", "policy", "executive"] = "human"
    target: str                      # agent id | group:<g> | swarm
    kind: Literal["pause", "resume", "message", "interrupt", "kill", "budget", "allow", "deny"]
    payload: dict[str, Any] = Field(default_factory=dict)
    result: str = "pending"


class TimeWindow(BaseModel):
    start: datetime
    end: datetime
    index: int
