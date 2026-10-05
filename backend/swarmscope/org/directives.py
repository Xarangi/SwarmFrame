"""Top-down channel: Directives from the Executive (or a human) applied to the organization.

Bounded by the org config (allowed monitors, max focuses, tunable ranges) and gated by
autonomy: observe = record only; assisted = wait for human approval; auto_investigate = apply.
Human directives always apply and take precedence.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable

from swarmscope.core.models import AttentionFocus, Directive


class AttentionPolicy:
    def __init__(self) -> None:
        self.focuses: dict[str, AttentionFocus] = {}
        self.tunes: dict[str, dict[str, Any]] = {}
        self.audits: list[str] = []

    def active(self, now: datetime) -> list[AttentionFocus]:
        for k in [k for k, f in self.focuses.items() if f.expires and f.expires < now]:
            self.focuses.pop(k)
        return sorted(self.focuses.values(), key=lambda f: -f.weight)

    def table(self, now: datetime) -> list[dict[str, Any]]:
        return [f.model_dump(mode="json") for f in self.active(now)]


class DirectiveApplier:
    def __init__(self, org: dict[str, Any], policy: AttentionPolicy, *, window_len: timedelta,
                 set_monitor: Callable[[str, bool], bool], tunables: Callable[[], dict[str, dict[str, list[float]]]],
                 open_question: Callable[[str], None]):
        self.org, self.policy, self.window_len = org, policy, window_len
        self.set_monitor, self.tunables, self.open_question = set_monitor, tunables, open_question

    @property
    def autonomy(self) -> str:
        return self.org.get("autonomy", "auto_investigate")

    def submit(self, d: Directive, now: datetime) -> Directive:
        if d.set_by != "human":
            if self.autonomy == "observe":
                d.status = "proposed"
                return d
            if self.autonomy == "assisted":
                d.status = "proposed"            # waits for approve()
                return d
        return self.apply(d, now)

    def apply(self, d: Directive, now: datetime) -> Directive:
        cfg = self.org.get("executive", {}).get("directives", {})
        ttl = self.window_len * int(cfg.get("focus_ttl_windows", 18))
        try:
            if d.kind == "focus":
                if len(self.policy.focuses) >= int(cfg.get("max_active_focuses", 8)) and d.scope not in self.policy.focuses \
                        and d.set_by != "human":
                    weakest = min(self.policy.focuses.values(), key=lambda f: f.weight)
                    if weakest.weight >= float(d.payload.get("weight", 1.0)):
                        d.status = "rejected"
                        d.reason += " [attention budget full]"
                        return d
                    self.policy.focuses.pop(weakest.scope)
                prev = self.policy.focuses.get(d.scope)
                if prev and prev.set_by == "human" and d.set_by != "human":
                    d.status = "rejected"
                    d.reason += " [human focus takes precedence]"
                    return d
                self.policy.focuses[d.scope] = AttentionFocus(scope=d.scope, weight=float(d.payload.get("weight", 1.0)),
                                                              reason=d.reason, set_by=d.set_by, expires=now + ttl,
                                                              directive=d.id)
            elif d.kind == "defocus":
                self.policy.focuses.pop(d.scope, None)
            elif d.kind == "tune":
                param, value = d.payload.get("param"), d.payload.get("value")
                watcher, _, key = str(param).partition(".")
                bounds = next((b for m in self.tunables().values() for k, b in m.items() if k == param), None)
                if bounds is None or value is None:
                    d.status = "rejected"
                    d.reason += " [not a tunable parameter]"
                    return d
                value = max(bounds[0], min(bounds[1], float(value)))
                target = f"{watcher}@{d.scope}" if d.scope and d.scope != "population" else watcher
                self.policy.tunes.setdefault(target, {})[key] = value
                d.payload["applied_value"] = value
            elif d.kind in ("activate", "deactivate"):
                mon = d.payload.get("monitor") or d.scope
                allowed = cfg.get("allowed_monitors", [])
                if d.set_by != "human" and mon not in allowed:
                    d.status = "rejected"
                    d.reason += " [monitor not allowed for the Executive]"
                    return d
                if not self.set_monitor(mon, d.kind == "activate"):
                    d.status = "rejected"
                    d.reason += " [monitor unavailable for this source]"
                    return d
            elif d.kind == "audit":
                self.policy.audits.append(d.scope or "population")
            elif d.kind == "ask":
                if d.payload.get("question"):
                    self.open_question(d.payload["question"])
            d.status = "applied"
        except Exception as exc:
            d.status = "rejected"
            d.reason += f" [{exc}]"
        return d
