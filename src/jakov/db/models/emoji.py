from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from jakov.db.base import Base, OwnedMixin, TimestampMixin


class EmojiLibraryItem(OwnedMixin, TimestampMixin, Base):
    """A custom emoji the bot may use. Moods come from `tags` plus the moods data file."""

    __tablename__ = "emoji_library"
    __table_args__ = (
        UniqueConstraint("owner_id", "custom_emoji_id", name="uq_emoji_library_owner_emoji"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    custom_emoji_id: Mapped[str] = mapped_column(String(64))
    fallback: Mapped[str] = mapped_column(String(16))
    pack_name: Mapped[str | None] = mapped_column(String(64), index=True)
    pack_title: Mapped[str | None] = mapped_column(String(128))
    # animated (TGS) | video (WEBM) | static
    kind: Mapped[str] = mapped_column(String(8), default="animated")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # How much the animation actually moves (engine.lottie_motion); None = not measured yet.
    motion: Mapped[float | None] = mapped_column(Float)
