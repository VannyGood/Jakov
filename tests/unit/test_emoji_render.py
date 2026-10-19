import random

from jakov.engine.emoji_render import (
    EmojiPalette,
    EmojiPicker,
    LibEmoji,
    normalize_emoji,
    render_emoji_tokens,
    strip_custom_emoji,
    tg_emoji,
)

MOODS = {"fire": ["🔥", "💥"], "love": ["❤", "😍"], "money": ["💰"]}


def lib(*items: tuple[str, str, str | None]) -> EmojiPalette:
    base = EmojiPalette(MOODS)
    return EmojiPalette(MOODS, [
        LibEmoji(cid, fb, pack, frozenset(base.auto_tags(fb))) for cid, fb, pack in items])


def picker(palette: EmojiPalette, custom: bool = True, **kw: object) -> EmojiPicker:
    return EmojiPicker(palette, random.Random(3), custom=custom, **kw)  # type: ignore[arg-type]


def test_auto_tags_ignore_variation_selector() -> None:
    palette = EmojiPalette(MOODS)
    assert palette.auto_tags("❤️") == {"love"}
    assert normalize_emoji("❤️") == "❤"


def test_custom_token_renders_tg_emoji() -> None:
    palette = lib(("1", "🔥", "A"))
    assert render_emoji_tokens("{emoji:fire}!", picker(palette)) == tg_emoji("1", "🔥") + "!"


def test_without_custom_support_uses_fallback_char() -> None:
    palette = lib(("1", "💥", "A"))
    assert render_emoji_tokens("{emoji:fire}", picker(palette, custom=False)) == "💥"


def test_empty_library_uses_mood_defaults() -> None:
    out = render_emoji_tokens("{emoji:fire}{emoji:unknown}", picker(EmojiPalette(MOODS)))
    assert out[0] in "🔥💥" and out.endswith("✨")


def test_generic_token_uses_generic_moods() -> None:
    palette = lib(("1", "💰", None))
    out = render_emoji_tokens("{emoji}", picker(palette, generic_moods=["money"]))
    assert out == tg_emoji("1", "💰")


def test_style_prefers_pack_but_falls_back() -> None:
    palette = lib(("a", "🔥", "Dogs"), ("b", "🔥", "Duck"), ("c", "💰", "Duck"))
    p = picker(palette, style="Dogs")
    assert all(render_emoji_tokens("{emoji:fire}", p) == tg_emoji("a", "🔥") for _ in range(5))
    assert render_emoji_tokens("{emoji:money}", p) == tg_emoji("c", "💰")


def test_avoids_repeats_while_possible() -> None:
    palette = lib(("a", "🔥", None), ("b", "💥", None))
    out = render_emoji_tokens("{emoji:fire}{emoji:fire}", picker(palette))
    assert 'emoji-id="a"' in out and 'emoji-id="b"' in out


def test_custom_emoji_cap() -> None:
    palette = lib(("a", "🔥", None))
    out = render_emoji_tokens("{emoji:fire}" * 5, picker(palette, max_custom=2))
    assert out.count("<tg-emoji") == 2 and out.count("🔥") == 5


def test_tg_emoji_escapes_and_strip_restores_fallback() -> None:
    html = "a " + tg_emoji('x"y', "🔥") + " b"
    assert 'emoji-id="x&quot;y"' in html
    assert strip_custom_emoji(html) == "a 🔥 b"


def test_mood_counts_sorted() -> None:
    palette = lib(("a", "🔥", None), ("b", "💥", None), ("c", "💰", None))
    assert palette.mood_counts() == [("fire", 2), ("money", 1)]
