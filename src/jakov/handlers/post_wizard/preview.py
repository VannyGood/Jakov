"""Previews and everything after: pick/rotate, re-roll, edit, options and Send now."""

from __future__ import annotations

import contextlib
import html

from aiogram import Bot, F
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.context import AppContext
from jakov.db.models import Post
from jakov.db.repositories.chats import ChatRepo
from jakov.db.repositories.posts import PostRepo
from jakov.handlers.post_wizard.common import (
    PostWizard,
    load_post,
    router,
    style_label,
    summary_line,
)
from jakov.handlers.views import main_menu_text
from jakov.keyboards.callbacks import PostCb
from jakov.keyboards.common import cancel_kb, main_menu_kb
from jakov.keyboards.posts import (
    chat_picker_kb,
    confirm_send_kb,
    preview_extra_rows,
    published_kb,
    ready_kb,
    review_kb,
)
from jakov.logging_setup import get_logger
from jakov.services.drafts import (
    DraftError,
    generate_variations,
    next_style,
    reroll_emojis,
    set_custom_text,
)
from jakov.services.publisher import (
    PublishError,
    message_link,
    publish,
    render_variation,
    send_rendered,
)
from jakov.utils.telegram import show

log = get_logger(__name__)


def _user_id(target: Message | CallbackQuery) -> int:
    user = target.from_user
    assert user is not None
    return user.id


async def _clear_previews(bot: Bot, chat_id: int, state: FSMContext) -> None:
    data = await state.get_data()
    ids = [int(i) for i in data.get("previews", [])]
    if ids:
        with contextlib.suppress(TelegramAPIError):
            await bot.delete_messages(chat_id, ids)
    await state.update_data(previews=[])


async def show_previews(target: Message | CallbackQuery, bot: Bot, post: Post, ctx: AppContext,
                        session: AsyncSession, state: FSMContext, *, fresh: bool) -> None:
    chat_id = _user_id(target)
    if fresh:
        try:
            await generate_variations(session, ctx.owner_id, post, ctx.generator, ctx.catalog,
                                      ctx.library)
        except DraftError as exc:
            await show(target, f"⚠️ {html.escape(str(exc))}", cancel_kb())
            return
    await _clear_previews(bot, chat_id, state)
    sent: list[int] = []
    for variation in post.variations:
        rendered = await render_variation(session, ctx.owner_id, post, variation, ctx.catalog,
                                          ctx.library, custom_emoji=ctx.ui.dm_supported)
        try:
            message = await send_rendered(
                bot, ctx.queue, chat_id, rendered.html, media_kind=post.media_kind,
                media_file_id=post.media_file_id, buttons=post.buttons,
                link_preview=post.link_preview,
                extra_rows=preview_extra_rows(post, variation.idx))
        except TelegramAPIError as exc:
            log.warning("preview_failed", post_id=post.id, error=str(exc))
            await bot.send_message(chat_id, f"⚠️ Preview #{variation.idx + 1} failed: "
                                            f"{html.escape(str(exc))}")
            continue
        sent.append(message.message_id)
    review = await bot.send_message(
        chat_id,
        f"👀 <b>{len(post.variations)} variations</b> above · {summary_line(post, ctx)}\n\n"
        "Tap <b>✅ Use this</b> under your favourite, or rotate all of them so repeated "
        "posts never look the same.",
        reply_markup=review_kb(post, style_label(post)))
    sent.append(review.message_id)
    await state.set_state(PostWizard.reviewing)
    await state.update_data(post=post.id, previews=sent)


async def _ready_text(post: Post, ctx: AppContext) -> str:
    if post.rotate:
        which = f"🔁 rotating all {len(post.variations)} variations"
    else:
        which = f"✅ variation #{(post.chosen_index or 0) + 1}"
    media = {"photo": "🖼 photo", "video": "🎬 video"}.get(post.media_kind or "", "text only")
    return (f"📝 <b>Post ready</b>\n{summary_line(post, ctx)}\n\n{which}\n"
            f"📎 {media} · 🔗 {len(post.buttons)} button(s)\n\n"
            "Set the options, then send it.")


async def _show_ready(target: Message | CallbackQuery, post: Post, ctx: AppContext) -> None:
    await show(target, await _ready_text(post, ctx), ready_kb(post))


# --- review actions ----------------------------------------------------------

@router.callback_query(PostCb.filter(F.action.in_({"use", "rotate"})))
async def cb_choose(callback: CallbackQuery, callback_data: PostCb, bot: Bot, ctx: AppContext,
                    session: AsyncSession, state: FSMContext) -> None:
    post = await load_post(callback, session, ctx, callback_data.post)
    if post is None:
        return
    if callback_data.action == "use":
        if callback_data.value not in {v.idx for v in post.variations}:
            await callback.answer("That variation is gone; regenerate.", show_alert=True)
            return
        post.rotate, post.chosen_index = False, callback_data.value
    else:
        post.rotate, post.chosen_index = True, None
    post.status = "ready"
    await session.flush()
    await callback.answer("Saved ✅")
    await state.set_state(None)
    # Keep the previews visible; send the ready card as a new message below them.
    await bot.send_message(callback.from_user.id, await _ready_text(post, ctx),
                           reply_markup=ready_kb(post))


@router.callback_query(PostCb.filter(F.action == "regen"))
async def cb_regen(callback: CallbackQuery, callback_data: PostCb, bot: Bot, ctx: AppContext,
                   session: AsyncSession, state: FSMContext) -> None:
    post = await load_post(callback, session, ctx, callback_data.post)
    if post is None:
        return
    await callback.answer("Regenerating…")
    await show_previews(callback, bot, post, ctx, session, state, fresh=True)


@router.callback_query(PostCb.filter(F.action.in_({"emojis", "style"})))
async def cb_emojis(callback: CallbackQuery, callback_data: PostCb, bot: Bot, ctx: AppContext,
                    session: AsyncSession, state: FSMContext) -> None:
    post = await load_post(callback, session, ctx, callback_data.post)
    if post is None:
        return
    if callback_data.action == "style":
        post.emoji_style = next_style(post.emoji_style, ctx.library.packs())
        note = f"Style: {style_label(post)}"
    else:
        note = "New emojis 🎭"
    reroll_emojis(post)
    await session.flush()
    await callback.answer(note)
    await show_previews(callback, bot, post, ctx, session, state, fresh=False)


@router.callback_query(PostCb.filter(F.action == "editpick"))
async def cb_editpick(callback: CallbackQuery, callback_data: PostCb, bot: Bot,
                      ctx: AppContext, session: AsyncSession, state: FSMContext) -> None:
    post = await load_post(callback, session, ctx, callback_data.post)
    if post is None:
        return
    await state.set_state(PostWizard.editing_text)
    await state.update_data(post=post.id, edit_idx=callback_data.value)
    await callback.answer()
    limit = 1024 if post.has_media else 4096
    await bot.send_message(
        callback.from_user.id,
        f"✏️ Send the new text for <b>variation #{callback_data.value + 1}</b> "
        f"(max {limit} characters).\n\n"
        "Formatting and your own animated emoji are kept. You can use spintax like "
        "<code>{Hi|Hey|Hello}</code> and placeholders like <code>{date}</code>.",
        reply_markup=cancel_kb())


@router.message(PostWizard.editing_text, F.text | F.caption)
async def msg_edit_text(message: Message, bot: Bot, ctx: AppContext, session: AsyncSession,
                        state: FSMContext) -> None:
    data = await state.get_data()
    post_id, idx = int(data.get("post", 0)), int(data.get("edit_idx", 0))
    post = await PostRepo(session, ctx.owner_id).get(post_id)
    if post is None:
        await state.clear()
        return
    new_html = message.html_text
    try:
        await set_custom_text(session, ctx.owner_id, post, idx, new_html, ctx.catalog,
                              ctx.library)
    except DraftError as exc:
        await message.answer(f"⚠️ {html.escape(str(exc))}", reply_markup=cancel_kb())
        return
    await message.answer(f"✅ Variation #{idx + 1} updated.")
    await show_previews(message, bot, post, ctx, session, state, fresh=False)


@router.callback_query(PostCb.filter(F.action == "back"))
async def cb_back(callback: CallbackQuery, callback_data: PostCb, bot: Bot, ctx: AppContext,
                  session: AsyncSession, state: FSMContext) -> None:
    post = await load_post(callback, session, ctx, callback_data.post)
    if post is None:
        return
    await callback.answer()
    await show_previews(callback, bot, post, ctx, session, state, fresh=False)


@router.callback_query(PostCb.filter(F.action == "close"))
async def cb_close(callback: CallbackQuery, ctx: AppContext, session: AsyncSession,
                   state: FSMContext) -> None:
    await state.clear()
    await show(callback, "👌 Draft saved.\n\n" + await main_menu_text(
        session, ctx, callback.from_user.id), main_menu_kb())
    await callback.answer()


# --- options -----------------------------------------------------------------

@router.callback_query(PostCb.filter(F.action.in_({"opt_pin", "opt_silent", "opt_preview",
                                                   "ready"})))
async def cb_option(callback: CallbackQuery, callback_data: PostCb, ctx: AppContext,
                    session: AsyncSession) -> None:
    post = await load_post(callback, session, ctx, callback_data.post)
    if post is None:
        return
    if callback_data.action == "opt_pin":
        post.pin = not post.pin
    elif callback_data.action == "opt_silent":
        post.silent = not post.silent
    elif callback_data.action == "opt_preview":
        post.link_preview = not post.link_preview
    await session.flush()
    await _show_ready(callback, post, ctx)
    await callback.answer()


# --- send now ----------------------------------------------------------------

@router.callback_query(PostCb.filter(F.action == "send"))
async def cb_send(callback: CallbackQuery, callback_data: PostCb, ctx: AppContext,
                  session: AsyncSession) -> None:
    post = await load_post(callback, session, ctx, callback_data.post)
    if post is None:
        return
    if post.status != "ready":
        await callback.answer("Pick a variation first.", show_alert=True)
        return
    chats = [c for c in await ChatRepo(session, ctx.owner_id).list(include_inactive=False)
             if c.can_post]
    if not chats:
        await callback.answer("No chats where I can post. Link one in 📡 Channels first.",
                              show_alert=True)
        return
    await show(callback, "📨 <b>Send now</b>: where to?", chat_picker_kb(post, chats))
    await callback.answer()


@router.callback_query(PostCb.filter(F.action == "sendto"))
async def cb_sendto(callback: CallbackQuery, callback_data: PostCb, ctx: AppContext,
                    session: AsyncSession) -> None:
    post = await load_post(callback, session, ctx, callback_data.post)
    chat = await ChatRepo(session, ctx.owner_id).get(callback_data.value)
    if post is None or chat is None:
        await callback.answer("Not available anymore.", show_alert=True)
        return
    emoji_note = {True: "✨ animated emoji work there",
                  False: "normal emoji will be used there",
                  None: "animated emoji not tested there yet; I'll check on send"}
    options = [name for name, on in (("📌 pin", post.pin), ("🔕 silent", post.silent)) if on]
    await show(callback,
               f"Send to <b>{html.escape(chat.name)}</b> now?\n\n"
               f"• {emoji_note[chat.custom_emoji_ok]}\n"
               f"• options: {', '.join(options) or 'none'}",
               confirm_send_kb(post, chat))
    await callback.answer()


@router.callback_query(PostCb.filter(F.action == "sendgo"))
async def cb_sendgo(callback: CallbackQuery, callback_data: PostCb, bot: Bot, ctx: AppContext,
                    session: AsyncSession, state: FSMContext) -> None:
    post = await load_post(callback, session, ctx, callback_data.post)
    chat = await ChatRepo(session, ctx.owner_id).get(callback_data.value)
    if post is None or chat is None:
        await callback.answer("Not available anymore.", show_alert=True)
        return
    await callback.answer("Sending…")
    try:
        record, notes = await publish(bot, session, ctx.owner_id, post, chat, ctx.catalog,
                                      ctx.library, ctx.queue)
    except PublishError as exc:
        hint = "\n\nOpen 📡 Channels → the chat → 🔄 Re-check rights." if exc.lost_access else ""
        await show(callback, f"⚠️ {html.escape(str(exc))}{hint}", ready_kb(post))
        return
    await session.commit()
    await state.clear()
    text = f"✅ <b>Published</b> in {html.escape(chat.name)}."
    if notes:
        text += "\n" + "\n".join(f"ℹ️ {html.escape(n)}" for n in notes)
    link = message_link(chat, record.tg_chat_id, record.message_id)
    await show(callback, text, published_kb(record, link, back_to_list=False))
