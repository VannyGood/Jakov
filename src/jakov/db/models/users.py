from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, String, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from jakov.db.base import Base, OwnedMixin, TimestampMixin
from jakov.db.types import UTCDateTime


class User(OwnedMixin, TimestampMixin, Base):
    """A Telegram user who manages the bot (admins today, customers later)."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("owner_id", "tg_user_id", name="uq_users_owner_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String(256), default="")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # IANA zone; None means "use the default TIMEZONE from config".
    timezone: Mapped[str | None] = mapped_column(String(64))
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # Animated emoji in the bot's own menus and replies.
    ui_animated: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # Preferred pack for menu emoji; None = first starter pack.
    ui_emoji_pack: Mapped[str | None] = mapped_column(String(64))
