from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jakov.db.base import Base, OwnedMixin, TimestampMixin
from jakov.db.types import UTCDateTime


class Post(OwnedMixin, TimestampMixin, Base):
    """A composed post: answers, media, buttons, options and its variations."""

    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_by: Mapped[int] = mapped_column(BigInteger)
    post_type: Mapped[str] = mapped_column(String(32))
    tone: Mapped[str | None] = mapped_column(String(16))
    answers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    # ISO datetimes (UTC) for datetime questions, e.g. {"deadline": "2026-10-25T21:59:00+00:00"}
    moments: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    media_kind: Mapped[str | None] = mapped_column(String(8))  # photo | video
    media_file_id: Mapped[str | None] = mapped_column(String(256))
    # [{"text": "...", "url": "..."}]
    buttons: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    pin: Mapped[bool] = mapped_column(Boolean, default=False)
    silent: Mapped[bool] = mapped_column(Boolean, default=False)
    link_preview: Mapped[bool] = mapped_column(Boolean, default=True)
    emoji_style: Mapped[str | None] = mapped_column(String(64))  # pack name or None = mixed
    # draft -> ready (variation chosen)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    rotate: Mapped[bool] = mapped_column(Boolean, default=False)
    chosen_index: Mapped[int | None] = mapped_column(Integer)
    last_variation_index: Mapped[int] = mapped_column(Integer, default=-1)

    variations: Mapped[list[PostVariation]] = relationship(
        back_populates="post", cascade="all, delete-orphan", order_by="PostVariation.idx",
        lazy="selectin",
    )

    @property
    def has_media(self) -> bool:
        return bool(self.media_file_id)

    def active_variations(self) -> list[PostVariation]:
        if self.rotate or self.chosen_index is None:
            return list(self.variations)
        return [v for v in self.variations if v.idx == self.chosen_index]


class PostVariation(OwnedMixin, TimestampMixin, Base):
    __tablename__ = "post_variations"
    __table_args__ = (UniqueConstraint("post_id", "idx", name="uq_post_variations_post_idx"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    # Unresolved template: spintax + {placeholders} + {emoji} tokens (re-spun on every send).
    template: Mapped[str] = mapped_column(Text)
    # The spin shown in the preview; "Send now" sends exactly this.
    resolved: Mapped[str] = mapped_column(Text)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    emoji_seed: Mapped[int] = mapped_column(BigInteger, default=0)
    # Who wrote it: "llm" (AI writer, rewritten fresh on scheduled sends), "template", "custom".
    source: Mapped[str] = mapped_column(String(12), default="template",
                                        server_default="template")

    post: Mapped[Post] = relationship(back_populates="variations")


class PublishedPost(OwnedMixin, TimestampMixin, Base):
    """Every message the bot published, so it can be edited or deleted later."""

    __tablename__ = "published_posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id", ondelete="SET NULL"),
                                                index=True)
    chat_id: Mapped[int | None] = mapped_column(ForeignKey("chats.id", ondelete="SET NULL"),
                                                index=True)
    tg_chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)
    variation_idx: Mapped[int | None] = mapped_column(Integer)
    media_kind: Mapped[str | None] = mapped_column(String(8))
    html: Mapped[str] = mapped_column(Text)
    buttons: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    custom_emoji_used: Mapped[bool] = mapped_column(Boolean, default=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime())
    edited_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PoolState(OwnedMixin, Base):
    """Which items of a content pool were used in the current cycle."""

    __tablename__ = "pool_state"
    __table_args__ = (UniqueConstraint("owner_id", "pool", name="uq_pool_state_owner_pool"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pool: Mapped[str] = mapped_column(String(32))
    used: Mapped[list[int]] = mapped_column(JSON, default=list)
