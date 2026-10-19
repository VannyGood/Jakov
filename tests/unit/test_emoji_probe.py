from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, MessageEntity, Sticker, StickerSet

from jakov.services.emoji_capability import EmojiProbe, has_custom_emoji, tg_emoji
from tests.conftest import FakeSession


def sticker(emoji: str, cid: str) -> Sticker:
    return Sticker(file_id=cid, file_unique_id=cid, type="custom_emoji", width=100, height=100,
                   is_animated=True, is_video=False, emoji=emoji, custom_emoji_id=cid)


def pack(fake: FakeSession) -> None:
    fake.on("GetStickerSet", lambda m: StickerSet(
        name=m.name, title="Pack", sticker_type="custom_emoji",
        stickers=[sticker("😀", "111"), sticker("🔥", "222")]))


def reply(entities: list[MessageEntity] | None) -> Any:
    return lambda m: Message(message_id=5, date=datetime.now(UTC),
                             chat=Chat(id=m.chat_id, type="private"), text="x", entities=entities)


def test_tg_emoji_escapes() -> None:
    assert tg_emoji('1"2', "<") == '<tg-emoji emoji-id="1&quot;2">&lt;</tg-emoji>'


async def test_supported_when_entity_survives(bot: Bot, fake_session: FakeSession) -> None:
    pack(fake_session)
    fake_session.on("SendMessage", reply([MessageEntity(
        type="custom_emoji", offset=0, length=2, custom_emoji_id="222")]))
    result = await EmojiProbe("P").probe(bot, 1, "test")
    assert result.supported
    sent = fake_session.called("SendMessage")[0]
    assert 'emoji-id="222">🔥</tg-emoji>' in sent.text  # prefers 🔥


async def test_unsupported_when_telegram_strips_it(bot: Bot, fake_session: FakeSession) -> None:
    pack(fake_session)
    fake_session.on("SendMessage", reply(None))
    result = await EmojiProbe("P").probe(bot, 1, "test")
    assert not result.supported and "replaced" in result.detail and result.message is not None


async def test_unsupported_when_rejected(bot: Bot, fake_session: FakeSession) -> None:
    pack(fake_session)
    fake_session.on("SendMessage",
                    lambda m: TelegramBadRequest(SendMessage(chat_id=1, text="x"), "ENTITY_BAD"))
    result = await EmojiProbe("P").probe(bot, 1, "test")
    assert not result.supported and "ENTITY_BAD" in result.detail


async def test_missing_pack_is_reported_not_raised(bot: Bot, fake_session: FakeSession) -> None:
    from aiogram.methods import GetStickerSet

    fake_session.on("GetStickerSet",
                    lambda m: TelegramBadRequest(GetStickerSet(name="x"), "STICKERSET_INVALID"))
    result = await EmojiProbe("Nope").probe(bot, 1, "test")
    assert not result.supported and "unavailable" in result.detail
    assert fake_session.called("SendMessage") == []


async def test_sample_is_cached(bot: Bot, fake_session: FakeSession) -> None:
    pack(fake_session)
    probe = EmojiProbe("P")
    await probe.sample(bot)
    await probe.sample(bot)
    assert len(fake_session.called("GetStickerSet")) == 1


def test_has_custom_emoji_checks_captions() -> None:
    msg = Message(message_id=1, date=datetime.now(UTC), chat=Chat(id=1, type="private"),
                  caption="c", caption_entities=[MessageEntity(
                      type="custom_emoji", offset=0, length=1, custom_emoji_id="1")])
    assert has_custom_emoji(msg)
