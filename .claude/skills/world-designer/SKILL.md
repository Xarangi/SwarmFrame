---
name: world-designer
description: Design SwarmFrame's World, the 3D model of a swarm in which position is a measurement, for whatever stream is being monitored. Use when composing or changing the World, choosing what distance means, mapping places to landmarks, designing the scene (ground, zones, props) and the activity rules (what units do when they write, talk, idle or get stopped), choosing encodings, scenes or the render tier, making a new 3D model, or when a new source is connected and needs a World.
---

# World designer

The World is a 3D model of the swarm where **where a unit stands is a measurement**: units that work on the same
places, interact, or behave alike stand together; a crowd at a shared file is literally a crowd at a landmark; a
unit whose behaviour changes walks away and leaves a trail. You design it for one stream by **composing from a premade
library**, and, when that library cannot say what something is, by **making a new 3D model** from the model kit.
You never write code or textures, never add channels, and never put agent-written text anywhere.

SwarmFrame observes; it does not control most swarms and did not write their logging. What the World can show is
whatever the stream lets us recover. Your first job is to find out what that is.

## Standing rules

1. **Compose from the library first** (`world_catalog`). If the data wants an encoding the grammar lacks, put it in
   `open_questions`; never approximate it by misusing a channel.
2. **Make a model when the library cannot say what a thing is** (rule 10 and `references/models.md`). A model
   changes what something looks like, never what is measured.
3. **Every choice has a reason**, in the source's nouns (`set_reason`). A world without reasons is rejected.
4. **No agent text.** Labels are ids; bubbles show that a message was sent, never its words; annotations are written
   by people or by you, never copied from agents.
5. **Position uses derived features only.** Inferred features (analyst labels) may label, tint or hatch; they never
   move anything. The validator enforces it.
6. **Draw uncertainty.** Anything inferred is translucent or hatched, and its legend sentence says "inferred".
7. **Prefer fewer encodings.** At most six on each unit (height, colour, state, ring, bubble, alpha, ...) and at most
   four on the ground (heat, fog, territory, ...); position and trail are the layout itself. If two encodings answer
   the same question, keep the one with the stronger status (observed > derived > inferred).
8. **Preview before committing.** Run `world_preview`; keep a metric only if `separates_beyond_chance` is true (or
   say why the stream cannot separate, e.g. too few units yet).
9. **Latency is a design constraint.** Pick the render tier for the population, not for looks:

   | Units on the map | Render tier | Why |
   |---|---|---|
   | up to ~80 | `characters` (the cast: newt, human, frog, owl, fox, robot, plus unit models you made) | each agent is worth recognising; ~30 meshes each is fine |
   | ~80 to ~2,000 | `pawns` (instanced capsules, one draw call per state) | 60 fps on an integrated GPU |
   | ~2,000 and more | `dots` (instanced points) with cohort blobs from afar | thousands of units, still 60 fps; zooming in shows pawns |
   | unsure or changing | `auto` | the renderer switches by count and zoom |

   Never choose `characters` for more than ~80 units in view. A unit model you make is drawn only in the characters
   tier (and for the ~40 agents nearest the camera when zoomed in); pawns and dots stay as they are, so a custom
   character never costs anything at scale. Landmark and scenery models are compiled once and instanced. Trails are
   drawn only for the ~200 most-moved units. Labels appear only near the camera. The layout runs on the server in
   numpy (≈20–40 ms per window at 1,000 units), so do not ask for per-unit work that scales with the square of the
   population.
10. **When to make a model.** Make one when the stream's agents or places have a kind that no premade character or
    archetype conveys and seeing that kind helps a person read the swarm: hosts as server racks, mailboxes for mail
    queues, benches for lab instruments, drones for robot agents, a plaza with a podium for a broadcast channel.
    For scenery, use the prop library first (rule 11); make a prop model only when no asset says what a place is. **Control** appears only when `world_features_available` says
    `control: observed`, and then only as the Control page's actions with its approval rules.

11. **Design the scene and the activity.** A World without them is dots on a disc. Choose a ground, zones that match
    the places (paved squares around rooms, desks around documents), and props that make places legible
    (`references/environment.md`); then activity rules: what a unit does when it writes, talks, idles, is new, gets
    stopped or moderated (`references/behaviours.md`). Library first; compose a `sequence` only when no entry says it.
    Props never encode a value and are drawn muted; a behaviour is an excursion that returns to the measured position,
    and its `meaning` is a legend sentence in the source's nouns.

## Procedure (required outputs at each step)

1. **Survey.** Call `world_features_available` and `stream_profile`. Write: what one unit is (an agent, a handle, a
   target), what the places are, what the acts are, what the groups are; which features are observed, derived,
   inferred or absent (copy the table's words); the suggested shape and whether you agree.
2. **Shape.** Pick the shape with `references/shapes.md` (first match wins) and start from the matching preset in
   `references/presets.md`. Adapt; do not start from nothing.
3. **Metric.** One legend sentence saying what distance means here, in the source's nouns. Choose the interactions
   that pull units together (co_touch, reply, lineage, shape) from the available features, and force weights within
   the allowed ranges, with a reason tied to the data's time scale and population.
4. **Vocabulary.** Map each kind of place to a landmark archetype with a reason; decide territories (groups, or none);
   the unit model (sprite or plinth); the render tier (rule 9); the character for sprites (`character_by`: group,
   unit, fixed; `cast` to choose which characters).
5. **Models (only if rule 10 applies).** For each: say what it stands for, sketch its parts, run
   `world_model_check`, read the three silhouettes, fix and re-check until it reads as the thing at a glance, then
   `add_model` and use it (`update_landmark` with `model`, `set_render` with `cast` or `character`, or `add_scenery`).
   Follow `references/models.md`.
6. **Scene and activity (rule 11).** `world_asset_catalog`, then `set_environment`, `add_zone`, `place_props`;
   `world_behaviour_catalog`, then one `add_behaviour` per thing the stream says a unit did (order matters: first
   match wins; put stopped and moderated before work, idle last). Write a reason for each with `set_reason`.
7. **Encodings.** The binding list: channel, quantity, status, legend sentence. Drop any whose feature is absent
   (the validator will refuse it anyway). Add at most one stream-specific encoding.
8. **Scenes.** The opening overview and up to four scenes, each with the question it answers and, where one fits, the
   finding kind it serves (so "Show me" on a finding opens it).
9. **Preview.** `world_preview`: report separation vs null, units moving beyond chance, crowding, recommended tier.
10. **Critic.** Go through the checklist below; fix and re-preview until every item passes; list the open questions.

## Critic checklist

- [ ] No binding rests on an absent feature; inferred bindings say "inferred" in their legend.
- [ ] Colour = a category; ring = severity; height = activity-like; alpha/material = certainty.
- [ ] Position uses derived features only.
- [ ] No agent text anywhere.
- [ ] Opening scene is an overview; ≤ 6 encodings on a unit and ≤ 4 on the ground; every scene has a question.
- [ ] Unit model matches identities (sprites need identities; otherwise plinths); control only with a control plane.
- [ ] Render tier fits the population (rule 9).
- [ ] Null model on; preview separates beyond chance, or the reason it cannot is written down.
- [ ] Every model has a meaning, passed `world_model_check` with no errors, is used somewhere, and has a reason; unit
      models carry `tint`; scenery is muted and says it encodes nothing.
- [ ] The scene has a ground, zones that match the places, and props that make them legible; no prop encodes data.
- [ ] Every behaviour's condition is available in this stream, walks return home, and its meaning reads as a legend
      sentence; plinth worlds only pulse, glow, carry or fade.
- [ ] Every landmark mapping, binding, scene, model, behaviour and force weight has a reason.

## Ops

`world_edit` takes a list of ops, applied atomically and versioned: `set_shape`, `set_unit`, `set_render`,
`set_metric`, `set_landmarks_from`, `add_landmark`, `update_landmark`, `remove_landmark`, `add_model`, `update_model`,
`remove_model`, `add_scenery`, `remove_scenery`, `set_environment`, `add_zone`, `remove_zone`, `place_props`,
`remove_props`, `add_behaviour`, `update_behaviour`, `move_behaviour`, `remove_behaviour`, `set_territories`, `add_binding`, `update_binding`,
`remove_binding`, `set_relations`, `set_fog`, `set_null_model`, `add_scene`, `update_scene`, `move_scene`,
`remove_scene`, `set_opening`, `add_annotation`, `remove_annotation`, `set_control`, `set_reason`, `reset_world`.
See `references/primitives.md` for every value, `references/models.md` for the model kit, and
`references/environment.md` and `references/behaviours.md` for the scene and the activity rules.

```json
[{"op": "set_render", "tier": "dots"},
 {"op": "set_metric", "sentence": "Distance: agents that edit the same files stand together.", "forces": {"landmark": 1.2}},
 {"op": "add_scene", "scene": {"id": "crowds", "title": "Contested files", "camera": "top", "target": "crowding",
   "question": "Which files have more agents than usual?", "finding_kind": "convergence"}},
 {"op": "set_environment", "ground": "grid"},
 {"op": "add_behaviour", "behaviour": {"id": "edit", "when": "acted_on_landmark", "do": "go_to",
   "meaning": "Walks to the file it edits, works there, walks back."}},
 {"op": "set_reason", "key": "render", "reason": "3,000 agents: dots from afar, pawns when zoomed in"}]
```
