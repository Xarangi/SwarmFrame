# The World: a 3D model of the swarm that is an instrument, not a picture

Plan drafted 2026-10-03, completed 2026-10-04. Built 2026-10-04: see the status section below.

**Part I** (§0–§13) is the argument: why, what it encodes, how it is laid out, which data first, how it feeds back.
**Part II** (§14–§24) is the contract: the fixed primitive library, the data-availability model, the encoding grammar,
the complete WorldSpec, the designer's instructions conditioned on the data, legend and interaction rules, wire
formats, the null model, and acceptance criteria per phase.

## Status (2026-10-04): built

W0 to W3 are implemented. The parts not yet built are listed at the end of this section.

**Where it lives**

- `backend/swarmscope/world/`: `features.py` (availability grading), `layout.py` (anchors, bounded forces, null
  model), `engine.py` (per-window step, flags, state), `spec.py` (WorldSpec, grammar, ops, store, presets),
  `designer.py` (free composer and the Claude designer run).
- Presets: `packs/{swarm_scale,ai_village,transluce,claude_code}/world.yaml`. German Wiki has a pack
  (`packs/german_wiki`) running on a synthetic stand-in.
- Skill: `.claude/skills/world-designer/` with references for shapes, primitives and presets, including the
  render-tier latency table (dots for thousands, characters only for about 80 agents or fewer).
- Frontend: `src/world/characters.ts` (the newts-lab cast: newt, human, frog, owl, fox, robot), `src/world/view.ts`
  (three.js renderer with characters, instanced pawns, dots and blobs, plinths), `src/screens/World.tsx` (page,
  scenes, legend, cards, box select, mini panel).
- Feedback: the SpatialDrift watcher, the `world_features` evidence tool, copilot ops `world_get`,
  `world_features`, `world_preview`, `world_edit`, `world_select`, and division analysts' `cohort_labels`.
- Tests: `tests/test_world.py`. Evaluation: `python -m swarmscope.evals.world_eval 1000`.

**Scene and activity rules (added 2026-10-04)**

- `world/scene.py`: the WorldSpec's `environment` (ground style, up to 8 zones drawn as soft tinted regions with
  labels, up to 16 prop placements / 480 instances) and `behaviours` (up to 8 activity rules: `when` one of 11
  server-computed conditions, `do` a library choreography or a validated `sequence` of steps; first match wins).
  `world/assets.py`: 22 generic props (tree, bench, desk, bookshelf, server_rack, terminal, small_house, ...) as part
  lists in the model kit; all pass `check_model`. Props never use `tint` and are drawn muted.
- The state carries `env` (zone discs, prop instances placed deterministically from the landmarks) and `acts` per unit
  (condition bitmask, behaviour index, target place, partner), base64 and bounded: one place and one partner per unit,
  only the busiest 1,500 units choreographed (400 at dots scale).
- `src/world/scene.ts` plays each unit's plan over the window's playback (walk pose while moving, work and talk poses
  at the place, return to the measured position); pulses, glows, carried tokens and fades are instanced. The dots tier
  skips choreography. The legend opens with "What you are seeing": each rule's meaning with how many units it moves
  now, the zones, the ground, and a note that scenery encodes nothing.
- Ops: `set_environment`, `add_zone`, `remove_zone`, `place_props`, `remove_props`, `add_behaviour`,
  `update_behaviour`, `move_behaviour`, `remove_behaviour`; designer tools `world_behaviour_catalog` and
  `world_asset_catalog`; skill references `environment.md` and `behaviours.md`. `compose_world` picks a ground, zones,
  props and one rule per capability; all five presets ship a designed scene. Unedited worlds composed before scenes
  existed are recomposed on load.

**Evaluation on the planted swarm, 1,000 agents, 12 hours**

| Measure | World | Shuffled null or control |
|---|---|---|
| Team separation | 7.06 | 3.17 |
| Cohort separation | 4.76 | 2.72 |
| Drift: displacement AUC | 0.76 | |
| Drift: gathering ratio | 0.80 | 1.08 |
| Surge: displacement AUC | 0.71 | |
| Surge: gathering ratio | 0.80 | 1.02 |
| Say-do: displacement AUC | 0.68 to 0.71 | |
| Say-do: gathering ratio | 0.80 to 0.89 | about 1.05 |
| Operator actions drawn as beams | 100% | |
| False flags per window before any planted behaviour | 0.05 | |

A gathering ratio below 1 means the planted agents moved closer together than the controls did.

**Latency at 5,000 agents:** a median of 133 ms per window for the world step. The state payload is about 257 KB.

**Known limits**

- Spread is not spatially separable on the planted swarm, because its templates are fragmented across ids.
- The crowding flag is conservative. It compares against the null's per-window maxima, so a planted crowd on one
  host does not cross it. A distinct-teams-per-place measure is a candidate replacement.
- Lineage arcs appear only when the propagation watcher has recorded reuse.
- Box select is shift-drag. Agents and places that are not on the map, such as artifacts, show a toast instead.

**Added after the first build (2026-10-04)**

- Models the designer makes (§14.7), with the check tool, the Edit-menu viewer and legend entries.
- The World on the Brief, beside "Needs attention" (Brief settings can hide it).
- A real designer run (Sonnet 5.5, low effort, planted swarm of 300 agents, asked to make hosts read as servers):
  8 turns, 22 seconds, about $0.43. It surveyed the features, checked one model, applied it in one edit, previewed
  (separation 1.53 against a null of 1.26) and returned its critic list. The model was a six-part server rack used
  for web hosts, with a recorded reason. Its one failed critic item was the old six-encodings rule, which counted
  ground encodings; the rule now counts at most six on a unit and four on the ground.

- Catalog mode for Transluce: a deterministic "mix" layout (method classes as corners, targets between them by
  their whole-record method mix), towers as stacked method bands, height as total reports, glass as mostly
  suggestive, every tower labelled. The shuffled-swarm glow is off for catalog maps because their positions do not
  come from forces.
- The German Wiki pack and preset (`packs/german_wiki`), on a synthetic stand-in until the export is downloaded.

**Not built yet**

- The German Wiki real export: not downloaded; the loader maps fields by alias and must be checked with a
  structure-only probe first.
- Time scrubbing of the World independent of the replay clock.

## 0. The idea in one paragraph

SwarmFrame already compresses thousands of agents into cohorts, outliers, findings and a Brief. The World adds a
second representation of the same evidence: a 3D space in which **where an agent stands is a measurement**. Agents
that work on the same things stand together; agents that behave alike stand together; agents that drift apart in
behaviour drift apart in space; a crowd forming at a shared file is literally a crowd forming at a landmark; an
agent that keeps talking about work it never does stands still while its speech bubble flickers. People are poor
at reading 2,000 rows and very good at noticing a shape change in a scene they have been watching. The World turns
the swarm's behaviour into shapes and motion, with every encoding measured, legended and clickable back to evidence,
and it feeds what it computes (clusters, drift, isolation, crowding) back into the analysts and the copilot, so the
human and the AI reason about the same picture.

## 1. Theory of impact

### 1.1 Why a spatial model should help (the mechanisms)

| Mechanism | What it buys | Where it comes from |
|---|---|---|
| **Preattentive perception.** Position, motion, size and colour are processed in parallel, before attention. A lone sprite drifting away from its group is seen in under a second; the same fact in a table needs a scan. | Faster *noticing* of anomalies, especially the kind our watchers do not have a rule for yet. | Healey & Enns, preattentive processing; Ware, *Information Visualization* |
| **Spatial memory and change blindness avoidance.** People remember *where* things were. A scene watched over minutes makes slow change visible as displacement, where a list of changing numbers does not. | Detection of drift and slow convergence, which are the planted behaviours our watchers find latest. | Scene-based change detection literature |
| **Semantic zoom.** Overview first (cohorts as blobs), zoom and filter (a team, a landmark), details on demand (one agent's trail and evidence). The same mantra as the Brief, in space. | One representation that works at 20 agents and at 5,000. | Shneiderman 1996 |
| **A shared referent.** The human and the copilot can point: "those three near the benchmark file", "the group that just split". Deixis is how people talk about scenes; a dashboard has no "there". | Faster, less ambiguous human–AI conversation; selection as a scope. | Clark, common ground; HCI work on shared visual context |
| **Coverage made visible.** Regions nobody has read closely are rendered hazy; analysts' reading lights regions up. A false sense of coverage, the biggest failure mode of swarm oversight, becomes a visible fog. | Honest uncertainty, in the same frame as the findings. | Thimble's "a claim is not a fact"; our coverage ledger |
| **Explanation of findings.** A finding is a sentence; the World shows its *context*: who else is nearby, what else the crowd touched, whether the convergence came from one team or many. | Faster triage of grouped findings. | |

### 1.2 Falsifiable hypotheses (what we will measure before calling it useful)

- **H1 Separability.** On the planted swarm, agents carrying a planted behaviour are spatially separable from
  their cohort at the time the behaviour is active: silhouette score of planted vs non-planted positions > 0.3,
  and the gap opens before the watcher fires in at least 3 of 5 behaviours.
- **H2 Time to notice.** Persona testers shown the World (no attention list) spot the convergence and the drift
  faster than testers shown the Brief alone; and the two together beat either. Measured in seconds, three testers
  each, both orders.
- **H3 No pareidolia.** On a null swarm (same generator, no planted behaviours, shuffled teams), testers report at
  most one "something is wrong" per ten minutes, and the World's own derived signals fire at the configured false
  positive rate (≤ 5% of windows).
- **H4 Grounding.** Every visible encoding has a legend entry and a click target that opens evidence; a tester can
  explain what each of position, size, colour, glow, trail and fog means after one minute with the legend.
- **H6 Inference honesty.** On the planted swarm, where task and state are known, the analysts' inferred cohort
  labels agree with the planted truth at least 80% of the time at confidence ≥ 0.6, and the World never shows an
  inferred feature as solid. On a stripped stream (`actor` + `action` only) the World still renders, with the
  legend listing what is unknown.
- **H5 Feedback value.** Adding the spatial features (isolation, drift velocity, crowding) as inputs to triage raises
  recall-at-budget on the planted swarm without raising the audit lane's false positive rate.

If H1 or H3 fails, the layout model is wrong and the project stops at a prototype. If H2 fails but H1 holds, the
rendering is wrong, not the idea.

### 1.3 What it must never be

- Decoration. No encoding without a measured quantity behind it; no quantity without a legend.
- A text leak. Agent-written text never appears in the World; speech is shown as *that something was said*, with
  its shape class if anything (the template id), never its words. Same evidence boundary as everywhere else.
- A second truth. The World reads the same store, cohorts, findings and coverage as the Brief; it adds derived
  spatial features as DERIVED claims with event evidence, never as facts.
- A substitute for the Brief. The Brief says what to do; the World shows why and where. Findings link to places;
  places link to findings.

## 2. What we actually have: we observe, we do not instrument

SwarmFrame is a monitoring layer at the end of someone else's pipeline. We do not control the agents, we did not
write their logging, and for most sources we cannot ask them anything. Everything the World shows has to be
**recovered from whatever events arrive**, and the events differ by source:

| Source | What arrives | What is missing |
|---|---|---|
| Planted swarm, planted village | actor, action, resource, family, team, text fingerprint, operator events | nothing (we generated it; this is the easy case and must not fool us) |
| Live Claude Code (hooks) | actor, tool name, file, timestamps, permission results; control plane | task intent, who is talking to whom, whether a tool call "worked" |
| AI Village | chat messages with rooms, computer-use session goals, screenshots as text | per-action structure; interactions only implicit in chat |
| Any JSON stream | whatever the sender chose; often just `actor` and `action`, sometimes only `text` | most of the above; even the notion of "resource" may have to be inferred |
| Transluce | target, method, time, grade | identities, interactions, states |

So the World cannot be designed as if agent state, task and interactions were fields. They are **features we
estimate**, with three grades, exactly the epistemic statuses the rest of SwarmFrame already uses:

- **Observed** when the stream states it (an operator `stop` event; a file path on a tool call).
- **Derived** when code computes it from observed events (activity rate; co-touching a file within a window; a
  reply that follows a message in the same room within a minute).
- **Inferred** when a model has to read structure or samples to say it (what a group of agents is working on; whether
  two agents are collaborating or competing; whether a message is a status report or a request; whether a run of
  errors means "blocked").

The World draws all three, and draws them differently (§2.3). It never fabricates a feature the stream cannot
support: the encoding is dropped and the legend says so.

### 2.1 The agent-feature layer (new)

A `world/features/` layer sits between the store and the layout. For each unit and window it produces a fixed
**feature vector**, with a status and evidence for every field:

| Feature | Observed when | Derived when | Inferred when (model) |
|---|---|---|---|
| **activity** (rate, burstiness) | — | always, from event timestamps | — |
| **behaviour signature** (mix of families, actions, resources, message shapes) | — | always; this is the scale layer's `Profile`, which exists for any stream with `actor` + `action` | if the stream has only free text, a model classifies *message shapes* (templates) into a small action vocabulary from masked samples |
| **state** (idle / working / talking / blocked / paused / stopped) | control plane status; operator events | idle and talking from rate and message events; blocked from error-like actions | "blocked" and "working on X" from samples of recent messages, read through `read_raw` by a division analyst, never by the Executive |
| **task / intent** (what it is doing) | a stated goal event (village goals) | — | a one-line label per **cohort**, written by a division analyst from message shapes and resource names; members inherit it; outliers and triage picks get their own |
| **interactions** (who to whom) | explicit reply / mention fields | co-touching a resource within a window; same-room reply within a minute; lineage exposure (A posted, B reused) | "A is responding to B" from samples when the stream has rooms but no reply structure (the village) |
| **group** | `group` / team field | model-family or host as a proxy | a model proposes groupings from behaviour when nothing is given, flagged as inferred |
| **resource kinds** (what is a file, a host, a channel) | `family` field | path and URL shape | a model names the kinds from the profile's top values when the stream gives none |

Rules:
- The **layout uses derived features only** (signature, activity, derived interactions). Positions are therefore
  reproducible with models off, on any stream with `actor` and `action`. Inferred features colour, label and
  annotate; they never move an agent. This keeps the map deterministic and the inference auditable.
- Inference runs at **cohort granularity**, not per agent: one label for a group of similar agents, propagated to
  members, and individual reads only for outliers and triage picks. This is what makes it affordable at 5,000
  agents and it is the same budget the triage tree already enforces.
- Inferred features are **claims**, with the sampled events as evidence, so the verifier can downgrade them and the
  World can show when a label is stale or contested.
- In models-off mode the inferred row is simply empty: cohorts are labelled by their signature ("shell · team-07"),
  states are the derived three (idle, active, talking), and the legend says what is not known.

### 2.2 Who infers

The agent organisation already exists; the World adds tasks to it rather than a new model loop:
- **Division analysts** label their cohorts' task and state each cycle (one extra field in the report contract:
  `cohort_labels: [{cohort, task, state, confidence}]`), and name the resource kinds for streams that lack them.
- **The capability inference** for linked streams (`infer_capabilities`) is extended to propose the actor, action
  and resource mapping when a stream's events do not use our field names, with a model's help once, confirmed by
  the person on the compose screen ("Looks like `agent_id` is your actor and `tool` is your action. Right?").
- **The world-designer** (§7) consumes the feature layer's *availability* table to decide what can be encoded.

### 2.3 Drawing uncertainty

The World must never look more certain than the data:
- Observed: solid. Derived: solid, with the derivation on hover. **Inferred: translucent or hatched, with a small
  dot that opens the claim** and its samples' structure (never their text). Stale inferences fade.
- Every tooltip shows the status word. The legend lists which encodings are inferred on this stream.
- A cohort label with low confidence is shown as "probably: refactoring the parser" and nothing stronger.

### 2.4 Control, where it exists

Control is a capability, not a given. Only the live Claude Code source has a control plane; everywhere else the
World is read-only and says so. Where control exists, the World exposes the same actions as the Control page
(pause, interrupt, message, stop) with the same approval rules; where it does not, the "operator beam" shows only
operator actions the stream itself reports, and a click offers "watch", "investigate" and "ask", never "pause".

## 2b. What the World encodes

Every row below is a measured quantity with a status (§2). The legend is generated from this table, so the two
cannot drift apart.

| Visual | Quantity | Status | Source | Notes |
|---|---|---|---|---|
| **Position** (x, z) | Behavioural and interactional similarity | derived | signature (`Profile`), derived interactions, cohorts | §3. Legend: "distance = how differently they behave and how little they interact". Never uses inferred features. |
| **Height** (y) | Activity vs the agent's own usual | derived | `Profile.rate`, z-score | Capped. |
| **Colour** | Dominant workstream family | derived (inferred when families were model-named) | `Profile.dominant`, fixed palette | Never rank, never severity. |
| **Pose** | idle / active / talking (derived); working / blocked / paused / stopped (observed or inferred) | mixed | rate, message events; control plane; analyst labels | Only the states the stream supports are used. |
| **Cohort label** | What the group is doing | inferred (or signature text when models are off) | division analysts' `cohort_labels` | Translucent banner over the cohort; "probably:" below confidence 0.6. |
| **Severity ring** | ACT / LOOK / WATCH of the finding the agent is in | derived | Brief digest | Same words and colours as the Brief. |
| **Trail** | Displacement over N windows | derived | position history | Long trail = behaviour changed. |
| **Interaction arcs** (near zoom) | who to whom this window | derived (inferred arcs hatched) | co-touch, replies, exposure; analyst-inferred replies | |
| **Landmark size / heat** | Resource activity; distinct agents vs usual | derived | events by object; convergence and burst baselines | A red crowd ring is exactly a convergence observation. |
| **Team territory** | Group membership | observed (inferred when proposed) | `Entity.group` | Soft ground tint; weak attractor. |
| **Fog** | Not read closely | derived | coverage ledger | Reading clears fog for a few windows. |
| **Speech bubble** | A message was sent (shape class only) | derived | message events, templates | Flickers for say-do candidates: talking, not moving. |
| **Operator beam** | Operator or environment action | observed | environment events; control plane | Only when the stream reports it. |
| **Analyst lanterns** (later) | Where the analyst team is reading | derived | triage picks, assignments | |

Deliberately not encoded: anything from agent text; model name as colour (a filter, not a colour); any "health
score" that is not one of the measured quantities above; any feature the stream cannot support.

## 3. The layout model (the part that has to be right)

### 3.1 Requirements

1. **Position means something and the legend can say what.** Not a pretty force-directed hairball.
0. **Positions use derived features only** (§2.1), so the map is the same with models on or off and on any stream
   with `actor` and `action`. Inferred features label and colour; they never move anything.
2. **Stable.** Same data, same positions (seeded, deterministic). Nothing jitters. A still swarm is a still scene.
3. **Motion = behaviour change.** Bounded step per window, so speed itself is readable (fast = changed a lot).
4. **Identity continuity.** An agent keeps its place unless its behaviour or interactions change; new agents spawn
   at their team's gate and walk in.
5. **Scales to 5,000 units at window cadence** (≤ 50 ms per window in Python with numpy, or ≤ 200 ms for 5,000).
6. **Works without identities** (Transluce): the unit becomes the target and the metric changes (see §6).

### 3.2 Two-level embedding

**Level 1: cohort anchors (deterministic).** Each cohort has a signature (dominant family, action, group). Anchors
are placed on a stable plane by signature: families as angular sectors (the family palette's fixed order gives the
sector order), teams as radial bands within a sector, so "shell agents of team-07" always sit in the same general
region across runs and sources. Cohorts that merge or split keep their region. This is what makes the map learnable.

**Level 2: agents within and between anchors (incremental forces).** Per window, for each active agent *i*:

```
x_i ← x_i + η · clamp( F_anchor + F_landmark + F_interact + F_similar + F_repel , max_step )
```

- `F_anchor`: spring to the agent's cohort anchor (keeps the map legible; weak).
- `F_landmark`: attraction to the landmarks it touched this window, weighted by events (this is what makes a
  convergence a visible crowd: the file pulls them in).
- `F_interact`: attraction along interaction edges: chat replies / mentions, co-touching the same resource within the
  window, lineage exposure (A posted, B reused after seeing it). Weights decay over windows.
- `F_similar`: attraction to the k nearest by behavioural signature (1 − TV distance of family mix, template overlap),
  computed against cohort members only, O(n·k).
- `F_repel`: short-range repulsion between agents (readability) and from landmark cores, approximated at cohort level
  (Barnes–Hut lite: agents repel from other cohorts' centroids, not from every agent).
- `max_step` bounds speed; `η` is small; inactive agents do not move (they dim instead).

Landmarks are placed at the barycentre of the agents that use them, damped, so a shared file sits between the teams
that share it, and a file that one team owns sits inside that team's territory. A landmark that starts drawing a
crowd from several sectors physically moves toward the middle, which is itself informative.

### 3.3 Derived spatial features (what feeds back)

Computed per window from positions and used in §5:

| Feature | Definition | Reads as |
|---|---|---|
| `isolation(i)` | distance to k-th nearest neighbour, normalised by cohort spread | an agent nobody is like, or near |
| `drift(i)` | displacement over the last N windows, normalised | behaviour changing |
| `cohort_spread(c)`, `cohort_split(c)` | spread; bimodality of member positions | a group coming apart |
| `crowding(r)` | agents within radius of landmark *r* vs its usual | convergence, burst |
| `approach(i, j)` | two agents (or an agent and a landmark) closing distance over N windows | coordination forming |
| `stillness(i)` while `speech(i)` | no displacement, many messages | say-do candidate |
| `coverage_fog(c)` | windows since an analyst read cohort *c* | unread region |

Each feature becomes a DERIVED claim with the events that moved the agent as evidence, so it can be verified and
can be wrong in the open.

### 3.4 Null model

The same layout run on a shuffled swarm (actors permuted within windows) gives the baseline distribution of every
feature. A feature only glows when it exceeds its null quantile. This is the defence against pareidolia (H3), and it
is cheap: the null layout runs on the first N windows at session start.

## 4. Default assets (never redesigned) and the world vocabulary (chosen per stream)

### 4.1 Fixed: the agent sprite set

One agent model, procedurally generated (no art pipeline), low-poly, billboarded at distance and instanced:
a rounded body with a face plate, tinted by family colour, with six states (idle, working, talking, blocked,
paused, stopped) as small deterministic animations (bob, hammer, bubble, cross-arms, sit, lie down). Size and
height are driven by data. Severity ring, trail and speech bubble are attachments. Identity-free units (targets)
use a second fixed model: a plinth whose height is activity and whose cap colour is method family.

### 4.2 Fixed: default world elements

Ground plane with faint grid and soft team territories; fog layer; four landmark archetypes (file = slab, host =
tower, channel = plaza with a hearth, board = kiosk); a gate per team where new agents appear; a horizon ring
that holds the legend; a light that follows the replay clock (time of day is literal).

### 4.3 Chosen by the designer: the vocabulary and the scene

The world-designer agent chooses, for a particular stream: which resource kinds become which landmark archetype;
whether teams or families are the territories; what the camera's opening shot is; which scenes exist ("the crowd
at the benchmark file", "team-07 drifting"); any stream-specific element it can justify (a Transluce world might
make methods into roads between target plinths). It may propose a *new* landmark archetype only as a composition
of primitives (box, cylinder, cone, slab, ring, beam) with a stated meaning; it cannot upload meshes or textures.

## 5. The feedback loop: the World as a shared instrument

1. **World → analysts.** The derived features (§3.3) are evidence tools: `world_features(scope)` returns isolation,
   drift, crowding and approach for a cohort, agent or landmark, with evidence. The triage priority gains a small
   `spatial` component (drift and isolation above null). A `SpatialDrift` watcher emits observations when a cohort
   splits or an agent isolates, with the moving events as evidence.
2. **World → Brief.** Findings carry a `place` (positions and a camera preset); the attention row gets a small
   "Show me" that flies the camera there. The Brief's status may add one spatial sentence when a feature is far
   above null ("team-07 has been drifting away from the rest for 3 hours").
3. **Human → copilot through the World.** Lasso or click a region: the selection becomes a scope ("agent:…",
   "cohort:…", or an ad hoc set), and "Ask about these" opens the copilot with that scope. Deixis.
4. **Copilot → World.** The copilot can place pins and annotations, set camera presets, and highlight a set
   ("the five I mean are these"). Annotations are versioned like dashboard ops.
5. **Control (live swarms).** Click an agent → the control actions (pause, interrupt, message, stop) from the
   World, with the same approval rules as the Control page. The operator beam shows the result.

## 6. Which dataset first

| Dataset | Agents | Identities | Interaction signal | Planted truth | Verdict |
|---|---|---|---|---|---|
| **Planted swarm at scale** | 500–5,000 in 26 teams | yes | shared files, hosts, chat, exposure edges, operator stops | yes: spread, surge, drift, say-do, operator | **Build here first.** It is the only dataset where H1 and H3 can be measured, the only one with enough agents for semantic zoom to matter, and all five planted behaviours have a spatial reading (crowd at a landmark; a wave; a team migrating; still agents with speech bubbles; agents frozen by a beam). |
| **Live Claude Code swarm** | 20–2,000 (simulated) | yes | files, tools, operator actions, control | partly (simulator schedule) | **Second.** The World plus control is the demo that is hard to do any other way: click the agent that is running `pip install …` and pause it. |
| **AI Village (real)** | ~21 | yes | chat rooms, shared docs, computer use | no | **Showpiece for real data, third.** Small enough that every agent is a character with a trail; chat makes the plaza come alive; say-do mismatches are real. Too small to stress the layout. |
| **Planted village** | ~20 | yes | same shape | yes | Regression test for the small-scale reading. |
| **Transluce** | 0 (reports) | no | targets × methods × time | no | **Different world, later.** No agents to move. A targets map: plinths for targets, roads for methods, bursts as height spikes. Interesting but not the agent-sprite idea; keep it as the identity-free variant that proves the design generalises. |

So: planted swarm for building and validating; live Claude Code for the control story; the village for the human
story. The composer picks the variant from capabilities exactly as the dashboard composer does today.

## 6b. Dynamic by construction, with presets as worked examples

Different streams carry different information, so **there is no fixed World**. There is a composition process
(§7) that reads the feature availability table (§2.1) and produces a `WorldSpec` for *this* stream, exactly as the
dashboard composer produces pages for it. Three layers, mirroring the dashboard:

| Layer | What it is | Who writes it | When |
|---|---|---|---|
| **Defaults** | The fixed assets and encodings (§4, §2b). Always available; what can be shown depends only on the feature table. | us, once | build time |
| **Presets** | `packs/<id>/world.yaml`: a complete `WorldSpec` for a source we know, hand-tuned, with a `reason` on every choice. Loaded first, editable, resettable, exactly like `dashboard.yaml`. | us, per shipped source | pack |
| **Composition** | For a stream without a preset (a linked JSON stream, a new pack) the composer (free, or the world-designer with models on) reasons from the feature table to a `WorldSpec`. With a preset present, composition only fills gaps and may propose scenes. | the composer, at compose time; the person, from Edit | compose mode, step 5 |

The presets also serve as **the skill's worked examples**: the world-designer's reference folder carries the
village, Transluce and German Wiki presets with their reasons, so a new stream is designed by analogy to the
nearest known shape (named agents in rooms; identity-free targets; partial-identity handles on shared pages)
rather than from nothing.

### Preset 1: AI Village (`packs/ai_village/world.yaml`)

| | |
|---|---|
| Unit | agent sprite; ~21 named agents, stable identities |
| Metric | "distance = who talks where and works on what": rooms and shared docs dominate, behaviour signature second |
| Landmarks | chat rooms → plazas (the social centres of this world); shared docs and sheets → slabs; external sites → towers at the edge |
| Territories | none (one village); model family available as a filter, never a colour |
| Encodings | position, height, colour (workstream), pose (idle / active / talking derived; working and blocked inferred from goals and messages), cohort label (inferred, from analysts), severity ring, trail, speech bubbles, interaction arcs (derived replies: same room within a minute; inferred replies hatched), fog |
| Control | none; read-only |
| Scenes | **The village square** (opening; everyone, plazas lit by message volume); **Who is saying and not doing** (agents with bubbles and no displacement, the say-do question); **Shared documents** (slabs with crowd rings); **One agent's day** (follow a sprite with its trail) |
| Why it is a good preset | small enough that every agent is a character; chat makes the plazas live; the say-do mismatch is real and visible as a still, talking sprite |

### Preset 2: Transluce (`packs/transluce/world.yaml`)

| | |
|---|---|
| Unit | **plinth** (target), not a sprite: there are no agents to move |
| Metric | "distance = targets scanned by the same methods in the same weeks" (co-targeting) |
| Landmarks | method classes → roads radiating from a centre; targets stand along the roads they are reached by; a target reached by several methods sits at a junction |
| Territories | target domain category if the catalog gives one; otherwise none |
| Encodings | plinth height = reports this week vs the target's usual (burst = a spike); cap colour = dominant method; grade = plinth material (significant solid, suggestive translucent: the catalog's own confidence, drawn as certainty); first-time-method = a new road reaching a plinth; fog = targets no analyst has read |
| Control | none |
| Scenes | **The map of targets** (opening); **This week's bursts** (camera to the tallest plinths); **New methods** (roads that appeared recently); **Grades over time** (a timeline sweep where plinths rise and fall) |
| Why it is a good preset | proves the design is not "agent sprites or nothing": the same encodings and legend discipline on a stream with no identities |

### Preset 3: German Wiki (`packs/german_wiki/world.yaml`) — depends on reviving the adapter

The source is parked in `sources/_later/german_wiki.py` and its export format is unconfirmed; the preset is
designed against the documented shape (about 3.1k handles, 4.6k pages, 14.6k revisions, a surge on shared question
pages in mid-June, text blocks propagating between handles, moderator deletion sweeps). Reviving it is a
prerequisite: `swarmscope probe <export>`, fix the adapter, pack with `identities: partial`.

| | |
|---|---|
| Unit | agent sprite, **drawn translucent by default** because identity is partial (a handle is not a stable agent); merged handles (alias watcher) share a tether |
| Metric | "distance = who edits the same pages and reuses the same text" (co-editing and lineage dominate; signature second) |
| Landmarks | pages → slabs, grouped by namespace into districts; question pages (the convergence targets) → larger slabs in a central square; external URLs cited in bodies → towers at the edge |
| Territories | handle groups, **inferred** (behavioural grouping proposed by analysts, hatched ground tint), since the data has no teams |
| Encodings | position, height (edits vs usual), colour (edit family: create / expand / revert / cite), pose (active / idle derived; blocked = recently deleted-upon), severity ring, trail, **lineage arcs** (text reuse with or without observed exposure, solid vs dashed, straight from the propagation watcher), **operator beams** = moderator deletion sweeps (observed), fog |
| Control | none; the moderators are the environment, not us |
| Scenes | **The wiki** (opening: districts, the central square); **The June surge** (time sweep; separate groups converging on the question pages); **Where the text came from** (lineage arcs lit); **After the sweeps** (displacement of handles after deletions) |
| Why it is a good preset | the richest *spatial* story we have in real data: separate groups converging on shared pages, propagation with and without exposure, and an environment that pushes back; and it exercises partial identity, which neither the village nor the planted swarm does |

### Presets 4 and 5 (already covered)

The **planted swarm** preset is the development and validation target (§6); the **live Claude Code** preset is the
village shape plus control (files as slabs, tools as colour, approvals as beams, the control menu on click).

### Composition for an unknown stream (no preset)

The composer maps the stream to the nearest preset shape from the feature table and adapts:

| Feature table says | Nearest shape | What changes |
|---|---|---|
| stable identities, resources, chat | village / Claude Code | rooms or files as the main landmarks depending on which carries more interaction |
| stable identities, resources, no chat | planted swarm | no bubbles, no reply arcs; co-touch and signature carry the metric |
| partial identities | German Wiki | translucent sprites, alias tethers, inferred territories |
| no identities, resources | Transluce | plinths; co-targeting metric |
| actor and action only | planted swarm, stripped | position from signature alone; one landmark archetype for inferred resource kinds, or none; legend lists what is unknown |
| text only | — | the composer asks for an actor field before composing; the World cannot run on text alone |

The free composer applies this table deterministically; the world-designer reasons from the same table but may
justify a different shape, and must say why.

### Where it sits in compose mode

Compose mode gains a fifth step after the dashboard is composed: **"Laying out the world"**, which loads the preset
when one exists, otherwise composes, then shows the chosen metric sentence and the encodings that are unavailable
on this stream ("No chat in this stream, so no speech bubbles or reply arcs"). The World is a page in the Default
lens; a lens can carry its own scenes.

## 7. The world-designer skill (`.claude/skills/world-designer/`)

A reasoning procedure, run once at compose time and again on request, producing a `WorldSpec`. It must reason, not
decorate, so each step has a required written output that the critic step checks.

1. **Survey.** Read `stream_profile` and the **feature availability table** (`world_features_available`): for each
   World feature, whether this stream gives it observed, derived, inferred, or not at all. Write: *what is an actor
   here, what is a place, what is an act, what is a group*, and *which features are missing*. Where the stream's
   fields do not match ours, propose the mapping (actor, action, resource) and the questions to ask the person.
2. **Metric.** Decide what distance should mean for this stream and why: for a coding swarm, shared files and
   exposure; for a village, rooms and replies; for Transluce, co-targeting within a week. Write the metric in one
   sentence that will become the legend.
3. **Vocabulary.** Map resource kinds to landmark archetypes; decide territories (team or family); decide the unit
   model (agent sprite or plinth). Write a reason per mapping.
4. **Encodings.** Confirm the fixed encodings apply; **drop any whose feature is unavailable** (no chat, no
   bubbles; no control, no pause pose); mark which are inferred so they draw translucent; add at most one
   stream-specific encoding, with its quantity, status and legend text.
5. **Scenes.** The opening shot (what a newcomer should see first) and up to four named scenes with camera presets
   and the question each answers ("Is anyone converging on a shared file?"). Scenes may be tied to findings kinds.
6. **Motion rules.** Choose the force weights within allowed ranges (landmark vs interaction vs similarity) and the
   trail length, with a reason tied to the time scale of the data.
7. **Critic.** Check against the rules: every encoding has a quantity, a status and a legend; no encoding rests on
   a feature the stream lacks; inferred features never move agents; nothing shows text; nothing is ranked by
   colour; the null model is on; the opening shot shows the overview, not a close-up; identity-free streams use the
   plinth variant; control affordances only where the control capability exists. Rewrite until it passes.

Tools: `stream_profile`, `world_features_available` (the availability table with statuses), `world_catalog`
(archetypes, encodings, primitives, allowed ranges), `world_preview`
(runs the layout on the data so far and returns separability, spread, crowding and null-model statistics, plus a
rendered thumbnail), `world_edit` (ops on the WorldSpec, validated and versioned like dashboard ops),
`world_undo`. In models-off mode, a free composer applies the same procedure with fixed rules.

## 8. WorldSpec (what the designer produces, what the human edits)

```yaml
unit: agent | target
metric: "distance = how differently they behave and how little they interact"
territories: group | family | none
landmarks:
  - {match: {kind: resource, group: files}, archetype: slab, label: "file"}
  - {match: {kind: resource, group: web},   archetype: tower, label: "host"}
  - {match: {kind: resource, group: chat},  archetype: plaza, label: "channel"}
features:               # what this stream supports, written by the survey; the legend and the critic read it
  state: {available: [idle, active, talking], inferred: [blocked, working]}
  interactions: {derived: [co_touch, exposure], inferred: [reply]}
  task: inferred           # cohort labels from division analysts; absent with models off
  control: false
encodings: [position, height, colour, pose, cohort_label, severity_ring, trail, landmark_heat, fog, speech]
forces: {anchor: 0.3, landmark: 1.0, interact: 0.8, similar: 0.5, repel: 0.6, max_step: 0.08, trail_windows: 12}
scenes:
  - {id: overview, title: "The whole swarm", camera: {...}, question: "Is anything out of shape?"}
  - {id: crowds, title: "Crowded files", camera: {...}, follow: "top_crowding_landmark", question: "Who is converging, and from which teams?"}
annotations: []        # pins placed by people or the copilot, versioned
null_model: true
```

The WorldSpec lives beside the DashboardSpec in each lens (a lens can have its own World), with the same ops,
history and undo, and the same "any edit from the Edit menu, from chat, or from the designer" rule.

## 9. Architecture

**Backend `backend/swarmscope/world/`**
- `layout.py`: the two-level embedding (§3.2), numpy, incremental per window; positions kept per unit with a
  short history; cohort anchors from the scale layer; landmarks from the top-K resources plus aggregates.
- `features/`: the agent-feature layer (§2.1). `derived.py` (activity, signature, derived states and interactions,
  always on), `inferred.py` (cohort task and state labels, inferred replies and groupings, read from the division
  analysts' reports and stored as claims), `availability.py` (the per-stream table the designer and the legend
  read), `spatial.py` (§3.3 features and the null model; `SpatialDrift` watcher in `org/watchers.py`).
- Report contract: division analysts gain `cohort_labels` (task, state, confidence, sampled evidence); the
  deterministic analyst fills it from signatures when models are off.
- `infer_capabilities` (generic streams) gains a model-assisted field-mapping proposal, confirmed on the compose
  screen before it is used.
- `spec.py`: `WorldSpec`, validation, ops, `preset_world(engine)` from `packs/<id>/world.yaml` (like
  `builtin_spec`), `default_world(engine)` composed from the feature table when there is no preset, catalog.
- `designer.py`: the free composer and the Claude designer run (mirrors `dashboard/designer.py`).
- API: `GET /api/world/state` (positions, landmarks, features for the current window, as compact arrays),
  `GET /api/world/history?unit=` (trail), `POST /api/world/ops`, `/undo`, `/preview`, `/design`,
  `POST /api/world/select` (a selection → scope for the copilot). Snapshot adds `world_version`; the WebSocket
  pushes a compact `world` delta per window (ids, xyz as float32 arrays, state codes) so 5,000 units cost ~100 KB.
- Evidence tools: `world_features`, `world_scene` (what is visible in a scene, structure only) for analysts and copilot.

**Frontend `frontend/src/world/`**
- `three` + `@react-three/fiber` + `@react-three/drei` (new dependencies). One `InstancedMesh` per sprite state,
  colour and height per instance; landmarks as instanced primitives; trails as line segments from a ring buffer;
  fog as a ground-level alpha texture painted from coverage. A web worker interpolates between window states so
  motion is smooth at any replay speed.
- Semantic zoom: far = cohort blobs with counts and flow arcs; mid = sprites; near = labels (ids, not text),
  trails, bubbles. Hover = tooltip with the measured quantities; click = the existing drawers (entity, finding).
- `WorldPage` is a page kind (`kind: world`) that any lens can hold; a `world` panel (span 12) can also sit on the
  Brief or any page. Scenes are tabs in the page header; the legend is a drawer generated from the encoding table.
- Selection: lasso on the ground plane; "Ask about these" opens the copilot with the scope.

**Performance budgets.** Layout ≤ 50 ms per window at 2,000 units, ≤ 200 ms at 5,000 (numpy, vectorised,
cohort-level repulsion). Render 60 fps at 5,000 instances on an integrated GPU; LOD drops to blobs above 2,000
visible. State delta ≤ 150 KB per window.

## 10. Validation plan

1. **Spike (before anything else).** Run the layout offline on a 2,000-agent planted replay, no rendering. Measure
   H1 separability per planted behaviour over time, and the null model's feature distributions. Plot positions as
   2D scatter PNGs per window (matplotlib, for us only). Decision gate: proceed only if H1 holds for ≥ 3 behaviours.
2. **Instrumented replay.** Record, per window, the first window at which each planted behaviour (a) exceeds the
   null in a spatial feature, (b) is observed by a watcher, (c) is surfaced in the Brief. Report minutes to each.
3. **Persona tests.** The three personas again, two conditions (Brief only; Brief + World), H2 and H4.
4. **Null test.** The same personas on the null swarm, H3.
5. **Scale test.** 5,000 agents, measure layout time, frame rate, delta size.
6. **Feedback test.** Triage recall-at-budget with and without the spatial component, H5.

## 11. Risks and how the design answers them

| Risk | Answer |
|---|---|
| Pretty but meaningless (decoration) | The encoding table *is* the legend; the critic step refuses unmeasured encodings; the null model gates glow. |
| Pareidolia: people see patterns in noise | Null model; features glow only above null; the persona null test. |
| Motion sickness / churn | Bounded step; inactive agents do not move; damping; a pause button stops motion but not data. |
| Hairball at scale | Two-level embedding with deterministic anchors; cohort blobs when zoomed out; repulsion at cohort level. |
| Text leak through labels or bubbles | Labels are ids and template ids; bubbles carry shape only; the same `read_raw` gate applies to tooltips (none). |
| The World and the Brief disagree | Both read the same store and digests; features are DERIVED claims that the verifier can downgrade. |
| Designer invents a "cool" world the data cannot support | Allowed ranges and archetype compositions only; `world_preview` must show the chosen metric separates something. |
| Identity-free data has no agents | The plinth variant with a different metric; chosen by capabilities, never by hand. |
| We do not control the agents and the stream is whatever it is | The feature layer grades every feature observed / derived / inferred and drops what is missing; positions use derived features only, so the map works on `actor` + `action` alone; control appears only with the control capability. |
| Inference is wrong or stale | Inferred features are claims with evidence; drawn translucent; the verifier can downgrade them; labels fade when not refreshed; cohort-level inference keeps the number of claims small enough to audit. |
| Inference is expensive at scale | Cohort granularity (tens to hundreds of labels, not thousands), inside the triage tree's existing budget; derived features carry everything else. |
| Cost | Layout is numpy, no model calls; the designer runs once per compose like the dashboard designer. |

## 12. Phases

- **Phase W0 — Spike (gate).** `world/layout.py` + `features.py` offline on the planted swarm; separability and
  null-model report; 2D scatter frames. No UI. Decide go/no-go on H1 and H3.
- **Phase W0b — Feature layer.** `features/derived.py` and `availability.py` on all six sources; a table per
  source of what is observed, derived, inferred or absent; the layout confirmed to run on `actor` + `action` alone
  (a stripped JSON stream). Gate: the planted swarm's results from W0 are unchanged when inferred features are off.
- **Phase W1 — World core.** API, WebSocket delta, three.js renderer with the fixed sprite set and default
  elements, semantic zoom, hover/click to drawers, legend generated from the encoding table with statuses,
  uncertainty styling, replay-smooth motion. Planted swarm only.
- **Phase W2 — Designer and inference.** `WorldSpec`, ops, the world-designer skill, free composer,
  `world_preview`, scenes, the World as a page kind and panel inside lenses; identity-free plinth variant for
  Transluce. `cohort_labels` in the analyst report contract; `inferred.py`; model-assisted field mapping for linked
  streams with confirmation on the compose screen. Tested with the usual cheap Sonnet runs, few and small.
- **Phase W3 — Feedback loop.** Spatial features as DERIVED claims; `SpatialDrift` watcher; `world_features` tool;
  triage spatial component; findings carry places; "Show me" from the attention list; lasso → copilot scope;
  copilot pins and camera presets.
- **Phase W4 — Live control.** Claude Code swarm: agent click → control actions; operator beams; approval flow.
- **Phase W5 — Validation.** Instrumented replay, persona tests in both conditions, null test, scale test, H5.
- **Phase W6 — Presets.** `world.yaml` for the village and Transluce (§6b), the compose-mode step, the skill's
  worked examples; analyst lanterns, light by time of day.
- **Phase W7 — German Wiki.** Probe the export, revive the adapter, pack with partial identities, then its preset:
  districts, the June surge sweep, lineage arcs, moderator beams.

Dependencies to add: `numpy` (backend), `three`, `@react-three/fiber`, `@react-three/drei` (frontend).

## 13. Open questions (to decide during W0/W1)

- 3D or 2.5D? The spike will tell: if height carries activity well and the ground plane carries the metric, an
  isometric 2.5D camera may read better than free 3D. The design above works for either.
- Should landmarks move (barycentre) or stay fixed? Moving landmarks make convergence legible but weaken spatial
  memory. Proposal: move slowly, with a ghost at the previous position.
- How much of the layout runs on the client? Backend-only keeps one truth and lets analysts use the same features;
  the client only interpolates. Keep it backend-only unless latency bites.
- Lenses: one World per lens, or one World per source with per-lens scenes? Start with one per source, scenes per
  lens.
- Transluce's method roads: do they read, or is a plain co-targeting layout with method colour enough? Decide
  from `world_preview` statistics, not taste.
- German Wiki's export format, and whether handle→IP joins are allowed (identity is partial on purpose; we must not
  manufacture identities the data does not support).


---

# Part II. Definitions

Part I is the argument; this part is the contract. Everything the World can show is defined here, and the designer
agent can only combine what is defined here. New visual vocabulary is added to this part by us, never by an agent.

## 14. The primitive library (premade; the designer composes first, and makes models when it must, §14.7)

All geometry is procedural (generated in code from parameters), so there is no art pipeline, every instance can be
driven by data, and the designer cannot upload or invent meshes. Every primitive has: an id, what it stands for,
the data it binds to, its parameter ranges, how it behaves at each zoom level, and what it may not be used for.

### 14.1 Unit models (one per unit; the designer picks exactly one)

| id | Stands for | Geometry | Data-bound parameters | Zoom | Must not |
|---|---|---|---|---|---|
| `sprite` | an agent with a stable identity | rounded capsule body, face plate, two stubby feet; billboarded beyond mid zoom | `tint` (family colour), `height` (0.6–1.8, activity), `state` (one of six), `alpha` (1.0 observed identity, 0.55 partial), `ring` (none / WATCH / LOOK / ACT) | far: merged into cohort blob; mid: body + ring; near: + label, trail, bubble, arcs | be coloured by severity or model; be scaled by anything but activity |
| `plinth` | a unit without identity (a target, a page, a host) when the unit is a place rather than an actor | square column with a cap | `height` (0.4–3.0, volume vs usual), `cap_tint` (dominant method or family), `material` (solid / translucent: the source's own confidence grade), `ring` | far: district blob; mid: column; near: + label, arcs | have a pose; move (plinths are placed, not walked) |
| `ghost` | a unit that has gone quiet or whose identity merged into another | the sprite at alpha 0.25, no feet | `since` (windows since last event) | mid and near only | carry a ring (quiet units are not findings) |

**Sprite states** (fixed set; each is a short looping animation, 1–2 s, deterministic from the unit id so a crowd
does not move in lockstep):

| state | Meaning | Derivable from | Observed from |
|---|---|---|---|
| `idle` | no events this window | rate = 0 | — |
| `active` | events, no finer knowledge | rate > 0 | — |
| `talking` | sent a message this window | message-family events | — |
| `working` | acting on a resource (editing, running, writing) | — (inferred: analyst label) | tool/resource actions when the stream distinguishes them |
| `blocked` | errors, denials, retries | error-like actions ≥ 3 in window (derived, weak) | denial / permission events |
| `paused` / `stopped` | held or terminated by an operator | — | control plane status; operator events |

A state the stream cannot support is never shown; `active` is the floor.

### 14.2 Attachments (zero or more per unit, each bound to one quantity)

| id | Geometry | Binds to | Status allowed | Notes |
|---|---|---|---|---|
| `ring` | flat ring at the feet, colour and pulse by severity | finding severity of the unit's scope | derived | ACT pulses; LOOK steady; WATCH thin, no pulse |
| `trail` | fading polyline of the last N positions | displacement history | derived | length = windows; brightness fades; never drawn for plinths |
| `bubble` | small speech mark above the head, flickers once per message | message events (count) | derived | carries the template id on hover, never text |
| `label` | monospace id or short label | entity label | observed | near zoom only; ids, never message text |
| `banner` | translucent text plate over a cohort | inferred cohort task label | inferred (always translucent) | "probably: …" below confidence 0.6; fades after K windows without refresh |
| `badge` | tiny glyph on the body | a boolean the stream states (e.g. "new this window", "merged identity") | observed / derived | at most two badges |
| `tether` | thin line between two units | alias / merged identity | derived (alias watcher) | near zoom |

### 14.3 Landmark archetypes (places; the designer maps resource kinds to these)

| id | Stands for | Geometry | Data-bound parameters | Notes |
|---|---|---|---|---|
| `slab` | a document, file, page, sheet | low wide block | `size` (events this window), `heat` (distinct units vs usual) | the default for anything written to |
| `tower` | an external endpoint: host, site, API | tall thin block | `size`, `heat` | sits at the world's edge by default |
| `plaza` | a place where units talk: channel, room, board | flat disc with a hearth | `size` (messages), `heat` (distinct speakers vs usual) | units drawn to a plaza stand around it, not on it |
| `kiosk` | a board, queue, ticket list, dataset | small post with a panel | `size`, `heat` | |
| `road` | a method, a tool class, a route (identity-free worlds) | ribbon from the centre | `width` (volume), `age` (windows since first seen: new roads are bright) | plinths stand along the roads that reach them |
| `gate` | where new units enter | arch at the edge of a territory | `flow` (new units this window) | one per territory |
| `district` | a grouping of landmarks (namespace, host group, method family) | faint outline and ground tint | membership | far zoom only |

**Heat** is the convergence / burst quantity (distinct units now vs this landmark's usual), rendered as a ground
ring whose colour follows the same severity scale as findings; a red ring *is* a convergence observation.

### 14.4 Relations (lines between things)

| id | Meaning | Status | Style |
|---|---|---|---|
| `arc_touch` | co-touched the same landmark this window | derived | thin, solid, landmark colour |
| `arc_reply` | A replied to B | derived (same room within a minute) or inferred (analyst) | solid when derived, **hatched when inferred** |
| `arc_lineage` | content reuse: A posted, B reused | derived (propagation watcher) | solid when exposure observed, **dashed when chronological only** |
| `arc_approach` | two units closing distance over N windows | derived (spatial feature, above null) | faint, grows with the feature |
| `beam` | an operator or environment action on a unit | observed | vertical shaft from above; red for stop, amber for pause / deny, grey for message |

### 14.5 Ground, atmosphere, light

| id | Binds to | Notes |
|---|---|---|
| `territory` | group membership (observed) or proposed grouping (inferred, hatched) | soft tint; weak attractor in the layout |
| `fog` | coverage: windows since an analyst read this cohort | ground-level haze over the cohort's region; reading clears it for K windows; the random spot-check lights a region |
| `lantern` (later) | an analyst currently reading a cohort | small hovering light; the reading plan made visible |
| `daylight` | replay clock | sun angle from time of day; purely orientational, carries no data |

### 14.6 Camera and scenes

| id | Meaning |
|---|---|
| `overview` | the whole world; cohort blobs; the opening shot |
| `follow(unit)` | track one unit, near zoom, trail on |
| `at(landmark)` | orbit a landmark at mid zoom |
| `region(cohort \| territory)` | frame a group |
| `sweep(t0, t1, speed)` | a time sweep: replay a span at a chosen pace with the camera fixed |
| `top(feature)` | fly to the unit or landmark with the highest value of a spatial feature (e.g. `top(crowding)`) |

A **scene** = a camera + an optional filter (units, landmarks, relations to show) + a question it answers +
optionally a finding kind it is attached to (so "Show me" on a convergence finding opens the crowds scene at that
landmark).

### 14.7 Models the designer makes (revised 2026-10-04)

The first version allowed two landmark composites of three solids. That was too little to show what a stream's
agents and places are, so it is replaced by a model kit (`backend/swarmscope/world/models.py`, skill reference
`references/models.md`):

- **What a model is.** Data, not code: an id, a kind (`landmark`, `unit`, `prop`), a one-sentence meaning, and up
  to 16 to 32 parts. Each part is a shape (box, cylinder, cone, sphere, dome, capsule, torus, disc, ring, prism,
  wedge, lathe) with a size, a position, a rotation, a theme colour token, a material (matte, gloss, metal, glass,
  glow) and an optional gentle animation (spin, sway, bob).
- **Where it is used.** Landmark rules take `model`; `render.cast` or `render.character` take unit models;
  `scenery` places props at the centre, around the rim, or beside each territory.
- **What keeps it honest.** `tint` is the only data colour (a unit's workstream, a landmark's kind) and scenery may
  not use it. Units may not be glass (translucency means an uncertain identity) or bob (the "active" pose). Every
  model has a meaning shown in the legend. Size, part and triangle budgets are enforced, and there are at most ten
  models and sixty scenery instances.
- **How the designer sees it.** `world_model_check` validates a model without applying it and returns bounds, a
  triangle estimate, warnings for floating parts, and ASCII silhouettes from the front, side and top.
- **What it costs.** Landmark and scenery models are compiled once into merged, instanced meshes. Unit models are
  drawn only in the characters tier, so pawns and dots, and therefore latency at scale, are unchanged.
- **Where people see them.** The World's Edit menu lists the models made for the stream with a turntable preview,
  what each stands for and where it is used.

## 15. The data-availability model

### 15.1 Fields a stream might have

The World reads the same normalised events as everything else (`EvidenceEvent`: `ts`, `actor`, `action`, `object`,
`artifact`, `attributes`; `Entity`: `type`, `label`, `group`, `identity_confidence`). From those and the capability
profile, the availability table is derived per stream. Capabilities already exist (`identities`, `resources`,
`artifacts`, `self_reports`, `communication`, `groups`, `tool_calls`, `computer_actions`, `environment`, `control`,
`timestamps`); the World adds **feature statuses** on top:

| Feature | observed if | derived if | inferred if (models on) | absent if |
|---|---|---|---|---|
| `identity` | `identities` present and `identity_confidence` strong | — | — | `identities` absent → unit becomes `plinth` |
| `identity_partial` | `identity_confidence` partial | alias watcher merges | — | — |
| `activity` | — | `timestamps` | — | never absent |
| `signature` | — | `actor` + `action` (the scale layer's Profile) | message-shape classes when only text exists | no actor → plinth world over `object` |
| `resources` | `resources` present | path/URL shapes in `object` | kinds named by the composer from top values | no `object` → no landmarks (signature-only world) |
| `resource_kinds` | `family` on events | path/URL heuristics | model names kinds from the profile | → one generic archetype |
| `messages` | `communication` | message-like actions | — | → no bubbles, no plazas |
| `replies` | explicit reply/mention fields | same room within 60 s | analyst from samples | → no reply arcs |
| `co_touch` | — | two units on one `object` in one window | — | needs resources |
| `lineage` | — | propagation watcher (artifacts) | — | needs artifacts |
| `groups` | `group` on entities | model family / host as proxy | analyst-proposed groupings | → no territories |
| `state_fine` (working/blocked) | tool vs resource actions distinguished; denial events | error-like actions | analyst labels | → `active` only |
| `operator` | `environment` events | — | — | → no beams |
| `control` | `control` capability | — | — | → read-only world |
| `task` | stated goal events | — | analyst cohort labels | → signature text as the only label |
| `grade` | a confidence attribute the source states | — | — | → no material encoding |
| `text` | artifacts present | — | — | only ever used behind the evidence boundary |

### 15.2 Our six sources, as the table sees them

| Feature | Planted swarm | Claude Code (live) | AI Village | Planted village | Any JSON (typical) | Transluce |
|---|---|---|---|---|---|---|
| identity | observed | observed | observed | observed | observed if `actor` | absent |
| identity_partial | — | — | — | — | — | — |
| signature | derived | derived | derived | derived | derived | derived over targets |
| resources / kinds | observed | observed (files) | observed (docs, rooms) | observed | derived from `object` | observed (targets) |
| messages / replies | observed / derived | — | observed / derived+inferred | observed / derived | if `chat.*` | — |
| co_touch | derived | derived | derived | derived | derived | — |
| lineage | derived | — | derived | derived | if artifacts | — |
| groups | observed (teams) | derived (model family) | — | — | if `group` | absent |
| state_fine | observed (operator stop) | observed (denials, control) | inferred | observed | rarely | — |
| operator | observed | observed | — | observed | if `environment.*` | — |
| control | — | observed | — | — | — | — |
| task | — | — | observed (goals) + inferred | — | inferred | — |
| grade | — | — | — | — | — | observed |
| **unit model** | sprite | sprite | sprite | sprite | sprite (or plinth) | plinth |
| **world shape** | swarm | swarm + control | village | village | nearest by table | targets map |

German Wiki, once revived: identity_partial, resources observed (pages), lineage derived, operator observed
(moderator sweeps), groups inferred; sprite at alpha 0.55; world shape "wiki".

### 15.3 What the World does at each level of poverty

| The stream has | The World shows |
|---|---|
| actor, action, time | sprites positioned by behaviour signature only, height by activity, colour by action family; no landmarks, no arcs; legend lists everything unknown |
| + object | landmarks (one generic archetype unless kinds are known), co-touch arcs, crowd rings, the convergence reading |
| + family / resource kinds | archetype per kind, districts |
| + messages | bubbles, plazas, derived reply arcs |
| + artifacts | lineage arcs, say-do reading |
| + groups | territories, gates |
| + environment / control | beams; the control menu |
| + analysts with models on | cohort banners, inferred states and arcs (translucent / hatched) |

## 16. The encoding grammar

A **binding** attaches one quantity to one visual channel:

```yaml
- channel: height            # one of: position, height, colour, alpha, material, state, ring, trail, bubble,
                             #         banner, badge, size, heat, width, age, arc, beam, fog, territory
  quantity: activity_z       # a named quantity from the feature layer (see list)
  transform: clamp(-1, 3)    # linear | log | zscore | rank | clamp(a, b)
  status: derived            # observed | derived | inferred; inferred forces translucent styling
  legend: "Height: how busy this agent is compared with its own usual."
```

Named quantities (the only ones a binding may use): `activity`, `activity_z`, `rate_change`, `self_shift`,
`family_dominant`, `action_dominant`, `messages`, `errors`, `severity`, `displacement`, `isolation`, `drift`,
`crowding`, `approach`, `landmark_events`, `landmark_distinct_z`, `coverage_age`, `identity_confidence`,
`grade`, `group`, `cohort`, `task_label`, `state`, `since_last`, `new_units`, `road_age`.

Constraints (validated, not advisory):
1. One quantity per channel; one channel per quantity (no double encoding, except position+trail which share
   displacement by construction).
2. **Colour is reserved for a categorical family** (workstream, method, edit kind); never a rank or a severity.
3. **Ring is reserved for severity**; nothing else may be red-amber-grey.
4. **Height is reserved for activity-like quantities** (`activity_z`, `landmark_distinct_z`, `grade`-weighted volume).
5. `alpha` and `material` are reserved for certainty: identity confidence, inferred status, the source's own grade.
6. A binding whose quantity is `absent` in the availability table is rejected.
7. Every binding has a legend sentence in the source's nouns.
8. At most 9 bindings active at once; the opening scene may show at most 6.

## 17. WorldSpec, complete

```yaml
version: 3
source: ai_village
lens: Default                      # a lens may override scenes and bindings; the layout is per source
shape: village                     # swarm | swarm_control | village | wiki | targets | stripped | custom
unit:
  model: sprite                    # sprite | plinth
  alpha_by: identity_confidence    # or a constant
  of: actor                        # actor | object (what a unit is)
metric:
  sentence: "Distance: who talks in the same rooms and works on the same documents."
  forces: {anchor: 0.3, landmark: 1.0, interact: 0.9, similar: 0.4, repel: 0.6, max_step: 0.08}
  interactions: [co_touch, reply_derived, lineage]      # which derived relations pull units together
  trail_windows: 12
landmarks:
  - {match: {family: chat},  archetype: plaza, label: room,     reason: "rooms are where the village coordinates"}
  - {match: {family: docs},  archetype: slab,  label: document, reason: "shared documents are the work product"}
  - {match: {family: web},   archetype: tower, label: site,     reason: "external sites sit at the edge"}
  - {match: {kind: other},   archetype: kiosk, label: resource, reason: "anything else, small"}
models: []                         # ≤ 10 models made for this stream (§14.7)
scenery: []                        # props placed at centre / rim / territories
territories: {by: none}            # none | group | family | inferred_group
bindings: [...]                    # §16; the fixed set minus what is absent, plus ≤ 1 stream-specific
relations: [arc_touch, arc_reply, arc_lineage, beam]
coverage_fog: true
null_model: {windows: 24, quantile: 0.95}
scenes:
  - {id: square, title: "The village square", camera: overview, question: "Is anything out of shape?", opening: true}
  - {id: saydo,  title: "Saying and not doing", camera: region(cohort=all), filter: {bubble: true, displacement: "<0.02"},
     question: "Who talks about work without doing any?", finding_kind: say_do_mismatch}
  - {id: docs,   title: "Shared documents", camera: top(crowding), question: "Who is converging, and from where?", finding_kind: convergence}
  - {id: day,    title: "One agent's day", camera: follow(selected), question: "What did this agent do, in order?"}
control: {enabled: false}          # true only with the control capability; actions mirror the Control page
annotations: []                    # pins {id, at: unit|landmark|xyz, text, by, ts}; text is human- or copilot-written, never agent text
availability: {...}                # the §15 table as computed for this stream, frozen at compose time
reasons: {...}                     # one sentence per choice, shown while composing and in the legend's "why" tab
```

**Ops** (validated, atomic, versioned, undoable, same store as dashboards): `set_unit`, `set_metric`,
`add_landmark` / `update_landmark` / `remove_landmark`, `add_model` / `update_model` / `remove_model`, `add_scenery` / `remove_scenery`, `set_territories`,
`add_binding` / `update_binding` / `remove_binding`, `set_relations`, `set_fog`, `set_null_model`, `add_scene` /
`update_scene` / `move_scene` / `remove_scene`, `set_opening`, `add_annotation` / `remove_annotation`,
`set_control`, `reset_world` (to the preset or the composed default).

**Validation** rejects: a binding on an absent feature; colour or ring misuse (§16); a sprite world with no
identities; a plinth world with poses; control enabled without the capability; scenes without a question; more than
four scenes besides the opening; any field containing agent text (checked against the artifact fingerprint index).

## 18. The world-designer skill: instructions conditioned on the data

`.claude/skills/world-designer/SKILL.md`, with `references/` holding the primitive library (§14), the grammar (§16),
the five presets with reasons, and `shapes.md` (the decision procedure below). Runs as one Claude Code session with
the tools `stream_profile`, `world_features_available`, `world_catalog`, `world_preview`, `world_edit`,
`world_undo`; cheap mode uses Sonnet at low effort, as the dashboard designer does; `max_turns` 20.

### 18.1 Standing rules (always)

1. You compose from the library first, and make a model (§14.7) only when nothing premade says what a thing is. You cannot add code, textures or new channels. If the data wants something
   the library lacks, write it in `open_questions` for us; do not approximate it with a misuse.
2. Every choice has a `reason` in the source's nouns. A world without reasons is rejected.
3. Nothing you place rests on agent text. You see structure, counts and shapes; the people will too.
4. Position uses derived features only. Inferred features may label, tint or hatch; they never move anything.
5. Draw uncertainty: anything inferred is translucent or hatched, and says so in its legend sentence.
6. Prefer fewer encodings. At most six bindings on each unit and four on the ground (position and trail are the layout itself). If two bindings answer the same question,
   keep the one with the stronger status.
7. Run `world_preview` before `world_edit`; keep a metric only if the preview shows it separates something (cohort
   separation above the null model) on the data so far.
8. Control appears only when `availability.control` is observed, and then only as the Control page's actions.

### 18.2 Decision procedure (`shapes.md`)

Read `world_features_available` and go down this list; stop at the first match; adapt the matching preset.

| If | Then shape | Start from | Adaptations to consider |
|---|---|---|---|
| no `identity`, `resources` observed | **targets** | Transluce preset | if the source has no method-like family, drop roads and lay plinths by co-occurrence alone; `grade` → material only if the source states a confidence |
| `identity_partial` | **wiki** | German Wiki preset | sprites at alpha 0.55, tethers on; territories inferred only if analysts are on, else none; lineage arcs if artifacts |
| `identity`, `messages`, ≤ 60 units | **village** | AI Village preset | rooms as plazas if `replies` derived or inferred; follow-scene on by default (few units, each matters) |
| `identity`, `control` observed | **swarm_control** | Claude Code preset | files as slabs, tools as colour family, denials as `blocked`, beams for pauses/stops, control menu on click |
| `identity`, `groups`, > 60 units | **swarm** | planted swarm preset | territories by group; gates; crowd scene attached to convergence; drop bubbles if no messages |
| `identity` only (actor + action) | **stripped** | planted swarm preset minus landmarks | signature-only metric; one generic `kiosk` archetype if `object` exists but kinds are unknown; legend lists the unknowns; propose the field questions for the person |
| no `actor` and no `object` | **none** | — | refuse politely: write what field would make a world possible |

### 18.3 Required outputs per step (the critic checks each)

| Step | Must write |
|---|---|
| Survey | the unit (what one sprite or plinth is), the places, the acts, the groups; the shape chosen and why; which features are observed / derived / inferred / absent, verbatim from the table |
| Metric | one legend sentence; the relations that pull units together and why those; the force weights with a reason tied to the data's time scale (window length, rate) |
| Vocabulary | the landmark mapping with a reason per kind; territories and why (or why none); the unit model |
| Encodings | the binding list, each with status and legend sentence; what was dropped and why; the one stream-specific binding, if any, with its quantity |
| Scenes | the opening question; up to four scenes, each with its question and the finding kind it serves |
| Preview | the `world_preview` statistics you relied on (separation vs null, crowding range, how many units moved more than the null) |
| Critic | the checklist (§18.4) with pass/fail per item, and the fixes made |
| Open questions | what the library or the data could not do |

### 18.4 Critic checklist

- [ ] Every binding's feature is not `absent`; inferred bindings are translucent/hatched; legend sentences exist.
- [ ] Colour = category, ring = severity, height = activity-like, alpha/material = certainty.
- [ ] Position bindings use derived features only.
- [ ] No agent text anywhere (labels are ids or template ids; annotations are human or copilot text).
- [ ] Opening scene is an overview with ≤ 6 bindings on a unit and ≤ 4 on the ground; every scene has a question.
- [ ] Unit model matches identity availability; control matches the control capability.
- [ ] Null model on; preview separation above null, or the metric was changed and re-previewed.
- [ ] Every landmark mapping, binding, scene and force weight has a reason.

### 18.5 Models-off (the free composer)

The same procedure as fixed rules: shape from §18.2, the preset's bindings minus absent features, default forces
per shape, scenes from the preset filtered by available finding kinds, reasons from templates ("the stream has no
messages, so no speech bubbles"). Deterministic, so the planted swarm's world is identical run to run.

## 19. Legend, tooltips and the "why" tab

- The **legend** is generated from the active bindings: one line each, in the source's nouns, grouped as *where
  things are*, *how they look*, *what the lines mean*, *what the ground means*. Inferred bindings carry the word
  "inferred" and the hatched swatch. A final line lists what this stream cannot show.
- **Tooltips** show, for a unit: label, cohort (signature or task label with its status), state and how it was
  obtained, activity vs usual, finding and severity if any, "read closely N windows ago"; for a landmark: kind,
  events, distinct units vs usual (and whether that is a finding), the teams present. Never message text.
- The **why tab** shows the designer's reasons and open questions, the preview statistics it relied on, and the
  version history with undo, exactly like the dashboard's History.

## 20. Interaction model

| Gesture | Effect |
|---|---|
| hover unit / landmark | tooltip (§19) |
| click unit | entity drawer (existing) + a "World" section: position history, isolation, drift, nearest units, approach arcs; actions: watch, investigate, ask, and (control only) pause / interrupt / message / stop |
| click landmark | landmark drawer: crowd over time, teams present, the convergence/burst observation if any |
| click finding (from Brief) → "Show me" | opens the scene attached to its kind at its scope |
| lasso on the ground | selection → ad hoc scope; "Ask about these" opens the copilot with it; "Pin" makes an annotation |
| scene tabs | camera presets; `sweep` scenes add a time scrubber |
| time scrubber | moves the replay clock (same `clock` API); the World interpolates |
| zoom | semantic: blobs ↔ sprites ↔ details; the legend updates to what is visible |
| `L` | legend; `W` the why tab; `space` pause motion (data keeps flowing; positions freeze until released) |

## 21. Wire formats and budgets

**`GET /api/world/state`** and the WebSocket `world` message (per window):

```json
{"window": 412, "now": "2026-09-01T03:20:00", "version": 7,
 "units": {"ids": ["01·028", ...], "xyz": "<float32 base64, 3 per unit>", "h": "<float32>", "fam": "<uint8>",
           "state": "<uint8>", "ring": "<uint8>", "alpha": "<uint8>", "cohort": "<uint16>"},
 "landmarks": [{"id": "shared/plan.md", "arch": "slab", "xyz": [..], "size": 41, "heat": 2.3, "heat_sev": "LOOK"}],
 "relations": [{"t": "arc_touch", "a": 12, "b": 44, "w": 3}, {"t": "beam", "a": 90, "kind": "stop"}],
 "cohorts": [{"id": "c17", "label": "shell · team-07", "task": "probably: data cleanup", "task_status": "inferred",
              "xyz": [..], "n": 57, "fog": 6}],
 "features_top": {"crowding": ["shared/plan.md"], "drift": ["07·048"], "isolation": ["03·011"]}}
```

Budgets: ≤ 150 KB per window at 5,000 units (typed arrays, ids sent once per session and then by index); layout
≤ 50 ms at 2,000 units and ≤ 200 ms at 5,000 (numpy, cohort-level repulsion); render 60 fps with instancing on an
integrated GPU, LOD to blobs above 2,000 visible units; trails limited to the 200 most-displaced units at mid zoom.

## 22. Null model, thresholds, and what glows

- At session start (and every 48 windows) the layout runs on a **shuffled copy** of the first N windows: actors
  permuted within each window, so rates and landmarks stay real but who-did-what is random. This yields a null
  distribution per spatial feature.
- A feature **glows** (ring on a landmark, approach arc, drift highlight, banner emphasis) only above its null
  `quantile` (default 0.95); the legend states the threshold ("brighter than 95% of a shuffled swarm").
- Spatial findings emitted to the Brief use the Brief's own severity bands on top of the null test; the null test
  is a gate, not a score.
- The null layout is also a **scene** ("What random would look like"), one click away, so a person can calibrate
  their own eye. This is the direct answer to pareidolia.

## 23. Compose-mode step and lenses

Step 5, "Laying out the world": loads `packs/<id>/world.yaml` when present, else composes (free or designer);
shows the shape chosen, the metric sentence, the landmark mapping, and the list of encodings this stream cannot
support, each with its reason; then "Open the dashboard" lands on the Brief as today, with **World** as the second
nav entry. A lens may carry its own scenes and binding overrides (not its own layout); "Save as a lens" captures
them with the dashboard.

## 24. Acceptance criteria (what "done" means, per phase)

| Phase | Done when |
|---|---|
| W0 | H1 holds for ≥ 3 planted behaviours; null feature distributions reported; a go decision recorded in this document |
| W0b | availability tables for all six sources match §15.2; the layout runs on a stripped stream; planted results unchanged with inference off |
| W1 | planted swarm renders at 2,000 units at 60 fps; every §14 primitive used by the swarm shape exists; legend generated from bindings; click → drawers; motion smooth at 1 h/s |
| W2 | WorldSpec ops and validation complete with tests for every rejection in §17; the skill composes a valid world for a stripped stream and for Transluce in one cheap run each; presets load and reset |
| W3 | spatial features are claims with evidence; `SpatialDrift` fires on the planted drift; "Show me" works from a finding; lasso → copilot scope |
| W4 | pause from the World on a simulated Claude Code agent, with approval, shows the beam within one window |
| W5 | H2–H6 measured and written up; failures listed, not hidden |
| W6/W7 | village and Transluce presets pass the critic; German Wiki adapter probed and revived; its preset passes |
