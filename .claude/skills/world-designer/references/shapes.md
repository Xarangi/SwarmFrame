# Picking the shape

Read `world_features_available` and go down this list; stop at the first match; start from that preset
(`presets.md`) and adapt.

| If the table says | Shape | Start from | Adaptations to consider |
|---|---|---|---|
| `identity` absent, `resources` present | **targets** | Transluce | units are places (plinths); `landmarks_from: family` makes methods roads; drop roads and lay plinths by co-occurrence if there is no method-like family; `material ← grade` only if `grade` is observed |
| `identity` absent, no resources | **stripped** | — | there is little to draw: activity over time only; say so in `open_questions` |
| `identity_partial` present | **wiki** | German Wiki (planned) | sprites with `alpha_by: identity_confidence`; tethers for aliases; territories only if groups are observed or inferred; lineage arcs if artifacts |
| `control` observed | **swarm_control** | Claude Code | files as slabs, tools as colour, denials as `blocked`, beams for pauses and stops, control actions on click |
| `messages` present and ≤ ~60 units | **village** | AI Village | every agent a character (`character_by: unit`); rooms as plazas; replies and rooms pull harder than similarity; a follow scene |
| no `resources` | **stripped** | planted swarm minus landmarks | position from the behaviour signature alone (`landmark` and `interact` forces 0, `similar` high); legend lists what is unknown; ask the person which field holds the place an agent acts on |
| otherwise | **swarm** | planted swarm | territories by group; gates; the crowd scene tied to convergence; drop bubbles if there are no messages |
| neither `actor` nor `object` | none | — | refuse: write which field would make a World possible |

## The population changes the render tier, not the shape

A swarm of 40 agents and one of 4,000 have the same shape; only the tier differs (`SKILL.md` rule 9). For a live
stream whose population will grow, prefer `auto`.

## Levels of poverty

| The stream has | The World can show |
|---|---|
| actor, action, time | units placed by behaviour signature, height by activity, colour by action family; no landmarks, no arcs |
| + object | landmarks (one generic archetype unless kinds are known), co-touch arcs, crowd rings: the convergence reading |
| + family / resource kinds | an archetype per kind, districts |
| + messages | bubbles, plazas, reply arcs (derived: same room within a minute) |
| + artifacts | lineage arcs, message-shape interactions, the say-do reading |
| + groups | territories and gates |
| + environment / control | operator beams; the control menu |
| + analysts with models on | cohort banners and inferred states (translucent / hatched) |
