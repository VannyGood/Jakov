"""Shared application objects injected into handlers as `ctx`."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jakov.config import Settings
from jakov.services.emoji_capability import EmojiProbe


@dataclass(slots=True)
class AppContext:
    settings: Settings
    sessions: async_sessionmaker[AsyncSession]
    emoji_probe: EmojiProbe
    started_at: float = field(default_factory=monotonic)
    updates_handled: int = 0

    @property
    def owner_id(self) -> int:
        return self.settings.primary_owner_id

    @property
    def admin_ids(self) -> set[int]:
        return set(self.settings.admin_ids)

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.admin_ids
