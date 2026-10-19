"""Every template combination in data/ renders cleanly for every type and tone."""

import random
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jakov.config import PROJECT_ROOT
from jakov.engine.catalog import Catalog, CatalogError
from jakov.engine.compose import RenderInput, render, resolve_spintax
from jakov.engine.emoji_render import EmojiPalette, EmojiPicker, LibEmoji
from jakov.engine.limits import CAPTION_LIMIT, check_length
from jakov.engine.text_generator import GenerationRequest, TemplateGenerator
from jakov.engine.variables import builtin_values

CATALOG = Catalog(PROJECT_ROOT / "data")
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

FULL = {"game": "Valorant", "cta": "Join the lobby", "product": "Air Max", "price": "$99",
        "offer": "-30% today", "for": "Mia", "mood": "Sweet", "topic": "New rules",
        "details": "Read them carefully.", "prize": "PS5", "how": "Comment ❤ below",
        "message": "Big things coming."}


def balanced(html: str) -> bool:
    stack: list[str] = []
    for closing, name in re.findall(r"<(/?)([a-z-]+)[^>]*>", html):
        if closing:
            if not stack or stack.pop() != name:
                return False
        else:
            stack.append(name)
    return not stack


def combos(type_key: str, tone: str) -> list[str]:
    parts = CATALOG.types[type_key].tones[tone]
    return ["\n\n".join((h, b, c)) for h in parts.hooks for b in parts.bodies for c in parts.ctas]


def palette() -> EmojiPalette:
    base = EmojiPalette(CATALOG.moods)
    return EmojiPalette(CATALOG.moods, [LibEmoji("1", "🔥", "P", frozenset(base.auto_tags("🔥")))])


@pytest.mark.parametrize("type_key", CATALOG.type_order)
@pytest.mark.parametrize("tone", list(CATALOG.tones))
@pytest.mark.parametrize("answers", ["full", "minimal"])
def test_every_combination_renders(type_key: str, tone: str, answers: str) -> None:
    post_type = CATALOG.types[type_key]
    if answers == "full":
        values = {q.key: FULL.get(q.key, "x") for q in post_type.questions}
        moments = {k: NOW + timedelta(days=2) for k in post_type.datetime_fields}
    else:
        values = {q.key: FULL.get(q.key, "x") for q in post_type.questions if q.required}
        moments = {}
    values |= builtin_values(NOW, moments) | {"channel": "Chan", "tip": "t", "quote": "q",
                                              "fact": "f"}
    data = RenderInput(values, frozenset(post_type.field_names))
    rng = random.Random(7)
    for template in combos(type_key, tone):
        for _ in range(3):
            picker = EmojiPicker(palette(), rng, custom=True, generic_moods=post_type.palette)
            html = render(resolve_spintax(template, rng), data, picker)
            plain = re.sub(r"<[^>]+>", "", html)
            assert "{" not in plain and "}" not in plain, html
            assert "[[" not in html and "]]" not in html, html
            assert "\n\n\n" not in html and html == html.strip(), repr(html)
            assert balanced(html), html
            assert check_length(html, has_media=True).length <= CAPTION_LIMIT // 2, html


async def test_generator_returns_distinct_hooks() -> None:
    gen = TemplateGenerator(CATALOG, random.Random(1))
    for type_key in CATALOG.type_order:
        out = await gen.generate(GenerationRequest(type_key, "hype"), 3)
        assert len(out) == 3 and len({t.split("\n\n")[0] for t in out}) == 3


async def test_generator_respects_exclude() -> None:
    gen = TemplateGenerator(CATALOG, random.Random(2))
    first = await gen.generate(GenerationRequest("sell", "chill"), 3)
    second = await gen.generate(GenerationRequest("sell", "chill"), 3, exclude=frozenset(first))
    assert not set(first) & set(second)


def test_pools_and_starters_load() -> None:
    assert set(CATALOG.pools) == {"tip", "quote", "fact"}
    assert "DogsEmoji" in CATALOG.starter_packs and CATALOG.starter_packs[0] == "RestrictedEmoji"


def test_bad_placeholder_is_rejected(tmp_path: Path) -> None:
    import shutil

    shutil.copytree(PROJECT_ROOT / "data", tmp_path / "data")
    path = tmp_path / "data" / "templates" / "game.yaml"
    path.write_text(path.read_text().replace("{game}", "{gaem}", 1))
    with pytest.raises(CatalogError, match="gaem"):
        _ = Catalog(tmp_path / "data").types


def test_bad_mood_is_rejected(tmp_path: Path) -> None:
    import shutil

    shutil.copytree(PROJECT_ROOT / "data", tmp_path / "data")
    path = tmp_path / "data" / "templates" / "sell.yaml"
    path.write_text(path.read_text().replace("{emoji:money}", "{emoji:monee}", 1))
    with pytest.raises(CatalogError, match="monee"):
        _ = Catalog(tmp_path / "data").types
