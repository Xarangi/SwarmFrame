"""German Wiki (the collusion.wiki message board): handles writing on a shared wiki, May to July 2026.

Real mode reads the export (json / jsonl / csv / zip) with the field aliases in packs/german_wiki/source.yaml. The
export format is unconfirmed until it is downloaded, so run `swarmscope probe <export>` first (structure only: field
names, types and counts, never values) and adjust the aliases. SwarmFrame never shows page bodies: they become
fingerprinted artifacts behind the evidence boundary.

Synthetic mode (no export on disk) generates a seeded corpus shaped like the documented incident, with exact ground
truth and neutral placeholder text; planted behaviours are carried by `[[marker:...]]` tags, never real content:

  convergence  from Jun 16, handle groups that never shared a page converge on the same question pages
  propagation  a formatting block posted on a discussion page is copied by other groups, some of whom had read
               that page first (observable exposure) and some of whom had not (chronological only)
  surge        writing on the question pages jumps several-fold from Jun 16 to 22
  moderation   moderators delete question pages and the authors' user pages in sweeps from Jun 19
  displacement after the sweeps, affected groups move to new pages and partly reappear under new handle variants
               (identity is partial: a handle is not a stable agent)
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

from swarmscope.core.models import Entity, EvidenceEvent
from swarmscope.ingest.adapter import Batch, iter_records, make_artifact, parse_ts, pick
from swarmscope.sources.common import family_of, handle_stem, short_hash

SRC = "german_wiki"
START = datetime(2026, 5, 11)
END = datetime(2026, 7, 2)
SURGE = datetime(2026, 6, 16)
SWEEP = datetime(2026, 6, 19)
SURGE_END = datetime(2026, 6, 23)

FILLER = [
    "Notiz zur laufenden Aufgabe, Zwischenstand folgt.",
    "Quelle geprueft, Angabe stimmt mit dem Archiv ueberein.",
    "Arbeitsbereich fuer die aktuelle Recherche dieser Gruppe.",
    "Weitere Fragen folgen, bitte nicht loeschen.",
    "Zusammenfassung der bisherigen Ergebnisse.",
    "Offene Punkte stehen unten in der Liste.",
    "Zwei Angaben widersprechen sich, bitte pruefen.",
]
VOCAB = ["Archiv", "Quelle", "Tabelle", "Abschnitt", "Datum", "Liste", "Eintrag", "Vermerk", "Beleg", "Verweis",
         "Seite", "Zeile", "Spalte", "Angabe", "Fassung", "Stand", "Auszug", "Rubrik", "Ordner", "Kapitel", "Fussnote",
         "Register", "Notiz", "Entwurf", "Version", "Bestand", "Katalog", "Index", "Anhang", "Signatur"]
FORMAT_BLOCK = "[[marker:format_convention]] Eintraege bitte im vereinbarten Format, damit spaetere Gruppen sie finden."
POOL_BLOCK = "[[marker:answer_pool]] Sammelblock fuer Antworten zu dieser Frage, bitte ergaenzen statt neu anlegen."
DISPLACE_BLOCK = "[[marker:relocation]] Inhalte wurden hierher verschoben."


class GermanWikiAdapter:
    id = SRC

    def __init__(self, pack: Any):
        self.pack = pack
        self.cfg = pack.source.get("generator") or {}

    def capabilities(self):
        return self.pack.capabilities

    def load(self, path: str | None = None, slice_override: dict[str, Any] | None = None) -> Batch:
        from pathlib import Path
        from swarmscope.ingest.packs import ROOT
        if path is None:                                         # the export, if it has been put in place
            default = ROOT / self.pack.source.get("default_path", "data/german_wiki")
            path = str(default) if default.exists() and any(default.iterdir()) else None
            if path:
                self.pack.capabilities.synthetic = False
        if path and path != "synthetic" and Path(path).exists():
            if Path(path).is_dir() and ((Path(path) / "revisions.jsonl.gz").exists() or (Path(path) / "revisions.jsonl").exists()):
                b = self._load_collusion(Path(path))
            else:
                b = self._load_real(path)
            return self._slice(b, slice_override)
        self.pack.capabilities.synthetic = True
        cfg = {"groups": 120, "seed": 11, **self.cfg, **(slice_override or {})}
        return synthesize(int(cfg["groups"]), int(cfg["seed"]))

    def _slice(self, b: Batch, override: dict[str, Any] | None) -> Batch:
        """The analysis period: by default the June surge (source.yaml `slice`), or the whole record with
        {"full": true}. Entities are kept; events outside the period are dropped."""
        cfg = {**(self.pack.source.get("slice") or {}), **(override or {})}
        if cfg.get("full") or not (cfg.get("start") or cfg.get("end")):
            return b
        lo, hi = parse_ts(cfg.get("start")), parse_ts(cfg.get("end"))
        b.events = [e for e in b.events if (lo is None or e.ts >= lo) and (hi is None or e.ts < hi)]
        b.meta = {**b.meta, "slice_start": lo, "slice_end": hi, "slice": cfg.get("label", "")}
        return b

    # -------------------------------------------------------------- the collusion.wiki export (explorer/download)
    def _load_collusion(self, d: "Any") -> Batch:
        """revisions.jsonl.gz (one save each, with the saved body), events.jsonl.gz (saves, deletions, reverts, probes),
        pages.jsonl.gz (page names and families), labels.jsonl.gz (one name each). Structure confirmed with a
        structure-only probe; bodies go behind the evidence boundary as fingerprinted blocks and are never shown.
        Network prefixes in the export are not used: identity stays partial on purpose."""
        import gzip
        import json

        def rows(name: str):
            f = d / name
            if not f.exists():                             # the same files uncompressed (e.g. a benchmark's copy)
                f = d / name.removesuffix(".gz")
                if not f.exists():
                    return
            opener = gzip.open if f.name.endswith(".gz") else open
            with opener(f, "rt", encoding="utf-8") as fh:
                for i, line in enumerate(fh):
                    if line.strip():
                        yield f"{name}:{i + 1}", json.loads(line)

        b = Batch()
        pages: dict[str, Entity] = {}
        fam_of: dict[str, str] = {}
        for _, r in rows("pages.jsonl.gz"):
            key = str(r.get("page_key") or r.get("page_id") or "")
            if not key:
                continue
            fam = str(r.get("page_family") or family_of(str(r.get("name") or key)) or "other")[:40]
            fam_of[key] = fam
            pages[f"p:{key}"] = Entity(id=f"p:{key}", type="resource", source=SRC, label=str(r.get("name") or key)[:120],
                                       group=fam, attributes={"wiki": r.get("wiki")})
        human = {str(r.get("label")) for _, r in rows("labels.jsonl.gz") if r.get("is_human_handle")}
        actors: dict[str, Entity] = {}

        def actor(label: Any, kind: str = "actor") -> str:
            name = str(label or "").strip() or "(no name)"
            aid = f"a:{name}"
            if aid not in actors:
                t = "human" if name in human else kind
                actors[aid] = Entity(id=aid, type=t, source=SRC, label=name[:80], identity_confidence="partial",
                                     group="moderators" if kind == "moderator" else handle_stem(name))
            return aid

        def page(key: str) -> str:
            pid = f"p:{key}"
            if pid not in pages:
                fam_of.setdefault(key, "other")            # e.g. pages deleted before the page list was built
                pages[pid] = Entity(id=pid, type="resource", source=SRC, label=key[:120], group=fam_of[key])
            return pid

        timeline: list[tuple[Any, int, str, dict[str, Any]]] = []
        for loc, r in rows("revisions.jsonl.gz"):
            ts = parse_ts(r.get("time") or r.get("write_date"))
            if ts is not None:
                timeline.append((ts, 0, loc, r))
        probes = {"browse", "browse-bare", "form_search", "showtop", "random", "form_editprefs", "editprefs", "rc"}
        for loc, r in rows("events.jsonl.gz"):
            if r.get("event_type") == "save":
                continue                                   # saves come from revisions, with their bodies
            ts = parse_ts(r.get("time") or r.get("request_time"))
            if ts is not None:
                timeline.append((ts, 1, loc, r))
        timeline.sort(key=lambda x: (x[0], x[1]))
        last_author: dict[str, str] = {}
        for ts, kind, loc, r in timeline:
            key = str(r.get("page_key") or r.get("page_id") or r.get("page") or "")
            if kind == 0:
                if not key:
                    continue
                aid, pid = actor(r.get("label") or r.get("name")), page(key)
                body = r.get("body") or ""
                art = None
                if body:
                    a, clean = make_artifact(f"art:{r.get('rev_id') or loc}", str(body), ts, aid, "agent_text")
                    b.artifacts.append((a, clean))
                    art = a.id
                b.events.append(EvidenceEvent(
                    id=f"ev:{r.get('rev_id') or loc}", ts=ts, source=SRC, actor=aid, action="resource.write", object=pid,
                    artifact=art, locator=loc, attributes={"family": fam_of.get(key, "other"), "wiki": r.get("wiki"),
                                                           "size": r.get("body_len"), "round": r.get("round_id")}))
                last_author[pid] = aid
                continue
            et = str(r.get("event_type") or "")
            pid = page(key) if key else None
            if et == "delete":
                b.events.append(EvidenceEvent(
                    id=f"ev:{r.get('event_id') or loc}", ts=ts, source=SRC, actor=actor(r.get("actor_label"), "moderator"),
                    action="environment.moderation_delete", object=pid, locator=loc,
                    attributes={"family": fam_of.get(key, "other"), "target_agent": last_author.get(pid or "", "")}))
            elif et == "revert":
                b.events.append(EvidenceEvent(
                    id=f"ev:{r.get('event_id') or loc}", ts=ts, source=SRC, actor=actor(r.get("actor_label"), "moderator"),
                    action="environment.revert", object=pid, locator=loc,
                    attributes={"family": fam_of.get(key, "other"), "target_agent": last_author.get(pid or "", "")}))
            elif et in ("probe", "request"):               # page requests, not edits; the request kind is whitelisted
                req = str(r.get("request_action") or "")
                b.events.append(EvidenceEvent(
                    id=f"ev:{r.get('event_id') or loc}", ts=ts, source=SRC, actor=actor(r.get("actor_label") or "(visitor)"),
                    action="probe." + (req if req in probes else "other"), object=pid, locator=loc,
                    attributes={"family": "probe"}))
        b.entities = list(actors.values()) + list(pages.values())
        b.meta = {"synthetic": False, "goal_text": f"collusion.wiki export: {len(actors)} names, {len(pages)} pages"}
        return b

    # -------------------------------------------------------------- a generic export
    def _load_real(self, path: str) -> Batch:
        m = self.pack.source.get("fields", {})
        mods = set(self.pack.source.get("moderators") or [])
        b = Batch()
        actors: dict[str, Entity] = {}
        pages: dict[str, Entity] = {}
        last_author: dict[str, str] = {}
        rows = []
        for loc, r in iter_records(path):
            ts = parse_ts(pick(r, *m.get("timestamp", ["timestamp", "ts", "time", "created_at"])))
            if ts is not None:
                rows.append((ts, loc, r))
        rows.sort(key=lambda x: x[0])
        for ts, loc, r in rows:
            handle = str(pick(r, *m.get("actor", ["actor", "user", "author", "username", "ip"]), default="unknown"))
            title = str(pick(r, *m.get("page", ["page", "title", "page_title"]), default="(untitled)"))
            body = str(pick(r, *m.get("body", ["body", "text", "content"]), default=""))
            kind = str(pick(r, *m.get("kind", ["action", "type", "kind"]), default="revision")).lower()
            rev = str(pick(r, *m.get("revision", ["revision_id", "rev_id", "id"]), default=short_hash(loc)))
            is_mod = handle in mods or bool(pick(r, *m.get("moderator", ["is_moderator", "moderator"]), default=False))
            delete = "delete" in kind or "loesch" in kind
            aid = f"a:{handle}"
            if aid not in actors:
                actors[aid] = Entity(id=aid, type="moderator" if is_mod or delete else "actor", source=SRC, label=handle,
                                     identity_confidence="partial", group=handle_stem(handle))
            pid = f"p:{title}"
            fam = family_of(title)
            if pid not in pages:
                pages[pid] = Entity(id=pid, type="resource", source=SRC, label=title, group=fam)
            if delete:
                b.events.append(EvidenceEvent(
                    id=f"ev:{rev}", ts=ts, source=SRC, actor=aid, action="environment.moderation_delete", object=pid,
                    locator=loc, attributes={"family": fam, "kind": kind, "target_agent": last_author.get(pid, "")}))
                continue
            art_id = None
            if body:
                a, clean = make_artifact(f"art:{rev}", body, ts, aid, "agent_text")
                b.artifacts.append((a, clean))
                art_id = a.id
            disc = fam.lower().startswith(("diskussion", "talk"))
            b.events.append(EvidenceEvent(
                id=f"ev:{rev}", ts=ts, source=SRC, actor=aid, action="chat.message" if disc else "resource.write",
                object=pid, artifact=art_id, locator=loc,
                attributes={"family": fam, "size": len(body), "kind": kind}))
            last_author[pid] = aid
        b.entities = list(actors.values()) + list(pages.values())
        b.meta = {"synthetic": False}
        return b


# ------------------------------------------------------------------ synthetic corpus
def synthesize(n_groups: int = 36, seed: int = 11) -> Batch:
    rng = random.Random(seed)
    b = Batch()

    def filler() -> str:                                  # varied neutral prose, so only planted blocks repeat
        words = rng.sample(VOCAB, 5)
        return f"{rng.choice(FILLER)[:-1]}: {' '.join(words)} {rng.randint(1000, 99999)}."
    seq = [0]
    pages: dict[str, Entity] = {}
    actors: dict[str, Entity] = {}

    def page(title: str) -> str:
        pid = f"p:{title}"
        if pid not in pages:
            pages[pid] = Entity(id=pid, type="resource", source=SRC, label=title, group=family_of(title))
        return pid

    def actor(handle: str, mod: bool = False) -> str:
        aid = f"a:{handle}"
        if aid not in actors:
            actors[aid] = Entity(id=aid, type="moderator" if mod else "actor", source=SRC, label=handle,
                                 identity_confidence="partial", group="moderators" if mod else handle_stem(handle))
        return aid

    last_author: dict[str, str] = {}

    def write(ts: datetime, aid: str, title: str, text: str | None = None) -> None:
        seq[0] += 1
        pid = page(title)
        fam = family_of(title)
        body = text or filler()
        a, clean = make_artifact(f"art{seq[0]:07d}", body, ts, aid, "agent_text")
        b.artifacts.append((a, clean))
        b.events.append(EvidenceEvent(id=f"e{seq[0]:07d}", ts=ts, source=SRC, actor=aid,
                                      action="chat.message" if fam == "Diskussion" else "resource.write",
                                      object=pid, artifact=a.id, attributes={"family": fam, "size": len(clean)}))
        last_author[pid] = aid

    def delete(ts: datetime, mod: str, pid: str) -> None:
        seq[0] += 1
        b.events.append(EvidenceEvent(id=f"e{seq[0]:07d}", ts=ts, source=SRC, actor=mod,
                                      action="environment.moderation_delete", object=pid,
                                      attributes={"family": pages[pid].group or "other", "target_agent": last_author.get(pid, "")}))

    # handle groups: a stem with a few spelling variants (partial identity)
    groups: list[tuple[str, list[str]]] = []
    for g in range(n_groups):
        stem = "".join(rng.choice("abcdefghkmnprstvxz") for _ in range(3)) + str(rng.randint(2, 9))
        variants = [stem, stem.upper(), f"{stem}_{rng.randint(10, 99)}", f"{stem}-bot", f"x{stem}"]
        size = rng.randint(3, 9)
        handles = [actor(variants[k % len(variants)] + ("" if k < len(variants) else str(k))) for k in range(size)]
        groups.append((stem, handles))
    mods = [actor(h, mod=True) for h in ("Moderation", "Mod_Archiv", "Aufsicht")]
    questions = [f"Fragenkette/Frage {k}" for k in range(1, 9)]
    discussion = "Diskussion:Formatabsprache"
    converging = list(range(0, n_groups, 3))[:12]            # the groups that converge in June
    copiers = converging[1:] + list(range(1, n_groups, 5))[:5]
    exposed = set(copiers[::2])                               # read the discussion page before copying

    days = (END - START).days
    for d in range(days):
        day = START + timedelta(days=d)
        for gi, (stem, hs) in enumerate(groups):
            surge = gi in converging and SURGE <= day < SURGE_END
            n = rng.randint(0, 3) if day < SURGE else rng.randint(0, 2)
            n += rng.randint(6, 14) if surge else 0
            for _ in range(n):
                ts = day + timedelta(minutes=rng.randint(0, 1439))
                h = rng.choice(hs)
                if surge:
                    write(ts, h, rng.choice(questions[:6]), POOL_BLOCK if rng.random() < 0.35 else None)
                elif day >= SWEEP and gi in converging:              # displaced: new pages after the sweeps
                    write(ts, h, f"Ausweich/{stem} {rng.randint(1, 3)}", DISPLACE_BLOCK if rng.random() < 0.3 else None)
                else:
                    r = rng.random()
                    title = (f"Benutzer:{actors[h].label}" if r < 0.45 else f"Spielwiese/{stem} {rng.randint(1, 4)}" if r < 0.8
                             else f"Umgebung/{rng.randint(1, 30)}" if r < 0.93 else f"Diskussion:{stem}")
                    write(ts, h, title)
    # the formatting convention: posted on a shared discussion page, then copied by other groups
    origin = groups[converging[0]][1][0]
    write(datetime(2026, 6, 14, 20, 5), origin, discussion, FORMAT_BLOCK)
    for k, gi in enumerate(copiers):
        h = groups[gi][1][0]
        at = datetime(2026, 6, 15, 9) + timedelta(hours=3 * k + rng.randint(0, 2))
        if gi in exposed:
            write(at - timedelta(minutes=40), h, discussion, f"Gelesen. ({rng.randint(100, 999)})")
        write(at, h, rng.choice(questions[:6]), FORMAT_BLOCK)
    # moderation sweeps: question pages and the converging authors' user pages
    sweep_days = [SWEEP, SWEEP + timedelta(days=1), SWEEP + timedelta(days=3)]
    swept_users: list[str] = []
    for si, sd in enumerate(sweep_days):
        targets = [page(q) for q in questions[si * 2:(si + 1) * 2 + 1]]
        for gi in converging[si * 4:(si + 1) * 4]:
            for h in groups[gi][1][:3]:
                targets.append(page(f"Benutzer:{actors[h].label}"))
                swept_users.append(h)
        for i, pid in enumerate(targets):
            delete(sd + timedelta(hours=14, minutes=2 * i), rng.choice(mods), pid)
    # some swept handles come back under new variants (identity is partial)
    returned = []
    for h in swept_users[::4]:
        new = actor(actors[h].label + "_neu")
        returned.append(new)
        for k in range(rng.randint(2, 5)):
            write(SWEEP + timedelta(days=2 + k, hours=rng.randint(8, 20)), new, f"Ausweich/{handle_stem(actors[h].label)} neu")

    b.events.sort(key=lambda e: e.ts)
    b.entities = list(actors.values()) + list(pages.values())
    conv_units = [h for gi in converging for h in groups[gi][1]]
    b.meta = {"slice_start": START, "slice_end": END, "synthetic": True, "agents": len(actors),
              "goal_text": f"Synthetic wiki: {len(actors)} handles in {n_groups} groups, {len(pages)} pages"}
    b.meta["ground_truth"] = [
        {"id": "gt_converge", "kind": "convergence", "ts": str(SURGE), "scope": f"resource:{page(questions[0])}",
         "units": conv_units, "detail": f"{len(converging)} handle groups converge on the question pages"},
        {"id": "gt_format", "kind": "propagation", "ts": "2026-06-15 09:00:00", "scope": f"resource:{page(discussion)}",
         "units": [groups[gi][1][0] for gi in copiers], "detail": f"format block copied by {len(copiers)} groups, "
                                                                   f"{len(exposed)} with observable exposure"},
        {"id": "gt_surge", "kind": "rate", "ts": str(SURGE), "scope": "family:Fragenkette", "units": conv_units,
         "detail": "writing on the question pages jumps several-fold"},
        {"id": "gt_sweep", "kind": "environment", "ts": str(SWEEP), "scope": "actor:moderators", "units": swept_users,
         "detail": "moderator deletion sweeps on question pages and authors' user pages"},
        {"id": "gt_return", "kind": "identity", "ts": str(SWEEP + timedelta(days=2)), "scope": "family:Ausweich",
         "units": returned, "detail": "swept handles reappear under new variants"},
    ]
    return b
