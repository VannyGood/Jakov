import itertools
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from jakov.engine.recurrence import (
    Recurrence,
    describe,
    format_interval,
    parse_interval,
    parse_time_of_day,
)

BEL = ZoneInfo("Europe/Belgrade")
BEIRUT = ZoneInfo("Asia/Beirut")


def u(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_once() -> None:
    rec = Recurrence("once", BEL, run_at=u(2026, 10, 21, 10))
    assert rec.first_run(u(2026, 10, 20)) == u(2026, 10, 21, 10)
    assert rec.next_after(u(2026, 10, 21, 10)) is None
    assert rec.first_run(u(2026, 10, 22)) == u(2026, 10, 21, 10)  # overdue still reported


def test_daily_in_local_time() -> None:
    rec = Recurrence("daily", BEIRUT, time_of_day=time(9, 0))  # UTC+3 in October
    assert rec.next_after(u(2026, 10, 20, 5)) == u(2026, 10, 20, 6)
    assert rec.next_after(u(2026, 10, 20, 6)) == u(2026, 10, 21, 6)  # strictly after
    assert rec.first_run(u(2026, 10, 20, 6)) == u(2026, 10, 20, 6)   # at-or-after


def test_daily_spring_forward_gap_shifts_forward() -> None:
    # Belgrade: 2026-03-29 02:00 -> 03:00. 02:30 doesn't exist that day.
    rec = Recurrence("daily", BEL, time_of_day=time(2, 30))
    run = rec.next_after(u(2026, 3, 28, 12))
    assert run is not None
    local = run.astimezone(BEL)
    assert (local.day, local.hour, local.minute) == (29, 3, 30)
    following = rec.next_after(run)
    assert following is not None and following.astimezone(BEL).hour == 2  # normal again


def test_daily_fall_back_runs_once_at_first_occurrence() -> None:
    # Belgrade: 2026-10-25 03:00 -> 02:00. 02:30 happens twice.
    rec = Recurrence("daily", BEL, time_of_day=time(2, 30))
    first = rec.next_after(u(2026, 10, 24, 12))
    assert first == u(2026, 10, 25, 0, 30)  # 02:30 CEST (UTC+2)
    second = rec.next_after(first)
    assert second is not None and second.astimezone(BEL).day == 26  # not again at 02:30 CET


def test_daily_runs_are_24h_apart_except_across_dst() -> None:
    rec = Recurrence("daily", BEL, time_of_day=time(9, 0))
    runs = rec.upcoming(u(2026, 10, 23), 4)
    gaps = [b - a for a, b in itertools.pairwise(runs)]
    assert gaps == [timedelta(hours=24), timedelta(hours=25), timedelta(hours=24)]


def test_interval_counts_real_time() -> None:
    anchor = u(2026, 10, 20, 10)
    rec = Recurrence("interval", BEL, interval=timedelta(hours=3), anchor=anchor)
    assert rec.first_run(u(2026, 10, 20, 9)) == anchor
    assert rec.next_after(anchor) == u(2026, 10, 20, 13)
    assert rec.next_after(u(2026, 10, 20, 14, 1)) == u(2026, 10, 20, 16)
    assert rec.first_run(u(2026, 10, 20, 14)) == u(2026, 10, 20, 16)
    # Across a DST change the gap stays exactly 3 h.
    runs = Recurrence("interval", BEL, interval=timedelta(hours=3),
                      anchor=u(2026, 10, 24, 22)).upcoming(u(2026, 10, 24), 4)
    assert all(b - a == timedelta(hours=3) for a, b in itertools.pairwise(runs))


def test_invalid_recurrences() -> None:
    with pytest.raises(ValueError):
        Recurrence("interval", BEL, interval=timedelta(0), anchor=u(2026, 1, 1))
    with pytest.raises(ValueError):
        Recurrence("daily", BEL)


@pytest.mark.parametrize(("text", "minutes"), [
    ("90m", 90), ("90 min", 90), ("4h", 240), ("2h30m", 150), ("1.5h", 90), ("45", 45),
    ("2 hours", 120)])
def test_parse_interval(text: str, minutes: int) -> None:
    assert parse_interval(text) == timedelta(minutes=minutes)


def test_parse_interval_rejects() -> None:
    assert parse_interval("soon") is None


def test_parse_time_and_describe() -> None:
    assert parse_time_of_day("9pm") == time(21, 0)
    assert parse_time_of_day("07:45") == time(7, 45)
    assert parse_time_of_day("25:00") is None
    assert describe(Recurrence("daily", BEL, time_of_day=time(9, 5))) == "Every day at 09:05"
    assert format_interval(timedelta(minutes=90)) == "1 h 30 min"
    assert format_interval(timedelta(hours=1)) == "hour"
    assert format_interval(timedelta(hours=6)) == "6 hours"
