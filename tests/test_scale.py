"""Scale layer, triage tree, Transluce source, skills and the agent-customizable dashboard."""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from swarmscope.dashboard.spec import SpecError
from swarmscope.engine import Engine

FAST = {"investigations.node_delay_s": 0, "agents.stub_delay_s": 0, "llm.mode": "stub"}


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ templates and cohorts
def test_template_miner_masks_variables():
    from swarmscope.scale.templates import TemplateMiner
    m = TemplateMiner()
    a = m.assign("a1", "rerunning step 4 of the parser with the smaller config")
    b = m.assign("a2", "rerunning step 17 of the parser with the smaller config")
    c = m.assign("a3", "merged the index changes, 12 files touched")
    assert a == b and a != c
    assert m.assign("a1", "anything") == a            # stable per artifact


def test_cohorts_partition_units_and_stay_bounded():
    from swarmscope.sources.swarm_scale import generate
    from swarmscope.scale.layer import ScaleLayer
    b = generate(n_agents=400, hours=12, seed=3)
    lay = ScaleLayer({"span_windows": 6}, identities=True)
    lay.add_texts([(a.id, t) for a, t in b.artifacts])
    by_win: dict[int, list] = {}
    t0 = b.events[0].ts
    for e in b.events:
        by_win.setdefault(int((e.ts - t0).total_seconds() // 1200), []).append(e)
    for i in sorted(by_win):
        lay.observe_window(i, by_win[i])
    members = [u for c in lay.cohorts.values() for u in c.members]
    assert len(members) == len(set(members))                 # a partition
    assert set(members) == {p.unit for p in lay.active_units()}
    assert 4 <= len(lay.cohorts) < len(members) / 3          # compression, not one cohort per agent
    pop = lay.population()
    assert pop["templates"] < pop["messages"] / 20           # thousands of messages, few templates
    assert pop["outliers"] < 0.1 * pop["units_active"]


# ------------------------------------------------------------------ triage
def test_triage_lanes_and_audit_floor():
    from swarmscope.scale.triage import Triage
    t = Triage({"reads_per_cycle": 10})
    t.configure(lanes={"triage": 1.0, "coverage": 0.0, "audit": 0.0})
    assert t.lanes["audit"] >= 0.1 - 1e-9                    # the random slice cannot be switched off
    t.configure(reads="auto")
    assert t.reads_auto


def test_triage_tree_on_planted_swarm():
    e = Engine("swarm_scale", "default", slice_override={"agents": 600, "hours": 14},
               overrides={**FAST, "agents.topology": "triage_tree"})
    run(e.run_to_end())
    org = e.agent_org
    assert org.cycle_index >= 5 and org.cycle_index < e.windows_processed      # cycles on cadence, not every window
    lanes = {i.lane for log in org.triage_log for i in log["items"]}
    assert lanes == {"triage", "coverage", "audit"}
    assert org.lookups and all(x["status"] for x in org.lookups)
    cov = org.coverage_log[-1]
    assert cov["cohorts"] > 0 and cov["random_audits_now"] >= 1 and "hit_rates" in cov
    assert any(n.role == "auditor" for n in org.active())
    # say-vs-do and the operator stop are planted; both should reach a triage pick
    gt = {g["id"]: set(g["units"]) for g in e.ground_truth}
    picked = {u for log in org.triage_log for i in log["items"] for u in i.units}
    assert picked & gt["gt_saydo"] and picked & gt["gt_spread"]


def test_sectors_appear_when_divisions_outgrow_one_reader():
    from swarmscope.agents.spec import load_topology
    t = load_topology("triage_tree")
    t.maintain["sector_span"] = 2
    t.divisions["cohorts_per_division"] = 2
    e = Engine("swarm_scale", "default", slice_override={"agents": 600, "hours": 8},
               overrides={**FAST, "agents.topology": "triage_tree"})
    e.agent_org.set_topology(t)
    run(e.run_to_end())
    org = e.agent_org
    assert org.sectors
    leads = [n for n in org.active() if n.role == "sector_lead"]
    assert leads and any(n.children for n in leads)
    from swarmscope.agents.runners import org_status
    st = org_status(org, org.nodes[org.root_id])
    assert st["hidden_agents"] > 0                           # the director reads sector leads, not every analyst


def test_director_input_is_bounded():
    from swarmscope.agents.runners import user_prompt
    from swarmscope.agents.runtime import RunContext
    e = Engine("swarm_scale", "default", slice_override={"agents": 1500, "hours": 10},
               overrides={**FAST, "agents.topology": "triage_tree"})
    run(e.run_to_end())
    org = e.agent_org
    root = org.nodes[org.root_id]
    ctx = RunContext(org, root, org.topology.roles[root.role], "cycle", e.tools("investigator"))
    ctx.x = org.current_x
    assert len(user_prompt(ctx)) < 60000


# ------------------------------------------------------------------ Transluce
def test_transluce_synthetic_identity_free():
    e = Engine("transluce", "default", path="synthetic", overrides=FAST)
    assert not e.profile.has("identities") and e.scale.cfg["unit"] == "object"
    assert "targets" in e.monitors
    run(e.run_to_end())
    obs = e.store.all("Observation")
    lib = next(g for g in e.ground_truth if g["id"] == "gt_burst")
    hits = [o for o in obs if o.kind == "burst" and o.scope == lib["scope"]
            and o.window_end >= datetime.fromisoformat(lib["ts"][:19])]
    assert hits, "the planted burst should be detected against the target's own baseline"
    nm = next(g for g in e.ground_truth if g["id"] == "gt_new_method")
    assert any(o.kind == "new_method" and o.scope == nm["scope"] for o in obs)
    assert all(ev.actor is None for ev in e.store.events(limit=50))
    # auto-designed dashboard: a targets page, no per-agent views
    pages = {p.id for p in e.dashboard.spec.pages}
    assert "targets" in pages
    assert "population" not in [r["id"] for r in e.dashboard.spec.room]


def test_transluce_real_catalog_structure():
    from swarmscope.ingest.packs import ROOT, load_pack
    if not list((ROOT / "data" / "transluce").glob("**/all-reports.csv")):
        pytest.skip("Transluce catalog not downloaded")
    b = load_pack("transluce").adapter().load(None)
    assert len(b.events) > 30000
    assert {e.attributes["family"] for e in b.events} <= {"source_request", "custom_program", "indirection", "unknown"}
    assert {e.attributes["confidence"] for e in b.events} <= {"significant", "suggestive", "ungraded"}
    assert all(e.actor is None for e in b.events[:500])


# ------------------------------------------------------------------ skills
def test_skills_are_real_claude_code_skills():
    from swarmscope.agents.skills import compose, list_skills
    ids = {s["id"]: s for s in list_skills()}
    assert {"swarm-oversight", "dashboard-designer"} <= set(ids)
    assert "director" in ids["swarm-oversight"]["references"]
    text = compose(["swarm-oversight"], ["director"])
    assert "Every number has its base" in text and "cycle protocol" in text


def test_topology_rejects_unknown_skill():
    from swarmscope.agents.spec import TopologyError, from_dict, load_topology
    d = load_topology("triage_tree").to_dict()
    d["roles"]["director"]["skills"] = ["no-such-skill"]
    with pytest.raises(TopologyError):
        from_dict(d, "bad")


# ------------------------------------------------------------------ dashboard
@pytest.fixture(scope="module")
def village():
    e = Engine("ai_village", "default", path="synthetic", overrides=FAST)
    run(e.run_to_end())
    return e


def test_query_language_is_safe(village):
    from swarmscope.dashboard import query as Q
    from swarmscope.dashboard.profile import text_attributes
    ta = text_attributes(village)
    assert "short_goal" in ta                                   # agent-written text is not usable in views
    with pytest.raises(Q.QueryError):
        Q.run(village, {"group_by": ["attr.short_goal"]}, ta)
    with pytest.raises(Q.QueryError):
        Q.run(village, {"group_by": ["id; DROP TABLE events"]}, ta)
    with pytest.raises(Q.QueryError):
        Q.run(village, {"from": "artifact_text"}, ta)
    r = Q.run(village, {"group_by": ["ts:hour", "family"], "time": {"all": True}}, ta)
    assert r["columns"] == ["ts:hour", "family", "count"] and r["rows"]
    r2 = Q.run(village, {"group_by": ["actor"], "time": {"all": True}, "top": 3}, ta)
    assert len(r2["rows"]) <= 3 and not r2["rows"][0][0].startswith("ag_")   # labels, not ids


def test_profile_has_no_agent_text(village):
    import json
    from swarmscope.dashboard.profile import stream_profile
    prof = json.dumps(stream_profile(village))
    texts = [t for (_, t) in [(a.id, village.store.artifact_text(a.id)) for a in village.store.artifacts()[:200]] if t]
    long = [t for t in texts if len(t) > 60]
    assert long and not any(t[:60] in prof for t in long)


def test_dashboard_ops_atomic_versioned_undoable(village):
    from swarmscope.dashboard.spec import SpecError
    d = village.dashboard
    v0, pages0 = d.spec.version, len(d.spec.pages)
    with pytest.raises(SpecError):
        d.apply_ops(village, [
            {"op": "add_page", "id": "ok_page", "title": "OK", "panels": []},
            {"op": "add_panel", "page": "ok_page", "panel": {"title": "bad", "view": {"primitive": "bar",
                                                                                    "query": {"group_by": ["nope"]}}}}])
    assert d.spec.version == v0 and len(d.spec.pages) == pages0       # nothing applied
    res = d.apply_ops(village, [{"op": "add_page", "id": "mine", "title": "Mine", "panels": [
        {"title": "Busiest rooms", "view": {"primitive": "bar", "query": {"where": {"family": "chat"},
                                                                           "group_by": ["object"], "time": {"all": True}}}}]}],
                      by="test", rationale="a page")
    assert res["version"] == v0 + 1 and any(p.id == "mine" for p in d.spec.pages)
    from swarmscope.dashboard.spec import panel_data
    assert panel_data(village, d.find_panel("mine", "busiest_rooms"))["rows"]
    d.undo()
    assert not any(p.id == "mine" for p in d.spec.pages)


def test_designer_tools_through_ops(village):
    from swarmscope.assistant.ops import OpsTools
    names = {s[0] for s in OpsTools.SPECS}
    assert {"stream_profile", "view_preview", "dashboard_edit", "dashboard_undo", "set_triage", "triage_plan"} <= names

    async def approve(*_):
        return True
    ops = OpsTools(lambda: village, approve, "test")
    pv = run(ops.call("view_preview", {"view": {"primitive": "timeseries", "query": {"group_by": ["ts:hour"]}}}))
    assert pv["ok"]
    bad = run(ops.call("dashboard_edit", {"ops": [{"op": "explode"}]}))
    assert not bad["ok"] and "unknown op" in bad["error"]


def test_auto_design_in_stub_mode(village):
    from swarmscope.dashboard.designer import run_designer
    res = run(run_designer(village, "anything"))
    assert res["backend"] == "stub" and village.dashboard.spec.pages


# ------------------------------------------------------------------ compose mode: built-in views, linked streams
def test_builtin_views_load_and_survive_composing():
    from swarmscope.dashboard.designer import run_designer
    e = Engine("transluce", "default", path="synthetic", overrides=FAST)
    pack_pages = [p.id for p in e.dashboard.spec.pages if p.by == "pack"]
    assert {"brief", "targets"} <= set(pack_pages)
    run(run_designer(e))
    assert set(pack_pages) <= {p.id for p in e.dashboard.spec.pages}          # composing never removes built-ins
    e.dashboard.apply_ops(e, [{"op": "remove_page", "page": "targets"}])
    e.dashboard.apply_ops(e, [{"op": "restore_builtin"}])
    assert any(p.id == "targets" and p.by == "pack" for p in e.dashboard.spec.pages)


def test_linked_stream_infers_capabilities_and_composes():
    from swarmscope.dashboard.designer import run_designer
    e = Engine("generic_stream", "default", overrides=FAST)
    assert e.control is None and e.stream is not None
    assert [p.id for p in e.dashboard.spec.pages] == ["brief"] and not e.dashboard.spec.pages[0].panels
    assert not e.profile.has("identities")
    n = e.stream.ingest([{"actor": f"a{i % 7}", "group": f"t{i % 2}", "action": "tool.write" if i % 3 else "chat.message",
                          "object": f"file{i % 5}" if i % 3 else "#room", "family": "files" if i % 3 else "chat",
                          "text": f"status line {i}" if not i % 3 else None, "attrs": {"model": "m1"}}
                         for i in range(90)] + [{"no_action": True}])
    assert n == 90
    e.stream.flush()
    res = run(run_designer(e))
    caps = {k for k, c in e.profile.capabilities.items() if c.present}
    assert {"identities", "resources", "artifacts", "communication", "tool_calls", "groups"} <= caps
    assert "coordination" in e.monitors and res["backend"] == "stub"
    brief = e.dashboard.spec.pages[0]
    assert brief.id == "brief" and 1 <= len(brief.panels) <= 2                 # composing fills the Brief's signature views
    act = [p for p in e.dashboard.spec.pages if p.nav != "brief"]
    assert 1 <= len(act) <= 3 and all(p.reason for p in act)                  # at most three pages, each with a reason


# ------------------------------------------------------------------ the Brief, customization, lenses
def test_brief_groups_ranks_and_recommends():
    e = Engine("swarm_scale", "default", slice_override={"agents": 600, "hours": 10}, overrides=FAST)
    run(e.run_to_end())
    b = e.snapshot()["brief"]
    assert b["status"] and b["items"] and set(b["counts"]) == {"ACT", "LOOK", "WATCH"}
    assert all(x["next"] and x["severity"] in ("ACT", "LOOK", "WATCH") for x in b["items"])
    groups = [x for x in b["items"] if x["group"]]
    assert groups and all(x["count"] >= 3 and len(x["members"]) == x["count"] for x in groups)
    raw = sum(b["raw_counts"].values())
    assert len(b["items"]) < raw                                               # duplicates collapsed
    sev = ["ACT", "LOOK", "WATCH"]
    unpinned = [sev.index(x["severity"]) for x in b["items"] if not x["pinned"]]
    assert unpinned == sorted(unpinned)                                        # most severe first
    assert "σ" not in " ".join(x["headline"] for x in b["items"])               # statistical shorthand rewritten
    assert {"active", "attention", "coverage"} <= set(b["glance"])
    from swarmscope.dashboard.brief import incident_detail
    d = incident_detail(e, groups[0]["id"])
    assert d and d["group_rows"]


def test_any_panel_anywhere_brief_settings_and_reset():
    e = Engine("transluce", "default", path="synthetic", overrides=FAST)
    st = e.dashboard
    st.apply_ops(e, [{"op": "add_panel", "page": "brief", "panel": {"id": "triage", "title": "Reading plan",
                                                                     "builtin": "triage"}}])
    assert any(x.builtin == "triage" for x in st.spec.pages[0].panels)         # machinery on the Brief, if wanted
    st.apply_ops(e, [{"op": "set_brief", "glance": ["attention", "events"], "attention_rows": 8,
                      "min_severity": "LOOK"}])
    assert st.spec.brief.glance == ["attention", "events"] and st.spec.brief.attention_rows == 8
    with pytest.raises(SpecError):
        st.apply_ops(e, [{"op": "remove_page", "page": "brief"}])
    st.apply_ops(e, [{"op": "update_page", "page": "targets", "nav": "top", "title": "Targets"}])
    assert next(p for p in st.spec.pages if p.id == "targets").nav == "top"
    st.apply_ops(e, [{"op": "reset_page", "page": "brief"}])
    assert not any(x.builtin == "triage" for x in st.spec.pages[0].panels) and st.spec.brief.glance[0] == "total"          # the catalog default
    st.apply_ops(e, [{"op": "set_machinery", "on": True}])
    mach = next(p for p in st.spec.pages if p.id == "machinery")
    assert {"triage", "coverage"} <= {x.builtin for x in mach.panels}
    with pytest.raises(SpecError):
        st.apply_ops(e, [{"op": "set_room", "layout": []}])                   # retired, with a pointer to the Brief


def test_lenses_save_switch_delete():
    from swarmscope.dashboard.spec import DASH_DIR, DashboardStore
    e = Engine("transluce", "default", path="synthetic", overrides=FAST)
    f = DASH_DIR / "_test_lenses.json"
    f.unlink(missing_ok=True)
    st = DashboardStore("transluce", f)
    st.replace(e.dashboard.spec.model_copy(deep=True), "pack", "defaults")
    st.save_lens("Incident review")
    st.apply_ops(e, [{"op": "remove_page", "page": "targets"}])
    assert st.lens == "Incident review" and not any(p.id == "targets" for p in st.spec.pages)
    st.switch_lens("Default")
    assert any(p.id == "targets" for p in st.spec.pages)                      # each lens keeps its own layout
    again = DashboardStore("transluce", f)                                     # and survives a restart
    assert again.lens_names() == ["Default", "Incident review"] and again.lens == "Default"
    again.delete_lens("Incident review")
    with pytest.raises(SpecError):
        again.delete_lens("Default")
    f.unlink(missing_ok=True)


def test_views_drop_empty_groups_and_the_filling_bucket():
    from swarmscope.dashboard import query as Q
    from swarmscope.dashboard.profile import text_attributes
    e = Engine("swarm_scale", "default", slice_override={"agents": 300, "hours": 8}, overrides=FAST)
    run(e.run_to_end())
    bars = Q.run(e, {"group_by": ["object"], "time": {"all": True}}, text_attributes(e))
    assert "none" not in [r[0] for r in bars["rows"]]
    ts = Q.run(e, {"group_by": ["ts:hour"], "time": {"all": True}}, text_attributes(e))
    assert "dropped_partial_bucket" in ts["meta"]
