# The dashboard

How the SwarmFrame dashboard is designed and why. The dashboard is small by default and fully informative on demand:
one screen says whether anything is wrong, how big it is and what to do next, and everything else is one step away.
The World (the 3D view) has its own note, `docs/design/world.md`.

## Why it looks like this

Three persona tests of the first composed dashboard (a safety lead on a planted 2,000-agent swarm, a policy
researcher on the Transluce catalog, an ML engineer linking a JSON stream) agreed: the front door worked, the
dashboard behind it was a wall. It was organized around how SwarmFrame works, not around what the operator came to
find out. What they hit, and what it led to:

| What testers hit | What the design does now |
|---|---|
| The home page stacked about twelve panels; the good summary was buried | A Brief that fits one screen, plus at most three composed pages |
| One finding shown three times by three subsystems | Findings are deduplicated and grouped into one row with a count |
| No answer to "what should I do?" | Three severities (Act, Look, Watch) and a **Next** step on every row |
| Internal words on screen (cohort, triage lane, template, σ, `llm: stub`) | One glossary (`frontend/src/words.ts`), plain labels, hover help |
| About twelve nav entries that mirrored the implementation | A rail of question pages, with the machinery at the foot |
| Replays opened on zeros with a small Play icon | Replays autoplay; a paused, empty replay shows a large Play |
| Identity-free data described as "agents" | The source's own nouns, and views gated by what the source has |
| Removing a page was instant and silent | Every edit applies at once with an Undo toast |
| The start screen asked for an organization and models with no explanation | One "How it runs" line; the options sit behind Change |

Later passes removed controls that were in view without being needed, and added a severity-free summary next to the
findings, because findings alone hide what everyone else is doing.

## Principles

They draw on Shneiderman (overview first, details on demand), Few (one screen, show exceptions), Nielsen
Norman Group (progressive disclosure, user control), SRE alert practice (group, deduplicate, a next step for every
alert) and Thimble (a claim is not a fact; every number with its base).

1. **One question per page.** Each page answers one question and is named for it, in the source's nouns (agent or
   report, resource or target). The Brief answers "is anything wrong, how big, what next". Detail opens in place, in
   a drawer, not on a new page.
2. **Evidence behind every claim.** Findings, overview lines, activity lines and answers carry numbered source marks
   that open the claims and events they rest on; view marks open their records. An answer that cites nothing is
   marked "no sources cited · interpretation". Provenance (observed, derived, claimed, inferred) is a small chip.
3. **Severity-free oversight next to findings.** Findings answer "what needs attention". "What's going on" answers
   the other question a supervisor has: what is everyone doing, and what is new, whatever the severity.
4. **Few controls in view.** The primary view carries what most people need most of the time. Everything else sits
   behind one **Change** (start screen, Analyze) or one **Edit** (every page), or under the hood.
5. **Agent-written text is untrusted evidence.** It never reaches the stream profile, the query language or a
   composed view. Where a person can read it (the evidence drawer, a stated goal), it is labelled as untrusted.
6. **Undo, not confirm.** Layout and look changes apply at once and can be undone (a toast, History, Undo in Look).
7. **Composing proposes, people dispose.** The composer proposes a Brief and at most three pages, each with a
   one-line reason. Humans, the copilot and the designer agent edit one spec with one version history.
8. **Empty states are calls to action.** A paused replay says Play; a stream waiting for events says how many have
   arrived and how to send more. Never a screen of zeros.

## The start screen

`frontend/src/screens/Compose.tsx`. One question, one list, one line of settings:

```
What should we watch?
[ Watch a swarm | Analyze a dump ]                  ModeSwitch: the two ways in

Running now: <source>          [Back to the dashboard]     only while a session runs

THE DATA
 ( ) Your own event stream          live · any source
 (o) AI Village                     recorded
 ( ) The German message board       recorded
 ( ) Agent activity on the web      recorded

HOW IT RUNS  [reader] [team] [how it plays] [how often it reports]   Change
[ Anything to focus on? (optional) ]                                 [Start]
```

- The selected card expands in place to show its one choice (the endpoint and a sample feed for a stream, the goal
  period for AI Village, the stretch for the message board).
- **Change** opens every option: who does the reading, the analyst team (default, composed for this data, a preset
  suggested for this source, more shapes), live stretch or replay, replay speed, how often it reports, and the
  monitoring organization when there is more than one.
- The focus note steers the composer. One sentence under Start says what will happen next.

## Composing

After Start, the same screen becomes a short checklist beside the stream profile:

1. Source connected (live or replay, synthetic or real).
2. Reading the stream's structure. A live stream waits for 150 events (or 30 after 25 s) and offers the sample
   swarm if nothing arrives.
3. The source's default views, if its pack ships any: a starting point that can be changed or reset.
4. Composing, with the free composer or with Claude. Each proposed page shows its reason. A source composed before
   reuses its saved views and offers **Recompose**.
5. Laying out the World, with the reasons for its shape, distance and units.
6. **Explaining it to you.** What this data can show and what it lacks, a note about names where relevant, who is
   reading it and why, how to study it, and good first questions. A question drops into the live column's box.

It ends with how the replay will open and **Open the dashboard**. The orientation is also posted in the live column.

## The rail

`frontend/src/App.tsx`. The rail lists question pages first, the source's own pages next, and the machinery at the
foot:

```
SwarmFrame                 connection dot
Brief
Findings              3    Act + Look count; highlighted while any are open
World
Investigations        1    running investigations
Control               2    only when the source has control; pending approvals
PAGES                 +    add a page
  <the source's pages>     pack-built and composed pages, no longer labelled by origin
-----------------------
Under the hood
Settings
+ New                      back to the start screen (watch or analyze)
```

Before a source is running, the rail shows only the wordmark and **New**. The theme can collapse the rail to icons.
Organization and monitor-effort views are not in the rail; Under the hood links to them.

The top bar carries the source title, a lens chip when there is more than one lens, synthetic and live chips, a
mode chip (rules only or Claude), and the clock: play or pause, a speed menu with step and jump, and progress.

## The Brief

`frontend/src/screens/Brief.tsx`, digest in `backend/swarmscope/dashboard/brief.py`. Top to bottom:

- **Bands, only when needed.** Findings escalated to a person that wait for acknowledgement, and changes the analyst
  team proposes outside what it may do alone (approve or decline).
- **Status line and detail.** One sentence as the headline, the rest underneath. The digest keeps it consistent with
  what is open. Before a replay starts, this area is a Play call to action; a live stream with no events says how
  many have arrived.
- **Attention line.** One sentence with a coloured lead dot ("Nothing needs a decision; 2 findings are worth a
  look.") and how long ago the brief was updated.
- **Glance numbers.** One to six readouts chosen from a catalog (active, need attention, being watched, being looked
  into, read closely, events, approvals, catalog counts), each with a trace. Some open their page.
- **What's going on** (`components/Overview.tsx`, `backend/swarmscope/dashboard/overview.py`). For each group: how
  many are active, what kind of work, where, the stated goal (marked agent-written), and whether it is new, rising
  or quiet. Then what is emerging: new places, new or rising work, groups that shifted. Every line cites events.
- **Needs attention.** The ranked, grouped findings, capped by the Brief settings, with counts per severity and
  "See all". The World sits beside it unless turned off.
- **Signature views.** The Brief's own panels, one or two views chosen for this stream.
- **What changed.** Up to five grouped briefing entries in plain words.

The Brief's Edit menu adds one entry for its fixed sections: which glance numbers, how many findings at what
minimum severity, and whether What's going on, the World and What changed appear.

## Findings and the finding drawer

`frontend/src/components/findings.tsx`, `frontend/src/components/EvidenceDrawer.tsx`, `screens/Attention.tsx`.

A finding row shows its severity word, the headline in the source's nouns, chips for overdue, awaiting receipt or
held escalations, a detail or plain explanation, a **Next** line, and its source marks. Freshness and the evidence
chip sit on the right. There is one primary action (Open investigation, See all N, or Investigate) and a ⋯ menu for
the rest: open details, show in the World, investigate, watch more closely, acknowledge, escalate, pin, snooze,
dismiss.

The Findings page lists every open finding, filterable by severity and text, with grouped findings expandable one by
one. Changes SwarmFrame suggests to where it looks appear above the list, to apply or reject.

The finding drawer reads top to bottom as an argument:

- severity, freshness, evidence chip, number of similar findings; the headline and detail;
- **In plain words**: what it is, why it might matter, the innocent reading, what to check;
- **Next**, then **Sources**: the numbered claims and events, each opening its own drawer;
- two primary actions (open or read the investigation, or Investigate; Show me in the World) and a quiet row
  (watch more closely, pin, snooze, dismiss);
- acknowledgement when escalated; how it got here (level history, independent sources); the investigation's
  conclusion; the members of a group;
- **How serious, on each axis**, in words (high, medium, low), never as raw scores; coordination is hidden for
  identity-free sources.

The same drawer opens claims (status explained, supporting and counter evidence), events (provenance, with
agent-written text in a labelled untrusted block) and entities (activity by workstream, observations, recent events,
"Focus monitors here", "Ask about").

## The live column

`frontend/src/components/ChatDock.tsx`. On wide screens (1280 px and up) it docks beside the page and collapses to a
narrow **Live** strip with an unseen count. On narrow screens it is an "Ask SwarmFrame" button that slides the column
over the page.

- **One header line**: Live, a ⋯ menu and collapse. The menu holds what to show, how often activity lines and lead
  summaries appear, pushing findings to the assistant, talking to your own Claude Code session, and a new
  conversation. A sub line gives the clock state, the next update, the reading mode and the spend.
- **Messages**: activity lines with source marks, new and revised findings with "Why it may matter" folded,
  answers with a folded numbered source list, approvals, and the orientation message with "how to study it" folded.

## Under the hood and Settings

**Under the hood** (`screens/UnderTheHood.tsx`) is how the oversight itself is working: the reading plan, groups that
behave alike, what has been read, the analyst team, monitor health, where monitoring effort goes, what SwarmFrame
believes, message types (wording hidden) and cost. Each section is collapsed, and its header carries a one-line
summary so the page reads closed. Any section can also go on any page from Edit, and one switch adds all of the
machinery as a page.

**Settings** (`screens/Settings.tsx`) has four tabs:

| Tab | What it holds |
|---|---|
| Look | The theme: describe it in words, pick a preset, or set each choice; Undo (`components/Appearance.tsx`) |
| Dashboard | Lenses (save, switch, rename, delete), the words for actor and resource, show the machinery |
| Monitoring | The watchers and the monitoring organization (`screens/Configure.tsx`) |
| Test bench | Compare the monitoring organization with baselines (`screens/Evaluate.tsx`) |

## Customizing the layout

The structure is fixed: the Brief, question pages, drawers. What fills it belongs to the user. **Edit** is the same
menu on every page, the Brief included (`PageEditMenu` in `screens/Views.tsx`): add a panel (any built-in, machinery
included, or a view from another page), build a view, ask the designer, change the look, arrange panels, rename or
move the page, save as a lens, history and undo, reset this page (only where a source default exists), remove the
page. Edits apply at once with an Undo toast.

A **lens** is a named, saved dashboard for a scenario ("Incident review", "Weekly report"). Each lens keeps its own
pages, Brief settings and history. Specs live per source and lens in `data/dashboards/<source>.json`.

## Analyze a dump

`frontend/src/screens/Analyze.tsx`, backend in `backend/swarmscope/analysis/`. The side mode for logs you already
have, reached from the same switch as Watch a swarm. It reads the whole record at once with the same watchers and
analysts, then writes a report where every claim names its records.

The screen is two lines after the drop zone (a path, dropped files, chosen files, or a sample):

- **What it can read.** "N rows in M files can be read as events", or a known source read with its own reader.
  **Check how it was read** shows the field mapping per file and lets you correct it.
- **How it reads.** The team and the writer as two pills, with **Change** for the options: compose a team, search
  (five teams try the first 30%, the best reads it all), compare up to six teams, or a preset; and the report written
  by the rules (free, local) or by Claude (model and effort).

The report opens first, with Download .md, Copy and **Explore in the dashboard** (the analysis as a session, with
every page and the drawer). Tabs show the report, the search or team comparison, and who read it. A Claude report
has a toggle to the rules reading; if Claude could not write, a note says so and the rules report stays. Record ids
in the report open the record in the dashboard.

## The design system

One stylesheet, `frontend/src/styles.css`, reads every colour, typeface, size, radius and spacing from custom
properties. Its defaults are the Observatory preset, so the first paint is right before the theme arrives.
Structural choices arrive as data attributes on `<html>`: `data-mode`, `data-surface`, `data-canvas`, `data-nav`,
`data-nav-style`, `data-motion`, `data-labels`, `data-display`.

The default identity, Observatory, says what SwarmFrame is: an instrument for watching a swarm. A graphite rail on a
warm paper canvas with a faint dot grid; one vermilion signal colour, reserved for what needs action; neutral data
colour for plain charts; hairline instrument-plate panels; Newsreader headlines, Instrument Sans for structure, Plex
Mono for labels and figures. The swarm field (`components/SwarmField.tsx`) behind the Brief's headline is a reading,
not a decoration: one dot per active agent (sampled above 420), coloured by workstream, restless with Act findings.

### The checked theme

`backend/swarmscope/dashboard/theme.py` keeps one theme for the whole app; `frontend/src/theme.ts` paints it. A
theme is a small checked description, never CSS: a preset plus a few changes on top.

- **Presets.** Observatory (the default), Paper (editorial, light rail), Console (dark, green signal, outlined
  panels), Clinic (white cards, blue accent), Signal (high contrast, Atkinson Hyperlegible).
- **Settings.** Mode, accent (a hex or a named colour tuned per mode), the three typefaces, density, radius (0 to
  18 px), panel surface, canvas, rail colour and style, headline size, label style, motion, and per-mode colours for
  twelve tokens. A new preset drops the old per-setting changes but keeps mode, motion and rail style.
- **Contrast rules**, checked in light and dark: main text 7:1 on panels and page, secondary text 4.5:1, muted text
  4:1 on panels and 3.6:1 on the page, the accent 3:1, accent-coloured text 4.5:1, rail names 7:1. A one-hex accent
  is lifted in dark mode until it stands out. A change that fails is refused with the reason, so an agent can adjust
  and retry.
- **Font allowlist.** Nineteen Google Fonts faces by role: display is serif or sans, UI is sans, mono is mono.
- **Fixed meaning colours.** Finding severity, evidence status and the eight-colour categorical chart palette cannot
  be set, so a finding reads the same in every look.
- **Versioned undo.** Every applied change records who made it and why, keeps a history, and can be undone. The
  theme is stored in `data/theme.json`; `theme.ts` caches the last resolved theme so the first paint is right, and
  follows the system light or dark setting when the mode is "system".

## The constrained designer

The designer composes; it never writes code or CSS. `backend/swarmscope/dashboard/designer.py`,
`backend/swarmscope/dashboard/spec.py`, `backend/swarmscope/dashboard/query.py`, and the skill in
`.claude/skills/dashboard-designer/SKILL.md`.

**Layout is ops over a fixed view library.** A panel is a built-in (a hand-made panel, by id) or a view: a primitive
plus a query. The primitives are stat, timeseries, bar, heatmap, table, feed, graph, bipartite, swimlane and note.
Every edit goes through `apply_ops` (add, update, move and remove pages and panels; `set_brief`, `set_machinery`,
`reset_page`, `set_terminology`, `set_title`, `restore_builtin`), which validates each op, runs each new view's query
once, applies the batch atomically and records a version. Each view declares what it needs: fields map to
capabilities (actor needs identities, object needs resources, time needs timestamps), and a view the source cannot
support is refused with the reason. Each view links to its evidence by default (`link: "evidence"`): a click on a
bar, row, node or lane opens the records behind it.

**The query language is safe by construction.** No raw SQL; queries compile to parameterized SQL over the evidence
store or read the scale layer, are clipped to the replay clock, and return only structural fields and attributes the
profile judged categorical. Agent-written text never comes back.

**The look is `theme_set`.** The designer reads `theme_options` (the whole design space) and changes only what was
asked, through the same checks as Settings → Look.

**Who designs:**

- The free composer (`auto_design`) reads the stream profile and proposes the Brief's one or two signature views and
  at most three pages, each with a reason; the focus note weights the candidates. `merge_pages` keeps the cap when
  it adds to a source's own pages.
- The free designer (`free_design`, `theme.interpret`) reads plain requests without a model ("dark, compact, teal
  accent, hide the World") into theme changes and Brief ops, and says what it understood.
- With a model, the designer is a Claude Agent SDK session whose only tools are the dashboard and theme tools in
  `DashboardTools` (profile, catalog, preview, edit, undo, lenses, theme), guided by the dashboard-designer skill
  and told to preview every view before adding it.

The copilot in the live column reaches the same ops, so humans and agents edit one spec with one history.
