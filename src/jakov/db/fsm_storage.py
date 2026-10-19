"""aiogram FSM storage backed by the database, so wizards survive restarts."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, DefaultKeyBuilder, KeyBuilder, StorageKey
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jakov.db.base import utcnow
from jakov.db.models import FsmState
from jakov.db.session import current_session


class SQLAlchemyStorage(BaseStorage):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        owner_id: int,
        key_builder: KeyBuilder | None = None,
    ) -> None:
        self._sessions = session_factory
        self._owner_id = owner_id
        self._keys = key_builder or DefaultKeyBuilder(with_destiny=True)

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        """Join the current update's transaction if there is one, else use a short one."""
        shared = current_session.get()
        if shared is not None:
            yield shared
            await shared.flush()
            return
        async with self._sessions.begin() as own:
            yield own

    async def _row(self, session: AsyncSession, key: StorageKey) -> FsmState | None:
        return await session.get(FsmState, self._keys.build(key))

    async def _upsert(self, key: StorageKey, **values: Any) -> None:
        async with self._session() as session:
            row = await self._row(session, key)
            if row is None:
                row = FsmState(key=self._keys.build(key), bot_id=key.bot_id,
                               owner_id=self._owner_id, data={})
                session.add(row)
            for name, value in values.items():
                setattr(row, name, value)
            row.updated_at = utcnow()
            if row.state is None and not row.data:
                # Nothing left to remember: drop the row instead of storing an empty one.
                if inspect(row).persistent:
                    await session.delete(row)
                else:
                    session.expunge(row)

    async def set_state(self, key: StorageKey, state: str | State | None = None) -> None:
        value = state.state if isinstance(state, State) else state
        await self._upsert(key, state=value)

    async def get_state(self, key: StorageKey) -> str | None:
        async with self._session() as session:
            row = await self._row(session, key)
            return row.state if row else None

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        await self._upsert(key, data=dict(data))

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        async with self._session() as session:
            row = await self._row(session, key)
            return dict(row.data) if row and row.data else {}

    async def close(self) -> None:
        return None
