# Reading at scale: the triage tree

How SwarmFrame reads thousands of agents that write thousands of messages each, with a reading budget that does not
grow with the population. This note is the design and its measurements. The `swarm-oversight` skill
(`.claude/skills/swarm-oversight/`) is how the models are told to carry it out, and
`backend/swarmscope/agents/topologies/triage_tree.yaml` is the team that runs it in full. How teams in general are
specified, chosen and composed is in [analyst-teams.md](analyst-teams.md).

The scale layer and the triage allocator run for every team. The `triage_tree` preset is the organization built to
work their reading plan: the `swarm_scale` pack suggests it, the selector picks it for more than 60 units or 12
cohorts, and the composer borrows its readers, sector leads and auditor for large populations.

## The arithmetic

| | Small swarm | Large swarm |
|---|---|---|
| Agents | 20 | 5,000 |
| Messages and actions per agent per day | 500 | 1,000 |
| Events per day | 10,000 | 5,000,000 |
| Tokens to read every event once (about 150 each) | 1.5 M | 750 M |
| A generous model budget per day | 20 M | 20 M |
| Share of the stream a model can read | all of it | under 3% |

At this scale no organization of models reads the stream. A system that pretends to (one summarizer over "recent
events", or one analyst per agent) reads a biased sliver and reports it as the whole. Three consequences follow:

1. **Code reads everything.** Every event passes through deterministic compression and detectors. Models read what
   code selected, plus a random sample.
2. **Attention scales with structure, not population.** Model reads per cycle grow with the number of behavioural
   cohorts (roughly with its square root), not with agents or messages.
3. **The selection is a target.** Monitored agents can learn what gets read. A random slice that no data can steer
   keeps the selection honest and measures what it misses.

## The funnel

```
 every event ─────────────────────────────────────────────────────────────────────── code
   │  L0  evidence boundary: normalize, fingerprint, store text behind a reference
   │  L1  scale layer: unit profiles · cohorts · message templates · outliers    (every window)
   │  L2  watchers with per-resource baselines                                   (every window)
   │  L3  triage: this cycle's reading plan in three lanes                       (every cycle)
   ▼
 a few dozen scopes ──────────────────────────────────────────────────────────── models
      L4  division analysts work their plans · auditor reads the random slice · specialists answer one question
      L5  sector leads merge division reports (only when divisions outgrow one reader)
      L6  director: population account, hypotheses, team shape, triage steering, directives
```

The director steers back down: focus, `set_triage`, spawn, split, merge, retire, questions.

## The scale layer

`backend/swarmscope/scale/layer.py` and `templates.py`. Code only; it runs every window and never calls a model.

- **Unit.** What the population is made of: an agent when identities exist, otherwise a key such as the targeted
  resource. Set per source pack (`scale.unit`).
- **Profile.** Streaming per-unit statistics: workstream, action, resource and template mix; rate per window;
  self-shift (total variation between the unit's recent and earlier mix).
- **Cohort.** Units with the same interpretable signature: dominant workstream, dominant action and group. Cohorts
  over 400 units are split by rate tier (quiet, steady, busy), so one cohort never hides a busy minority. Cohorts
  under three units fold into "<workstream> · mixed". The signature is the id, so cohorts are stable across cycles
  and every label says why its members are together. Signatures were chosen over clustering on purpose: oversight
  needs groups a person can name and audit, and signatures cost O(n).
- **Outlier.** A unit far from its cohort's centroid, far from its own history, or far busier than its peers (rate
  z-score), with the reason recorded.
- **Template.** A kind of message: agent text with numbers, ids, urls, paths and emails masked, grouped by the words
  that remain (a small Drain-style miner). Each template has volume, distinct units, cohorts, growth and example ids.
  Spread across cohorts is the propagation signal; a new template with spread is one of the strongest early signs of
  coordination or a shared instruction. Template wording is untrusted text and reaches only raw-access roles, inside
  the untrusted envelope.

In the planted 5,000-agent swarm, 204,000 events compress to 71 cohorts and the messages to 13 templates.

## Watchers that scale

Absolute thresholds stop working when everything is busy, so two watchers in `org/watchers.py` compare a resource
with its own baseline:

- **Shared-resource convergence** fires when a resource's crowd is large in absolute terms and at least twice its
  usual crowd (an EWMA of distinct units per lookback). A team file with eighty regular users stays quiet; a file or
  host that suddenly draws many agents does not. Without this, convergence signals flooded triage.
- **Resource bursts and new methods** (identity-free): per-resource counts against the resource's own EWMA, and an
  event family seen on a resource for the first time after warm-up.

## Triage

`backend/swarmscope/scale/triage.py`. Each cycle the allocator turns candidates into a reading plan.

**Candidates.** Every cohort; the top outliers of each cohort; every agent or resource a watcher flagged at
severity 0.4 or more (a few agents saying one thing and doing another, or scattered agents converging on one host,
are invisible at cohort level); and spreading templates (3 or more units, and more than double the previous count).

**Priority.** `0.35·severity + 0.20·change + 0.15·novelty + 0.20·coverage debt + 0.10·focus`, each in [0, 1].
Severity is the strongest watcher signal on the scope's units; change is |log2(now/prev)| / 3, weighted by volume;
novelty covers new cohorts, new templates, outliers and never-examined signals; coverage debt is cycles since the
last close look over `coverage_every_cycles`; focus comes from the director and from human directives. Weights live
in the topology, and the director can change them.

**Lanes.**

| Lane | Share | Picks | Why |
|---|---|---|---|
| triage | 60% | highest priority | spend where the signal is |
| coverage | 25% | cohorts with the most coverage debt | nothing goes unvisited for long, however quiet |
| audit | 15%, never below 10% | uniformly random units | a population that learns what triage ranks still cannot predict what is read; measures triage's misses |

The audit lane draws with a secret seed taken from the operating system at start, never from the data, mixed with
the cycle number. Lane shares can be steered, but `configure` raises the audit share back to 10% if anyone sets it
lower.

**Budget.** `reads_per_cycle: auto` is 4·√cohorts, clamped to [8, 60]: 30 cohorts give 22 reads, 71 give 34, 400
give 60. With a fixed budget of 10, triage reached only 3 of 5 planted behaviours at 5,000 agents; with the auto
budget it reached 5 of 5.

**Calibration.** Every close look records an outcome, and a lane's hit rate is the share of its looks that found
something notable. When random audits (after at least 4 looks) find something at least 20% of the time and at least
0.8 times as often as triage, the allocator writes a warning into the cycle's blind spots: triage is not separating
interesting scopes from the rest. The doctrine tells the director to say so and change the weights.

**Assignment.** Each pick goes to the agent responsible for it: cohorts to their division's analyst, signals to the
division holding most of the units involved, audits to the auditor. Picks with no responsible agent are listed as
unassigned, a team-shape problem the director must fix or name.

## The organization

| Role | Count | Reads | Writes |
|---|---|---|---|
| Director (Opus 5.5, medium) | 1 | population digest, triage, coverage ledger, sector reports, concerning deeper reports, questions | executive state, briefing, hypotheses, directives, team changes, triage steering |
| Sector lead (Sonnet 5.5, low) | 1 per 6 divisions, only above 6 divisions | its analysts' reports; templates, outliers and timing across its divisions | `division_report` |
| Division analyst (Sonnet 5.5, low) | 1 per division of 6 cohorts (at most 24) | its reading plan; cohort cards, outliers, templates, timelines; raw text through `skim_reader` | `division_report` with `looked_at` per pick and `blind_spots` |
| Auditor (Haiku 4.5) | 1 | profiles and events of the sampled units | `division_report`: sample size, share notable, notable but not triaged |
| Specialist (Sonnet 5.5, low) | on demand | one question, raw text if needed | `finding` with a verdict |

**Depth grows with the logarithm of the population.** With 6 cohorts per division and 6 divisions per sector:

| Agents | Cohorts | Divisions | Sectors | Model runs per cycle | Director input |
|---|---|---|---|---|---|
| 500 | about 12 | 2 | 0 | about 4 | 25k characters (measured) |
| 2,000 | 30 | 5–7 | 0–2 | about 10 | 31k characters (measured) |
| 5,000 | 71 | 16 | 3 | about 21 | 36–41k characters (measured) |
| 50,000 | about 300 (estimate) | 24 (cap) | 4 | about 30 | about 45k characters (estimate) |

The director's input grows by about 60% while the population grows tenfold. Its system prompt (the skill and its
role references) does not grow at all, and is cacheable.

**Cadence.** Watchers and the scale layer run every window. A full cycle runs every 3 windows (the topology's
`cadence`, or `min_cycle_windows`), or at once on human input or an escalation. Between cycles the deterministic
executive keeps the Brief current. The cycle itself is the runtime's: see [analyst-teams.md](analyst-teams.md),
"The runtime".

**The director's protocol** (from the skill's director reference): orient, check coverage, read reports by claim
status, test before accepting (name the rival and the record that separates them), shape the team within budget,
steer triage, and write the state.

## Report contract

Every report has a fixed, bounded shape (`division_report`, `finding`, `director`) with graded claims that cite event
ids. A verifier downgrades OBSERVED or DERIVED claims whose events do not exist or lie in the future. Three fields
carry most of the scale discipline:

- `looked_at`: one entry per reading-plan pick, including "nothing notable" (the denominator matters);
- `blind_spots`: what in scope was not examined, and why;
- `recommend`: split, retire, or a specialist kind.

## The coverage ledger

Written at the end of every cycle (`AgentOrg.coverage`), shown on the dashboard and given to the director: events in
span and in total; units active and seen; cohorts, templates and compression; the share of recent activity in
cohorts that got a close look this cycle; cohorts looked at now and recently; random audits, raw reads and agent
runs; stale cohorts, unassigned picks and uncovered divisions; lane hit rates and warnings. Its warnings and stale
cohorts are copied into the executive state's blind spots.

## Sources without identities

The same machinery runs with `scale.unit: object`. In the Transluce catalog (37,649 reports attributed to autonomous
agents, Nov 2025 to Sep 2026) units are the 40 targeted data sources, cohorts group targets by method class and the
source's own confidence grade, and the resource-burst watcher looks for per-target bursts and new methods. The
skill's `identity_free_sources` reference tells models not to ask identity questions and not to upgrade suggestive
reports by volume. The full catalog replays in about 12 seconds in deterministic mode, and the burst watcher fires on
the April surge that Transluce documents. The `catalog_review` preset is the team built for this shape.

## The skill

The doctrine is a Claude Code skill with two readers. `.claude/skills/swarm-oversight/SKILL.md` holds what every
role shares (the funnel, fourteen rules, the escalation ladder, why the random slice is not optional), and
`references/` one file per role and per topic. The runner puts SKILL.md and the role's `skill_refs` into each agent's
system prompt and offers the rest through a `read_reference` tool (`agents/skills.py`); a Claude Code session opened
in the project discovers the same skill natively. This note says why and what was measured; the skill says what to
do. Rules change in the skill; reasons and numbers change here.

## Measured

Deterministic mode, recorded 2026-10-04. The planted swarm in `packs/swarm_scale` has 5 behaviours (a template
spreading across teams, a team surge, low-rate drift by scattered agents, say-vs-do, an operator stop), over 36
simulated hours. Reproduce with `swarmscope scale-eval --agents 2000 --hours 36`.

| Agents | Events | Cohorts | Watched | Triaged | Surfaced as notable | Triage / audit hit rate | Seconds per window |
|---|---|---|---|---|---|---|---|
| 2,000 | 81k | 30 | 5/5 | 5/5 | 5/5 | 74% / 3% | 1.1 |
| 5,000 | 204k | 71 | 5/5 | 5/5 | 5/5 | 71% / 3% | 5.4 |

Real-model checks, same date (Sonnet 5.5 at low effort through the local Claude Code CLI; its cost estimates run
high):

- **Director**, one cycle on 1,000 agents with deterministic sub-agents, about $0.43: a state with counts and bases,
  a named rival, honest blind spots and a revised entry with its reason. It used no tools and deferred a specialist
  it could afford; the director reference now says to act when the budget allows.
- **Division analyst**, about $0.44: every pick recorded in `looked_at`, reuse claims verified as OBSERVED, a rival
  named, and what it did not check listed. At low effort it made only two tool calls.

## Known limits

- **Paraphrase.** Templates group surface forms; the same idea in other words lands in another template.
- **No online recall.** Without canaries in live streams, per-monitor recall is known only in evaluation.
- **No critic** diffs what was read against what exists beyond the coverage ledger, and there are no label
  predicates (Thimble's labels) for categories the source does not provide.
- **Wall-clock time above 5,000 agents** is dominated by per-window Python in the watchers.

## Research

| Source | What it does | What SwarmFrame took |
|---|---|---|
| Thimble (safety-research/thimble) | survey, rival hypotheses, views, critic; a swarm extension splits a corpus into shares each read whole, then reconciles counts | survey and rival phases; a coverage reconciliation every cycle; a fixed reader schema with an explicit "nothing here"; every number with its base; absence claims name their search |
| Transluce Docent | per-transcript summaries, search, clustering; rubrics as decision procedure, schema and citations | cheap readers and an expensive reducer; structured outputs with citations |
| Anthropic hierarchical summarization for monitoring; Clio | per-interaction summaries, then per-actor aggregates; facets and a hierarchy; minimum cluster sizes; raw text never sets the summarizer's instructions | units → cohorts → divisions → sectors → director, citations kept down to event ids; small cohorts folded; the untrusted envelope |
| AI control: trusted monitoring, audit budgets, random audits, collusion | suspicion-ranked audits within a budget; random audits raise uncertainty for colluders; monitors can be gamed by injected text | three lanes with a random floor and a secret seed; lane hit rates as a measure of triage; text addressing monitors is a finding |
| Stream compression (Drain, MinHash/LSH, sketches, change points, stratified sampling) | templates, near-duplicate clusters, heavy hitters, rate shifts | the template miner over masked text; spread as the propagation signal; per-resource baselines |
