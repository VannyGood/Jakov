"""Draft posts built by the New post wizard: variations, re-rolls, styles and edits."""

from __future__ import annotations

import random
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from jakov.db.models import Post, PostVariation
from jakov.engine.catalog import Catalog
from jakov.engine.compose import resolve_spintax
from jakov.engine.limits import check_length
from jakov.engine.text_generator import GenerationRequest, TemplateGenerator, TextGenerator
from jakov.services.emoji_library import EmojiLibrary
from jakov.services.publisher import render_variation

VARIATIONS = 3
_rng = random.SystemRandom()


class DraftError(ValueError):
    """Shown to the admin as-is."""


def new_seed() -> int:
    return _rng.randrange(1, 2**62)


async def generate_variations(
    session: AsyncSession, owner_id: int, post: Post, generator: TextGenerator,
    catalog: Catalog, library: EmojiLibrary, count: int = VARIATIONS,
) -> None:
    """Replace the post's variations with `count` fresh ones that fit Telegram's limits."""
    previous = frozenset(v.template for v in post.variations if not v.is_custom)
    request = build_request(post)
    generated = await generator.generate(request, count, exclude=previous)
    # Backup candidates in case some written texts don't fit Telegram's limits.
    backup = await TemplateGenerator(catalog).generate(request, count * 4, exclude=previous)
    rng = random.Random(new_seed())
    fitting: list[PostVariation] = []
    for item in [*generated, *backup]:
        variation = PostVariation(owner_id=owner_id, idx=len(fitting), template=item.template,
                                  resolved=resolve_spintax(item.template, rng),
                                  emoji_seed=new_seed(), source=item.source)
        # Kept detached from the session until chosen (render only reads its fields).
        rendered = await render_variation(session, owner_id, post, variation, catalog, library,
                                          custom_emoji=False)
        if check_length(rendered.html, post.has_media).ok:
            fitting.append(variation)
        if len(fitting) == count:
            break
    if not fitting:
        limit = "1024 (with media)" if post.has_media else "4096"
        raise DraftError(f"Your answers are too long to fit Telegram's {limit} character limit. "
                         "Start again with shorter answers.")
    post.variations.clear()
    await session.flush()
    for variation in fitting:
        post.variations.append(variation)
    post.status, post.rotate, post.chosen_index = "draft", False, None
    await session.flush()


def build_request(post: Post) -> GenerationRequest:
    return GenerationRequest(post.post_type, post.tone or "hype", dict(post.answers),
                             has_buttons=bool(post.buttons))


def reroll_emojis(post: Post) -> None:
    for variation in post.variations:
        variation.emoji_seed = new_seed()


def next_style(current: str | None, packs: list[str]) -> str | None:
    """Cycle: Mixed (None) -> pack1 -> pack2 -> ... -> Mixed."""
    if not packs:
        return None
    if current not in packs:
        return packs[0]
    index = packs.index(current) + 1
    return packs[index] if index < len(packs) else None


async def set_custom_text(
    session: AsyncSession, owner_id: int, post: Post, idx: int, html_text: str,
    catalog: Catalog, library: EmojiLibrary,
) -> None:
    variation = next((v for v in post.variations if v.idx == idx), None)
    if variation is None:
        raise DraftError("That variation no longer exists.")
    rng = random.Random(new_seed())
    candidate = PostVariation(owner_id=owner_id, idx=idx, template=html_text,
                              resolved=resolve_spintax(html_text, rng), emoji_seed=new_seed(),
                              is_custom=True, source="custom")
    rendered = await render_variation(session, owner_id, post, candidate, catalog, library,
                                      custom_emoji=False)
    length = check_length(rendered.html, post.has_media)
    if not length.ok:
        raise DraftError(f"That text is {length.length} characters; the limit is "
                         f"{length.limit}{' for posts with media' if post.has_media else ''}.")
    variation.template = candidate.template
    variation.resolved = candidate.resolved
    variation.emoji_seed = candidate.emoji_seed
    variation.is_custom = True
    variation.source = "custom"
    await session.flush()


def store_moment(post: Post, key: str, moment: datetime) -> None:
    post.moments = {**post.moments, key: moment.astimezone(UTC).isoformat()}
