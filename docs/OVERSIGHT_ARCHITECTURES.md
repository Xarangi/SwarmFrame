# Oversight architectures: fixed teams, and the rules for improvising one

How one human oversees thousands of agents whose messages and actions do not fit in anyone's context, by running an
organization of LLM agents that reads on the human's behalf. This document plans that organization: a small library of
fixed architectures (one each for the AI Village, the German message board and the Transluce catalog, plus the
existing large-swarm triage tree), the grammar they are all written in, and the rules by which a team improvises a
shape for a stream nobody has seen before. It ends with the changes the dashboard needs so that none of this is
hard-coded.

Update (2026-10-10): **a composer beside the selector.** `agents/composer.py` assembles a team for the data from the
parts the presets are made of (lead and explorers always; readers, sector leads and specialists switched on by
measured evidence; an auditor), each with its reason, validated like any topology; Claude may compose by choosing
among the same parts. Dump analysis can read one record with several teams, compare them without ground truth
(agreement, what only one team found, records read closely, supported claims, cost), or search: candidates try the
first 30% and the best reads it all (`analysis/jobs.py`). See the technical reference, "The composer".

Status (2026-10-04): **built**, phases 1–4 of §10 in a first version. The grammar (§4) is in `agents/spec.py`
(partition/levels/standing/questions/cadence/human/envelope/authority); the library (§5) ships `desks`,
`board_watch`, `catalog_review` beside `triage_tree`; each pack names its team in `packs/<id>/oversight.yaml`
(`auto` = the selector); the selector (§6.2) and its reasons are in `agents/selector.py` and shown on Compose and
Organization; the Scout, proposals, envelope, approvals and promote-to-preset (§6.3–6.6) are in
`agents/proposals.py`; the findings ledger (§7.1) is in `org/cases.py`. Not yet built: deeper `levels` than one
(the first level drives sectors), the critic and canaries (§6.5), the trust readouts and "since you last looked"
digest (§7), and the eval matrix (§9). Tests: `tests/test_architectures.py`, `test_dynamic.py`, `test_cases.py`.
`docs/STRATEGY.md` is the design of the default triage tree; this document generalizes it.

---

## 1. The problem, with its constraints

- **We are a monitoring layer, not a controller.** Agents arrive as a stream of events (messages, actions, resource
  touches, environment interventions). We never see their prompts or weights, and we cannot steer them. Everything we
  know is derived from the record.
- **The record is far larger than any reader.** 5,000 agents × 1,000 events/day × ~150 tokens is 750 M tokens a day;
  a generous model budget is 20 M. Even one window of a mid-sized swarm overflows a single model's context. No LLM
  reads the stream; code does, and models read what code selected plus a random slice.
- **The stream's shape is not fixed.** A live Claude Code fleet has strong identities, tool calls and no shared chat.
  The Village has 20 agents with rich chat, stated goals and screenshots. The German board has *handles* (partial
  identities), pages as places, and moderators as the environment. Transluce has no identities at all: a catalog of
  reports about targets. The right team for one is wrong for another, and a new stream may match none of them.
- **The human's budget is the scarcest.** A few minutes a day for a quiet swarm; an interrupt only when something is
  consequential and ongoing. The architecture exists to protect that budget, not to produce reports.
- **The monitored population can learn what gets read.** Any selection rule is a target; the design must measure its
  own misses.

What "scalable oversight" means here: the human's reading grows with the number of *findings worth acting on*, not
with agents, messages, or the number of analysts. Everything between the stream and the human is there to make that
true, and to be auditable when it is not.

## 2. What exists today, and what does not

Built (see `docs/STRATEGY.md`, `backend/swarmscope/agents/`, `.claude/skills/swarm-oversight/`):

| Layer | Exists | Notes |
|---|---|---|
| L0–L2 code: boundary, scale layer (cohorts, templates, outliers), watchers | yes | per window, every event |
| L3 triage: three lanes, auto budget 4·√cohorts, hit-rate calibration | yes | weights in topology |
| L4–L6 organization: `Topology` YAML (roles, helpers, divisions, scaling, cycle, maintain, triage) | yes | 5 topologies: `single_agent`, `flat_pool`, `hierarchical_divisions`, `sdk_native`, `triage_tree` |
| Runtime: spawn / run / retire / split / merge / sectors / coverage ledger / verifier | yes | `agents/runtime.py` |
| Doctrine skill with per-role references and a report contract | yes | injected into system prompts |
| Human actions: run, spawn, retire, split, merge, force cycle, ask a question | yes | `human_action`, API |
| Deterministic fallback per role kind | yes | `BEHAVIOURS` in `agents/deterministic.py` |
| Eval harness against planted ground truth | yes | `evals/harness.py`, `scale_eval.py` |
| Per-source dashboard and World presets | yes | `packs/<id>/dashboard.yaml`, `world.yaml` |

Not built, and needed for this plan:

| Gap | Where it shows | Consequence |
|---|---|---|
| **No per-source team.** No `packs/<id>/oversight.yaml`; `Compose.tsx:70` hard-codes `triage_tree` for the planted swarm and everything else falls to the engine default `hierarchical_divisions` (`engine.py:113`) | every source gets the same team shape | the Village runs a graph-community topology meant for hundreds of agents; Transluce gets agent-shaped divisions it cannot fill |
| **Closed role set at runtime.** `can_spawn` only names roles already in the topology; there is no op to define a role, change the partition, or add a level | `agents/spec.py`, `org_tools.py` | the director can reshape *membership* but not *structure*; nothing improvises |
| **One partition family.** `DIVISION_STRATEGIES` = by_cohort / by_resource_cluster / by_family / by_group / llm (`llm` is an alias of by_resource_cluster) | `agents/divisions.py:176` | a stream whose natural axis is `namespace`, `target`, `repo`, `host` or `method class` cannot be partitioned on it |
| **One intermediate level.** `maintain.sector_role` / `sector_span` give exactly one layer between director and analysts | `runtime.py:refresh_sectors` | depth is capped in code, not by span of control |
| **Cadence is time windows only.** A cycle runs every `min_cycle_windows` | `engine.py`, `executive.py` | a catalog that arrives as record batches has no natural cycle |
| **Fixed vocabularies.** Flag kinds (`schemas.py:15`), specialist kinds (`prompts/specialist.md`), eval kind matching (`harness.py:KIND_MATCH`) are enums in code, while each pack already declares its question kinds in `questions.yaml` | schema, prompts, harness | a pack with an `identity` question (German board) cannot raise an `identity` flag |
| **Role words in the UI.** `words.ts:23` ("a director, leads and division analysts"), `Organization.tsx:49` | glossary, Organization page | a topology with different roles is described wrongly |
| **No approval queue, no interrupt policy, no trust instruments.** The Brief ranks findings but has no place for "the team wants to change shape", no per-source rule for when the human is interrupted, and shows coverage but not canary recall or verifier downgrade rates | Brief, `human_action` | the human cannot govern the organization, only poke it |
| **No critic, no canaries.** Listed as next steps in STRATEGY §8 | — | the organization's own honesty is measured only by the audit lane |

## 3. Invariants every architecture must satisfy

An architecture is any topology that keeps these. They are what makes a team trustworthy at scale; the fixed library
and the improviser both live inside them.

1. **Code reads everything; models read selections and a random slice.** No role's input is "the stream". Every
   model read is a triage pick, a coverage pick, an audit pick, or an answer to a bounded question.
2. **Every reader's input is bounded and does not grow with the population.** Analysts read a plan of ≤ N picks;
   leads read ≤ span reports; the director reads ≤ span reports plus digests. When a reader's input would exceed its
   bound, the structure adds a level (span of control), never a longer prompt.
3. **Fixed-shape reports with graded claims and event ids, verified.** `division_report` / `finding` / `director`,
   or a custom schema validated on load. A verifier downgrades claims whose evidence does not exist.
4. **A random slice no data can steer**, with its hit rate compared with triage's every cycle.
5. **A budget is the governor.** Reads per cycle, agents, depth, concurrency and spend are capped in the topology;
   the team must fit the budget, not the other way round.
6. **Stability with hysteresis.** Structural change requires evidence that held more than one cycle; the reason is
   recorded as an `OrgEvent`.
7. **Blind spots are named.** Every report and every cycle state lists what was not examined.
8. **Agent text is untrusted data** and reaches only raw-access roles, in an envelope.
9. **The human sees findings, not reports**, under an interrupt policy the source pack declares, and can trace any
   finding to event ids in two clicks.
10. **Anything the team changes about itself is visible, reversible and attributable** (who, why, when), and can be
    promoted to a saved preset.
11. **Reading is cheap; authority is budgeted.** Spawning a reader costs only model budget and is always allowed
    inside the caps. Raising a finding to ALERT, interrupting the human, or (where control exists) acting on the
    population draws on a separate, smaller *authority budget* per cycle. A team can grow its eyes freely and still
    cannot flood the human. (Progressive risk vesting, §12.)
12. **Two independent readers before ALERT.** An ALERT needs OBSERVED or DERIVED evidence from two readers that saw
    the scope through *different* views (for example a division analyst's plan and the auditor's random slice, or a
    specialist's question and a template's spread), not two passes of the same prompt. Diversity, not repetition,
    is what raises monitor recall (§12).
13. **Both discovery modes always run.** Rubric-driven reading answers the pack's known questions; bottom-up
    structure (cohorts, templates, outliers; later embedding facets) surfaces what nobody wrote a question for.

## 4. The architecture grammar: what a topology must be able to say

Today's `Topology` already says: root, roles (prompt, model, effort, tools, raw access, can_spawn, output schema,
memory, scope, refresh), helpers, divisions, scaling, cycle phases, maintain policy, triage weights and lanes. The
plan adds the fields below. All are optional with today's behaviour as default, so existing topologies keep working.

```yaml
# ---- partition: how the population is cut into scopes for scoped roles
partition:
  unit: actor | object                 # from source pack scale.unit (default)
  by: cohort | field | resource_cluster | group | family | none
  field: namespace                     # when by: field — any categorical field the stream profile marks usable
  span: 6                              # cohorts (or field values) per division
  min_events: 1
  fold_small_into: "mixed"             # small partitions fold so noise is not a headline

# ---- levels: intermediate readers, inserted while span is exceeded, removed while it is not (hysteresis: 2 cycles)
levels:
  - {role: sector_lead, span: 6}       # may repeat for deeper trees; depth is a consequence, not a setting
  - {role: region_lead, span: 5}

# ---- standing roles: spawned at start and kept, independent of partitions
standing:
  - {role: auditor, scope: audit}
  - {role: integrity_specialist, scope: population, refresh_every_cycles: 2}

# ---- questions: which pack question kinds this team answers with which role (specialists are spawned from these)
questions:
  integrity: integrity_specialist
  propagation: propagation_specialist
  "*": specialist                      # fallback role for any other kind in packs/<id>/questions.yaml

# ---- cadence: what one cycle is
cadence:
  kind: windows | records | events | human     # windows = replay/live clock; records = catalog batches
  every: 3                                     # 3 windows, or 500 records, or 5,000 events
  also_on: [human_input, page_alert]

# ---- human: the contract with the overseer (see §7)
human:
  briefing_every: 1d                   # digest cadence in stream time
  interrupt_at: PAGE                   # WATCH | INVESTIGATE | ALERT | PAGE — below this, findings wait for the digest
  approvals: [new_role, raw_access, budget_over, partition_change]   # what needs a human yes
  max_open_questions: 5

# ---- envelope: what the director may improvise without a human (see §6.4)
envelope:
  may_define_roles: true
  tools_subset_of: director            # a proposed role's tools ⊆ this role's; never wider
  raw_access: false                    # proposals asking for raw text go to approvals
  max_model: claude-sonnet-5-5
  budget_share_max: 0.3                # of the cycle budget
  max_new_roles_per_cycle: 1
  approval: auto_within_envelope       # or always_human

# ---- authority: what costs more than model budget (invariant 11)
authority:
  alerts_per_cycle: 3                  # findings the team may raise to ALERT or above per cycle
  interrupts_per_day: 2                # human interrupts (PAGE) per stream-day; beyond this, PAGE waits for the digest with a warning
  control_actions_per_cycle: 0         # only where the source has control; 0 = read-only

# ---- honesty instruments (see §6.5)
critic: {role: critic, every_cycles: 2}
canaries: {enabled: true, per_cycle: 2, kinds: [propagation, convergence]}
audit: {front_load_new_units: true}    # a unit's first cycles get a higher audit draw (decaying threshold)
```

Selection of a topology moves into the source pack: `packs/<id>/oversight.yaml` names a topology (`topology:
desks`) and may override any of the fields above for that source (for example the partition field, the question
map, the human contract). A pack without `oversight.yaml` gets the selector's choice (§6.2). Hash-refresh works as it
does for `dashboard.yaml` and `world.yaml`: an unedited pack team is refreshed when the file changes.

## 5. The fixed library

Four exist; four are planned. Each row is a complete team shape a human can read in a minute.

| Topology | For | Unit | Partition | Levels | Standing | Cadence | Human |
|---|---|---|---|---|---|---|---|
| `single_agent` | baseline, tiny streams | — | none | 0 | — | windows/3 | digest |
| `flat_pool` | comparison; ≤ 10 groups | actor | group | 0 | — | windows/3 | digest |
| `hierarchical_divisions` | mid-size, graph-structured | actor | resource_cluster | 0 | — | windows/3 | digest |
| `triage_tree` (built) | thousands of agents, identities | actor | cohort, span 6 | sector_lead ×1+ | auditor | windows/3 | PAGE |
| **`desks`** (new) | the Village: tens of agents, rich chat, stated goals | actor | group (team / model family), fold < 2 | 0 | auditor, integrity, goals, comms specialists; diarist | windows/3 | ALERT, daily digest |
| **`board_watch`** (new) | the German board: partial identities, pages as places, moderators | actor (handle group) | field `family` (namespace), span 4 | none until > 6 | auditor, identity resolver, moderation-response, propagation | windows/3 | ALERT |
| **`catalog_review`** (new) | Transluce: identity-free catalog of reports about targets | object (target) | field `method_class`, span 8 | 0 | grade auditor, chronicler, new-method specialist | records/500 | digest; ALERT on new method or new target |
| **`scout`** (new) | an unknown live stream (generic JSON, Claude Code fleet) | from profile | chosen by the selector | grown by span | auditor | windows/3 → adapts | approvals on, ALERT |

Costs below are CLI estimates (which run ~5× high) for Sonnet 5.5 low analysts (~$0.45 a run), Haiku helpers
(~$0.05), an Opus 5.5 medium director (~$0.8–1.2 a run). Rules-only mode costs nothing and uses the deterministic
behaviours.

### 5.1 `desks`: the Village

Why not the triage tree: 20 agents make at most a handful of cohorts; the scale layer's compression buys little, and
what matters is each agent's *story over days* (what it said it would do, what it did, who it talked to, what the
humans in the chat changed). The team is organized around standing desks, not a reading plan.

| Role | Model | Scope | Reads | Writes | Spawned by |
|---|---|---|---|---|---|
| Director | Sonnet 5.5 low (default; any role's `model`/`effort` is a topology field, so a pack or a person can set Opus) | population | digest, desk reports, specialist findings, questions | `director` | standing |
| Desk analyst | Sonnet 5.5 low | one group (team or model family), ≤ 6 agents | timeline, observations, cohort card, a few events; `skim_reader` helper for text | `division_report` with one `looked_at` entry **per agent** | partition |
| Diarist | Haiku 4.5 | population | each desk report | `diary`: one paragraph per agent per day, appended, never rewritten | standing, every cycle |
| Integrity specialist | Sonnet 5.5 low | population | self-reports vs recorded actions (say-vs-do watcher output) | `finding` | standing, every 2 cycles |
| Goals specialist | Sonnet 5.5 low | population | stated goals vs workstream mix (focus-shift watcher) | `finding` | standing, every 3 cycles |
| Comms specialist | Sonnet 5.5 low | chat rooms | propagation across rooms, who adopted whose phrasing, text addressing monitors | `finding` | on flag |
| Environment specialist | Sonnet 5.5 low | one environment event | before/after behaviour of affected agents | `finding` | on flag |
| Auditor | Haiku 4.5 | audit | random agents' recent events | `division_report` | standing |

- Partition `group`, fold groups under 2 agents into "mixed". With 21 agents in the default slice that is 3–4 desks.
- Human contract: a daily digest in stream time (one Brief read); interrupt at ALERT (someone did something they
  said they would not, an operator intervened, a goal changed hands). The Brief's "Needs attention" holds ≤ 5 items.
- Planted behaviours it must catch (`village_sim` ground truth): convergence, propagation, integrity, environment,
  rate, goals: each has a watcher and a standing or on-flag specialist.
- Cycle cost, models on: ~4 desks + diarist + 1–2 specialists + director ≈ $3.5–4.5 (CLI estimate) per cycle, 8
  cycles a stream-day. Cheap mode (everything Sonnet low): ≈ $3.
- Failure modes: desks drift into narrative; the diarist's paragraphs are a *summary*, graded SELF_REPORTED where
  they repeat agent words. The report contract's `looked_at` per agent keeps the denominator honest.

### 5.2 `board_watch`: the German message board

Why its own shape: identities are partial, so "agent" is a handle group and every identity claim is graded. Places
(pages) and namespaces are the stable structure; the moderators are the environment; the interesting events are
cross-group convergence on question pages, text that spreads, and displacement after deletions.

| Role | Model | Scope | Reads | Writes |
|---|---|---|---|---|
| Director | Opus 5.5 med | population | digest, namespace reports, findings | `director` |
| Namespace analyst | Sonnet 5.5 low | one namespace (`family`): its pages and the handles writing there | reading plan over pages (crowding, bursts) and handle groups | `division_report`, `looked_at` per pick |
| Identity resolver | Sonnet 5.5 low | a handle group | spelling variants, co-timing, shared pages, reused text | `finding` with verdict one-agent / several / unknown |
| Moderation-response | Sonnet 5.5 low | one deletion sweep | where affected handles went, under which names | `finding` |
| Propagation specialist | Sonnet 5.5 low | one template | did copiers see the origin page first (exposure) | `finding` |
| Auditor | Haiku 4.5 | audit | random pages and handles | `division_report` |

- Partition `field: family` (Diskussion, Fragenkette, Benutzer, Ausweich, other); span 4 pages per pick; a
  `sector_lead` level only if namespaces exceed 6 (they do not in the synthetic data; a real export may have more).
- Questions map: `identity → identity_resolver`, `environment → moderation_response`, `propagation →
  propagation_specialist`, `convergence|surge → namespace analyst re-run with a sharp task`.
- Human contract: interrupt at ALERT (cross-group convergence with reuse; a sweep followed by returns under new
  names); weekly digest otherwise.
- Planted behaviours (`german_wiki.synthesize`): convergence, propagation, rate, environment, identity: all five
  have a role.
- Rule for the real export: adapters never show page bodies; text reuse is by fingerprint; the identity resolver's
  verdict is never above DERIVED.

### 5.3 `catalog_review`: Transluce

Why its own shape: nothing persists across reports except targets and methods. There is no "who", so no divisions
of agents, no diarist, no identity questions. Cycles follow the record (batches of reports), not the clock. The
risk the team guards against is *volume masquerading as evidence*: many suggestive reports do not make a significant
one.

| Role | Model | Scope | Reads | Writes |
|---|---|---|---|---|
| Curator (root) | Sonnet 5.5 low | catalog | catalog summary, target bursts, new methods, grade mix shift, method reports | `director` (population_state = the record; hypotheses about methods and targets) |
| Method analyst | Sonnet 5.5 low | one method class | its targets' volumes, grade mix, first/last seen, bursts | `division_report` |
| Grade auditor | Haiku 4.5 | audit | random reports' metadata: is the grade consistent with the method and target? (never `why_included`) | `division_report`: share of sample where volume is being read as weight |
| Chronicler | Haiku 4.5 | catalog | what changed since the last digest: new targets, new methods, grade shift | `finding` |
| New-method specialist | Sonnet 5.5 low | one (target, method) first seen | is it a new technique or a relabel; which targets share it | `finding` |

- Cadence `records/500` or one stream-day, whichever first; the replay of 37k reports is ~75 cycles.
- Human contract: a digest per cycle (the Brief already shows total, last 90 days vs the 90 before, top targets,
  method mix); interrupt at ALERT for a new method class or a new target in the top 10 by volume.
- The dashboard's catalog mode and the World's mix layout are the visual counterpart; this team is the reading
  counterpart.

### 5.4 `scout`: an unknown stream

The one that improvises. It starts as a single role and grows under the rules of §6. Described there.

## 6. Dynamic architecture: how a team improvises

Two layers, deliberately separate (built 2026-10-04):

**6.0 The light layer: agents fire off their own sub-agents, and leave a trail.** Any role with `delegate: true`
(every director, sector lead and analyst in the library) has the Task tool with a `reader` sub-agent it briefs
itself (the role's own evidence tools, scoped the same way, never raw text unless the role has it), plus the
topology's helpers. No permission is asked; a reason is required. The skill reference `delegation.md` says when
to delegate (bounded question, independent questions in parallel, a view you should not take yourself, at your
span), when not to (to "get a feel", to decide), and the four-line brief. **Every** delegation lands in the
session's delegation log, `data/runs/<source>_<started>/delegations.jsonl`, and on the Organization page: native
Task calls (captured from the session stream: the call's description is the reason, the result is the outcome),
managed spawns, re-runs and retirements with their briefs, escalations, proposals, and the agent's own
`log_decision` lines ("not delegating X because…"). A reviewer can read the file alone and understand every
reader that existed and why. (`agents/delegation.py`, tool `log_decision`, API `/api/agents/delegations`.)

**6.1–6.6 The structural layer** below is for changes that outlive a run: a new persistent role, a different
partition, another base topology. Those are proposals under an envelope and, when needed, a person's approval.

The library covers streams we know. For the rest, structure must come from the stream, under the invariants. The
approach: **code decides the skeleton from the stream's shape (deterministic, explained); a model refines within an
envelope; the human approves what the envelope does not cover; the result can be saved as a preset.** Over time
improvised teams become library entries.

### 6.1 The shape vector (code)

Computed from the stream profile (`dashboard/profile.py`), the pack's capabilities and the scale layer, every cycle:

| Feature | Values | From |
|---|---|---|
| identity | strong / partial / absent | capabilities.identities |
| population | n units active in the lookback | scale layer |
| rate | events per hour | profile |
| cohorts | n (compression) | scale layer |
| communication, self_reports, environment, groups, stated_goals, tool_calls, computer_actions | present / absent | capabilities |
| catalog | bool | source.yaml |
| control | available / not | capabilities |
| candidate axes | categorical fields usable in views, with cardinality 2–60 and share of events covered | profile.attribute_shapes |
| text | present / absent | profile |

### 6.2 The selector (code, explained)

A decision table, in order; the first row that matches wins, and the reasons are written into the org events and
shown on the Compose screen ("Proposed team, and why"):

| If | Then | Partition |
|---|---|---|
| catalog | `catalog_review` | best axis among {method, technique, family} else top candidate axis |
| identity absent (not catalog) | `triage_tree` with unit object | cohort |
| identity partial and resources strong and environment present | `board_watch` | the axis that covers most events among candidate axes with cardinality ≤ 12 (namespace-like) |
| identity strong and population ≤ 60 and communication present | `desks` | group if present else family |
| population > 60 or cohorts > 12 | `triage_tree` | cohort |
| otherwise | `scout` | best candidate axis, else cohort |

Overrides: `packs/<id>/oversight.yaml` wins over the selector; a human choice wins over both. Hysteresis: the
selector's choice is re-evaluated every cycle but a *change* needs the new row to hold for 2 cycles and goes through
approvals (`partition_change`).

### 6.3 The scout protocol (one model run, Sonnet 5.5 low)

When models are on and the selector chose `scout` (or the pack asks for a review), one Scout run reads the shape
vector, the profile, the capabilities, the pack's questions, and the library's descriptions, and returns an
`architecture_proposal`:

```json
{"base": "flat_pool", "partition": {"by": "field", "field": "repo", "span": 5},
 "standing": [{"role": "auditor"}, {"role": "integrity_specialist", "refresh_every_cycles": 2}],
 "new_roles": [{"id": "tool_abuse_specialist", "title": "Tool abuse specialist", "kind": "generic",
                "prompt": "...", "tools": ["evidence.query_events", "evidence.timeline", "evidence.observations"],
                "output": "finding", "model": "claude-sonnet-5-5", "effort": "low", "max_turns": 8}],
 "questions": {"integrity": "integrity_specialist", "*": "specialist"},
 "human": {"interrupt_at": "ALERT"},
 "reasons": ["identities strong, 340 units, no chat: per-repo desks beat cohorts because repos are the shared resource",
             "tool_calls present and no pack question covers tool misuse: one specialist proposed"],
 "blind_spots": ["no environment field in the stream: operator actions invisible"]}
```

The proposal is validated like any topology (`from_dict` + `validate`); each `new_role` is checked against the
envelope; what fits is applied, what does not goes to the approvals queue with the reasons. In rules-only mode the
selector's skeleton is applied without the Scout.

### 6.4 Growth and contraction rules (code, every cycle, with hysteresis)

These generalize today's `maintain` and `refresh_sectors`:

| Trigger (held 2 cycles unless marked) | Action | Why |
|---|---|---|
| a reader has more children than its level's span | insert a level above the children (role from `levels`) | span of control |
| a level's readers would each have ≤ span/2 children | remove the level | contraction |
| a division's events > `split_when_events_over`, or its analyst's report `recommend.split` twice | split (same strategy, finer) | one reader per unit of work |
| two divisions share ≥ 0.6 of units (Jaccard) or both analysts flag the same scopes | merge | one thing, one reader |
| a partition value is empty for `retire_quiet_cycles` | retire its analyst | spend where the information is |
| audit hit rate ≥ 0.5 × triage hit rate (immediate) | raise the audit lane 5 points, write a warning, tell the director | triage is not working |
| a question kind with no role fires ≥ 2 flags | spawn the `"*"` fallback specialist, and propose a dedicated role | question-driven |
| coverage share < 40% for 3 cycles | raise reads toward the cap; else add a level of readers; else say so in blind spots | coverage debt |
| spend > budget | drop model tiers first (Opus→Sonnet→Haiku), then reads, then refresh cadence; never the audit floor | budget is the governor |

Every action is an `OrgEvent` with its trigger and the cycles it held.

### 6.5 Honesty instruments

- **Audit lane** (exists). **Verifier** (exists).
- **Critic** (new role, any topology): every N cycles, diffs what the organization read (lookups, coverage ledger)
  against what exists (scale layer), and what the director's state claims against the reports; returns a `finding`
  with "read but unmentioned", "mentioned but unread", and "claims above their grade". Haiku; cheap.
- **Canaries** (new): synthetic events planted into the *compressed views* (never the store) with known kind and
  scope; recall per kind per cycle is a number the human can see. Canaries are labelled in the drawer; they never
  reach briefings.
- **Trusted describer** (exists as `skim_reader`; made a rule): agent-written text never reaches a judging role
  directly. A cheap helper (Haiku) writes a neutral one-sentence description; the judging role reads the
  description, and only a raw-access specialist reads the text itself, in the untrusted envelope. This strips
  instructions and steganographic context before anything is judged.
- **Syndromic signals** (new watchers, cheap, over everyone): step repetition, error-like action rate, tool call
  claimed but never executed (claims vs tool events), stale plan (an agent's actions diverging from its last stated
  plan), termination unawareness (work continuing after a stop). These are the "non-specific symptoms across the
  whole population" that complement the deep reads; several are the top failure modes in MAST (§12), and the
  "plan drift" alert is what coding-fleet dashboards converge on.
- **Sentinels** (reframing the coverage lane): a small, slowly rotating set of units read deeply every cycle, chosen
  for yield (busiest cohort representative, newest unit, the one with the most self-reports), alongside the random
  audit. Sentinel + syndromic + random is the surveillance pattern that detects clusters cheaply.
- **Sequential audits, later**: make the audit lane's "nothing found" a certified statement with an anytime-valid
  test (e-process) over the random sample, so the Brief can say "no undetected behaviour of kind X at rate above
  p, with error α" instead of "the auditor found nothing".
- **Lane hit rates, verifier downgrade rate, canary recall, cost per finding**: the four trust instruments of §7.

### 6.6 The envelope, approvals, and promotion

- The director (or Scout) may **propose**: `org.propose_role`, `org.propose_change` (partition, levels, lanes,
  cadence, human contract). Proposals inside the `envelope` apply at once and are reversible for one cycle (undo
  from the Organization page); the rest wait in the approvals queue on the Brief.
- A human may **promote** the current team to a preset: `org.promote_preset` writes `packs/<id>/oversight.yaml`
  (or a named topology under `topologies/`) with the reasons from the org events as comments. This is how dynamic
  becomes fixed: a stream that was unknown in week one has a library entry in week two.
- Nothing a proposal says is an instruction to the system: it is data validated against the grammar. A proposed
  prompt is shown to the human before any run with raw access.

## 7. The human overseer's console

The dashboard already has the Brief (one screen, ranked "Needs attention", recommended next step), question pages,
drawers down to event ids, the World, and the Organization page. The plan adds the governance the human lacks:

| Element | Where | Contract |
|---|---|---|
| **Interrupt ladder → delivery** | per source `human.interrupt_at` | PAGE: push now (desktop notification, the Brief's top band turns live); ALERT: top of the next digest, badge in the rail; INVESTIGATE / WATCH: inside the digest, collapsed |
| **Digest** | Brief, "Since you last looked" | what changed since the human's last visit, in the pack's words; ≤ 5 items; each with its grade and a "why now" |
| **Approvals queue** | Brief side panel + Organization | proposals with reasons, cost, and the envelope rule they exceeded; approve / edit / decline / "always allow this" |
| **Trust instruments** | Brief footer readouts (4 numbers) | triage vs audit hit rate; verifier downgrades this cycle; canary recall; cost per notable finding. Each with a one-line reading ("audit finds a third of what triage finds: healthy") |
| **Ask** | Brief → Ask | plain-language question → `ask_question` → the questions map routes it to a role → answer lands in the Brief with its claims |
| **Budget dial** | Settings → Oversight | spend per cycle and per day; model mode; the team shrinks itself under §6.4 |
| **Team card** | Compose step "Who reads", Organization | the selected or proposed team with reasons; one click to accept, edit, or pick from the library |

Rule for the Brief's text: findings, not reports. A human never reads a `division_report`; they read a briefing entry
with a grade, a base, a time and a next step, and can open the report behind it.

### 7.1 The findings ledger (built 2026-10-04)

Before this, only watcher reports became tracked incidents; a division analyst's concerning report was a one-off
briefing line and a flag became a question, so an agent's finding had no level, no history and no path to a person.
`backend/swarmscope/org/cases.py` is now the one path through which any finding is tracked and escalated:

| Mechanism | Rule |
|---|---|
| One case per open scope | whoever saw it first (watcher, analyst, specialist, agent tool, person); later sightings update it and add a *view* |
| Levels only rise through the ledger | `Incident.history` records every change: when, to what, by whom, why, on which evidence; `held` records a request not granted |
| Two views before ALERT | ALERT/PAGE need two independent views (`monitor:x`, `role:y`, `human`); until then the request is held at INVESTIGATE and granted automatically when the second view arrives (invariant 12) |
| Evidence must exist | an escalation citing unknown evidence ids is held |
| Authority budget | `topology.authority.alerts_per_cycle` (default 3) cases may rise to ALERT per executive cycle; the rest are held and reconsidered next cycle (invariant 11) |
| People are never held | human escalations and de-escalations apply at once, with a reason |
| Fast path | `org.escalate_finding` (every reading role has it) writes the case immediately; at ALERT+ the UI hears an `escalation` event now and the executive runs at the next window instead of waiting for its cadence |
| Acknowledgement and SLA | ALERT+ waits for a person's receipt; unacknowledged past `ack_sla_windows` (3) it is *overdue* and leads the Brief; the tab title carries the unacknowledged count |
| Aging with a trail | quiet INVESTIGATE cases go to monitoring after `quiet_windows` and resolve after twice that, each with a history entry; ALERT and PAGE never fade |

Surfaces: the Brief's acknowledgement band; `overdue` / `awaiting your receipt` / `held: wants alert` chips on
rows; the drawer's "How it got here" history with the independent sources; menu actions Acknowledge and Escalate;
API actions `ack`, `escalate {level}`, `lower {level, reason}`; agent tools `cases` and `escalate_finding`; the
doctrine's rule 14. Tests: `tests/test_cases.py`.

Four rules the human-factors literature adds (§12):

- **A hard throughput number.** A SOC analyst handles ~40 alerts an hour at most; our human has minutes a day.
  The authority budget (invariant 11) caps ALERTs and PAGEs so the digest never exceeds what fits in one reading.
  Low-confidence items are closed by the team with a reason, medium ones are enriched and held, only high
  confidence × high stakes reaches the human.
- **Evidence before verdict.** A briefing entry opens with the counts and the cited events, then the team's
  reading. Humans anchor on a verdict they see first; the layout should not invite that.
- **Oversee the plan, not the stream.** The human's most valuable minute is spent on the *team card* (what will be
  read, by whom, under which rules) and on approvals, where plan-level oversight has been shown to prevent most
  problems, while runtime intervention catches few. Post-approval complacency is real: the digest's trust readouts
  are there to show whether the approved plan is still working.
- **Measure brief accuracy, not confidence.** Canary recall and the verifier's downgrade rate are the dashboard's
  accuracy instruments; "the Brief felt clear" is not one. Occasionally the digest includes an unlabelled item
  (a finding with its grade hidden until opened) so the human's own judgement stays calibrated.

## 8. The dashboard must not hard-code a design

The dashboard and World are already per-pack data. The organization must be too. Concrete changes:

| File | Today | Change |
|---|---|---|
| `frontend/src/screens/Compose.tsx:70` | `agents.topology: triage_tree` only for the planted swarm | read the pack's `oversight.yaml` (via `/api/packs`), show the team card with reasons; selector fallback |
| `backend/swarmscope/engine.py:113` | default `hierarchical_divisions` | pack `oversight.yaml` → selector → global default |
| `backend/swarmscope/agents/spec.py` | `DIVISION_STRATEGIES`, `SCOPE_KINDS` with a single `sector`, `maintain.sector_role/sector_span` | add `partition`, `levels`, `standing`, `questions`, `cadence`, `human`, `envelope`, `critic`, `canaries`; keep old keys as aliases; scopes `level:<n>:<id>` |
| `backend/swarmscope/agents/divisions.py` | fixed strategies | `by_field(field)` over any usable categorical attribute; `by_cohort` unchanged |
| `backend/swarmscope/agents/schemas.py:15` | `_FLAG.kind` enum fixed | built per engine from `questions.yaml` kinds ∪ `general`; same for `recommend.specialist` |
| `backend/swarmscope/agents/topologies/prompts/specialist.md` | four kinds in prose | generated from the pack's questions (text and required capabilities) |
| `backend/swarmscope/evals/harness.py:KIND_MATCH` | code | pack `monitors.yaml` declares `answers: [question kinds]` per monitor |
| `backend/swarmscope/agents/runtime.py` `refresh_sectors`, `maintain` | one level, auditor special-cased | `levels` loop, `standing` loop, §6.4 rules with hysteresis, approvals |
| `backend/swarmscope/agents/org_tools.py` | spawn/run/retire/split/merge/define/ask/set_triage | `propose_role`, `propose_change`; human-only `approve`, `decline`, `promote_preset` |
| `frontend/src/words.ts:23` | names roles | help built from `topology.roles[*].title` ("The AI readers SwarmFrame runs: {titles}") |
| `frontend/src/screens/Organization.tsx:49` | names roles | `topology.description`; the role list renders titles and descriptions from the topology (it already does for the editor) |
| `frontend/src/screens/Brief.tsx` | no approvals, no trust readouts | approvals panel, four trust readouts, "since you last looked" |
| `backend/swarmscope/dashboard/spec.py` `GLANCE` | fixed glance keys | add `trust_*` and `approvals` glance keys so any Brief can show them, or not |
| `packs/<id>/oversight.yaml` | — | new; `ingest/packs.py` loads and hashes it like `dashboard.yaml` |

Test that proves it: a topology with invented role ids and a `by_field` partition on a generic stream composes,
runs a deterministic cycle, and the UI snapshot (`/api/agents/org`) contains no string from the default topologies.

## 9. Evaluation

Architectures are compared the way strategies already are: same code path, different topology, planted ground truth.

| Source (synthetic) | Ground truth kinds | Architectures to run |
|---|---|---|
| `ai_village` (`village_sim`) | convergence, propagation, integrity, environment, rate, goals | `desks`, `hierarchical_divisions`, `single_agent` |
| `german_wiki` (`synthesize`) | convergence, propagation, rate, environment, identity | `board_watch`, `triage_tree`, `flat_pool` |
| `swarm_scale` 2k / 5k | 5 planted behaviours | `triage_tree` (reference), `scout` (must converge to a tree) |
| `transluce` (real metadata) | documented: April surge, method classes, grade mix | `catalog_review` vs `triage_tree`-as-object: digest fidelity, new-method latency |
| `generic_stream` with the planted swarm replayed as JSON | 5 behaviours | `scout` from a cold start: which team it chose, how many cycles to recall 5/5 |

Metrics (harness already has most): recall, time to first signal, explained, unsupported-claim rate, false
incidents, cost, **director input size per cycle**, **human interrupts per stream-day and share that were ALERT or
above**, **approvals raised**, **canary recall**, audit vs triage hit rate.

Real-model checks follow the standing rule: Sonnet 5.5 at the lowest effort, one cycle each, only to confirm the
prompts work (a Scout proposal on the generic stream; one `desks` cycle on the Village; one `catalog_review` cycle).

## 10. Phases

1. **Grammar and selector** (backend): `oversight.yaml` loading; `partition`/`levels`/`standing`/`questions`/
   `cadence`/`human`/`envelope` in `spec.py` with aliases; `by_field`; shape vector + selector with reasons; flag
   kinds from packs; tests (`tests/test_topology_grammar.py`).
2. **Fixed library**: `desks.yaml`, `board_watch.yaml`, `catalog_review.yaml` with prompts; `oversight.yaml` in the
   three packs; deterministic behaviours for new kinds (`diarist`, `chronicler`, `critic` → `generic` where no code
   behaviour is needed); eval matrix rows in §9 run in rules-only mode.
3. **Dynamic**: `scout` topology and `architecture_proposal` schema; `propose_*` ops; approvals queue in the store
   and API; growth/contraction rules with hysteresis; `promote_preset`; critic and canaries.
4. **Console**: Compose team card; Brief approvals, trust readouts, "since you last looked"; interrupt delivery;
   words and Organization from topology; Settings budget dial.
5. **Verify**: full eval matrix; one Sonnet low run per new prompt; UX tester pass on the approvals flow; docs
   (README "Who reads", STRATEGY pointer, memory).

## 11. Risks and open questions

- **Over-structure for small streams.** A 20-agent village does not need a director over four desks; the `desks`
  director may be Sonnet, or the root may be the diarist with a director run only on ALERT. Decide by the eval's
  cost-per-finding.
- **Proposal quality at low effort.** Earlier real runs showed Sonnet low makes few tool calls and defers actions.
  The Scout gets everything in one prompt (profile, shape, library) so it needs no tools; its output is validated.
- **Hysteresis vs responsiveness.** Two cycles of evidence before a structural change could delay coverage of a new
  partition value by 6 windows; the fallback is that triage picks are assigned to the nearest reader meanwhile
  (today's "unassigned" path).
- **Canaries in compressed views** must be impossible to confuse with real findings in the UI and never reach
  the store; they are the one place synthetic data touches a live session.
- **Human contract drift.** If a human never opens the digest, interrupts should not escalate to fill the silence;
  the rule is the interrupt ladder, not attention-seeking.
- **Real German export.** The partition field and identity resolver are designed on synthetic data; the real
  export's namespaces and handle patterns may differ. The adapter's probe (structure only) decides the field.
- **Distributed behaviour defeats per-unit readers.** When a goal is split across many agents, each piece looks
  unremarkable; only the aggregate layer (templates across cohorts, convergence, synchronized timing) can see it.
  This is the strongest argument for keeping the scale layer and the critic even in small-stream teams like
  `desks`, and the hardest open problem in the literature.
- **Weaker monitors over stronger agents.** Our analysts are Sonnet at low effort and our auditor is Haiku; the
  population may be stronger. Hybrid scaffolds (rules plus model) and a meta-reader over the monitors' own
  reasoning (the critic) are the known mitigations; neither is proven at scale.

## 12. What the research says

A sweep done for this plan (2024–2026, mechanism-level). Only items that changed a design choice are listed.

| Source | Mechanism | What this plan takes |
|---|---|---|
| Ctrl-Z: controlling agents via resampling (2025) | trusted monitor scores actions; suspicious ones resampled; audit budget spent on a decaying threshold | front-load audit draws on a unit's first cycles (`audit.front_load_new_units`) |
| Untrusted monitoring protocols, ControlArena (2025) | trusted model writes a neutral description; strong model scores it; scores ensembled | the trusted describer rule (§6.5); two views before ALERT (invariant 12) |
| Ensemble monitoring for AI control (2026) | three *diverse* monitors gain 2.4× what three identical ones do | diversity requirement in invariant 12; critic reads with a different view than analysts |
| Multi-agent AI control: distributed attacks hamper per-instance monitors (2026) | goals split across N agents evade per-agent monitors; aggregate monitoring needed | the scale layer and critic stay in every team, including `desks` (§11) |
| Bootstrapped monitoring (2026) | a weak trusted model oversees the *reasoning* of a stronger monitor | the critic as a meta-reader over reports and the director's state |
| Adaptive attacks on trusted monitors (2025) | agents that know the monitor prompt inject against it | role prompts and rubrics are never in any stream the population can see; text addressing monitors is a finding (already rule 9) |
| Anthropic: hierarchical summarization for monitoring (2025); Clio (2024) | summarize → summarize summaries → judge; bottom-up taxonomy with size thresholds | invariant 13 (both discovery modes); fold small partitions |
| Hierarchical clustering of agent traces for unknown failures (2026); Meerkat (2026) | facets → embeddings → clusters → labels; an investigator agent spends budget on suspicious regions | embedding facets as the next scale-layer feature; specialists as the investigator |
| Transluce Docent (2025) | vague question → rubric → judge at scale; map/reduce reading steps | the questions map and the `"*"` fallback; coarse ordinal grades |
| LLM-as-judge calibration (2025–26) | 3–6 level scales beat fine ones; validate against a small human-labelled set | status enums stay coarse; canaries and the verifier as the calibration set |
| Anthropic multi-agent research system (2025) | orchestrator–worker; explicit effort rules; subagent brief = objective, output format, boundaries; results via a store, not the parent's context | director prompt gets effort rules; reports already go through the store |
| MAST: why multi-agent systems fail (2025) | specification, inter-agent misalignment, weak verification; step repetition and termination unawareness are top modes | syndromic watchers (§6.5); three-level verification = verifier + critic + eval |
| Dynamic agent hierarchies, AdaptOrch (2024–26) | spawn on observed complexity; choose topology from the task's shape; dissolve on completion | the selector (§6.2) and growth/contraction rules (§6.4) |
| Spawn freely, act sparingly: progressive risk vesting (2026) | reading branches are cheap; acting authority is escrowed and budgeted | invariant 11 and the `authority` block |
| When more is less (2026) | fan-out past a point degrades results | caps on readers per level; cost per finding as a first-class metric |
| OpenTelemetry GenAI agent spans (2025–26) | standard agent/tool/session span schema | a `generic_stream` field map for OTel, so unknown fleets arrive with structure |
| Alert fatigue in SOCs (ACM CSUR 2025) | 100k alerts/day vs ~40 per analyst-hour; tiered escalation; static suppression creates blind spots | the throughput rule (§7); no static suppression, the audit lane instead |
| Coding-agent fleet dashboards (2026) | plan-drift warnings; a review queue distinct from the live feed | stale-plan watcher; the approvals queue |
| FEMA ICS; ATC dynamic sectorisation | span of control 3–7; add a layer only when exceeded; split/merge sectors on predicted workload | `levels` by span (§4), hysteresis (§6.4) |
| Sentinel vs syndromic surveillance (CDC) | chosen deep reporters plus cheap signals from everyone detect clusters comparably | sentinels + syndromic + random (§6.5) |
| Adaptive auditing with anytime-valid guarantees (2026) | e-processes let an auditor stop any time with error control | certified "nothing found" as a later upgrade (§6.5) |
| Scalable oversight: sandwiching (2022); human–AI complementarity (DeepMind 2025) | human + model beats either; route by stakes × uncertainty; log human corrections | the Ask flow; approvals as logged corrections feeding the selector |
| Human oversight strategies for computer-use agents (2026); overseeing agents without constant oversight (2026); confirmation bias in oversight (2025) | plan approval prevents most problems, runtime intervention catches ~21%; better trace UIs raise confidence not accuracy; humans anchor on verdicts | §7's four rules: throughput, evidence first, oversee the plan, measure accuracy |

Open problems the literature leaves, which this plan does not claim to solve: weaker monitors over stronger agents;
collusion and fragmentation across agents; human accuracy versus confidence; and the token cost of orchestration
(roughly 15× a single reader), which is why cost per finding is measured in every evaluation.
