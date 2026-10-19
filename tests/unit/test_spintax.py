import random

import pytest

from jakov.engine.spintax import spin


def outputs(text: str, n: int = 300) -> set[str]:
    rng = random.Random(1)
    return {spin(text, rng) for _ in range(n)}


def test_picks_each_option() -> None:
    assert outputs("{Hello|Hi|Hey} there") == {"Hello there", "Hi there", "Hey there"}


def test_nested_groups() -> None:
    assert outputs("{a|{b|c}d}") == {"a", "bd", "cd"}


def test_placeholders_and_emoji_tokens_survive() -> None:
    assert spin("{Buy|Get} {product} {emoji:fire}", random.Random(0)) in {
        "Buy {product} {emoji:fire}", "Get {product} {emoji:fire}"}


def test_placeholder_inside_option() -> None:
    assert outputs("{Only {price}|Just {price}}") == {"Only {price}", "Just {price}"}


def test_escapes_are_literal() -> None:
    assert spin(r"\{not|spun\} a\|b", random.Random(0)) == "{not|spun} a|b"


@pytest.mark.parametrize("text", ["{unclosed", "a } b", "{", "}"])
def test_unbalanced_braces_kept(text: str) -> None:
    assert spin(text, random.Random(0)) == text


def test_html_untouched() -> None:
    assert spin('<b>{x|x}</b> <a href="https://t.me/a">l</a>', random.Random(0)) == \
        '<b>x</b> <a href="https://t.me/a">l</a>'


def test_seeded_is_deterministic() -> None:
    text = "{a|b|c|d|e} {f|g|h|i}"
    assert spin(text, random.Random(42)) == spin(text, random.Random(42))


def test_empty_option_allowed() -> None:
    assert outputs("x{!|}") == {"x!", "x"}
