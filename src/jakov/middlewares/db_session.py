"""Open one DB session per update, commit on success, roll back on error."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jakov.context import AppContext
from jakov.db.session import current_session


class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.sessions() as session:
            data["session"] = session
            token = current_session.set(session)
            try:
                result = await handler(event, data)
            except Exception:
                await session.rollback()
                raise
            finally:
                current_session.reset(token)
            await session.commit()
            return result


class UpdateCounterMiddleware(BaseMiddleware):
    """Counts updates for the periodic health log."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        self.ctx.updates_handled += 1
        return await handler(event, data)
