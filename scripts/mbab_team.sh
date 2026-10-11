#!/usr/bin/env bash
# Read MessageBoardAuditBench with one analyst team, let Claude write the report, then grade it (scores only).
#   scripts/mbab_team.sh <team> [investigators] [parallel]
# Writes data/bench/teams/r_<team>.md (the report), g_<team>.json (scores) and <team>.log (run summary).
set -u
team=${1:?team}; inv=${2:-4}; par=${3:-2}
cd "$(dirname "$0")/.." || exit 1
out=data/bench/teams
mkdir -p "$out"
export PYTHONUTF8=1 SWARMSCOPE_DB_MEMORY=${SWARMSCOPE_DB_MEMORY:-700MB}
.venv/Scripts/swarmframe.exe analyze data/bench/mbab/verbatim --source german_wiki --team "$team" \
  --write claude --model claude-sonnet-5-5 --effort low --words 2500-3000 \
  --investigators "$inv" --parallel "$par" --out "$out/r_$team.md" > "$out/$team.log" 2>&1 \
  || { echo "analyze failed"; tail -c 800 "$out/$team.log"; exit 1; }
.venv/Scripts/python -X utf8 scripts/mbab_grade.py data/bench/mbab "$out/r_$team.md" --model claude-sonnet-5-5 \
  --effort low --parallel 3 --out "$out/g_$team.json" 2>&1 | grep -v unrecognized_model | tail -16
