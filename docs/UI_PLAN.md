# SwarmFrame UI: minimal, still fully informative

Drafted 2026-10-03 after three persona tests of the compose-mode dashboard (safety lead on the planted 2,000-agent
swarm; policy researcher on Transluce; ML engineer linking a JSON stream). All three reached the same verdict: the
front door works, the dashboard behind it is a wall. This document diagnoses why, sets the design principles we will
hold to, lays out the new information architecture, and ends with the implementation plan.

## Status (2026-10-03): implemented

| Plan | Where |
|---|---|
| The Brief (status, glance, needs attention, signature views, what changed) | `frontend/src/screens/Brief.tsx`; digest in `backend/swarmscope/dashboard/brief.py` |
| Grouping, ACT / LOOK / WATCH, next step, plain headlines (σ → ×usual) | `dashboard/brief.py` (`brief_digest`, `incident_detail`) |
| Finding actions (investigate, watch, pin, snooze, dismiss) and the finding drawer | `POST /api/incident/{id}/action`, `components/findings.tsx`, `EvidenceDrawer.tsx` |
| Nav: Brief · Attention · Activity · Investigations · Control · Under the hood · Settings | `frontend/src/App.tsx` |
| Under the hood (collapsed sections with summaries), machinery switch | `screens/UnderTheHood.tsx`, op `set_machinery` |
| Glossary with hover help; plain labels in every panel | `frontend/src/words.ts`, `components/kit.tsx` (`Term`, `Tip`) |
| Edit ▾ on every page, panel catalog (any panel anywhere), arrange, rename, move, reset, Undo toast | `screens/Views.tsx`, ops `move_page`, `reset_page`, `update_page.nav` |
| Brief settings (glance numbers, rows, minimum severity, what changed) | op `set_brief`, `BriefSettings` in `Brief.tsx` |
| Lenses | `DashboardStore` lenses, `POST /api/dashboard/lens`, copilot and designer tool `dashboard_lens` |
| Composer: Brief + at most three pages, each with a reason; focus note steers it | `dashboard/designer.py` (`auto_design`, `merge_pages`), dashboard-designer skill |
| Autoplay, Play call to action, Advanced disclosure on compose | pack `source.yaml` `autoplay`, `Brief.tsx`, `Compose.tsx` |
| Bugs: partial bucket, `none` group, axis labels by span, heatmap column labels, real preview, consistent status | `dashboard/query.py`, `primitives/views.tsx`, `primitives/charts.tsx` |

## Visual identity: "Observatory" (2026-10-04)

The first build was clean but read as a generic warm-paper template. The identity now says what SwarmFrame is: an
instrument for watching a swarm.

- **Two-tone shell.** A graphite navigation rail (its tokens are re-scoped, so buttons and counts inside it turn
  graphite) against a warm paper canvas with a faint plotting-paper dot grid. Inks are cool graphite, not brown.
- **One signal colour.** Vermilion is reserved for what needs action: ACT findings, the active page, hot readouts.
  Plain data bars, heatmaps and histograms use a neutral data colour (`--data`).
- **Instrument plates.** Panels have hairline frames and registration ticks in two corners. Glance numbers are
  readouts: a mono label, a large lining numeral, context, and a full-width trace. Findings carry a severity rail.
- **Type.** Newsreader for headlines and section titles, Instrument Sans for structure, Plex Mono for labels and
  figures.
- **The swarm field** (`components/SwarmField.tsx`). A live field of streaks behind the Brief's headline and the
  compose screen. One streak per active agent (one per k agents above 420), coloured by workstream, flocking
  around a moving centre per workstream; it is calm when nothing needs attention, livelier with LOOK and restless
  with ACT. Canvas 2D at about 30 fps, paused in hidden tabs, a still frame with reduced motion, hidden on phones.
- **Logo.** A scope reticle over a small swarm, with one vermilion agent at the centre.
- **Dark mode** is a deep blue-black observatory rather than warm brown.

Verified on 2026-10-04 by two Sonnet testers (one on customisation flows, one on visual design) and by scripted
checks; every defect they ranked medium or higher was fixed: the Brief's Edit menu stacking, modal scrim and Esc,
custom words reaching the Brief, page reordering and Enter-to-rename, reset only where a default exists, lens
switching from a page that exists in one lens, the World header at tablet width, empty time series, the Ask
button overlapping content, and mobile navigation.

## 1. Diagnosis

The dashboard is organized around **how SwarmFrame works** (Executive, analyst organization, triage lanes, cohorts,
coverage ledger, monitor health, LLM spend) rather than around **what the operator came to find out**. Every module
we built got a panel, and every panel went on the home page. The result:

| What testers hit | Why it happens |
|---|---|
| Situation Room stacks ~12 panels; the good summary at the top is buried | `defaultOn: true` on 16 of 20 panels; pack `room` layouts list 9–11 panels |
| Same finding appears three times (incident, Live brief, triage row) | Three subsystems each render their own view of one fact; no deduplication layer |
| No answer to "what should I do?" | Incidents carry scores but no severity rank and no recommended action |
| Internal words on screen: cohort, unit, triage lane, coverage ledger, audit, template, blind spot, σ, `EXEC V5`, `TRIAGE_TREE`, `llm: stub` | Labels were written for us, during development |
| ~12 nav destinations; "Built-in" vs "Composed" means nothing to a user | Nav exposes the implementation (fixed screens + pack pages + composed pages + a modal listed as a page) |
| Replays open on zeros with a tiny Play icon; Transluce then plays in real time | Replay clock starts paused at 1×; no empty-state call to action |
| Identity-free data (Transluce) shows agent panels and "events by agents" wording | Capability gating hides a few panels but the nav, hero and copy assume agents |
| Removing a page is instant and silent; undo lives in a History tab | Edit affordances were built for the designer agent first |
| Compose screen asks for Organization and Models with no explanation | Settings exposed before the user has a mental model |

The composing ethos is right, but composing today **adds pages on top of the full stack**. It should **build a small
dashboard**, with the stack one click away.

## 2. Principles we will hold to

Drawn from the dashboard and incident-response literature, and from Thimble.

1. **Overview first, zoom and filter, details on demand** (Shneiderman). One screen answers "is anything wrong, how
   big, what next". Everything else is a click away, and detail opens in place (drawer), not on a new page.
2. **Summarize and show exceptions** (Few, *Information Dashboard Design*). A dashboard fits one screen within the
   eye span; non-data pixels are cut; what is shown is the exception, not the inventory. Few's listed mistakes are
   exactly ours: exceeding one screen, inadequate context for numbers, excessive detail.
3. **Progressive disclosure** (Nielsen). The primary view carries only what most people need most of the time; the
   machinery is reachable in one step and clearly labelled as machinery.
4. **Alert hygiene** (SRE and incident-management practice). Deduplicate and group similar findings; rank by
   severity; every surfaced item has an owner-facing next step; a finding that never leads to action is demoted from
   the attention list to a chart. Dashboards inform alerting, not the other way round.
5. **Every number with its base; a claim is not a fact** (Thimble). Keep provenance (observed / derived / claimed),
   but at the detail level, as a small chip, not as a paragraph on every card.
6. **Question-first structure.** Pages are named by the question they answer, in the source's own nouns (agent /
   report, resource / target), not by the subsystem that produces them.
7. **Empty states are calls to action.** A paused replay says "Play" in large type; a stream waiting for events says
   how many have arrived and what will happen next. Never a screen of zeros.
8. **Undo, not confirm** (Nielsen's user control). Edits apply at once with a toast that undoes them; "Reset to
   default" is always visible in edit mode.
9. **Composing proposes, people dispose.** The composer (free or Claude) proposes a Brief and at most three pages,
   each with a one-line reason. It never appends to a full stack.

## 3. The three layers

### Layer 0: the Brief (home; one screen at 1280×800)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Planted swarm at scale · synthetic                      ▶ 1h/s ───●──── 03:00 │
├──────────────────────────────────────────────────────────────────────────────┤
│ Nine agents across two teams converged on one shared file in the last hour;  │
│ the rest of the swarm is working normally.                   updated 2 min ago│
│                                                                              │
│  1,840 active   ·   3 need attention (1 act · 2 look)   ·   2 being looked   │
│  ▁▂▃▅▆▆▇            ▁▁▂▂▃                                   into          │
│                                                                              │
│ NEEDS ATTENTION                                              see all 9 →     │
│ ● ACT   9 agents converged on shared/plan.md        new · observed           │
│         Next: open the investigation (running, 60% done)                      │
│ ● LOOK  team-07 says it finished tasks it never touched   updated · derived  │
│         Next: verify 4 claims against the file history                        │
│ ● LOOK  shell · team-03 doubled its rate in one hour      new · observed     │
│         Next: watch; investigate if it lasts another window                   │
│                                                                              │
│ ┌ Work by team (last 6 h) ──────────────┐ ┌ Resources drawing a crowd ──────┐ │
│ │ [stacked area]                        │ │ [ranked bars]                    │ │
│ └───────────────────────────────────────┘ └──────────────────────────────────┘ │
│                                                                              │
│ WHAT CHANGED   03:00 new incident · 02:40 brief revised · 02:10 2 similar…   │
└──────────────────────────────────────────────────────────────────────────────┘
```

Content, in order, and nothing else:

1. **Status sentence.** The Executive's `population_state`, one or two sentences, with "updated N min ago".
   Contradictions are resolved at the source: if incidents are open the sentence must mention them.
2. **Glance row.** Three to five numbers, each one a question, each with a seven-point sparkline:
   `<noun>s active` · `need attention` (split by severity) · `being looked into` · `how much we have read` (coverage,
   with a qualifier word) · `awaiting your approval` (live control sources only).
3. **Needs attention.** The centrepiece. At most five rows after deduplication, ranked by severity. Each row:
   severity (ACT / LOOK / WATCH), headline in the source's nouns, freshness (new / updated / quiet 2 h), evidence
   chip (observed / derived / claimed), and a **Next:** line with the recommended step and, where one exists, the
   link to the running investigation or the control action. "See all N" opens the Attention page.
4. **Signature views.** Up to two source-specific views chosen by composing: for the swarm, work by team and crowded
   resources; for Transluce, targets by method and bursts; for the village, who is doing what and where they talk;
   for a linked stream, the two breakdowns the profile ranks highest.
5. **What changed.** One compact line or a short list (max five) of grouped brief entries in plain words: "new
   incident", "brief revised", "3 similar updates". Clicking opens the full brief in the drawer.

What is **not** on the Brief: triage, cohorts, coverage ledger, analyst organization, monitor health, executive
context, templates, lineage, say-do tables, the population graph, incident score axes, spend, LLM mode, topology.

### Layer 1: question pages (the nav)

```
 Brief
 Attention            ③
 Activity             ▸  Teams at scale · Breakdowns · Conversation · (+ add)
 Investigations       ②
 Control              ①   (live sources with control only)
 Under the hood
 ─────────────
 + New source           ⚙ Settings      ☾
```

- **Attention.** Every open and recent incident, grouped (same watcher + same scope collapse into one with a count),
  filterable by severity and status. Selecting one opens the detail drawer: the five score axes **with a sentence
  each** ("coordination: how many agents are involved"), the evidence list with observed / derived / claimed chips,
  the linked investigation, and the actions (Investigate · Watch · Dismiss · Pause these agents where control exists).
  This absorbs today's *Monitor attention* screen; proposed directives appear here as "SwarmFrame proposes…" rows.
- **Activity.** What the population is doing. Its sub-pages are the source's pages (pack-built and composed, no longer
  labelled as such) plus the generic ones: Timeline, Who does what (population graph / swimlanes, identity sources
  only), Narration vs action (self-report sources only), Content reuse (artifact sources only), Raw events. Each
  sub-page opens with a one-line header saying what question it answers.
- **Investigations.** As today, with one addition: each conclusion ends in a recommended action that writes back to
  the incident row on the Brief.
- **Control.** As today; hidden when the pack sets `control: false` or the source is a replay.
- **Under the hood.** One page of collapsed sections, each with a one-line summary in its header so the page is
  informative even fully collapsed:
  `Reading plan (triage) · 36 picks this cycle, 74% found something` ·
  `Groups of similar agents (cohorts) · 81 groups, 4 outliers` ·
  `What we have read (coverage) · 17 of 81 groups this cycle, 4 picks unread` ·
  `The analyst organization · 5 analysts over 3 divisions` ·
  `Monitor health · coverage fair, 7 blind spots` ·
  `Message types (templates) · 1.1k messages → 11 types` ·
  `Cost · $0.00, deterministic mode`.
  The current panels render inside the sections unchanged; only their framing moves.
- **Settings** (gear): Configure and Evaluate, source and organization details, the theme toggle.

The nav drops from ~12 entries to 5–6. "Design with Claude" leaves the nav and becomes part of **Edit** on every page.

### Layer 2: details on demand

Drawers, never new pages: incident, investigation, cohort/group, agent or target, evidence event, brief history.
Hover help on every label and score (see §5).

## 4. Customization: anything, anywhere; the defaults are only a starting point

The minimal layout in §3 is what a **new** dashboard looks like. It is not a ceiling. The rule that keeps the two
goals compatible is: **the structure (Brief, question pages, drawers) is fixed; what fills it is entirely the user's.**

**What can be changed**

- **Any panel on any page, including the Brief.** Every panel in the registry (built-in modules, pack views,
  hand-built views, machinery sections like triage or cohorts) is placeable on any page. A safety lead who wants the
  reading plan on the Brief puts it there; a researcher who wants the targets heatmap full-width at the top does that.
  Panels are gated only by what the source can support, never by "where they belong".
- **The glance row.** Pick which numbers appear (from a catalog: active, need attention, being looked into, coverage,
  approvals, any hand-built `stat` view) and in what order; two to six of them.
- **Needs attention.** Set the row cap (3–10), the minimum severity shown (WATCH / LOOK / ACT), and whether grouped
  duplicates expand. Pin an incident to the top; snooze one.
- **Pages.** Add, rename, reorder, remove and restore pages; nest a page under Activity or make it top-level in the
  nav. Pack pages are ordinary pages after the first load; the only trace of their origin is the *Reset this page*
  entry, which restores the pack's version.
- **Panel size and order** by drag and width buttons, as today, on every page.
- **Words.** `terminology` is editable per source from Settings (what to call the unit and the resource, and the
  severity words), and the glossary follows it.
- **Density.** *Show the machinery* (per source) expands the Under-the-hood sections into panels on Activity for
  people who want today's level of detail.

**How it is changed** (one menu, the same on every page)

- **Edit ▾** in every page header, Brief included: *Add a view* (hand-built, real chart preview, or pick any existing
  panel from the catalog) · *Ask Claude* (natural language: "put the crowded-resources chart on the Brief and drop
  the timeline"; disabled with a pointer to Settings when no model mode is on) · *Show / hide* · *Rename / move this
  page* · *History and undo* · *Reset this page*.
- The copilot can do all of the above from chat, and so can the designer agent through the same ops; the human and
  the agents edit one spec with one version history.
- Every edit applies immediately and raises a toast with Undo. No confirm dialogs.

**Lenses: saved layouts per scenario**

The same source is watched differently during an incident, during a quiet week, and when writing a report. A
**lens** is a named, saved dashboard spec for a source: *Default* (what composing produced), plus any the user saves
("Incident mode": Brief with needs-attention at 10 rows, the control panel and the investigation list; "Research":
the breakdowns and heatmaps, no incidents). Lenses are switched from the top bar, saved from Edit ▾ ("Save as
lens…"), and can be asked for in words ("make me a lens for reviewing team-07"). The spec store already versions one
spec per source; lenses make it one spec per (source, lens) with the same ops and undo.

**Composing**

- Composing produces the *Default* lens: a Brief and ≤ 3 Activity pages, each with a one-line reason shown in the
  composing checklist ("Targets by method, because the stream has resources and method families but no identities").
  The focus note typed on the compose screen shapes it ("I care about shared files" puts crowded resources on the
  Brief). The spec gains `brief: {status, glance: [...], attention: {rows, min_severity}, signature: [...]}`; `room`
  is retired (the old room survives as an *Everything* page only when the user asks for it).
- Composing can be rerun at any time on the current lens ("Recompose around: <new focus>"); it proposes a diff and the
  user accepts or undoes it.

## 5. Words

One glossary, used by the frontend, the pack `terminology` and the designer skill. Internal name → what the screen says
(with `<noun>` filled from the pack: agent / report; resource / target / file).

| Internal | On screen | Hover help |
|---|---|---|
| cohort | group of similar `<noun>`s | `<noun>`s that behave alike: same kind of work, same places, similar pace |
| unit | `<noun>` | — |
| triage | reading plan | what the analysts will read closely this cycle, and why |
| triage lane / coverage lane / audit lane | picked for priority / picked because unread for longest / random spot-check | — |
| coverage ledger | what we have read | which groups got a close look this cycle and which did not |
| blind spots | not yet read | groups or picks nobody has looked at |
| template | message type | messages with the same shape after names and numbers are masked |
| outlier (0.62) | unlike its group | how far this `<noun>`'s behaviour is from its group, 0–1 |
| 53.0σ | 53× usual | compared with this `<resource>`'s own typical hour |
| EXEC V5 | brief, revised 5× | — |
| NEW / REVISED / ALERT / INVESTIGATE | New · Updated · Needs attention · Looking into | — |
| coordination / impact / scope / external / novelty | shown only in the incident drawer, each with a sentence | how many involved / what it could affect / how widely / outside reach / seen before? |
| evidence 100% | dropped from cards; in the drawer as "N observed · M derived · K claimed" | — |
| llm: stub · auto investigate · TRIAGE_TREE | Settings and Under the hood only | — |
| events by agents (identity-free) | `<noun>`s on `<resource>`s | — |

Severity words: **ACT** (score ≥ 0.7 or an investigation concluded against the agents), **LOOK** (≥ 0.4), **WATCH**
(below). The score itself appears only in the drawer.

## 6. The first minute

- Replays **auto-play** on open at a speed chosen by the pack: planted swarm 1 h/s; AI Village 10 m/s; Transluce
  "load the history" (catch up to the end at max, then hold). The compose checklist's last step says what will happen
  ("Opens playing at one simulated hour per second").
- If the clock is paused with nothing in view, the Brief's status area is replaced by a large **Play** call to action,
  not zeros.
- Linked streams show "N events received · composing at 150" with a live counter until composing starts.
- The compose screen: the chosen card is the only one highlighted; **Organization** and **Models** move under an
  *Advanced* disclosure with one sentence each ("Models off: deterministic analysts, no cost"); clicking **Connect and
  compose** scrolls to the checklist and disables the button.

## 7. Identity-free and capability-gated sources

- Pack `identities: absent` hides: Who does what, Control, agent swimlanes, "agents active" (replaced by "reports in
  the last day"), and every agent-worded string via `terminology`.
- The analyst organization section's summary speaks of "targets" ("3 analysts over 1 group of targets").
- The hero sentence and brief entries are generated with the pack nouns (backend change in `executive.py` and
  deterministic prompts).

## 8. Known bugs to fix in the same pass

- Coverage "events in span" goes stale versus the header count.
- Status sentence "No report activity" alongside open incidents.
- Transluce headline date (Sep 18) outside the data range; repeated axis labels on the timeline.
- Agent counts disagree between the brief, the glance row and the stream profile.
- Timeseries dips to zero at the replay edge (clip the last partial bucket).
- Resource bars include a `none` bucket.
- Hand-built view Preview returns text, not a chart.

## 9. Implementation plan

Each phase ends with the three persona tests rerun on the free mode. Success criteria for the whole effort:
each tester answers their scenario question in under 60 seconds of opening the dashboard; names at most two unexplained
terms; the Brief fits one screen at 1280×800 with no scrolling; nobody reports "it looks broken or empty".

**Phase A — Structure (frontend + spec).**
`App.tsx` nav to Brief / Attention / Activity / Investigations / Control / Under the hood / footer. New `screens/Brief.tsx`
(status, glance row, needs-attention list, signature views, what-changed line). New `screens/UnderTheHood.tsx` with
collapsible sections wrapping the existing panels. `Attention.tsx` absorbs incidents + proposed directives + the
incident drawer with axis sentences. `DashboardSpec` gains `brief`; `room` is read for migration only. Pack
`dashboard.yaml` files get a `brief:` block and lose `room:`. Glossary module `frontend/src/words.ts` with `t(term,
terminology)` and hover help; every label routed through it.

**Phase B — Alert hygiene (backend).**
`executive.py`: incident deduplication by (watcher, scope) with counts; severity band; `recommendation` on every
incident (deterministic rules per watcher kind in stub mode; the director's report contract gains a `next_step` field
for model modes). Brief entries grouped ("3 similar updates"). Status sentence must mention open incidents. Investigation
conclusions write `recommendation` back to their incident.

**Phase C — First minute.**
Pack `source.autoplay` (speed or `catch_up`), honoured by the engine on session start. Brief empty-state CTA. Stream
counter. Compose screen: Advanced disclosure, single-highlight cards, scroll-and-disable on Connect.

**Phase D — Editing and lenses.**
`Edit ▾` menu component used by Brief and every Activity page; toast with undo (`dashboard_undo` already exists);
`Reset this page` op (`restore_builtin` scoped to a page); real chart in Preview (reuse `ViewBody` with the preview
query result). Panel catalog lets any registered panel, machinery included, be added to any page; Brief ops for the
glance row and the attention settings (`set_brief`). Page ops gain `rename_page`, `move_page`, `nest_page`.
Lenses: `DashboardStore` keyed by (source, lens); ops `save_lens`, `switch_lens`, `delete_lens`; a lens switcher in
the top bar; `terminology` editable from Settings. Remove the Built-in / Composed headings; show the origin only in
edit mode. Copilot ops (`assistant/ops.py`) and the designer tools expose the same new ops.

**Phase E — Composer contract.**
`auto_design` and the `dashboard-designer` skill produce `brief` + ≤ 3 pages with reasons; `merge_pages` keeps the
≤ 3 cap; composing checklist shows the reasons. Identity-free wording in `executive.py` and deterministic prompts.

**Phase F — Bugs (§8), then the persona rerun.**

Order: A, B, C in one pass (they are what the testers hit first), then D and E, then F. A alone removes most of the
density; B is what makes the Brief answer "what do I do"; C is what stops the "it looks broken" first impression.

## References

- Shneiderman, *The Eyes Have It* (1996): overview first, zoom and filter, details on demand.
- Few, *Information Dashboard Design* (2006): single screen, data-ink, summarize and show exceptions, the thirteen
  common mistakes.
- Nielsen Norman Group: progressive disclosure; the ten usability heuristics (user control and freedom, recognition
  over recall, match between system and real world).
- incident.io and pragmatic SRE guidance on alert fatigue: deduplicate and group, demote non-actionable alerts to
  dashboards, every alert needs an owner and a next step.
- Thimble (safety-research/thimble): orientation agent proposes views after surveying; a claim is not a fact; every
  number with its base.
- The three persona test reports of 2026-10-03 (session transcript).
