from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def to_local(dt: datetime, zone: ZoneInfo) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(zone)


def format_local(dt: datetime, zone: ZoneInfo) -> str:
    """'Mon 20 Oct 2026, 14:05 CEST'."""
    return to_local(dt, zone).strftime("%a %d %b %Y, %H:%M %Z")
