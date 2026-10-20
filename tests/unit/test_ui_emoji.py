from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from jakov.config import PROJECT_ROOT
from jakov.db.models import EmojiLibraryItem
from jakov.engine.catalog import Catalog
from jakov.services.emoji_library import EmojiLibrary
from jakov.services.ui_emoji import AnimatedUiMiddleware, UiEmojiService, UiPrefs, raw_output
from tests.conftest import ADMIN, FakeSession


def service() -> UiEmojiService:
    library = EmojiLibrary(Catalog(PROJECT_ROOT / "data").moods, default_ui_pack="P")
    library.load([EmojiLibraryItem(custom_emoji_id="77", fallback="🔥", pack_name="P",
                                   kind="animated", tags=[], is_active=True, motion=500.0)])
    svc = UiEmojiService(library, {ADMIN})
    svc.dm_supported = True
    return svc


def kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔥 Hot", callback_data="a"),
        InlineKeyboardButton(text="Plain", callback_data="b")]])


async def test_admin_messages_get_animated(bot: Bot, fake_session: FakeSession) -> None:
    bot.session.middleware(AnimatedUiMiddleware(service()))
    await bot.send_message(ADMIN, "<b>🔥 Menu</b>", reply_markup=kb())
    sent = fake_session.called("SendMessage")[0]
    assert sent.text == '<b><tg-emoji emoji-id="77">🔥</tg-emoji> Menu</b>'
    button = sent.reply_markup.inline_keyboard[0][0]
    assert (button.icon_custom_emoji_id, button.text) == ("77", "Hot")
    assert sent.reply_markup.inline_keyboard[0][1].icon_custom_emoji_id is None


async def test_non_admin_chats_untouched(bot: Bot, fake_session: FakeSession) -> None:
    bot.session.middleware(AnimatedUiMiddleware(service()))
    await bot.send_message(-100123, "🔥 post")
    assert fake_session.called("SendMessage")[0].text == "🔥 post"


async def test_raw_output_bypasses(bot: Bot, fake_session: FakeSession) -> None:
    bot.session.middleware(AnimatedUiMiddleware(service()))
    with raw_output():
        await bot.send_message(ADMIN, "🔥 preview", reply_markup=kb())
    sent = fake_session.called("SendMessage")[0]
    assert sent.text == "🔥 preview"
    assert sent.reply_markup.inline_keyboard[0][0].icon_custom_emoji_id is None


async def test_disabled_by_user_or_capability(bot: Bot, fake_session: FakeSession) -> None:
    svc = service()
    svc.prefs[ADMIN] = UiPrefs(animated=False)
    bot.session.middleware(AnimatedUiMiddleware(svc))
    await bot.send_message(ADMIN, "🔥")
    svc.prefs.clear()
    svc.dm_supported = False
    await bot.send_message(ADMIN, "🔥")
    assert [c.text for c in fake_session.called("SendMessage")] == ["🔥", "🔥"]


async def test_markdown_text_not_rewritten(bot: Bot, fake_session: FakeSession) -> None:
    bot.session.middleware(AnimatedUiMiddleware(service()))
    await bot.send_message(ADMIN, "🔥 *x*", parse_mode="MarkdownV2")
    assert fake_session.called("SendMessage")[0].text == "🔥 *x*"
