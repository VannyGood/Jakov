import random
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import PinChatMessage, SendMessage
from aiogram.types import Chat as TgChat
from aiogram.types import Message, MessageEntity
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.config import PROJECT_ROOT
from jakov.db.models import Chat, ChatKind, EmojiLibraryItem, Post
from jakov.db.repositories.posts import PostRepo
from jakov.engine.catalog import Catalog
from jakov.engine.text_generator import TemplateGenerator
from jakov.services.drafts import (
    DraftError,
    generate_variations,
    next_style,
    reroll_emojis,
    set_custom_text,
)
from jakov.services.emoji_library import EmojiLibrary
from jakov.services.publisher import (
    PublishError,
    delete_published,
    edit_published,
    message_link,
    pick_variation,
    publish,
)
from jakov.services.send_queue import SendQueue
from tests.conftest import ADMIN, OWNER, FakeSession

CATALOG = Catalog(PROJECT_ROOT / "data")


def library() -> EmojiLibrary:
    lib = EmojiLibrary(CATALOG.moods)
    lib.load([EmojiLibraryItem(custom_emoji_id=str(i), fallback=fb, pack_name="P",
                               kind="animated", tags=[], is_active=True)
              for i, fb in enumerate(["🔥", "💰", "🛒", "⏰", "👉", "🏷", "💎", "✨", "🚀"])])
    return lib


async def make_post(session: AsyncSession, **kw: Any) -> Post:
    defaults: dict[str, Any] = dict(created_by=ADMIN, post_type="sell", tone="hype",
                                    answers={"product": "Air Max <90>", "price": "$99"},
                                    moments={}, buttons=[], timezone="Europe/Belgrade")
    choice = {k: kw.pop(k) for k in ("chosen_index", "rotate", "status") if k in kw}
    defaults.update(kw)
    post = await PostRepo(session, OWNER).add(Post(**defaults))
    await generate_variations(session, OWNER, post, TemplateGenerator(CATALOG, random.Random(1)),
                              CATALOG, library())
    for key, value in choice.items():  # generating resets the choice, so apply it after
        setattr(post, key, value)
    return post


def channel(**kw: Any) -> Chat:
    base: dict[str, Any] = dict(owner_id=OWNER, tg_chat_id=-1001, kind=ChatKind.CHANNEL,
                                title="Chan", username="chan", can_post=True, is_active=True,
                                settings={})
    base.update(kw)
    return Chat(**base)


def echo_with_custom(keep: bool) -> Any:
    def handler(m: SendMessage) -> Message:
        entities = [MessageEntity(type="custom_emoji", offset=0, length=2, custom_emoji_id="1")]
        return Message(message_id=555, date=datetime.now(UTC),
                       chat=TgChat(id=m.chat_id, type="channel"), text="x",
                       entities=entities if keep else None)
    return handler


async def test_three_variations_with_escaped_answers(session: AsyncSession) -> None:
    post = await make_post(session)
    assert [v.idx for v in post.variations] == [0, 1, 2]
    assert len({v.template for v in post.variations}) == 3
    assert all("{" in v.template for v in post.variations)  # stays a template


async def test_too_long_answers_fail_clearly(session: AsyncSession) -> None:
    with pytest.raises(DraftError, match="1024"):
        await make_post(session, post_type="custom",
                        answers={"topic": "t", "message": "x" * 1100},
                        media_kind="photo", media_file_id="F")


async def test_publish_records_and_escapes(bot: Bot, fake_session: FakeSession,
                                           session: AsyncSession, queue: SendQueue) -> None:
    post = await make_post(session, chosen_index=1, status="ready")
    chat = channel(custom_emoji_ok=True)
    session.add(chat)
    fake_session.on("SendMessage", echo_with_custom(keep=True))
    record, notes = await publish(bot, session, OWNER, post, chat, CATALOG, library(), queue)
    sent = fake_session.called("SendMessage")[0]
    assert "Air Max &lt;90&gt;" in sent.text and "<tg-emoji" in sent.text
    assert record.message_id == 555 and record.variation_idx == 1 and notes == []
    assert record.custom_emoji_used and post.last_variation_index == 1


async def test_stripped_custom_emoji_marks_chat(bot: Bot, fake_session: FakeSession,
                                                session: AsyncSession,
                                              queue: SendQueue) -> None:
    post = await make_post(session, chosen_index=0, status="ready")
    chat = channel(custom_emoji_ok=None)
    session.add(chat)
    fake_session.on("SendMessage", echo_with_custom(keep=False))
    _, notes = await publish(bot, session, OWNER, post, chat, CATALOG, library(), queue)
    assert chat.custom_emoji_ok is False and "normal emoji" in notes[0]
    # Next post to that chat goes out with plain emoji only.
    await publish(bot, session, OWNER, post, chat, CATALOG, library(), queue)
    assert "<tg-emoji" not in fake_session.called("SendMessage")[1].text


async def test_rotation_cycles_variations(session: AsyncSession) -> None:
    post = await make_post(session, rotate=True, status="ready")
    seen = []
    for _ in range(4):
        variation = pick_variation(post)
        seen.append(variation.idx)
        post.last_variation_index = variation.idx
    assert seen == [0, 1, 2, 0]


async def test_media_pin_and_silent(bot: Bot, fake_session: FakeSession,
                                    session: AsyncSession, queue: SendQueue) -> None:
    post = await make_post(session, chosen_index=0, status="ready", media_kind="photo",
                           media_file_id="PHOTO", pin=True, silent=True,
                           buttons=[{"text": "Buy", "url": "https://shop.io"}])
    chat = channel()
    session.add(chat)
    record, _ = await publish(bot, session, OWNER, post, chat, CATALOG, library(), queue)
    photo = fake_session.called("SendPhoto")[0]
    assert photo.photo == "PHOTO" and photo.disable_notification is True
    assert photo.reply_markup.inline_keyboard[0][0].url == "https://shop.io"
    pin = fake_session.called("PinChatMessage")[0]
    assert pin.message_id == record.message_id and record.pinned


async def test_pin_failure_is_a_note_not_an_error(bot: Bot, fake_session: FakeSession,
                                                  session: AsyncSession,
                                              queue: SendQueue) -> None:
    post = await make_post(session, chosen_index=0, status="ready", pin=True)
    chat = channel()
    session.add(chat)
    fake_session.on("PinChatMessage", lambda m: TelegramBadRequest(
        PinChatMessage(chat_id=1, message_id=1), "not enough rights to pin"))
    record, notes = await publish(bot, session, OWNER, post, chat, CATALOG, library(), queue)
    assert not record.pinned and any("Couldn't pin" in n for n in notes)


async def test_forbidden_raises_publish_error(bot: Bot, fake_session: FakeSession,
                                              session: AsyncSession,
                                              queue: SendQueue) -> None:
    post = await make_post(session, chosen_index=0, status="ready")
    chat = channel()
    session.add(chat)
    fake_session.on("SendMessage", lambda m: TelegramForbiddenError(m, "bot was kicked"))
    with pytest.raises(PublishError) as info:
        await publish(bot, session, OWNER, post, chat, CATALOG, library(), queue)
    assert info.value.lost_access


async def test_inactive_chat_refused(bot: Bot, session: AsyncSession, queue: SendQueue) -> None:
    post = await make_post(session, chosen_index=0, status="ready")
    with pytest.raises(PublishError, match="rights"):
        await publish(bot, session, OWNER, post, channel(is_active=False), CATALOG, library(),
                      queue)


async def test_edit_and_delete_published(bot: Bot, fake_session: FakeSession,
                                         session: AsyncSession, queue: SendQueue) -> None:
    post = await make_post(session, chosen_index=0, status="ready",
                           buttons=[{"text": "Go", "url": "https://go.io"}])
    chat = channel()
    session.add(chat)
    record, _ = await publish(bot, session, OWNER, post, chat, CATALOG, library(), queue)
    await edit_published(bot, record, "<b>New</b>")
    edit = fake_session.called("EditMessageText")[0]
    assert edit.text == "<b>New</b>" and edit.reply_markup.inline_keyboard[0][0].url == \
        "https://go.io"
    assert record.html == "<b>New</b>" and record.edited_at is not None
    await delete_published(bot, record)
    assert fake_session.called("DeleteMessage")[0].message_id == record.message_id
    assert record.deleted_at is not None


async def test_edit_too_long_rejected(bot: Bot, session: AsyncSession, queue: SendQueue) -> None:
    post = await make_post(session, chosen_index=0, status="ready", media_kind="photo",
                           media_file_id="P")
    chat = channel()
    session.add(chat)
    record, _ = await publish(bot, session, OWNER, post, chat, CATALOG, library(), queue)
    with pytest.raises(PublishError, match="1024"):
        await edit_published(bot, record, "x" * 1500)


async def test_custom_text_and_reroll(session: AsyncSession) -> None:
    post = await make_post(session)
    await set_custom_text(session, OWNER, post, 1, "<b>{Hi|Hey}</b> {product}!", CATALOG,
                          library())
    v = post.variations[1]
    assert v.is_custom and v.resolved in ("<b>Hi</b> {product}!", "<b>Hey</b> {product}!")
    seeds = [x.emoji_seed for x in post.variations]
    reroll_emojis(post)
    assert seeds != [x.emoji_seed for x in post.variations]
    with pytest.raises(DraftError, match="4096"):
        await set_custom_text(session, OWNER, post, 0, "y" * 5000, CATALOG, library())


def test_next_style_cycle() -> None:
    assert next_style(None, ["A", "B"]) == "A"
    assert next_style("A", ["A", "B"]) == "B"
    assert next_style("B", ["A", "B"]) is None
    assert next_style("gone", ["A"]) == "A"
    assert next_style(None, []) is None


def test_message_links() -> None:
    assert message_link(channel(), -1001, 5) == "https://t.me/chan/5"
    assert message_link(None, -1001234567, 9) == "https://t.me/c/1234567/9"
