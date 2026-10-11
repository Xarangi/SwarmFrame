# Architecture and the evidence boundary

How SwarmFrame is put together, the parts that change rarely, and why it treats everything the watched agents wrote
as untrusted. The detailed settings and files are in the [technical reference](../REFERENCE.md).

## Three processes

| Process | What it runs |
|---|---|
| Backend (Python, FastAPI, asyncio) | Ingest, the evidence store, the clock, the monitoring, the analyst team, the control plane, the WebSocket feed |
| Frontend (React, Vite, TypeScript) | The dashboard: screens, panels, view primitives, the World |
| Runner (same package, separate process) | Launches and supervises live Claude Code agents through the Claude Agent SDK, streams their events, receives control actions |

There is one database (DuckDB, in process) and no message queue, graph database or vector store. A recorded source
and a live one go through the same path: an adapter turns the source's records into events, and a simulated clock
cuts them into windows.

```
sources ─► adapter ─► evidence store ─► watchers ─► scale layer ─► monitors ─► analyst team ─► executive ─► cases
                                                                                     │
                                         evidence tools (the only way models read the store)
```

## The stable core

The data model (`backend/swarmscope/core/models.py`) is the part that changes least; strategies, monitors, teams and
views are all replaceable around it.

| Model | What it holds |
|---|---|
| `EvidenceEvent` | One record: time (with its uncertainty), source, actor, action, object, artifact, attributes, a locator back into the source |
| `Entity` | An actor, resource, artifact, target, goal or session, with how confident its identity is and its aliases |
| `Relation` | A typed link between entities with its status, confidence and support |
| `Artifact` | Written text by reference: fingerprint, type, size, first seen, first author, provenance; never the text itself |
| `Claim` | A statement with an epistemic status, support, counter-evidence, confidence and author |
| `Observation` | What a watcher saw in a window, with its evidence |
| `MonitorReport` | A monitor's claims, questions, risk vector and operational level for a window |
| `Question`, `Investigation` | A question someone asked and the tree of agents that answered it |
| `Incident` | A tracked case with its escalation history |
| `ExecutiveState`, `ContextLedger` | The population picture, workstreams, hypotheses, open questions, blind spots, and what the executive keeps in mind |
| `Directive`, `AttentionFocus` | How the executive or a person steers attention |
| `AttentionRecord` | Who spent how many tokens and dollars on what |
| `CapabilityProfile` | What a source can and cannot show, and how good each capability is |
| `ControlAction` | An operator's pause, message, interrupt or stop, and its result |

Rules enforced in code, not in prompts:

- An OBSERVED or DERIVED claim must cite at least one evidence reference, or it cannot be built.
- A verifier downgrades any OBSERVED or DERIVED claim from a model whose cited events do not exist, or lie after the
  current replay time.
- Written text is never stored on a model object. It sits in its own table behind the artifact's reference.

## Epistemic status

Every claim says how it is known:

| Status | Meaning |
|---|---|
| OBSERVED | Seen directly in the records (an event happened) |
| DERIVED | Computed from records by code (a count, a path, a convergence) |
| SELF_REPORTED | An agent said it about itself; to be checked against what it did |
| INFERRED | A model's interpretation |
| CONTRADICTED | The records say otherwise |
| UNKNOWN | Not settled |

The dashboard shows these as chips on every source, so a reader can tell a count from a guess and a self-report from
an observation.

## The evidence boundary

The agents being watched may write text meant to steer whoever reads it. SwarmFrame assumes they will.

- **At ingest** (`backend/swarmscope/ingest/boundary.py`) every piece of written text is fingerprinted, control
  characters are stripped, and the text goes into its own table with its provenance. Events carry only the
  reference.
- **Models reach the store only through the evidence tools** (`backend/swarmscope/llm/evidence_tools.py`, an
  in-process MCP server). Most return structure: who did what, when, on what, and counts. Text comes back only from
  `read_raw` and `search_text`, capped in size and HTML-escaped inside an `<untrusted source=… ref=…>` envelope that
  the text cannot close, with a standing notice that it is evidence, never instructions.
- **The executive and the critic cannot read raw text at all**; they see structured reports. A manipulated message can
  bias what an analyst writes about it, but it cannot reach the role that steers attention without passing through a
  structured report with cited evidence.
- **Designers never see agent text.** The dashboard and World designers work from capabilities, field names,
  categorical values and the scale layer.
- **People see text the same way**: in the evidence drawer, marked untrusted, never rendered as markup.
- **Datasets are read for structure.** `probe` prints field names, types and value shapes; values print only when
  asked for.

## Risk and operational levels

Watchers and monitors fill a risk vector (`RiskVector`: impact, scope, coordination evidence, external capability,
novelty, evidence strength, monitor integrity, uncertainty). A risk policy (`backend/swarmscope/org/risk.py`) maps it
to an operational level: WATCH, INVESTIGATE, ALERT or PAGE. Two policies ship, `research_default` (the default) and
`secops_strict`; an organization picks one with `risk_policy`. ALERT and PAGE also need two independent views and a
share of the authority budget (see cases in the reference).

## Roles and backends

Every role (a monitor's slot, the executive, an investigator, an analyst, the assistant, a designer) sits behind one
interface with interchangeable backends: `stub` (rules, no model), `claude_code` (a Claude Agent SDK session through
the local Claude Code CLI, with the evidence tools), `messages_api`, or `external` (any process speaking JSON lines).
So a researcher can swap in a Python function, an SDK agent or another program for any role, and the whole system
runs with no model at all.

## What was taken from Thimble

[Thimble](https://github.com/safety-research/thimble), a Claude Code plugin for human oversight of agent output,
shaped several choices:

- Swappable roles through a prompt, an SDK program or a JSON-lines process: kept, as the role backends above.
- Extensions as folders with a manifest, validated when added: kept, as source packs and monitor manifests.
- Every claim cites a specific reference, and "looked and found nothing" is distinct from a finding: kept, as
  evidence references and the analysts' `looked_at` entries.
- An orientation step that surveys the data and proposes views: kept, as composing and the orientation message.
- Custom views as notebook code in a sandbox: not taken. Views are a constrained spec over a fixed library, so a
  designer (person or model) cannot run code.
- Tight coupling to one interactive Claude Code session: not taken. SwarmFrame runs headless, and your own Claude
  Code session is one optional way to talk to it.

## References

- Thimble: https://github.com/safety-research/thimble
- The German message board: https://collusion.wiki (paper arXiv:2609.12748)
- Transluce agent activity: https://transluce.org/agent-activity
- The AI Village dataset: https://huggingface.co/datasets/aidigestorg/ai-village
- MessageBoardAuditBench: https://github.com/hamzah2304/messageboardauditbench
- Claude Agent SDK (Python): https://code.claude.com/docs/en/agent-sdk/python
