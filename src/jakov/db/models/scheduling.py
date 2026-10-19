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
from sqlalchemy.orm import Mapped, mapped_column

from jakov.db.base import Base, OwnedMixin, TimestampMixin
from jakov.db.types import UTCDateTime


class Schedule(OwnedMixin, TimestampMixin, Base):
    """When and where a post is published. All times are UTC; `timezone` drives daily runs."""

    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[int] = mapped_column(BigInteger)
    timezone: Mapped[str] = mapped_column(String(64))
    # once | daily | interval
    kind: Mapped[str] = mapped_column(String(16))
    run_at: Mapped[datetime | None] = mapped_column(UTCDateTime())        # once
    time_of_day: Mapped[str | None] = mapped_column(String(5))            # daily "HH:MM"
    interval_minutes: Mapped[int | None] = mapped_column(Integer)         # interval
    anchor_at: Mapped[datetime | None] = mapped_column(UTCDateTime())     # interval start
    # forever | count | until
    limit_kind: Mapped[str] = mapped_column(String(8), default="forever")
    limit_count: Mapped[int | None] = mapped_column(Integer)
    until_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    rotate: Mapped[bool] = mapped_column(Boolean, default=False)
    require_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    # active | paused | finished
    status: Mapped[str] = mapped_column(String(12), default="active", index=True)
    paused_reason: Mapped[str | None] = mapped_column(Text)
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    last_variation_index: Mapped[int] = mapped_column(Integer, default=-1)
    last_error: Mapped[str | None] = mapped_column(Text)


class SendLog(OwnedMixin, TimestampMixin, Base):
    """One row per scheduled run. The unique run key prevents duplicate sends."""

    __tablename__ = "send_log"
    __table_args__ = (
        UniqueConstraint("schedule_id", "scheduled_for", name="uq_send_log_run"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedules.id", ondelete="SET NULL"), index=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id", ondelete="SET NULL"))
    tg_chat_id: Mapped[int] = mapped_column(BigInteger)
    scheduled_for: Mapped[datetime] = mapped_column(UTCDateTime())
    # in_flight | awaiting_approval | sent | skipped | expired | failed | uncertain
    status: Mapped[str] = mapped_column(String(20), index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    published_post_id: Mapped[int | None] = mapped_column(
        ForeignKey("published_posts.id", ondelete="SET NULL"))
    variation_idx: Mapped[int | None] = mapped_column(Integer)


class ApprovalRequest(OwnedMixin, TimestampMixin, Base):
    """A scheduled run waiting for the admin's Approve / Skip / Edit."""

    __tablename__ = "approval_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedules.id", ondelete="CASCADE"), index=True)
    send_log_id: Mapped[int] = mapped_column(ForeignKey("send_log.id", ondelete="CASCADE"))
    admin_id: Mapped[int] = mapped_column(BigInteger)
    # pending | approved | skipped | expired
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    html: Mapped[str] = mapped_column(Text)
    variation_idx: Mapped[int | None] = mapped_column(Integer)
    preview_message_id: Mapped[int | None] = mapped_column(BigInteger)
    control_message_id: Mapped[int | None] = mapped_column(BigInteger)


class AppState(OwnedMixin, Base):
    """Small key/value store for bot bookkeeping (e.g. which starter packs were imported)."""

    __tablename__ = "app_state"
    __table_args__ = (UniqueConstraint("owner_id", "key", name="uq_app_state_owner_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[Any] = mapped_column(JSON)
