from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from jakov.db.base import Base, OwnedMixin, TimestampMixin
from jakov.db.types import UTCDateTime


class BotCapability(OwnedMixin, TimestampMixin, Base):
    """Result of a live feature probe, e.g. whether custom emoji survive in DMs."""

    __tablename__ = "bot_capabilities"
    __table_args__ = (UniqueConstraint("owner_id", "key", name="uq_bot_capabilities_owner_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64))
    supported: Mapped[bool] = mapped_column(Boolean)
    detail: Mapped[str] = mapped_column(Text, default="")
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime())


class FsmState(OwnedMixin, Base):
    """Persistent aiogram FSM storage so half-finished wizards survive restarts."""

    __tablename__ = "fsm_states"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    bot_id: Mapped[int] = mapped_column(BigInteger)
    state: Mapped[str | None] = mapped_column(String(255))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
