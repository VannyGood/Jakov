"""Builders for aiogram objects used across tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aiogram.types import (
    Chat,
    ChatFullInfo,
    ChatMemberAdministrator,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberOwner,
    ChatMemberUpdated,
    User,
)

BOT_ID = 123456789
BOT_USER = User(id=BOT_ID, is_bot=True, first_name="Jakov", username="Jakovthebot")


def admin_member(user: User = BOT_USER, **rights: bool) -> ChatMemberAdministrator:
    base: dict[str, Any] = dict(
        can_be_edited=False, is_anonymous=False, can_manage_chat=True,
        can_delete_messages=True, can_manage_video_chats=False, can_restrict_members=True,
        can_promote_members=False, can_change_info=False, can_invite_users=True,
        can_post_stories=False, can_edit_stories=False, can_delete_stories=False,
        can_send_welcome_messages=False,
        can_post_messages=True, can_edit_messages=True, can_pin_messages=True,
    )
    base.update(rights)
    return ChatMemberAdministrator(user=user, **base)


def owner_member(user: User) -> ChatMemberOwner:
    return ChatMemberOwner(user=user, is_anonymous=False)


def plain_member(user: User = BOT_USER) -> ChatMemberMember:
    return ChatMemberMember(user=user)


def left_member(user: User = BOT_USER) -> ChatMemberLeft:
    return ChatMemberLeft(user=user)


def tg_chat(chat_id: int = -1001, kind: str = "channel", title: str = "My Channel") -> Chat:
    return Chat(id=chat_id, type=kind, title=title)


def full_chat(chat_id: int = -1001, kind: str = "channel", title: str = "My Channel",
              username: str | None = "mychan", linked: int | None = None) -> ChatFullInfo:
    return ChatFullInfo(id=chat_id, type=kind, title=title, username=username,
                        linked_chat_id=linked, accent_color_id=0, max_reaction_count=11,
                        accepted_gift_types={"unlimited_gifts": False, "limited_gifts": False,
                                             "unique_gifts": False, "premium_subscription": False,
                                             "gifts_from_channels": False})


def member_update(chat: Chat, actor: User, old: Any, new: Any) -> ChatMemberUpdated:
    return ChatMemberUpdated(chat=chat, from_user=actor, date=datetime.now(UTC),
                             old_chat_member=old, new_chat_member=new)
