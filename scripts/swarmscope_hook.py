#!/usr/bin/env python3
"""Forward a Claude Code hook payload (JSON on stdin) to SwarmFrame.

Add to .claude/settings.json of any project whose sessions you want to watch:

  {"hooks": {
     "SessionStart":     [{"hooks": [{"type": "command", "command": "python /path/to/swarmscope_hook.py"}]}],
     "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "python /path/to/swarmscope_hook.py"}]}],
     "PreToolUse":       [{"matcher": "*", "hooks": [{"type": "command", "command": "python /path/to/swarmscope_hook.py"}]}],
     "PostToolUse":      [{"matcher": "*", "hooks": [{"type": "command", "command": "python /path/to/swarmscope_hook.py"}]}],
     "Stop":             [{"hooks": [{"type": "command", "command": "python /path/to/swarmscope_hook.py"}]}]}}

Environment: SWARMSCOPE_URL (default http://127.0.0.1:8765), SWARMSCOPE_TEAM, SWARMSCOPE_LABEL.
Observation only: this never blocks the session. Use the runner for control.
"""
import json
import os
import sys
import urllib.request

def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    sid = str(payload.get("session_id", "unknown"))
    payload.setdefault("swarm_agent_id", f"cc:{sid[:12]}")
    payload.setdefault("swarm_team", os.environ.get("SWARMSCOPE_TEAM"))
    payload.setdefault("swarm_label", os.environ.get("SWARMSCOPE_LABEL") or f"session {sid[:6]}")
    url = os.environ.get("SWARMSCOPE_URL", "http://127.0.0.1:8765") + "/ingest/claude-code"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=2).read()
    except Exception:
        pass   # SwarmFrame being down must never break the session

if __name__ == "__main__":
    main()
