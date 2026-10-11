# Analyst teams

How SwarmFrame organizes the Claude agents that read a swarm on a person's behalf: the grammar a team is written in,
the runtime that runs it, the preset teams, how a source gets its team, and the composer that assembles one from
parts. The default way of reading thousands of agents (cohorts, templates, triage lanes) is in
[reading-at-scale.md](reading-at-scale.md); this note is about the organization that does the reading.

Code: `backend/swarmscope/agents/` (spec, runtime, org tools, delegation, selector, composer, proposals),
`agents/topologies/*.yaml` (the presets) and `packs/<id>/oversight.yaml` (each source's suggestion). Tests:
`tests/test_architectures.py`, `tests/test_dynamic.py`, `tests/test_cases.py`.

## The problem

SwarmFrame monitors and does not control: it never sees the agents' prompts or weights, only the record. The record
is far larger than any reader (see [reading-at-scale.md](reading-at-scale.md), "The arithmetic"), so code reads the
stream and models read what code selected, plus a random slice. Streams also differ in shape. A live Claude Code
fleet has strong identities and tool calls but no shared chat; the AI Village has about 20 agents with rich chat and
stated goals; the German board has handles (partial identities), pages as places and moderators as the environment;
Transluce has no identities at all. A team that suits one is wrong for another. The person's attention is the
scarcest budget, and the monitored population can learn what gets read, so a team must measure its own misses.

Scalable oversight here means that the person's reading grows with the number of findings worth acting on, not with
the number of agents, messages or analysts.

## Rules every team keeps

Any topology is allowed if it keeps these. Most are enforced in code; the rest are doctrine in the
`swarm-oversight` skill.

1. **Code reads everything; models read selections and a random slice.** No role's input is "the stream".
2. **A reader's input is bounded.** When divisions outgrow one reader, sector leads are added; prompts do not grow.
3. **Fixed-shape reports with graded claims and event ids**, checked by a verifier that downgrades claims whose
   evidence does not exist.
4. **A random slice no data can steer**, with its hit rate compared with triage's every cycle.
5. **A budget governs.** Agents, depth, concurrency and spend are capped; past the budget, roles run deterministically.
6. **Stability.** Division ids are kept by overlap; structure changes on evidence that held more than one cycle
   (doctrine), and every change is an `OrgEvent` with its reason.
7. **Blind spots are named** in every report and every cycle's state.
8. **Agent text is untrusted data**, reaching only roles with `raw_access`, inside an untrusted envelope.
9. **The person sees findings, not reports**, and can trace any finding to event ids.
10. **What a team changes about itself is visible, reversible and attributable**, and can be saved as a preset.
11. **Reading is cheap; authority is budgeted.** Spawning a reader costs only model budget; raising a case to ALERT
    draws on a separate, smaller per-cycle budget, so a team can grow its eyes and still not flood the person.
12. **Two independent views before ALERT**: a watcher and an analyst, or two roles, not two passes of one prompt.
13. **Both discovery modes run.** The pack's questions drive specialists; the scale layer surfaces what nobody
    wrote a question for.

## The topology spec

A team is a topology: a YAML file validated by `agents/spec.py` (`from_dict` + `validate`). The Organization screen
edits the same structure, and an edited team can be saved as a new file.

| Block | Says |
|---|---|
| `root` | the role that runs every cycle (lead, director, curator) |
| `roles` | every role an agent can take (below) |
| `helpers` | native Claude Code sub-agents a role can call through the Task tool, such as `skim_reader` |
| `partition` | how the population is cut into slices for division-scoped roles |
| `levels` | readers inserted above divisions while the span is exceeded |
| `standing` | roles spawned at the start and kept, whatever the partition |
| `questions` | which role answers which kind of question; `"*"` is the fallback |
| `cadence` | what one cycle is: every N windows, or every N records |
| `scaling` | caps: `max_agents`, `max_depth`, `max_concurrent_runs`, `budget_usd_per_cycle`, `budget_usd_total` |
| `maintain` | the policy applied after the root runs: cover, audit, explore, split, retire |
| `triage` | reading budget, priority weights and lane shares (see [reading-at-scale.md](reading-at-scale.md)) |
| `authority` | `alerts_per_cycle`, `ack_sla_windows`, `quiet_windows` for the findings ledger |
| `human` | `interrupt_at` (the level the Brief treats as an interrupt), `briefing_every`, `approvals` |
| `envelope` | what a director may change without a person (see "Proposals and the envelope") |

Every block is optional; a missing one keeps the runtime's default behaviour.

### Roles

A role has a prompt (inline or a file under `topologies/prompts/`), a model and effort, `max_turns`, tools (globs
over `evidence.*` and `org.*`), `raw_access`, `can_spawn` (the roles it may create), an output schema, a memory mode
(`none`, `notes`, `session`, `state`), a scope kind (population, sector, division, audit, question, any, ...), a
refresh cadence, native helpers, a backend (`claude_code`, `stub`, `external`), skills and `skill_refs`, and
`delegate`. Its `kind` names the deterministic behaviour it falls back to in rules-only mode (`BEHAVIOURS` in
`agents/deterministic.py`), so every team runs for free with the same mechanism.

### Standing and on call

A **standing** role is spawned at the start and kept (the auditor, a diarist, an integrity specialist). An **on
call** role exists in the topology but is spawned only when something asks for it: a question routed to it, the
root's own decision, or an open finding (explorers). The composer decides which parts are standing and which are on
call from measured evidence.

### Partition

`partition.by` is `cohort`, `field` (any categorical attribute, with `field:`), `resource_cluster`, `group`,
`family` or `none`, with a `span` and `min_events`. It drives the older `divisions` keys (`_aliases` in
`spec.py`), so the runtime has one source of truth. `by: field` lets a stream be cut on whatever axis it has: a
page namespace, a method class, a repo.

`levels` takes a list of `{role, span}`, but only the first level is built: the sector lead, inserted while there
are more divisions than `span` and removed when there are not (`refresh_sectors` in `runtime.py`).

### Questions routing

`questions` maps a pack's question kind to the role that answers it. When a question of that kind opens, `maintain`
spawns that role scoped to the question (at most three a cycle), or the `"*"` fallback. This is how
`packs/<id>/questions.yaml` turns into specialists without the topology naming every question.

### Maintain

After the root runs, `maintain` retires agents whose division dissolved or that stayed quiet for
`retire_quiet_cycles`; splits divisions over `split_when_events_over`; keeps one auditor on the audit lane
(`audit_with`); spawns `standing` roles and question routes; sends explorers (`explore_with`); covers each division
with `cover_divisions_with`; and places analysts under their sector leads. Exploring is interest-driven: every open
case at `explore_min_level` (INVESTIGATE) or above gets an explorer for its area, at most `explore_max` at a time;
an explorer is let go when its case closes, or after `explore_ttl_cycles` if the case did not rise.

### Budgets

`scaling` caps the organization; `can_spawn` checks the role, `max_agents` and `max_depth` before any spawn.
Once `budget_usd_per_cycle` or `budget_usd_total` is spent, further runs are deterministic, with an org event
saying so. Per-run costs seen through the local Claude Code CLI (whose estimates run high): about $0.45 for a Sonnet
5.5 low analyst, $0.05 for a Haiku helper, $0.8 to $1.2 for an Opus 5.5 medium director (2026-10-04).

## The runtime

`agents/runtime.py` (`AgentOrg`) spawns, runs, scales and retires the team. A cycle runs at the topology's cadence,
or at once on human input or an escalation; between cycles the deterministic executive keeps the Brief current
(`org/executive.py`). One cycle:

1. Refresh divisions (ids kept by overlap), regroup sectors, allocate triage and hand each pick to the agent that
   owns it.
2. `refresh_children`: due agents run in parallel, deepest first, and report bottom-up.
3. `root`: the root reads the reports, writes the executive state and reshapes the team through org tools.
4. `maintain`: the policy above.
5. The coverage ledger is written and its warnings join the state's blind spots.

Every node is persisted (`AgentNode`), every run recorded (`AgentRun`, `AttentionRecord`), every structural change
an `OrgEvent`.

### Org tools

`agents/org_tools.py` exports the in-process MCP server `org`: `org_status`, `list_roles`, `spawn_agent(s)`,
`run_agent`, `get_report`, `retire_agent`, `split_division`, `merge_divisions`, `define_division`, `ask_question`,
`set_triage`, `escalate_finding`, `cases`, `propose_role`, `propose_change`, `log_decision`, `delegations`. Each
structural tool is checked against the topology. A parent waiting on its children gives up its concurrency slot, so
nesting cannot deadlock.

### Delegation

Two layers, kept apart on purpose:

- **Light delegation.** A role with `delegate: true` (the root of every preset, and most analysts, sector leads and
  explorers) has the Task tool with a `reader` sub-agent it briefs itself, with the role's own evidence tools and
  scope, plus the topology's helpers. No permission is asked; a reason is required. The doctrine is
  `.claude/skills/swarm-oversight/references/delegation.md`.
- **Structural change** (a new persistent role, another partition, another base team) goes through proposals.

Every delegation lands in `data/runs/<source>_<started>/delegations.jsonl` and on the Organization page: native Task
calls, managed spawns, re-runs and retirements with their briefs, escalations, proposals, and `log_decision` notes
("not delegating X because ...") (`agents/delegation.py`). The file alone explains every reader that existed and why.

## The presets

| Preset | For | Shape |
|---|---|---|
| `lead` | the default for every source | a lead analyst (Sonnet 5.5 medium) watches everything and sends explorers to areas with open findings; nothing pre-assigned |
| `triage_tree` | thousands of agents with identities | Opus director, division analysts over cohorts, sector leads above 6 divisions, a Haiku auditor on the random slice, specialists on demand |
| `desks` | tens of agents with a shared chat and stated goals (the Village) | a desk analyst per group, a diarist, standing integrity and goals specialists, comms and environment specialists on call, an auditor; Sonnet director |
| `board_watch` | partial identities on shared pages with moderators (the German board) | namespace analysts (partition by `family`), identity resolver, moderation-response and propagation specialists, an auditor, sector leads if needed |
| `catalog_review` | identity-free records about targets (Transluce) | a curator, method analysts, a grade auditor and a chronicler (standing), a new-method specialist; a cycle every 500 records |
| `hierarchical_divisions` | mid-size streams with a resource graph | Opus director, one analyst per community in the agent–resource graph, specialists |
| `flat_pool` | comparison | a director over one generalist per group |
| `single_agent` | baseline: does a team beat one agent? | one agent with evidence tools |
| `sdk_native` | comparison with the managed hierarchy | one Claude Code session with native sub-agents; nothing persists between cycles but the director's state |

Each preset has a reason not to be another. The Village does not get the triage tree because 20 agents make a
handful of cohorts and the story that matters is each agent's over days. The German board gets its own shape because
identity is a question to resolve, never an assumption. Transluce has no "who", so no agent divisions, no diarist and
no identity questions; its guard is against volume masquerading as evidence. The diarist grades repeated agent words
as SELF_REPORTED.

## Which team a source gets

`choose_topology` in `agents/selector.py`, in order of authority:

1. **A session override** (`agents.topology`): a preset id, `composed`, or an edited topology. The Compose screen
   sets it when a person picks a team other than the default.
2. **A pack's `topology:`** in `oversight.yaml`, or `topology: auto` for the selector's pick.
3. **The org config's default**, `agents.topology` in `orgs/default.yaml`: `lead`.

Any failure falls back to the default with the reason. The choice, who made it and why are shown on the Compose and
Organization screens.

### Per-pack oversight.yaml

Each shipped pack names the preset that suits it with `preset:` and a `reason`, and may carry `overrides`
(deep-merged into that preset when it is chosen). `preset:` is a suggestion: Compose offers it as "suits this
source", and the default team stays `lead`. `ai_village` suggests `desks` (with a Sonnet 5.5 low director),
`german_wiki` `board_watch`, `transluce` `catalog_review` (cadence every 500 records), `swarm_scale` `triage_tree`;
`claude_code`, `generic_stream` and `dump` say `auto`. The German board and Transluce partition by `family`, which
holds the page namespace in one and the method class in the other.

`promote_preset` (`agents/proposals.py`) writes the running team to `topologies/<name>.yaml` and points the pack's
`oversight.yaml` at it with `topology:`, so a team improvised for a stream becomes that stream's team.

### The selector

The selector computes a shape from the stream (structure only: identity strength, population, rate, cohorts,
capabilities, candidate partition axes, catalog) and walks a decision table; the first row that matches wins.

| If | Team | Partition |
|---|---|---|
| a catalog | `catalog_review` | `family`, `method` or `technique`, span 8 |
| no identities | `triage_tree` | cohort (the unit is the target) |
| partial identities, strong resources, an environment that acts | `board_watch` | a namespace-like axis with at most 12 values, span 4 |
| strong identities, at most 60 agents, communication | `desks` | group, else family |
| more than 60 units or more than 12 cohorts | `triage_tree` | cohort |
| otherwise | `triage_tree` | the best candidate axis, else cohort |

Its pick is applied when a session asks for `auto` by name (dump analysis's "Picked by the selector") or a pack's
`oversight.yaml` says `topology: auto`. No shipped pack does (they suggest a `preset:`), so a source opened from the
start screen gets the default team unless you pick another, and the Organization page shows the selector's pick
beside it ("from the stream's shape alone SwarmFrame would pick ..."). When a pack applies the pick and models are
on, a Scout is added: it runs once, reads the shape, and returns an `architecture_proposal`.

## The composer

`agents/composer.py` builds a team from the parts the presets are made of, so a stream gets the readers and
specialists its records call for rather than a whole preset. It was added on 2026-10-10 and is the default team in
dump analysis (`--team composed`) and an option on the Compose screen ("Composed for this data").

It first measures the records, structure only: counts and shares of self-report actions, environment actions and
goal actions, texts whose fingerprint has more than one first author, actor names that share a stem with two or more
others, groups, units, graded records and the partition axes. Then:

| Part | Copied from | Switched on when |
|---|---|---|
| Lead (root) | `lead` | always |
| Explorers (on call) | `lead` | always; sent for findings at INVESTIGATE or above |
| Readers | `triage_tree` | more than 40 units or 12 cohorts; cut by group (strong identities, 2 to 60 groups), by a field with about 8 values, or by cohort |
| Sector leads | `triage_tree` | more than 12 slices |
| Integrity specialist | `desks` | self-reports: standing at 5% of records, on call at 0.5% or 5 records |
| Goals specialist | `desks` | stated goals: standing at 10 goal records |
| Propagation specialist | `board_watch` | shared texts: standing at 10, on call at 1 |
| Environment specialist | `board_watch` | deletions, stops, denials: standing at 2% of records |
| Identity resolver | `board_watch` | partial identities with look-alike names: standing at 30 |
| Diarist | `desks` | strong identities and a cast of 2 to 40 |
| Chronicler, grade auditor, new-method specialist | `catalog_review` | a catalog (the grade auditor only when records carry a grade) |
| Auditor | `triage_tree` | 200 records or more |

Specialists are switched on by what the records show, never by the source's name: a new stream with self-reports and
shared text gets an integrity checker and a propagation specialist whether or not anyone wrote a pack for it. Every
part carries its reason and the measure behind it, as a count with its base and share. Standing specialists get a
brief; on-call parts are reached through the questions map, with `"*"` routed to explorers. Cadence, agent caps and
budget scale with the population (a cycle every 3 windows and $1 a cycle up to 40 units; every 6 windows and $0.50
above). The result goes through `from_dict` like a hand-written topology, so it can be edited on the Organization
screen, compared with the presets on the same data, and saved as a preset.

### The Claude composer

`compose_with_claude` gives Claude the measures, the shape, the axes, the part catalog and the rules' composition,
and accepts only JSON in a fixed schema: standing, on call or off per part, a partition (`cohort`, `field` on a
measured axis, `group`, or none) and a budget (`economical` or `thorough`), with a reason per change. The assembly
and validation stay in `compose`. Claude cannot add a role, a tool or raw access this way. If it does not answer,
the rules' composition stands.

### Comparing teams on one record

In dump analysis (`analysis/jobs.py`) several teams can read one record. Without ground truth the comparison scores
agreement (recall against the findings most teams raised), what was read closely, supported claims, agents and cost;
a search tries composed variants on the first 30% and reads the rest with the best. See `docs/REFERENCE.md`,
"Which team reads the dump".

## Proposals and the envelope

A director or the Scout may propose (`agents/proposals.py`): a new role (`propose_role`), a change to `partition`,
`levels`, `standing`, `questions`, `cadence`, `human`, `authority` or `triage` (`propose_change`), or another base
team. A proposal is data validated against the grammar; nothing in it is an instruction to the system.

The `envelope` says what applies without a person. By default: a new reading-only role, no raw access, a model no
stronger than Sonnet 5.5, at most one new role a cycle. Anything that touches `human.approvals` (by default raw
access, a partition change, a team change, the human contract, going over budget) waits in the approvals queue on
the Brief and the Organization page. Proposals apply between cycles, never while agents hold slots, and an applied
one can be reverted for one cycle.

## Findings and escalation

`org/cases.py` is the one path through which a finding is tracked and escalated, whoever saw it first (a watcher,
an analyst's concerning report, a specialist's verdict, an agent's `escalate_finding`, a person).

| Rule | How |
|---|---|
| One case per open scope | later sightings update it and add a *view* |
| Levels rise only through the ledger | `Incident.history` records when, to what, by whom, why and on which evidence; a request not granted is recorded as held |
| Two views before ALERT | ALERT and PAGE need two independent sources; until then the request is held at INVESTIGATE and granted when the second view arrives |
| Evidence must exist | an escalation citing unknown ids is held |
| Authority budget | `authority.alerts_per_cycle` (default 3) cases may rise to ALERT per cycle; the rest wait |
| People are never held; agents get a fast path | a person's change applies at once, with a reason; an agent's escalation reaches the Brief at once and brings the next cycle forward |
| Acknowledgement | ALERT and PAGE wait for a person's receipt; past `ack_sla_windows` they are overdue and lead the Brief |
| Aging with a trail | quiet INVESTIGATE cases go to monitoring after `quiet_windows` and resolve after twice that; ALERT and PAGE never fade |

The human-factors work below adds four rules for what reaches the person. The first is enforced; the others guide
the Brief's design: a hard cap on what reaches the person (the authority budget); evidence before verdict (counts
and cited events, then the team's reading); oversee the plan, not the stream (the team card and the approvals queue
are where a person's minute pays most); and measure accuracy, not confidence.

## Measured

- **Planted swarm, deterministic, `triage_tree`** (2026-10-04): at 2,000 and 5,000 agents every planted behaviour
  was watched, triaged and surfaced as notable (5 of 5); details in [reading-at-scale.md](reading-at-scale.md).
- **MessageBoardAuditBench** (2026-10-11, judge and writer Sonnet 5.5 low, one run each, not comparable to the
  leaderboard): with the parallel writer, headline 0.093 and 0.149 for two runs of the composed team, 0.104 for the
  lead with explorers, 0.112 for the triage tree. Two runs of one team differed by more than the spread between
  teams, so this bench cannot yet rank teams. See `docs/REFERENCE.md`, "MessageBoardAuditBench".

No team other than `triage_tree` has a recall measurement against planted ground truth yet.

## Not built

- Levels deeper than one; `partition.fold_small_into` (declared in `desks.yaml`, not read by the code).
- A critic that diffs what was read against what exists; canaries planted into the compressed views.
- Trust readouts on the Brief, a "since you last looked" digest, interrupt delivery
  (`authority.interrupts_per_day` is declared but not enforced).
- Front-loaded audits for new units, sentinels, syndromic watchers, a certified "nothing found".
- An evaluation of every preset against every planted source.

## Research behind the decisions

A mechanism-level sweep of 2024–2026 work; only items that shaped a choice are listed.

| Source | Mechanism | What SwarmFrame takes |
|---|---|---|
| Ctrl-Z: controlling agents via resampling (2025) | audit budget spent on a decaying threshold | front-loaded audits for new units (not built) |
| Untrusted monitoring protocols, ControlArena (2025) | a trusted model writes a neutral description; ensembled scores | `skim_reader` describes agent text for judging roles; two views before ALERT |
| Ensemble monitoring for AI control (2026) | three diverse monitors gain far more than three identical ones | views must differ to count toward ALERT |
| Multi-agent AI control: distributed attacks (2026) | goals split across agents evade per-agent monitors | the scale layer stays in every team, including small ones |
| Bootstrapped monitoring (2026) | a weak model oversees a stronger monitor's reasoning | the critic as a meta-reader (not built) |
| Adaptive attacks on trusted monitors (2025) | agents that know the monitor prompt inject against it | prompts never appear in the stream; text addressing monitors is a finding |
| Anthropic hierarchical summarization (2025); Clio (2024) | summarize, then summarize summaries; bottom-up taxonomy with size thresholds | both discovery modes; small cohorts folded |
| Hierarchical clustering of agent traces (2026); Meerkat (2026) | facets, embeddings, clusters; an investigator spends budget on suspicious regions | explorers and specialists as investigators; embedding facets not built |
| Transluce Docent (2025) | vague question, rubric, judge at scale | the questions map and its `"*"` fallback; coarse grades |
| LLM-as-judge calibration (2025–26) | 3–6 level scales beat fine ones | claim and status enums stay coarse |
| Anthropic multi-agent research system (2025) | orchestrator–worker; brief = objective, output, boundaries; results via a store | the delegation brief; reports go through the store |
| MAST: why multi-agent systems fail (2025) | weak verification, step repetition, termination unawareness | the verifier and report contract; syndromic watchers not built |
| Dynamic agent hierarchies, AdaptOrch (2024–26) | choose the topology from the task's shape; spawn on observed complexity | the selector, the composer, interest-driven explorers |
| Spawn freely, act sparingly: progressive risk vesting (2026) | reading is cheap; acting authority is budgeted | the authority budget |
| When more is less (2026) | fan-out past a point degrades results | caps on agents and depth; sector span |
| OpenTelemetry GenAI agent spans (2025–26) | a standard agent/tool/session span schema | a structure target for unknown fleets arriving as generic streams |
| Alert fatigue in SOCs (ACM CSUR 2025) | about 40 alerts per analyst-hour at most; static suppression creates blind spots | the authority budget; the audit lane instead of suppression |
| Coding-agent fleet dashboards (2026) | plan-drift warnings; a review queue apart from the feed | the approvals queue; stale-plan watcher not built |
| FEMA ICS; ATC dynamic sectorisation | span of control 3–7; add a layer only when exceeded | sector leads by span |
| Sentinel and syndromic surveillance (CDC) | chosen deep reporters plus cheap signals from everyone | the coverage lane; sentinels not built |
| Adaptive auditing with anytime-valid guarantees (2026) | e-processes let an auditor stop any time with error control | certified "nothing found" (not built) |
| Sandwiching (2022); human–AI complementarity (DeepMind 2025) | human plus model beats either; route by stakes and uncertainty | the Ask flow; approvals as logged corrections |
| Oversight of computer-use agents (2026); oversight without constant attention (2026); confirmation bias in oversight (2025) | plan approval prevents most problems; runtime intervention catches about 21%; better trace UIs raise confidence, not accuracy | the Brief's four rules |

## Open problems

- **Weaker monitors over stronger agents.** Analysts are Sonnet at low effort, auditors Haiku; the population may be
  stronger. Rules plus models, and a meta-reader over the monitors, are known mitigations, unproven at scale.
- **Distributed behaviour.** A goal split across many agents leaves each piece unremarkable; only aggregate views
  (templates across cohorts, convergence, synchronized timing) can see it.
- **Over-structure for small streams.** A director over four desks may cost more than it finds for 20 agents.
- **The cost of orchestration** (roughly 15 times a single reader) is why agents and cost count against a team in
  every comparison.
