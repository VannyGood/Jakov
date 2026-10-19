"""Parse human date/time input in the admin's timezone and localize with DST rules."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class DateParseError(ValueError):
    pass


def localize(naive: datetime, zone: ZoneInfo) -> datetime:
    """Attach `zone` to a wall-clock time and return it in UTC.

    DST rules: a wall time that doesn't exist (spring-forward gap) shifts forward by the
    gap; an ambiguous one (fall-back overlap) uses the first occurrence. Python's
    fold=0 gives exactly that: it applies the pre-transition offset.
    """
    return naive.replace(tzinfo=zone, fold=0).astimezone(UTC)


def parse_clock(text: str) -> time | None:
    m = re.fullmatch(r"(\d{1,2})(?::|\.|h)?(\d{2})?\s*(am|pm)?", text.strip())
    if not m:
        return None
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ampm:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if ampm == "pm" else 0)
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def _parse_date(text: str, today: date) -> date | None:
    try:
        return _parse_date_unchecked(text.strip(), today)
    except ValueError:  # e.g. 31.02 or 32.13
        return None


def _parse_date_unchecked(text: str, today: date) -> date | None:
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text):
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if m := re.fullmatch(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?", text):
        day, month = int(m.group(1)), int(m.group(2))
        if m.group(3):
            year = int(m.group(3))
            year += 2000 if year < 100 else 0
            return date(year, month, day)
        candidate = date(today.year, month, day)
        return candidate if candidate >= today else date(today.year + 1, month, day)
    if text == "today":
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)
    if (weekday := weekday_index(text)) is not None:
        return today + timedelta(days=(weekday - today.weekday()) % 7)
    return None


def weekday_index(text: str) -> int | None:
    """'fri', 'friday' -> 4."""
    if len(text) < 3:
        return None
    return next((i for i, name in enumerate(WEEKDAYS) if name.startswith(text)), None)


def parse_when(text: str, now_local: datetime) -> datetime:
    """Return an aware UTC datetime in the future.

    Accepts: '2026-10-25 18:00', '25.10', '25/10/2026 9pm', 'tomorrow 18:00', 'friday',
    'fri 20:00', '18:00' (today, or tomorrow if passed), 'in 3 days', 'in 2 hours',
    'in 45 minutes'. Dates without a time default to 23:59 for deadlines.
    """
    zone = now_local.tzinfo
    if not isinstance(zone, ZoneInfo):
        raise DateParseError("internal: timezone missing")
    raw = " ".join(text.lower().replace(",", " ").split())
    if not raw:
        raise DateParseError("Empty date.")

    if m := re.fullmatch(r"in (\d{1,4}) ?(minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|w)", raw):
        amount, unit = int(m.group(1)), m.group(2)[0]
        delta = {"m": timedelta(minutes=amount), "h": timedelta(hours=amount),
                 "d": timedelta(days=amount), "w": timedelta(weeks=amount)}[unit]
        return (now_local + delta).astimezone(UTC)

    parts = raw.split(" ")
    clock: time | None = None
    day: date | None = None
    if len(parts) >= 2 and (clock := parse_clock(" ".join(parts[1:]))):
        day = _parse_date(parts[0], now_local.date())
    elif len(parts) >= 2 and (clock := parse_clock(parts[-1])):
        day = _parse_date(" ".join(parts[:-1]), now_local.date())
    elif len(parts) == 1 and (day := _parse_date(raw, now_local.date())):
        clock = time(23, 59)
    elif clock := parse_clock(raw):
        day = now_local.date()
        if datetime.combine(day, clock) <= now_local.replace(tzinfo=None):
            day += timedelta(days=1)

    if day is None or clock is None:
        raise DateParseError(
            "I couldn't read that date. Try e.g. 'friday 20:00', '25.12 18:00', "
            "'tomorrow 9am' or 'in 3 days'."
        )
    result = localize(datetime.combine(day, clock), zone)
    day_word = parts[0] if len(parts) > 1 else raw
    if result <= now_local.astimezone(UTC) and weekday_index(day_word) is not None:
        # "friday 9:00" said on Friday at noon means next Friday.
        result = localize(datetime.combine(day + timedelta(days=7), clock), zone)
    if result <= now_local.astimezone(UTC):
        raise DateParseError("That time is in the past.")
    return result
