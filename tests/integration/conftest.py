"""Shared fixtures: full dispatcher + fake Telegram."""

from collections.abc import Iterator
from datetime import UTC, datetime
from itertools import count
from typing import Any

import pytest
from aiogram import Dispatcher
from aiogram.types import (
    CallbackQuery,
    Chat,
    Message,
    Sticker,
    StickerSet,
    Update,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jakov.app import build_dispatcher
from jakov.config import Settings
from jakov.context import AppContext, build_context
from jakov.handlers import all_routers
from jakov.services.emoji_capability import EmojiProbe
from tests.conftest import ADMIN, TOKEN, FakeSession, tg_user
from tests.factories import BOT_USER

_ids = count(1)


@pytest.fixture
def ctx(sessions: async_sessionmaker[AsyncSession]) -> AppContext:
    settings = Settings(_env_file=None, bot_token=TOKEN, admin_ids=str(ADMIN),  # type: ignore[arg-type]
                        timezone="UTC")
    ctx = build_context(settings, sessions)
    ctx.emoji_probe = EmojiProbe("P")
    return ctx


@pytest.fixture
def dp(ctx: AppContext, fake_session: FakeSession) -> Iterator[Dispatcher]:
    fake_session.on("GetMe", lambda m: BOT_USER)
    fake_session.on("GetStickerSet", lambda m: StickerSet(
        name="P", title="P", sticker_type="custom_emoji", stickers=[Sticker(
            file_id="f", file_unique_id="u", type="custom_emoji", width=1, height=1,
            is_animated=True, is_video=False, emoji="🔥", custom_emoji_id="42")]))
    yield build_dispatcher(ctx)
    for router in all_routers():  # module-level routers can only be attached once
        router._parent_router = None


def text_update(text: str, user_id: int = ADMIN, **extra: Any) -> Update:
    return Update(update_id=next(_ids), message=Message(
        message_id=next(_ids), date=datetime.now(UTC), chat=Chat(id=user_id, type="private"),
        from_user=tg_user(user_id), text=text, **extra))


def button_update(data: str, user_id: int = ADMIN) -> Update:
    menu = Message(message_id=1, date=datetime.now(UTC), chat=Chat(id=user_id, type="private"),
                   text="menu", from_user=BOT_USER)
    return Update(update_id=next(_ids), callback_query=CallbackQuery(
        id=str(next(_ids)), from_user=tg_user(user_id), chat_instance="c", data=data,
        message=menu))


def sent_texts(fake: FakeSession) -> list[str]:
    return [c.text for c in fake.calls if type(c).__name__ in ("SendMessage", "EditMessageText")]


