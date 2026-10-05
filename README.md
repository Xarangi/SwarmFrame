# SwarmFrame

SwarmFrame is a dashboard for watching a large group of AI agents while they work. You point it at a source of
agent activity. It reads the data, builds a dashboard that fits it, and keeps telling you what is going on.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/04-brief-dark.png">
  <img alt="The Brief for the AI Village: a status line, glance numbers, what each group is doing, and the live column on the right" src="docs/screenshots/04-brief-light.png">
</picture>

It is built for three questions:

- **What is everyone doing right now?** Each group of agents gets a line saying how many are active, what kind of
  work they are doing, where, and toward which goal. New and rising activity is listed on its own.
- **Does anything need my attention?** Watchers and a team of analyst agents raise findings. Each finding says what
  happened in plain words, why it might matter, what the innocent explanation would be, and which records it rests on.
- **Can I trust what I am told?** Every claim cites its sources. Click a number and you see the record behind it.

A live column on the right narrates the stream as it arrives, posts findings the moment they appear, and answers
questions.

## Quick start

You need Python 3.11, Node 20 or later, and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Xarangi/SwarmFrame.git
cd SwarmFrame
uv venv --python 3.11 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
cd frontend && npm install && npm run build && cd ..
.venv/Scripts/swarmframe serve
```

On macOS or Linux use `.venv/bin/` in place of `.venv/Scripts/`. Then open http://127.0.0.1:8765.

The recorded sources need their data first (see [Data](#data)). The two live options, a Claude Code swarm and any
JSON event stream, work without downloading anything.

## How it works, in four steps

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/01-start-dark.png">
  <img alt="The start screen: four steps, then the data sources" src="docs/screenshots/01-start-light.png">
</picture>

1. **You pick the data.** Link a live stream, or open one of the recorded sources.
2. **An agent reads it.** It works out what the data records (who did what, when, who talked to whom, what they
   worked on) and what it cannot show.
3. **It builds your dashboard.** It sets up pages and a team of analysts for this data, and tells you why it chose
   each one.
4. **You watch, and it reports.** The live column posts an update every window and raises findings as they appear.

Before you press Start you choose who does the reading (fixed rules for free, or Claude through your Claude Code login,
with a separate model for the lead agent and for the agents it sends out), how the analysts are organised, whether to
watch live or replay, and how often you want updates.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/02-setup-dark.png">
  <img alt="Setup: provider and models, the analyst team, live or replay, and how often to report" src="docs/screenshots/02-setup-light.png">
</picture>

The [guide](docs/GUIDE.md) walks through every screen.

## Make it yours

Everything on the dashboard can be changed while it runs, and every change can be undone.

- **Pages and panels.** Every page has an **Edit** menu. Add any panel, remove or resize panels, rename or reorder
  pages, give a page its own place in the navigation, or reset it to the source's default.
- **Build a view.** Pick a chart type (a number, a trend, a ranking, a grid or a table), what to count and how to
  split it, and see a live preview before you add it.
- **Ask Claude.** Describe the view you want in a sentence and a Claude session builds it with the same tools you
  have.
- **Lenses.** Save a whole layout under a name ("Incident review", "Weekly report") and switch between them from the
  top bar.
- **Words.** Call things what your team calls them: agents, handles, reports, targets, pages.
- **The Brief.** Choose its glance numbers, how many findings it lists and from which level, and whether it shows
  "What's going on" and the World.
- **The World.** The 3D view has its own designer: the scene, the zones, the props, and the rules for how agents
  move (walk to what they work on, gather to talk, step back when stopped). Claude can design it, or you can.
- **The analysts.** The default team is one lead analyst that sends explorers to anything that starts to look
  interesting. Other team shapes are presets you can pick, and any team can be edited role by role.
- **Your own source.** Post JSON events from any swarm and SwarmFrame works out what your data contains and composes
  a dashboard around it. Or write a source pack: a folder of YAML files that describes the data, its default views,
  its World and its questions.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/08-edit-menu-dark.png">
  <img alt="The Edit menu on a page" src="docs/screenshots/08-edit-menu-light.png">
</picture>

Views composed for a source are remembered. Open the same source again and its pages and World are reused, with a
Recompose button if you want a fresh start.

## Data sources

| Source | What it is | Kind |
|---|---|---|
| A Claude Code swarm | Agents started by the SwarmFrame runner, or any Claude Code session reporting through hooks. Every tool call, with the option to pause, deny or stop. | Live |
| Any event stream | Post JSON events to `/ingest/events`. Only an `action` field is required. | Live |
| AI Village | Twenty-one AI agents with their own computers and a shared chat, over one week: messages, computer sessions, goals, memory checkpoints, pauses, searches, outreach requests and the reasoning behind each action. | Recorded |
| The German message board | Handles writing on a shared wiki, with groups that converge on the same pages, text that spreads between them, and moderators deleting pages in sweeps. | Recorded |
| Agent activity on the web | Transluce's catalog of 37,649 web-scan reports attributed to autonomous agents. A record of targets and methods, with no agent identities. | Recorded |

## Data

Datasets are not stored in this repository. They live in `data/`, which is ignored by git.

- **AI Village** is a gated Hugging Face dataset (`aidigestorg/ai-village`). Set `HF_TOKEN` to a token with access
  and run `swarmframe fetch ai_village --set village_dense`. This downloads about 95 MB. For the activity between
  messages (memory checkpoints, pauses, searches, outreach, reasoning) also run
  `python scripts/fetch_village_events.py 2026-06-28 2026-07-06`, which keeps about 11 MB from a 330 MB file.
- **The German message board** export comes from collusion.wiki and goes in `data/german_wiki/`.
- **Transluce** is a public zip from transluce.org that goes in `data/transluce/`.

Agent-written text (messages, reasoning, goals) is shown only as untrusted evidence. It is never treated as an
instruction to SwarmFrame's own agents.

## More

- [Guide](docs/GUIDE.md): a walk through the dashboard, screen by screen.
- [Technical reference](docs/REFERENCE.md): every part of the system, its settings and its files.
- Design notes: [the dashboard](docs/UI_PLAN.md), [the World](docs/WORLD_PLAN.md),
  [the analyst teams](docs/OVERSIGHT_ARCHITECTURES.md), [reading at scale](docs/STRATEGY.md).

Run the tests with `.venv/Scripts/python -m pytest tests -q`.
