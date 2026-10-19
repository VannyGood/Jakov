"""Schedules as data: build from the wizard, compute runs, apply limits, describe."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from jakov.db.models import Schedule
from jakov.engine.recurrence import Recurrence, describe, format_interval
from jakov.utils.time import format_local


class ScheduleError(ValueError):
    """Shown to the admin as-is."""


@dataclass(slots=True)
class ScheduleSpec:
    """What the schedule wizard collects (stored in FSM data as a dict)."""

    chat_pk: int = 0
    kind: str = ""                    # once | daily | interval
    run_at: str | None = None         # ISO UTC (once)
    time_of_day: str | None = None    # "HH:MM" (daily)
    interval_minutes: int | None = None
    anchor_at: str | None = None      # ISO UTC (interval first run)
    limit_kind: str = "forever"       # forever | count | until
    limit_count: int | None = None
    until_at: str | None = None       # ISO UTC
    rotate: bool = False
    require_approval: bool = False
    timezone: str = "UTC"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ScheduleSpec:
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in (data or {}).items() if k in known})

    def recurrence(self) -> Recurrence:
        zone = ZoneInfo(self.timezone)
        if self.kind == "once":
            return Recurrence("once", zone, run_at=_dt(self.run_at))
        if self.kind == "daily":
            return Recurrence("daily", zone, time_of_day=_clock(self.time_of_day))
        if self.kind == "interval":
            return Recurrence("interval", zone,
                              interval=timedelta(minutes=self.interval_minutes or 0),
                              anchor=_dt(self.anchor_at))
        raise ScheduleError("Pick how often to post first.")

    def until(self) -> datetime | None:
        return _dt(self.until_at) if self.limit_kind == "until" and self.until_at else None


def _dt(value: str | None) -> datetime:
    if not value:
        raise ScheduleError("A date is missing.")
    return datetime.fromisoformat(value)


def _clock(value: str | None) -> time:
    if not value:
        raise ScheduleError("A time is missing.")
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def recurrence_of(schedule: Schedule) -> Recurrence:
    return spec_of(schedule).recurrence()


def spec_of(schedule: Schedule) -> ScheduleSpec:
    return ScheduleSpec(
        chat_pk=schedule.chat_id, kind=schedule.kind,
        run_at=schedule.run_at.isoformat() if schedule.run_at else None,
        time_of_day=schedule.time_of_day, interval_minutes=schedule.interval_minutes,
        anchor_at=schedule.anchor_at.isoformat() if schedule.anchor_at else None,
        limit_kind=schedule.limit_kind, limit_count=schedule.limit_count,
        until_at=schedule.until_at.isoformat() if schedule.until_at else None,
        rotate=schedule.rotate, require_approval=schedule.require_approval,
        timezone=schedule.timezone)


def within_limits(schedule: Schedule, candidate: datetime | None, pending: int = 0
                  ) -> datetime | None:
    """`candidate` if the schedule may still run then, else None."""
    if candidate is None:
        return None
    if schedule.limit_kind == "until" and schedule.until_at and candidate > schedule.until_at:
        return None
    if schedule.limit_kind == "count" and schedule.limit_count is not None \
            and schedule.sent_count + pending >= schedule.limit_count:
        return None
    return candidate


def apply_spec(schedule: Schedule, spec: ScheduleSpec, now: datetime) -> None:
    """Copy the wizard's choices onto a schedule and compute its first run."""
    rec = spec.recurrence()
    schedule.chat_id = spec.chat_pk
    schedule.kind = spec.kind
    schedule.timezone = spec.timezone
    schedule.run_at = _dt(spec.run_at) if spec.kind == "once" else None
    schedule.time_of_day = spec.time_of_day if spec.kind == "daily" else None
    schedule.interval_minutes = spec.interval_minutes if spec.kind == "interval" else None
    schedule.anchor_at = _dt(spec.anchor_at) if spec.kind == "interval" else None
    schedule.limit_kind = "forever" if spec.kind == "once" else spec.limit_kind
    schedule.limit_count = spec.limit_count if schedule.limit_kind == "count" else None
    schedule.until_at = spec.until() if schedule.limit_kind == "until" else None
    schedule.rotate = spec.rotate
    schedule.require_approval = spec.require_approval
    first = rec.first_run(now)
    if first is not None and first < now - timedelta(minutes=1) and spec.kind == "once":
        raise ScheduleError("That time is in the past.")
    schedule.next_run_at = within_limits(schedule, first)
    if schedule.next_run_at is None:
        raise ScheduleError("With these settings the schedule would never run.")
    schedule.status = "active"
    schedule.paused_reason = None


def timing_text(spec_or_schedule: ScheduleSpec | Schedule, zone: ZoneInfo) -> str:
    spec = spec_or_schedule if isinstance(spec_or_schedule, ScheduleSpec) \
        else spec_of(spec_or_schedule)
    rec = spec.recurrence()
    if rec.kind == "once":
        assert rec.run_at is not None
        return describe(rec, format_local(rec.run_at, zone))
    text = describe(rec)
    if rec.kind == "interval" and rec.anchor is not None:
        text += f", starting {format_local(rec.anchor, zone)}"
    return text


def limit_text(spec_or_schedule: ScheduleSpec | Schedule, zone: ZoneInfo) -> str:
    if isinstance(spec_or_schedule, ScheduleSpec):
        spec = spec_or_schedule
        if spec.kind == "once":
            return "one post"
        if spec.limit_kind == "count":
            return f"{spec.limit_count} times, then stop"
        if spec.limit_kind == "until" and spec.until_at:
            return f"until {format_local(_dt(spec.until_at), zone)}"
        return "forever"
    sch = spec_or_schedule
    if sch.kind == "once":
        return "one post"
    if sch.limit_kind == "count":
        return f"{sch.limit_count} times ({sch.sent_count} sent)"
    if sch.limit_kind == "until" and sch.until_at:
        return f"until {format_local(sch.until_at, zone)}"
    return "forever"


def interval_label(minutes: int) -> str:
    return format_interval(timedelta(minutes=minutes))
