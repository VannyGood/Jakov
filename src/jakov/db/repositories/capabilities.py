from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.db.base import utcnow
from jakov.db.models import BotCapability


class CapabilityRepo:
    def __init__(self, session: AsyncSession, owner_id: int) -> None:
        self.session = session
        self.owner_id = owner_id

    async def get(self, key: str) -> BotCapability | None:
        return await self.session.scalar(
            select(BotCapability).where(
                BotCapability.owner_id == self.owner_id, BotCapability.key == key
            )
        )

    async def set(self, key: str, supported: bool, detail: str = "") -> BotCapability:
        cap = await self.get(key)
        if cap is None:
            cap = BotCapability(owner_id=self.owner_id, key=key)
            self.session.add(cap)
        cap.supported = supported
        cap.detail = detail
        cap.checked_at = utcnow()
        await self.session.flush()
        return cap
