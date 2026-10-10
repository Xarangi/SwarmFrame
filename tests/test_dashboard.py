"""Customising views (docs/UI_PLAN.md): pages, panels, the Brief's settings, lenses, undo and persistence."""
from __future__ import annotations

import asyncio
import json

import pytest

from swarmscope.dashboard.spec import DashboardStore, SpecError
from swarmscope.engine import Engine

FAST = {"investigations.node_delay_s": 0, "agents.stub_delay_s": 0, "llm.mode": "stub"}
BAR = {"id": "by_family", "title": "Events by workstream", "span": 6,
       "view": {"primitive": "bar", "query": {"group_by": ["family"], "metric": "count"}}}
NOTE = {"id": "note", "title": "A note", "span": 4, "view": {"primitive": "note", "options": {"text": "hello"}}}


@pytest.fixture(scope="module")
def eng():
    e = Engine("swarm_scale", "default", slice_override={"agents": 120, "hours": 4}, overrides=FAST)

    async def go():
        for _ in range(6):
            w = e.clock.next_window()
            if w is None:
                break
            await e.process(w)
    asyncio.run(go())
    return e


def fresh(eng: Engine) -> DashboardStore:
    st = DashboardStore(eng.profile.source, False)
    st.replace(eng.dashboard.spec.model_copy(deep=True), "test", "copy of the composed dashboard")
    st.history = []
    return st


def page(st: DashboardStore, pid: str):
    return next(p for p in st.spec.pages if p.id == pid)


def test_pages_add_rename_move_nav_remove(eng):
    st = fresh(eng)
    st.apply_ops(eng, [{"op": "add_page", "id": "mine", "title": "Mine"}])
    st.apply_ops(eng, [{"op": "update_page", "page": "mine", "title": "My page", "description": "d", "nav": "top"}])
    p = page(st, "mine")
    assert p.title == "My page" and p.nav == "top"
    st.apply_ops(eng, [{"op": "move_page", "page": "mine", "to": 0}])
    assert st.spec.pages[0].id == "mine"
    for bad, why in [({"op": "add_page", "id": "mine", "title": "x"}, "exists"),
                     ({"op": "add_page", "id": "Bad Id", "title": "x"}, "lowercase"),
                     ({"op": "remove_page", "page": "brief"}, "cannot be removed"),
                     ({"op": "update_page", "page": "brief", "nav": "top"}, "home page"),
                     ({"op": "move_page", "page": "nope", "to": 1}, "no page")]:
        with pytest.raises(SpecError, match=why):
            st.apply_ops(eng, [bad])
    st.apply_ops(eng, [{"op": "remove_page", "page": "mine"}])
    assert not any(p.id == "mine" for p in st.spec.pages)


def test_panels_add_update_move_remove_and_validate(eng):
    st = fresh(eng)
    st.apply_ops(eng, [{"op": "add_page", "id": "p", "title": "P"},
                       {"op": "add_panel", "page": "p", "panel": BAR},
                       {"op": "add_panel", "page": "p", "panel": NOTE},
                       {"op": "add_panel", "page": "p", "panel": {"id": "w", "title": "World", "builtin": "world", "span": 12}}])
    assert [x.id for x in page(st, "p").panels] == ["by_family", "note", "w"]
    st.apply_ops(eng, [{"op": "update_panel", "page": "p", "panel_id": "by_family", "changes": {"span": 99, "title": "T"}}])
    assert page(st, "p").panels[0].span == 12 and page(st, "p").panels[0].title == "T"      # spans are clamped
    st.apply_ops(eng, [{"op": "move_panel", "page": "p", "panel_id": "w", "to": 0}])
    assert page(st, "p").panels[0].id == "w"
    st.apply_ops(eng, [{"op": "remove_panel", "page": "p", "panel_id": "note"}])
    assert [x.id for x in page(st, "p").panels] == ["w", "by_family"]
    for bad, why in [({"op": "remove_panel", "page": "p", "panel_id": "gone"}, "no panel"),
                     ({"op": "move_panel", "page": "p", "panel_id": "gone", "to": 0}, "no panel"),
                     ({"op": "add_panel", "page": "p", "panel": {**BAR}}, "exists"),
                     ({"op": "add_panel", "page": "p", "panel": {"id": "x", "title": "x", "builtin": "nope"}}, "unknown built-in"),
                     ({"op": "add_panel", "page": "p", "panel": {"id": "n", "title": "n", "view": {"primitive": "note"}}}, "needs options.text"),
                     ({"op": "add_panel", "page": "p", "panel": {"id": "t", "title": "t", "view": {"primitive": "timeseries", "query": {"group_by": ["family"]}}}}, "ts:")]:
        with pytest.raises(SpecError, match=why):
            st.apply_ops(eng, [bad])


def test_ops_are_atomic_and_undoable(eng):
    st = fresh(eng)
    v0, pages0 = st.spec.version, [p.id for p in st.spec.pages]
    with pytest.raises(SpecError):
        st.apply_ops(eng, [{"op": "add_page", "id": "a", "title": "A"}, {"op": "remove_page", "page": "nope"}])
    assert [p.id for p in st.spec.pages] == pages0 and st.spec.version == v0          # nothing half-applied
    st.apply_ops(eng, [{"op": "add_page", "id": "a", "title": "A"}])
    st.apply_ops(eng, [{"op": "add_panel", "page": "a", "panel": NOTE}])
    st.undo()
    assert not page(st, "a").panels
    st.undo()
    assert [p.id for p in st.spec.pages] == pages0
    with pytest.raises(SpecError, match="nothing to undo"):
        st.undo()


def test_brief_settings(eng):
    st = fresh(eng)
    st.apply_ops(eng, [{"op": "set_brief", "glance": ["events", "active", "nope"], "attention_rows": 99,
                        "min_severity": "LOOK", "show_changes": False, "world": False, "snooze": "f1", "pin": "f2"}])
    b = st.spec.brief
    assert b.glance == ["events", "active"] and b.attention_rows == 12 and b.min_severity == "LOOK"
    assert not b.show_changes and not b.world and b.snoozed == ["f1"] and b.pinned == ["f2"]
    st.apply_ops(eng, [{"op": "set_brief", "unsnooze": "f1", "world": True}])
    assert not st.spec.brief.snoozed and st.spec.brief.world
    for bad, why in [({"op": "set_brief", "glance": ["nope"]}, "glance needs"),
                     ({"op": "set_brief", "min_severity": "LOUD"}, "ACT, LOOK or WATCH")]:
        with pytest.raises(SpecError, match=why):
            st.apply_ops(eng, [bad])
    st.apply_ops(eng, [{"op": "add_panel", "page": "brief", "panel": NOTE}, {"op": "reset_page", "page": "brief"}])
    assert st.spec.brief.attention_rows == 5 and not any(x.id == "note" for x in page(st, "brief").panels)


def test_machinery_terminology_title_restore(eng):
    st = fresh(eng)
    st.apply_ops(eng, [{"op": "set_machinery", "on": True}])
    assert st.spec.machinery and page(st, "machinery").panels
    st.apply_ops(eng, [{"op": "set_machinery", "on": False}])
    assert not any(p.id == "machinery" for p in st.spec.pages)
    st.apply_ops(eng, [{"op": "set_terminology", "terms": {"agent": "worker"}}, {"op": "set_title", "title": "Ops"}])
    assert st.spec.terminology == {"agent": "worker"} and st.spec.title == "Ops"
    removable = [p.id for p in st.spec.pages if p.by == "pack" and p.id != "brief"]
    if removable:
        st.apply_ops(eng, [{"op": "remove_page", "page": removable[0]}, {"op": "restore_builtin"}])
        assert any(p.id == removable[0] for p in st.spec.pages)
    with pytest.raises(SpecError, match="Brief"):
        st.apply_ops(eng, [{"op": "set_room"}])


def test_lenses_are_separate_layouts_with_their_own_undo(eng):
    st = fresh(eng)
    st.save_lens("Incident review")
    assert st.lens == "Incident review" and st.lens_names() == ["Default", "Incident review"]
    st.apply_ops(eng, [{"op": "add_page", "id": "ir", "title": "IR"}])
    st.switch_lens("Default")
    assert not any(p.id == "ir" for p in st.spec.pages)
    st.switch_lens("Incident review")
    assert any(p.id == "ir" for p in st.spec.pages)
    st.undo()                                                        # undo stays within the lens
    assert not any(p.id == "ir" for p in st.spec.pages)
    with pytest.raises(SpecError):
        st.save_lens("Default")
    with pytest.raises(SpecError):
        st.rename_lens("Incident review", "Default")
    st.rename_lens("Incident review", "Review")
    assert st.lens == "Review"
    st.delete_lens("Review")
    assert st.lens == "Default" and st.lens_names() == ["Default"]
    with pytest.raises(SpecError, match="last lens"):
        st.delete_lens("Default")


def test_layouts_survive_a_restart(eng):
    import tempfile
    from pathlib import Path
    path = Path(tempfile.mkdtemp(prefix="ss-dash-")) / "dash.json"
    st = DashboardStore(eng.profile.source, path)
    st.replace(eng.dashboard.spec.model_copy(deep=True), "test", "seed")
    st.apply_ops(eng, [{"op": "add_page", "id": "kept", "title": "Kept"}])
    st.save_lens("Second")
    st.apply_ops(eng, [{"op": "set_brief", "attention_rows": 3}])
    again = DashboardStore(eng.profile.source, path)
    assert again.lens == "Second" and again.spec.brief.attention_rows == 3
    assert any(p.id == "kept" for p in again.spec.pages) and again.history
    again.switch_lens("Default")
    assert again.spec.brief.attention_rows == 5                       # the other lens kept its own Brief
    assert json.loads(path.read_text())["current"] == "Default"


def test_every_panel_on_the_composed_dashboard_renders(eng):
    from swarmscope.dashboard.spec import panel_data
    for p in eng.dashboard.spec.pages:
        for x in p.panels:
            if x.kind == "view":
                d = panel_data(eng, x)
                assert "error" not in d or not d["error"], (p.id, x.id, d.get("error"))


def test_custom_words_reach_the_brief(eng):
    from swarmscope.dashboard.brief import brief_digest, swap_words
    assert swap_words("An agent and 3 agents on a resource", {"agent": "bot", "resource": "item"}) == \
        "A bot and 3 bots on an item"
    st0 = eng.dashboard.spec.terminology
    try:
        eng.dashboard.spec.terminology = {"agent": "bot"}
        d = brief_digest(eng)
        assert d["terms"]["agent"] == "bot" and "bot" in d["glance"]["active"]["label"]
        assert "agent" not in d["status"].lower().replace("agentic", "")
    finally:
        eng.dashboard.spec.terminology = st0


def test_the_library_of_views_feed_network_two_sided_and_lanes(eng):
    """The designer composes from a fixed library; each new primitive is checked against the data, says what it
    needs, and carries the ids a click opens."""
    from swarmscope.dashboard.spec import panel_data
    st = fresh(eng)
    allt = {"all": True}
    panels = [
        {"id": "latest", "title": "Latest", "view": {"primitive": "feed", "query": {"time": allt, "top": 10}}},
        {"id": "net", "title": "Who works with whom", "view": {"primitive": "graph", "query": {"group_by": ["actor", "object"], "time": allt}}},
        {"id": "two", "title": "Agents and places", "view": {"primitive": "bipartite", "query": {"group_by": ["actor", "object"], "time": allt}}},
        {"id": "lanes", "title": "Lanes", "view": {"primitive": "swimlane", "query": {"group_by": ["actor", "ts:hour"], "time": allt}}},
    ]
    st.apply_ops(eng, [{"op": "add_page", "id": "library", "title": "Library", "panels": panels}])
    pg = page(st, "library")
    by = {p.id: p for p in pg.panels}
    assert by["latest"].view.query["list"] is True
    assert by["net"].view.requires == ["identities", "resources"] and by["lanes"].view.requires == ["identities", "timestamps"]
    feed = panel_data(eng, by["latest"])
    assert feed["columns"][:2] == ["time", "actor"] and len(feed["meta"]["event_ids"]) == len(feed["rows"]) > 0
    assert all(eid.startswith(("ev", "ss")) or eid for eid in feed["meta"]["event_ids"])
    net = panel_data(eng, by["net"])
    assert net["meta"]["ids"] and net["meta"]["ids"][0][0]          # the entity id behind each label
    with pytest.raises(SpecError, match="two group_by dimensions"):
        st.apply_ops(eng, [{"op": "add_panel", "page": "library", "panel": {"id": "bad", "title": "x", "view": {"primitive": "graph", "query": {"group_by": ["actor"]}}}}])
    with pytest.raises(SpecError, match="swimlane needs"):
        st.apply_ops(eng, [{"op": "add_panel", "page": "library", "panel": {"id": "bad", "title": "x", "view": {"primitive": "swimlane", "query": {"group_by": ["ts:hour", "actor"]}}}}])
