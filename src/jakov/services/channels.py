"""Linking channels/groups, refreshing rights and reacting to my_chat_member updates."""

from __future__ import annotations

import html
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import ChatFullInfo, ChatMemberUpdated

from jakov.db.base import utcnow
from jakov.db.models import Chat, ChatKind
from jakov.db.repositories.chats import ChatRepo
from jakov.logging_setup import get_logger
from jakov.services.rights import (
    Rights,
    apply_rights,
    lost_rights,
    publisher_problems,
    rights_from_member,
    rights_of,
)

log = get_logger(__name__)

_ADMIN_STATUSES = {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}


class LinkError(Exception):
    """Shown to the admin as-is."""


@dataclass(slots=True)
class LinkResult:
    chat: Chat
    created: bool
    problems: list[str] = field(default_factory=list)


def chat_kind(chat_type: str) -> ChatKind:
    match chat_type:
        case ChatType.CHANNEL:
            return ChatKind.CHANNEL
        case ChatType.SUPERGROUP:
            return ChatKind.SUPERGROUP
        case ChatType.GROUP:
            return ChatKind.GROUP
    raise LinkError("That's a private chat, not a channel or group.")


async def fetch_rights(bot: Bot, tg_chat_id: int, kind: ChatKind) -> Rights:
    member = await bot.get_chat_member(tg_chat_id, bot.id)
    return rights_from_member(member, kind)


async def link_chat(
    bot: Bot, repo: ChatRepo, ref: int | str, requested_by: int
) -> LinkResult:
    """Verify and store a chat. Raises LinkError with a user-facing message on failure."""
    try:
        info: ChatFullInfo = await bot.get_chat(ref)
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        raise LinkError(
            "I can't see that chat. Add me as an admin there first, then try again."
        ) from exc
    kind = chat_kind(info.type)

    try:
        rights = await fetch_rights(bot, info.id, kind)
        requester = await bot.get_chat_member(info.id, requested_by)
    except TelegramAPIError as exc:
        raise LinkError(
            "I can't read the member list there. Make me an admin, then try again."
        ) from exc
    if requester.status not in _ADMIN_STATUSES:
        raise LinkError("You must be an admin of that chat to link it.")

    chat = await repo.by_tg_id(info.id)
    created = chat is None
    if chat is None:
        chat = Chat(tg_chat_id=info.id, kind=kind, settings={})
        await repo.add(chat)
    chat.kind = kind
    chat.title = info.title or ""
    chat.username = info.username
    chat.linked_chat_id = info.linked_chat_id
    apply_rights(chat, rights)
    chat.rights_checked_at = utcnow()
    await repo.session.flush()
    return LinkResult(chat, created, publisher_problems(kind, rights))


async def refresh_chat(bot: Bot, chat: Chat) -> list[str]:
    """Re-read title and rights from Telegram. Returns publisher problems (empty = OK)."""
    try:
        info = await bot.get_chat(chat.tg_chat_id)
        rights = await fetch_rights(bot, chat.tg_chat_id, chat.kind)
    except (TelegramBadRequest, TelegramForbiddenError):
        apply_rights(chat, Rights(ChatMemberStatus.LEFT.value))
        chat.rights_checked_at = utcnow()
        return ["I'm not a member of this chat anymore."]
    chat.title = info.title or chat.title
    chat.username = info.username
    chat.linked_chat_id = info.linked_chat_id
    apply_rights(chat, rights)
    chat.rights_checked_at = utcnow()
    return publisher_problems(chat.kind, rights)


@dataclass(slots=True)
class MembershipChange:
    chat: Chat | None
    message: str | None
    leave: bool = False


async def handle_membership(
    event: ChatMemberUpdated, repo: ChatRepo, admin_ids: set[int]
) -> MembershipChange:
    """Update the DB for a my_chat_member update and describe it for the admins."""
    tg_chat = event.chat
    if tg_chat.type == ChatType.PRIVATE:
        return MembershipChange(None, None)
    kind = chat_kind(tg_chat.type)
    new = rights_from_member(event.new_chat_member, kind)
    old = rights_from_member(event.old_chat_member, kind)
    title = html.escape(tg_chat.title or str(tg_chat.id))
    actor = event.from_user
    chat = await repo.by_tg_id(tg_chat.id)

    if chat is None:
        if not new.is_present:
            return MembershipChange(None, None)
        if actor.id not in admin_ids:
            log.warning("added_by_stranger", chat_id=tg_chat.id, actor_id=actor.id)
            return MembershipChange(
                None,
                f"⚠️ <b>{html.escape(actor.full_name)}</b> (id <code>{actor.id}</code>) added me "
                f"to <b>{title}</b>. They are not a Jakov admin, so I left.",
                leave=True,
            )
        chat = Chat(tg_chat_id=tg_chat.id, kind=kind, title=tg_chat.title or "",
                    username=tg_chat.username, settings={})
        await repo.add(chat)
        apply_rights(chat, new)
        chat.rights_checked_at = utcnow()
        problems = publisher_problems(kind, new)
        text = f"✅ I was added to <b>{title}</b> and linked it."
        if problems:
            text += "\n" + "\n".join(f"• {p}" for p in problems)
        return MembershipChange(chat, text)

    before = rights_of(chat)
    apply_rights(chat, new)
    chat.title = tg_chat.title or chat.title
    chat.rights_checked_at = utcnow()

    if not new.is_present:
        return MembershipChange(chat, f"🚫 I was removed from <b>{title}</b>.")
    if not old.is_present:
        return MembershipChange(chat, f"✅ I'm back in <b>{title}</b>.")
    lost = lost_rights(before, new)
    if before.is_admin and not new.is_admin:
        return MembershipChange(chat, f"⚠️ I'm no longer an admin in <b>{title}</b>.")
    if lost:
        return MembershipChange(
            chat, f"⚠️ I lost rights in <b>{title}</b>: {', '.join(lost)}."
        )
    if new.is_admin and not before.is_admin:
        return MembershipChange(chat, f"✅ I'm now an admin in <b>{title}</b>.")
    return MembershipChange(chat, None)
