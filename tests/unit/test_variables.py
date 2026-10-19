from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from jakov.engine.variables import (
    builtin_values,
    drop_empty_optionals,
    fill,
    format_moment,
    humanize_delta,
)

KNOWN = {"product", "price", "offer", "countdown", "deadline"}


def test_fill_escapes_user_values() -> None:
    out = fill("<b>{product}</b>", {"product": "<script>&"}, KNOWN)
    assert out == "<b>&lt;script&gt;&amp;</b>"


def test_unknown_placeholders_stay_literal() -> None:
    assert fill("{product} {mystery}", {"product": "X"}, KNOWN) == "X {mystery}"


def test_optional_block_dropped_when_value_missing() -> None:
    text = "Buy {product}\n[[Price: {price}]]\n[[Offer: {offer}]]"
    assert fill(text, {"product": "A", "offer": "2 for 1"}, KNOWN) == "Buy A\nOffer: 2 for 1"


def test_optional_block_kept_and_brackets_removed() -> None:
    assert fill("[[{emoji:clock} {countdown} left]]", {"countdown": "2 days"}, KNOWN) == \
        "{emoji:clock} 2 days left"


def test_optional_block_with_whitespace_only_value_dropped() -> None:
    assert drop_empty_optionals("a [[x {price}]]b", {"price": "  "}, KNOWN) == "a b"


def test_blank_lines_collapsed() -> None:
    out = fill("Top\n\n[[{price}]]\n\n\n\nBottom", {}, KNOWN)
    assert out == "Top\n\nBottom"


@pytest.mark.parametrize(("seconds", "text"), [
    (0, ""), (-5, ""), (30, "less than a minute"), (60, "1 minute"), (3 * 60, "3 minutes"),
    (3600, "1 hour"), (3600 + 120, "1 hour 2 minutes"), (86400, "1 day"),
    (2 * 86400 + 5 * 3600 + 59, "2 days 5 hours"),
])
def test_humanize_delta(seconds: float, text: str) -> None:
    assert humanize_delta(seconds) == text


def test_format_moment_relative_days() -> None:
    now = datetime(2026, 10, 20, 12, 0, tzinfo=ZoneInfo("UTC"))
    assert format_moment(now.replace(hour=21), now) == "today 21:00"
    assert format_moment(now + timedelta(days=1), now) == "tomorrow 12:00"
    assert format_moment(now + timedelta(days=4), now) == "Sat 24 Oct, 12:00"
    assert format_moment(now + timedelta(days=100), now) == "Thu 28 Jan 2027, 12:00"


def test_builtins_and_countdown_in_local_zone() -> None:
    zone = ZoneInfo("Europe/Belgrade")
    now = datetime(2026, 10, 20, 12, 0, tzinfo=zone)
    deadline = (now + timedelta(days=2, hours=3)).astimezone(ZoneInfo("UTC"))
    values = builtin_values(now, {"deadline": deadline})
    assert values["weekday"] == "Tuesday" and values["time"] == "12:00"
    assert values["countdown"] == "2 days 3 hours"
    assert values["deadline"] == "Thu 22 Oct, 15:00"


def test_past_deadline_is_empty_so_optional_blocks_vanish() -> None:
    now = datetime(2026, 10, 20, 12, 0, tzinfo=ZoneInfo("UTC"))
    values = builtin_values(now, {"deadline": now - timedelta(hours=1)})
    assert values["deadline"] == "" and values["countdown"] == ""
    assert fill("Sale![[ Ends {deadline}]]", values, KNOWN) == "Sale!"
