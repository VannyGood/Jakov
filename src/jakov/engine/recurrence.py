"""When does a schedule run next? Pure functions, all inputs and outputs in UTC.

DST rules (via utils.dates.localize): a daily time that doesn't exist on a given day
(spring-forward gap) runs at the shifted-forward wall time; an ambiguous one (fall-back)
runs once, at the first occurrence. Interval schedules count real elapsed time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from jakov.utils.dates import localize, parse_clock

Kind = Literal["once", "daily", "interval"]


@dataclass(frozen=True, slots=True)
class Recurrence:
    kind: Kind
    zone: ZoneInfo
    run_at: datetime | None = None          # once
    time_of_day: time | None = None         # daily
    interval: timedelta | None = None       # interval
    anchor: datetime | None = None          # interval: the first run

    def __post_init__(self) -> None:
        if self.kind == "once" and self.run_at is None:
            raise ValueError("once needs run_at")
        if self.kind == "daily" and self.time_of_day is None:
            raise ValueError("daily needs time_of_day")
        if self.kind == "interval" and (self.interval is None or self.anchor is None
                                        or self.interval <= timedelta(0)):
            raise ValueError("interval needs a positive interval and an anchor")

    def first_run(self, now: datetime) -> datetime | None:
        """The first run at or after `now` (a once-run in the past still counts: it's due)."""
        if self.kind == "once":
            return self.run_at
        if self.kind == "interval":
            assert self.anchor is not None
            return self.anchor if self.anchor >= now else self.next_after(now)
        return self.next_after(now - timedelta(microseconds=1))

    def next_after(self, after: datetime) -> datetime | None:
        """The first run strictly after `after`, or None if there are no more."""
        if self.kind == "once":
            assert self.run_at is not None
            return self.run_at if self.run_at > after else None
        if self.kind == "interval":
            assert self.anchor is not None and self.interval is not None
            if after < self.anchor:
                return self.anchor
            steps = (after - self.anchor) // self.interval + 1
            return self.anchor + steps * self.interval
        assert self.time_of_day is not None
        day = after.astimezone(self.zone).date()
        for offset in range(0, 3):
            candidate = localize(datetime.combine(day + timedelta(days=offset),
                                                  self.time_of_day), self.zone)
            if candidate > after:
                return candidate
        raise AssertionError("unreachable: a daily time always recurs within 3 days")

    def upcoming(self, now: datetime, count: int) -> list[datetime]:
        runs: list[datetime] = []
        cursor = self.first_run(now)
        while cursor is not None and len(runs) < count:
            runs.append(cursor)
            cursor = self.next_after(cursor)
        return runs


def describe(rec: Recurrence, fmt_moment: str | None = None) -> str:
    """'Once', 'Every day at 09:00', 'Every 3 hours', 'Every 90 minutes'."""
    if rec.kind == "once":
        return f"Once{f', {fmt_moment}' if fmt_moment else ''}"
    if rec.kind == "daily":
        assert rec.time_of_day is not None
        return f"Every day at {rec.time_of_day.strftime('%H:%M')}"
    assert rec.interval is not None
    return f"Every {format_interval(rec.interval)}"


def format_interval(interval: timedelta) -> str:
    minutes = int(interval.total_seconds() // 60)
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours} h {mins} min"
    if hours:
        return "hour" if hours == 1 else f"{hours} hours"
    return "minute" if mins == 1 else f"{mins} minutes"


def parse_interval(text: str) -> timedelta | None:
    """'90m', '90 min', '4h', '2h30m', '1.5h', '45' (minutes) -> timedelta."""
    raw = text.strip().lower().replace(" ", "")
    if m := re.fullmatch(r"(\d+(?:\.\d+)?)(h|hr|hrs|hour|hours)", raw):
        return timedelta(minutes=round(float(m.group(1)) * 60))
    if m := re.fullmatch(r"(\d+)h(\d+)(m|min|mins|minutes)?", raw):
        return timedelta(hours=int(m.group(1)), minutes=int(m.group(2)))
    if m := re.fullmatch(r"(\d+)(m|min|mins|minute|minutes)?", raw):
        return timedelta(minutes=int(m.group(1)))
    return None


def parse_time_of_day(text: str) -> time | None:
    """'9', '09:30', '21.00', '9pm', '9:15 am' -> time."""
    return parse_clock(text.strip().lower())
