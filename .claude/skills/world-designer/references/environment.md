# The scene: ground, zones, props

The scene tells a viewer what kind of world this is and what each region is for. It is decoration: it never encodes
a measured value, it is drawn muted, and the units and landmarks always read first. Full details:
`world_asset_catalog`.

## Ground (`set_environment {ground}`)

| ground | for |
|---|---|
| `paper` | abstract worlds; the plain page with a faint polar grid |
| `grass` | villages, campuses |
| `stone` | towns, wikis |
| `plaza_tiles` | offices, workshops |
| `grid` | machine swarms, infrastructure |
| `water_edge` | closed worlds (an island) |
| `sand` | catalogs, open fields |

## Zones (`add_zone {zone: {name, around, style, label}}`, at most 8)

A zone is a soft tinted region drawn under every place it matches, with its label on the ground.
`around` is one of `{family: x}` (or a list), `{archetype: plaza}`, `{label: room}`, `{group: all}` (every team's
territory; needs groups). `style`: `lawn`, `paving`, `tiles`, `sand`, `water`, `wood`, `dark`, `plain`. The label is a
few words in the source's nouns ("rooms", "user pages"), never agent text.

## Props (`place_props {props: [{asset, at, near, count, meaning}]}`, at most 16 placements, 480 instances)

Library assets: `tree`, `pine`, `bush`, `rock`, `bench`, `lamp`, `desk`, `chair`, `bookshelf`, `notice_board`,
`server_rack`, `terminal`, `signpost`, `fence`, `small_house`, `office_block`, `tower_block`, `fountain`,
`crate_stack`, `path_tiles`, `planter`, `parasol`. A prop model you made (`add_model` kind `prop`) works too.

| at | places | count |
|---|---|---|
| `landmarks` | around each place matching `near: {family\|archetype\|label: x}` | 1-4 per place |
| `zones` | inside each region of `near: {zone: name}` | 1-6 per region |
| `rim` | evenly around the edge | up to 32 |
| `scatter` | over the open ground | up to 60 |
| `territories` | beside each team | one each |
| `centre` | the middle | one |

## Fixed places (`set_metric {places: districts}`)

When every unit uses most places (a small village, a team sharing one repo), measured place positions all drift to the
centre and the scene collapses. `places: districts` stands each kind of place still, in its own quarter of the ground
(rooms together, documents together, the web at its edge), so zones read clearly and units visibly walk out to what
they work on. Units are still measured; only places are fixed. Use it for villages and offices; leave it off for
large swarms, where where a place sits is itself informative.

## How to choose

1. One zone per kind of place a person should tell apart; style it like the real thing (a room is paving, a document
   desk is wood, a dataset is dark, the web is outside on the lawn).
2. Props make a place legible at a glance: benches and a notice board around a room, a desk beside a document, a
   terminal beside a shell target, a rack beside a dataset, a small house for a user page. One to three per place.
3. Frame the world with a rim (trees, fence, rocks) and a little scatter (lamps, bushes). Fewer is better at scale.
4. Prop `meaning` says "decoration" and what it marks; the legend lists props as scenery that encodes nothing.

```json
[{"op": "set_environment", "ground": "grass"},
 {"op": "add_zone", "zone": {"name": "square", "around": {"family": "chat"}, "style": "paving", "label": "rooms"}},
 {"op": "place_props", "props": [
   {"asset": "bench", "at": "landmarks", "near": {"family": "chat"}, "count": 2, "meaning": "decoration: benches by each room"},
   {"asset": "desk", "at": "landmarks", "near": {"family": "docs"}, "count": 1, "meaning": "decoration: a desk by each document"},
   {"asset": "tree", "at": "rim", "count": 20, "meaning": "decoration: the village edge"}]},
 {"op": "set_reason", "key": "environment", "reason": "a village: rooms are squares, documents are desks"}]
```
