"""Channel bridge end to end: real backend + the channel server over stdio, driven by a scripted MCP client
playing Claude Code's side of the protocol (initialize, tools, channel notifications, permission relay)."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
PORT = 8797
URL = f"http://127.0.0.1:{PORT}"
PY = str(ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))


@pytest.fixture(scope="module")
def backend():
    env = {**os.environ, "SWARMSCOPE_SESSION": json.dumps({"source": "ai_village", "path": "synthetic",
                                                            "overrides": {"agents.stub_delay_s": 0}})}
    p = subprocess.Popen([PY, "-m", "uvicorn", "swarmscope.api.app:app", "--port", str(PORT), "--log-level", "warning"],
                         cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        try:
            if httpx.get(f"{URL}/api/chat", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.5)
    yield
    p.terminate()


class Client:
    """Minimal stand-in for Claude Code's MCP client side."""
    def __init__(self):
        self.p = subprocess.Popen([PY, "-m", "swarmscope.channel"], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  env={**os.environ, "SWARMSCOPE_URL": URL})
        self.q: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.n = 0

    def _read(self):
        for line in iter(self.p.stdout.readline, b""):
            self.q.put(json.loads(line))

    def send(self, obj):
        self.p.stdin.write((json.dumps(obj) + "\n").encode())
        self.p.stdin.flush()

    def request(self, method, params=None):
        self.n += 1
        self.send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}})
        return self.wait(lambda m: m.get("id") == self.n)

    def wait(self, pred, timeout=20):
        end = time.time() + timeout
        skipped = []
        while time.time() < end:
            try:
                m = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            if pred(m):
                for s in skipped:
                    self.q.put(s)
                return m
            skipped.append(m)
        raise AssertionError("timed out waiting for message")

    def close(self):
        self.p.terminate()


def test_channel_bridge_end_to_end(backend):
    c = Client()
    try:
        init = c.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test"}})
        caps = init["result"]["capabilities"]
        assert caps["experimental"] == {"claude/channel": {}, "claude/channel/permission": {}} and "tools" in caps
        assert "reply" in init["result"]["instructions"]
        c.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = {t["name"] for t in c.request("tools/list")["result"]["tools"]}
        assert {"reply", "situation", "focus", "org_spawn", "control"} <= tools
        for _ in range(40):                                   # wait for the channel's websocket to attach
            if httpx.get(f"{URL}/api/chat").json()["channel"]["connected"]:
                break
            time.sleep(0.25)
        # viewer -> channel -> Claude Code notification
        sent = httpx.post(f"{URL}/api/chat", json={"text": "what changed?", "target": "channel"}).json()
        n = c.wait(lambda m: m.get("method") == "notifications/claude/channel")
        assert n["params"]["content"] == "what changed?" and n["params"]["meta"] == {"kind": "chat", "chat_id": sent["id"], "sender": "viewer"}
        # Claude Code calls an operator tool and replies
        sit = c.request("tools/call", {"name": "situation", "arguments": {}})
        assert "population_state" in sit["result"]["content"][0]["text"]
        c.request("tools/call", {"name": "reply", "arguments": {"chat_id": sent["id"], "text": "Two agents converged."}})
        time.sleep(0.5)
        msgs = httpx.get(f"{URL}/api/chat").json()["messages"]
        assert any(m["role"] == "assistant" and m["via"] == "channel" and "converged" in m["text"] for m in msgs)
        # permission relay: Claude Code -> dashboard card -> verdict back to Claude Code
        c.send({"jsonrpc": "2.0", "method": "notifications/claude/channel/permission_request",
                "params": {"request_id": "abcde", "tool_name": "Bash", "description": "list files", "input_preview": "{\"command\":\"ls\"}"}})
        card = None
        for _ in range(40):
            card = next((m for m in httpx.get(f"{URL}/api/chat").json()["messages"]
                         if m["role"] == "approval" and m["meta"].get("request_id") == "abcde"), None)
            if card:
                break
            time.sleep(0.25)
        assert card and card["status"] == "pending"
        httpx.post(f"{URL}/api/chat/approval", json={"id": card["id"], "approve": True})
        v = c.wait(lambda m: m.get("method") == "notifications/claude/channel/permission")
        assert v["params"] == {"request_id": "abcde", "behavior": "allow"}
        # ops endpoint refuses callers without the token
        assert httpx.post(f"{URL}/api/ops/situation", json={}).status_code == 403
    finally:
        c.close()


def test_stub_copilot_answers_and_acts(backend):
    r = httpx.post(f"{URL}/api/chat", json={"text": "status", "target": "copilot"})
    assert r.status_code == 200
    for _ in range(40):
        msgs = httpx.get(f"{URL}/api/chat").json()["messages"]
        if any(m["role"] == "assistant" and m["via"] == "copilot" for m in msgs):
            break
        time.sleep(0.25)
    assert any(m["role"] == "assistant" and m["via"] == "copilot" for m in msgs)
    httpx.post(f"{URL}/api/chat", json={"text": "ask Why did agents converge on plan.example.org?", "target": "copilot"})
    time.sleep(1.5)
    qs = httpx.get(f"{URL}/api/snapshot").json()["questions"]
    assert any("plan.example.org" in q["text"] for q in qs)
