"""Turn a getChatMember result into a rights snapshot and explain what's missing."""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum

from aiogram.enums import ChatMemberStatus
from aiogram.types import (
    ChatMemberAdministrator,
    ChatMemberBanned,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberOwner,
    ChatMemberRestricted,
)

from jakov.db.models import Chat, ChatKind

AnyChatMember = (
    ChatMemberOwner
    | ChatMemberAdministrator
    | ChatMemberMember
    | ChatMemberRestricted
    | ChatMemberLeft
    | ChatMemberBanned
)

RIGHT_LABELS = {
    "can_post": "post messages",
    "can_edit": "edit messages",
    "can_delete": "delete messages",
    "can_pin": "pin messages",
    "can_restrict": "ban/restrict users",
    "can_invite": "invite users",
}


@dataclass(frozen=True, slots=True)
class Rights:
    status: str
    can_post: bool = False
    can_edit: bool = False
    can_delete: bool = False
    can_pin: bool = False
    can_restrict: bool = False
    can_invite: bool = False

    @property
    def is_admin(self) -> bool:
        return self.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)

    @property
    def is_present(self) -> bool:
        return self.status not in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED)

    def flags(self) -> dict[str, bool]:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "status"}


def status_value(status: object) -> str:
    """'administrator', not 'ChatMemberStatus.ADMINISTRATOR' (aiogram enums aren't StrEnum)."""
    return str(status.value) if isinstance(status, Enum) else str(status)


def rights_from_member(member: AnyChatMember, kind: ChatKind) -> Rights:
    status = status_value(member.status)
    if isinstance(member, ChatMemberOwner):
        return Rights(status, True, True, True, True, True, True)
    if isinstance(member, ChatMemberAdministrator):
        is_channel = kind is ChatKind.CHANNEL
        return Rights(
            status,
            # In groups admins can always write; in channels it is an explicit right.
            can_post=bool(member.can_post_messages) if is_channel else True,
            can_edit=bool(member.can_edit_messages) if is_channel else False,
            can_delete=member.can_delete_messages,
            # Pinning in channels is governed by the edit right (Bot API pinChatMessage).
            can_pin=bool(member.can_edit_messages) if is_channel else bool(member.can_pin_messages),
            can_restrict=member.can_restrict_members,
            can_invite=member.can_invite_users,
        )
    if isinstance(member, ChatMemberMember):
        return Rights(status, can_post=kind is not ChatKind.CHANNEL)
    if isinstance(member, ChatMemberRestricted):
        return Rights(status, can_post=bool(member.can_send_messages) and member.is_member)
    return Rights(status)


def apply_rights(chat: Chat, rights: Rights) -> None:
    chat.bot_status = rights.status
    chat.is_active = rights.is_present
    for name, value in rights.flags().items():
        setattr(chat, name, value)


def publisher_problems(kind: ChatKind, rights: Rights) -> list[str]:
    """Human-readable reasons the bot can't publish here. Empty list = good to go."""
    if not rights.is_present:
        return ["I'm not a member of this chat."]
    if not rights.is_admin:
        return ["I'm not an admin here. Promote me to admin."]
    problems: list[str] = []
    if not rights.can_post:
        problems.append("Missing right: post messages.")
    if kind is ChatKind.CHANNEL and not rights.can_edit:
        problems.append("Missing right: edit messages (needed to edit published posts).")
    return problems


def lost_rights(before: Rights, after: Rights) -> list[str]:
    old, new = before.flags(), after.flags()
    return [RIGHT_LABELS[name] for name, had in old.items() if had and not new[name]]


def rights_of(chat: Chat) -> Rights:
    return Rights(
        chat.bot_status,
        chat.can_post,
        chat.can_edit,
        chat.can_delete,
        chat.can_pin,
        chat.can_restrict,
        chat.can_invite,
    )
