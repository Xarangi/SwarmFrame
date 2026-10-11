# Presets: worked examples
Each is the full WorldSpec we ship for a known source, with its reasons. Start from the nearest one.

## Planted swarm (shape: swarm)

```yaml
# The World for the planted swarm (docs/design/world.md, "Presets: swarm"). Thousands of agents in teams: dots and team blobs from
# afar, pawns at mid zoom, characters only when a few are in view. Every choice has a reason; people and the
# world-designer can change anything with ops, and "Reset" brings this back.
shape: swarm
unit: {model: sprite, of: actor, alpha_by: null}
render: {tier: auto, max_characters: 80, character_by: group, character: newt}
metric:
  sentence: "Distance: agents that work on the same files and hosts, reuse each other's content or behave alike stand together."
  forces: {anchor: 0.3, landmark: 1.0, interact: 0.8, similar: 0.5, repel: 0.6, max_step: 0.08}
  interactions: [co_touch, reply, lineage, shape]
  trail_windows: 12
landmarks_from: object
landmarks:
  - {match: {family: files}, archetype: slab, label: file, reason: "shared files are where coordination shows first"}
  - {match: {family: docs}, archetype: slab, label: document, reason: "documents are work products"}
  - {match: {family: data}, archetype: kiosk, label: dataset, reason: "datasets are shared inputs"}
  - {match: {family: web}, archetype: tower, label: host, reason: "external hosts stand at the edge of the world"}
  - {match: {family: chat}, archetype: plaza, label: board, reason: "team boards are where teams talk"}
  - {match: {kind: other}, archetype: kiosk, label: resource, reason: "anything else, drawn small"}
territories: {by: group}
bindings:
  - {channel: position, quantity: cohort, legend: "Distance: agents that work on the same files and hosts, reuse each other's content or behave alike stand together."}
  - {channel: height, quantity: activity_z, transform: "clamp(-1,3)", legend: "Height: how busy this agent is compared with its own usual."}
  - {channel: colour, quantity: family_dominant, legend: "Colour: the kind of work it mostly does."}
  - {channel: state, quantity: state, legend: "Pose: idle, active, talking, blocked or stopped (stopped comes from operator events)."}
  - {channel: ring, quantity: severity, legend: "Ring: part of a finding (grey watch, amber look, red act)."}
  - {channel: trail, quantity: displacement, legend: "Trail: where it has been; a long trail means its behaviour or partners changed."}
  - {channel: bubble, quantity: messages, legend: "Bubble: it posted to a board (the words are never shown)."}
  - {channel: heat, quantity: landmark_distinct_z, legend: "Ground ring on a file or host: more agents than usual are on it (a crowd)."}
  - {channel: fog, quantity: coverage_age, legend: "Fog: no analyst has read this group closely for a while."}
relations: [arc_touch, arc_reply, arc_lineage, beam]
coverage_fog: true
null_model: {windows: 24, quantile: 0.95}
scenes:
  - {id: overview, title: The whole swarm, camera: overview, question: "Is anything out of shape?", opening: true}
  - {id: crowds, title: Crowded files and hosts, camera: top, target: crowding, finding_kind: convergence,
     question: "Which places draw more agents than usual, and from which teams?"}
  - {id: drift, title: Who is drifting, camera: top, target: drift, question: "Which agents are changing how they behave or whom they work with?"}
  - {id: saydo, title: Talking, not moving, camera: region, target: still_talking, finding_kind: say_do_mismatch,
     question: "Which agents post updates without doing anything new?"}
  - {id: operator, title: Operator actions, camera: region, target: beams, finding_kind: environment,
     question: "Where did operators step in, and what happened next?"}
control: {enabled: false}
reasons:
  shape: "a large population in teams acting on shared files, hosts and boards"
  render: "up to 5,000 agents: dots and team blobs from afar, instanced pawns at mid zoom, characters only near"
  territories: "teams are territories, each with a gate where new members walk in"
  control: "a replay: SwarmFrame observes these agents and cannot control them"
```

## AI Village (shape: village)

```yaml
# The World for AI Village (docs/design/world.md, "Presets: village"). About twenty named agents who talk: every agent is
# a character, rooms are plazas, and replies pull agents together more than behavioural similarity does.
shape: village
unit: {model: sprite, of: actor, alpha_by: null}
render: {tier: characters, max_characters: 80, character_by: unit, character: newt}
metric:
  sentence: "Distance: agents who talk in the same rooms, answer each other and work on the same documents stand together."
  forces: {anchor: 0.25, landmark: 1.1, interact: 1.2, similar: 0.3, repel: 0.7, max_step: 0.1}
  interactions: [co_touch, reply, lineage, shape]
  trail_windows: 18
landmarks_from: object
landmarks:
  - {match: {family: chat}, archetype: plaza, label: room, reason: "rooms are where the village coordinates"}
  - {match: {family: docs}, archetype: slab, label: document, reason: "shared documents are the work product"}
  - {match: {family: sheets}, archetype: slab, label: sheet, reason: "sheets are shared work too"}
  - {match: {family: web}, archetype: tower, label: site, reason: "external sites stand at the edge"}
  - {match: {family: research}, archetype: tower, label: site, reason: "research happens out on the web"}
  - {match: {family: computer}, archetype: kiosk, label: app, reason: "apps on the agents' computers"}
  - {match: {kind: other}, archetype: kiosk, label: place, reason: "anything else, drawn small"}
territories: {by: none}
bindings:
  - {channel: position, quantity: cohort, legend: "Distance: agents who talk in the same rooms, answer each other and work on the same documents stand together."}
  - {channel: height, quantity: activity_z, transform: "clamp(-1,3)", legend: "Height: how busy this agent is compared with its own usual."}
  - {channel: colour, quantity: family_dominant, legend: "Colour: the kind of work it mostly does."}
  - {channel: state, quantity: state, legend: "Pose: idle, active, talking or working."}
  - {channel: ring, quantity: severity, legend: "Ring: part of a finding (grey watch, amber look, red act)."}
  - {channel: trail, quantity: displacement, legend: "Trail: where it has been today."}
  - {channel: bubble, quantity: messages, legend: "Bubble: it said something in a room (the words are never shown here)."}
  - {channel: banner, quantity: task_label, legend: "Banner: what the group is working on (stated goals, or an analyst's reading)."}
  - {channel: heat, quantity: landmark_distinct_z, legend: "Ground ring on a room or document: more agents than usual are there."}
  - {channel: fog, quantity: coverage_age, legend: "Fog: no analyst has read this group closely for a while."}
relations: [arc_touch, arc_reply, arc_lineage]
coverage_fog: true
null_model: {windows: 24, quantile: 0.95}
scenes:
  - {id: square, title: The village square, camera: overview, question: "Is anything out of shape?", opening: true}
  - {id: saydo, title: Saying and not doing, camera: region, target: still_talking, finding_kind: say_do_mismatch,
     question: "Who talks about work without doing any?"}
  - {id: docs, title: Shared documents, camera: top, target: crowding, finding_kind: convergence,
     question: "Which documents and rooms draw a crowd, and who is there?"}
  - {id: day, title: One agent's day, camera: follow, question: "What did this agent do, in order, and who was it near?"}
control: {enabled: false}
reasons:
  shape: "a small population that talks: every agent is a character with a trail"
  render: "about twenty agents: full characters, each its own kind so you can tell them apart"
  forces: "replies and rooms pull harder than behavioural similarity: this population coordinates by talking"
  territories: "one village, no teams"
  control: "a replay of a recorded village: read-only"
```

## Transluce (shape: targets)

The shipped preset (`packs/transluce/world.yaml`): a map of targets laid out by their method mix.

```yaml
# The World for Transluce: a map of what autonomous agents reached, and how (docs/design/world.md, "Presets: targets").
# This is a historical catalog with no agent identities, so the units are TARGETS (the data sources agents went
# after), never agents. Each method class is a corner of the map; each target stands where its whole-record mix
# of methods puts it. Tall towers are the most reported targets; bands show how they were reached; glass means the
# catalog only calls the reports on it suggestive.
shape: targets
unit: {model: plinth, of: object, alpha_by: grade}
render: {tier: auto, max_characters: 0, character_by: none, character: newt}
metric:
  sentence: "Each tower is a targeted data source. The corners are the three ways agents reached targets; a tower stands near the methods used on it."
  layout: mix
  forces: {anchor: 0.35, landmark: 1.2, interact: 0.0, similar: 0.6, repel: 0.6, max_step: 0.08}
  interactions: []
  trail_windows: 8
landmarks_from: family
landmarks:
  - {match: {kind: other}, archetype: road, label: method, reason: "each method class is an axis from the centre to its corner"}
territories: {by: none}
bindings:
  - {channel: position, quantity: cohort, legend: "Position: a tower stands between the corners in proportion to the methods used on it; at a corner, only that method."}
  - {channel: height, quantity: volume, transform: "log", legend: "Height: how many reports name this target over the whole record (log scale)."}
  - {channel: colour, quantity: family_dominant, legend: "Bands: the share of its reports by each method, bottom to top in the order of the corners."}
  - {channel: material, quantity: grade, legend: "Solid: most reports on it are graded significant; glassy: mostly suggestive."}
  - {channel: ring, quantity: severity, legend: "Ring: part of a finding, such as a burst (grey watch, amber look, red act)."}
  - {channel: trail, quantity: displacement, legend: "Trail: the target's method mix shifted recently."}
relations: []
coverage_fog: false
null_model: {windows: 24, quantile: 0.95}
scenes:
  - {id: map, title: The map of targets, camera: overview, question: "What did agents go after, and how?", opening: true}
  - {id: bursts, title: Bursts, camera: top, target: activity, finding_kind: burst, question: "Which targets spiked recently?"}
control: {enabled: false}
# The scene: no characters (there are no agent identities). A paved square at each method's corner, muted city
# blocks across the map, rocks at the edge. Decoration only; towers stay where their method mix puts them.
environment:
  ground: sand
  zones:
    - {name: methods, around: {archetype: road}, style: paving, label: methods}
  props:
    - {asset: path_tiles, at: zones, near: {zone: methods}, count: 3, meaning: "decoration: paths at each method's corner"}
    - {asset: signpost, at: landmarks, near: {archetype: road}, count: 1, meaning: "decoration: a signpost at each method"}
    - {asset: office_block, at: scatter, count: 10, meaning: "decoration: muted city blocks"}
    - {asset: rock, at: rim, count: 16, meaning: "decoration: the edge of the map"}
# Targets are places, so they cannot walk: they pulse.
behaviours:
  - {id: reported, when: active, do: pulse, meaning: "A ring pulses under a target when new reports name it this window."}
reasons:
  shape: "no agent identities: targets carry the story, so units are places (towers)"
  layout: "with three methods and about forty targets, a deterministic mix map is readable at a glance; a force layout was not"
  render: "tens of targets: every tower labelled"
  forces: "positions come from each target's method mix, not from forces"
  control: "a public catalog: read-only"
  environment: "a sand map with a paved square at each method's corner and muted city blocks; decoration only"
  behaviours: "targets are places, not actors: they pulse when new reports name them"
```

## Live Claude Code (shape: swarm_control)

```yaml
# The World for a live Claude Code swarm (docs/design/world.md, "Presets: swarm_control"). The village shape plus control:
# files are slabs, tools colour the agents, denials show as blocked, and clicking an agent offers the Control
# page's actions (with the same approval rules).
shape: swarm_control
unit: {model: sprite, of: actor, alpha_by: null}
render: {tier: auto, max_characters: 80, character_by: group, character: robot}
metric:
  sentence: "Distance: agents that edit the same files and run the same kinds of tools stand together."
  forces: {anchor: 0.3, landmark: 1.1, interact: 0.8, similar: 0.5, repel: 0.6, max_step: 0.1}
  interactions: [co_touch, reply, lineage, shape]
  trail_windows: 12
landmarks_from: object
landmarks:
  - {match: {family: files}, archetype: slab, label: file, reason: "files are what Claude Code agents edit"}
  - {match: {family: docs}, archetype: slab, label: document, reason: "documents are files too"}
  - {match: {family: web}, archetype: tower, label: site, reason: "fetched sites stand at the edge"}
  - {match: {family: shell}, archetype: kiosk, label: command target, reason: "what shell commands touch"}
  - {match: {family: chat}, archetype: plaza, label: channel, reason: "where agents message each other"}
  - {match: {kind: other}, archetype: kiosk, label: resource, reason: "anything else, drawn small"}
territories: {by: group}
bindings:
  - {channel: position, quantity: cohort, legend: "Distance: agents that edit the same files and run the same kinds of tools stand together."}
  - {channel: height, quantity: activity_z, transform: "clamp(-1,3)", legend: "Height: tool calls now, compared with the agent's own usual."}
  - {channel: colour, quantity: family_dominant, legend: "Colour: the kind of tool it mostly uses."}
  - {channel: state, quantity: state, legend: "Pose: working, talking, blocked (denials), paused or stopped (from the control plane)."}
  - {channel: ring, quantity: severity, legend: "Ring: part of a finding (grey watch, amber look, red act)."}
  - {channel: trail, quantity: displacement, legend: "Trail: where it has been; a long trail means it moved to other files or tools."}
  - {channel: heat, quantity: landmark_distinct_z, legend: "Ground ring on a file: more agents than usual are editing it."}
  - {channel: fog, quantity: coverage_age, legend: "Fog: no analyst has read this group closely for a while."}
relations: [arc_touch, arc_reply, beam]
coverage_fog: true
null_model: {windows: 24, quantile: 0.95}
scenes:
  - {id: overview, title: The swarm at work, camera: overview, question: "Is anything out of shape?", opening: true}
  - {id: crowds, title: Contested files, camera: top, target: crowding, finding_kind: convergence,
     question: "Which files have more agents on them than usual?"}
  - {id: blocked, title: Blocked and waiting, camera: region, target: blocked, question: "Which agents are stuck on denials or waiting for approval?"}
  - {id: operator, title: Operator actions, camera: region, target: beams, finding_kind: environment,
     question: "Where did someone pause or stop agents, and what happened next?"}
control: {enabled: true}
reasons:
  shape: "a live swarm with a control plane attached"
  render: "robots for Claude Code agents; pawns and dots when there are many"
  control: "the control plane is attached: pause, interrupt, message and stop from the World, with approvals"
```

## German Wiki (shape: wiki)

The adapter is parked until the export format is probed. Designed against the documented shape: about 3.1k handles
on 4.6k pages; sprites at alpha 0.55 because a handle is not a stable agent; pages as slabs grouped into namespace
districts, question pages in a central square; lineage arcs (solid with exposure, dashed without); moderator deletion
sweeps as beams; territories only as inferred handle groups (hatched). Scenes: the wiki; the June surge (sweep); where
the text came from; after the sweeps. Never join handles to IPs: identity is partial on purpose.
