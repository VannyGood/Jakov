"""📰 Published posts: open, edit text, delete."""

from __future__ import annotations

import html

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.context import AppContext
from jakov.db.models import Chat, PublishedPost
from jakov.db.repositories.chats import ChatRepo
from jakov.db.repositories.posts import PublishedRepo
from jakov.engine.limits import visible_text
from jakov.handlers.views import zone_for
from jakov.keyboards.callbacks import MenuCb, PubCb
from jakov.keyboards.common import cancel_kb
from jakov.keyboards.posts import confirm_delete_kb, published_kb, published_list_kb
from jakov.services.publisher import PublishError, delete_published, edit_published, message_link
from jakov.services.timezones import effective_zone
from jakov.utils.telegram import show
from jakov.utils.time import format_local

router = Router(name="published")
router.message.filter(F.chat.type == ChatType.PRIVATE)
PAGE = 8


class PublishedStates(StatesGroup):
    editing = State()


def _snippet(record: PublishedPost, size: int = 40) -> str:
    text = " ".join(visible_text(record.html).split())
    return text[:size] + ("…" if len(text) > size else "")


async def _list(target: Message | CallbackQuery, ctx: AppContext, session: AsyncSession,
                page: int) -> None:
    rows = await PublishedRepo(session, ctx.owner_id).recent(page * PAGE, PAGE + 1)
    has_more = len(rows) > PAGE
    items = [(record, f"{chat.name if chat else 'removed chat'} · {_snippet(record, 30)}")
             for record, chat in rows[:PAGE]]
    text = "📰 <b>Published posts</b>" + ("" if items or page else "\n\nNothing published yet.")
    await show(target, text, published_list_kb(items, page, has_more))


@router.message(Command("posts"))
async def cmd_posts(message: Message, ctx: AppContext, session: AsyncSession,
                    state: FSMContext) -> None:
    await state.clear()
    await _list(message, ctx, session, 0)


@router.callback_query(MenuCb.filter(F.to == "published"))
async def cb_menu(callback: CallbackQuery, ctx: AppContext, session: AsyncSession,
                  state: FSMContext) -> None:
    await state.clear()
    await _list(callback, ctx, session, 0)
    await callback.answer()


@router.callback_query(PubCb.filter(F.action == "list"))
async def cb_list(callback: CallbackQuery, callback_data: PubCb, ctx: AppContext,
                  session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await _list(callback, ctx, session, max(0, callback_data.page))
    await callback.answer()


async def _load(callback: CallbackQuery, ctx: AppContext, session: AsyncSession,
                pk: int) -> tuple[PublishedPost, Chat | None] | None:
    record = await PublishedRepo(session, ctx.owner_id).get(pk)
    if record is None:
        await callback.answer("Not found.", show_alert=True)
        return None
    chat = await ChatRepo(session, ctx.owner_id).get(record.chat_id) if record.chat_id else None
    return record, chat


async def _card(target: Message | CallbackQuery, record: PublishedPost, chat: Chat | None,
                ctx: AppContext, session: AsyncSession, user_id: int, prefix: str = "") -> None:
    zone_name, _ = await zone_for(session, ctx, user_id)
    zone = effective_zone(zone_name, ctx.settings.timezone)
    lines = [
        f"📰 <b>{html.escape(chat.name if chat else 'Removed chat')}</b>",
        f"Sent: {format_local(record.sent_at, zone)}",
    ]
    if record.edited_at:
        lines.append(f"Edited: {format_local(record.edited_at, zone)}")
    if record.deleted_at:
        lines.append("🗑 Deleted from the chat")
    if record.pinned:
        lines.append("📌 Pinned")
    lines.append(f"\n<i>{html.escape(_snippet(record, 300))}</i>")
    link = message_link(chat, record.tg_chat_id, record.message_id)
    await show(target, prefix + "\n".join(lines), published_kb(record, link))


@router.callback_query(PubCb.filter(F.action == "open"))
async def cb_open(callback: CallbackQuery, callback_data: PubCb, ctx: AppContext,
                  session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    loaded = await _load(callback, ctx, session, callback_data.pk)
    if loaded:
        await _card(callback, *loaded, ctx, session, callback.from_user.id)
        await callback.answer()


@router.callback_query(PubCb.filter(F.action == "edit"))
async def cb_edit(callback: CallbackQuery, callback_data: PubCb, ctx: AppContext,
                  session: AsyncSession, state: FSMContext) -> None:
    loaded = await _load(callback, ctx, session, callback_data.pk)
    if loaded is None:
        return
    record, _ = loaded
    await state.set_state(PublishedStates.editing)
    await state.update_data(pk=record.id)
    limit = 1024 if record.media_kind else 4096
    await show(callback, "✏️ Send the new text for this post "
               f"(max {limit} characters). Formatting and animated emoji are kept.\n\n"
               "Current text, to copy and adjust:", cancel_kb())
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(record.html)


@router.message(PublishedStates.editing, F.text | F.caption)
async def msg_edit(message: Message, bot: Bot, ctx: AppContext, session: AsyncSession,
                   state: FSMContext) -> None:
    assert message.from_user is not None
    data = await state.get_data()
    record = await PublishedRepo(session, ctx.owner_id).get(int(data.get("pk", 0)))
    if record is None:
        await state.clear()
        return
    chat = await ChatRepo(session, ctx.owner_id).get(record.chat_id) if record.chat_id else None
    try:
        await edit_published(bot, record, message.html_text)
    except PublishError as exc:
        await message.answer(f"⚠️ {html.escape(str(exc))}", reply_markup=cancel_kb())
        return
    await state.clear()
    await _card(message, record, chat, ctx, session, message.from_user.id, "✅ Edited.\n\n")


@router.callback_query(PubCb.filter(F.action == "delete"))
async def cb_delete(callback: CallbackQuery, callback_data: PubCb, ctx: AppContext,
                    session: AsyncSession) -> None:
    loaded = await _load(callback, ctx, session, callback_data.pk)
    if loaded:
        await show(callback, "🗑 Delete this post from the chat? This can't be undone.",
                   confirm_delete_kb(loaded[0]))
        await callback.answer()


@router.callback_query(PubCb.filter(F.action == "delete_go"))
async def cb_delete_go(callback: CallbackQuery, callback_data: PubCb, bot: Bot,
                       ctx: AppContext, session: AsyncSession) -> None:
    loaded = await _load(callback, ctx, session, callback_data.pk)
    if loaded is None:
        return
    record, chat = loaded
    try:
        await delete_published(bot, record)
    except PublishError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await session.flush()
    await _card(callback, record, chat, ctx, session, callback.from_user.id, "🗑 Deleted.\n\n")
    await callback.answer("Deleted")
