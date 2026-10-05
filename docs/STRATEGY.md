# The default oversight strategy: a triage tree

How SwarmFrame oversees thousands of agents that write thousands of messages each, with a reading budget that does
not grow with the population. This document is the design; the skill in `.claude/skills/swarm-oversight/` is how
the models are instructed to carry it out; `backend/swarmscope/agents/topologies/triage_tree.yaml` is the default
organization that runs it.

## 1. The arithmetic that forces the design

| | Small swarm | Large swarm |
|---|---|---|
| Agents | 20 | 5,000 |
| Messages and actions per agent per day | 500 | 1,000 |
| Events per day | 10,000 | 5,000,000 |
| Tokens to read every event once (~150 each) | 1.5 M | 750 M |
| A generous model budget per day | 20 M | 20 M |
| Share of the stream a model can read | all of it | under 3% |

At population scale, no organization of models reads the stream. A system that pretends to (one summarizer over
"recent events", or one analyst per agent) reads a biased sliver and reports it as the whole. Three consequences
shape everything below:

1. **Code reads everything.** Every event passes through deterministic compression and detectors. Models read what
   code selected, plus a random sample.
2. **Attention must scale with structure, not population.** The number of model reads per cycle grows with the
   number of behavioural cohorts (roughly with the square root), not with agents or messages.
3. **The selection itself is a target.** Monitored agents can learn what gets read. A random slice that no data
   can steer keeps the selection honest and measures what it misses.

## 2. What the research says

| Source | What it does | What we took |
|---|---|---|
| Thimble (safety-research/thimble) | Orientation agent: survey, then hypothesize against rivals, then propose views, then critic; swarm extension splits a corpus into shares each read whole by a subagent, then reconciles counts | Survey → rivals → critic phases; a coverage reconciliation every cycle; fixed reader schema including an explicit "nothing here"; "an agent's claim is not a fact"; every number with its base; absence claims name their search |
| Transluce Docent | Per-transcript summaries, search, clustering (large model proposes centroids, small model assigns); rubrics as decision procedure + schema + citations | Cheap readers, expensive reducer; structured outputs with citations; budget map steps as rows × calls before running them |
| Anthropic hierarchical summarization for monitoring; Clio | Per-interaction structured summaries, then per-actor aggregates; facets, clusters and a hierarchy browsed top-down; minimum cluster sizes; raw text never sets the summarizer's instructions | Units → cohorts → divisions → sectors → director, with citations kept down to event ids; small cohorts folded so noise does not become a headline; untrusted envelope for agent text |
| AI control: trusted monitoring, audit budgets, random audits, collusion | Suspicion-ranked audits within a budget; random audits raise uncertainty for colluders; monitors can be gamed by injected text | Three-lane triage with a random floor and a secret seed; lane hit rates as a measure of triage recall; text addressing monitors is a finding |
| Stream compression (Drain, MinHash/LSH, sketches, change points, stratified sampling) | Collapse messages into templates; near-duplicate clusters; heavy hitters; segments where a rate shifted | Template miner over masked text; spread across units and cohorts as the propagation signal; per-resource baselines for convergence and bursts |

## 3. The funnel

```
 every event ────────────────────────────────────────────────────────────────────────────────── code
   │  L0  evidence boundary: normalize, fingerprint, store text behind a reference
   │  L1  scale layer: unit profiles · cohorts · message templates · outliers           (every window)
   │  L2  watchers: baseline-relative convergence, bursts, reuse, say-vs-do, environment (every window)
   │  L3  triage: this cycle's reading plan in three lanes                               (every cycle)
   ▼
 a few dozen scopes ──────────────────────────────────────────────────────────────────────── models
      L4  division analysts work their plans · auditor reads the random slice · specialists answer one question
      L5  sector leads merge division reports (only when divisions outgrow one reader)
      L6  director: population account, hypotheses, team shape, triage steering, directives
      ▲                                                                                         │
      └──────────────── top-down: focus, set_triage, spawn/split/merge/retire, questions ◄──────┘
```

### L1: the scale layer (`backend/swarmscope/scale/`)

- **Unit.** What the population is made of: an agent when identities exist, otherwise a key such as the targeted
  resource (identity-free sources). Configured per source pack (`scale.unit`).
- **Profile.** Streaming per-unit statistics: workstream, action, resource and template mix; rate per window;
  self-shift (distance between the unit's recent and earlier mix); error-like actions.
- **Cohort.** Units with the same interpretable signature: dominant workstream, dominant action, group, and, for
  cohorts over 400 units, a rate tier (quiet, steady, busy), so one cohort never hides a busy minority. Cohorts under
  three units fold into "<workstream> · mixed". The signature is the id, so cohorts are stable across cycles, and
  every cohort label says why its members are together. We chose signatures over clustering on purpose:
  oversight needs groups a human can name and audit, and signatures cost O(n).
- **Outlier.** A unit far from its cohort's centroid (total variation of mixes), far from its own history, or far
  busier than its peers (rate z-score), with the reason recorded.
- **Template.** A kind of message: agent text with numbers, ids, urls, paths and emails masked, grouped by the words
  that remain (a small Drain-style miner). Volume, distinct units, cohorts, growth and example event ids. Spread
  across cohorts is the propagation signal; a brand-new template with spread is one of the strongest early signals
  of coordination or shared instruction. Template wording is untrusted text and reaches only raw-access roles, in an
  untrusted envelope.

In the planted 5,000-agent swarm, 204,000 events compress to 71 cohorts, and its messages to 13 templates.

### L2: watchers that scale

Two watchers changed for scale. Absolute thresholds stop working when everything is busy, so baselines are
per resource:

- **Shared-resource convergence** now fires when a resource's crowd is large in absolute terms *and* at least twice
  its usual crowd (an EWMA of distinct units per lookback). Team files with eighty regular users stay quiet; a file
  or host that suddenly draws many agents does not. Without this, convergence signals flooded triage.
- **Resource bursts and new methods** (new; identity-free): per-resource counts against the resource's own EWMA, and
  an event family seen on a resource for the first time after warm-up.

### L3: triage (`backend/swarmscope/scale/triage.py`)

Each cycle the allocator turns candidates into a reading plan.

**Candidates.** Every cohort; the top outlier units of each cohort; every agent or resource that a watcher flagged
at severity ≥ 0.4 (a "signal": a few agents saying one thing and doing another, or scattered agents converging on
one host, are invisible at cohort level); and templates that are spreading (≥ 3 units, more than double the
previous span).

**Priority.** `0.35·severity + 0.20·change + 0.15·novelty + 0.20·coverage debt + 0.10·focus`, each component
in [0, 1]:
severity is the strongest watcher signal on the scope's units; change is |log2(now/prev)| / 3, weighted by
volume; novelty covers new cohorts, new templates, outliers, and never-examined signals; coverage debt is cycles
since the scope's last close look, divided by `coverage_every_cycles`; focus comes from the director and from human
directives. Weights are in the topology and the director can change them.

**Lanes.**

| Lane | Share | Picks | Why |
|---|---|---|---|
| triage | 60% | highest priority | spend where the signal is |
| coverage | 25% | cohorts with the most coverage debt | nothing goes unvisited for long however quiet it seems |
| audit | 15%, floor 10% | uniformly random units, secret seed | a population that learns what triage ranks still cannot predict what is read; measures triage's misses |

**Budget.** `reads_per_cycle: auto` = 4·√cohorts, clamped to [8, 60]. 30 cohorts give 22 reads; 71 give 34; 400
would give 60. With a fixed budget of 10, triage reached only 3 of 5 planted behaviours at 5,000 agents; with the
auto budget it reached 5 of 5. That is how the design keeps its promise that attention follows structure.

**Calibration.** Every close look records an outcome, and each lane's hit rate is the share of its looks that found
something notable. In the 2,000-agent run, triage hits 74%, coverage 52%, and random audit 3%: triage separates
interesting scopes from the rest. If the audit rate approaches the triage rate, the allocator writes a warning into
the executive state's blind spots and the director widens the random slice.

**Assignment.** Each pick goes to the agent responsible for it: cohorts to their division's analyst, signals to
the division holding most of the units involved, audits to the auditor. Picks with no responsible agent are listed
as unassigned, which is a team-shape problem the director must fix or name.

### L4–L6: the organization (`triage_tree` topology)

| Role | Count | Scope | Reads | Writes |
|---|---|---|---|---|
| Director (Opus 5.5, medium) | 1 | population | population digest, triage, coverage ledger, sector reports, concerning deeper reports, monitor reports, questions | executive state, briefing, hypotheses, directives, team changes, triage steering |
| Sector lead (Sonnet 5.5, low) | 1 per 6 divisions, only when divisions > 6 | sector | its analysts' reports; cross-division templates, outliers, timing | a division_report |
| Division analyst (Sonnet 5.5, low) | 1 per division (6 cohorts) | division | its reading plan; cohort cards, outliers, templates, timelines; a few events; raw text through a reading helper | a division_report with `looked_at` per pick and `blind_spots` |
| Auditor (Haiku 4.5) | 1 | the random slice | profiles and events of sampled units | a division_report: sample size, share notable, notable-but-not-triaged |
| Specialist (Sonnet 5.5, low) | on demand | one question | everything in scope, raw text if needed | a finding with a verdict |

**Depth is logarithmic.** With 6 cohorts per division and 6 divisions per sector:

| Agents | Cohorts (measured or est.) | Divisions | Sectors | Model runs per cycle | Director input |
|---|---|---|---|---|---|
| 500 | ~12 | 2 | 0 | ~4 | 25k chars (measured) |
| 2,000 | 30 | 5–7 | 0–2 | ~10 | 31k chars (measured) |
| 5,000 | 71 | 16 | 3 | ~21 | 36–41k chars (measured) |
| 50,000 | ~300 (est.) | 24 (cap) | 4 | ~30 | ~45k chars (est.) |

The director's input grows by about 60% while the population grows 10×; its system prompt (the skill and two
references, 15.6k characters) is constant and cacheable.

**Cadence.** Watchers and the scale layer run every window. A full organization cycle runs at most every
`min_cycle_windows` (default 3), or immediately on human input. Between cycles the deterministic executive keeps the
briefing current.

**One cycle.**

1. Refresh divisions from cohorts (ids kept stable by overlap), regroup sectors if needed, allocate triage, assign picks.
2. Run due agents deepest first: analysts and the auditor, then sector leads reading fresh reports.
3. The director works its protocol (below).
4. Maintenance: cover uncovered divisions, keep one auditor, place analysts under sector leads, retire quiet agents.
5. Write the coverage ledger; carry its warnings and stale cohorts into the executive state's blind spots.

**The director's protocol** (from the skill): orient, check coverage, read reports by claim status, test before
accepting (name the rival and the record that separates them), shape the team within budget, steer triage, and
write the state.

### Report contract

Every report has a fixed shape (`division_report`, `finding`, `director`), bounded in size, with graded claims citing
event ids. A verifier downgrades OBSERVED or DERIVED claims whose events do not exist or lie in the future. Three
fields carry most of the scale discipline:

- `looked_at`: one entry per reading-plan pick, including "nothing notable" (the denominator matters);
- `blind_spots`: what in scope was not examined, and why;
- `recommend`: split, retire, or a specialist kind.

### The coverage ledger

Written at the end of every cycle, shown in the dashboard and given to the director:

- events in span and in total; units active and seen; cohorts; templates and compression;
- the share of recent activity in cohorts that got a close look this cycle;
- cohorts looked at now and recently;
- random audits, raw reads and agent runs;
- stale cohorts, unassigned picks and uncovered divisions;
- lane hit rates and warnings.

## 4. The skill

`.claude/skills/swarm-oversight/` is a real Claude Code skill: SKILL.md (the doctrine every role shares: the funnel,
thirteen rules, the escalation ladder, why the random slice is not optional) plus references per role (director,
sector_lead, division_analyst, auditor, specialist) and per topic (reading compressed views and their failure modes,
the report contract with good and bad examples, identity-free sources).

- SwarmFrame's runner puts SKILL.md and the role's `skill_refs` into each agent's system prompt, and gives it a
  `read_reference` tool for the rest (progressive disclosure).
- A Claude Code session opened in the project discovers the same skill natively, so a human working with Claude
  Code over the channel gets the same doctrine.
- Roles choose skills in the topology (`skills`, `skill_refs`); validation rejects unknown skills.

A second skill, `dashboard-designer`, instructs the agent that composes the dashboard around a stream (section 6).

## 5. Sources without identities

The Transluce catalog (37,649 URLQuery reports attributed to autonomous agents, Nov 2025 to Sep 2026) has no
persistent agent identities. The same machinery runs with `scale.unit: object`: units are the 40 targeted data
sources, cohorts group targets by method class and the source's own confidence grade, and the `targets` monitor
watches per-target bursts and new methods. Identity panels disappear from the auto-designed dashboard, and a targets
page replaces them. The skill's `identity_free_sources` reference tells models not to ask identity questions and not
to upgrade suggestive reports by volume. The full catalog replays in about 12 seconds in deterministic mode. The
burst watcher fires on the April surge that Transluce documents.

## 6. A dashboard the agent shapes around the stream

- The **stream profile** (`dashboard/profile.py`) is all a designer sees: capabilities, field cardinalities, the
  most common values of short categorical fields, the rate over time, attribute shapes, and the scale layer. It has
  no agent-written text. Attributes that look like text or are high-cardinality are named, marked unusable, and
  refused by the query compiler.
- **Views** are a primitive (`stat`, `timeseries`, `bar`, `heatmap`, `table`, `note`) plus a query in a small
  language compiled to parameterized SQL, clipped to the replay clock. Derived sources are cohorts, templates,
  triage, claims, the org, and observations.
- **Edits** are ops (add, update, remove or move pages and panels; set the Brief; set terminology; lenses). They are
  validated, atomic, versioned per source and undoable.
- **Who designs.**
  - On session start the free auto-designer builds a dashboard from the profile.
  - "Design with Claude" runs one Claude Code session with the dashboard tools and the dashboard-designer skill.
  - The copilot and the user's own Claude Code session (over the channel) have the same tools.
  - The human can build a view by hand in the design studio.

## 7. Measured

Deterministic mode, the planted swarm in `packs/swarm_scale` (5 behaviours: a template spreading across teams, a
team surge, low-rate drift by scattered agents, say-vs-do, an operator stop), 36 simulated hours:

| Agents | Events | Cohorts | Watched | Triaged | Surfaced as notable | Triage / audit hit rate | Seconds per window |
|---|---|---|---|---|---|---|---|
| 2,000 | 81k | 30 | 5/5 | 5/5 | 5/5 | 74% / 3% | 1.1 |
| 5,000 | 204k | 71 | 5/5 | 5/5 | 5/5 | 71% / 3% | 5.4 |

Real-model checks (Sonnet 5.5, low effort, via the local Claude Code CLI; costs are the CLI's estimates, which run
high):

- **Director** (one cycle on 1,000 agents, sub-agents deterministic, about $0.43): a state with counts and bases, a
  named rival ("a shared upstream source is as likely as propagation"), honest blind spots, and a revised entry
  with its reason. It used no tools and deferred a specialist it could have afforded; the director reference now
  says to act when the budget allows.
- **Division analyst** (about $0.44): every reading-plan pick recorded in `looked_at`, reuse claims verified as
  OBSERVED, a rival named, and exactly what it did not check listed. At low effort it made only two tool calls.
- **Dashboard designer** (Transluce, about $0.91): profile and catalog read, every view previewed, and a six-panel
  page on grade mix and bursts added that follows the skill: a note, the total beside the subset, and grades kept
  as their own dimension.

## 8. Known limits and next steps

- **Paraphrase.** Templates group surface forms. Embedding clusters (Clio-style facets) would catch the same idea
  in different words.
- **Canaries.** Planted known-bad and known-benign items injected into live streams would give per-monitor recall
  online, not only in evaluation.
- **A critic.** A critic role in the cycle that diffs what was read against what exists (Thimble's critic), beyond
  the coverage ledger.
- **Label predicates.** The cheapest classifier that works, piloted on a small sample and auditable in the UI
  (Thimble's labels), for categories the source does not provide.
- **Wall-clock time at 5,000+ agents** is dominated by per-window Python in watchers. Columnar watchers in DuckDB
  are the next optimization.
