import pytest

from jakov.engine.tidy import tidy
from jakov.engine.variables import apply_filter, fill, with_article

KNOWN = {"product", "cta"}


@pytest.mark.parametrize(("raw", "clean"), [
    ("Join now!.", "Join now!"),
    ("Really?.", "Really?"),
    ("End.. more", "End. more"),
    ("Wait...", "Wait..."),
    ("Hello , world .", "Hello, world."),
    ("Go!!!!!!", "Go!!!"),
    ("a  b", "A b"),
    ("Price ()", "Price"),
    ("x,.", "X."),
])
def test_punctuation_fixes(raw: str, clean: str) -> None:
    assert tidy(raw) == clean


def test_tags_and_entities_untouched() -> None:
    html = '<a href="https://x.io/a..b?c=!.">go</a> &amp; <b>bold</b>'
    assert tidy(html) == '<a href="https://x.io/a..b?c=!.">Go</a> &amp; <b>bold</b>'


def test_line_starts_capitalized_but_mixed_case_kept() -> None:
    assert tidy("join the lobby\niPhone deal\n<b>free</b> stuff") == \
        "Join the lobby\niPhone deal\n<b>Free</b> stuff"


def test_capitalize_can_be_disabled_for_admin_text() -> None:
    assert tidy("lowercase vibes only", capitalize=False) == "lowercase vibes only"


def test_emoji_before_word_still_capitalizes() -> None:
    assert tidy("👉 join us") == "👉 Join us"


@pytest.mark.parametrize(("value", "expected"), [
    ("apple", "an apple"), ("Air Max", "an Air Max"), ("hour pass", "an hour pass"),
    ("user guide", "a user guide"), ("PS5", "a PS5"), ("one-off deal", "a one-off deal"),
])
def test_article(value: str, expected: str) -> None:
    assert with_article(value) == expected


def test_filters() -> None:
    assert apply_filter("air max", "upper") == "AIR MAX"
    assert apply_filter("air max by iPhone", "title") == "Air Max By iPhone"
    assert apply_filter("Air", "lower") == "air"
    assert fill("Get {product.a} now: {product.upper}!", {"product": "ice <cream>"}, KNOWN) == \
        "Get an ice &lt;cream&gt; now: ICE &lt;CREAM&gt;!"
