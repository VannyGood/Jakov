"""Import the starter emoji packs the first time the library is empty."""

from __future__ import annotations

import html

from aiogram import Bot

from jakov.context import AppContext
from jakov.db.repositories.emoji import EmojiRepo
from jakov.logging_setup import get_logger
from jakov.services.emoji_library import EmojiImportError, import_pack
from jakov.services.notifier import notify_admins

log = get_logger(__name__)


async def import_starter_packs(bot: Bot, ctx: AppContext) -> tuple[int, list[str]]:
    """Returns (emoji imported, failed pack names). Each pack commits separately."""
    total, failed = 0, []
    for name in ctx.catalog.starter_packs:
        async with ctx.sessions() as session:
            try:
                result = await import_pack(bot, session, ctx.owner_id, name)
            except EmojiImportError as exc:
                log.warning("starter_pack_failed", pack=name, error=str(exc))
                failed.append(name)
                continue
            await session.commit()
            total += result.total
    await ctx.reload_emoji()
    return total, failed


async def ensure_starter_library(bot: Bot, ctx: AppContext) -> None:
    async with ctx.sessions() as session:
        if await EmojiRepo(session, ctx.owner_id).count():
            return
    log.info("starter_import_begin", packs=len(ctx.catalog.starter_packs))
    total, failed = await import_starter_packs(bot, ctx)
    text = (f"😀 I filled your emoji library with <b>{total}</b> animated emoji from "
            f"{len(ctx.catalog.starter_packs) - len(failed)} packs. Browse them in "
            "😀 Emoji library.")
    if failed:
        text += f"\n⚠️ Couldn't load: {html.escape(', '.join(failed))}"
    await notify_admins(bot, ctx.admin_ids, text)
