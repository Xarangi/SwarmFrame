"""Any swarm event stream: link it, and SwarmFrame learns what it can tell us.

POST /ingest/events with a JSON list of events (or {"events": [...]}). Every field but `action` is optional:

  {"ts": "2026-10-03T14:05:00Z", "actor": "agent-17", "actor_label": "Kestrel", "group": "team-a",
   "action": "tool.write", "object": "repo/README.md", "family": "files", "text": "agent-written text",
   "attrs": {"model": "sonnet", "status": "ok"}}

Text is fingerprinted and stored behind the evidence boundary like every other source. Capabilities are not
declared up front: `infer_capabilities` reads what has arrived (are there actors? resources? text? chat? tool
calls?) and turns monitors and dashboard panels on accordingly. A demo feed replays a planted swarm into the stream in
real time, so the whole link-and-compose path can be tried without a swarm of your own.
"""
from __future__ import annotations

import asyncio
import hashlib
from collections import Counter
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from swarmscope.core.models import Capability, Entity, EvidenceEvent
from swarmscope.ingest.adapter import Batch, make_artifact, parse_ts
from swarmscope.ingest.packs import SourcePack

if TYPE_CHECKING:
    from swarmscope.engine import Engine

SELF_REPORT_ACTIONS = {"chat.message", "narration", "summary.generated", "memory.update"}


class GenericStreamAdapter:
    id = "generic_stream"

    def __init__(self, pack: SourcePack):
        self.pack = pack

    def capabilities(self):
        return self.pack.capabilities

    def load(self, path: str | None = None) -> Batch:
        return Batch()


def _hid(prefix: str, s: str) -> str:
    return f"{prefix}{hashlib.sha1(s.encode()).hexdigest()[:10]}"


class StreamIngest:
    """Buffered ingest for a generic live stream, flushed by the engine once per window."""

    def __init__(self, engine: "Engine"):
        self.engine = engine
        self._ents: dict[str, Entity] = {}
        self._arts: list = []
        self._evs: list[EvidenceEvent] = []
        self._known: set[str] = set()
        self.received = 0
        self.feed: asyncio.Task | None = None
        self.feed_info: dict[str, Any] | None = None

    def ingest(self, items: list[dict[str, Any]]) -> int:
        now = datetime.utcnow()
        n = 0
        for raw in items[:5000]:
            if not isinstance(raw, dict) or not raw.get("action"):
                continue
            ts = parse_ts(raw.get("ts")) if raw.get("ts") else now
            ts = (ts or now).replace(tzinfo=None)
            actor = raw.get("actor")
            actor = str(actor) if actor not in (None, "") else None
            obj = raw.get("object")
            obj = str(obj) if obj not in (None, "") else None
            fam = str(raw.get("family") or str(raw["action"]).split(".")[0])
            if actor and actor not in self._known:
                self._known.add(actor)
                self._ents[actor] = Entity(id=actor, type="agent", source="generic_stream",
                                           label=str(raw.get("actor_label") or actor)[:60],
                                           group=str(raw["group"])[:60] if raw.get("group") else None)
            if obj and obj not in self._known:
                self._known.add(obj)
                self._ents[obj] = Entity(id=obj, type="resource", source="generic_stream",
                                         label=str(raw.get("object_label") or obj)[:80], group=fam)
            art = None
            if raw.get("text"):
                aid = _hid("gs_art_", f"{self.received}|{actor}|{ts}")
                a, clean = make_artifact(aid, str(raw["text"])[:20000], ts, actor, "agent_text")
                self._arts.append((a, clean))
                art = a.id
            attrs = {k: v for k, v in (raw.get("attrs") or {}).items() if isinstance(v, (str, int, float, bool))}
            self.received += 1
            self._evs.append(EvidenceEvent(id=raw.get("id") or _hid("gs_", f"{self.received}|{ts}|{actor}|{raw['action']}"),
                                           ts=ts, source="generic_stream", actor=actor, action=str(raw["action"])[:80],
                                           object=obj, artifact=art, attributes={**attrs, "family": fam}))
            n += 1
        return n

    def flush(self) -> int:
        if not (self._ents or self._arts or self._evs):
            return 0
        st = self.engine.store
        ents, arts, evs = list(self._ents.values()), self._arts, self._evs
        self._ents, self._arts, self._evs = {}, [], []
        st.add_entities(ents)
        st.add_artifacts(arts)
        st.add_events(evs)
        self.engine.scale.add_texts([(a.id, t) for a, t in arts])
        return len(evs)

    # ------------------------------------------------------------ demo feed
    def start_demo(self, agents: int = 300, hours: float = 8, speed: float = 120.0) -> None:
        """Replay a planted swarm into the stream: simulated time runs `speed` times faster than real time."""
        if self.feed and not self.feed.done():
            return
        from swarmscope.sources.swarm_scale import generate
        b = generate(n_agents=agents, hours=hours, seed=11)
        texts = {a.id: t for a, t in b.artifacts}
        labels = {e.id: e for e in b.entities}
        t0 = b.events[0].ts
        self.feed_info = {"agents": agents, "hours": hours, "speed": speed, "events": len(b.events), "sent": 0}

        async def run():
            start = datetime.utcnow()
            i = 0
            evs = b.events
            while i < len(evs):
                elapsed = (datetime.utcnow() - start).total_seconds() * speed
                due = []
                while i < len(evs) and (evs[i].ts - t0).total_seconds() <= elapsed:
                    e = evs[i]
                    ent = labels.get(e.actor) if e.actor else None
                    due.append({"ts": (start + (e.ts - t0) / speed).isoformat(), "actor": e.actor,
                                "actor_label": ent.label if ent else None, "group": ent.group if ent else None,
                                "action": e.action, "object": e.object,
                                "object_label": labels[e.object].label if e.object in labels else None,
                                "family": e.attributes.get("family"),
                                "text": texts.get(e.artifact) if e.artifact else None,
                                "attrs": {k: v for k, v in e.attributes.items() if k not in ("family",)}})
                    i += 1
                if due:
                    self.ingest(due)
                    self.feed_info["sent"] = i
                await asyncio.sleep(0.5)
        self.feed = asyncio.create_task(run())

    def stop(self) -> None:
        if self.feed:
            self.feed.cancel()


def infer_capabilities(engine: "Engine") -> dict[str, bool]:
    """Read what has arrived and declare what the stream can tell us. Returns what changed."""
    st = engine.store
    n = st.count_events()
    if not n:
        return {}
    row = st.sql("SELECT count(actor) a, count(DISTINCT actor) da, count(object) o, count(artifact) t, "
                 "count(actor_group) g FROM events")[0]
    acts = Counter({r["action"]: r["n"] for r in st.sql("SELECT action, count(*) n FROM events GROUP BY action")})
    fams = {r["family"] for r in st.sql("SELECT DISTINCT family FROM events")}
    has = {
        "timestamps": True,
        "identities": row["a"] >= 0.5 * n and row["da"] >= 2,
        "resources": row["o"] >= 0.3 * n,
        "artifacts": row["t"] > 0,
        "self_reports": any(a in SELF_REPORT_ACTIONS for a in acts),
        "communication": "chat" in fams or any(a.startswith("chat.") for a in acts),
        "groups": row["g"] >= 0.5 * n,
        "tool_calls": any(a.startswith("tool.") for a in acts),
        "computer_actions": any(a.startswith(("tool.", "computer.", "session.")) for a in acts),
        "environment": any(a.startswith(("environment.", "control.")) for a in acts),
    }
    changed = {}
    caps = engine.profile.capabilities
    for k, v in has.items():
        old = caps.get(k)
        if old is None or old.present != v:
            caps[k] = Capability(present=v, quality="derived" if v else "absent",
                                 note="inferred from the events received" if v else "not seen in the stream yet")
            changed[k] = v
    if changed:
        if "identities" in changed:
            engine.scale.cfg["unit"] = "actor" if has["identities"] else "object"
            engine.scale.profiles.clear()
            engine.scale.cohorts.clear()
        engine._build_monitors()
    return changed
