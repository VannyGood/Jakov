"""Feed real updates through the full dispatcher with a fake Telegram."""

from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.types import Chat, Message, MessageEntity

from jakov.context import AppContext
from jakov.db.repositories.chats import ChatRepo
from jakov.db.repositories.users import UserRepo
from jakov.keyboards.callbacks import ChannelCb, SettingsCb
from tests.conftest import ADMIN, OWNER, TOKEN, FakeSession, tg_user
from tests.factories import BOT_ID, admin_member, full_chat, owner_member
from tests.integration.conftest import _ids, button_update, sent_texts, text_update


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
    assert any("Welcome to Jakov" in t for t in texts)  # no channel linked yet
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
