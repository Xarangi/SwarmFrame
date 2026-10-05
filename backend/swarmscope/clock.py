"""One clock drives replay and live monitoring, so monitors and UI agree on "now"."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from swarmscope.core.models import TimeWindow


class Clock(Protocol):
    live: bool
    speed: float
    paused: bool

    def now(self) -> datetime: ...
    def next_window(self) -> TimeWindow | None: ...
    def describe(self) -> dict: ...


class ReplayClock:
    """Steps through fixed windows of a recorded corpus. `speed` is windows per real second."""
    live = False

    def __init__(self, start: datetime, end: datetime, window: timedelta, *, speed: float = 2.0,
                 nonempty: list[datetime] | None = None):
        self.start, self.end, self.window = start, end, window
        self.speed = speed
        self.paused = True
        self.skip_gaps = True                  # fast-forward over stretches with no events (nights, weekends)
        self.catching_up: dict | None = None
        self.cursor = start
        self.index = 0
        # sorted event timestamps; lets us skip empty stretches (nights, weekends)
        self._ts = nonempty or []
        self._ti = 0

    def now(self) -> datetime:
        return self.cursor

    def next_window(self) -> TimeWindow | None:
        if self.cursor >= self.end:
            return None
        while self._ti < len(self._ts) and self._ts[self._ti] <= self.cursor:
            self._ti += 1
        if self.skip_gaps and self._ts and self._ti < len(self._ts) and self._ts[self._ti] > self.cursor + self.window * 3:
            # fast-forward to the window containing the next event
            gap = (self._ts[self._ti] - self.cursor) // self.window
            self.cursor += self.window * max(0, gap)
        w = TimeWindow(start=self.cursor, end=min(self.cursor + self.window, self.end), index=self.index)
        self.cursor = w.end
        self.index += 1
        return w

    def seek(self, ts: datetime) -> None:
        self.cursor = max(self.start, min(ts, self.end))
        self._ti = 0

    @property
    def time_scale(self) -> float:
        """Simulated seconds per real second."""
        return self.speed * self.window.total_seconds()

    def set_time_scale(self, scale: float) -> None:
        self.speed = max(1e-4, min(60.0, scale / self.window.total_seconds()))

    @property
    def progress(self) -> float:
        total = (self.end - self.start).total_seconds() or 1
        return max(0.0, min(1.0, (self.cursor - self.start).total_seconds() / total))

    def describe(self) -> dict:
        return {"live": False, "now": self.cursor, "start": self.start, "end": self.end, "speed": self.speed,
                "paused": self.paused, "window_s": self.window.total_seconds(), "progress": self.progress,
                "index": self.index, "done": self.cursor >= self.end, "time_scale": self.time_scale,
                "skip_gaps": self.skip_gaps, "catching_up": self.catching_up}


class WallClock:
    """Live monitoring: windows close on real time."""
    live = True

    def __init__(self, window: timedelta = timedelta(seconds=10)):
        self.window = window
        self.speed = 1.0 / window.total_seconds()
        self.paused = False
        self.start = datetime.utcnow()
        self._last = self.start
        self.index = 0

    def now(self) -> datetime:
        return datetime.utcnow()

    def next_window(self) -> TimeWindow | None:
        now = datetime.utcnow()
        w = TimeWindow(start=self._last, end=now, index=self.index)
        self._last = now
        self.index += 1
        return w

    def describe(self) -> dict:
        return {"live": True, "now": self.now(), "start": self.start, "end": None, "speed": 1.0,
                "paused": self.paused, "window_s": self.window.total_seconds(), "progress": None,
                "index": self.index, "done": False}
