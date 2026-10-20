"""Measure how alive each library emoji is, in the background, and remember it.

Frozen "animated" emoji (no keyframe ever changes) are never used in menus or posts.
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import Sequence

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Sticker
from sqlalchemy import select

from jakov.context import AppContext
from jakov.db.models import EmojiLibraryItem
from jakov.engine.lottie_motion import tgs_motion
from jakov.logging_setup import get_logger

log = get_logger(__name__)
VIDEO_MOTION = 100.0  # WEBM emoji can't be inspected cheaply; video implies movement
BATCH = 200


async def _score(bot: Bot, sticker: Sticker, limit: asyncio.Semaphore) -> float | None:
    if sticker.is_video:
        return VIDEO_MOTION
    if not sticker.is_animated:
        return 0.0
    async with limit:
        try:
            buffer = io.BytesIO()
            await bot.download(sticker.file_id, destination=buffer)
            return tgs_motion(buffer.getvalue())
        except (TelegramAPIError, OSError, ValueError) as exc:
            log.warning("motion_score_failed", emoji=sticker.custom_emoji_id, error=str(exc))
            return None


async def score_ids(bot: Bot, ids: Sequence[str]) -> dict[str, float]:
    limit = asyncio.Semaphore(6)
    scores: dict[str, float] = {}
    for start in range(0, len(ids), BATCH):
        stickers = await bot.get_custom_emoji_stickers(list(ids[start:start + BATCH]))
        results = await asyncio.gather(*(_score(bot, s, limit) for s in stickers))
        for sticker, value in zip(stickers, results, strict=True):
            if sticker.custom_emoji_id and value is not None:
                scores[sticker.custom_emoji_id] = value
    return scores


async def backfill_motion(bot: Bot, ctx: AppContext) -> int:
    """Score every emoji whose motion is unknown. Returns how many were scored."""
    async with ctx.sessions() as session:
        ids = list(await session.scalars(select(EmojiLibraryItem.custom_emoji_id).where(
            EmojiLibraryItem.owner_id == ctx.owner_id, EmojiLibraryItem.motion.is_(None))))
    if not ids:
        return 0
    log.info("motion_backfill_begin", count=len(ids))
    done = 0
    for start in range(0, len(ids), BATCH):
        chunk = ids[start:start + BATCH]
        try:
            scores = await score_ids(bot, chunk)
        except TelegramAPIError as exc:
            log.warning("motion_backfill_batch_failed", error=str(exc))
            continue
        async with ctx.sessions() as session:
            rows = await session.scalars(select(EmojiLibraryItem).where(
                EmojiLibraryItem.owner_id == ctx.owner_id,
                EmojiLibraryItem.custom_emoji_id.in_(list(scores))))
            for row in rows:
                row.motion = scores[row.custom_emoji_id]
            await session.commit()
        done += len(scores)
    await ctx.reload_emoji()
    log.info("motion_backfill_done", scored=done)
    return done
