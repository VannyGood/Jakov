from jakov.engine.emoji_render import tg_emoji
from jakov.engine.limits import CAPTION_LIMIT, TEXT_LIMIT, check_length, tg_length, visible_text


def test_tags_do_not_count_and_entities_unescape() -> None:
    assert visible_text("<b>a &amp; b</b>") == "a & b"
    assert tg_length("<b>a &amp; b</b>") == 5


def test_utf16_units_for_emoji() -> None:
    assert tg_length("🔥") == 2
    assert tg_length(tg_emoji("123", "🔥")) == 2


def test_text_vs_caption_limits() -> None:
    long = "a" * 2000
    assert check_length(long, has_media=False).ok
    caption = check_length(long, has_media=True)
    assert not caption.ok and caption.limit == CAPTION_LIMIT and caption.over_by == 976
    assert check_length("a" * TEXT_LIMIT, False).ok
    assert not check_length("a" * (TEXT_LIMIT + 1), False).ok


def test_empty_text_is_not_ok() -> None:
    assert not check_length("<b></b>", False).ok
