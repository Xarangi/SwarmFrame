"""Grade a report against MessageBoardAuditBench (github.com/hamzah2304/messageboardauditbench) with Claude.

The benchmark grades with its own Inspect task and an API judge. This reproduces its grading code path outside the
harness so a SwarmFrame report can be scored with the local Claude Code login:

  * the committed v2 sheets (8 sheets, 38 points) and the holistic TL;DR sheet, filled in code with the human report
    (the answer key) and the model report; the sheets and the answer key are never printed
  * the benchmark's system prompt, JSON extraction, one retry, score clamping and rounding
  * per point max(2s - 1, 0); headline = 0.7 x mean over the 38 points + 0.3 x the TL;DR score
  * missing points are asked for again rather than dropped from the denominator

Scores from a judge other than the published one are not comparable to the benchmark's leaderboard.

    python scripts/mbab_grade.py data/bench/mbab report.md --model claude-sonnet-5-5 --effort low --out grades.json

<bench> needs rubrics/v2_*.md|json, rubrics/tldrh_1.md|json, benchmark/human_report.txt and scripts/extract_tldr.py
(see docs/GUIDE.md, "Analyze a dump"). Prints scores only.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import sys
from pathlib import Path

SYSTEM = "You are a careful grader. Follow the grading sheet exactly and output strict JSON only."
RETRY = ("\n\nIMPORTANT: return ONLY the JSON object itself — no prose before or after it, and no markdown code "
         "fences.")
W_COV, W_TLDR = 0.7, 0.3


def extract_json(text: str) -> dict | None:
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        i, j = t.find("{"), t.rfind("}")
        if i >= 0 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                return None
    return None


def parse_items(d: dict | None) -> dict[str, float]:
    out = {}
    for it in (d or {}).get("items") or []:
        try:
            s = float(it.get("score"))
        except (TypeError, ValueError):
            s = 0.0
        out[str(it.get("id"))] = round(min(1.0, max(0.0, s)), 1)
    return out


async def ask(prompt: str, model: str, effort: str) -> str:
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from swarmscope.llm.router import find_claude_cli
    opts = ClaudeAgentOptions(system_prompt=SYSTEM, model=model, effort=effort, max_turns=1, tools=[], allowed_tools=[],
                              setting_sources=[], cli_path=find_claude_cli())
    text, cost = "", 0.0
    async for msg in query(prompt=prompt, options=opts):
        if isinstance(msg, ResultMessage):
            text, cost = msg.result or "", float(msg.total_cost_usd or 0)
    ask.cost += cost
    return text
ask.cost = 0.0  # type: ignore[attr-defined]


async def grade_sheet(sheet: str, ids: list[str], human: str, report: str, model: str, effort: str) -> dict[str, float]:
    base = sheet.replace("{{HUMAN_REPORT}}", human).replace("{{MODEL_REPORT}}", report)
    got: dict[str, float] = {}
    prompt = base
    for attempt in range(3):
        d = extract_json(await ask(prompt, model, effort))
        got.update({k: v for k, v in parse_items(d).items() if k in ids})
        missing = [i for i in ids if i not in got]
        if not missing:
            break
        prompt = base + RETRY + (f"\nScore every point, including {', '.join(missing)}." if d else "")
    return got


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("bench")
    ap.add_argument("report")
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--out", default=None, help="write per-point scores here (no quotes, no reasons)")
    a = ap.parse_args()
    b = Path(a.bench)
    human = (b / "benchmark" / "human_report.txt").read_text(encoding="utf-8")
    report = Path(a.report).read_text(encoding="utf-8")
    spec = importlib.util.spec_from_file_location("extract_tldr", b / "scripts" / "extract_tldr.py")
    et = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(et)  # type: ignore[union-attr]
    tldr, how = et.extract(report)
    sheets = sorted((b / "rubrics").glob("v2_*.md"), key=lambda p: int(p.stem.split("_")[1]))
    jobs = []
    for s in sheets:
        meta = json.loads(s.with_suffix(".json").read_text(encoding="utf-8"))
        jobs.append(grade_sheet(s.read_text(encoding="utf-8"), list(meta["claim_ids"]), human, report, a.model, a.effort))
    tmeta = json.loads((b / "rubrics" / "tldrh_1.json").read_text(encoding="utf-8"))
    jobs.append(grade_sheet((b / "rubrics" / "tldrh_1.md").read_text(encoding="utf-8"), [tmeta.get("rubric_id", "TLDRH")],
                            human, tldr, a.model, a.effort))
    res = await asyncio.gather(*jobs)
    points: dict[str, float] = {}
    for r in res[:-1]:
        points.update(r)
    tl = next(iter(res[-1].values()), 0.0)
    n = len(points)
    raw = sum(points.values()) / max(1, n)
    strict = sum(max(2 * s - 1, 0) for s in points.values()) / max(1, n)
    out = {"report": a.report, "judge": f"{a.model} ({a.effort})", "points": n, "coverage_raw": round(raw, 3),
           "coverage_strict": round(strict, 3), "tldrh": tl, "headline": round(W_COV * strict + W_TLDR * tl, 3),
           "tldr_from": how, "tldr_words": len(tldr.split()), "words": len(re.sub(r"\[([^\]]*)\]\([^)]*\)", "", report).split()),
           "points_at_least_0_7": sum(1 for s in points.values() if s >= 0.7), "cost_usd": round(ask.cost, 3)}
    if a.out:
        Path(a.out).write_text(json.dumps({**out, "per_point": points}, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
