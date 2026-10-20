"""Import starter emoji packs: everything on first run, and newly added packs on upgrades.

Imported pack names are remembered, so a pack the admin deleted is not brought back.
"""

from __future__ import annotations

import html

from aiogram import Bot

from jakov.context import AppContext
from jakov.db.repositories.emoji import EmojiRepo
from jakov.db.repositories.state import StateRepo
from jakov.logging_setup import get_logger
from jakov.services.emoji_library import EmojiImportError, import_pack
from jakov.services.emoji_motion import backfill_motion
from jakov.services.notifier import notify_admins

log = get_logger(__name__)
STATE_KEY = "starter_packs_imported"


async def import_starter_packs(bot: Bot, ctx: AppContext, names: list[str] | None = None
                               ) -> tuple[int, list[str]]:
    """Returns (emoji imported, failed pack names). Each pack commits separately."""
    total, failed = 0, []
    for name in names if names is not None else ctx.catalog.starter_packs:
        async with ctx.sessions() as session:
            try:
                result = await import_pack(bot, session, ctx.owner_id, name)
            except EmojiImportError as exc:
                log.warning("starter_pack_failed", pack=name, error=str(exc))
                failed.append(name)
                continue
            state = StateRepo(session, ctx.owner_id)
            done = set(await state.get(STATE_KEY, []))
            await state.set(STATE_KEY, sorted(done | {name}))
            await session.commit()
            total += result.total
    await ctx.reload_emoji()
    return total, failed


async def retire_packs(ctx: AppContext) -> int:
    """Delete retired packs from the library. Returns how many emoji were removed."""
    removed = 0
    async with ctx.sessions() as session:
        repo = EmojiRepo(session, ctx.owner_id)
        present = {p.name.lower(): p.name for p in await repo.packs()}
        for name in ctx.catalog.retired_packs:
            if name.lower() in present:
                removed += await repo.delete_pack(present[name.lower()])
        await session.commit()
    if removed:
        log.info("retired_packs_removed", emoji=removed)
        await ctx.reload_emoji()
    return removed


async def ensure_starter_library(bot: Bot, ctx: AppContext) -> None:
    """Retire, import missing starter packs, then measure motion of new emoji."""
    await retire_packs(ctx)
    await _import_missing(bot, ctx)
    await backfill_motion(bot, ctx)


async def _import_missing(bot: Bot, ctx: AppContext) -> None:
    async with ctx.sessions() as session:
        state = StateRepo(session, ctx.owner_id)
        done: list[str] | None = await state.get(STATE_KEY)
        if done is None:
            # Upgrade from a version without bookkeeping: packs already present count as done.
            present = {p.name.lower() for p in await EmojiRepo(session, ctx.owner_id).packs()}
            done = [n for n in ctx.catalog.starter_packs if n.lower() in present]
            await state.set(STATE_KEY, done)
            await session.commit()
    done_lower = {n.lower() for n in done}
    missing = [n for n in ctx.catalog.starter_packs if n.lower() not in done_lower]
    if not missing:
        return
    log.info("starter_import_begin", packs=len(missing))
    total, failed = await import_starter_packs(bot, ctx, missing)
    text = (f"😀 I added <b>{total}</b> animated emoji from "
            f"{len(missing) - len(failed)} new pack(s) to your library.")
    if failed:
        text += f"\n❗ Couldn't load: {html.escape(', '.join(failed))}"
    await notify_admins(bot, ctx.admin_ids, text)
