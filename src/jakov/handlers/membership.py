"""React to the bot being added, removed or re-permissioned, and to group→supergroup upgrades."""

from __future__ import annotations

import html

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatMemberUpdated, Message
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.context import AppContext
from jakov.db.models import ChatKind
from jakov.db.repositories.chats import ChatRepo
from jakov.logging_setup import get_logger
from jakov.services.channels import handle_membership
from jakov.services.notifier import notify_admins
from jakov.services.rights import status_value

log = get_logger(__name__)
router = Router(name="membership")


@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated, bot: Bot, ctx: AppContext,
                            session: AsyncSession) -> None:
    change = await handle_membership(event, ChatRepo(session, ctx.owner_id), ctx.admin_ids)
    if change.chat is not None and ctx.scheduler is not None \
            and (not change.chat.is_active or not change.chat.can_post):
        paused = await ctx.scheduler.pause_for_chat(
            session, change.chat.id, "I lost access or posting rights in this chat.")
        if paused and change.message:
            change.message += f"\n⏸ Paused {paused} schedule(s) for this chat."
    log.info("my_chat_member", chat_id=event.chat.id,
             old=status_value(event.old_chat_member.status),
             new=status_value(event.new_chat_member.status))
    if change.leave:
        try:
            await bot.leave_chat(event.chat.id)
        except TelegramAPIError as exc:
            log.warning("leave_failed", chat_id=event.chat.id, error=type(exc).__name__)
    await session.commit()
    if change.message:
        await notify_admins(bot, ctx.admin_ids, change.message)


@router.message(F.migrate_to_chat_id)
async def on_group_migrated(message: Message, bot: Bot, ctx: AppContext,
                            session: AsyncSession) -> None:
    """A basic group became a supergroup: Telegram gives it a new ID."""
    assert message.migrate_to_chat_id is not None
    repo = ChatRepo(session, ctx.owner_id)
    chat = await repo.by_tg_id(message.chat.id)
    if chat is None or await repo.by_tg_id(message.migrate_to_chat_id):
        return
    chat.tg_chat_id = message.migrate_to_chat_id
    chat.kind = ChatKind.SUPERGROUP
    await session.commit()
    log.info("chat_migrated", old=message.chat.id, new=message.migrate_to_chat_id)
    await notify_admins(
        bot, ctx.admin_ids,
        f"ℹ️ <b>{html.escape(chat.name)}</b> was upgraded to a supergroup; I updated its ID.",
    )
