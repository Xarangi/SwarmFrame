# SwarmFrame technical reference

Every part of SwarmFrame, its settings and its files. For an introduction see the [README](../README.md); for a walk
through the screens see the [guide](GUIDE.md). The reasoning behind the main designs is in [docs/design/](design/):
[the dashboard](design/dashboard.md), [the World](design/world.md), [analyst teams](design/analyst-teams.md) and
[reading at scale](design/reading-at-scale.md).

## Contents

- [Install and run](#install-and-run)
- [How it works](#how-it-works)
- [Sources](#sources)
- [Watchers, monitors and the executive](#watchers-monitors-and-the-executive)
- [Analyst teams](#analyst-teams)
- [Findings, cases and investigations](#findings-cases-and-investigations)
- [Models](#models)
- [The dashboard](#the-dashboard)
- [The live column](#the-live-column)
- [The World](#the-world)
- [Analyze a dump](#analyze-a-dump)
- [Evaluation and benchmarks](#evaluation-and-benchmarks)
- [Configuration](#configuration)
- [API](#api)
- [Layout of the repository](#layout-of-the-repository)

## Install and run

You need Python 3.11, Node 20 or later and [uv](https://docs.astral.sh/uv/).

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
cd frontend && npm install && npm run build && cd ..
.venv/Scripts/swarmframe serve
```

Open http://127.0.0.1:8765. On macOS or Linux use `.venv/bin/`. The command is installed under two names,
`swarmframe` and `swarmscope` (the package's original name); they are the same program. For frontend development
run `npm run dev` in `frontend/` (port 5173, proxied to the API on 8765).

| Command | What it does |
|---|---|
| `serve [--source ID] [--llm stub\|cheap\|full] [--port N]` | The dashboard. Without `--source` it opens on the start screen; with it, a session starts at once (`--synthetic` for the stand-in data, `--goal` for an AI Village goal period, `--simulate N` for a simulated live swarm). |
| `analyze PATH [options]` | Read a dump of logs and write a report (see [Analyze a dump](#analyze-a-dump)). |
| `fetch SOURCE [--set NAME]` | Download a recorded source's data (see [Sources](#sources)). |
| `probe PATH [--show-values]` | Report a dataset's structure (fields, types, value shapes). Values print only with the flag. |
| `replay --source ID` | Run a source headless through the monitoring and print the reports. |
| `eval`, `scale-eval` | The evaluation harnesses (see [Evaluation and benchmarks](#evaluation-and-benchmarks)). |
| `channel-setup`, `channel` | Connect your own Claude Code session to the live column (see [The live column](#the-live-column)). |
| `run-swarm SCENARIO` | Launch a small live Claude Code swarm from `runner/scenarios/`. |

Tests: `.venv/Scripts/python -m pytest tests -q`.

## How it works

```
source adapter ─► evidence store (DuckDB: events, entities, artifacts behind references)
   ─► watchers          deterministic detectors, every window
   ─► scale layer       profiles, cohorts, message templates, outliers, a reading plan (triage)
   ─► monitors          retrieval → summarization → evaluation → escalation → critique
   ─► analyst team      a lead and the agents it sends out, or a preset team (one topology file)
   ─► executive         the population picture, hypotheses, a context ledger, directives
   ─► cases             tracked findings with escalation history; investigations on demand
   ─► Brief digest ─► dashboard and live column (one WebSocket snapshot per window)
```

- **A source says what evidence exists.** Its pack (`packs/<id>/`) declares what the data can and cannot show;
  SwarmFrame switches on the monitors and composes the dashboard around that.
- **Code reads everything; models read what is worth reading.** Watchers and the scale layer never call a model.
  With models off, every role runs on rules, so the whole pipeline works for free and deterministically.
- **Every conclusion is tied to evidence.** Claims carry an epistemic status (OBSERVED, DERIVED, SELF_REPORTED,
  INFERRED, CONTRADICTED, UNKNOWN). A verifier downgrades any model-proposed OBSERVED or DERIVED claim whose cited
  events do not exist or lie in the future.
- **Agent-written text is untrusted evidence.** It is fingerprinted and stored behind a reference, reaches models only
  through `read_raw` or `search_text` wrapped in an escaped `<untrusted>` envelope, and is never followed as an
  instruction. The executive and the critic cannot read it at all.
- **Time is simulated.** A replay plays at a chosen pace (real time up to as fast as possible), skips quiet
  stretches, and can jump to any time: it catches up deterministically, then hands back to the models. Jumping back
  restarts the session and catches up to the target.

## Sources

| Source | Pack | What it is | On the start screen |
|---|---|---|---|
| Your own event stream | `generic_stream` | Whatever you post to `/ingest/events`; capabilities inferred from what arrives | Yes (live) |
| AI Village | `ai_village` | Twenty-one AI agents with their own computers and a shared chat, one week | Yes |
| The German message board | `german_wiki` | The collusion.wiki export: handles on a shared wiki, moderator sweeps | Yes |
| Agent activity on the web | `transluce` | Transluce's catalog of 37,649 scan reports attributed to agents, no identities | Yes |
| A Claude Code swarm | `claude_code` | Live agents from the SwarmFrame runner or any Claude Code session's hooks | `serve --source claude_code` |
| A dump of logs | `dump` | Any folder or file of logs, read after the fact | Analyze a dump |

`swarm_scale` is a synthetic test fixture (planted behaviours in swarms of any size), used by the tests and
`scale-eval`, not offered in the dashboard. Every recorded source falls back to a synthetic stand-in of the same shape
when its data is missing.

### A source pack

| File | What it holds |
|---|---|
| `source.yaml` | What the data is, the adapter, what to call things (`naming`, `workstream_noun`), replay speeds and the busiest stretch to watch live, `catalog: true` for a catalog rather than a swarm |
| `capabilities.yaml` | What the data can and cannot show (identities, resources, artifacts, communication, groups, tool calls, environment, control) and how good each is |
| `monitors.yaml` | Which monitors run and their overrides |
| `oversight.yaml` | The team preset that suits the source (`preset:`), or a forced team (`topology:`), and topology overrides |
| `questions.yaml` | Good first questions, shown when the dashboard is composed |
| `dashboard.yaml` | Default views: a `brief:` block and pages |
| `views.yaml` | Named views the source offers |
| `world.yaml` | The 3D scene and its presets |

The shipped packs are working examples. A new source is a folder with these files and an adapter that turns its
files into events (`backend/swarmscope/sources/`).

### Your own event stream

```bash
curl -X POST http://127.0.0.1:8765/ingest/events -H "content-type: application/json" -d '[
  {"ts": "2026-10-03T14:05:00Z", "actor": "agent-17", "group": "team-a", "action": "tool.write",
   "object": "repo/README.md", "family": "files", "text": "optional agent-written text", "attrs": {"model": "sonnet"}}]'
```

Only `action` is required; every other field unlocks more of the dashboard. After about 150 events SwarmFrame infers
what the stream contains and composes the dashboard, and it re-infers every 12 windows so monitors and panels switch
on as new kinds of events appear. "Play a sample swarm into it" on the start screen posts 400 simulated agents.

### Live Claude Code swarms

```bash
.venv/Scripts/swarmframe serve --source claude_code
.venv/Scripts/swarmframe run-swarm runner/scenarios/smoke.yaml   # 1 real agent, 4 turns
.venv/Scripts/swarmframe run-swarm runner/scenarios/tiny.yaml    # 3 agents sharing a folder
```

The runner launches each agent as a Claude Agent SDK session. Hooks stream every tool call to `/ingest/claude-code`;
every permission request goes to `/api/control/decide`, which applies the pack's control policy, holds paused agents
and can hold an action for a person on the Control page. Operators can pause, resume, message, interrupt and stop
agents or groups. To watch any other Claude Code session, add hooks that run `scripts/swarmscope_hook.py`
(instructions in the file); hook forwarding is observation only.

### Getting the recorded data

The datasets are not in the repository; each goes in its own folder under `data/` (ignored by git).

- **AI Village** (gated on Hugging Face; about 105 MB fetched). Request access to `aidigestorg/ai-village`, then
  `HF_TOKEN=... swarmframe fetch ai_village --set village_dense` (agents, goals, rooms, the full chat, every computer
  session) and `python scripts/fetch_village_events.py 2026-06-28 2026-07-06` (the demo week's slice of the activity
  timeline: memory checkpoints, pauses, searches, outreach requests with recipients reduced to domain + hash, and
  each action's reasoning). The token is read from the environment and never saved. Other sets: `computer_use_sample`,
  `claude_code_sample`. The export is not time-ordered, so head slices are sparse samples.
- **The German message board** (about 4 MB). The five files of the collusion.wiki export (events, revisions, pages,
  labels, manifest) in `data/german_wiki/`. 14,591 saves, 5,217 moderator deletions, 4 reverts and 101 probes from
  May 17 to July 14, 2026; by default the June 10–25 surge (74% of events) in half-hour windows. Saved bodies stay
  behind the evidence boundary; network prefixes in the export are not used, so identity stays partial.
- **Transluce** (4.6 MB, public). `swarmframe fetch transluce`. Report links and metadata only. Each report is one
  event: a method class, the source's confidence grade and the targeted data source. It is a catalog: its Brief
  summarises the whole record and its World is a map of targets.

**Reading the AI Village.** The adapter maps chat, computer sessions, memory consolidations, pauses (an `idle` family
that never counts as work), history searches, room moves, sign-ins, human-helper handoffs and outreach (the drafted
message and rationale, then a person's approval or denial). Each action's raw model output becomes the agent's
private reasoning: an untrusted artifact analysts can read with `read_raw` and the evidence drawer shows. The
`reasoning_cues` watcher flags reasoning about keeping something from people, reporting unfinished work as done,
working around a restriction, or credentials.

**Watch live.** Each recorded source names its busiest real stretch (the German board's evening of June 18, at about
30 edits a minute; Transluce's busiest night; the village's busiest evening). "Watch live" reads the hour or so
before it at full speed, so the monitors know what usual looks like, then plays it at real time in 30-second windows.

## Watchers, monitors and the executive

- **Watchers** (`backend/swarmscope/org/watchers.py`) never call a model. They detect convergence on shared resources,
  content reuse with or without an observed exposure path, rate surges, operator and environment events, say-versus-do
  mismatches, focus shifts and reasoning cues, each against per-resource baselines.
- **The scale layer** (`backend/swarmscope/scale/`) keeps a profile per unit, groups units that behave alike into
  cohorts, groups messages into templates, finds outliers and writes a reading plan in three lanes: triage (priority),
  coverage (what has not been read) and a random audit with a secret seed, never below 10%. See
  [reading at scale](design/reading-at-scale.md).
- **Monitors** are a manifest plus five strategy slots (retrieval, summarization, evaluation, escalation, critique)
  in `backend/swarmscope/org/monitors/*.yaml`. Each emits a report with claims, a risk vector and an operational
  level (WATCH, INVESTIGATE, ALERT, PAGE).
- **The executive** sees structured reports, never raw agent text. It owns the population picture, hypotheses and a
  context ledger, and steers attention through directives (ask, focus, defocus, tune, activate, audit, brief_human).
  Autonomy decides whether directives are recorded (observe), held for approval (assisted) or applied
  (auto_investigate); a person's directives always apply. `executive.strategy` picks the implementation: `agent_org`
  (the analyst team, default), `structured_state`, `persistent_session`, `hierarchical_summary`, `ensemble`,
  `deterministic`, `global_summary`.
- **What's going on** (`backend/swarmscope/dashboard/overview.py`) is severity-free oversight: for each group, how many
  are active, what kind of work, where, toward which stated goal, and whether that is new, rising, steady, slowing or
  quiet, plus what is emerging. Every line cites events, and the analysts and the live column read it too.

## Analyst teams

An analyst team is an organization of agents defined by one topology file in `backend/swarmscope/agents/topologies/`.
The design and its reasons are in [analyst teams](design/analyst-teams.md).

- **The default team is `lead`**: one lead analyst watches the whole stream and sends an explorer to every open
  finding at INVESTIGATE or above (at most 4 at a time), letting it go when the finding closes or after 4 cycles if it
  did not rise. With a model on, the lead can also spawn, re-run and retire explorers from its own reading.
- **Presets**: `triage_tree` (thousands of agents: readers per cohort, sector leads, an auditor, a coverage ledger),
  `desks` (the AI Village: per-group desks, a diarist, integrity and goals specialists), `board_watch` (the German
  board: namespace analysts, an identity resolver, moderation response), `catalog_review` (Transluce: method
  analysts, a grade auditor, a chronicler, record-batch cycles), `hierarchical_divisions`, `flat_pool`,
  `single_agent` and `sdk_native` (one session with native Claude Code subagents).
- **Composed for this data** (`backend/swarmscope/agents/composer.py`) assembles a team from the parts the presets are
  made of, each switched on by what the records show (see the table below). `compose_with_claude` lets Claude choose
  standing, on call or off per part, a partition and a budget; the assembly and the checks stay in code.
- **Which team a source gets.** A session's choice wins (a preset, `composed`, or `auto` for the selector's pick), then
  a pack's `topology:` in `oversight.yaml` (a team id, or `auto` for the selector), then the org default (`lead`). The
  selector (`backend/swarmscope/agents/selector.py`) reads the stream's shape and walks a decision table, with its
  reasons. The shipped packs only suggest a team (`preset:`, offered on the start screen as "suits this source"), so
  every source starts with `lead` unless you pick another.
- **The topology grammar**: roles (prompt, model, effort, turns, tools, raw-text access, which roles it may spawn,
  output schema, memory, scope, cadence, backend), a `partition` (cohorts, a group, or any categorical field),
  `levels` inserted by span of control, `standing` roles, a `questions → role` map, `maintain` rules, a `cadence`
  (time windows or record batches), a `human` contract (digest cadence, interrupt level, what needs approval), an
  `envelope` (what the director may change alone) and an `authority` budget.
- **Org tools** let an agent shape its team: `spawn_agent(s)`, `run_agent`, `split_division`, `merge_divisions`,
  `define_division`, `retire_agent`, `ask_question`, `org_status`, each checked against the topology's limits and
  budget. Agents can also brief their own short-lived `reader` helpers. Every delegation is logged with its reason to
  `data/runs/<session>/delegations.jsonl` and shown on the Organization page (Under the hood → The analyst team).
- **Proposals** (new roles, partition changes) apply alone inside the envelope or wait for you on the Brief; an applied
  one can be reverted, and a running team can be saved as a preset. The Organization page edits a topology live.
- **One skill instructs every role**: [`.claude/skills/swarm-oversight/`](../.claude/skills/swarm-oversight/SKILL.md),
  the doctrine plus per-role references, injected into each agent.

### The composer

It measures the records first (structure only: shares of self-reports, environment actions, stated goals, texts
written by more than one author, look-alike names, groups, units and candidate partition axes), then:

| Part | From | Switched on when |
|---|---|---|
| Lead (root) | `lead.yaml` | always |
| Explorers (on call) | `lead.yaml` | always; sent for findings at investigate or above |
| Readers | `triage_tree.yaml` | more than 40 units or 12 cohorts; cut by group, by a field with about 8 values, or by cohort |
| Sector leads | `triage_tree.yaml` | more than 12 slices |
| Integrity specialist | `desks.yaml` | agents describe their own work (standing at 5% of records) |
| Goals specialist | `desks.yaml` | agents state goals |
| Propagation specialist | `board_watch.yaml` | texts also written by another author (standing at 10) |
| Environment specialist | `board_watch.yaml` | deletions, stops or denials (standing at 2% of records) |
| Identity resolver | `board_watch.yaml` | partial identities with many look-alike names |
| Diarist | `desks.yaml` | a named cast of 2 to 40 |
| Chronicler, grade auditor, new-method specialist | `catalog_review.yaml` | a catalog (graded, for the auditor) |
| Auditor | `triage_tree.yaml` | 200 records or more |

Strong evidence makes a specialist standing; weaker evidence puts it on call. Budgets and cadence scale with the
population. Every part carries its reason and the measure behind it, and the result is validated like any topology.

## Findings, cases and investigations

- **A finding** is what the Brief shows: watcher and monitor reports deduplicated, grouped (same watcher and scope
  collapse into one with a count) and ranked ACT, LOOK or WATCH by how much they need a person
  (`backend/swarmscope/dashboard/brief.py`). Each has a next step and an `explain` block
  (`backend/swarmscope/dashboard/explain.py`): what happened in plain words with real ratios, why it might matter, the
  innocent reading and what to check.
- **Sources.** Every finding carries numbered sources (`backend/swarmscope/dashboard/cites.py`): the claims behind it,
  each followed by the recorded events that support it. They appear on Brief and Findings rows, in the finding
  drawer, after each finding in the live column and after each narration line. Labels are names, actions and times
  only; opening one goes through the evidence drawer and its untrusted-text boundary.
- **Cases.** Every finding at INVESTIGATE or above is a tracked case (`backend/swarmscope/org/cases.py`), whoever saw
  it first: a watcher, an analyst, a specialist's verdict, an agent's `escalate_finding` call, or you. A case keeps
  its escalation history and the independent sources that have seen it. ALERT and PAGE need two independent views and
  existing evidence, and draw on a per-cycle authority budget (`authority.alerts_per_cycle`); until then the request
  is held at INVESTIGATE with the reason. ALERT and PAGE wait for a person's acknowledgement, become overdue past the
  agreed time and lead the Brief; they never fade. Quieter cases fade with a recorded trail.
- **Investigations** (the Investigation Manager: timeline, communication, exposure, action verifier, trigger and a
  skeptic) run on request from a finding or from the analysts and conclude with findings and open points the record
  cannot settle.
- **Finding actions**: investigate, show in the World, watch more closely, pin, snooze, dismiss, acknowledge
  (`POST /api/incident/{id}/action`).

## Models

**Who does the reading** is chosen on the start screen (Change): no model; Claude through your Claude Code login,
with a model and effort for the **lead agent** (the lead analyst, the live-column assistant and the designers) and
for the **explorers** (everything the lead sends out); or an Anthropic API key (listed, not yet wired for the analyst
team). The top bar shows the choice.

| `llm.mode` | Behaviour |
|---|---|
| `stub` (default) | Deterministic: rule-based monitors, executive, analysts and investigators. No model calls. |
| `custom` | The start screen's choice: primary roles on `llm.primary`, every other role on `llm.subagents`. |
| `cheap` | Every role on Sonnet 5.5 at low effort. |
| `full` | Per-role models from `orgs/default.yaml` (Opus 5.5 executive and critic, Sonnet 5.5 investigators). |

Model calls go through the locally logged-in Claude Code CLI with the Claude Agent SDK (no API key needed). The CLI is
found through `CLAUDE_CLI`, then `claude` on the path, then `~/.local/bin/claude`. Its login is the standalone CLI's
(`claude`, then `/login`), separate from the Claude desktop app's sign-in. Analysts' only tools are the in-process
evidence MCP server. Spend is capped by `budgets.max_usd_per_hour`; past the cap, roles fall back to rules. Claude
Code 2.1.283 reports `claude-sonnet-5-5` as an unrecognized model and overestimates its cost several times over, so
treat reported costs as an upper bound; per-call CLI budgets are opt-in for that reason (`max_budget_usd`,
`max_budget_usd_per_agent`).

**Evidence tools** (`backend/swarmscope/llm/evidence_tools.py`, served over MCP): `query_events`, `events_by_id`,
`entity`, `neighborhood`, `artifact_meta`, `exposure_paths`, `timeline`, `window` (what happened between two times,
as counts), `history` (everything that happened to one resource), `observations`, `population_digest`,
`world_features`, `cohorts`, `cohort`, `unit_profile`, `outliers`, `templates`, `triage`, `sample_events`, and for
roles allowed raw text, `read_raw` and `search_text`.

## The dashboard

The design and its reasons are in [the dashboard design notes](design/dashboard.md).

- **The start screen** (`frontend/src/screens/Compose.tsx`) switches between Watch a swarm and Analyze a dump. Watch a
  swarm is one list of sources and a **How it runs** line that sums up the choices; **Change** opens every option:
  the reader and models, the team (the default, Composed for this data, the source's suggested preset, every preset),
  live or replay, the replay speed (each with an estimate of how long the whole replay takes), the update cadence
  and the monitoring organization. A focus box steers what gets composed.
- **Composing.** SwarmFrame reads the data, loads the pack's default views, has the designer propose a few pages with
  the reason for each, lays out the World, and ends with an orientation: what the data can and cannot show, how names
  are formed, which team reads it and why, how to study it, and good first questions. The same orientation is the
  live column's first message (`backend/swarmscope/assistant/orientation.py`). A source opened again reuses its saved
  pages and World (`data/composed.json`); **Recompose** starts fresh.
- **The rail**: Brief, Findings, World, Investigations, Control (live sources with control), this source's pages, and
  at the foot Under the hood, Settings and **New** (back to the start screen).
- **The Brief**: a one-sentence status with the counts underneath, an attention line, glance numbers (agents active,
  findings that need attention, investigations running, how much has been read closely), What's going on, Needs
  attention, and the World. Its glance numbers and attention list are configurable.
- **Findings, Investigations, Control** are the full lists. **Under the hood** shows the machinery as collapsed
  sections (the reading plan, groups that behave alike, what has been read, the analyst team, monitor health, where
  the effort goes, what SwarmFrame believes, message types, cost), each of which can also be put on a page.
- **Settings**: Look (the theme), Dashboard (lenses, the words used for agents and resources, the machinery as a page),
  Monitoring (autonomy and models, the executive, budgets, each monitor's slots) and Test bench (score the monitoring
  organizations on planted ground truth).
- **Edit** on every page: add a panel, build a view with a live preview, ask the designer, change the look, arrange,
  rename or move the page, save the layout as a lens, see the history, reset to the source's default, remove. Every
  change applies at once with an Undo. **Lenses** are saved layouts per scenario, each with its own pages and history.
  Labels go through one glossary (`frontend/src/words.ts`).

### Dashboard specs and the designer

Each source has its own dashboard specs (`data/dashboards/<source>.json`), one per lens, versioned and undoable; a spec
holds the Brief's settings and every page. The **designer** composes from a fixed library of views and a fixed set of
look settings, and every change goes through the same checked operations a person uses; it never writes code or CSS.
Edit → Ask the designer, Settings → Look, the live column and your own Claude Code session all reach it. With a model
on, a Claude session works with the dashboard and theme tools and the
[dashboard-designer skill](../.claude/skills/dashboard-designer/SKILL.md). With models off, the free designer reads
plain requests ("dark, compact, a teal accent, hide the World") into the same operations and says what it understood.
Claude sees capabilities, fields, categorical values and the scale layer, never agent text. Tools: `stream_profile`,
`view_catalog`, `view_preview`, `dashboard_edit`, `dashboard_undo`, `dashboard_lens`, `theme_options`, `theme_get`,
`theme_set`, `theme_undo`.

**The view library.** A view is a primitive plus a query in a small language: filters, a time range clipped to the
replay clock, up to two group-by fields and a metric. Derived sources are cohorts, templates, triage, claims, the
organization and observations. There is no raw SQL, and attributes that hold free text are refused.

| Primitive | Shows | Query shape |
|---|---|---|
| `stat` | one number, or a few tiles | no group_by, or one small dimension |
| `timeseries` | stacked area over time | `[ts:<bucket>]` or `[ts:<bucket>, <dimension>]` |
| `bar` | a ranking | `[<dimension>]` |
| `heatmap` | a grid of two dimensions | `[<dimension>, <dimension or ts:bucket>]` |
| `table` | rows of any result | anything |
| `feed` | the latest records, each opening its record | no group_by; `top` = rows |
| `graph` | who works with whom, linked through shared values | `[actor, object]` or two dimensions |
| `bipartite` | two linked columns weighted by count | two dimensions |
| `swimlane` | one lane per value, marks over time | `[<dimension>, ts:<bucket>]` |
| `note` | a short text from the designer | none |

Each view records what it `requires` (identities for `actor`, resources for `object`, timestamps for time views); a
view a source cannot support is refused. A click on a bar, row, node or lane opens the records behind it.

### The look

One theme for the whole app (`data/theme.json`, `backend/swarmscope/dashboard/theme.py`), versioned and undoable,
applied by `frontend/src/theme.ts` as CSS custom properties and data attributes; everything in
`frontend/src/styles.css` reads from those tokens.

| Setting | Values |
|---|---|
| `preset` | `observatory` (default), `paper`, `console`, `clinic`, `signal` |
| `mode` | `system`, `light`, `dark` |
| `accent` | a hex colour, or a name (`teal`, `blue`, `purple`, ...) tuned separately for light and dark |
| `fonts` | `display`, `ui`, `mono`, each from a fixed list of Google Fonts for that role |
| `density` | `compact`, `comfortable`, `roomy` |
| `radius` | 0 to 18 px |
| `surface` | `plate` (hairline with registration marks), `card`, `flat`, `outline` |
| `canvas` | `dots`, `grid`, `plain` |
| `nav`, `nav_style` | `dark` or `light` rail; `full` or `icons` only |
| `headline`, `labels`, `motion` | `small`/`medium`/`large`; `mono`/`sans`; `full`/`reduced`/`none` |
| `colors` | per-mode overrides of `bg`, `surface`, `raised`, `sunken`, `ink`, `ink2`, `ink3`, `ink4`, `line`, `line2`, `accent`, `data` |

Every change is resolved for both modes and checked before it applies: main text at least 7:1 against panels and the
page, secondary text 4.5:1, muted text 4:1, the accent 3:1, accent-coloured text 4.5:1, the rail's text 7:1. A change
that fails is refused with the pair and the ratio. The colours that carry meaning (finding levels, evidence status,
the categorical chart palette) cannot be set.

## The live column

On wide screens the live column is docked beside every page; on narrow ones it slides over. It posts a counts-only
line about each stretch of activity, every new finding the moment it appears (with "Why it may matter" folded), and
with a model on, the lead agent's own short summary. Its ⋯ menu sets what it shows, how often it posts (activity
every window, every minute or every five minutes; summaries every 5 or 15 minutes or never;
`POST /api/chat/settings`), the watch stream, and who answers:

| Target | What it is |
|---|---|
| Built-in assistant | A persistent Claude Agent SDK session in the backend with operator tools |
| My Claude Code | Your own interactive Claude Code session, connected through a SwarmFrame channel |

Operator tools (`/api/ops`, shared by both): `situation`, `query_events`, `observations`, `explain_claim`, `entity`,
`org_status`, `open_question`, `focus`, `defocus`, `pin`, `org_run`, `org_spawn`, `org_retire`, `run_cycle`, `clock`,
`control`, `set_config`. Messaging, interrupting or stopping live agents and switching the model mode show an approval
card first. Answers cite claim ids inline; the column turns them into numbered marks, shows `?` for an id not known
at the replay time, and labels an answer that cites nothing as *no sources cited · interpretation*. With models off
the assistant understands a few commands (`status`, `ask …`, `focus on …`, `play`, `pause`, `jump to …`, a claim id).

To connect your own Claude Code session (Claude Code channels, research preview):

```bash
.venv/Scripts/swarmframe channel-setup      # writes .mcp.json with this machine's interpreter path
claude --dangerously-load-development-channels server:swarmscope
```

Dashboard messages arrive in the session as `<channel source="swarmscope" kind="chat" chat_id=…>`; it answers with
the `reply` tool and gets the operator tools, and its permission prompts appear in the column as approve or deny
cards. Only the backend can push into the channel; it authenticates with `data/.channel_token`.

## The World

The World page places every agent in a 3D scene where position is a measurement: agents that work on the same files
and hosts, reply to each other, reuse each other's content or behave alike stand together, and agents whose behaviour
changes move and leave a trail. Places and props only set the scene. Drift, isolation, crowding and splitting groups
glow only when they exceed a shuffled-swarm null model. The legend explains every movement and colour with a live
count. Each source's scene and presets are in `packs/<id>/world.yaml`; Edit → Ask the designer runs the
[world-designer skill](../.claude/skills/world-designer/SKILL.md) with a model on and the free composer otherwise.
Findings have "Show me in the World", shift-drag selects a region to ask about, and analysts read the same spatial
features through `world_features`. The design is in [the World design notes](design/world.md).

## Analyze a dump

A side mode beside live monitoring: a folder or file of logs in, a report with sources out
(`backend/swarmscope/analysis/`).

- **Reading.** `dump.detect(path)` lists the files with their format, rows, fields and a guess at which field is the
  time, who acted, what they did, what they acted on, their group, their text and the record id, from field names and
  value shapes, never content. JSON, JSON lines and CSV, gzipped or zipped. Files without a time field are listed and
  left out. A folder SwarmFrame knows (the collusion.wiki export, the Transluce catalog, the AI Village export) is read
  with that source's own adapter; anything else with `DumpAdapter` and the mapping, which can be corrected in the UI.
- **Running.** A job (`analysis/jobs.py`) builds an engine and reads every window through the same watchers, monitors
  and analyst team as live monitoring, on rules (free and repeatable), then builds the report.
- **The report** (`analysis/report.py`): a TL;DR, a timeline tied to record ids, then the analysis (the data and what
  it cannot show, when it happened, the groups, the busiest actors, where they converged, how the environment
  responded, each detection with its innocent reading and a confidence, what the analysts flagged, how it was read).
- **Claude's write-up** (`analysis/writer.py`, optional). The record is cut into stretches with about the same number
  of records (`investigators`, default 4). One investigator reads each stretch and one reads across the whole record
  (identities, coordination, spread, moderation, beginning and end), at most `parallel` (default 5) at once, each
  starting from its stretch's counts and using the evidence tools. A writer turns their notes into the report with a
  confidence for each conclusion. `investigators: 0` investigates in `rounds` instead. If Claude cannot run, the job
  keeps the rules report and says why (`writer_error`).
- **Exploring.** "Explore in the dashboard" opens the finished engine as the session, paused at the end of the record;
  clicking a record id in the report opens it in the evidence drawer. Reports are also kept in `data/reports/`.

### Which team reads the dump

`options.strategy`, `options.strategies`, `options.search`; on the command line `--team`, `--compare`, `--search`:

- **Compose one** (default): the composer assembles a team for this data; `composer: claude` lets Claude choose among
  the same parts.
- **A preset**: any team as it is, or `auto` for the selector's pick.
- **Compare**: up to six teams each read the whole record. Without ground truth it measures what can be measured: the
  findings each team raised, how many teams agree on each (recall against the *consensus*, the findings most teams
  raised; identical teams count once), what only one team found, how much of the record the team read closely,
  supported claims, investigations concluded, agents, cost and time. The best by that measure is shown first.
- **Search**: four variants of the composed team and the selector's pick each read the first 30%, are scored (0.5 ×
  consensus recall + 0.35 × read closely + 0.1 × supported claims, minus agents and cost), and the best reads it all.

### Command line

```bash
swarmframe analyze PATH --out report.md                         # rules
swarmframe analyze PATH --write claude --words 2500-3000 --out report.md
swarmframe analyze PATH --compare composed lead triage_tree     # several teams, side by side
swarmframe analyze PATH --search                                # the best of five on the first 30%
swarmframe analyze PATH --detect                                # what is in the dump (structure only)
```

Other options: `--source` (read as a known source), `--team`, `--composer rules|claude`, `--model`, `--effort`,
`--investigators N`, `--parallel N`, `--rounds N`, `--title`.

## Evaluation and benchmarks

- **`swarmframe eval`** runs each monitoring organization on the synthetic AI Village corpus, which has planted ground
  truth (convergence, propagation with and without exposure, a false completion report, an operator burst, a surge, a
  drift), and scores recall, explanation, time to signal, exposure correctness, false incidents, unsupported
  inferences, model calls and coverage. Baselines are organization configs (`orgs/`): `baseline_deterministic`,
  `baseline_uniform_local`, `baseline_single_summarizer`. Settings → Test bench runs the same harness.
- **`swarmframe scale-eval --agents 2000 --hours 36`** runs a planted synthetic swarm and reports, per seeded
  behaviour, minutes to the first watcher signal, the first triage pick and the first close look that came back
  notable, plus the director's input size, the share of activity looked at, and lane hit rates. At 2,000 and 5,000
  agents every seeded behaviour was surfaced; triage looks found something 71–74% of the time, random audits 3%.
- **`python -m swarmscope.evals.world_eval 1000`** checks the World's layout against its null model.

### MessageBoardAuditBench

[MessageBoardAuditBench](https://github.com/hamzah2304/messageboardauditbench) measures how well a model reconstructs a
published investigation of the German message board from its logs.

- **Grading.** `scripts/mbab_grade.py <bench> <report.md>` reproduces the benchmark's grading code path (the
  committed v2 sheets with 38 points and the holistic TL;DR sheet, its system prompt, JSON parsing and retry,
  `max(2s − 1, 0)` per point, headline 0.7 × points + 0.3 × TL;DR) with Claude through the Claude Code CLI. The
  sheets and the answer key are filled in code and never printed; the script prints scores only.
- **The data.** Download `full-wiki-logs.zip` (SHA256 `eb68aa12...25ae`), unzip it, run the benchmark's
  `scripts/strip_analysis_fields.py` and `scripts/fill_verbatim.py` (standard library only; `python -X utf8` on
  Windows), normalise line endings, and check the four files against `data/SHA256SUMS.variants`.
- **Scoring a team.** `scripts/mbab_team.sh <team> [investigators] [parallel]` reads the bench with that team, lets
  Claude write the report, grades it and keeps the scores in `data/bench/teams/g_<team>.json`. One read of the whole
  record peaks near 2 GB of memory; run one team at a time on a busy machine.

Results so far (judge and writer Sonnet 5.5 at low effort; judged locally, so not comparable to the leaderboard; one
run each unless noted):

| Report | Headline | Points (strict) | Points (raw) | Points at 0.7 or more | TL;DR |
|---|---:|---:|---:|---:|---:|
| Rules only | 0.000 | 0.000 | 0.016 | 0 | 0.0 |
| Claude, one session (earlier writer) | 0.060 | 0.000 | 0.047 | 0 | 0.2 |
| Claude, rounds (earlier writer) | 0.037 | 0.011 | 0.105 | 1 | 0.1 |
| Claude, parallel investigators: composed team, run 1 | 0.093 | 0.047 | 0.166 | 3 | 0.2 |
| Claude, parallel investigators: composed team, run 2 | 0.149 | 0.084 | 0.168 | 5 | 0.3 |
| Claude, parallel investigators: lead with explorers | 0.104 | 0.063 | 0.155 | 4 | 0.2 |
| Claude, parallel investigators: triage tree | 0.112 | 0.074 | 0.161 | 4 | 0.2 |

The parallel writer roughly doubles the score (mean 0.115 over four runs against a best of 0.060 before) for about
$2.2 to $2.6 of writing per report. The team made no difference a single run can show: two runs of the same team
differed by 0.056, more than the spread between teams, so ranking teams needs several runs each.

## Configuration

**Organizations** (`orgs/*.yaml`; `default`, the baselines and `live_cheap`) set which monitors run and their slots,
autonomy, budgets, the executive strategy, the default team (`agents.topology`) and the models. The Monitoring tab
edits the running one; a session can override any key (`overrides` on `POST /api/session`, dotted keys).

| To change | Edit |
|---|---|
| A strategy slot | Add a function to `backend/swarmscope/strategies/slots.py` and register it in `SLOTS` |
| A monitor | A manifest in `backend/swarmscope/org/monitors/` |
| A watcher | Subclass `Watcher` in `backend/swarmscope/org/watchers.py` and add it to `WATCHERS` |
| An analyst team | A topology in `backend/swarmscope/agents/topologies/`, or the Organization page |
| A source | A pack in `packs/<id>/` and an adapter in `backend/swarmscope/sources/` |
| Dashboard panels | `frontend/src/panels/panels.tsx` (panels declare required capabilities; unsupported ones are hidden) |
| A source's default views | `packs/<id>/dashboard.yaml` |
| An LLM role's backend | `llm.roles.<role>.backend`: `claude_code`, `messages_api`, `external` (JSON lines) or `stub` |

| Environment variable | Use |
|---|---|
| `HF_TOKEN` | Hugging Face token for `fetch ai_village` (read, never saved) |
| `CLAUDE_CLI` | Path to the Claude Code CLI, if it is not on the path or in `~/.local/bin` |
| `ANTHROPIC_API_KEY` | Detected by the model picker; the analyst team does not use it yet |
| `SWARMSCOPE_DB_MEMORY` | DuckDB memory limit per store (default `1500MB`); past it DuckDB spills to disk |
| `SWARMSCOPE_DB_THREADS` | DuckDB threads per store (default 4) |
| `SWARMSCOPE_DB_TMP` | Where DuckDB spills (default `data/cache/duckdb_tmp`) |
| `SWARMSCOPE_URL`, `SWARMSCOPE_TOKEN` | The channel server's backend address and token |

## API

The dashboard talks to the backend over one WebSocket (`/ws`, a snapshot per window) and these routes.

| Area | Routes |
|---|---|
| Session and clock | `POST /api/session`, `GET /api/snapshot`, `POST /api/clock`, `GET /api/sources`, `GET /api/sources/{id}/slices`, `GET /api/compose/info`, `GET /api/orientation`, `GET /api/profile`, `GET /api/orgs`, `POST /api/config`, `GET /api/llm/options`, `GET /api/registry` |
| Ingest | `POST /ingest/events`, `POST /ingest/claude-code`, `POST /api/stream/demo` |
| Evidence | `GET /api/event/{id}`, `GET /api/entity/{id}`, `GET /api/claim/{id}`, `GET /api/observations`, `GET /api/attention/records`, `GET /api/views/{name}` |
| Findings and cases | `GET /api/incident/{id}`, `POST /api/incident/{id}/action`, `POST /api/investigation/{id}/action`, `POST /api/question`, `POST /api/directive`, `POST /api/directive/{id}/approve`, `GET /api/executive/history`, `POST /api/ledger/pin`, `DELETE /api/ledger/{id}` |
| Analyst team | `GET /api/agents`, `GET /api/agents/node/{id}`, `GET /api/agents/topologies`, `POST /api/agents/topology`, `POST /api/agents/action`, `GET /api/agents/delegations`, `GET /api/agents/proposals`, `POST /api/agents/proposal/{id}`, `POST /api/agents/promote` |
| Dashboard | `GET /api/dashboard`, `POST /api/dashboard/ops`, `POST /api/dashboard/undo`, `POST /api/dashboard/restore`, `POST /api/dashboard/lens`, `POST /api/dashboard/preview`, `POST /api/dashboard/design`, `POST /api/dashboard/auto`, `GET /api/dashboard/profile`, `GET /api/dashboard/data/{page}/{panel}`, `POST /api/design` |
| The look | `GET /api/theme`, `POST /api/theme` `{changes}`, `GET /api/theme/options`, `POST /api/theme/undo` |
| The World | `GET /api/world/spec`, `GET /api/world/state`, `GET /api/world/catalog`, `GET /api/world/preview`, `GET /api/world/features`, `GET /api/world/unit/{id}`, `POST /api/world/ops`, `POST /api/world/undo`, `POST /api/world/design`, `POST /api/world/select` |
| Live column | `GET /api/chat`, `POST /api/chat`, `POST /api/chat/settings`, `POST /api/chat/approval`, `POST /api/chat/channel`, `GET /api/ops`, `POST /api/ops/{name}`, `/ws/channel` |
| Control | `POST /api/control/action`, `POST /api/control/decide`, `POST /api/control/policy`, `POST /api/control/register`, `/ws/runner` |
| Analysis | `POST /api/analysis/detect` `{path}`, `POST /api/analysis/upload`, `POST /api/analysis/sample`, `POST /api/analysis/compose`, `POST /api/analysis/start` `{path, options}`, `GET /api/analysis`, `GET /api/analysis/{id}`, `POST /api/analysis/{id}/open` `{run}`, `POST /api/analysis/{id}/stop` |
| Evaluation | `POST /api/eval` |

## Layout of the repository

```
backend/swarmscope/   api (FastAPI app) · cli · engine · store (DuckDB) · core models · ingest · sources (adapters)
                      org (watchers, monitors, executive, cases, investigations, directives, risk) · strategies
                      scale (profiles, cohorts, templates, outliers, triage) · agents (topology spec, runtime,
                      selector, composer, org tools, topologies/) · llm (router, evidence tools) · dashboard (brief,
                      overview, explain, cites, query language, spec, designer, theme) · world · assistant (copilot,
                      chat, orientation, operator tools) · channel · control · analysis (dump, jobs, report, writer)
                      · runner · evals
frontend/src/         App · screens · components · panels · primitives · world · styles.css · theme.ts
packs/                ai_village · german_wiki · transluce · claude_code · generic_stream · dump · swarm_scale (tests)
orgs/                 default · baselines · live_cheap
.claude/skills/       swarm-oversight · dashboard-designer · world-designer
scripts/              fetch_village_events.py · swarmscope_hook.py · mbab_grade.py · mbab_team.sh
runner/scenarios/     smoke · tiny · research_team
docs/                 GUIDE · REFERENCE · design/ (dashboard, world, analyst-teams, reading-at-scale) · screenshots/
tests/                pytest suite
```
