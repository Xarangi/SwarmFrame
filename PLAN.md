# SwarmFrame — Implementation Plan

Adaptive, hierarchical observability and control for AI agent populations.
Drafted 2026-10-03 against the SwarmFrame brief, the Thimble repo, and the
SwarmChasing datasets (German Wiki, Transluce, AI Village).

## Implementation status (2026-10-03)

Built and tested: phases 0–4, most of 6, and the AI Village part of 5. See README.md.

Changes from the plan below, made during implementation:

- **AI Village is the primary source**, not German Wiki (user direction). It runs on a ~92 MB budgeted subset
  (full chat plus all computer-use session goals) fetched by `swarmscope fetch`. The German Wiki adapter is
  deferred; partial code is parked in `backend/swarmscope/sources/_later/`.
- **Structure-only data handling.** Incident datasets are inspected for structure, never content. Synthetic corpora
  use neutral placeholder prose and `[[technique:name]]` markers. No built-in attack-pattern detectors; label
  patterns are configured per pack.
- **The LLM backend is the local Claude Code CLI** through the Agent SDK (no API key on this machine). The Messages
  API and external JSON-lines backends exist behind the same router. Default mode is deterministic (`stub`).
- **Exposure channels are explicit** (`exposure_families` per pack). A private session goal is not an exposure path.
- **Live ingest is buffered** and flushed in bulk; per-event inserts saturated the loop at swarm rates.
- **At swarm scale the agent map collapses by group** (more than 40 agents).

- **The Executive is an agent organization** (2026-10-03, user direction): a main agent spawns and steers
  structured sub-agents (division analysts, specialists, native helpers) through org tools, defined by an
  editable topology. See README, "The analyst organization".
- **Conversation over the stream**: a built-in copilot (Agent SDK session with operator tools) and a Claude Code
  channel bridge (Thimble-style) share one dashboard chat, with approval cards and permission relay.
- **Timed simulator**: time-scale replay, gap skipping, jump with deterministic catch-up, live simulator speed.

- **Default strategy at scale: the triage tree** (2026-10-03, user direction: design for thousands of agents with
  thousands of messages each). Deterministic scale layer (cohorts, templates, outliers), three-lane triage with a
  secret-seed random audit, sector leads, a coverage ledger, and the swarm-oversight skill that instructs every role.
  Design and measurements: docs/STRATEGY.md.
- **Transluce pack** on the real public catalog (identity-free: the unit is the target), with a synthetic stand-in.
- **Agent-customizable dashboard**, which replaces the planned LLM-proposed ViewSpecs. A stream profile (structure
  only), a safe view query language, a versioned dashboard spec with atomic ops, a free auto-designer, and a Claude
  designer session with the dashboard-designer skill. The same tools are open to the copilot and the channel.

Not yet built: the orientation agent proper (proposing a Source Pack from a probe), the German Wiki pack,
ensemble-based shadow monitors, canaries, and injection detection beyond the untrusted envelope (phase 6).

---

## 0. What this plan changes relative to the brief

The brief is sound. Four deliberate departures:

1. **Live Claude Code swarms are a first-class source, not an afterthought.**
   The real goal is a system for a person to monitor *and control* thousands of
   running agents. The three historical datasets are replay sources that stress
   the abstractions; the live source is what makes SwarmFrame a tool rather than
   a viewer. Replay and live share one code path via a `Clock` abstraction.
   The live source also brings a **control plane** (pause, deny tool call,
   message, kill) that the brief does not have.

2. **Hand-written Source Packs first, Orientation Agent second.** The
   orientation agent only pays off once the pack format is stable and the UI
   reacts to capability profiles. Writing three packs by hand is the fastest way
   to find out what the format needs to express. Orientation is Phase 5.

3. **Watchers are deterministic by default.** Cheap, replayable, auditable.
   LLM cognition is spent at the monitor, executive and investigator layers.
   This is a strategy choice encoded in config, not a hard architectural
   constraint; an LLM watcher is just another strategy implementation.

4. **Evaluation baselines are org configs, not separate code.** "Single global
   summarizer", "uniform local summarizers" and "deterministic only" are each a
   YAML organization config that selects different strategies. This keeps the
   research story honest: the test bed is the product.

Everything else in the brief (Source Packs, capability profiles, Executive
state object, questions as objects, claims with epistemic status, evidence
boundary, risk dimensions, Situation Room, attention panel, config screen)
is kept.

---

## 1. Lessons taken from Thimble

Thimble (safety-research/thimble) is a Claude Code plugin for human oversight of
agent output. Relevant structure, and what we take or leave:

| Thimble | Take | Leave |
|---|---|---|
| Roles are swappable via three mechanisms: a prompt file, an Agent SDK program with `run(input)`, or any process speaking JSON lines on stdin/stdout | Yes. Our `Role` interface supports the same three backends, so a researcher can drop in a Python function, an SDK agent, or an external binary | |
| Extensions are folders with a manifest, loaded in place, validated on add, toggled per workspace | Yes, as the shape of Source Packs and Monitor Packs | The card/report/label vocabulary; ours is events/claims/questions |
| Every claim cites a specific tool-call reference and distinguishes "searched and found nothing" from a finding | Yes, as `EvidenceRef` and as a hard rule in the Claim model | |
| Orientation agent surveys, hypothesizes, proposes views, submits to a critic before concluding | Yes, as the design of the Phase 5 orientation role | |
| Custom views are notebook code in a Node sandbox | No. Constrained `ViewSpec` over a primitive library (brief section 6) | |
| Server has no auth, localhost only | Same for MVP | |
| Tight coupling to the interactive Claude Code session as "main" | No. SwarmFrame runs headless; Claude Code is one of several LLM backends | |

---

## 2. Architecture overview

```
 SOURCES                      CORE                                  HUMAN
 ---------------------        ------------------------------------  -----------------
 replay: german_wiki  -+      Ingest  -> EvidenceStore (DuckDB)      Situation Room
 replay: transluce    -+-->   Clock   -> Watchers (deterministic)    Investigation tree
 replay: ai_village   -+                -> Monitors (strategy slots) Attention / health
 live:   claude_code  -+                -> Executive (state object)  Configure screen
   ^  hooks / SDK                       -> Investigation Manager     Evidence drill-down
   |  control actions <---------------  ControlPlane <-------------- operator actions
                                         |
                                         +-> LLM layer: Agent SDK roles | Messages API roles | stubs
```

Three process boundaries only:

- **backend** (Python 3.12, FastAPI, asyncio): ingest, store, clock, monitoring
  organization, LLM roles, control plane, WebSocket event feed.
- **frontend** (React + Vite + TypeScript): panel registry, visualization
  primitives, Situation Room, config screen.
- **runner** (Python, same package, separate process): launches and supervises
  live Claude Code agents via the Claude Agent SDK; streams events to the
  backend; receives control actions.

No Kafka, no graph DB, no vector DB, no plugin marketplace.

---

## 3. Repository layout

```
swarmscope/
  pyproject.toml                 # uv-managed; one package `swarmscope`
  backend/swarmscope/
    core/                        # stable data model (pydantic): EvidenceEvent, Entity,
                                 #   Relation, Artifact, Claim, Question, Investigation,
                                 #   BriefingEntry, MonitorReport, AttentionRecord,
                                 #   ControlAction, CapabilityProfile
    store/                       # DuckDB + Parquet append-only tables; query helpers
    clock/                       # Clock protocol: ReplayClock(speed, cursor), WallClock
    ingest/                      # SourceAdapter protocol; batch + streaming ingest; evidence boundary
    sources/                     # one module per adapter: german_wiki.py, transluce.py,
                                 #   ai_village.py, claude_code.py
    org/                         # the monitoring organization
      registry.py                #   strategy + monitor + investigator registries
      watchers/                  #   deterministic detectors (rate, convergence, fingerprint reuse, ...)
      monitors/                  #   Monitor = manifest + strategy slots; coordination.py, propagation.py, environment.py
      executive.py               #   Executive role: state object in, state object out
      questions.py               #   Question lifecycle
      investigations.py          #   Investigation Manager, budgets, tree
      risk.py                    #   RiskVector + RiskPolicy -> WATCH/INVESTIGATE/ALERT/PAGE
      attention.py               #   token/cost accounting per monitor/investigation/target
    strategies/
      retrieval/  summarization/  evaluation/  escalation/  critique/
    roles/                       # LLM-backed roles: investigators (timeline, exposure, identity, skeptic),
                                 #   extractor (low-privilege), orientation (Phase 5)
    llm/                         # LLMBackend protocol: agent_sdk.py, messages_api.py, stub.py, external_process.py
                                 #   evidence_tools.py: in-process MCP server exposing the store to agents
    control/                     # ControlPlane: policies, pending approvals, action log
    api/                         # FastAPI routers + WebSocket feed; /ingest/claude-code hook endpoint
    cli.py                       # `swarmscope ingest|replay|serve|run-swarm|probe|eval`
  runner/                        # live Claude Code swarm runner (Agent SDK), scenario generator
  packs/                         # Source Packs (YAML + optional python): german_wiki/, transluce/, ai_village/, claude_code/
  orgs/                          # Organization configs: default.yaml, baseline_single_summarizer.yaml,
                                 #   baseline_uniform_local.yaml, baseline_deterministic.yaml
  frontend/
    src/panels/                  # one folder per panel; each exports a manifest {id, requires, optional}
    src/primitives/              # timeline, table, metric, feed, swimlane, graph, bipartite, heatmap,
                                 #   lineage, claim-card, investigation-tree
    src/views/                   # ViewSpec renderer (composes primitives from a spec)
    src/screens/                 # SituationRoom, Investigation, Configure, Evidence, Control
  evals/                         # harness, metrics, ground-truth annotations, scenario definitions
  docs/                          # ARCHITECTURE.md, PACKS.md, STRATEGIES.md, DATA-MODEL.md
```

---

## 4. Stable core: data model and interfaces

These change rarely. Everything else is replaceable.

### 4.1 Data model (pydantic, stored in DuckDB)

```
EvidenceEvent   id, ts, ts_uncertainty_s, source, actor_ref?, action, object_ref?, artifact_ref?,
                attributes(json), evidence_ref (source, locator, hash), ingest_seq
Entity          id, type (actor|resource|artifact|target|technique|goal|session|agent...),
                source, identity_confidence, attributes, aliases[]
Relation        src, dst, type, status, confidence, support[EvidenceRef]
Artifact        id, fingerprint (sha256), mime, size, first_seen, provenance, text_ref (never inline)
Claim           id, statement, status in {OBSERVED, DERIVED, SELF_REPORTED, INFERRED, CONTRADICTED, UNKNOWN},
                support[EvidenceRef|ClaimRef], counter[...], confidence, author (role id), ts, supersedes?
Question        id, text, priority, requested_by, required_capabilities[], status, answers[AnswerRef]
Investigation   id, question_id, root_node, nodes[{role, status, budget, result: Claim[]}], budget, status
BriefingEntry   id, ts, text, claims[], supersedes?, confidence, kind in {NEW, UPDATE, REVISED}
MonitorReport   id, monitor_id, window, observations[], claims[], questions[], escalation, cost
ExecutiveState  version, ts, population_state, workstreams[], important_changes[], hypotheses[],
                open_questions[], active_incidents[], blind_spots[], monitor_health, attention_policy_ref, briefing_tail[]
ContextLedger   version, entries[{kind, text, evidence_refs[], pinned_by, sticky|ttl_windows, tokens}]
Directive       id, ts, executive_version, kind in {ask, focus, defocus, activate, deactivate, tune, audit, brief_human},
                scope, payload, set_by (executive|human), status in {proposed, applied, rejected, expired}
AttentionPolicy scope, weight, reason, set_by, expires
AttentionRecord monitor_or_investigation_id, target_ref, tokens_in/out, cost_usd, calls, window
ControlAction   id, ts, actor (human|policy), target (agent|group|swarm), kind, payload, result
CapabilityProfile  source_id, capabilities: {name: {present: bool, quality: strong|partial|weak, note}}
```

Rules enforced in code, not prompts:

- A Claim with status OBSERVED must carry at least one `EvidenceRef` pointing
  at an event, or construction fails.
- A Claim produced by an LLM role defaults to INFERRED; promotion requires a
  deterministic check (for example `exposure_path_exists`) that attaches the
  evidence.
- Raw artifact text is never stored on the model; it lives in the store behind
  a `text_ref` and is only reachable through `read_raw` (see section 7).

### 4.2 Core protocols (Python `Protocol` classes; `strategies/` implements them)

```python
class SourceAdapter(Protocol):
    manifest: SourcePackManifest
    def probe(self, path) -> SchemaReport                 # columns, dtypes, samples, ranges
    def capabilities(self) -> CapabilityProfile
    def iter_events(self, path, since=None) -> Iterator[EvidenceEvent]   # ordered by ts
    def entities(self, path) -> Iterator[Entity]
    def artifacts(self, path) -> Iterator[Artifact]

class Clock(Protocol):                       # single driver for replay and live
    def now(self) -> datetime
    async def tick(self) -> TimeWindow        # yields the next window to process
    speed: float
    paused: bool

class Watcher(Protocol):                     # cheap, deterministic, incremental
    requires: set[str]
    def observe(self, window: TimeWindow, store) -> list[Observation]

class Retriever(Protocol):
    def retrieve(self, scope, window, store) -> EvidenceSlice

class Summarizer(Protocol):
    async def summarize(self, slice, prior) -> Summary

class Evaluator(Protocol):
    async def evaluate(self, summary, slice) -> tuple[list[Claim], list[Question]]

class Escalation(Protocol):
    def decide(self, claims, risk: RiskVector, budget) -> EscalationLevel

class Critic(Protocol):
    async def critique(self, claims, slice) -> list[Claim]   # may emit CONTRADICTED

class Monitor:                               # composition, not inheritance
    manifest: MonitorManifest                # id, requires, optional, outputs, tunables{name: (min, max, default)}
    retriever: Retriever
    summarizer: Summarizer
    evaluator: Evaluator
    escalation: Escalation
    critic: Critic | None
    async def run(self, window, observations, attention: AttentionPolicy) -> MonitorReport
    def apply(self, directive: Directive) -> None        # tune / focus / defocus

class ExecutiveStrategy(Protocol):           # the master role is itself a slot
    async def step(self, state: ExecutiveState, ledger: ContextLedger,
                   reports: list[MonitorReport], results: list[Investigation],
                   human_inputs: list[Directive]) -> ExecutiveStep   # new state, ledger edits, briefing, directives

class Role(Protocol):                        # any LLM-backed unit of cognition
    async def run(self, input: RoleInput, tools: EvidenceTools, budget: Budget) -> RoleOutput
    # backends: AgentSDKRole, MessagesAPIRole, StubRole, ExternalProcessRole (JSON lines)

class RiskPolicy(Protocol):
    def classify(self, risk: RiskVector) -> OperationalState

class ControlPolicy(Protocol):               # live source only
    async def on_tool_request(self, agent, tool, input) -> Allow | Deny | AskHuman
```

### 4.3 Registries and manifests

Every pluggable thing is a registered module with a YAML manifest. The
registry validates `requires` against the active `CapabilityProfile` at
startup and reports what is enabled, disabled, and why. The Configure screen
reads the same registry.

```yaml
# backend/swarmscope/org/monitors/propagation.yaml
id: propagation
requires: [artifacts, timestamps]
optional: [identities, communication]
slots:
  retrieval: graph_neighborhood
  summarization: extract_evaluate
  evaluation: hybrid
  escalation: adaptive
  critique: independent
outputs: [observations, claims, questions]
```

```yaml
# orgs/default.yaml
monitors: [executive, coordination, propagation, environment]
overrides:
  propagation.slots.evaluation: ensemble
budgets:
  max_active_investigations: 3
  max_investigators_per_incident: 4
  max_depth: 2
  max_usd_per_hour: 5
risk_policy: research_default
autonomy: auto_investigate      # observe | assisted | auto_investigate
executive:
  strategy: structured_state    # structured_state | persistent_session | hierarchical_summary | ensemble
  cadence_windows: 4
  ledger_token_budget: 6000
  directives:
    max_active_focuses: 8
    allowed_monitors: [coordination, propagation, environment, identity]
llm:
  mode: full                    # stub | cheap | full
  executive:    {backend: messages_api, model: claude-opus-5-5, effort: high}
  investigator: {backend: agent_sdk,    model: claude-sonnet-5-5, max_turns: 12, max_budget_usd: 0.5}
  extractor:    {backend: messages_api, model: claude-haiku-4-5}
  critic:       {backend: messages_api, model: claude-opus-5-5}
```

`mode: stub` returns canned structured outputs so the whole UI and pipeline run
without an API key. `mode: cheap` pins everything to Sonnet 5.5 at low effort,
matching the existing preference for minimal-cost real-model tests.

---

## 5. Source Packs

A pack is a folder: `source.yaml` (identity, file globs, evidence mapping),
`capabilities.yaml`, `monitors.yaml` (defaults), `questions.yaml` (reusable
questions), `views.yaml` (default ViewSpecs), and `adapter.py` when the mapping
needs code. Loading a pack registers the adapter and merges its defaults into
the org config unless overridden.

### 5.1 German Wiki (`packs/german_wiki`): replay centerpiece

Facts to design around (collusion.wiki and arXiv 2609.12748):

- About 18k agent posts; about 14.6k revisions over 4.6k pages from 3.1k actor names.
- May 11 to Jul 2 2026; heaviest Jun 16 to 22; moderator deletion sweeps from Jun 19.
- Fields: revision id, timestamp, page, actor (handle or IP), body, diff, sha.
- Identity is partial: handles are not stable backend agent IDs.

Mapping: revision to `resource.write`; delete to `resource.delete` (actor type
moderator, environment event); page to resource entity; actor to actor entity
with `identity_confidence: partial`; body to artifact with sha256 fingerprint;
diff to artifact modification; URLs in body to external resource entities.
Derived relations: `actor -writes-> page`, `artifact -reused_by-> actor` when a
fingerprint or a normalized text block recurs.

Capabilities: identities=partial, resources=strong, artifacts=strong,
timestamps=strong, communication=derived (co-editing), tool_calls=absent,
computer_state=absent.

First task is `swarmscope probe <download>` because the exact export format is
not confirmed; the adapter is written against the probe output.

### 5.2 Transluce (`packs/transluce`): stresses the abstraction

Facts: `urlquery-agent-activity-2026-09-23.zip`; 6,467 strong and 31,182
suggestive reports; Nov 2025 to Sep 2026; three documented exploitation
episodes (UNM library May 25 to 26, Data USA May 28, AIHW Jun 20 to 21);
individual agents largely distinct, so no persistent identity.

Mapping: report to `activity_episode` entity; scanned URL host to `target`
entity; decoded payload to artifact plus `technique` label (SQLi, XSS, path
traversal, base64 script, account creation) via deterministic regex first and
extractor LLM second; HTTP transaction to `resource.interaction` event.
Capabilities: identities=absent, targets=strong, techniques=derived,
artifacts=strong, timestamps=strong. Identity-centric panels must disappear
when this pack is active.

### 5.3 AI Village (`packs/ai_village`): rich first-party case

Facts: Hugging Face `aidigestorg/ai-village`; `events.jsonl.gz` (~233k),
`chat_messages` (~123k), `computer_use_sessions` (~37k), `computer_use_turns`
(~1.14M), `agent_memories` (~165k), `agents` (31), `village_goals` (~45),
`agent_goals`, `summaries` (~800), screenshots in daily tars. The dataset card
warns agents mis-see and misreport; screenshots are ground truth.

Slice: one village goal, one day. Mapping per brief section 3. Capabilities
include stated_goals, self_reports, computer_actions, screenshots. Enables the
narration-vs-action integrity monitor.

### 5.4 Live Claude Code swarm (`packs/claude_code`): the control case

Two ingestion paths, one event schema:

1. **Managed agents.** The `runner` launches N agents with `ClaudeSDKClient`
   and `ClaudeAgentOptions(hooks=..., can_use_tool=..., max_budget_usd=...,
   agents={...})`. Hooks `SessionStart`, `UserPromptSubmit`, `PreToolUse`,
   `PostToolUse`, `SubagentStop`, `Stop` emit events to the backend over a
   local HTTP/WebSocket channel. `ResultMessage.usage` and `total_cost_usd`
   feed attention accounting for the observed swarm too.
2. **External sessions.** Any Claude Code session can add a `hooks` block to
   `.claude/settings.json` whose command POSTs the hook JSON to
   `/ingest/claude-code`. This covers swarms the user runs elsewhere.

Mapping: tool call to `tool.invoke` event with tool name, redacted input hash,
file paths as resource entities; file write to `resource.write` plus artifact
fingerprint; subagent spawn to `agent.spawn` relation; assistant text to
`self_report` artifact (untrusted); session end to `agent.stop` with cost.
Capabilities: identities=strong, tool_calls=strong, artifacts=strong,
self_reports=strong, shared_resources=strong (filesystem, git, network hosts).

**Control plane** (only this pack): `can_use_tool` consults the active
`ControlPolicy`; outcomes are Allow, Deny (with a message to the agent), or
AskHuman (the request appears in the Situation Room with a timeout and a
default). Operator actions: pause/resume agent or group (block at next tool
request), inject message (`client.query`), interrupt (`client.interrupt()`),
kill, raise or lower budget. Every action is a `ControlAction` row and a
BriefingEntry.

**Scenario generator** (`runner/scenarios/`): launches swarms on toy research
tasks with planted behaviors (two groups converging on one file; one agent
copying another's output; an agent narrating a test pass that did not happen;
a decoy flood). This yields causal ground truth for the evaluation harness,
which the historical datasets cannot provide.

---

## 6. The monitoring organization

```
                    HUMAN  (briefing out; questions, pins, control actions in)
                      ^                              |
Executive  — master LLM role; owns the global context (ExecutiveState + ContextLedger)
   ^ MonitorReports / Claims / Answers        | Directives: Questions, AttentionPolicy,
   |                                          |   monitor activation, thresholds, scope
Domain monitors (coordination, propagation, environment, plus pack-specific)
   ^ Observations                             | scope and threshold overrides
Watchers (deterministic, every window)
   ^
Store (events for the window plus graph neighborhood)
```

Both directions are concrete objects in the store, not prompt text. Bottom-up
is `Observation -> MonitorReport -> Executive input`. Top-down is a
`Directive` emitted by the Executive and consumed by the Investigation
Manager, monitors and watchers (section 6.5). The Executive is the only role
that sees the whole population; everything below it is scoped.

### 6.1 Watchers (deterministic, Phase 1)

- `rate_change`: events per actor and per resource per window against a rolling baseline (z-score).
- `shared_resource_convergence`: distinct actor groups touching the same resource family within a window; groups from cheap incremental clustering over the co-edit graph.
- `artifact_reuse`: fingerprint or normalized-text-block recurrence across actors; records first-seen and exposure edges (actor touched the resource containing the artifact before reusing it).
- `new_actor_burst`: first-seen actors per window.
- `environment_response`: moderator, deletion and ban events; agent activity after them.
- `self_report_mismatch` (live and AI Village): narration claims ("tests pass", "done") with no matching tool event.

Each watcher emits `Observation{kind, scope, metrics, evidence_refs}`. Watchers never call an LLM.

### 6.2 Monitors (strategy composition, Phases 1 and 2)

Default strategies shipped in the MVP:

| Slot | MVP implementations |
|---|---|
| retrieval | `sliding_window`, `graph_neighborhood`, `sql_query`, `random_sample` |
| summarization | `structured_facts_only` (no LLM), `rolling_llm`, `extract_evaluate` |
| evaluation | `deterministic_rule`, `single_llm`, `hybrid` (LLM proposes, rules verify), `ensemble` (Phase 6) |
| escalation | `static_threshold`, `llm_decision`, `budget_aware` |
| critique | `none`, `independent_critic` |

Monitors output a `MonitorReport` with claims, questions and an escalation
level. The report is what the Executive sees. Raw text never travels in a
report; only `EvidenceRef`s and extractor-produced structured observations.

### 6.3 Executive: the master LLM role (Phase 2)

The Executive is the one always-on, population-wide LLM role. It is the
top of the hierarchy in both directions: every monitor report flows up to it,
and every question, attention decision and monitor reconfiguration flows down
from it. Humans talk to the swarm through it.

**What it holds.** Its context is two persistent, versioned objects:

- `ExecutiveState`: population_state, workstreams, important_changes,
  hypotheses (each with supporting and contradicting claim refs),
  open_questions, active_incidents, blind_spots, monitor_health,
  attention_policy, briefing (last N entries).
- `ContextLedger`: the "important context" that must survive across
  invocations without re-reading history. Entries are typed
  (`pinned_fact`, `key_entity`, `key_artifact`, `human_instruction`,
  `resolved_question`, `standing_hypothesis`), each carrying evidence refs, a
  `pinned_by` (executive | human), a `ttl_windows` or `sticky` flag, and a
  size budget. The Executive may add, refresh or expire entries each
  invocation; humans may pin or unpin from the UI. The ledger is rendered into
  the prompt after the frozen system prompt and schema so it stays inside the
  prompt-cache prefix.

**Each invocation** receives: previous `ExecutiveState`, the `ContextLedger`,
new `MonitorReport`s since the last run, completed investigation results,
human inputs (questions, pins, control actions), and a small set of
representative `EvidenceRef`s chosen by the reports. It returns, as structured
output against a JSON schema: the new state, ledger edits, `BriefingEntry`s,
and `Directive`s (section 6.5). It never receives raw swarm text.

**When it runs.** On a cadence (every K windows, K from org config) and
immediately on any INVESTIGATE or higher escalation, a completed
investigation, or a human message. Runs are serialized; reports arriving
mid-run queue for the next one.

**Executive strategy is itself a slot.** The baseline is
`structured_state` (above: stateless call, state object in and out, Messages
API with structured outputs). Alternatives that fit the same `Role`
interface: `persistent_session` (a long-lived `ClaudeSDKClient` session that
keeps its own conversational memory, with the state object written out each
turn for inspectability), `hierarchical_summary` (a tree of window summaries
the Executive queries), and `ensemble` (two executives with a reconciler).
Swapping the strategy changes nothing above (UI) or below (monitors).

State and ledger are versioned per invocation so a replay can be rewound and
the Executive's trajectory inspected, diffed and scored.

### 6.4 Questions and investigations (Phase 2)

A Question created by the Executive or a human goes to the Investigation
Manager, which checks `required_capabilities` against the profile, picks a
template (timeline, exposure, identity, skeptic), allocates budget from the org
config, and spawns investigator roles as Agent SDK agents with evidence tools
only. Results are Claims attached to tree nodes; the skeptic runs last and may
add CONTRADICTED claims. The manager enforces `max_active_investigations`,
`max_depth` and per-node `max_budget_usd`, and writes `AttentionRecord`s from
`ResultMessage` usage.

### 6.5 Top-down channel: Directives and attention policy (Phase 2)

A `Directive` is the Executive's only way to act on the system below it.
Kinds:

| Kind | Consumer | Effect |
|---|---|---|
| `ask` | Investigation Manager | Creates a `Question` with priority and required capabilities (section 6.4) |
| `focus` | Monitors | Adds a scope (entity, cluster, resource family, time range) with a weight to the `AttentionPolicy`; the monitor's retriever samples it more densely and its escalation threshold drops |
| `defocus` | Monitors | Removes or decays a focus entry |
| `activate` / `deactivate` | Registry | Turns a monitor on or off at runtime, within the org config's allowed set |
| `tune` | Watchers, monitors | Overrides a named threshold or window size for a scope (bounded by min and max in the manifest) |
| `audit` | Investigation Manager | Requests a random-coverage or shadow-monitor pass on a scope the Executive considers a blind spot |
| `brief_human` | UI, risk policy | Raises a briefing entry to ALERT or PAGE |

`AttentionPolicy` is a persistent table `{scope, weight, reason, set_by,
expires}` that monitors read at the start of every window. It is the same
table the Monitor Attention panel displays, so the human sees exactly where
the Executive is spending cognition and can edit it directly. Human edits are
`Directive`s with `set_by: human` and take precedence.

Directives are bounded by the org config (allowed monitors, max active
focuses, threshold ranges, budget per hour). Under `autonomy: observe` they
are recorded but not applied; under `assisted` they wait for human approval
in the UI; under `auto_investigate` they apply immediately. Every directive
is logged with the Executive invocation that produced it, so the top-down
path is auditable and replayable in the same way as the bottom-up path.

### 6.6 Risk (Phase 2)

`RiskVector{impact, scope, coordination_evidence, external_capability,
novelty, evidence_strength, monitor_integrity, uncertainty}` is filled by
monitors and watchers; a `RiskPolicy` maps it to WATCH, INVESTIGATE, ALERT or
PAGE. Two policies ship: `research_default` and `secops_strict`.

---

## 7. Evidence boundary and adversarial robustness

- Ingest computes sha256 for every artifact, stores text in a separate
  `artifact_text` table, strips or escapes control characters and HTML, and
  records provenance (source, locator, ingest time).
- LLM roles reach the store only through the in-process MCP server
  (`llm/evidence_tools.py`, built with the Agent SDK's `create_sdk_mcp_server`):
  `query_events`, `entity`, `neighborhood`, `artifact_meta`, `exposure_paths`,
  `timeline`, `read_raw`. `read_raw` returns text wrapped as
  `<untrusted source=... hash=...>...</untrusted>` with a size cap, and is
  denied to the Executive and the critic by role config.
- The **extractor** role (Haiku, no tools, structured output) is the only role
  that reads large volumes of raw text. It outputs observations, never
  instructions, and its outputs are tagged SELF_REPORTED or DERIVED.
- Optional plugins (Phase 6): shadow monitor, evaluator-disagreement alert,
  attention-flood detector (many low-value escalations from one cluster),
  prompt-injection pattern detector on `read_raw` results.

---

## 8. Frontend

React, Vite and TypeScript. Cytoscape.js for graphs; a lightweight chart
library (Observable Plot or Recharts) for timelines and heatmaps; Zustand for
state; a single WebSocket feed for events, briefing, questions and attention.

- **Panel registry.** Each panel exports `{id, title, requires, optional,
  component}`. The Situation Room reads the active `CapabilityProfile` from the
  API and mounts only satisfiable panels. Switching source visibly reflows.
- **Primitives.** timeline, table, metric, feed, swimlane, graph, bipartite,
  heatmap, lineage, claim-card, investigation-tree.
- **ViewSpec renderer.** A spec names a primitive, a backend query id, a
  transform, and evidence-linking behavior. Default views live in each pack's
  `views.yaml`; LLM-proposed views (Phase 5) go through the same validator.
- **Screens.** Situation Room (brief section 16 layout); Investigation (tree
  plus actions: deeper, alternative explanation, launch investigator, stop
  branch, pin, ask); Evidence (claim to support and counterevidence to raw
  event or artifact with provenance); Configure (monitors on/off, slot
  dropdowns from the registry, autonomy, budgets, panels; writes an org config
  override); Control (live pack only: agents table, pending approvals, action
  log).
- **Replay controls.** Play, pause, speed, scrub. The Clock is server-side so
  monitors and UI agree on "now".

---

## 9. Evaluation harness (`evals/`)

Runs an org config against a source, logs every claim, briefing entry,
escalation and AttentionRecord, and scores against ground truth:

- German Wiki: hand-annotated incident list (June surge onset, first
  cross-group convergence, deletion sweeps, propagation of specific
  techniques) with timestamps. Metrics: recall, time to first signal, time to
  correct explanation, unsupported-claim rate, tokens, fraction of corpus read
  raw.
- Scenario swarms (live pack): planted behaviors give exact ground truth,
  including decoy and misreport conditions.
- Baselines are `orgs/baseline_*.yaml`; the harness runs all configs on the
  same replay and emits a comparison table.

---

## 10. Phases

Effort is in focused engineering days. A hackathon cut-line is marked for
Sunday Oct 4, 17:00 PT.

### Phase 0: skeleton and replay (1 day)

- `pyproject`, package layout, DuckDB store, pydantic core model, registries.
- `Clock` with `ReplayClock`; `swarmscope probe` and `swarmscope ingest`.
- German Wiki adapter against the probe output; capability profile.
- FastAPI: `/events`, `/entities`, `/profile`, `/clock`, WebSocket feed.
- Frontend shell: panel registry, activity timeline, actor/resource bipartite
  graph, raw event feed, replay controls.
- Exit: replay runs, graph and timeline move, panels mount by capability.

### Phase 1: watchers and monitors (1 day)

- Watchers: rate_change, shared_resource_convergence, artifact_reuse,
  new_actor_burst, environment_response.
- Strategy implementations listed in 6.2 (LLM ones against `stub` and `cheap`
  modes); monitors: coordination, propagation, environment.
- MonitorReport persistence; "What deserves attention" panel.
- Exit: the June surge produces INVESTIGATE escalations from deterministic evidence.

### Phase 2: Executive, questions, investigations (1.5 days)

- ExecutiveState, ContextLedger and Directive schemas; `structured_state`
  executive strategy; BriefingEntry feed; Open Questions panel; ledger pin
  and unpin from the UI.
- Directive application: `ask` to the Investigation Manager, `focus` and
  `tune` into monitors via `AttentionPolicy`; Monitor Attention panel reads
  the same table.
- Investigation Manager with budgets; investigator roles (timeline, exposure,
  skeptic) on the Agent SDK with evidence tools; attention accounting.
- Claim-to-evidence drill-down screen; investigation tree with human actions.
- Risk vector and policy; ALERT surfaces in the UI.
- **Hackathon cut-line.** Phases 0 to 2 on German Wiki with the LLM in `cheap`
  mode is the two-minute demo in brief section 30 minus the dataset switch.

### Phase 3: second source and config (1 day)

- Transluce adapter and pack; verify identity panels disappear and
  target/technique panels appear; Executive text adapts.
- Configure screen wired to registries and org overrides; `orgs/baseline_*`.
- Exit: dataset switch demo; module enable/disable demo.

### Phase 4: live Claude Code swarm and control (2 days)

- `runner`: launch N agents from a scenario file; hooks to `/ingest`;
  `can_use_tool` to ControlPolicy; pause, message, interrupt, kill.
- `/ingest/claude-code` for external sessions plus a settings.json snippet.
- Control screen; pending approvals with timeout; action log in the briefing.
- Scenario generator with planted behaviors; `self_report_mismatch` watcher.
- Exit: run 20 to 50 agents, watch convergence detected live, deny a tool call
  from the UI, see the agent adapt.

### Phase 5: orientation agent, AI Village, custom views (2 to 3 days)

- Orientation role: probe, proposed Source Pack (YAML), validation stage that
  runs proposed queries and views against the corpus, human edits, activate.
- AI Village bounded slice; narration-vs-action monitor; screenshot evidence
  in drill-down.
- LLM-proposed ViewSpecs through the validator.

### Phase 6: evaluation and hardening (ongoing)

- `evals/` harness, German Wiki annotations, baseline comparison table.
- Ensemble evaluator, shadow monitor, disagreement alerts, attention-flood
  detection, injection detector on `read_raw`.
- Scale tests: a 1k-agent synthetic stream through ingest and watchers.

---

## 11. Model and SDK choices

- **Roles with tools** (investigators, orientation): `claude-agent-sdk`
  (`ClaudeAgentOptions` with `agents`, `hooks`, `mcp_servers`, `max_turns`,
  `max_budget_usd`, `output_format` JSON schema). Evidence tools as an
  in-process MCP server. Cost from `ResultMessage`.
- **Single-call roles** (Executive, critic, extractor, label strategies): the
  `anthropic` Messages API with structured outputs (`output_config.format`),
  adaptive thinking left on, effort set per role. Prompt caching: stable
  system prompt and schema first, state and deltas after the cache breakpoint.
- **Defaults**: Opus 5.5 for Executive and critic, Sonnet 5.5 for
  investigators, Haiku 4.5 for extractors; all overridable per org config.
  `stub` and `cheap` modes for development.
- **Monitored swarm**: the runner uses the Agent SDK exclusively; model per
  scenario.
- Both backends sit behind the `Role` protocol with an `ExternalProcessRole`
  (JSON lines) so a non-Anthropic or non-LLM implementation can be dropped in.

---

## 12. Risks and open decisions

| Risk | Mitigation |
|---|---|
| German Wiki export format unknown until downloaded | `probe` first; the adapter is one file; mapping lives in YAML where possible |
| Transluce zip structure unknown | Same; Transluce is Phase 3 so Phases 0 to 2 are unaffected |
| LLM roles slow the replay | Executive runs on cadence, not per window; investigations are async; replay speed is independent of LLM latency |
| Attention flood at 1k agents | Watchers are O(events); monitors run on aggregates; budget-aware escalation caps active investigations |
| Agents manipulating monitors | Evidence boundary (section 7); Executive never sees raw text; skeptic role; disagreement alerts in Phase 6 |
| Over-engineering strategy slots before any monitor works | Phase 1 ships `structured_facts_only` plus `deterministic_rule` end to end before any LLM slot |

Open decisions to settle during Phase 0:

1. Chart library (Observable Plot vs Recharts) after a one-hour spike on the timeline primitive.
2. Whether hook events from external Claude Code sessions include tool inputs verbatim or hashed by default. Proposed default: hashed, with an allowlist of safe read-only tools.
3. Whether the Executive gets a `neighborhood` tool in Phase 2 or stays tool-free until Phase 4.

---

## 13. References

- Thimble: https://github.com/safety-research/thimble (docs/agents.md, docs/extensions.md, prompts/orient.md)
- German Wiki data: https://collusion.wiki ; paper arXiv:2609.12748 (code on Zenodo 10.5281/zenodo.22689980)
- Transluce agent activity: https://transluce.org/agent-activity (urlquery-agent-activity-2026-09-23.zip)
- AI Village dataset: https://huggingface.co/datasets/aidigestorg/ai-village
- SwarmTraces (candidate fifth source; 97% of payloads lack timestamps): https://swarmtraces.org
- Hackathon: https://swarmchasing.com (Oct 3 to 4, submissions Sunday 17:00 PT)
- Claude Agent SDK (Python): https://code.claude.com/docs/en/agent-sdk/python ; hooks: https://code.claude.com/docs/en/agent-sdk/hooks
