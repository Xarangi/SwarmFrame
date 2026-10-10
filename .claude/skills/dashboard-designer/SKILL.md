---
name: dashboard-designer
description: Compose SwarmFrame dashboard pages and panels around whatever data stream is being monitored. Use when asked to customize, design, add or change dashboard views, pages, the Brief, or saved lenses, or when a new source is connected and the dashboard should fit it.
---

# Dashboard designer

You compose the oversight dashboard around a data stream you have not seen before. The dashboard is small by
default and grows only when the viewer wants it to. It answers, in order: is anything wrong, how big is it, and what
should I do next. You work only from structure: the stream profile never contains agent-written text, and views
cannot show it.

## The shape of the dashboard

- **The Brief** is the home page (page id `brief`). It always shows a status sentence, glance numbers, a ranked
  "needs attention" list with a recommended next step on every row, and a short "what changed" line. You configure
  those with `set_brief` (`glance`, `attention_rows`, `min_severity`, `show_changes`, `world`: the World beside the attention list). Its own panels are **one or
  two signature views**: the views that best show this particular stream at a glance.
- **Activity pages** hold the stream's own structure. **At most three** when composing from scratch, each with a
  one-line `reason` saying why this stream earned it ("no identities, so targets and methods describe the population").
- **The machinery** (reading plan, groups of similar agents, coverage, the analyst team, monitor health) lives under
  the hood. Do not compose it onto pages unless the viewer asks; `set_machinery` adds it as one page.
- **Anything can go anywhere** when the viewer asks: any built-in or view on any page, the Brief included.
- **Lenses** are saved layouts per scenario ("Incident review", "Weekly report"). Build the layout, then save it with
  `dashboard_lens` action `save`.

## Tools

- `stream_profile`: capabilities, fields with cardinality and top values, categorical attributes, the rate over time
  with a suggested bucket, entity counts, the scale layer.
- `view_catalog`: primitives, the built-ins this source supports, the query language, the ops, glance numbers.
- `dashboard_get`: what is there now, including the Brief's settings and the lenses.
- `view_preview`: run a candidate view against live data. Always preview before adding.
- `dashboard_edit`: apply ops atomically; nothing applies if one fails. Every change is versioned and undoable.
- `dashboard_undo`, `dashboard_lens`.
- `theme_options`, `theme_get`, `theme_set`, `theme_undo`: the look (see below).

## The look

You change how the dashboard looks only through `theme_set`, never with CSS or code. The design space is fixed and
every value is checked: a preset (observatory, paper, console, clinic, signal), light or dark, an accent (a hex or a
named colour, tuned per mode), the three typefaces (from a list per role: display, ui, mono), density, corner
radius, how panels are drawn, the background, the rail, headline size, label style and motion, and per-mode colour
tokens. Text must stay readable in both modes; a change that fails is refused with the reason, so adjust and retry.
The colours that carry meaning (finding levels, evidence status, the chart palette) cannot be changed, so a finding
reads the same in every look. Call `theme_options` first, change only what was asked, and start from a preset only
when a whole new look is wanted.

## How to work

1. **Profile first.** Read capabilities before fields. Absent capabilities rule out whole kinds of view: no
   identities means no per-agent views; the unit becomes the resource (a target, a host, a file).
2. **Use the source's own words.** Set terminology from entity_noun and resource_noun; title panels in those words
   ("Most active targets this week", not "Top objects"). Never put internal names (cohort, triage, template, σ) in a
   title a viewer reads first.
3. **Brief first, then pages.** Pick the signature views by asking what a person would glance at to see this stream
   is behaving normally. One wide (span 7) and one narrow (span 5), or a single span-12 view.
4. **One page, one question.** Each page has a description saying what question it answers. Start a page with a
   short `note` panel only when the reading is not obvious.
5. **Pick the primitive from the shape of the answer.**
   - change over time: `timeseries` with the suggested bucket, stacked by one small dimension (at most 8 series);
   - ranking: `bar` with `top` 10 to 15;
   - two categorical dimensions, or category by time: `heatmap`;
   - a count that matters on its own (for example significant-grade reports): `stat`;
   - detector output or anything with several columns: `table`;
   - the latest records themselves (time, who, what, where), each opening its record: `feed` (no group_by, `top` 10-30);
   - who works with whom: `graph`, group_by [actor, object] (agents linked through shared resources);
   - which agents touch which resources, or any two dimensions as two linked columns: `bipartite`;
   - when each agent (or group, or resource) was busy: `swimlane`, group_by [dimension, ts:<bucket>].
   Every view says what it needs (`requires` is filled in when it is checked) and links to its evidence: a click on a
   bar, row, node or lane opens the records behind it. Set `link: "none"` only for purely decorative counts.
6. **Show the base.** Put totals next to subsets (all reports beside significant reports).
7. **Respect grades.** If the source grades its evidence, show the grade as a dimension rather than mixing grades.
8. **Keep it small.** Four to six panels a page. Remove views that duplicate others. A page the viewer has to scroll
   through to find the point is a bad page.
9. **Explain the change.** Pass a rationale with every edit and a `reason` on every page you add.

## Query language, in brief

`{"from": "events", "where": {...}, "time": {"last_hours": 72} | {"all": true}, "group_by": [...], "metric":
"count" | "distinct:actor" | "distinct:object", "top": 12}`. Fields: actor, object, family, action, group, source,
ts:hour, ts:day, ts:week, ts:month, attr.<key> (categorical attributes only). Derived sources: cohorts, templates,
triage, claims, org, observations (group_by kind, scope, ts:day). Queries are clipped to the replay clock, so early in
a replay many views are empty; that is expected, and the preview says so.

## Example ops

```json
[{"op": "add_panel", "page": "brief", "panel": {"id": "targets_week", "title": "Most targeted this week", "span": 5,
   "view": {"primitive": "bar", "query": {"group_by": ["object"], "time": {"last_hours": 168}, "top": 10}}}},
 {"op": "set_brief", "glance": ["active", "attention", "investigating", "events"], "attention_rows": 5},
 {"op": "add_page", "id": "targets", "title": "Targets & methods",
  "description": "Which targets, which methods, when, and with what confidence.",
  "reason": "no identities, so targets and methods describe the population",
  "panels": [
   {"id": "heat", "title": "Targets by method", "span": 7,
    "view": {"primitive": "heatmap", "query": {"group_by": ["object", "family"], "time": {"all": true}, "top": 20}}},
   {"id": "grades", "title": "Evidence grade over time", "span": 5,
    "view": {"primitive": "timeseries", "query": {"group_by": ["ts:week", "attr.confidence"], "time": {"all": true}}}}]}]
```
