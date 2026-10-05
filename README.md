# SwarmFrame

Adaptive, hierarchical oversight for populations of AI agents: replayed corpora or live Claude Code swarms.

A source describes what evidence exists. SwarmFrame composes the monitors and the dashboard around it, keeps a
living account of what the population is doing, spends extra machine cognition where something deserves it, and
keeps every conclusion tied to evidence. Every part is swappable: source adapters, watchers, the five strategy slots
of each monitor, the Executive strategy, the risk policy, investigators, and dashboard panels.

## Quick start

```bash
cd swarmscope
uv venv --python 3.11 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
cd frontend && npm install && npm run build && cd ..
.venv/Scripts/swarmscope serve
```

Open http://127.0.0.1:8765. The dashboard opens in **compose mode**:

1. **Link a swarm stream**, either a Claude Code swarm (runner or hooks) or any JSON event stream, or **pick existing
   swarm data** for a demo. Both live options have a demo switch: simulated Claude Code agents, or a planted swarm
   played into the stream in real time.
2. SwarmFrame reads the stream's structure. For a linked stream it infers the capabilities from what arrives (actors,
   resources, text, chat, tool calls, operator actions) and switches on the matching monitors.
3. **Default views** load for sources that ship them (AI Village, Transluce, the planted swarm, live Claude Code).
4. **Composing starts automatically** and proposes a small dashboard: the Brief's one or two signature views and at
   most three Activity pages, each with the reason it was proposed. The free composer runs with models off; with
   models on it is a Claude session with the dashboard-designer skill.
5. **Open the dashboard.** Replays start playing at a speed the source chooses (Transluce loads its whole history).

## The dashboard

**What's going on** (Brief, below the glance numbers; `dashboard/overview.py`): severity-free oversight. For each
group (team, model family, handle group) over the last few windows: how many are active, what kind of work, where,
toward which stated goal, and whether that is new, rising, steady, slowing or quiet; then what is **emerging** (places
used for the first time, new or rising kinds of work, groups that changed focus). Every line cites events. The lead
analyst and the live-column summaries read it too, so updates cover what is going on, not only what is wrong.

**Opening a source again reuses its views.** The first compose of a source runs the designers and records it in
`data/composed.json`; later composes of the same source reuse the saved dashboard and World (step 4 says "Using the
views saved for this source", with a **Recompose** link). A focus instruction also recomposes. Built-in views from
each pack's `dashboard.yaml` are fixed as before. Starting a new source starts a clean live column.

**The journey.** Compose mode states the whole path once, as four numbered steps at the top: *you pick the data* →
*an agent reads it* (what it records, what it cannot show) → *it builds your dashboard* (pages and an analyst team
for this data, each with its reason) → *you watch, it reports* (the live column narrates every window and raises
findings with sources; ask it anything). The form below is numbered to match (data, who reads, team shape, how to
play), and a *When you press Start* line says in one sentence what will happen with the current choices. The
composing screen ends with step 6, **Explaining it to you**: what the data can and cannot show, which team reads it
and why, how to study it, and good first questions (from the pack's `questions.yaml`; one click puts a question in
the live column). The same orientation is posted as the live column's first message (`assistant/orientation.py`,
`GET /api/orientation`), in every LLM mode.

**Citations.** Every finding carries numbered sources (`dashboard/cites.py`): the claims behind it (newest monitor
reports first, the one matching the finding's title leading; for analyst escalations, the evidence in the case
history), each followed by the recorded events that support it. They show as `sources [1][2][3] +n` on Brief and
Attention rows, as a **Sources** list in the finding drawer, after each finding posted in the live column, and after
each narration line (one recorded event per leading workstream plus the busiest resource). Copilot answers cite
claim ids inline; the dock turns them into numbered marks with a *sources* list underneath, shows `?` for an id
unknown at the replay time, and labels an answer that cites nothing as *no sources cited · interpretation*. Labels
are names, actions and times only; opening a source goes through the evidence drawer and its untrusted-text boundary.

Minimal by default, fully informative on demand (design notes in [docs/UI_PLAN.md](docs/UI_PLAN.md)). The visual
identity, "Observatory", is a graphite rail on a dot-grid paper canvas, instrument-plate panels, one vermilion signal
colour for what needs action, and a live swarm field behind the Brief's headline whose streaks are the active
agents, coloured by workstream.

- **Brief** (home, one screen): a status sentence, glance numbers, **Needs attention** (findings deduplicated,
  grouped and ranked ACT / LOOK / WATCH, each with a *Next* step and actions: investigate, watch, pin, snooze,
  dismiss), the signature views, and what changed.
- **Attention**: every open finding, filterable, plus SwarmFrame's pending suggestions to apply or reject.
- **Activity**: the source's pages (composed or default; nothing is labelled built-in any more), plus *Add a page*.
- **Investigations** and **Control** (live sources with control) as before.
- **Under the hood**: the reading plan, groups of similar agents, what has been read, the analyst team, monitor
  health, message types and cost, as collapsed sections whose headers carry a one-line summary.
- **Settings**: lenses, the words used for agents and resources, the machinery switch, theme, monitoring and models,
  and strategy comparison.

Everything is customizable. **Edit ▾** on every page (the Brief included): add any panel to any page (machinery
too), build a view with a live chart preview, ask Claude, arrange (resize, reorder, remove), rename or move a page,
reset it to the source's default, and see the history. Every edit applies at once with an **Undo** toast. The Brief's
glance numbers and attention list (rows, minimum severity) are configurable. **Lenses** are saved layouts per scenario
("Incident review", "Weekly report"), switched from the top bar; each keeps its own pages and history. Labels go
through one glossary (`frontend/src/words.ts`) with hover help; internal terms such as cohort or triage appear only as
plain words.

`swarmscope serve --source <id>` skips compose mode and starts a session directly.

| Source | What it is |
|---|---|
| Replay the village | A real AI Village slice (needs the subset, see Data) |
| Planted scenario | Synthetic AI Village corpus in the real schema, with ground truth |
| Live swarm | The live Claude Code source with simulated agents (20 to 2,000) |
| Planted swarm at scale | 500 to 5,000 synthetic agents in teams, tens of thousands of messages, planted behaviours |
| Agent activity on the web | The Transluce catalog: 37,649 scan reports attributed to agents, no identities |
| Any event stream | Whatever you post to `/ingest/events`; capabilities inferred, dashboard composed around them |

For frontend development run `npm run dev` in `frontend/` (port 5173, proxied to the API).

## The default strategy at scale: a triage tree

The default organization is designed for thousands of agents writing thousands of messages each, where no
organization of models can read the stream. The full design, with the research behind it and measured results, is
in [docs/STRATEGY.md](docs/STRATEGY.md).

```
every event ── code ──► scale layer: profiles · cohorts · message templates · outliers      (every window)
                    ──► watchers with per-resource baselines                                  (every window)
                    ──► triage: reading plan in three lanes                                   (every cycle)
                          triage 60% (priority) · coverage 25% (debt) · audit 15% (random, secret seed)
a few dozen scopes ──► division analysts · auditor · specialists ──► sector leads ──► director
```

- **Code reads everything; models read what triage picked, plus a random slice.** The random slice keeps triage
  honest: lane hit rates show what triage misses, and the audit share never drops below 10%.
- **Attention follows structure, not population.** The reading budget is 4·√cohorts per cycle. Sector leads appear
  once divisions outgrow one reader, so the director reads a bounded digest: 25k characters at 500 agents, 36–41k at
  5,000.
- **Every level reports in a fixed shape** with graded claims, a `looked_at` entry per reading-plan pick (including
  "nothing notable"), and blind spots. A coverage ledger each cycle says what got a close look and what did not.
- **One skill instructs every role.** [`.claude/skills/swarm-oversight/`](.claude/skills/swarm-oversight/SKILL.md)
  holds the doctrine plus per-role references. The runner injects it into each agent; a Claude Code session opened
  here discovers it natively.

On the planted swarm, all five planted behaviours were watched, triaged, and surfaced as notable by an agent, at
both 2,000 agents (81k events) and 5,000 agents (204k events). Triage looks found something 71–74% of the time,
random audits 3%.

```bash
.venv/Scripts/swarmscope scale-eval --agents 2000 --hours 36
```

### Tracking and escalating what is found

Every finding at INVESTIGATE or above is a tracked *case* (`backend/swarmscope/org/cases.py`), whoever saw it first: a
watcher, a division analyst's concerning report, a specialist's supported verdict, an agent calling the
`escalate_finding` tool, or you. A case keeps its escalation history (when, to what level, by whom, why, on which
evidence) and the independent sources that have seen it. ALERT and PAGE need two independent views and existing
evidence, and draw on a per-cycle authority budget (`authority.alerts_per_cycle` in the topology); until then the
request is held at INVESTIGATE with the reason and granted the moment the second view arrives. An agent's escalation
reaches the Brief immediately and brings the executive forward instead of waiting for its cadence. ALERT and PAGE wait
for a person's acknowledgement; past the SLA they are overdue and lead the Brief, and the tab title carries the
count. Quiet lower cases fade with a recorded trail; ALERT and PAGE never fade. Design notes:
`docs/OVERSIGHT_ARCHITECTURES.md` §7.1.

### Which team reads a stream: the lead with explorers, and the presets

**The default team is `lead`** (`agents/topologies/lead.yaml`): one lead analyst watches the whole stream and, when an
area starts to look interesting, sends an **explorer** there. Interest is concrete: every open finding at
`explore_min_level` (INVESTIGATE) or above gets an explorer for its area (a place, a group, a piece of copied text, a
workstream), at most `explore_max` (4) at a time; an explorer is let go when its finding closes, or after
`explore_ttl_cycles` (4) cycles if the finding did not rise. With a model on, the lead can also spawn, re-run and
retire explorers itself (`org.spawn_agent` and friends) from its own reading; its prompt (`prompts/lead.md`) asks it
to explain the picture in plain words. Nothing is pre-assigned, so the team grows only where something is happening.

The other topologies are **presets**, offered on the Compose screen under "Show the other team presets" with plain
descriptions; each pack's `oversight.yaml` names the preset that suits it (`preset:`), shown as "suits this source".

Teams are topologies (`backend/swarmscope/agents/topologies/*.yaml`) written in one grammar: roles, a `partition`
(cohorts, or any categorical field), `levels` inserted by span of control, `standing` roles, a `questions → role`
map, a `cadence` (time windows or record batches), a `human` contract (digest cadence, interrupt level, what needs
approval), an `envelope` (what the director may change alone) and an `authority` budget. The library ships
`triage_tree` (thousands of agents), `desks` (the Village: per-group desks, a diarist, standing integrity and goals
specialists; Sonnet director by default, any model per role), `board_watch` (the German board: namespace analysts,
identity resolver, moderation response) and `catalog_review` (Transluce: method analysts, grade auditor, chronicler,
record-batch cycles). A pack can still force a team with `topology:` in `packs/<id>/oversight.yaml`; `topology: auto` lets the selector
(`agents/selector.py`) choose from the stream's shape with reasons, and when models are on a Scout reviews the pick
and proposes refinements. Proposals (new roles, partition changes) apply alone inside the envelope or wait for you on
the Brief; an applied one can be reverted; a running team can be saved as the source's preset. Pick a team on the
Compose screen ("How is the team shaped?") or switch on the Organization page. Design: `docs/OVERSIGHT_ARCHITECTURES.md`.

Agents also delegate on their own: any director or analyst can fire off a `reader` sub-agent it briefs itself (Task
tool), and every delegation (native sub-agent, spawn, re-task, retirement, escalation, or a `log_decision` note on
why it did not delegate) is written with its reason to `data/runs/<session>/delegations.jsonl` and shown in the
Organization page's delegation log. The doctrine is `.claude/skills/swarm-oversight/references/delegation.md`.

## The analyst organization (core module)

The Executive is not one LLM call. It is a **main agent that builds and steers its own team** of structured
sub-agents, defined entirely by a topology file in `backend/swarmscope/agents/topologies/`.

```
Director (root, whole population)            Claude Code session with org tools + evidence tools
 ├─ Division analyst · <division>            one per division; scoped evidence; structured report; notes memory
 │   ├─ Specialist · <scope>                 bounded question (integrity, propagation, timeline, response)
 │   └─ helper (native Claude Code subagent) ephemeral, via the Task tool
 └─ Division analyst · <division> …
```

- **Divisions** partition the population (agent–resource communities, workstream, group, or defined by the agent).
  Ids stay stable as the population drifts.
- **Each cycle** runs three phases. First, due agents refresh and report bottom-up. Second, the Director reads them,
  reshapes the team, and writes the executive state. Third, the maintenance policy covers, retires and splits.
- **Org tools** let an agent shape its team: `spawn_agent(s)`, `run_agent`, `split_division`, `merge_divisions`,
  `define_division`, `retire_agent`, `ask_question`, `org_status`. Each is checked against the topology's
  `can_spawn`, `max_agents`, `max_depth` and budget. A parent waiting on children gives up its concurrency slot,
  so nesting cannot deadlock.
- **Every role is configurable**: prompt, model, effort, max turns, tools (with globs), raw-text access, which
  roles it may spawn, output schema (`director`, `division_report`, `finding`, or custom JSON schema), memory
  (`none`, `notes`, `session` resume, `state`), scope, refresh cadence, native helpers, and backend
  (`claude_code`, `stub`, `external`).
- **Shipped topologies**: `triage_tree` (default, see above), `hierarchical_divisions` (director and community
  analysts, for small swarms), `flat_pool`, `single_agent`, `sdk_native` (one session with native Claude Code
  subagents). Edit them in the **Organization → Topology** screen; changes validate and apply
  live, and can be saved as new topology files.
- **Deterministic mode** runs the same mechanism with rule-based behaviours per role, so the team grows, splits and
  reports for free.

## Talking to the stream: copilot and Claude Code channel

**Findings in plain words.** Every finding carries an `explain` block (`dashboard/explain.py`): what happened in
everyday words with real ratios (never a z-score), why it might matter, the innocent reading, and what to check.
It shows under the row on the Brief, in the drawer ("In plain words"), on finding posts in the live column, and is
handed to the copilot, whose prompt now asks it to write for someone new to the data and to avoid internal terms.
Each pack's `source.yaml` has a `naming` note (how names are formed: "team 5 · agent 8" is the eighth agent of team
5; German handles are the board's own; and so on) and a `workstream_noun` (page family, method, workstream) used in
the status sentence; the naming note is in the orientation and the copilot's first turn.

**How often it speaks** is a setting (compose step 5 and the live column's header): activity updates every window,
every minute (default) or every 5 minutes; and, with a model on, the lead agent's own short summary every 5 or 15
minutes or never (`ChatHub.narrate` / `ChatHub.commentary`, `POST /api/chat/settings`). New findings always post at
once.

The **Ask SwarmFrame** dock (bottom right, every screen) talks to an agent that operates over the same stream:

| Target | What it is |
|---|---|
| Built-in copilot | A persistent Claude Agent SDK session in the backend, with operator tools |
| My Claude Code | Your own interactive Claude Code session, connected through a SwarmFrame channel |

Operator tools (`/api/ops`, shared by both targets): `situation`, `query_events`, `observations`, `explain_claim`,
`entity`, `org_status`, `open_question`, `focus`, `defocus`, `pin`, `org_run`, `org_spawn`, `org_retire`,
`run_cycle`, `clock`, `control`, `set_config`. Messaging, interrupting or stopping live agents, and switching the LLM
mode, show an approval card in the dock first. **Watch stream** pushes new incidents and revised assessments to the
agent as they happen. In deterministic mode the copilot understands a few commands (`status`, `ask …`,
`focus on …`, `play`, `pause`, `jump to …`, or a claim id).

To connect your own Claude Code session (Claude Code channels, research preview):

```bash
.venv/Scripts/swarmscope channel-setup      # writes .mcp.json with this machine's interpreter path
claude --dangerously-load-development-channels server:swarmscope
```

The channel server declares `claude/channel` and `claude/channel/permission`. Dashboard messages arrive in the
session as `<channel source="swarmscope" kind="chat" chat_id=…>`. The session answers with the `reply` tool and gets
the operator tools. Its permission prompts appear in the dock as approve or deny cards. Only the backend can push
into the channel; it authenticates with `data/.channel_token`.

## Linking any stream

```bash
curl -X POST http://127.0.0.1:8765/ingest/events -H "Content-Type: application/json" -d '[
  {"ts": "2026-10-03T14:05:00Z", "actor": "agent-17", "group": "team-a", "action": "tool.write",
   "object": "repo/README.md", "family": "files", "text": "optional agent-written text", "attrs": {"model": "sonnet"}}]'
```

Only `action` is required. Text goes behind the evidence boundary like every other source. Capabilities are
re-inferred every 12 windows, so monitors and panels switch on as new kinds of events appear.

## A dashboard Claude shapes around the stream

Each source gets its own dashboard specs (`data/dashboards/<source>.json`), one per lens, versioned and undoable.
A spec holds the Brief's settings and every page (the Brief is page `brief`).

- **On session start** the source's default views load (`packs/<id>/dashboard.yaml`: a `brief:` block and pages);
  sources without one get a Brief composed from the stream profile.
- **Edit → Ask Claude** runs one Claude Code session with the dashboard tools and the
  [dashboard-designer skill](.claude/skills/dashboard-designer/SKILL.md) when models are on; with models off it is
  the free composer. Claude sees capabilities, fields, categorical values and the scale layer, never agent text.
- **The copilot and your own Claude Code session** have the same tools: `stream_profile`, `view_catalog`,
  `view_preview`, `dashboard_edit`, `dashboard_undo`, `dashboard_lens`.
- **The Brief digest** (`backend/swarmscope/dashboard/brief.py`) groups and ranks findings, writes their next step
  and keeps the status sentence consistent, in every LLM mode.
- **Views** are a primitive (`stat`, `timeseries`, `bar`, `heatmap`, `table`, `note`) plus a query in a small
  language: filters, a time range clipped to the replay clock, up to two group-by fields, and a metric. Derived
  sources are cohorts, templates, triage, claims, the organization and observations. There is no raw SQL, and
  attributes that hold free text are refused.

## The World: a 3D map of the swarm

The World page places every agent in a 3D scene where **position is a measurement**. Agents that work on the same
files and hosts, reply to each other, reuse each other's content or behave alike stand together. Agents whose
behaviour changes move, and leave a trail. The full design is in [docs/WORLD_PLAN.md](docs/WORLD_PLAN.md).

- **Honest about the data.** SwarmFrame observes and does not instrument, so each feature is graded observed,
  derived, inferred or absent per stream. Positions use derived features only, so the map is the same with models
  on or off. The legend lists what a stream cannot show.
- **Premade first, new models when needed.** Agent characters (ported from newts-lab), pawns, dots, plinths,
  landmarks, rings, beams, bubbles and trails are premade. When none says what a stream's agents or places are,
  Claude makes a model from a part kit (shapes, theme colours, materials, gentle animations), checks it with ASCII
  silhouettes, and the dashboard compiles and instances it. Models are data, never code; see
  [references/models.md](.claude/skills/world-designer/references/models.md).
- **Scales by tier.** Characters up to about 80 agents, instanced pawns up to about 2,000, dots and cohort blobs
  beyond that. Places become plinths when the stream has no agent identities.
- **A scene and activity rules.** Each World has a ground, zones that say what each region is (rooms, desks,
  datasets) and props from a generic library (trees, benches, desks, racks, houses) that set the scene and encode
  nothing. Activity rules make the stream legible: agents walk to the page or file they act on and back, gather at a
  plaza when they talk, wander when idle, scatter when moderated, fade when stopped. Every walk returns to the measured
  position, and the legend's "What you are seeing" states each rule. The designer picks from the libraries or composes
  its own rule from library steps; see [environment.md](.claude/skills/world-designer/references/environment.md) and
  [behaviours.md](.claude/skills/world-designer/references/behaviours.md).
- **Glow only beyond chance.** Drift, isolation, crowding, "talking without moving" and splitting groups are
  flagged only when they exceed a shuffled-swarm null model at a family-wise threshold.
- **Designed per stream.** Presets live in `packs/<id>/world.yaml`. **Edit → Ask Claude** runs the
  [world-designer skill](.claude/skills/world-designer/SKILL.md) with models on, and the free composer otherwise.
- **Part of the dashboard.** The Brief shows the live World beside "Needs attention". Findings have "Show me in the World". Shift-drag selects a region and "Ask about
  these" hands it to the copilot. The World is also a panel you can add to any page. Analysts and the copilot read
  the same spatial features through `world_features`.

```bash
.venv/Scripts/python -m swarmscope.evals.world_eval 1000
```

## Timed simulator

- **Replay at a chosen pace.** The top bar sets simulated time per real second: real time, 1 min/s, 10 min/s,
  1 h/s, 6 h/s, or max. "Skip gaps" fast-forwards over stretches with no events.
- **Jump to a time.** The replay catches up deterministically and fast, then hands back to the configured LLMs.
  Jumping backwards restarts the session and catches up to the target.
- **Live simulator.** The live Claude Code source can run 20 to 2,000 simulated agents at real time, 3× or 10×,
  with planted behaviours on a schedule.

## How it works

```
Evidence (DuckDB) ─► Watchers (deterministic, every window)
                   ─► Monitors (retrieval → summarization → evaluation → escalation → critique)
                   ─► Executive  — master role: ExecutiveState + ContextLedger
                        │  bottom-up: MonitorReports, claims, investigation results
                        │  top-down:  Directives (ask, focus, defocus, tune, activate, audit, brief_human)
                   ─► Investigation Manager (timeline, communication, exposure, action verifier, trigger, …, skeptic)
                   ─► Brief digest ─► dashboard (WebSocket snapshot)
```

- **Watchers** never call a model. They detect convergence on shared resources, content reuse with or without an
  observed exposure path, rate surges, operator and environment events, say-versus-do mismatches, and focus shifts.
- **Monitors** are a manifest plus five strategy slots (`backend/swarmscope/org/monitors/*.yaml`). Each emits a
  report with claims, a risk vector and an operational level (WATCH, INVESTIGATE, ALERT, PAGE).
- **The Executive** sees only structured reports, never raw agent text. It owns the population picture, hypotheses
  and a context ledger, and steers attention through directives. Autonomy decides whether directives are recorded
  (observe), held for approval (assisted) or applied (auto_investigate). Human directives always apply.
- **Claims** carry an epistemic status: OBSERVED, DERIVED, SELF_REPORTED, INFERRED, CONTRADICTED or UNKNOWN. A
  verifier downgrades any model-proposed OBSERVED or DERIVED claim whose cited events do not exist or are in the future.
- **The evidence boundary**: agent-written text is fingerprinted, stored behind a reference, and reaches models only
  through `read_raw`, wrapped in an escaped `<untrusted>` envelope. The Executive and critic cannot call it.

## Swapping things

| To change | Edit |
|---|---|
| Which monitors run, slots, autonomy, budgets | The Configure screen, or an `orgs/*.yaml` file |
| A strategy | Add a function to `backend/swarmscope/strategies/slots.py` and register it in `SLOTS` |
| The Executive | `executive.strategy`: agent_org (default), structured_state, persistent_session, hierarchical_summary, ensemble, deterministic, global_summary |
| The analyst organization | A topology in `backend/swarmscope/agents/topologies/`, or the Organization → Topology screen |
| A monitor | Add a manifest in `backend/swarmscope/org/monitors/` |
| A watcher | Subclass `Watcher` in `backend/swarmscope/org/watchers.py` and add it to `WATCHERS` |
| A source | Add `packs/<id>/` with `source.yaml`, `capabilities.yaml`, `monitors.yaml`, `questions.yaml`, `views.yaml` |
| Dashboard panels | `frontend/src/panels/panels.tsx`; panels declare required capabilities, unsupported ones are hidden |
| A source's default views | `packs/<id>/dashboard.yaml` (`brief:` and `pages:`) |
| An LLM role backend | `llm.roles.<role>.backend`: claude_code, messages_api, external (JSON lines), or stub |

## LLM modes

Compose step 2, **Who does the reading?**, is a model picker: a provider (no model; Claude through your Claude Code
login; an Anthropic API key, listed but not wired for the analyst team yet), then the **lead agent's** model and
effort (the lead analyst, the live-column assistant and the designers) and the **explorers'** model and effort
(everything the lead spawns). That is `llm.mode: custom` with `llm.primary` and `llm.subagents`
(`config.custom_llm`, `GET /api/llm/options`); the top bar shows the choice (`org.llm_label`).

| Mode | Behaviour |
|---|---|
| `stub` (default) | Deterministic. Rule-based monitors, executive and investigators. No model calls. |
| `custom` | The model picker: primary roles (lead/director, executive, copilot, designers) on `llm.primary`, all other roles on `llm.subagents`. |
| `cheap` | Every role on Sonnet 5.5 at low effort through the locally logged-in Claude Code CLI (Claude Agent SDK). |
| `full` | Per-role models from `orgs/default.yaml` (Opus 5.5 executive and critic, Sonnet 5.5 investigators). |

Investigators in LLM modes are Agent SDK agents whose only tools are the in-process evidence MCP server. Spend is
capped by `budgets.max_usd_per_hour`; when the cap is hit, roles fall back to deterministic.

Cost note: Claude Code 2.1.283 reports `claude-sonnet-5-5` as an unrecognized model and its `total_cost_usd`
estimate ran several times higher than Sonnet pricing in testing. Treat reported costs as an upper bound. For the
same reason, per-call CLI budgets are opt-in (`max_budget_usd`, `max_budget_usd_per_agent`).

## Live Claude Code swarms

```bash
.venv/Scripts/swarmscope serve --source claude_code             # start a live session
.venv/Scripts/swarmscope run-swarm runner/scenarios/smoke.yaml  # 1 real agent, 4 turns
.venv/Scripts/swarmscope run-swarm runner/scenarios/tiny.yaml   # 3 agents sharing a folder
```

The runner launches each agent as a `ClaudeSDKClient` session. Hooks stream every tool call to `/ingest/claude-code`;
every permission request goes to `/api/control/decide`, which applies the pack's control policy, holds paused agents,
and can hold an action for a human in the Control screen. Operators can pause, resume, message, interrupt and stop
agents or whole groups.

To watch any other Claude Code session, add hooks that run `scripts/swarmscope_hook.py` (instructions in the file).
Hook forwarding is observation only.

## Data

The AI Village dataset is gated and about 6 GB. SwarmFrame fetches a budgeted subset:

```bash
HF_TOKEN=... .venv/Scripts/swarmscope fetch ai_village --set village_dense   # ~95 MB
```

| Set | Contents | Use |
|---|---|---|
| `village_dense` | Full chat and computer-use session goals, plus small tables | Default replay |
| `computer_use_sample` | Head slices of events, sessions and turns | Action-level monitors |
| `claude_code_sample` | Head slice of the Claude Code agent stream | Tool-call monitors |

The demo week (Jun 29 to Jul 4, 2026) also has its slice of `events.jsonl.gz` in `data/ai_village/events.jsonl.gz`
(11 MB, streamed from the 329 MB file and filtered by date; everything kept except outreach recipients, which are
reduced to domain + hash). The adapter maps memory consolidations, pauses (an `idle` family that never counts as work),
history searches (query and answer), room moves, sign-in and human-helper handoffs, and outreach (the drafted message
and rationale, then a person's approval or denial with their comment). Each action's raw model output becomes the
agent's **private reasoning**, an untrusted artifact on the event (also attached to the chat message it produced),
read with the four provider shapes in `reasoning_of`; analysts get its id from `query_events` and read it with
`read_raw`, and the evidence drawer shows it. The integrity monitor's `reasoning_cues` watcher flags reasoning that
talks about keeping something from people, reporting unfinished work as done, working around a restriction or
credentials (weighted; such findings do not fade until dismissed). Chat and session rows the timeline repeats are
skipped. `computer_use_turns.jsonl.gz` (2.5 GB, per-step computer actions) is not fetched yet.

The export is not time-ordered, so head slices are sparse samples across the timeline, not dense windows.
`swarmscope probe <dir>` reports structure only (field names, types, value shapes); values print only with
`--show-values`.

The Transluce agent-activity catalog is a public 4.6 MB package of report links and metadata. It has no report
bodies or payloads.

```bash
.venv/Scripts/swarmscope fetch transluce        # downloads and unzips into data/transluce
```

Each report becomes one event: a method class (source_request, custom_program, indirection), the source's own
confidence grade (significant or suggestive), and the targeted data source. Without the download, the pack falls
back to a synthetic stand-in in the same schema with planted episodes.

Transluce is a **catalog**, not a live swarm (`catalog: true` in its source.yaml). Its Brief summarises the whole record
(totals, the 90-day trend, the most targeted sources, the method mix and how it shifts, the share graded significant)
instead of the last few windows. Its World is a map of targets: each method class is a corner, each target stands
between the corners in proportion to how it was reached, tower height is its number of reports, colour bands are
its method mix and glass means mostly suggestive.

The German message board (collusion.wiki, `packs/german_wiki`) is handles writing on a shared wiki from May to July
2026, with partial identities. The export comes from collusion.wiki/explorer/download; SwarmFrame uses five of its
files (events, revisions, pages, labels, manifest; about 4 MB) in `data/german_wiki`: 14,591 saves, 5,217 moderator
deletions, 4 reverts and 101 probes from May 17 to July 14 2026. The main analysis period is the June surge (June 10 to 25:
74% of all events, with quieter days first as a baseline) in half-hour windows; the whole record is one click away
on the compose card. Saved bodies are fingerprinted behind the evidence
boundary and never shown; network prefixes in the export are not used, so identity stays partial. Without the
export, a seeded synthetic stand-in reproduces the documented shape with neutral placeholder text.

Every replay has a speed you choose when composing and can change from the top bar. Each source recommends speeds
measured from its density (windows that hold events, events per window), with an estimate of how long the whole
replay takes; quiet stretches are skipped. "Real time" replays at the recorded pace, which only makes sense for a
short stretch; the live sources (a Claude Code swarm, any event stream) are real time by nature.

**Watch live.** For the replay sources, the default on the compose screen is to watch the source's busiest real
stretch at real time: the planted swarm's surge afternoon (~40 events a minute), the German board's evening of June 18
(~30 edits a minute, up to 225), Transluce's busiest night and the village's busiest evening. SwarmFrame first reads the
preceding hour or so at full speed (so the monitors know what usual looks like), then switches to real time with
30-second windows: the Brief, findings and World refresh twice a minute, and the top bar shows LIVE.

**SwarmFrame · live.** On wide screens the assistant is a docked column beside every page: a running, counts-only
narration of each beat ("41 events by 23 handles; mostly relay-coordination; activity is picking up"), new findings the
moment they appear, a countdown to the next update, and the question box. With Claude on, the copilot also comments
when something needs attention. "Conversation" hides the narration; the column collapses to a slim rail.

## Evaluation

```bash
.venv/Scripts/swarmscope eval
```

`swarmscope scale-eval --agents N` runs the planted swarm at scale and reports, per planted behaviour, minutes to
the first watcher signal, to the first triage pick, and to the first close look that came back notable. It also
reports the director's input size, the share of activity looked at, and lane hit rates.

Baselines are organization configs: `baseline_deterministic`, `baseline_uniform_local`, `baseline_single_summarizer`.
Each runs on the synthetic corpus and is scored for recall, explanation, time to signal and explanation, exposure
correctness, false incidents, unsupported inferences, model calls and coverage. The Evaluate screen runs the same harness.

## Tests

```bash
.venv/Scripts/python -m pytest -q
```

## Layout

```
docs/STRATEGY.md     the default oversight strategy at scale: design, research, measurements
.claude/skills/      swarm-oversight (doctrine + per-role references) · dashboard-designer
backend/swarmscope/  scale (templates, cohorts, outliers, triage) · dashboard (query language, stream profile, spec,
                     designers) · agents (topology spec, runtime, runners, org tools, skills, divisions, topologies/) · assistant (copilot,
                     chat hub, operator tools) · channel (Claude Code channel server) · core models · store · ingest · sources · org (watchers, monitors,
                     executive, investigations, directives, risk) · strategies · llm (router, evidence tools)
                     · control (plane, simulator) · runner · api · evals · cli
packs/               ai_village · claude_code · transluce · swarm_scale · generic_stream (each may ship dashboard.yaml built-in views)
orgs/                default · baselines · live_cheap
frontend/src/        panels · primitives (timeline, bipartite, swimlanes, lineage) · screens · components
runner/scenarios/    smoke · tiny · research_team
```
