"""Feed real updates through the full dispatcher with a fake Telegram."""

from collections.abc import Iterator
from datetime import UTC, datetime
from itertools import count
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import (
    CallbackQuery,
    Chat,
    Message,
    MessageEntity,
    Sticker,
    StickerSet,
    Update,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jakov.app import build_dispatcher
from jakov.config import Settings
from jakov.context import AppContext
from jakov.db.repositories.chats import ChatRepo
from jakov.db.repositories.users import UserRepo
from jakov.handlers import all_routers
from jakov.keyboards.callbacks import ChannelCb, SettingsCb
from jakov.services.emoji_capability import EmojiProbe
from tests.conftest import ADMIN, OWNER, TOKEN, FakeSession, tg_user
from tests.factories import BOT_ID, BOT_USER, admin_member, full_chat, owner_member

_ids = count(1)


@pytest.fixture
def ctx(sessions: async_sessionmaker[AsyncSession]) -> AppContext:
    settings = Settings(_env_file=None, bot_token=TOKEN, admin_ids=str(ADMIN),  # type: ignore[arg-type]
                        timezone="UTC")
    return AppContext(settings=settings, sessions=sessions, emoji_probe=EmojiProbe("P"))


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


async def test_stranger_gets_no_response(dp: Dispatcher, bot: Bot,
                                         fake_session: FakeSession) -> None:
    await dp.feed_update(bot, text_update("/start", user_id=777))
    await dp.feed_update(bot, button_update("m:main", user_id=777))
    assert fake_session.calls == []


async def test_admin_start_runs_emoji_probe_and_shows_menu(
    dp: Dispatcher, bot: Bot, fake_session: FakeSession, ctx: AppContext
) -> None:
    fake_session.on("SendMessage", lambda m: Message(
        message_id=next(_ids), date=datetime.now(UTC), chat=Chat(id=m.chat_id, type="private"),
        text=m.text, entities=[MessageEntity(type="custom_emoji", offset=0, length=1,
                                             custom_emoji_id="42")]))
    await dp.feed_update(bot, text_update("/start"))
    texts = sent_texts(fake_session)
    assert any('emoji-id="42"' in t for t in texts)
    assert any("Animated custom emoji work" in t for t in texts)
    assert any("Jakov control panel" in t for t in texts)
    assert any("Set my timezone" in str(c.reply_markup) for c in fake_session.calls
               if type(c).__name__ == "SendMessage")
    # Second /start doesn't re-run the probe.
    fake_session.calls.clear()
    await dp.feed_update(bot, text_update("/start"))
    assert fake_session.called("GetStickerSet") == []
    async with ctx.sessions() as s:
        user = await UserRepo(s, OWNER).get(ADMIN)
        assert user is not None and user.is_admin


async def test_link_channel_by_username_flow(
    dp: Dispatcher, bot: Bot, fake_session: FakeSession, ctx: AppContext
) -> None:
    fake_session.on("GetChat", lambda m: full_chat())
    fake_session.on("GetChatMember", lambda m: admin_member() if m.user_id == BOT_ID
                    else owner_member(tg_user()))
    await dp.feed_update(bot, button_update(ChannelCb(action="add").pack()))
    assert "Link a channel" in sent_texts(fake_session)[-1]
    await dp.feed_update(bot, text_update("@mychan"))
    assert "Linked!" in sent_texts(fake_session)[-1]
    async with ctx.sessions() as s:
        chats = await ChatRepo(s, OWNER).list()
    assert [c.tg_chat_id for c in chats] == [-1001]


async def test_wizard_state_survives_and_cancel_clears(
    dp: Dispatcher, bot: Bot, fake_session: FakeSession
) -> None:
    await dp.feed_update(bot, button_update(ChannelCb(action="add").pack()))
    await dp.feed_update(bot, text_update("not a valid ref!!"))
    assert "Try again or cancel" in sent_texts(fake_session)[-1]
    await dp.feed_update(bot, button_update("x"))
    assert "Cancelled" in sent_texts(fake_session)[-1]
    fake_session.calls.clear()
    await dp.feed_update(bot, text_update("@mychan"))  # no longer in the wizard
    assert fake_session.called("GetChat") == []


async def test_timezone_typed(dp: Dispatcher, bot: Bot, fake_session: FakeSession,
                              ctx: AppContext) -> None:
    await dp.feed_update(bot, text_update("/start"))
    await dp.feed_update(bot, button_update(SettingsCb(action="tz_type").pack()))
    await dp.feed_update(bot, text_update("tokyo"))
    assert "Asia/Tokyo" in sent_texts(fake_session)[-1]
    async with ctx.sessions() as s:
        user = await UserRepo(s, OWNER).get(ADMIN)
        assert user is not None and user.timezone == "Asia/Tokyo"


async def test_handler_crash_notifies_admin(dp: Dispatcher, bot: Bot,
                                            fake_session: FakeSession) -> None:
    fake_session.on("GetChat", lambda m: RuntimeError(f"boom {TOKEN}"))
    await dp.feed_update(bot, button_update(ChannelCb(action="add").pack()))
    await dp.feed_update(bot, text_update("@mychan"))
    alert = sent_texts(fake_session)[-1]
    assert "Something went wrong" in alert and "RuntimeError" in alert
    assert TOKEN not in alert
