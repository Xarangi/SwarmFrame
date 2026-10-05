# Making a model

A model is a list of parts. The server validates it (`world_model_check`, and again on `add_model`); the dashboard
compiles it once and draws it in its own palette, instanced. Nothing you write runs in the viewer's browser.

## Space

- y is up; the ground is y = 0; +z faces the default camera.
- Units are world units. A premade agent is about 1 tall. A slab landmark is 1.3 wide. Landmarks are scaled 0.75 to
  1.35 by how busy the place is, so design them at "normal" size.
- Each part is centred on `at` (except `dome`, whose `at` is the centre of its flat face, and `lathe`, whose `at` is
  the origin of its profile). `rot` is `[x, y, z]` in degrees, applied x, then y, then z.

## Kinds and limits

| kind | used by | parts | triangles | x and z | height |
|---|---|---|---|---|---|
| `landmark` | a landmark rule's `model` | 24 | 4,000 | ±1.6 | 4.0 |
| `unit` | `render.cast` or `render.character` (characters tier only) | 16 | 2,500 | ±0.5 | 1.3 |
| `prop` | `scenery` (centre, rim, territories; 120 instances) or environment props (`environment.md`) | 32 | 4,000 | ±3 | 6 |

At most 10 models per World.

## Shapes (`size`)

| shape | size | notes |
|---|---|---|
| `box` | `[width, height, depth]` | |
| `cylinder` | `[radius_top, radius_bottom, height]` | a radius of 0 makes a cone |
| `cone` | `[radius, height]` | point up |
| `sphere` | `[radius]` | about 340 triangles: use few |
| `dome` | `[radius]` | half sphere, flat face down |
| `capsule` | `[radius, length]` | total height = length + 2·radius; about 320 triangles |
| `torus` | `[radius, tube, arc_degrees]` | stands in the x-y plane; arc 180 is an arch; rot `[90,0,0]` lays it flat |
| `disc` | `[radius]` | 0.02 thick |
| `ring` | `[inner_radius, outer_radius]` | 0.02 thick |
| `prism` | `[radius, height, sides]` | 3 to 8 sides |
| `wedge` | `[width, height, depth]` | a ramp: full height at −z, zero at +z |
| `lathe` | `[[r, y], ...]` | 2 to 12 points, bottom to top: vases, bottles, towers, lamp posts |

## Colour, material, animation

- `colour` is a theme token, never a hex value, so the model works in light and dark: `ink`, `paper`, `stone`, `wood`,
  `metal`, `glass`, `leaf`, `water`, `warm`, `cool`, `shadow`, `accent` (sparingly), and **`tint`**.
- **`tint` is the data colour**: a unit's workstream, a landmark's kind. Unit models need at least one tint part
  (the body, a scarf, a stripe). Scenery may not use tint.
- `material`: `matte` (default), `gloss`, `metal`, `glass` (translucent; not on units, because translucency means an
  uncertain identity), `glow` (unlit, reads as a light: screens, lamps, status strips).
- `anim`: `spin` (dishes, fans, rotors), `sway` (antennae, flags, plants), `bob` (floating things; not on units, whose
  bob is the "active" pose). Units are also posed by state like the premade cast (idle, working, talking, waiting,
  blocked, stopped), so do not try to show state with parts.

## Procedure

1. Say in one sentence what the model stands for, in the stream's nouns. That sentence is its `meaning` and goes in
   the legend.
2. Sketch 3 to 10 parts: one big silhouette part first, then two or three features that make it recognisable, then
   at most a few details. Small worlds are seen from 10 to 30 units away; details under 0.05 vanish.
3. `world_model_check`. Read `errors` and `warnings`, then the `front`, `side` and `top` silhouettes (each letter is
   a part, nearest wins). Ask: is the shape recognisable from the front? Is anything floating? Does the top view show
   the footprint you meant?
4. Fix and re-check until there are no errors and the silhouettes read as the thing.
5. `add_model`, then use it, then `set_reason` with the key `model:<id>`.

## Examples

A host as a server rack (landmark):

```json
{"id": "server-rack", "kind": "landmark", "meaning": "A host the agents call, drawn as a rack of servers.",
 "parts": [
  {"shape": "box", "size": [0.9, 1.8, 0.7], "at": [0, 0.9, 0], "colour": "metal", "material": "metal", "name": "cabinet"},
  {"shape": "box", "size": [0.8, 0.06, 0.04], "at": [0, 0.6, 0.36], "colour": "tint", "material": "glow", "name": "strip"},
  {"shape": "box", "size": [0.8, 0.06, 0.04], "at": [0, 1.2, 0.36], "colour": "tint", "material": "glow", "name": "strip"},
  {"shape": "dome", "size": [0.22], "at": [-0.2, 1.8, 0], "colour": "stone", "anim": "spin", "name": "dish"}]}
```

An agent as a small drone (unit):

```json
{"id": "drone", "kind": "unit", "meaning": "An agent, drawn as a small drone.",
 "parts": [
  {"shape": "capsule", "size": [0.18, 0.3], "at": [0, 0.5, 0], "colour": "tint", "material": "gloss", "name": "body"},
  {"shape": "cylinder", "size": [0.3, 0.3, 0.02], "at": [0, 0.85, 0], "colour": "ink", "anim": "spin", "name": "rotor"},
  {"shape": "cylinder", "size": [0.03, 0.03, 0.3], "at": [0, 0.15, 0], "colour": "metal", "name": "leg"}]}
```

Then:

```json
[{"op": "add_model", "model": {"id": "server-rack", "...": "..."}},
 {"op": "update_landmark", "index": 0, "changes": {"model": "server-rack"}},
 {"op": "add_model", "model": {"id": "drone", "...": "..."}},
 {"op": "set_render", "cast": ["drone"]},
 {"op": "set_reason", "key": "model:server-rack", "reason": "hosts are most of the places; a rack reads as 'a server' at a glance"}]
```
