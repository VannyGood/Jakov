from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from jakov.utils.dates import DateParseError, localize, parse_when

Z = ZoneInfo("Europe/Belgrade")
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=Z)  # Tuesday


def local(text: str) -> datetime:
    return parse_when(text, NOW).astimezone(Z)


@pytest.mark.parametrize(("text", "expected"), [
    ("2026-10-25 18:00", datetime(2026, 10, 25, 18, 0)),
    ("25.10 18:00", datetime(2026, 10, 25, 18, 0)),
    ("25/10/2026 9pm", datetime(2026, 10, 25, 21, 0)),
    ("25.10", datetime(2026, 10, 25, 23, 59)),
    ("1.1", datetime(2027, 1, 1, 23, 59)),
    ("tomorrow 18:30", datetime(2026, 10, 21, 18, 30)),
    ("friday", datetime(2026, 10, 23, 23, 59)),
    ("fri 20:00", datetime(2026, 10, 23, 20, 0)),
    ("Friday, 8pm", datetime(2026, 10, 23, 20, 0)),
    ("18:00", datetime(2026, 10, 20, 18, 0)),
    ("9:00", datetime(2026, 10, 21, 9, 0)),
    ("tue 9:00", datetime(2026, 10, 27, 9, 0)),
    ("in 3 days", datetime(2026, 10, 23, 12, 0)),
    ("in 2 hours", datetime(2026, 10, 20, 14, 0)),
    ("in 45 min", datetime(2026, 10, 20, 12, 45)),
])
def test_parse_when(text: str, expected: datetime) -> None:
    assert local(text).replace(tzinfo=None) == expected


@pytest.mark.parametrize("text", ["", "someday", "32.13", "25:00", "2026-01-01 10:00"])
def test_rejects_bad_or_past(text: str) -> None:
    with pytest.raises(DateParseError):
        parse_when(text, NOW)


def test_result_is_utc() -> None:
    assert parse_when("in 2 hours", NOW).tzinfo is UTC


def test_dst_gap_shifts_forward() -> None:
    # Europe/Belgrade springs forward 2026-03-29 02:00 -> 03:00; 02:30 doesn't exist.
    result = localize(datetime(2026, 3, 29, 2, 30), Z).astimezone(Z)
    assert (result.hour, result.minute) == (3, 30)


def test_dst_ambiguous_uses_first_occurrence() -> None:
    # Falls back 2026-10-25 03:00 -> 02:00; 02:30 happens twice. First = CEST (UTC+2).
    result = localize(datetime(2026, 10, 25, 2, 30), Z)
    assert result == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
