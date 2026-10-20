from datetime import UTC, datetime

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import GetStickerSet
from aiogram.types import Chat, Message, MessageEntity, Sticker, StickerSet
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.config import PROJECT_ROOT
from jakov.db.repositories.emoji import EmojiRepo
from jakov.engine.catalog import Catalog
from jakov.services.emoji_library import (
    EmojiImportError,
    EmojiLibrary,
    add_from_message,
    custom_emoji_in,
    import_pack,
    normalize_tag,
    parse_pack_ref,
)
from tests.conftest import OWNER, FakeSession

MOODS = Catalog(PROJECT_ROOT / "data").moods


def st(cid: str, emoji: str, animated: bool = True, video: bool = False,
       set_name: str | None = None) -> Sticker:
    return Sticker(file_id=cid, file_unique_id=cid, type="custom_emoji", width=1, height=1,
                   is_animated=animated, is_video=video, emoji=emoji, custom_emoji_id=cid,
                   set_name=set_name)


def pack(fake: FakeSession, kind: str = "custom_emoji") -> None:
    fake.on("GetStickerSet", lambda m: StickerSet(
        name=m.name, title="Dogs Emoji", sticker_type=kind, stickers=[
            st("1", "🔥"),
            st("2", "😂", animated=False, video=True),
            st("3", "💰", animated=False)]))


@pytest.mark.parametrize(("text", "name"), [
    ("https://t.me/addemoji/DogsEmoji", "DogsEmoji"), ("t.me/addstickers/Abc_1", "Abc_1"),
    ("DogsEmoji", "DogsEmoji")])
def test_parse_pack_ref(text: str, name: str) -> None:
    assert parse_pack_ref(text) == name


def test_parse_pack_ref_rejects_garbage() -> None:
    with pytest.raises(EmojiImportError):
        parse_pack_ref("https://evil.com/addemoji/x")


def test_normalize_tag() -> None:
    assert normalize_tag(" Heart-Fire! ") == "heart_fire"


async def test_import_pack_skips_static_and_is_idempotent(
    bot: Bot, fake_session: FakeSession, session: AsyncSession
) -> None:
    pack(fake_session)
    first = await import_pack(bot, session, OWNER, "https://t.me/addemoji/DogsEmoji")
    assert (first.added, first.updated, first.skipped_static) == (2, 0, 1)
    second = await import_pack(bot, session, OWNER, "DogsEmoji")
    assert (second.added, second.updated) == (0, 2)
    items = await EmojiRepo(session, OWNER).all()
    assert {(i.custom_emoji_id, i.kind, i.pack_name) for i in items} == {
        ("1", "animated", "DogsEmoji"), ("2", "video", "DogsEmoji")}


async def test_sticker_pack_is_rejected(bot: Bot, fake_session: FakeSession,
                                        session: AsyncSession) -> None:
    pack(fake_session, kind="regular")
    with pytest.raises(EmojiImportError, match="sticker pack"):
        await import_pack(bot, session, OWNER, "Stickers")


async def test_missing_pack(bot: Bot, fake_session: FakeSession, session: AsyncSession) -> None:
    fake_session.on("GetStickerSet", lambda m: TelegramBadRequest(GetStickerSet(name="x"), "no"))
    with pytest.raises(EmojiImportError, match="can't find"):
        await import_pack(bot, session, OWNER, "Nope")


def emoji_message() -> Message:
    text = "hi 🔥 and 😂🔥"
    return Message(message_id=1, date=datetime.now(UTC), chat=Chat(id=1, type="private"),
                   text=text, entities=[
                       MessageEntity(type="custom_emoji", offset=3, length=2, custom_emoji_id="10"),
                       MessageEntity(type="custom_emoji", offset=10, length=2,
                                     custom_emoji_id="11"),
                       MessageEntity(type="custom_emoji", offset=12, length=2,
                                     custom_emoji_id="10")])


def test_custom_emoji_extraction_uses_utf16_offsets() -> None:
    found = custom_emoji_in(emoji_message())
    assert [(f.custom_emoji_id, f.fallback) for f in found] == [("10", "🔥"), ("11", "😂")]


async def test_add_from_message_tags(bot: Bot, fake_session: FakeSession,
                                     session: AsyncSession) -> None:
    fake_session.on("GetCustomEmojiStickers", lambda m: [st("10", "🔥", set_name="Snoop")])
    new, tagged = await add_from_message(bot, session, OWNER, emoji_message(), "snoop")
    assert (new, tagged) == (2, 2)
    items = {i.custom_emoji_id: i for i in await EmojiRepo(session, OWNER).all()}
    assert items["10"].tags == ["snoop"] and items["10"].pack_name == "Snoop"
    assert items["11"].fallback == "😂"


async def test_add_from_message_without_emoji(bot: Bot, session: AsyncSession) -> None:
    msg = Message(message_id=1, date=datetime.now(UTC), chat=Chat(id=1, type="private"), text="x")
    with pytest.raises(EmojiImportError):
        await add_from_message(bot, session, OWNER, msg, "x")


async def test_library_palette_and_ui_map(bot: Bot, fake_session: FakeSession,
                                          session: AsyncSession) -> None:
    pack(fake_session)
    await import_pack(bot, session, OWNER, "DogsEmoji")
    fake_session.on("GetStickerSet", lambda m: StickerSet(
        name=m.name, title="Base", sticker_type="custom_emoji", stickers=[st("50", "🔥")]))
    await import_pack(bot, session, OWNER, "Base")
    for item in await EmojiRepo(session, OWNER).all():
        item.motion = 300.0  # measured as clearly moving
    library = EmojiLibrary(MOODS, default_ui_pack="Base")
    library.load(await EmojiRepo(session, OWNER).all(active_only=True))
    assert library.size == 3 and library.packs() == ["Base", "DogsEmoji"]
    assert library.ui_map(None)["🔥"] == "50"          # default pack wins
    assert library.ui_map("DogsEmoji")["🔥"] == "1"    # user's chosen pack wins
    assert library.ui_map(None)["😂"] == "2"           # gaps filled from any pack
    assert {e.custom_emoji_id for e in library.palette.candidates("fire")} == {"1", "50"}
    await EmojiRepo(session, OWNER).set_pack_active("DogsEmoji", False)
    library.load(await EmojiRepo(session, OWNER).all(active_only=True))
    assert library.size == 1


async def test_frozen_and_unmeasured_emoji_stay_out_of_menus(
    bot: Bot, fake_session: FakeSession, session: AsyncSession
) -> None:
    pack(fake_session)
    await import_pack(bot, session, OWNER, "DogsEmoji")
    items = {i.custom_emoji_id: i for i in await EmojiRepo(session, OWNER).all()}
    items["1"].motion = 0.0     # frozen 🔥
    items["2"].motion = None    # 😂 not measured yet
    library = EmojiLibrary(MOODS, ui_icons={"⚙️": "1", "🕒": "2"})
    library.load(list(items.values()))
    menu = library.ui_map(None)
    assert "🔥" not in menu and "😂" not in menu and "⚙" not in menu and "🕒" not in menu
    # Posts: frozen excluded, unmeasured still usable.
    assert library.palette.candidates("fire") == []
    assert [e.custom_emoji_id for e in library.palette.candidates("laugh")] == ["2"]


async def test_retired_packs_cannot_be_imported(bot: Bot, session: AsyncSession) -> None:
    with pytest.raises(EmojiImportError, match="blocked"):
        await import_pack(bot, session, OWNER, "https://t.me/addemoji/TopicIcons")


def test_retired_list_matches_config() -> None:
    from jakov.services.emoji_library import RETIRED_LOWER

    retired = Catalog(PROJECT_ROOT / "data").retired_packs
    assert {r.lower() for r in retired} == RETIRED_LOWER
    assert not set(retired) & set(Catalog(PROJECT_ROOT / "data").starter_packs)
