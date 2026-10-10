"""Designers: who composes the dashboard around a stream.

auto_design      free and deterministic: reads the stream profile and proposes a small starting dashboard (the
                 Brief's signature views and at most three Activity pages, each with a reason)
DashboardDesigner a Claude Agent SDK session with the dashboard tools and the dashboard-designer skill: it reads the
                 profile, previews candidate views against live data, and applies ops. Every op is validated and
                 versioned, so the human can undo any change.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Callable

from swarmscope.dashboard.profile import stream_profile
from swarmscope.dashboard.spec import BUILTINS, DashboardSpec, PageSpec, PanelSpec, SpecError, \
    _check_panel, catalog, panel_data

if TYPE_CHECKING:
    from swarmscope.engine import Engine

BUILTIN_REQUIRES = {"population": ["identities", "resources"], "timeline": ["timestamps"], "say_do": ["self_reports"],
                    "lineage": ["artifacts", "identities"], "swimlane": ["identities", "timestamps"],
                    "environment": ["environment"], "control": ["control"], "templates": ["artifacts"]}


def supported(engine: "Engine", builtin: str) -> bool:
    return all(engine.profile.has(c) for c in BUILTIN_REQUIRES.get(builtin, []))


def _v(pid: str, title: str, prim: str, q: dict[str, Any], span: int = 6, blurb: str = "", **opt: Any) -> dict[str, Any]:
    return {"id": pid, "title": title, "blurb": blurb, "span": span, "kind": "view",
            "view": {"primitive": prim, "query": q, "options": opt}}


def _b(bid: str, span: int, title: str | None = None) -> dict[str, Any]:
    return {"id": bid, "title": title or BUILTINS[bid].split(":")[0], "span": span, "kind": "builtin", "builtin": bid}


def auto_design(engine: "Engine", focus: str = "") -> tuple[DashboardSpec, str]:
    """A small starting dashboard: the Brief's 1-2 signature views and at most three Activity pages, each with the
    reason it was proposed. The machinery (triage, cohorts, coverage, the analyst team) is not composed; it lives
    under the hood and anyone can add it to any page."""
    prof = stream_profile(engine)
    caps = {k for k, c in prof["capabilities"].items() if c["present"]}
    noun, rnoun = prof["source"]["entity_noun"], prof["source"]["resource_noun"]
    bucket = prof["time"]["suggested_bucket"]
    allt = {"all": True}
    ident, res = "identities" in caps, "resources" in caps
    groups = bool(prof["fields"].get("group", {}).get("distinct"))
    f = (focus or "").lower()
    want = lambda *ws: any(w in f for w in ws)  # noqa: E731

    # ---------------------------------------------------------------- Brief: 1-2 signature views
    cand: list[tuple[float, dict[str, Any], str]] = []
    if "timestamps" in caps:
        cand.append((2.0, _v("sig_work", "Activity by workstream", "timeseries",
                             {"group_by": [bucket, "family"], "time": {"last_hours": 24}}, 7), "activity over time"))
    if ident and res:
        cand.append((2.2 + 2 * want("file", "resource", "shared", "converge", "crowd"),
                     _v("sig_crowd", f"{rnoun.title()}s drawing the most {noun}s", "bar",
                        {"metric": "distinct:actor", "group_by": ["object"], "time": {"last_hours": 6}}, 5),
                     f"shared {rnoun}s are where coordination shows first"))
    if not ident and res:
        cand.append((2.4 + 2 * want("target", "method"), _v("sig_targets", f"Most active {rnoun}s this week", "bar",
                                                           {"group_by": ["object"], "time": {"last_hours": 168}}, 5),
                     f"no identities, so {rnoun}s carry the story"))
    if groups:
        cand.append((1.6 + 2 * want("team", "group"), _v("sig_groups", "Busiest teams", "bar",
                                                        {"group_by": ["group"], "time": {"last_hours": 6}}, 5),
                     "the stream has teams"))
    conf = prof["attributes"].get("confidence", {})
    if conf.get("usable_in_views"):
        cand.append((1.8 + 2 * want("grade", "confidence", "significant"),
                     _v("sig_grades", "Evidence grade over time", "timeseries",
                        {"group_by": [bucket, "attr.confidence"], "time": allt}, 7), "the source grades its own evidence"))
    cand.sort(key=lambda x: -x[0])
    sig = cand[:2]
    if len(sig) == 2 and sig[0][1]["view"]["primitive"] == sig[1][1]["view"]["primitive"] == "bar":
        sig = [sig[0]] + [c for c in cand[2:] if c[1]["view"]["primitive"] != "bar"][:1]
    if len(sig) == 2:                                        # one wide, one narrow
        w = [7, 5] if sig[0][1]["view"]["primitive"] == "timeseries" else [5, 7]
        sig[0][1]["span"], sig[1][1]["span"] = w
    elif sig:
        sig[0][1]["span"] = 12

    # ---------------------------------------------------------------- Activity pages (at most three)
    pages: list[dict[str, Any]] = []
    act = []
    if "timestamps" in caps:
        act.append(_b("timeline", 12, "Activity by workstream"))
    if ident and res:
        act.append(_b("population", 7, f"Who works on which {rnoun}s"))
    if ident:
        act.append(_v("top_act", f"Busiest {noun}s", "bar", {"group_by": ["actor"], "time": {"last_hours": 24}}, 5))
    if res:
        act.append(_v("top_res", f"Busiest {rnoun}s", "bar", {"group_by": ["object"], "time": {"last_hours": 24}}, 6))
    if "self_reports" in caps:
        act.append(_b("say_do", 6, "What they said vs what they did"))
    if "artifacts" in caps and ident:
        act.append(_b("lineage", 6, "Content reuse"))
    if act and ident:
        pages.append({"id": "activity", "title": f"What the {noun}s are doing", "icon": "layers", "panels": act,
                      "description": f"Workstreams over time, the busiest {noun}s and {rnoun}s, and who works where.",
                      "reason": f"the stream names its {noun}s and {rnoun}s"})
    if not ident and res:
        tp = [_v("heat", f"{rnoun.title()}s by method", "heatmap", {"group_by": ["object", "family"], "time": allt,
                                                                    "top": 20}, 7),
              _v("over_time", "Methods over time", "timeseries", {"group_by": [bucket, "family"], "time": allt}, 5),
              _v("tgt_time", f"{rnoun.title()}s over time", "heatmap", {"group_by": ["object", bucket], "time": allt,
                                                                       "top": 14}, 7),
              _v("bursts", "Bursts and first-time methods", "table",
                 {"from": "observations", "where": {"kind": ["burst", "new_method"]}, "group_by": ["scope", "kind"],
                  "top": 15}, 5)]
        pages.append({"id": "targets", "title": f"{rnoun.title()}s & methods", "icon": "map", "panels": tp,
                      "description": f"Which {rnoun}s, which methods, when, and what spiked.",
                      "reason": f"no persistent {noun} identities, so {rnoun}s and methods describe the population"})
    if groups and len(pages) < 3:
        gn = getattr(engine.profile, "group_noun", "group") or "group"
        gns = gn + ("es" if gn.endswith("s") else "s") if not gn.endswith("y") else gn[:-1] + "ies"
        pages.append({"id": "teams", "title": gns[0].upper() + gns[1:], "icon": "layers",
                      "description": f"Which {gns} are busy, what they work on, and how many of their members are active.",
                      "reason": f"the stream groups its {noun}s into {gns}",
                      "panels": [_v("team_work", f"{gns[0].upper() + gns[1:]} by workstream", "heatmap",
                                    {"group_by": ["group", "family"], "time": allt, "top": 20}, 7),
                                 _v("team_size", f"Active members per {gn}", "bar",
                                    {"metric": "distinct:actor", "group_by": ["group"], "time": {"last_hours": 24}}, 5)]})
    if ("communication" in caps or "chat" in [x[0] for x in prof["fields"]["family"]["top"]]) and len(pages) < 3:
        pages.append({"id": "conversation", "title": "Conversation", "icon": "chat",
                      "description": "Who talks where, and how much.", "reason": "the stream carries chat",
                      "panels": [_v("rooms", "Busiest rooms", "bar", {"where": {"family": "chat"}, "group_by": ["object"],
                                                                      "time": allt}, 5),
                                 _v("talk_time", "Messages over time", "timeseries",
                                    {"where": {"family": "chat"}, "group_by": [bucket, "object"], "time": allt,
                                     "top": 6}, 7)]})
    attrs = [k for k, a in prof["attributes"].items() if a.get("usable_in_views") and a.get("note") == "categorical"
             and k not in ("family", "confidence") and 2 <= (a.get("distinct_in_sample") or 0) <= 40]
    if attrs and len(pages) < 3:
        pages.append({"id": "breakdowns", "title": "Breakdowns", "icon": "chart",
                      "description": "The stream's categorical fields, as found by the profile.",
                      "reason": f"{len(attrs)} categorical field{'s' if len(attrs) != 1 else ''} worth splitting by",
                      "panels": [_v(f"attr_{k}"[:40], k.replace("_", " ").title(), "bar",
                                    {"group_by": [f"attr.{k}"], "time": allt}, 6) for k in attrs[:4]]})

    spec = DashboardSpec(source=engine.profile.source, title=prof["source"]["title"],
                         terminology={"agent": noun, "resource": rnoun})

    def checked(xs: list[dict[str, Any]]) -> list[PanelSpec]:
        out = []
        for x in xs:
            try:
                ps = _check_panel(engine, x)
                if ps.kind == "builtin" and not supported(engine, ps.builtin or ""):
                    continue
                out.append(ps)
            except SpecError:
                continue
        return out
    spec.pages.append(PageSpec(id="brief", title="Brief", nav="brief", by="auto", panels=checked([c[1] for c in sig]),
                               reason="; ".join(c[2] for c in sig)))
    if "control" in caps:
        spec.brief.glance = ["active", "attention", "approvals", "investigating"]
    elif not ident:
        spec.brief.glance = ["active", "attention", "investigating", "events"]
    for p in pages[:3]:
        panels = checked(p["panels"])
        if panels:
            spec.pages.append(PageSpec(id=p["id"], title=p["title"], description=p["description"], icon=p["icon"],
                                       panels=panels, by="auto", nav="activity", reason=p["reason"]))
    why = (f"A Brief with {len(sig)} signature view{'s' if len(sig) != 1 else ''} "
           f"({', '.join(c[1]['title'] for c in sig) or 'none'}) and {len(spec.pages) - 1} page"
           f"{'s' if len(spec.pages) != 2 else ''}.")
    return spec, why


# ------------------------------------------------------------------ tools shared by the designer agent and the ops

class DashboardTools:
    def __init__(self, engine: Callable[[], "Engine"], actor: str = "designer"):
        self._engine, self.actor = engine, actor

    @property
    def e(self) -> "Engine":
        return self._engine()

    def stream_profile(self) -> dict[str, Any]:
        return stream_profile(self.e)

    def view_catalog(self) -> dict[str, Any]:
        out = catalog()
        out["builtins"] = {k: v for k, v in out["builtins"].items() if supported(self.e, k)}
        return out

    def dashboard_get(self) -> dict[str, Any]:
        s = self.e.dashboard.spec
        return {"version": s.version, "title": s.title, "terminology": s.terminology,
                "brief": s.brief.model_dump(), "machinery": s.machinery, "lens": self.e.dashboard.lens,
                "lenses": self.e.dashboard.lens_names(),
                "pages": [{"id": p.id, "title": p.title, "description": p.description, "by": p.by, "nav": p.nav,
                           "panels": [{"id": x.id, "title": x.title, "kind": x.kind, "builtin": x.builtin,
                                       "span": x.span, "view": x.view.model_dump() if x.view else None}
                                      for x in p.panels]} for p in s.pages],
                "by": s.by, "rationale": s.rationale}

    def view_preview(self, view: dict[str, Any]) -> dict[str, Any]:
        """Run a candidate view's query and return its shape and first rows (aggregates only)."""
        try:
            p = _check_panel(self.e, {"id": "preview", "title": "preview", "kind": "view", "view": view})
        except SpecError as exc:
            return {"ok": False, "error": str(exc)}
        d = panel_data(self.e, p)
        return {"ok": True, "columns": d["columns"], "rows": len(d["rows"]), "first_rows": d["rows"][:8],
                "note": "empty at the current replay time" if not d["rows"] else ""}

    def view_data(self, view: dict[str, Any]) -> dict[str, Any]:
        """Full result of a candidate view, for drawing a real preview in the dashboard."""
        try:
            p = _check_panel(self.e, {"id": "preview", "title": "preview", "kind": "view", "view": view})
        except SpecError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **panel_data(self.e, p)}

    def dashboard_lens(self, action: str, name: str = "", new_name: str = "") -> dict[str, Any]:
        """Saved layouts per scenario: list, save (the current dashboard under a new name), switch, delete, rename."""
        st = self.e.dashboard
        try:
            if action == "save":
                st.save_lens(name)
            elif action == "switch":
                st.switch_lens(name)
            elif action == "delete":
                st.delete_lens(name)
            elif action == "rename":
                st.rename_lens(name, new_name)
            elif action != "list":
                return {"ok": False, "error": "action is list, save, switch, delete or rename"}
        except SpecError as exc:
            return {"ok": False, "error": str(exc)}
        if action != "list":
            self.e._notify("dashboard", st.spec.model_dump())
        return {"ok": True, "current": st.lens, "lenses": st.lens_names()}

    def dashboard_edit(self, ops: list[dict[str, Any]], rationale: str = "") -> dict[str, Any]:
        try:
            for op in ops:
                if op.get("op") == "add_page":
                    op.setdefault("by", self.actor)
            res = self.e.dashboard.apply_ops(self.e, ops, by=self.actor, rationale=rationale)
        except SpecError as exc:
            return {"ok": False, "error": str(exc), "hint": "nothing was applied; fix the op and retry"}
        self.e._notify("dashboard", res["spec"])
        return {"ok": True, "version": res["version"], "applied": res["applied"]}

    # ---------------------------------------------------------------- the look (dashboard/theme.py)
    def theme_options(self) -> dict[str, Any]:
        from swarmscope.dashboard import theme as T
        return T.options()

    def theme_get(self) -> dict[str, Any]:
        from swarmscope.dashboard import theme as T
        st = T.store()
        r = T.resolve(st.spec)
        return {"spec": st.spec.model_dump(exclude={"updated"}), "fonts": r["font_names"], "attrs": r["attrs"],
                "light": {k: r["modes"]["light"][k] for k in T.TOKENS},
                "dark": {k: r["modes"]["dark"][k] for k in T.TOKENS}}

    def theme_set(self, changes: dict[str, Any], rationale: str = "") -> dict[str, Any]:
        from swarmscope.dashboard import theme as T
        try:
            st = T.store().apply(changes or {}, by=self.actor, rationale=rationale)
        except (T.ThemeError, ValueError, TypeError) as exc:
            return {"ok": False, "error": str(exc), "hint": "nothing was applied; adjust and retry"}
        self._tell(st)
        return {"ok": True, "version": st["spec"]["version"]}

    def theme_undo(self) -> dict[str, Any]:
        from swarmscope.dashboard import theme as T
        try:
            st = T.store().undo()
        except T.ThemeError as exc:
            return {"ok": False, "error": str(exc)}
        self._tell(st)
        return {"ok": True, "version": st["spec"]["version"]}

    def _tell(self, st: dict[str, Any]) -> None:
        try:
            e = self._engine()
        except Exception:
            e = None
        if e is not None:
            e._notify("theme", st)

    def dashboard_undo(self) -> dict[str, Any]:
        try:
            res = self.e.dashboard.undo()
        except SpecError as exc:
            return {"ok": False, "error": str(exc)}
        self.e._notify("dashboard", res["spec"])
        return {"ok": True, "version": res["version"]}

    SPECS: list[tuple[str, str, dict[str, Any]]] = [
        ("stream_profile", "Structure of the data stream: capabilities, fields, cardinalities, categorical values, "
                           "rate over time, scale layer. No agent-written text.", {"type": "object", "properties": {}}),
        ("view_catalog", "Primitives, built-in panels this source supports, the query language and the edit ops.",
         {"type": "object", "properties": {}}),
        ("dashboard_get", "The current dashboard: the Brief's settings, every page (the Brief is page 'brief') with "
                          "its panels, and the saved lenses.", {"type": "object", "properties": {}}),
        ("view_preview", "Try a view {primitive, query, options} against live data before adding it; returns columns "
                         "and first rows, or the validation error.",
         {"type": "object", "properties": {"view": {"type": "object"}}, "required": ["view"]}),
        ("dashboard_edit", "Apply edit ops atomically (add_page, update_page, move_page, remove_page, add_panel, "
                           "update_panel, remove_panel, move_panel, set_brief, set_machinery, reset_page, "
                           "set_terminology, set_title). Validated and versioned; nothing applies if any op fails.",
         {"type": "object", "properties": {"ops": {"type": "array", "items": {"type": "object"}},
                                           "rationale": {"type": "string"}}, "required": ["ops"]}),
        ("dashboard_undo", "Undo the last dashboard change.", {"type": "object", "properties": {}}),
        ("theme_options", "The whole design space for the look: presets, settings and their meanings, the typefaces "
                          "allowed for each role, settable colour tokens, what is fixed and the readability rules.",
         {"type": "object", "properties": {}}),
        ("theme_get", "The current look: preset, settings, typefaces and the resolved colours in light and dark.",
         {"type": "object", "properties": {}}),
        ("theme_set", "Change the look with checked settings {preset, mode, accent, fonts {display, ui, mono}, density, "
                      "radius, surface, canvas, nav, nav_style, headline, motion, colors {light|dark: {token: hex}}}. "
                      "Refused with the reason if text would be hard to read. Versioned; undo with theme_undo.",
         {"type": "object", "properties": {"changes": {"type": "object"}, "rationale": {"type": "string"}},
          "required": ["changes"]}),
        ("theme_undo", "Undo the last change to the look.", {"type": "object", "properties": {}}),
        ("dashboard_lens", "Saved layouts per scenario (lenses): action list | save | switch | delete | rename, with "
                           "name (and new_name for rename). Save copies the current dashboard under a new name.",
         {"type": "object", "properties": {"action": {"type": "string"}, "name": {"type": "string"},
                                           "new_name": {"type": "string"}}, "required": ["action"]}),
    ]

    def mcp_server(self):
        from claude_agent_sdk import create_sdk_mcp_server, tool

        def wrap(name):
            async def run(args: dict[str, Any]) -> dict[str, Any]:
                try:
                    res = getattr(self, name)(**{k: v for k, v in args.items() if v not in (None, "")})
                except Exception as exc:
                    return {"content": [{"type": "text", "text": f"error: {exc}"}], "is_error": True}
                return {"content": [{"type": "text", "text": json.dumps(res, default=str)[:14000]}]}
            return run
        tools = [tool(n, d, s)(wrap(n)) for n, d, s in self.SPECS]
        return create_sdk_mcp_server(name="dashboard", version="1.0.0", tools=tools), \
            [f"mcp__dashboard__{n}" for n, _, _ in self.SPECS]


DESIGN_SCHEMA = {"type": "object", "properties": {
    "summary": {"type": "string"}, "pages": {"type": "array", "items": {"type": "string"}},
    "open_questions": {"type": "array", "items": {"type": "string"}}}, "required": ["summary", "pages"]}


def free_design(engine: "Engine | None", instruction: str) -> dict[str, Any]:
    """The designer without a model: read a plain request into checked theme changes and Brief ops, and apply them.
    It says what it understood; anything else in the request is left for a model to do."""
    from swarmscope.dashboard import theme as T
    ch, ops, said = T.interpret(instruction)
    applied, errors = [], []
    if ch:
        try:
            T.store().apply(ch, by="designer", rationale=f"asked: {instruction[:200]}")
            applied.append("look")
        except T.ThemeError as exc:
            errors.append(str(exc))
    if ops and engine is not None:
        try:
            engine.dashboard.apply_ops(engine, ops, by="designer", rationale=f"asked: {instruction[:200]}")
            engine._notify("dashboard", engine.dashboard.spec.model_dump())
            applied.append("layout")
        except SpecError as exc:
            errors.append(str(exc))
    if engine is not None and "look" in applied:
        engine._notify("theme", T.store().state())
    if said and not errors:
        summary = "Changed " + ", ".join(said) + "."
    elif errors:
        summary = "Nothing changed: " + "; ".join(errors)
    else:
        summary = ("I did not recognise a change I can make without a model. Try words like dark, compact, a teal "
                   "accent, flat panels, Paper, Console, Clinic, no animation, or hide the World.")
    return {"backend": "stub", "understood": said, "applied": applied, "errors": errors, "summary": summary,
            "theme": ch, "ops": ops}


LOOK_PROMPT = ("You design the look of SwarmFrame, a dashboard for watching agent swarms, inside a fixed design space. "
               "You never write CSS or code: you change the look only through theme_set, whose settings are checked "
               "(typefaces from a list, colours checked for readability in light and dark, the colours that carry "
               "meaning are fixed). Call theme_options and theme_get first. Make the smallest change that does what "
               "was asked; start from a preset only when a whole new look is wanted. If a change is refused, read "
               "the reason, adjust and try again. Layout requests (pages, panels, the Brief) go through "
               "dashboard_edit. Finish with a one-paragraph summary of what you changed.")


async def run_designer(engine: "Engine", instruction: str = "", post: Callable[[str], Any] | None = None,
                       scope: str = "layout") -> dict[str, Any]:
    """One Claude Code session that customizes the dashboard, constrained to checked ops (layout) and checked theme
    settings (look). Without a model: the free designer reads plain requests; the free composer fills the layout."""
    if getattr(engine.pack, "source", {}).get("infer_capabilities"):
        from swarmscope.sources.generic_stream import infer_capabilities
        infer_capabilities(engine)
    if engine.router.mode == "stub" and instruction:
        free = free_design(engine, instruction)
        if free["applied"] or free["errors"] or scope in ("look", "all"):
            return {**free, "version": engine.dashboard.spec.version, "pages": []}
    if engine.router.mode == "stub":
        import copy
        from swarmscope.dashboard.spec import merge_pages
        auto, why = auto_design(engine, instruction)
        base = copy.deepcopy(engine.dashboard.spec)
        added = merge_pages(base, auto)
        if not added:
            return {"backend": "stub", "summary": "The dashboard already covers what the composer would add.",
                    "version": engine.dashboard.spec.version, "pages": [],
                    "reasons": {p.id: p.reason for p in base.pages if p.reason}}
        names = [next(p.title for p in base.pages if p.id == a) for a in added]
        why = f"Composed {', '.join(names)} from the stream profile. " + why
        res = engine.dashboard.replace(base, "auto", why)
        engine._notify("dashboard", res["spec"])
        return {"backend": "stub", "summary": why, "version": res["version"], "pages": added,
                "reasons": {p.id: p.reason for p in base.pages if p.reason}}
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    from swarmscope.agents.skills import compose
    from swarmscope.llm.router import find_claude_cli
    tools = DashboardTools(lambda: engine, actor="designer")
    server, names = tools.mcp_server()
    llm = engine.org.get("llm", {})
    role = (llm.get("roles") or {}).get("designer", {})
    if llm.get("mode") == "custom":
        from swarmscope.config import custom_llm
        role = {**role, **{k: v for k, v in custom_llm(engine.org, True).items() if k in ("model", "effort")}}
    model = llm.get("cheap", {}).get("model", "claude-sonnet-5-5") if llm.get("mode") == "cheap" else \
        role.get("model", "claude-sonnet-5-5")
    effort = llm.get("cheap", {}).get("effort", "low") if llm.get("mode") == "cheap" else role.get("effort", "low")
    system = compose(["dashboard-designer"], []) or "You design monitoring dashboards."
    builtins = [p.title for p in engine.dashboard.spec.pages if p.by == "pack" and p.id != "brief"]
    if scope == "look":
        system = LOOK_PROMPT
    prompt = (f"The viewer asked for this change to the look: {instruction}" if scope == "look" else
              f"The viewer asked: {instruction}\n\nThis may be about the layout (use dashboard_edit, previewing new "
              "views first), the look (theme_options, then theme_set), or both. Change only what was asked and finish "
              "with a short summary." if scope == "all" and instruction else "") or (
             "Compose this dashboard for the stream it is watching: the Brief (page 'brief') gets one or two signature "
              "views, and there are at most three Activity pages in all, each with a one-line `reason`. "
              + (f"The source ships pages ({', '.join(builtins)}); keep them and refine around them. "
                 if builtins else "")
              + (f"The viewer asked: {instruction}\n\n" if instruction else "Start from what the stream can show.\n\n")
              + "Call stream_profile and dashboard_get first, preview every new view, then apply your changes with "
                "dashboard_edit in one or two batches. Finish with a short summary of what you changed and why.")
    opts = ClaudeAgentOptions(system_prompt=system, model=model, effort=effort, max_turns=int(role.get("max_turns", 18)),
                              tools=[], allowed_tools=names, mcp_servers={"dashboard": server},
                              output_format={"type": "json_schema", "schema": DESIGN_SCHEMA}, setting_sources=[],
                              cli_path=find_claude_cli(), env={"MCP_TOOL_TIMEOUT": "600000"})
    result = None
    async for msg in query(prompt=prompt, options=opts):
        if isinstance(msg, ResultMessage):
            result = msg
    if result is None or result.is_error:
        raise RuntimeError(f"designer failed: {getattr(result, 'subtype', 'no result')}")
    data = result.structured_output or {}
    cost = float(result.total_cost_usd or 0)
    engine.router.spent_usd += cost
    return {"backend": "claude_code", "model": model, "summary": data.get("summary", ""), "pages": data.get("pages", []),
            "cost_usd": cost, "version": engine.dashboard.spec.version}
