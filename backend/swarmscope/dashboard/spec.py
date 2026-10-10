"""Dashboard specification: pages of panels, composed by humans or agents, versioned per source.

A panel is either a built-in (one of the dashboard's hand-made panels, by id) or a view: a primitive (how to draw)
plus a query (what to draw, dashboard/query.py). Every edit goes through `apply_ops`, which validates each op, runs
each new view's query once, and records a version, so any change can be undone and attributed.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from swarmscope.dashboard import query as Q
from swarmscope.ingest.packs import ROOT

if TYPE_CHECKING:
    from swarmscope.engine import Engine

PRIMITIVES = {
    "stat": "One big number, or a few tiles. Query without group_by, or one small dimension.",
    "timeseries": "Stacked area over time. group_by [ts:<bucket>] or [ts:<bucket>, <series dimension>].",
    "bar": "Horizontal bars ranked by value. group_by [<dimension>].",
    "heatmap": "Grid of two dimensions, e.g. [object, ts:day] or [object, family].",
    "table": "Rows of any grouped result.",
    "feed": "The latest matching events as a list (time, who, what, where); each row opens its record. Query with no "
            "group_by; `top` is how many rows (default 20).",
    "graph": "Who works with whom: a network of the first dimension, linked when they share values of the second. "
             "group_by [actor, object] (agents linked through shared resources) or any two dimensions.",
    "bipartite": "Two columns joined by lines weighted by count, e.g. agents and the resources they touch. "
                 "group_by [two dimensions].",
    "swimlane": "One lane per value of the first dimension, with marks over time sized by count. "
                "group_by [dimension, ts:<bucket>].",
    "note": "A short text written by the designer: what this page is for and how to read it. No query.",
}
# what a field in a query needs the source to have
FIELD_NEEDS = {"actor": "identities", "object": "resources"}
BUILTINS = {
    "brief": "The live brief: what SwarmFrame has noticed, newest first", "organization": "The analyst team",
    "population": "Agents and shared resources (needs identities)", "timeline": "Activity by workstream",
    "attention": "What deserves attention (incidents)", "questions": "Open questions",
    "investigations": "Active investigations", "monitor_attention": "Where monitors spend effort",
    "executive": "What the Executive holds", "health": "Monitor health", "say_do": "Narration vs action",
    "lineage": "Content lineage", "swimlane": "Agent swimlanes", "workstreams": "Workstreams",
    "environment": "Environment & humans", "control": "Live control", "feed": "Raw event stream",
    "cohorts": "Groups of similar agents (cohorts), with change and outliers",
    "triage": "Reading plan (triage): what the analysts read closely this cycle, and why",
    "coverage": "What we have read (coverage): which groups got a close look and which did not",
    "templates": "Message types (templates): kinds of agent text, with spread",
    "world": "The World: the swarm in 3D, units standing near what they work on and whom they work with",
}
MACHINERY = ["triage", "cohorts", "coverage", "organization", "health", "templates"]
GLANCE = {"active": "agents active", "attention": "need attention", "watching": "being watched",
          "investigating": "being looked into", "coverage": "read closely", "events": "events so far",
          "approvals": "awaiting your approval (live control only)",
          "total": "records so far (catalogs)", "recent": "last 30 days (catalogs)",
          "targets": "targets reached (catalogs)", "significant": "share graded significant (catalogs)"}
ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
DASH_DIR = ROOT / "data" / "dashboards"


class ViewSpec(BaseModel):
    primitive: str
    query: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)       # e.g. {"stack": true, "unit": "reports", "text": "..."}
    requires: list[str] = Field(default_factory=list)          # capabilities the view needs (filled in when checked)
    link: Literal["evidence", "none"] = "evidence"             # clicking a mark opens the records behind it


class PanelSpec(BaseModel):
    id: str
    title: str
    blurb: str = ""
    span: int = 6
    kind: Literal["builtin", "view"] = "view"
    builtin: str | None = None
    view: ViewSpec | None = None


class PageSpec(BaseModel):
    id: str
    title: str
    description: str = ""
    icon: str = "layers"
    panels: list[PanelSpec] = Field(default_factory=list)
    by: str = "human"
    nav: str = "activity"          # brief (the home page) | activity (under Activity) | top (its own nav entry)
    reason: str = ""               # why the composer proposed it, shown while composing


class BriefSpec(BaseModel):
    """The Brief's fixed sections, configurable; its panels live on the page with id 'brief'."""
    glance: list[str] = Field(default_factory=lambda: ["active", "attention", "investigating", "coverage"])
    attention_rows: int = 5
    min_severity: str = "WATCH"    # ACT | LOOK | WATCH
    show_changes: bool = True
    world: bool = True             # the World next to "Needs attention"
    overview: bool = True          # "What's going on": every group's work and what is emerging, whatever the severity
    pinned: list[str] = Field(default_factory=list)
    snoozed: list[str] = Field(default_factory=list)


class DashboardSpec(BaseModel):
    source: str
    version: int = 0
    title: str = ""
    terminology: dict[str, str] = Field(default_factory=dict)  # e.g. {"agent": "report", "resource": "target"}
    room: list[dict[str, Any]] = Field(default_factory=list)    # retired (pre-Brief layouts); read only to migrate
    pages: list[PageSpec] = Field(default_factory=list)
    brief: BriefSpec = Field(default_factory=BriefSpec)
    machinery: bool = False
    pack_hash: str = ""            # the pack dashboard.yaml this spec came from (refreshed when it changes, if unedited)
    by: str = "default"
    rationale: str = ""
    updated: str | None = None


class SpecError(ValueError):
    pass


def _check_panel(engine: "Engine", p: dict[str, Any]) -> PanelSpec:
    p = dict(p)
    p.setdefault("id", re.sub(r"[^a-z0-9]+", "_", str(p.get("title", "panel")).lower()).strip("_")[:40] or "panel")
    if not ID.match(p["id"]):
        raise SpecError(f"panel id {p['id']!r}: lowercase letters, digits, - and _ only")
    p["span"] = max(3, min(12, int(p.get("span", 6))))
    if p.get("builtin") and not p.get("view"):
        p["kind"] = "builtin"
    ps = PanelSpec(**p)
    if ps.kind == "builtin":
        if ps.builtin not in BUILTINS:
            raise SpecError(f"unknown built-in {ps.builtin!r}; known: {', '.join(BUILTINS)}")
        return ps
    if not ps.view or ps.view.primitive not in PRIMITIVES:
        raise SpecError(f"panel {ps.id}: view.primitive must be one of {', '.join(PRIMITIVES)}")
    if ps.view.primitive == "note":
        if not str(ps.view.options.get("text", "")).strip():
            raise SpecError(f"panel {ps.id}: a note needs options.text")
        ps.view.options["text"] = str(ps.view.options["text"])[:1200]
        return ps
    from swarmscope.dashboard.profile import text_attributes
    prim = ps.view.primitive
    q = ps.view.query
    if prim == "feed":
        q["list"] = True
    elif q.get("list"):
        raise SpecError(f"panel {ps.id}: only a feed lists events; drop `list`")
    dims = [str(x) for x in (q.get("group_by") or [])] + [str(k) for k in (q.get("where") or {})]
    needs = sorted({FIELD_NEEDS[d] for d in dims if d in FIELD_NEEDS}
                   | ({"timestamps"} if prim in ("timeseries", "swimlane") else set()))
    missing = [c for c in needs if not engine.profile.has(c)]
    if missing and q.get("from", "events") == "events":
        raise SpecError(f"panel {ps.id}: this source has no {', '.join(missing)}, which the view needs")
    ps.view.requires = needs
    try:
        Q.run(engine, q, text_attributes(engine))
    except Q.QueryError as exc:
        raise SpecError(f"panel {ps.id}: {exc}") from exc
    gb = [str(x) for x in (q.get("group_by") or [])]
    g = len(gb)
    if prim in ("graph", "bipartite") and (g != 2 or any(x.startswith("ts:") for x in gb)):
        raise SpecError(f"panel {ps.id}: a {prim} needs two group_by dimensions that are not time, e.g. [actor, object]")
    if prim == "swimlane" and (g != 2 or sum(x.startswith("ts:") for x in gb) != 1 or gb[0].startswith("ts:")):
        raise SpecError(f"panel {ps.id}: a swimlane needs group_by [dimension, ts:<bucket>]")
    if prim == "timeseries" and not any(str(x).startswith("ts:") for x in ps.view.query.get("group_by") or []):
        raise SpecError(f"panel {ps.id}: timeseries needs a ts:<bucket> in group_by")
    if prim == "heatmap" and g != 2 and ps.view.query.get("from", "events") == "events":
        raise SpecError(f"panel {ps.id}: heatmap needs two group_by dimensions")
    return ps


class DashboardStore:
    """Per-source specs, one per lens (a saved layout for a scenario), each with its own version history (undo), on
    disk under data/dashboards/<source>.json. `spec` and `history` always refer to the current lens."""

    def __init__(self, source: str, path: Path | None | bool = None):
        """path=None persists under data/dashboards/<source>.json; path=False keeps the spec in memory only."""
        self.source = source
        self.path = None if path is False else (path or DASH_DIR / f"{source}.json")
        self.lens = "Default"
        self.lenses: dict[str, dict[str, Any]] = {}
        self.history: list[dict[str, Any]] = []
        self.spec = DashboardSpec(source=source)
        if self.path is not None and self.path.exists():
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
                if "lenses" in d:
                    self.lenses = d["lenses"]
                    self.lens = d.get("current") if d.get("current") in self.lenses else next(iter(self.lenses))
                else:                                                       # single-spec file from before lenses
                    self.lenses = {"Default": {"spec": d["spec"], "history": d.get("history", [])}}
                cur = self.lenses[self.lens]
                self.spec = migrate(DashboardSpec(**cur["spec"]))
                self.history = cur.get("history", [])[-30:]
            except Exception:
                self.lenses, self.lens = {}, "Default"
        self.lenses.setdefault(self.lens, {"spec": self.spec.model_dump(), "history": self.history})

    @property
    def empty(self) -> bool:
        return not self.spec.pages and not self.spec.room and self.spec.version == 0

    def save(self) -> None:
        self.lenses[self.lens] = {"spec": self.spec.model_dump(), "history": self.history[-30:]}
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"current": self.lens, "lenses": self.lenses}, indent=1), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------ lenses
    def lens_names(self) -> list[str]:
        return list(self.lenses)

    def save_lens(self, name: str) -> None:
        name = str(name).strip()[:40]
        if not name:
            raise SpecError("a lens needs a name")
        if name in self.lenses:
            raise SpecError(f"there is already a lens called {name!r}")
        self.save()
        spec = copy.deepcopy(self.spec)
        spec.version, spec.by, spec.rationale = 1, "human", f"saved as the lens {name}"
        self.lenses[name] = {"spec": spec.model_dump(), "history": []}
        self.switch_lens(name)

    def switch_lens(self, name: str) -> None:
        if name not in self.lenses:
            raise SpecError(f"no lens {name!r}; lenses: {', '.join(self.lenses)}")
        self.save()
        self.lens = name
        self.spec = migrate(DashboardSpec(**self.lenses[name]["spec"]))
        self.history = self.lenses[name].get("history", [])
        self.save()

    def delete_lens(self, name: str) -> None:
        if name not in self.lenses:
            raise SpecError(f"no lens {name!r}")
        if len(self.lenses) == 1:
            raise SpecError("the last lens cannot be deleted")
        del self.lenses[name]
        if self.lens == name:
            self.lens = next(iter(self.lenses))
            self.spec = migrate(DashboardSpec(**self.lenses[self.lens]["spec"]))
            self.history = self.lenses[self.lens].get("history", [])
        self.save()

    def rename_lens(self, old: str, new: str) -> None:
        new = str(new).strip()[:40]
        if old not in self.lenses or not new or new in self.lenses:
            raise SpecError("rename needs an existing lens and a new, unused name")
        self.save()
        self.lenses = {(new if k == old else k): v for k, v in self.lenses.items()}
        if self.lens == old:
            self.lens = new
        self.save()

    def apply_ops(self, engine: "Engine", ops: list[dict[str, Any]], by: str = "human",
                  rationale: str = "") -> dict[str, Any]:
        """Validate and apply ops atomically. Returns {spec, applied, version}."""
        new = copy.deepcopy(self.spec)
        applied = []
        for op in ops[:40]:
            kind = op.get("op")
            try:
                applied.append(_apply(engine, new, op))
            except (SpecError, Q.QueryError, KeyError, TypeError, ValueError) as exc:
                raise SpecError(f"op {len(applied) + 1} ({kind}): {exc}") from exc
        self.history.append({"version": self.spec.version, "spec": self.spec.model_dump(), "by": self.spec.by,
                             "rationale": self.spec.rationale})
        new.version = self.spec.version + 1
        new.by, new.rationale = by, rationale or "; ".join(applied)[:400]
        new.updated = datetime.utcnow().isoformat(timespec="seconds")
        self.spec = new
        self.save()
        return {"spec": self.spec.model_dump(), "applied": applied, "version": new.version}

    def undo(self) -> dict[str, Any]:
        if not self.history:
            raise SpecError("nothing to undo")
        prev = self.history.pop()
        v = self.spec.version
        self.spec = DashboardSpec(**prev["spec"])
        self.spec.version = v + 1
        self.save()
        return {"spec": self.spec.model_dump(), "version": self.spec.version}

    def replace(self, spec: DashboardSpec, by: str, rationale: str) -> dict[str, Any]:
        self.history.append({"version": self.spec.version, "spec": self.spec.model_dump(), "by": self.spec.by,
                             "rationale": self.spec.rationale})
        spec.version = self.spec.version + 1
        spec.by, spec.rationale = by, rationale
        spec.updated = datetime.utcnow().isoformat(timespec="seconds")
        self.spec = spec
        self.save()
        return {"spec": spec.model_dump(), "version": spec.version}

    def find_panel(self, page_id: str, panel_id: str) -> PanelSpec | None:
        page = next((p for p in self.spec.pages if p.id == page_id), None)
        return next((x for x in page.panels if x.id == panel_id), None) if page else None


def _page(spec: DashboardSpec, pid: str) -> PageSpec:
    p = next((p for p in spec.pages if p.id == pid), None)
    if p is None:
        raise SpecError(f"no page {pid!r}; pages: {', '.join(x.id for x in spec.pages) or 'none'}")
    return p


def _apply(engine: "Engine", spec: DashboardSpec, op: dict[str, Any]) -> str:
    kind = op.get("op")
    if kind == "add_page":
        pid = op.get("id") or re.sub(r"[^a-z0-9]+", "_", op["title"].lower()).strip("_")[:40]
        if not ID.match(pid):
            raise SpecError("page id: lowercase letters, digits, - and _ only")
        if any(p.id == pid for p in spec.pages):
            raise SpecError(f"page {pid} exists")
        if len(spec.pages) >= 12:
            raise SpecError("at most 12 custom pages")
        panels = [_check_panel(engine, p) for p in (op.get("panels") or [])[:16]]
        spec.pages.append(PageSpec(id=pid, title=op["title"][:60], description=str(op.get("description", ""))[:400],
                                   icon=op.get("icon", "layers"), panels=panels, by=op.get("by", "human"),
                                   nav="top" if op.get("nav") == "top" else "activity",
                                   reason=str(op.get("reason", ""))[:300]))
        return f"added page {pid} with {len(panels)} panels"
    if kind == "remove_page":
        if op["page"] == "brief":
            raise SpecError("the Brief cannot be removed; remove its panels or reset it instead")
        before = len(spec.pages)
        spec.pages = [p for p in spec.pages if p.id != op["page"]]
        if len(spec.pages) == before:
            raise SpecError(f"no page {op['page']}")
        if op["page"] == "machinery":
            spec.machinery = False
        return f"removed page {op['page']}"
    if kind == "update_page":
        p = _page(spec, op["page"])
        for k in ("title", "description", "icon", "reason"):
            if k in op:
                setattr(p, k, str(op[k])[:400])
        if "nav" in op:
            if op["nav"] not in ("activity", "top") or p.id == "brief":
                raise SpecError("nav is activity or top (the Brief stays the home page)")
            p.nav = op["nav"]
        return f"updated page {p.id}"
    if kind == "move_page":
        i = next((i for i, x in enumerate(spec.pages) if x.id == op["page"]), None)
        if i is None:
            raise SpecError(f"no page {op['page']}")
        x = spec.pages.pop(i)
        spec.pages.insert(max(0, min(len(spec.pages), int(op["to"]))), x)
        return f"moved page {x.id}"
    if kind == "set_brief":
        b = spec.brief
        if "glance" in op:
            g = [str(x) for x in op["glance"] if str(x) in GLANCE][:6]
            if not g:
                raise SpecError(f"glance needs 1-6 of: {', '.join(GLANCE)}")
            b.glance = g
        if "attention_rows" in op:
            b.attention_rows = max(0, min(12, int(op["attention_rows"])))
        if "min_severity" in op:
            if op["min_severity"] not in ("ACT", "LOOK", "WATCH"):
                raise SpecError("min_severity is ACT, LOOK or WATCH")
            b.min_severity = op["min_severity"]
        if "show_changes" in op:
            b.show_changes = bool(op["show_changes"])
        if "world" in op:
            b.world = bool(op["world"])
        if "overview" in op:
            b.overview = bool(op["overview"])
        for key in ("pin", "unpin", "snooze", "unsnooze"):
            if key in op:
                lst = b.pinned if key in ("pin", "unpin") else b.snoozed
                v = str(op[key])
                if key in ("pin", "snooze") and v not in lst:
                    lst.append(v)
                elif key in ("unpin", "unsnooze") and v in lst:
                    lst.remove(v)
        return "updated the Brief"
    if kind == "set_machinery":
        on = bool(op.get("on", True))
        spec.machinery = on
        spec.pages = [p for p in spec.pages if p.id != "machinery"]
        if on:
            spec.pages.append(PageSpec(
                id="machinery", title="The machinery", by="human", nav="activity",
                description="How the oversight works: reading plan, groups, coverage, the analyst team and monitor "
                            "health, as full panels.",
                panels=[_check_panel(engine, {"id": b, "title": MACHINERY_TITLES[b], "builtin": b,
                                              "span": 7 if b in ("triage", "organization") else 5})
                        for b in MACHINERY if _supported(engine, b)]))
        return "showed the machinery" if on else "hid the machinery"
    if kind == "reset_page":
        b = builtin_spec(engine) or default_spec(engine)
        src = next((p for p in b.pages if p.id == op["page"]), None)
        if src is None:
            raise SpecError(f"page {op['page']} has no default version to reset to")
        i = next((i for i, x in enumerate(spec.pages) if x.id == src.id), None)
        if i is None:
            spec.pages.insert(0 if src.id == "brief" else len(spec.pages), src)
        else:
            spec.pages[i] = src
        if src.id == "brief":
            spec.brief = b.brief
        return f"reset page {src.id} to the source's default"
    if kind == "add_panel":
        p = _page(spec, op["page"])
        panel = _check_panel(engine, op["panel"])
        if any(x.id == panel.id for x in p.panels):
            raise SpecError(f"panel {panel.id} exists on {p.id}")
        at = op.get("at")
        p.panels.insert(int(at) if at is not None else len(p.panels), panel)
        return f"added {panel.id} to {p.id}"
    if kind == "update_panel":
        p = _page(spec, op["page"])
        i = next((i for i, x in enumerate(p.panels) if x.id == op["panel_id"]), None)
        if i is None:
            raise SpecError(f"no panel {op['panel_id']} on {p.id}")
        merged = {**p.panels[i].model_dump(), **(op.get("changes") or {})}
        if "view" in (op.get("changes") or {}) and isinstance(op["changes"]["view"], dict):
            merged["view"] = {**(p.panels[i].view.model_dump() if p.panels[i].view else {}), **op["changes"]["view"]}
        p.panels[i] = _check_panel(engine, merged)
        return f"updated {op['panel_id']} on {p.id}"
    if kind == "remove_panel":
        p = _page(spec, op["page"])
        if not any(x.id == op["panel_id"] for x in p.panels):
            raise SpecError(f"no panel {op['panel_id']} on {p.id}")
        p.panels = [x for x in p.panels if x.id != op["panel_id"]]
        return f"removed {op['panel_id']} from {p.id}"
    if kind == "move_panel":
        p = _page(spec, op["page"])
        i = next((i for i, x in enumerate(p.panels) if x.id == op["panel_id"]), None)
        if i is None:
            raise SpecError(f"no panel {op['panel_id']} on {p.id}")
        x = p.panels.pop(i)
        p.panels.insert(max(0, min(len(p.panels), int(op["to"]))), x)
        return f"moved {op['panel_id']}"
    if kind == "set_room":                                   # retired; kept so old agents get a clear message
        raise SpecError("the Situation Room is now the Brief: add_panel / remove_panel on page 'brief', and set_brief "
                        "for its glance numbers and attention list")
    if kind == "set_terminology":
        spec.terminology = {str(k)[:24]: str(v)[:24] for k, v in (op.get("terms") or {}).items()}
        return "set terminology"
    if kind == "restore_builtin":
        b = builtin_spec(engine) or default_spec(engine)
        names = []
        for p in b.pages:
            if not any(x.id == p.id for x in spec.pages):
                spec.pages.insert(len([x for x in spec.pages if x.by == "pack"]), p)
                names.append(p.id)
        return f"restored the source's default pages ({', '.join(names) or 'all already present'})"
    if kind == "set_title":
        spec.title = str(op.get("title", ""))[:80]
        return "set title"
    raise SpecError(f"unknown op {kind!r}; ops: {', '.join(OPS)}")


OPS = ["add_page", "remove_page", "update_page", "move_page", "add_panel", "update_panel", "remove_panel",
       "move_panel", "set_brief", "set_machinery", "reset_page", "set_terminology", "set_title", "restore_builtin"]
MACHINERY_TITLES = {"triage": "Reading plan", "cohorts": "Groups of similar agents", "coverage": "What we have read",
                    "organization": "The analyst team", "health": "Monitor health", "templates": "Message types"}


def _supported(engine: "Engine", builtin: str) -> bool:
    from swarmscope.dashboard.designer import supported
    return supported(engine, builtin)


def migrate(spec: DashboardSpec) -> DashboardSpec:
    """Older specs: give them a Brief page and drop the retired room layout."""
    if not any(p.id == "brief" for p in spec.pages):
        spec.pages.insert(0, PageSpec(id="brief", title="Brief", nav="brief", by=spec.by or "default"))
    for p in spec.pages:
        if p.id == "brief":
            p.nav = "brief"
        elif p.nav == "brief":
            p.nav = "activity"
    spec.room = []
    return spec


def default_spec(engine: "Engine") -> DashboardSpec:
    """A Brief with no signature views, for sources without a pack dashboard and before anything is composed."""
    return DashboardSpec(source=engine.profile.source, title=engine.profile.title,
                         pages=[PageSpec(id="brief", title="Brief", nav="brief", by="default")])


def pack_hash(engine: "Engine") -> str:
    import hashlib
    f = engine.pack.dir / "dashboard.yaml"
    return hashlib.sha1(f.read_bytes()).hexdigest()[:12] if f.exists() else ""


def builtin_spec(engine: "Engine") -> DashboardSpec | None:
    """The source pack's own curated views (packs/<id>/dashboard.yaml), validated against this engine.

    `brief:` holds the Brief's signature panels and settings; `pages:` become Activity pages."""
    import yaml
    f = engine.pack.dir / "dashboard.yaml"
    if not f.exists():
        return None
    d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    spec = DashboardSpec(source=engine.profile.source, title=d.get("title", ""), terminology=d.get("terminology") or {},
                         pack_hash=pack_hash(engine))

    def panels_of(where: str, xs: list[dict[str, Any]] | None) -> list[PanelSpec]:
        out = []
        for x in xs or []:
            try:
                ps = _check_panel(engine, x)
                if ps.kind == "builtin" and not _supported(engine, ps.builtin or ""):
                    continue
                out.append(ps)
            except SpecError as exc:
                engine.router.errors.append(f"built-in view {where}/{x.get('id')}: {exc}")
        return out

    b = d.get("brief") or {}
    spec.brief = BriefSpec(**{k: v for k, v in b.items() if k in BriefSpec.model_fields})
    spec.pages.append(PageSpec(id="brief", title="Brief", nav="brief", by="pack",
                               panels=panels_of("brief", b.get("panels"))))
    for p in d.get("pages") or []:
        spec.pages.append(PageSpec(id=p["id"], title=p["title"], description=p.get("description", ""),
                                   icon=p.get("icon", "layers"), panels=panels_of(p["id"], p.get("panels")), by="pack",
                                   nav=p.get("nav", "activity"), reason=p.get("reason", "")))
    return spec


def merge_pages(base: DashboardSpec, extra: DashboardSpec, max_activity: int = 3) -> list[str]:
    """Add extra's Activity pages that base lacks, keeping at most `max_activity` Activity pages in all; fill an empty
    Brief from extra's. Returns the ids added (including 'brief' when its panels were filled)."""
    added = []
    bb = next((p for p in base.pages if p.id == "brief"), None)
    eb = next((p for p in extra.pages if p.id == "brief"), None)
    if bb is None and eb is not None:
        base.pages.insert(0, eb)
        added.append("brief")
    elif bb is not None and eb is not None and not bb.panels and eb.panels:
        bb.panels = eb.panels
        added.append("brief")
    have = {p.id for p in base.pages}
    have_builtins = {x.builtin for p in base.pages for x in p.panels if x.kind == "builtin"}
    titles = {p.title.lower() for p in base.pages}
    n_act = sum(1 for p in base.pages if p.nav != "brief")
    for p in extra.pages:
        if p.id == "brief" or n_act >= max_activity:
            continue
        bis = {x.builtin for x in p.panels if x.kind == "builtin"}
        if p.id in have or p.title.lower() in titles or (bis and len(bis & have_builtins) >= 2):
            continue
        base.pages.append(p)
        added.append(p.id)
        n_act += 1
    base.title = base.title or extra.title
    base.terminology = base.terminology or extra.terminology
    return added


def panel_data(engine: "Engine", panel: PanelSpec) -> dict[str, Any]:
    if panel.kind != "view" or not panel.view or panel.view.primitive == "note":
        return {"columns": [], "rows": [], "meta": {}}
    from swarmscope.dashboard.profile import text_attributes
    return Q.run(engine, panel.view.query, text_attributes(engine))


def catalog() -> dict[str, Any]:
    return {"primitives": PRIMITIVES, "builtins": BUILTINS, "query": {
        "sources": Q.SOURCES, "metrics": Q.METRICS, "fields": sorted(Q.CORE) + sorted(Q.BUCKETS) + ["attr.<key>"],
        "where": "field: value | [values] | {prefix: str}; actor/object accept ids or labels",
        "time": "{last_hours: N} (default 24) or {all: true}; always clipped to the replay clock",
        "group_by": "up to two fields; time buckets ts:hour | ts:day | ts:week | ts:month",
        "derived_sources": "cohorts | templates | triage | claims | org | observations (group_by kind, scope, ts:day)"},
        "ops": OPS, "glance": GLANCE,
        "brief": "The home page is the page with id 'brief'. It always shows a status sentence, glance numbers "
                 "(set_brief glance), a ranked attention list (set_brief attention_rows, min_severity) and what "
                 "changed; its own panels are 1-3 signature views. Any panel, built-in or view, may go on any page."}
