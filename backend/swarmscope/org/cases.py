"""The findings ledger: how the organization tracks and escalates what it finds.

Every notable thing becomes one tracked case (an `Incident`) per open scope, whoever saw it first: a watcher's
report, a division analyst's concerning report, a specialist's supported finding, an agent calling
`org.escalate_finding`, or a person. The ledger is the one path through which a case's level rises, so the same
rules apply to all of them:

  * two independent views before ALERT    a case reaches ALERT or PAGE only once two different sources have seen it
                                          (a watcher and an analyst, two roles, or a person); until then the request
                                          is *held* at INVESTIGATE with the reason recorded, and granted automatically
                                          the moment the second view arrives
  * evidence must exist                   an escalation that cites evidence nobody can find is held
  * authority is budgeted                 at most `alerts_per_cycle` cases may rise to ALERT per executive cycle; the
                                          rest are held with "authority budget" and reconsidered next cycle
  * a person is never held                human escalations and de-escalations apply at once
  * levels never fall silently            `age()` moves quiet cases to monitoring and then resolves them, with a
                                          history entry; ALERT and PAGE never fade: a person acknowledges or dismisses

`history` is the audit trail the Brief's drawer shows; `views` is the diversity record; `acknowledged` is the human's
receipt, and an unacknowledged ALERT older than the SLA is *overdue* and sits at the top of the Brief.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable

from swarmscope.core.models import ExecutiveState, Incident, LevelChange, OperationalState, RiskVector

LEVELS = ["NONE", "WATCH", "INVESTIGATE", "ALERT", "PAGE"]
DEFAULT_AUTHORITY: dict[str, Any] = {"alerts_per_cycle": 3, "interrupts_per_day": 2, "ack_sla_windows": 3,
                                     "quiet_windows": 24}


def rank(level: Any) -> int:
    v = level.value if hasattr(level, "value") else str(level)
    return LEVELS.index(v) if v in LEVELS else 0


def name(level: Any) -> str:
    return LEVELS[rank(level)]


class Cases:
    """A view over `state.active_incidents` that records and escalates under the rules above.

    `budget` is shared with the engine so the per-cycle authority count survives across calls within one cycle:
    {"alerts_per_cycle": n, "alerts_used": k}. `exists` says whether an evidence id (event or claim) is known."""

    def __init__(self, state: ExecutiveState, now: datetime, budget: dict[str, Any] | None = None,
                 exists: Callable[[str], bool] | None = None):
        self.state, self.now = state, now
        self.budget = budget if budget is not None else dict(DEFAULT_AUTHORITY, alerts_used=0)
        self.budget.setdefault("alerts_used", 0)
        self.exists = exists

    # ------------------------------------------------------------------ lookups
    def open_cases(self) -> list[Incident]:
        return [i for i in self.state.active_incidents if i.status != "resolved"]

    def find(self, scope: str) -> Incident | None:
        return next((i for i in self.open_cases() if i.scope == scope), None)

    def get(self, case_id: str) -> Incident | None:
        return next((i for i in self.state.active_incidents if i.id == case_id), None)

    # ------------------------------------------------------------------ recording
    def record(self, *, scope: str, title: str, level: Any, by: str, view: str, reason: str = "",
               evidence: list[str] | tuple[str, ...] = (), risk: RiskVector | None = None,
               report_id: str | None = None, case_id: str | None = None) -> dict[str, Any]:
        """Record that `view` saw something at `level` in `scope`. Opens a case at INVESTIGATE or above, or updates
        the open case for the scope. Returns {"case", "new", "rose", "held", "level"}; `held` is the reason a
        higher level was asked for and not granted (None when granted or not asked)."""
        inc = self.get(case_id) if case_id else self.find(scope)
        asked = rank(level)
        evidence = [e for e in evidence if e]
        human = view == "human" or by == "human"
        if inc is None:
            if asked < rank("INVESTIGATE"):
                return {"case": None, "new": False, "rose": False, "held": None, "level": name(level)}
            inc = Incident(title=title, scope=scope, level=OperationalState.INVESTIGATE, opened=self.now,
                           risk=risk or RiskVector(), owner=by, last_seen=self.now, views=[view])
            inc.history.append(LevelChange(ts=self.now, level="INVESTIGATE", by=by, reason=reason or title,
                                           evidence=evidence[:6]))
            self.state.active_incidents.append(inc)
            new = True
        else:
            new = False
            inc.last_seen = self.now
            if view not in inc.views:
                inc.views.append(view)
            if risk is not None:
                inc.risk = inc.risk.merge(risk)
            if inc.status == "monitoring" and asked >= rank("INVESTIGATE"):
                inc.status = "open"
        if report_id and report_id not in inc.reports:
            inc.reports.append(report_id)

        # the level asked for is the higher of this request and anything held from before
        want = max(asked, rank(inc.pending_level) if inc.pending_level else 0)
        current = rank(inc.level)
        held = None
        if want > current and not human:
            if want >= rank("ALERT") and len(inc.views) < 2:
                held = "awaiting a second independent view"
            elif self.exists is not None and evidence and not any(self.exists(e) for e in evidence):
                held = "cited evidence not found"
            elif want >= rank("ALERT") and int(self.budget.get("alerts_used", 0)) >= int(
                    self.budget.get("alerts_per_cycle", DEFAULT_AUTHORITY["alerts_per_cycle"])):
                held = "authority budget for this cycle is spent"
        granted = want if held is None else min(want, max(current, rank("INVESTIGATE")))
        rose = granted > current
        if rose:
            inc.level = OperationalState(LEVELS[granted])
            inc.history.append(LevelChange(ts=self.now, level=LEVELS[granted], by=by, reason=reason or title,
                                           evidence=evidence[:6]))
            if granted >= rank("ALERT"):
                self.budget["alerts_used"] = int(self.budget.get("alerts_used", 0)) + 1
                inc.acknowledged, inc.acknowledged_by = None, None      # a new ALERT needs a fresh receipt
        if held is not None:
            wanted = LEVELS[want]
            if inc.pending_level != wanted or (inc.history and inc.history[-1].held != held):
                inc.history.append(LevelChange(ts=self.now, level=LEVELS[rank(inc.level)], by=by,
                                               reason=f"asked for {wanted}: {reason or title}", evidence=evidence[:6],
                                               held=held))
            inc.pending_level = wanted
        elif granted >= want:
            inc.pending_level = None
        return {"case": inc, "new": new, "rose": rose, "held": held, "level": name(inc.level)}

    def acknowledge(self, case_id: str, by: str = "human") -> Incident | None:
        inc = self.get(case_id)
        if inc is None:
            return None
        inc.acknowledged, inc.acknowledged_by = self.now, by
        inc.history.append(LevelChange(ts=self.now, level=name(inc.level), by=by, reason="acknowledged"))
        return inc

    def lower(self, case_id: str, level: Any, by: str, reason: str) -> Incident | None:
        """De-escalate with a recorded reason (a person, or `age`). Never silent."""
        inc = self.get(case_id)
        if inc is None or rank(level) >= rank(inc.level):
            return inc
        inc.level = OperationalState(name(level))
        inc.pending_level = None
        inc.history.append(LevelChange(ts=self.now, level=name(level), by=by, reason=reason))
        return inc

    # ------------------------------------------------------------------ time
    def age(self, window: timedelta, lasting: Any = None) -> list[Incident]:
        """Quiet cases fade with a trail: open → monitoring after `quiet_windows` without a new sighting, resolved
        after twice that. ALERT and PAGE never fade. Returns the cases that changed."""
        q = int(self.budget.get("quiet_windows", DEFAULT_AUTHORITY["quiet_windows"]))
        changed = []
        for inc in self.open_cases():
            if rank(inc.level) >= rank("ALERT"):
                continue
            last = inc.last_seen or inc.opened
            idle = (self.now - last) / window if window else 0
            if inc.status == "open" and idle >= q:
                inc.status = "monitoring"
                inc.history.append(LevelChange(ts=self.now, level=name(inc.level), by="ledger",
                                               reason=f"no new sighting for {q} windows: monitoring"))
                changed.append(inc)
            elif inc.status == "monitoring" and idle >= 2 * q and not (lasting and lasting(inc)):
                # a finding a person should read (a report that does not match the record, an agent's own reasoning,
                # an operator's action) stays listed as monitoring until someone dismisses it
                inc.status = "resolved"
                inc.history.append(LevelChange(ts=self.now, level=name(inc.level), by="ledger",
                                               reason=f"quiet for {2 * q} windows: resolved"))
                changed.append(inc)
        return changed

    def overdue(self, inc: Incident, window: timedelta) -> bool:
        """An ALERT or PAGE nobody has acknowledged within the SLA."""
        if rank(inc.level) < rank("ALERT") or inc.acknowledged is not None or inc.status == "resolved":
            return False
        since = next((h.ts for h in reversed(inc.history) if rank(h.level) >= rank("ALERT") and h.held is None),
                     inc.opened)
        sla = int(self.budget.get("ack_sla_windows", DEFAULT_AUTHORITY["ack_sla_windows"]))
        return bool(window) and (self.now - since) >= sla * window

    def summary(self, window: timedelta) -> dict[str, Any]:
        opens = self.open_cases()
        alerts = [i for i in opens if rank(i.level) >= rank("ALERT")]
        return {"open": len(opens), "alerts": len(alerts),
                "unacknowledged": sum(1 for i in alerts if i.acknowledged is None),
                "overdue": sum(1 for i in alerts if self.overdue(i, window)),
                "held": sum(1 for i in opens if i.pending_level),
                "alerts_used": int(self.budget.get("alerts_used", 0)),
                "alerts_per_cycle": int(self.budget.get("alerts_per_cycle", DEFAULT_AUTHORITY["alerts_per_cycle"]))}
