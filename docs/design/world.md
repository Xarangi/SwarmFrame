# The World

The World is a 3D view of the swarm in which **where a unit stands is a measurement**. Units that act on the same
places, interact, or behave alike stand together. A crowd forming at a shared file is a crowd at a landmark. A unit
whose behaviour changes walks away and leaves a trail. Everything else on screen is either bound to a measured
quantity, listed in the legend, or marked as scenery that encodes nothing.

The World reads the same store, cohorts and findings as the Brief. It adds a spatial reading of them and feeds that
reading back to the analysts and the copilot.

| Part | Where |
|---|---|
| Feature grading | `backend/swarmscope/world/features.py` |
| Layout, spatial features, null model | `backend/swarmscope/world/layout.py` |
| Per-window step, flags, state for the renderer, preview | `backend/swarmscope/world/engine.py` |
| World spec, grammar, ops, store, preset loading | `backend/swarmscope/world/spec.py` |
| Scene (ground, zones, props) and activity rules | `backend/swarmscope/world/scene.py`, `world/assets.py` |
| Models the designer makes | `backend/swarmscope/world/models.py` |
| Free composer, designer session, World tools | `backend/swarmscope/world/designer.py` |
| Renderer | `frontend/src/world/view.ts`, `characters.ts`, `models.ts`, `scene.ts` |
| Page, legend, cards, Brief panel | `frontend/src/screens/World.tsx` |
| Presets | `packs/<source>/world.yaml` |
| Designer skill | `.claude/skills/world-designer/` |
| Tests, evaluation | `tests/test_world.py`, `backend/swarmscope/evals/world_eval.py` |

## Principles

- **Position is a measurement.** Positions come from derived features only (activity, behaviour signature, places
  used, derived interactions). The map is the same with models on or off and runs on any stream with `actor` and
  `action`. Inferred features (an analyst's label for a group) may label or tint; they never move a unit. The
  validator refuses a position binding with inferred status.
- **Grade every feature.** SwarmFrame observes swarms it did not instrument, so each feature is graded per stream as
  observed (the stream states it), derived (code computes it), inferred (a model reads samples) or absent. An
  encoding whose feature is absent is refused, and the legend lists what the stream cannot show.
- **Places and props only set the scene.** Ground styles, zones, props and scenery orient a viewer and make places
  legible. They never encode a value, are drawn muted, and may not use the data colour `tint`.
- **Null baselines.** The same layout runs on a shuffled copy of every window. A spatial feature is flagged, and
  glows, only above the shuffled swarm's family-wise threshold. This is the defence against seeing patterns in noise.
- **Motion means behaviour change.** The step per window is bounded, so speed is readable. Units with no events in a
  window do not move. Activity rules make units walk to the place they used, but every walk ends at the measured
  position.
- **Colour is a category.** Colour is the unit's dominant workstream (or a target's methods); never a rank or a
  severity. Rings are reserved for severity, height for activity-like quantities, translucency for uncertainty.
- **No agent text.** Labels are ids. A bubble shows that a message was sent, never its words. Message shapes are
  used as template ids only.

## Why a spatial view

| Mechanism | What it buys | Source |
|---|---|---|
| Preattentive perception: position, motion, size and colour are read in parallel, before attention | A unit drifting from its group is seen at a glance, including patterns no watcher has a rule for | Healey & Enns, preattentive processing; Ware, *Information Visualization* |
| Spatial memory: people remember where things were | Slow change becomes visible as displacement in a scene watched over minutes | scene-based change detection literature |
| Semantic zoom: overview, zoom and filter, details on demand | One view that works at 20 agents and at 5,000 | Shneiderman 1996 |
| A shared referent: people and the copilot can point at "those three near the file" | Selection becomes a scope for a question | Clark, common ground |
| Coverage made visible | Regions no analyst has read are hazy, so a false sense of coverage shows | the coverage ledger |

## What a stream can show

`features.availability()` grades 16 features from a 20,000-row sample of the store and the capability profile:
identity, identity_partial, activity, signature, resources, resource_kinds, messages, replies, co_touch, lineage,
groups, state_fine, operator, control, task, grade. Each entry has a status and a one-line reason. Each binding
quantity names the features it needs (`QUANTITY_NEEDS`), and takes the weakest status among them.

| The stream has | The World can show |
|---|---|
| actor, action, time | units placed by behaviour signature, height by activity, colour by family; no landmarks |
| + object | landmarks, co-touch arcs, crowd rings: the convergence reading |
| + family | an archetype per kind of place |
| + messages | bubbles, reply arcs (consecutive messages in one room within 60 seconds) |
| + artifacts | lineage arcs and message-shape pulls |
| + groups | team territories and team-ordered anchors |
| + environment events or a control plane | operator beams; control actions on click |
| + analysts | cohort task labels (derived from signatures with models off, inferred with models on) |

## Layout

The layout is two levels, recomputed every window in numpy (`Layout.step`).

**Cohort anchors.** Each cohort's signature fixes an anchor on a wheel. With two or more teams, the team picks the
angular sector and the workstream picks a ring inside it. Without teams, the workstream picks a sector from a fixed
16-slot order (`FAMILY_WHEEL`). The same cohort lands in the same region in every run. The world's radius grows with
the square root of the expected population.

**Forces.** Each active unit moves by the sum of five forces, clamped to `max_step` times the world scale:

| Force | Pulls toward |
|---|---|
| `anchor` | its cohort anchor (three times stronger for its first 8 windows) |
| `landmark` | the places it acted on this window, weighted by specificity |
| `interact` | the other end of each derived interaction edge, normalised per kind |
| `similar` | its cohort's centroid, scaled by 1 − TV distance between its mix and the cohort's |
| `repel` | away from units in the same grid cell, so crowds stay readable |

Interaction kinds and weights: `co_touch` (0.6, only on uncommon places), `reply` (1.0), `lineage` (1.6, from the
propagation watcher's `content_reuse` observations), `shape` (1.2: a unit posting an uncommon message template is
pulled toward the most recent earlier posters within 12 windows). Units present in the first 10 windows start at
home; later arrivals start just outside their anchor and walk in.

**Places.** Landmarks are the 90 busiest places plus any place shared this window by three or more units from at
least two groups or cohorts. Each pull is weighted by inverse document frequency, so a place everyone uses says
nothing and a place a few units share pulls hard. A landmark starts at the mean position of its first users, then
drifts toward the weighted mean of its users' anchors, so a shared place sits between the teams that share it.
Landmarks repel each other a little. Crowding is (distinct units now + 1) / (usual + 1), with a slow baseline so a
sustained new crowd stays a crowd for hours.

Two variants replace the force layout for places or units:

- `metric.places: districts` fixes places in one sector per kind (rooms together, documents together). Units are
  still measured. The village preset uses it.
- `metric.layout: mix` is the catalog layout: each method class is a corner and each unit stands at its
  whole-record method mix. Flags are off, because the shuffled baseline does not apply to a map not made by forces.
  The Transluce preset uses it.

**Spatial features and flags.** Per unit: displacement (one window), drift (six windows), isolation (distance to the
cohort centroid over the cohort's mean), activity z-score, and still-talking (sent messages, barely moved in three
windows). Units still walking in from their gate are not flagged.

| Flag | Fires when |
|---|---|
| `drift` | drift above the null's threshold and above 0.02 |
| `isolation` | isolation above the null's threshold and above 1.5 |
| `crowding` | a place seen for more than 3 windows, with 3 or more units, crowding above the threshold and above 1.5 |
| `still_talking` | messages with no movement |
| `split` | a cohort's spread jumps above 1.8 times its running average, after 8 windows |

The null model (`NullModel`) gives each unit another unit's window (actors permuted, activity and places kept) and
runs the same layout, every window up to 2,500 units and every third window above that. It keeps 24 windows of
samples. Thresholds are family-wise: the 0.95 quantile of the shuffled swarm's per-window maximum, because with
thousands of units a per-unit 95% threshold flags about 5% of them every window by construction.

## Encodings

| Visual | Quantity | Notes |
|---|---|---|
| Position | cohort, places, interactions | the layout above; the metric sentence is its legend |
| Height | `activity_z`, clamped to −1..3 | plinths in the catalog layout: log of total reports |
| Colour | `family_dominant` | the dashboard's family palette, so a workstream has one colour everywhere |
| Pose | `state` | idle, active, talking, working (tool calls), blocked (3+ error-like actions), paused, stopped (control plane or a stop beam) |
| Ring | `severity` | ACT / LOOK / WATCH from the Brief digest, same words and colours |
| Trail | displacement | sent for flagged units and the 30 that moved most |
| Bubble | `messages` | flickers faster for still-talking units |
| Crowd ring | `landmark_distinct_z` | on a place above 1.25× its usual; amber when flagged, severity colour when a finding names it |
| Fog | `coverage_age` | a haze over cohorts no analyst has read for 12 or more windows |
| Territory | group | a soft tint over each team's members |
| Cohort label | `task_label` | the analyst label, "probably:" when inferred below 0.6 confidence; marked stale after 18 windows |
| Material | `grade` | plinths only: solid when most reports are significant, glass otherwise |
| Glow | drift or isolation flag | a thin blue pillar |
| Arcs | co-touch, reply, lineage | lineage dashed when exposure was not observed; co-touch drawn only when zoomed in |
| Beams | operator or control events | red stop, amber pause or deny, grey message |

Not built: translucent sprites for partial identities (alpha is sent but drawn only on plinths), tethers and badges,
inferred (hatched) arcs and territories, and drawn annotations (pins are stored in the spec, not shown).

## Render tiers

| Units in view | Tier | Notes |
|---|---|---|
| up to `render.max_characters` (80) | characters | the cast: newt, human, frog, owl, fox, robot, plus unit models made for the stream |
| up to 2,000 | pawns | one instanced body and head |
| beyond 2,000 | dots | a point cloud, cohort blobs from afar; zooming in switches to pawns |

With `tier: auto` the server recommends a tier by count. In any tier the 40 units nearest the camera become
characters when zoomed in. Worlds whose units are places use plinths. The tint of a character carries the workstream;
the character's kind is identity only (`character_by`: group, unit, fixed or none).

## The legend

The legend is built from the active spec, so it cannot drift from what is drawn. In order:

1. **What you are seeing**: each activity rule's meaning with how many units it moves now, the zones with swatches,
   the ground, and a line saying scenery encodes nothing.
2. **Where things are**, **How they look**, **The ground and places**: one line per binding, its legend sentence,
   and a status tag when it is not derived.
3. **Lines**: one line per relation in the spec.
4. **Glow**, with the current drift threshold (not shown for catalog maps).
5. **Made for this stream**: each model's meaning, and scenery.
6. **Not in this stream**: the absent features with their reasons.

## Scene and activity

The scene is decoration with rules (`world/scene.py`).

- **Ground**: paper, grass, stone, plaza_tiles, grid, water_edge or sand.
- **Zones**: up to 8, each a soft tinted region around every place matching one of `family`, `archetype`, `label`, or
  a team (`group`, or `all`), with a style and a short label.
- **Props**: up to 16 placements and 480 instances, from 22 library assets (tree, bench, desk, bookshelf,
  server_rack, terminal, small_house, fountain, ...) or prop models made for the stream. Placement is `centre`,
  `rim`, `territories`, `landmarks` (near a matching place), `zones` or `scatter`, deterministic for the same places.
  Every placement has a meaning, "decoration" when it encodes nothing.

**Behaviours** are activity rules, up to 8, checked in order; the first that matches a unit decides what it does
this window. `when` is one of 11 conditions the server computes per unit (active, acted_on_landmark, talked, idle,
new, stopped, paused, flagged, surge, environment_hit, reused_content), optionally filtered by family, action prefix
or beam kind. `do` is a library choreography (go_to, gather, follow, scatter, wander, pulse, glow, carry, stay_home,
fade) or a `sequence` of up to 8 steps whose durations sum to at most one window. A sequence that walks away must
end with `return`. Units that are places cannot walk: they pulse, glow, carry or fade. Each rule has a meaning sentence for
the legend. Conditions the stream cannot support are refused, and presets drop them with a reason.

The server sends, per unit, the condition bitmask, the chosen rule, a target place and a partner, for the busiest
1,500 units (400 in the dots tier). The renderer plays each plan over the time until the next window. Dots do not
move, so behaviours cost nothing at scale.

## Models the designer makes

When no premade character or archetype says what a thing is (hosts as server racks, robot agents as drones), the
designer writes a model: an id, a kind (`landmark`, `unit` or `prop`), a one-sentence meaning and a list of parts.
A part is a shape (box, cylinder, cone, sphere, dome, capsule, torus, disc, ring, prism, wedge, lathe) with a size,
position, rotation, theme colour token, material (matte, gloss, metal, glass, glow) and an optional animation (spin,
sway, bob). A part list cannot run code, is cheap to validate, and renders in the dashboard's palette in both themes.

- Budgets: unit models 16 parts and 2,500 triangles, landmarks 24 and 4,000, props 32 and 4,000; size limits per
  kind; at most 10 models and 120 scenery instances per World.
- Meaning: `tint` is the only data colour. Unit models need a `tint` part, may not be glass (translucency means
  uncertain identity) and may not bob (bobbing is the active pose). Props may not use `tint`.
- `world_model_check` validates a model without applying it and returns bounds, a triangle estimate, warnings for
  floating parts and ASCII silhouettes from the front, side and top.
- Landmark and prop models compile once into instanced meshes. Unit models are drawn only as characters, so pawns
  and dots, and latency at scale, are unchanged.
- The Edit menu's "Models made for this stream" shows each with a turntable preview, its meaning and where it is used.

## World spec

One `WorldSpec` per source, kept with a version history of 30 and undo (`WorldStore`). A pack's `world.yaml` is a
complete spec without `source`. The fields a designer sets:

| Field | What it holds |
|---|---|
| `shape` | swarm, swarm_control, village, wiki, targets, stripped or custom |
| `unit` | `model` (sprite or plinth), `of` (actor or object), `alpha_by` |
| `render` | `tier` (auto, characters, pawns, dots), `max_characters`, `character_by`, `character`, `cast` |
| `metric` | `sentence` (what distance means), `forces`, `interactions`, `trail_windows`, optional `places: districts` or `layout: mix` |
| `landmarks_from`, `landmarks` | `object` (resources are places) or `family` (methods are roads); rules `{match: {family | prefix | kind: other}, archetype, label, reason, model}`, first match wins |
| `models`, `scenery` | models made for this stream; scenery at centre, rim or territories |
| `environment`, `behaviours` | the scene and activity rules above |
| `territories` | `{by: group}` or `{by: none}` |
| `bindings` | `{channel, quantity, transform, legend}`; status is filled in from the availability table |
| `relations` | arc_touch, arc_reply, arc_lineage, beam |
| `coverage_fog`, `null_model` | fog on or off; `{windows, quantile}` |
| `scenes` | `{id, title, camera, target, question, finding_kind, opening}` |
| `control` | `{enabled}` |
| `reasons` | one sentence per choice, keyed by what it explains |

Archetypes: slab (document, file, page), tower (host, site), plaza (room, channel), kiosk (board, dataset, anything
else), road (a method, in worlds whose units are places), gate, district. Force ranges: anchor 0.05–1.0, landmark
0–2, interact 0–2, similar 0–1.5, repel 0.2–1.5, max_step 0.02–0.2.

On load, a preset is validated against this run's availability table. Bindings, behaviours and zones the run cannot
support are dropped with a `dropped:` reason, and control is switched off without a control plane. A saved World that
is still the pack's preset is refreshed when the preset file changes; an edited one is kept.

Ops (`world_edit`, `POST /api/world/ops`) are applied atomically, validated, versioned and undoable. They cover every
field: `set_shape`, `set_unit`, `set_render`, `set_metric`, landmark, model, scenery, binding, scene, zone, prop and
behaviour add/update/remove, `set_relations`, `set_fog`, `set_null_model`, `set_opening`, annotations,
`set_control`, `set_reason`, `set_environment` and `reset_world`. `spec.OPS` is the full list.

### Encoding grammar

Validation (`spec.validate`, `scene.validate_scene`, `models.validate_models`) refuses:

- a quantity whose features are absent, or a position binding with inferred status;
- colour on anything but a category (`family_dominant`, `action_dominant`, `group`); ring on anything but
  `severity`; height on anything but activity-like quantities; alpha and material on anything but
  `identity_confidence` or `grade`;
- a channel used twice, or a quantity encoded twice (position and trail share displacement);
- more than 10 bindings besides the trail, a binding without a legend sentence, an empty metric sentence;
- a sprite world on a stream without identities, or control without a control plane;
- a scene without a question, more than four scenes besides the opening one, forces outside their ranges.

More than six encodings on a unit or four on the ground is a warning, not an error.

## Choosing a shape

The free composer (`compose_world`) and the designer use the same order; the first match wins (`pick_shape`).

| If the availability table says | Shape | Units |
|---|---|---|
| no identities, places present | targets | plinths; methods are roads |
| no identities, no places | stripped | activity only |
| partial identities | wiki | sprites |
| a control plane | swarm_control | sprites; control actions on click |
| messages and 60 units or fewer | village | every agent a character |
| no places | stripped | position from the behaviour signature alone |
| otherwise | swarm | sprites, territories by team |

The composer then writes the fixed bindings minus what is absent, relations for available interactions, scenes for
the shape, a ground for the shape, a zone per kind of place, a few props, one behaviour per thing the stream says a
unit did, and a reason for each choice. It is deterministic: the same stream gives the same World.

## Presets

Each shipped source has a hand-tuned `world.yaml` with a reason on every choice. The skill's `references/presets.md`
carries them as worked examples.

### swarm: the planted swarm

`packs/swarm_scale/world.yaml`. Up to 5,000 agents in teams: dots and team blobs from afar, pawns at mid zoom.
Distance means shared files and hosts, reused content and alike behaviour. Files and documents are slabs, datasets
kiosks, hosts towers, team boards plazas. Territories by team. Scenes: the whole swarm, crowded files and hosts, who
is drifting, talking without moving, operator actions. The scene is team campuses on a grid around a fountain.

### village: AI Village

`packs/ai_village/world.yaml`. About twenty named agents who talk, each its own character. Places stand in
districts. Replies and rooms pull harder than similarity. Rooms are plazas; documents and sheets slabs; sites towers;
requests to contact the outside and hand-offs to people have their own places. Scenes: the village square, saying
and not doing, shared documents, one agent's day. The scene is a village on grass.

### swarm_control: live Claude Code

`packs/claude_code/world.yaml`. One character kind per team; files as slabs; denials as blocked; pauses and stops as beams; the
card offers pause, resume, interrupt and stop. Scenes: the swarm at work, contested files, blocked and waiting,
operator actions. The scene is a workshop.

### targets: Transluce

`packs/transluce/world.yaml`. No agent identities, so units are the targeted data sources, drawn as towers in the
catalog layout. Each method class is a corner; bands show each tower's method mix; height is total reports (log);
glass means the catalog calls most reports on it suggestive. Every tower is labelled. Scenes: the map, bursts.

### wiki: the German message board

`packs/german_wiki/world.yaml`. Handles are partial identities. Distance means writing on the same pages and reusing
the same text. Question and discussion pages are plazas, other pages slabs; moderator deletions are beams; reused
text draws lineage arcs. The pack reads the real export from `data/german_wiki` when present and a seeded synthetic
stand-in otherwise.

## The World designer

With models off, "Recompose" runs the free composer. With models on, `run_world_designer` runs one Claude Code
session with the `world-designer` skill and its references (shapes, primitives, models, environment, behaviours). It
uses the configured designer model (by default Sonnet 5.5 at low effort) and the World tools: `stream_profile`,
`world_features_available`, `world_catalog`, `world_behaviour_catalog`, `world_asset_catalog`, `world_get`,
`world_preview`, `world_features`, `world_model_check`, `world_edit`, `world_undo`. It returns a summary, a critic
checklist and open questions.

Constraints, enforced by the validator where they can be:

- compose from the premade library; make a model only when nothing premade says what a thing is;
- no code, textures or new channels; what the grammar lacks goes in `open_questions`;
- every choice has a reason in the source's nouns;
- no agent text; positions from derived features only; inferred features say so;
- the render tier fits the population; control only with a control plane;
- run `world_preview` and keep a metric only if it separates cohorts beyond chance (`separates_beyond_chance`:
  separation above 1.15 times the null's, where separation is inter-cohort distance over intra-cohort spread).

A real run on 2026-10-04 (Sonnet 5.5, low effort, planted swarm of 300 agents, asked to make hosts read as servers)
took 8 turns, 22 seconds and about $0.43. It surveyed the features, checked one model (a six-part server rack for web
hosts), applied it in one edit, previewed (separation 1.53 against a null of 1.26) and returned its critic list. Its
one failed item was the old six-encodings rule, which counted ground encodings; the rule now counts six on a unit
and four on the ground.

## Using the World

- **Page.** Scenes are buttons in the header with their question as a tooltip. `overview` frames what is populated;
  `follow` tracks a unit; `top` flies to the highest value of crowding, drift, isolation or activity; `region` frames
  a flag set (still talking, beams, blocked). `at` and `sweep` fall back to the overview. A scene's `finding_kind`
  is stored but not yet used.
- **Chips** over the stage count what is beyond chance now (drifting, crowded places, groups coming apart, talking
  without moving) and frame them.
- **Hover** shows a unit's family, state, activity against its usual, cohort, finding and flags, or a place's events,
  distinct units against usual, and teams. **Click** opens a card with drift and isolation against their null
  values, places, nearest units, and Follow, Evidence, Ask, Investigate and Pin; with control, pause, resume,
  interrupt and stop.
- **Shift-drag** selects units; "Ask about these" opens the copilot with a structure-only summary of the selection.
- **Edit menu**: recompose or ask Claude to redesign, ask about the World, ask for a new model, models made for this
  stream, render tier, coverage fog, undo, reset to the source's world.
- **Elsewhere.** "Show me in the World" on a finding frames its scope. The Brief shows a live World beside "Needs
  attention" (Brief settings can hide it). Compose mode's fifth step, "Laying out the World", shows the shape, the
  metric sentence, the render reason and what the stream cannot show.

## What the World feeds back

- **`SpatialDrift` watcher** (`org/watchers.py`): a drift flag sustained for two windows becomes a derived
  `spatial_drift` observation with the agent's recent events as evidence, at most six per window and once per six
  windows per agent; a split flag becomes `cohort_split`.
- **`world_features`** is an evidence tool for analysts and the copilot: the spatial reading of an agent, cohort or
  place with its null baselines.
- **Copilot ops**: `world_get`, `world_features`, `world_preview`, `world_edit` (including pins), `world_select`.
- **`cohort_labels`** in the analyst report contract: models off, the deterministic analyst labels each cohort from
  its signature (derived); models on, labels are inferred and stored as INFERRED claims.

## API

`GET /api/world/state` (per-window typed arrays as base64, places, relations, cohorts, territories, trails, flags,
null thresholds, scene and acts), `GET /api/world/spec`, `/catalog`, `/unit/{id}`, `/features?scope=`, `/preview`;
`POST /api/world/ops`, `/undo`, `/select`, `/design`. The snapshot carries the World's version, window, shape and
flag counts. Units on the map are those active in the last 36 windows, at most 6,000.

## Evaluation

`python -m swarmscope.evals.world_eval 1000` runs the planted swarm with models off and asks whether position
carries the planted behaviours beyond chance. For each behaviour, over the 12 windows after onset: the AUC of drift
and isolation for planted agents against the rest; how much closer the planted agents stand to each other six windows
after onset than before, against a random control set (the gathering ratio, below 1 means they gathered); the share
flagged, beamed and still talking; whether the crowd ring hit the behaviour's place. Before any behaviour: spatial
flags per window. It also reports team and cohort separation against the shuffled layout, and layout time.

Results on 2026-10-04, planted swarm, 1,000 agents, 12 hours:

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

Latency on 2026-10-04 at 5,000 agents: a median of 133 ms per window for the World step; the state payload was
about 257 KB.

Not measured: whether people notice drift or convergence faster with the World than with the Brief alone, how many
false alarms people report on a null swarm, whether a tester can explain every encoding after a minute with the
legend, whether spatial features raise triage recall, and how often inferred cohort labels agree with planted truth.

## Known limits

- Spread is not spatially separable on the planted swarm, because its templates are fragmented across ids.
- The crowding flag is conservative. It compares against the null's per-window maxima, so a planted crowd on one host
  does not cross it. A distinct-teams-per-place measure is a candidate replacement.
- Lineage arcs appear only when the propagation watcher has recorded reuse.
- Agents and places that are not on the map, such as artifacts, show a toast instead of a frame.
- Not built: time scrubbing independent of the replay clock, one World per lens (there is one per source), the null
  layout as a viewable scene, a spatial component in triage priority, opening a scene from a finding's kind, and
  model-assisted field mapping for linked streams.
