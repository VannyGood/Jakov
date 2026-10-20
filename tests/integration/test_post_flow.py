"""End-to-end: the New post wizard, Send now, published posts and the emoji commands."""

from aiogram import Bot, Dispatcher
from aiogram.types import MessageEntity, Sticker, StickerSet
from sqlalchemy import select

from jakov.context import AppContext
from jakov.db.models import Chat, ChatKind, Post, PublishedPost
from jakov.db.repositories.emoji import EmojiRepo
from jakov.keyboards.callbacks import EmojiCb, MenuCb, PostCb, PubCb
from jakov.services.ui_emoji import AnimatedUiMiddleware
from tests.conftest import OWNER, FakeSession
from tests.integration.conftest import button_update, sent_texts, text_update


async def seed_channel(ctx: AppContext) -> int:
    async with ctx.sessions() as s:
        chat = Chat(owner_id=OWNER, tg_chat_id=-1009, kind=ChatKind.CHANNEL, title="Shop",
                    username="shop", can_post=True, can_edit=True, is_active=True,
                    bot_status="administrator", settings={})
        s.add(chat)
        await s.commit()
        return chat.id


async def latest_post(ctx: AppContext) -> Post:
    async with ctx.sessions() as s:
        post = await s.scalar(select(Post).order_by(Post.id.desc()))
        assert post is not None
        return post


async def test_full_wizard_send_edit_delete(dp: Dispatcher, bot: Bot, fake_session: FakeSession,
                                            ctx: AppContext) -> None:
    chat_pk = await seed_channel(ctx)
    feed = dp.feed_update

    await feed(bot, button_update(MenuCb(to="newpost").pack()))
    assert "What kind of post" in sent_texts(fake_session)[-1]
    await feed(bot, button_update(PostCb(action="type", value=1).pack()))  # sell
    post = await latest_post(ctx)
    assert "What are you selling" in sent_texts(fake_session)[-1]
    await feed(bot, text_update("Air Max <90>"))
    await feed(bot, text_update("$99"))
    await feed(bot, button_update(PostCb(action="skip", post=post.id).pack()))  # offer
    await feed(bot, text_update("someday maybe"))  # bad deadline
    assert "read that date" in sent_texts(fake_session)[-1]
    await feed(bot, text_update("in 3 days"))
    assert "Pick a tone" in sent_texts(fake_session)[-1]
    await feed(bot, button_update(PostCb(action="tone", post=post.id, value=0).pack()))
    assert "Almost done" in sent_texts(fake_session)[-1]
    await feed(bot, text_update("Buy - https://shop.io\nbroken line"))
    extras = sent_texts(fake_session)[-1]
    assert "Buttons added" in extras and "broken line" in extras and "Buy" in extras
    fake_session.calls.clear()
    await feed(bot, button_update(PostCb(action="create", post=post.id).pack()))

    previews = fake_session.called("SendMessage")
    texts = [m.text for m in previews]
    post_previews = [m for m in previews if m.reply_markup and any(
        "Use this" in b.text for row in m.reply_markup.inline_keyboard for b in row)]
    assert len(post_previews) == 3
    assert all("air max &lt;90&gt;" in m.text.lower() for m in post_previews)  # escaped
    assert all(m.reply_markup.inline_keyboard[0][0].url == "https://shop.io"
               for m in post_previews)
    assert "3 versions" in texts[-1] and "built-in writer" in texts[-1]

    # Regenerate deletes the old previews.
    await feed(bot, button_update(PostCb(action="regen", post=post.id).pack()))
    assert fake_session.called("DeleteMessages")

    await feed(bot, button_update(PostCb(action="use", post=post.id, value=1).pack()))
    assert "Post ready" in sent_texts(fake_session)[-1]
    await feed(bot, button_update(PostCb(action="opt_pin", post=post.id).pack()))
    assert "Pin on" in str(fake_session.called("EditMessageText")[-1].reply_markup)
    await feed(bot, button_update(PostCb(action="send", post=post.id).pack()))
    # Only one chat linked: straight to the confirmation, no picker.
    assert "Post to <b>Shop</b>" in sent_texts(fake_session)[-1]
    fake_session.calls.clear()
    await feed(bot, button_update(PostCb(action="sendgo", post=post.id, value=chat_pk).pack()))

    channel_msgs = [c for c in fake_session.called("SendMessage") if c.chat_id == -1009]
    assert len(channel_msgs) == 1 and "air max &lt;90&gt;" in channel_msgs[0].text.lower()
    assert "Use this" not in str(channel_msgs[0].reply_markup)  # picker rows never published
    assert fake_session.called("PinChatMessage")
    assert "Published" in sent_texts(fake_session)[-1]
    async with ctx.sessions() as s:
        record = await s.scalar(select(PublishedPost))
        assert record is not None and record.variation_idx == 1 and record.pinned

    # Published list → open → edit → delete
    await feed(bot, text_update("/posts"))
    assert "Published posts" in sent_texts(fake_session)[-1]
    await feed(bot, button_update(PubCb(action="edit", pk=record.id).pack()))
    await feed(bot, text_update("Fresh <b>text</b>", entities=None))
    edit = fake_session.called("EditMessageText")[-1]
    assert edit.chat_id == -1009 and edit.text == "Fresh &lt;b&gt;text&lt;/b&gt;"
    assert "Edited" in sent_texts(fake_session)[-1]
    await feed(bot, button_update(PubCb(action="delete_go", pk=record.id).pack()))
    assert fake_session.called("DeleteMessage")[-1].message_id == record.message_id


async def test_cancel_mid_wizard(dp: Dispatcher, bot: Bot, fake_session: FakeSession,
                                 ctx: AppContext) -> None:
    await dp.feed_update(bot, button_update(PostCb(action="type", value=0).pack()))
    await dp.feed_update(bot, button_update("x"))
    fake_session.calls.clear()
    await dp.feed_update(bot, text_update("Valorant"))  # not captured by the wizard anymore
    assert not any("Step" in t for t in sent_texts(fake_session))


async def test_choice_question_romantic(dp: Dispatcher, bot: Bot, fake_session: FakeSession,
                                        ctx: AppContext) -> None:
    await dp.feed_update(bot, button_update(PostCb(action="type", value=2).pack()))
    post = await latest_post(ctx)
    await dp.feed_update(bot, text_update("Mia"))
    await dp.feed_update(bot, text_update("typed instead of tapping"))
    assert "tap one of the buttons" in sent_texts(fake_session)[-1]
    await dp.feed_update(bot, button_update(PostCb(action="choice", post=post.id,
                                                   value=1).pack()))
    assert "Pick a tone" in sent_texts(fake_session)[-1]
    post = await latest_post(ctx)
    assert post.answers == {"for": "Mia", "mood": "passionate"}


async def test_emoji_commands(dp: Dispatcher, bot: Bot, fake_session: FakeSession,
                              ctx: AppContext) -> None:
    def sticker(cid: str, emoji: str) -> Sticker:
        return Sticker(file_id=cid, file_unique_id=cid, type="custom_emoji", width=1, height=1,
                       is_animated=True, is_video=False, emoji=emoji, custom_emoji_id=cid,
                       set_name="DogsEmoji")

    fake_session.on("GetStickerSet", lambda m: StickerSet(
        name="DogsEmoji", title="Dogs Emoji", sticker_type="custom_emoji",
        stickers=[sticker("1", "🔥"), sticker("2", "😂")]))
    await dp.feed_update(bot, text_update("/emojipack https://t.me/addemoji/DogsEmoji"))
    assert "Dogs Emoji" in sent_texts(fake_session)[-1] and "2 new" in sent_texts(fake_session)[-1]
    assert ctx.library.size == 2

    fake_session.on("GetCustomEmojiStickers", lambda m: [sticker("9", "🐶")])
    await dp.feed_update(bot, text_update("/addemoji Dog"))
    msg_with_emoji = text_update("🐶", entities=[MessageEntity(
        type="custom_emoji", offset=0, length=2, custom_emoji_id="9")])
    await dp.feed_update(bot, msg_with_emoji)
    assert "tagged <b>dog</b>" in sent_texts(fake_session)[-1]
    async with ctx.sessions() as s:
        items = {i.custom_emoji_id: i for i in await EmojiRepo(s, OWNER).all()}
    assert items["9"].tags == ["dog"]
    assert {e.custom_emoji_id for e in ctx.library.palette.candidates("dog")} == {"9"}

    await dp.feed_update(bot, button_update(EmojiCb(action="moods").pack()))
    assert "Moods" in sent_texts(fake_session)[-1]


async def test_menus_are_animated_for_admin(dp: Dispatcher, bot: Bot, fake_session: FakeSession,
                                            ctx: AppContext) -> None:
    fake_session.on("GetStickerSet", lambda m: StickerSet(
        name="RestrictedEmoji", title="Animated", sticker_type="custom_emoji",
        stickers=[Sticker(file_id="a", file_unique_id="a", type="custom_emoji", width=1,
                          height=1, is_animated=True, is_video=False, emoji="📣",
                          custom_emoji_id="555")]))
    await dp.feed_update(bot, text_update("/emojipack RestrictedEmoji"))
    async with ctx.sessions() as s:  # as measured by the motion backfill
        for item in await EmojiRepo(s, OWNER).all():
            item.motion = 250.0
        await s.commit()
    await ctx.reload_emoji()
    ctx.ui.dm_supported = True
    bot.session.middleware(AnimatedUiMiddleware(ctx.ui))
    fake_session.calls.clear()
    await dp.feed_update(bot, button_update(MenuCb(to="main").pack()))
    edit = fake_session.called("EditMessageText")[-1]
    buttons = [b for row in edit.reply_markup.inline_keyboard for b in row]
    channels = next(b for b in buttons if b.text == "Channels")
    assert channels.icon_custom_emoji_id == "555"  # alive library emoji animate the button
    create = next(b for b in buttons if b.text.endswith("Create a post"))
    assert create.style == "primary"
