# Activity rules (behaviours)

A behaviour says what a unit does in a window: `when` a condition the server computes for each unit, `do` a
choreography the renderer plays over the window's playback. Rules are checked in order and the first that matches a
unit decides. Positions stay measurements: every walk starts and ends at the unit's measured position. Full details:
`world_behaviour_catalog`.

## when

| when | holds if | needs |
|---|---|---|
| `active` | it did anything this window | |
| `acted_on_landmark` | it acted on a place; `filter: {family: x \| [x, y], action: prefix}` | resources |
| `talked` | it sent a message | messages |
| `idle` | on the map, did nothing | |
| `new` | first seen in the last two windows | |
| `stopped` / `paused` | control plane or operator events say so | state_fine |
| `flagged` | part of an open finding | |
| `surge` | activity z >= 2 | |
| `environment_hit` | an operator or the environment acted on it; `filter: {kind: stop\|pause\|message}` | operator |
| `reused_content` | it reused content another unit posted | lineage |

## do (library)

`go_to` (walk to the place it acted on, work, walk back) · `gather` (walk to the nearest plaza, talk, back) ·
`follow` (toward its main partner, talk, back) · `scatter` (away from where it was hit, wait, back) · `wander` (a small
loop) · `pulse` · `glow` · `carry` (a token travels to the place, or from the origin to a reuser) · `stay_home` ·
`fade`. Params: `reach` 0.2-1 (how far toward the target), `radius` 0.2-3 (wander and scatter distance).

## Your own (`do: sequence`)

Compose steps from `go_to`, `gather`, `follow`, `scatter`, `wander`, `return`, `work`, `talk`, `wait`, `pulse`,
`glow`, `carry`, `fade`, each with `dur` (a share of the window, total <= 1). A sequence that walks away must
`return`. No code, no new steps.

## How to choose

1. One rule per thing the stream says a unit did. Order: stopped/paused, moderated (`environment_hit`), reuse,
   talking, working, then `idle` last.
2. The library first; a sequence only when the story needs two places (talk in the square, then go to work).
3. The `meaning` is the legend sentence, in the source's nouns: "Walks to the page it edits, writes there, walks back."
4. Plinth worlds (units are places) cannot walk: `pulse`, `glow`, `carry`, `fade`.
5. Dots (thousands of units) stay still; the busiest 1,500 are choreographed as pawns, so rules cost nothing at scale.

```json
[{"op": "add_behaviour", "behaviour": {"id": "deleted", "when": "environment_hit", "do": "scatter", "params": {"radius": 1.8},
   "meaning": "Scatters away from a page the moderators deleted, then comes back."}},
 {"op": "add_behaviour", "behaviour": {"id": "edit", "when": "acted_on_landmark", "do": "go_to",
   "meaning": "Walks to the page it edits, writes there, walks back."}},
 {"op": "add_behaviour", "behaviour": {"id": "visit", "when": "talked", "do": "sequence", "steps": [
   {"do": "gather", "dur": 0.25}, {"do": "talk", "dur": 0.2}, {"do": "go_to", "dur": 0.2}, {"do": "work", "dur": 0.15},
   {"do": "return", "dur": 0.2}], "meaning": "Talks in the square, then goes to the place it works on."}},
 {"op": "add_behaviour", "behaviour": {"id": "idle", "when": "idle", "do": "wander",
   "meaning": "An idle handle drifts around its spot."}}]
```
