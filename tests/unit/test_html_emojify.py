from jakov.engine.emoji_render import tg_emoji
from jakov.engine.html_emojify import Emojifier

E = Emojifier({"🔥": "1", "❤️": "2", "✍": "3", "👨‍💻": "4"})


def test_replaces_plain_emoji_in_text() -> None:
    assert E.html("<b>🔥 Hot</b>") == f"<b>{tg_emoji('1', '🔥')} Hot</b>"


def test_matches_with_or_without_variation_selector() -> None:
    assert E.html("❤") == tg_emoji("2", "❤")
    assert E.html("❤️") == tg_emoji("2", "❤️")
    assert E.html("✍️ New") == tg_emoji("3", "✍️") + " New"


def test_zwj_sequence_matched_whole() -> None:
    assert E.html("👨‍💻") == tg_emoji("4", "👨‍💻")


def test_skips_code_pre_links_and_existing_custom() -> None:
    src = ("<code>🔥</code><pre>🔥</pre><a href=\"https://x.y\">🔥</a>"
           f"{tg_emoji('9', '🔥')}🔥")
    out = E.html(src)
    assert out.startswith("<code>🔥</code><pre>🔥</pre><a href=\"https://x.y\">🔥</a>")
    assert out.count('emoji-id="1"') == 1 and out.count('emoji-id="9"') == 1


def test_unknown_emoji_and_tags_untouched() -> None:
    assert E.html('<i title="🔥">🍕</i>') == '<i title="🔥">🍕</i>'


def test_budget() -> None:
    assert E.html("🔥🔥🔥", budget=2).count("<tg-emoji") == 2


def test_leading_for_buttons() -> None:
    assert E.leading("🔥 Hot deals") == ("1", "Hot deals")
    assert E.leading("✍️ New post") == ("3", "New post")
    assert E.leading("🍕 Pizza") == (None, "🍕 Pizza")
    assert E.leading("🔥") == (None, "🔥")  # never leave a button without text
    assert E.leading("Plain") == (None, "Plain")


def test_empty_mapping_is_noop() -> None:
    assert Emojifier({}).html("🔥") == "🔥"
