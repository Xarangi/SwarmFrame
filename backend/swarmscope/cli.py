"""swarmscope CLI.

  serve       run the API + dashboard        swarmscope serve --source ai_village --org default
  probe       structure-only schema report    swarmscope probe data/ai_village
  fetch       budgeted dataset subset         HF_TOKEN=... swarmscope fetch ai_village --set village_dense
  replay      headless replay with a summary  swarmscope replay --source ai_village --synthetic
  eval        compare organizations           swarmscope eval --orgs default baseline_deterministic
  scale-eval  planted swarm at scale          swarmscope scale-eval --agents 2000 --hours 36
  run-swarm   real Claude Code agents         swarmscope run-swarm runner/scenarios/tiny.yaml
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="swarmscope")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--source", default=None, help="start a session now; omit to open in compose mode")
    s.add_argument("--org", default="default")
    s.add_argument("--llm", choices=["stub", "cheap", "full"], default=None)
    s.add_argument("--synthetic", action="store_true")
    s.add_argument("--goal", default=None)
    s.add_argument("--simulate", type=int, default=0, help="live source: number of simulated agents")
    s.add_argument("--autoplay", action="store_true")

    p = sub.add_parser("probe")
    p.add_argument("path")
    p.add_argument("--show-values", action="store_true", help="print sample values (off by default)")

    f = sub.add_parser("fetch")
    f.add_argument("source")
    f.add_argument("--set", default=None)

    r = sub.add_parser("replay")
    r.add_argument("--source", default="ai_village")
    r.add_argument("--org", default="default")
    r.add_argument("--llm", choices=["stub", "cheap", "full"], default=None)
    r.add_argument("--synthetic", action="store_true")
    r.add_argument("--goal", default=None)
    r.add_argument("--windows", type=int, default=None)

    e = sub.add_parser("eval")
    e.add_argument("--orgs", nargs="+", default=["default", "baseline_deterministic", "baseline_uniform_local",
                                                 "baseline_single_summarizer"])

    se = sub.add_parser("scale-eval", help="does the organization find planted behaviours in a large swarm?")
    se.add_argument("--agents", type=int, default=2000)
    se.add_argument("--hours", type=float, default=36)
    se.add_argument("--topology", default="triage_tree")

    ch = sub.add_parser("channel-setup", help="write .mcp.json so Claude Code can load the SwarmFrame channel")
    ch.add_argument("--url", default="http://127.0.0.1:8765")

    sub.add_parser("channel", help="run the channel server (Claude Code spawns this)")

    w = sub.add_parser("run-swarm")
    w.add_argument("scenario")
    w.add_argument("--server", default="http://127.0.0.1:8765")

    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if a.cmd == "serve":
        import uvicorn
        session = {"source": a.source, "org": a.org, "autoplay": a.autoplay}
        if a.llm:
            session["overrides"] = {"llm.mode": a.llm}
        if a.synthetic:
            session["path"] = "synthetic"
        if a.goal:
            session["goal"] = a.goal
        if a.simulate:
            session["simulate"] = a.simulate
        os.environ["SWARMSCOPE_SESSION"] = json.dumps(session if a.source else {})
        print(f"SwarmFrame on http://{a.host}:{a.port}  "
              + (f"(source={a.source}, org={a.org}, llm={a.llm or 'org default'})" if a.source else "(compose mode)"))
        uvicorn.run("swarmscope.api.app:app", host=a.host, port=a.port, log_level="warning")

    elif a.cmd == "probe":
        from swarmscope.ingest.probe import probe
        print(json.dumps(probe(a.path, show_values=a.show_values), indent=2, default=str))

    elif a.cmd == "fetch":
        import yaml
        from swarmscope.ingest.packs import ROOT, load_pack
        from swarmscope.sources.hf_fetch import fetch_plan
        pack = load_pack(a.source)
        fcfg = pack.source.get("fetch") or {}
        dl = pack.source.get("download")
        if dl and not fcfg:                       # a public package: one file, unzipped in place
            import urllib.request
            import zipfile
            out = ROOT / pack.source.get("default_path", f"data/{a.source}")
            out.mkdir(parents=True, exist_ok=True)
            dest = out / dl["url"].rsplit("/", 1)[-1]
            print(f"Downloading {dl['url']} (~{dl.get('size_mb', '?')} MB) to {dest}")
            urllib.request.urlretrieve(dl["url"], dest)
            if dest.suffix == ".zip":
                zipfile.ZipFile(dest).extractall(out)
            print("done")
            return
        name = a.set or fcfg.get("default_set")
        plan = fcfg["sets"][name]["plan"]
        out = ROOT / pack.source.get("default_path", f"data/{a.source}")
        for row in fetch_plan(fcfg["repo"], plan, out, float(fcfg.get("budget_mb", 100))):
            print(f"{row['file']:34} {row['mode']:4} {row['downloaded_mb']:8.2f} MB  rows={row['rows']}")

    elif a.cmd == "replay":
        from swarmscope.engine import Engine

        async def go():
            ov = {"investigations.node_delay_s": 0}
            if a.llm:
                ov["llm.mode"] = a.llm
            eng = Engine(a.source, a.org, path="synthetic" if a.synthetic else None, overrides=ov,
                         slice_override={"goal": a.goal} if a.goal else None)
            await eng.run_to_end(a.windows)
            snap = eng.snapshot()
            print(f"{eng.profile.title}: {eng.store.count_events()} events, {eng.windows_processed} windows")
            for b in snap["briefing"]:
                print(f"  {b['ts'][5:16]}  {b['kind']:8} {b['text']}")
            print("Executive:", eng.exec_state.population_state)
            print("Spent: $", round(eng.router.spent_usd, 4), "| errors:", eng.router.errors[-3:])
        asyncio.run(go())

    elif a.cmd == "eval":
        from swarmscope.evals.harness import compare
        res = asyncio.run(compare(a.orgs))
        cols = ["org", "recall", "explained", "median_minutes_to_signal", "median_minutes_to_explanation",
                "exposure_correct", "false_incidents", "llm_calls", "coverage"]
        print(" | ".join(cols))
        for r in res["results"]:
            print(" | ".join(str(r.get(c, r.get("error", ""))) for c in cols))

    elif a.cmd == "scale-eval":
        from swarmscope.evals.scale_eval import evaluate_scale
        r = asyncio.run(evaluate_scale(a.agents, a.hours, topology=a.topology))
        inc = r.pop("incidents")
        print(json.dumps(r, default=str, indent=1))
        print(f"{'incident':14} {'units':>5} {'watcher':>8} {'triage':>7} {'surfaced':>9}  lane / by")
        for i in inc:
            f = lambda v: "-" if v is None else f"{v:.0f}m"  # noqa: E731
            print(f"{i['incident']:14} {i['units']:>5} {f(i['minutes_to_watcher']):>8} {f(i['minutes_to_triage']):>7} "
                  f"{f(i['minutes_to_surfaced']):>9}  {i['surfaced_lane'] or i['triage_lane'] or ''} / {i['surfaced_by'] or ''}")

    elif a.cmd == "channel-setup":
        from swarmscope.ingest.packs import ROOT
        cfg_path = ROOT / ".mcp.json"
        cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {"mcpServers": {}}
        cfg.setdefault("mcpServers", {})["swarmscope"] = {"command": sys.executable, "args": ["-m", "swarmscope.channel"],
                                                          "env": {"SWARMSCOPE_URL": a.url}}
        cfg_path.write_text(json.dumps(cfg, indent=2))
        print(f"Wrote {cfg_path}. Start SwarmFrame, then in {ROOT} run:")
        print("  claude --dangerously-load-development-channels server:swarmscope")

    elif a.cmd == "channel":
        from swarmscope.channel.server import main as channel_main
        channel_main()

    elif a.cmd == "run-swarm":
        from swarmscope.runner.run_swarm import run_swarm
        print(json.dumps(asyncio.run(run_swarm(a.scenario, a.server)), indent=2))


if __name__ == "__main__":
    main()
