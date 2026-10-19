from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, Enum, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from jakov.db.base import Base, OwnedMixin, TimestampMixin
from jakov.db.types import UTCDateTime


class ChatKind(enum.StrEnum):
    CHANNEL = "channel"
    GROUP = "group"
    SUPERGROUP = "supergroup"


class Chat(OwnedMixin, TimestampMixin, Base):
    """A channel or group the bot works in, with its rights snapshot and settings."""

    __tablename__ = "chats"
    __table_args__ = (UniqueConstraint("owner_id", "tg_chat_id", name="uq_chats_owner_chat"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    kind: Mapped[ChatKind] = mapped_column(
        Enum(ChatKind, native_enum=False, length=16, values_callable=lambda e: [m.value for m in e])
    )
    title: Mapped[str] = mapped_column(String(256), default="")
    username: Mapped[str | None] = mapped_column(String(64))
    # Admin-chosen name shown in menus; falls back to the Telegram title.
    display_name: Mapped[str | None] = mapped_column(String(64))
    linked_chat_id: Mapped[int | None] = mapped_column(BigInteger)

    # Status of the bot in the chat: administrator / member / left / kicked / restricted.
    bot_status: Mapped[str] = mapped_column(String(16), default="administrator")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    can_post: Mapped[bool] = mapped_column(Boolean, default=False)
    can_edit: Mapped[bool] = mapped_column(Boolean, default=False)
    can_delete: Mapped[bool] = mapped_column(Boolean, default=False)
    can_pin: Mapped[bool] = mapped_column(Boolean, default=False)
    can_restrict: Mapped[bool] = mapped_column(Boolean, default=False)
    can_invite: Mapped[bool] = mapped_column(Boolean, default=False)
    rights_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    # None = never tested, True/False = result of the last live test in this chat.
    custom_emoji_ok: Mapped[bool | None] = mapped_column(Boolean)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    @property
    def name(self) -> str:
        return self.display_name or self.title or str(self.tg_chat_id)
