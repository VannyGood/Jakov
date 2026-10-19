from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.db.models import AppState


class StateRepo:
    def __init__(self, session: AsyncSession, owner_id: int) -> None:
        self.session = session
        self.owner_id = owner_id

    async def get(self, key: str, default: Any = None) -> Any:
        row = await self.session.scalar(
            select(AppState).where(AppState.owner_id == self.owner_id, AppState.key == key))
        return default if row is None else row.value

    async def set(self, key: str, value: Any) -> None:
        row = await self.session.scalar(
            select(AppState).where(AppState.owner_id == self.owner_id, AppState.key == key))
        if row is None:
            self.session.add(AppState(owner_id=self.owner_id, key=key, value=value))
        else:
            row.value = value
        await self.session.flush()
