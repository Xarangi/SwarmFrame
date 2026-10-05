# Presets: worked examples
Each is the full WorldSpec we ship for a known source, with its reasons. Start from the nearest one.

## Planted swarm (shape: swarm)

```yaml
# The World for the planted swarm (docs/WORLD_PLAN.md §6b). Thousands of agents in teams: dots and team blobs from
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
# The World for AI Village (docs/WORLD_PLAN.md §6b, preset 1). About twenty named agents who talk: every agent is
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

```yaml
# The World for Transluce (docs/WORLD_PLAN.md §6b, preset 2). There are no agents to move: each target is a
# plinth, method classes are roads radiating from the centre, and targets stand along the roads that reach them.
shape: targets
unit: {model: plinth, of: object, alpha_by: grade}
render: {tier: auto, max_characters: 0, character_by: none, character: newt}
metric:
  sentence: "Distance: targets reached by the same methods in the same weeks stand together, along those methods' roads."
  forces: {anchor: 0.35, landmark: 1.2, interact: 0.0, similar: 0.6, repel: 0.6, max_step: 0.08}
  interactions: []
  trail_windows: 8
landmarks_from: family
landmarks:
  - {match: {kind: other}, archetype: road, label: method, reason: "each method class is a road; a target reached by several methods sits near a junction"}
territories: {by: none}
bindings:
  - {channel: position, quantity: cohort, legend: "Distance: targets reached by the same methods in the same weeks stand together."}
  - {channel: height, quantity: activity_z, transform: "clamp(-1,3)", legend: "Height: reports on this target now, compared with its own usual (a spike is a burst)."}
  - {channel: colour, quantity: family_dominant, legend: "Cap colour: the method that reaches it most."}
  - {channel: ring, quantity: severity, legend: "Ring: part of a finding (grey watch, amber look, red act)."}
  - {channel: trail, quantity: displacement, legend: "Trail: the target's method mix changed."}
  - {channel: material, quantity: grade, legend: "Solid: the catalog rates reports on it significant; glassy: only suggestive."}
  - {channel: fog, quantity: coverage_age, legend: "Fog: no analyst has read this group of targets closely for a while."}
relations: []
coverage_fog: true
null_model: {windows: 24, quantile: 0.95}
scenes:
  - {id: map, title: The map of targets, camera: overview, question: "Which methods reach which targets?", opening: true}
  - {id: bursts, title: This week's bursts, camera: top, target: activity, finding_kind: burst, question: "Which targets spiked?"}
  - {id: new, title: New methods, camera: top, target: new_roads, finding_kind: new_method, question: "Which methods appeared on targets for the first time?"}
  - {id: grades, title: Grades over time, camera: sweep, question: "Do grades rise or fall as reports pile up?"}
control: {enabled: false}
reasons:
  shape: "no agent identities: targets carry the story, so units are places"
  render: "thousands of targets at most: plinths, instanced"
  forces: "methods (roads) pull hardest; similarity of method mix second; there are no interactions between targets"
  control: "a public catalog: read-only"
```

## Live Claude Code (shape: swarm_control)

```yaml
# The World for a live Claude Code swarm (docs/WORLD_PLAN.md §6b, preset 5). The village shape plus control:
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

## German Wiki (shape: wiki), planned

The adapter is parked until the export format is probed. Designed against the documented shape: about 3.1k handles
on 4.6k pages; sprites at alpha 0.55 because a handle is not a stable agent; pages as slabs grouped into namespace
districts, question pages in a central square; lineage arcs (solid with exposure, dashed without); moderator deletion
sweeps as beams; territories only as inferred handle groups (hatched). Scenes: the wiki; the June surge (sweep); where
the text came from; after the sweeps. Never join handles to IPs: identity is partial on purpose.
