"""/channels: link, inspect, rename, test and remove channels and groups."""

from __future__ import annotations

import html

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, MessageOriginChannel, MessageOriginChat
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.context import AppContext
from jakov.db.models import Chat
from jakov.db.repositories.chats import ChatRepo
from jakov.handlers.states import ChannelStates
from jakov.handlers.views import chat_card, zone_for
from jakov.keyboards.callbacks import ChannelCb, MenuCb
from jakov.keyboards.channels import (
    channel_detail_kb,
    channels_list_kb,
    confirm_emoji_test_kb,
    confirm_remove_kb,
)
from jakov.keyboards.common import cancel_kb
from jakov.logging_setup import get_logger
from jakov.services.channels import LinkError, link_chat, refresh_chat
from jakov.utils.chat_refs import ChatRefError, parse_chat_ref
from jakov.utils.telegram import show

log = get_logger(__name__)
router = Router(name="channels")
router.message.filter(F.chat.type == ChatType.PRIVATE)

ADD_PROMPT = (
    "➕ <b>Link a channel or group</b>\n\n"
    "1. Add me as an <b>admin</b> there (for channels: with <i>Post</i> and <i>Edit</i> rights).\n"
    "2. Then either <b>forward any message</b> from it here, or send its <b>@username</b>, "
    "<b>t.me link</b> or <b>numeric ID</b>.\n\n"
    "Tip: adding me as admin is often enough. I link the chat automatically when you add me."
)
MAX_NAME = 64


async def _list_text(repo: ChatRepo) -> tuple[str, list[Chat]]:
    chats = await repo.list()
    if not chats:
        return "📡 <b>Channels and groups</b>\n\nNothing linked yet.", chats
    return (
        "📡 <b>Channels and groups</b>\n\n✅ ready · ⚠️ missing rights · 🚫 bot not in chat",
        chats,
    )


async def _chat_or_alert(callback: CallbackQuery, repo: ChatRepo, pk: int) -> Chat | None:
    chat = await repo.get(pk)
    if chat is None:
        await callback.answer("That chat is no longer linked.", show_alert=True)
    return chat


@router.message(Command("channels"))
async def cmd_channels(message: Message, ctx: AppContext, session: AsyncSession,
                       state: FSMContext) -> None:
    await state.clear()
    text, chats = await _list_text(ChatRepo(session, ctx.owner_id))
    await message.answer(text, reply_markup=channels_list_kb(chats))


@router.callback_query(MenuCb.filter(F.to == "channels"))
async def cb_channels(callback: CallbackQuery, ctx: AppContext, session: AsyncSession,
                      state: FSMContext) -> None:
    await state.clear()
    text, chats = await _list_text(ChatRepo(session, ctx.owner_id))
    await show(callback, text, channels_list_kb(chats))
    await callback.answer()


async def _show_chat(target: Message | CallbackQuery, chat: Chat, session: AsyncSession,
                     ctx: AppContext, user_id: int, prefix: str = "") -> None:
    zone, _ = await zone_for(session, ctx, user_id)
    await show(target, prefix + chat_card(chat, zone), channel_detail_kb(chat))


@router.callback_query(ChannelCb.filter(F.action == "open"))
async def cb_open(callback: CallbackQuery, callback_data: ChannelCb, ctx: AppContext,
                  session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    chat = await _chat_or_alert(callback, ChatRepo(session, ctx.owner_id), callback_data.pk)
    if chat:
        await _show_chat(callback, chat, session, ctx, callback.from_user.id)
        await callback.answer()


# --- add -------------------------------------------------------------------

@router.callback_query(ChannelCb.filter(F.action == "add"))
async def cb_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ChannelStates.waiting_ref)
    await show(callback, ADD_PROMPT, cancel_kb())
    await callback.answer()


def _ref_from_message(message: Message) -> int | str:
    origin = message.forward_origin
    if isinstance(origin, MessageOriginChannel):
        return origin.chat.id
    if isinstance(origin, MessageOriginChat):
        return origin.sender_chat.id
    if origin is not None:
        raise ChatRefError(
            "That forward doesn't show which chat it came from (it was sent by a person, "
            "or the origin is hidden). Send the @username or numeric ID instead."
        )
    if not message.text:
        raise ChatRefError("Forward a message from the chat, or send its @username or ID.")
    return parse_chat_ref(message.text)


@router.message(ChannelStates.waiting_ref)
async def msg_add_ref(message: Message, bot: Bot, ctx: AppContext, session: AsyncSession,
                      state: FSMContext) -> None:
    assert message.from_user is not None
    try:
        ref = _ref_from_message(message)
        result = await link_chat(bot, ChatRepo(session, ctx.owner_id), ref, message.from_user.id)
    except (ChatRefError, LinkError) as exc:
        await message.answer(f"⚠️ {html.escape(str(exc))}\n\nTry again or cancel.",
                             reply_markup=cancel_kb())
        return
    await state.clear()
    log.info("chat_linked", chat_id=result.chat.tg_chat_id, created=result.created)
    prefix = "✅ Linked!\n\n" if result.created else "🔄 Already linked, details refreshed.\n\n"
    await _show_chat(message, result.chat, session, ctx, message.from_user.id, prefix)


# --- rename ----------------------------------------------------------------

@router.callback_query(ChannelCb.filter(F.action == "rename"))
async def cb_rename(callback: CallbackQuery, callback_data: ChannelCb, ctx: AppContext,
                    session: AsyncSession, state: FSMContext) -> None:
    chat = await _chat_or_alert(callback, ChatRepo(session, ctx.owner_id), callback_data.pk)
    if chat is None:
        return
    await state.set_state(ChannelStates.waiting_name)
    await state.update_data(chat_pk=chat.id)
    await show(
        callback,
        f"✏️ Send a new name for <b>{html.escape(chat.name)}</b> (max {MAX_NAME} characters).\n"
        "Send <code>-</code> to go back to the Telegram title.",
        cancel_kb(),
    )
    await callback.answer()


@router.message(ChannelStates.waiting_name, F.text)
async def msg_rename(message: Message, ctx: AppContext, session: AsyncSession,
                     state: FSMContext) -> None:
    assert message.from_user is not None and message.text is not None
    name = message.text.strip()
    if len(name) > MAX_NAME:
        await message.answer(f"⚠️ That's {len(name)} characters; the limit is {MAX_NAME}.",
                             reply_markup=cancel_kb())
        return
    data = await state.get_data()
    repo = ChatRepo(session, ctx.owner_id)
    chat = await repo.get(int(data.get("chat_pk", 0)))
    await state.clear()
    if chat is None:
        await message.answer("That chat is no longer linked.")
        return
    chat.display_name = None if name in ("", "-") else name
    await session.flush()
    await _show_chat(message, chat, session, ctx, message.from_user.id, "✅ Renamed.\n\n")


# --- re-check rights --------------------------------------------------------

@router.callback_query(ChannelCb.filter(F.action == "recheck"))
async def cb_recheck(callback: CallbackQuery, callback_data: ChannelCb, bot: Bot,
                     ctx: AppContext, session: AsyncSession) -> None:
    chat = await _chat_or_alert(callback, ChatRepo(session, ctx.owner_id), callback_data.pk)
    if chat is None:
        return
    problems = await refresh_chat(bot, chat)
    await session.flush()
    await _show_chat(callback, chat, session, ctx, callback.from_user.id)
    await callback.answer("All good ✅" if not problems else "Rights updated")


# --- custom emoji test in a chat ---------------------------------------------

@router.callback_query(ChannelCb.filter(F.action == "emoji"))
async def cb_emoji(callback: CallbackQuery, callback_data: ChannelCb, ctx: AppContext,
                   session: AsyncSession) -> None:
    chat = await _chat_or_alert(callback, ChatRepo(session, ctx.owner_id), callback_data.pk)
    if chat is None:
        return
    await show(
        callback,
        f"🧪 <b>Custom emoji test in {html.escape(chat.name)}</b>\n\n"
        "I'll post one short <b>silent</b> message there with an animated emoji, check whether "
        "Telegram kept it, and <b>delete it right away</b>.",
        confirm_emoji_test_kb(chat),
    )
    await callback.answer()


@router.callback_query(ChannelCb.filter(F.action == "emoji_go"))
async def cb_emoji_go(callback: CallbackQuery, callback_data: ChannelCb, bot: Bot,
                      ctx: AppContext, session: AsyncSession) -> None:
    chat = await _chat_or_alert(callback, ChatRepo(session, ctx.owner_id), callback_data.pk)
    if chat is None:
        return
    await callback.answer("Testing…")
    try:
        result = await ctx.emoji_probe.probe(bot, chat.tg_chat_id, "Jakov test", silent=True)
    except TelegramAPIError as exc:
        await _show_chat(callback, chat, session, ctx, callback.from_user.id,
                         f"⚠️ I couldn't post there: {html.escape(str(exc))}\n\n")
        return
    note = ""
    if result.message is not None:
        try:
            await result.message.delete()
        except TelegramAPIError:
            note = "\n⚠️ I couldn't delete the test message; please delete it manually."
    chat.custom_emoji_ok = result.supported
    await session.flush()
    log.info("emoji_probe", scope="chat", chat_id=chat.tg_chat_id, supported=result.supported)
    head = ("✅ Animated custom emoji work in this chat." if result.supported else
            f"⚠️ {html.escape(result.detail)} Posts here will use normal emoji automatically.")
    await _show_chat(callback, chat, session, ctx, callback.from_user.id, f"{head}{note}\n\n")


# --- remove ----------------------------------------------------------------

@router.callback_query(ChannelCb.filter(F.action == "remove"))
async def cb_remove(callback: CallbackQuery, callback_data: ChannelCb, ctx: AppContext,
                    session: AsyncSession) -> None:
    chat = await _chat_or_alert(callback, ChatRepo(session, ctx.owner_id), callback_data.pk)
    if chat is None:
        return
    await show(
        callback,
        f"🗑 Remove <b>{html.escape(chat.name)}</b> from Jakov?\n\n"
        "<b>Remove</b> forgets it here; I stay in the chat.\n"
        "<b>Remove and leave</b> also makes me leave the chat.",
        confirm_remove_kb(chat),
    )
    await callback.answer()


@router.callback_query(ChannelCb.filter(F.action.in_({"remove_go", "leave_go"})))
async def cb_remove_go(callback: CallbackQuery, callback_data: ChannelCb, bot: Bot,
                       ctx: AppContext, session: AsyncSession) -> None:
    repo = ChatRepo(session, ctx.owner_id)
    chat = await _chat_or_alert(callback, repo, callback_data.pk)
    if chat is None:
        return
    name, note = chat.name, ""
    if callback_data.action == "leave_go":
        try:
            await bot.leave_chat(chat.tg_chat_id)
        except TelegramAPIError as exc:
            note = f"\n⚠️ Couldn't leave the chat: {html.escape(str(exc))}"
    await repo.delete(chat)
    log.info("chat_removed", chat_id=chat.tg_chat_id, left=callback_data.action == "leave_go")
    text, chats = await _list_text(repo)
    await show(callback, f"🗑 Removed <b>{html.escape(name)}</b>.{note}\n\n{text}",
               channels_list_kb(chats))
    await callback.answer()
