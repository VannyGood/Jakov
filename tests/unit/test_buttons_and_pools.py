import random

from jakov.engine.pools import next_pick
from jakov.utils.buttons import parse_buttons


def test_parse_button_formats() -> None:
    buttons, errors = parse_buttons(
        "Join - https://t.me/group\nShop | https://shop.example.com/x?y=1\nOpen https://a.io",
        6)
    assert errors == []
    assert [b["text"] for b in buttons] == ["Join", "Shop", "Open"]
    assert buttons[1]["url"] == "https://shop.example.com/x?y=1"


def test_button_errors() -> None:
    buttons, errors = parse_buttons("No url here\nBad - https://nodot\n - https://x.io", 6)
    assert buttons == [] and len(errors) == 3


def test_button_limit() -> None:
    text = "\n".join(f"B{i} - https://x{i}.io" for i in range(8))
    buttons, errors = parse_buttons(text, 6)
    assert len(buttons) == 6 and "At most 6" in errors[-1]


def test_javascript_urls_rejected() -> None:
    buttons, errors = parse_buttons("x - javascript://alert(1)", 6)
    assert buttons == [] and errors


def test_pool_never_repeats_until_exhausted() -> None:
    rng = random.Random(5)
    used: list[int] = []
    seen = []
    for _ in range(5):
        index, used = next_pick(5, used, rng)
        seen.append(index)
    assert sorted(seen) == [0, 1, 2, 3, 4]


def test_new_cycle_does_not_start_with_last_item() -> None:
    rng = random.Random(1)
    for _ in range(50):
        used = [0, 1, 2]
        index, new_used = next_pick(3, used, rng)
        assert index != 2 and new_used == [index]


def test_pool_ignores_stale_indices() -> None:
    index, used = next_pick(2, [7, 9], random.Random(0))
    assert index in (0, 1) and used == [index]
