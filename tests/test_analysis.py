"""Post-analysis: a dump of logs in, a report with sources out; and the checked theme the designer works within."""
import asyncio
import gzip
import json

import pytest

from swarmscope.analysis.dump import detect, guess
from swarmscope.dashboard import theme as T


def _dump(tmp_path, n_agents=24, hours=10):
    """A planted swarm written out as two files in everyday shapes: a gzipped JSON-lines log and a CSV."""
    from swarmscope.sources.swarm_scale import generate
    b = generate(n_agents=n_agents, hours=hours, seed=5)
    ents = {e.id: e for e in b.entities}
    texts = {a.id: t for a, t in b.artifacts}
    d = tmp_path / "dump"
    d.mkdir()
    with gzip.open(d / "activity.jsonl.gz", "wt", encoding="utf-8") as f:
        for i, e in enumerate(b.events):
            f.write(json.dumps({"event_id": f"r{i}", "created_at": e.ts.isoformat(), "agent_name": ents[e.actor].label if e.actor in ents else e.actor,
                                "team": ents[e.actor].group if e.actor in ents else None, "event_type": e.action,
                                "target": ents[e.object].label if e.object in ents else e.object,
                                "message": texts.get(e.artifact, "") if e.artifact else ""}) + "\n")
    (d / "notes.csv").write_text("name,colour\nalpha,red\nbeta,blue\n", encoding="utf-8")
    return d, len(b.events)


def test_detect_guesses_the_roles(tmp_path):
    d, n = _dump(tmp_path)
    info = detect(str(d))
    f = next(x for x in info["files"] if x["file"].startswith("activity"))
    assert f["rows"] == n and f["usable"]
    m = f["mapping"]
    assert (m["ts"], m["actor"], m["action"], m["object"], m["group"], m["id"]) == \
        ("created_at", "agent_name", "event_type", "target", "team", "event_id")
    assert m["text"] == "message"
    notes = next(x for x in info["files"] if x["file"] == "notes.csv")
    assert not notes["usable"]                          # no time field: listed, not used as events
    assert info["known"] is None and info["usable"]


def test_guess_on_odd_names():
    rows = [{"when": f"2026-01-0{i % 9 + 1}T10:00:00", "who": f"bot{i % 4}", "verb": "post", "where": f"room{i % 3}"} for i in range(30)]
    m = guess(rows)
    assert m["ts"] == "when"                            # found by its values, not its name


def test_analysis_job_reads_the_whole_dump_and_writes_a_report(tmp_path, monkeypatch):
    from swarmscope.analysis import jobs
    monkeypatch.setattr(jobs, "_save", lambda job: None)
    d, n = _dump(tmp_path)

    async def go():
        return await jobs.run_blocking(str(d), {"title": "Test dump"})
    job = asyncio.run(go())
    assert job.status == "done", job.error + job.message
    rep = job.report
    assert rep["totals"]["records"] == n
    assert rep["totals"]["actors"] >= 20
    assert rep["timeline"] and rep["tldr"]
    assert job.engine.profile.has("identities") and job.engine.profile.has("artifacts")
    md = job.markdown
    assert md.startswith("# Test dump") and "## TL;DR" in md and "## Timeline" in md and "## Analysis" in md
    assert "`ev:" in md                                  # claims point at record ids
    assert job.engine.meta["files_skipped"] == ["notes.csv"]


def test_theme_checks_and_undo():
    st = T.ThemeStore(False)
    r = st.apply({"preset": "paper", "accent": "teal", "density": "compact"})
    assert r["resolved"]["attrs"]["surface"] == "flat" and r["resolved"]["vars"]["fs"] == "13px"
    assert r["resolved"]["modes"]["dark"]["accent"] != r["resolved"]["modes"]["light"]["accent"]   # tuned per mode
    with pytest.raises(T.ThemeError, match="hard to read"):
        st.apply({"colors": {"light": {"ink": "#dddddd"}}})
    with pytest.raises(T.ThemeError, match="not an available typeface"):
        st.apply({"fonts": {"ui": "Comic Sans MS"}})
    with pytest.raises(T.ThemeError, match="cannot be set"):
        st.apply({"colors": {"light": {"sev_act": "#00ff00"}}})   # meaning colours are fixed
    v = st.spec.version
    st.undo()
    assert st.spec.preset == "observatory" and st.spec.version == v + 1


def test_free_designer_reads_plain_words(monkeypatch):
    monkeypatch.setattr(T, "_STORE", T.ThemeStore(False))
    from swarmscope.dashboard.designer import free_design
    res = free_design(None, "make it dark and compact with a teal accent, a light sidebar and no animation")
    assert res["applied"] == ["look"]
    s = T.store().spec
    assert (s.mode, s.density, s.accent, s.nav, s.motion) == ("dark", "compact", "teal", "light", "none")
    assert "dark" in res["summary"]
    res = free_design(None, "something it cannot understand")
    assert not res["applied"] and "did not recognise" in res["summary"]


def test_every_preset_is_readable():
    for k in T.PRESETS:
        assert T.check(T.ThemeSpec(preset=k)) == [], k
