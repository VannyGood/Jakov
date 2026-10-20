from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, Message, User
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import jakov.db.models  # noqa: F401 - register ORM tables
from jakov.db.base import Base
from jakov.db.session import create_engine, create_session_factory

OWNER = 391996029
ADMIN = OWNER
TOKEN = "123456789:AAFakeTokenForTestsOnly_abcdefghijklmn"

# Settings must never read the developer's real .env during tests.
os.environ.update({"BOT_TOKEN": TOKEN, "ADMIN_IDS": str(ADMIN), "TIMEZONE": "UTC",
                   "LLM_ENABLED": "false"})  # tests never call a real model


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
async def session(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with sessions() as s:
        yield s


class FakeSession(BaseSession):
    """Records every Bot API call and answers from per-method handlers."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []
        self.handlers: dict[str, Callable[[Any], Any]] = {}
        self._message_id = 100

    def on(self, method_name: str, handler: Callable[[Any], Any]) -> None:
        self.handlers[method_name] = handler

    def called(self, method_name: str) -> list[Any]:
        return [c for c in self.calls if type(c).__name__ == method_name]

    # Signature fixed by aiogram's BaseSession.
    async def make_request(
        self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None  # noqa: ASYNC109
    ) -> Any:
        self.calls.append(method)
        name = type(method).__name__
        if name in self.handlers:
            result = self.handlers[name](method)
            if isinstance(result, Exception):
                raise result
            return result
        if name in ("SendMessage", "SendPhoto", "SendVideo"):
            self._message_id += 1
            return Message(
                message_id=self._message_id,
                date=datetime.now(UTC),
                chat=Chat(id=method.chat_id, type="private"),
                text=getattr(method, "text", None),
                caption=getattr(method, "caption", None),
            )
        return True

    async def close(self) -> None:
        return None

    async def stream_content(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError


@pytest.fixture
def fake_session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def bot(fake_session: FakeSession) -> Bot:
    from aiogram.client.default import DefaultBotProperties

    return Bot(TOKEN, session=fake_session, default=DefaultBotProperties(parse_mode="HTML"))


async def _no_sleep(_: float) -> None:
    return None


@pytest.fixture
def queue() -> Any:
    from jakov.services.send_queue import SendQueue

    return SendQueue(sleep=_no_sleep)


def tg_user(user_id: int = ADMIN, name: str = "Admin") -> User:
    return User(id=user_id, is_bot=False, first_name=name)
