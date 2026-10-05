# The fixed library

Everything here is procedural geometry driven by data. You combine it; you cannot add to it.

## Unit models

| id | Use for | Notes |
|---|---|---|
| `sprite` | agents with identities | rendered by tier: character (near / few), pawn (instanced capsule), dot (instanced point) |
| `plinth` | units that are places (targets, pages) | column; height = activity vs usual; cap colour = family; material = grade |

**Characters** (sprites, near or few): `newt` (default), `human` (scientist), `frog`, `owl`, `fox`, `robot`.
`render.character_by`: `group` (one character kind per team), `unit` (each agent its own kind, for villages),
`none` (all `render.character`). Colour always comes from the workstream family, never from the character.

**States** (sprite poses): idle, active, talking, working, blocked, paused, stopped. Only states the stream supports
are shown; `active` is the floor.

## Attachments

ring (severity only) · trail · bubble (shape, never words) · label (ids, near only) · banner (cohort task; translucent
when inferred) · badge · tether (aliases).

## Landmark archetypes

slab (document, file, page) · tower (external host, site, API) · plaza (room, channel) · kiosk (board, queue,
dataset, anything else) · road (a method; worlds where units are places) · gate (where new units enter a
territory) · district (a grouping of landmarks). Rules map kinds to archetypes: `{match: {family: files}, archetype:
slab, label: file, reason: ...}`; `{match: {prefix: "host:"}, ...}`; `{match: {kind: other}, ...}` catches the rest.

Models made for this stream (≤ 10 per world): landmarks, unit characters and scenery built from the part kit in `models.md`, each with a one-sentence meaning; check with `world_model_check` first.

## Relations

arc_touch (co-touched a place this window) · arc_reply (replied; hatched when inferred) · arc_lineage (reused
content; solid with exposure, dashed without) · beam (operator or environment action).

## Channels and quantities

Channels: position, height, colour, alpha, material, state, ring, trail, bubble, banner, badge, size, heat, width,
age, arc, beam, fog, territory. Reserved: colour → a category (family_dominant, action_dominant, group); ring →
severity; height → activity_z, activity, landmark_distinct_z, landmark_events, grade; alpha / material → certainty
(identity_confidence, grade).

Quantities: activity, activity_z, rate_change, self_shift, family_dominant, action_dominant, messages, errors,
severity, displacement, isolation, drift, crowding, approach, landmark_events, landmark_distinct_z, coverage_age,
identity_confidence, grade, group, cohort, task_label, state, since_last, new_units, road_age. Transforms: linear,
log, zscore, rank, clamp(a,b).

## Forces (allowed ranges)

anchor 0.05–1.0 · landmark 0–2 · interact 0–2 · similar 0–1.5 · repel 0.2–1.5 · max_step 0.02–0.2. Interactions:
co_touch, reply, lineage, shape (the same uncommon message shape, a chain over the last 12 windows).

## Cameras

overview · follow (a unit) · at (a landmark) · region (a cohort, territory or flag set) · sweep (a time span) ·
top (the unit or landmark with the highest value of a feature: crowding, drift, isolation, activity).
