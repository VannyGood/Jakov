"""/start, main menu and the global Cancel button."""

from __future__ import annotations

import html

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.context import AppContext
from jakov.db.repositories.capabilities import CapabilityRepo
from jakov.db.repositories.users import UserRepo
from jakov.handlers.views import main_menu_text
from jakov.keyboards.callbacks import CancelCb, MenuCb, SettingsCb
from jakov.keyboards.common import main_menu_kb
from jakov.keyboards.settings import CANCEL_TEXT
from jakov.logging_setup import get_logger
from jakov.services.emoji_capability import CAP_PRIVATE
from jakov.utils.telegram import show

log = get_logger(__name__)
router = Router(name="start")
router.message.filter(F.chat.type == ChatType.PRIVATE)


async def run_private_emoji_probe(bot: Bot, ctx: AppContext, session: AsyncSession,
                                  chat_id: int) -> str:
    """Send the DM test message, store the result and return a short explanation."""
    try:
        result = await ctx.emoji_probe.probe(bot, chat_id, "✨ Custom emoji test:")
    except TelegramAPIError as exc:
        log.warning("emoji_probe_failed", error=type(exc).__name__)
        return "❗ I couldn't run the custom emoji test right now. Try again in /settings."
    await CapabilityRepo(session, ctx.owner_id).set(CAP_PRIVATE, result.supported, result.detail)
    await session.commit()
    await ctx.ui.load(ctx.sessions, ctx.owner_id)
    log.info("emoji_probe", scope="private", supported=result.supported, detail=result.detail)
    if result.supported:
        return ("✅ <b>Animated custom emoji work.</b> If you see an animated emoji above, "
                "posts can use them.")
    return ("❗ <b>Custom emoji are not available for this bot.</b>\n"
            f"Telegram said: {html.escape(result.detail)}\n"
            "I'll use normal emoji automatically. Bots can send custom emoji only when the bot "
            "owner has Telegram Premium (Bot API 9.4+).")


@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot, ctx: AppContext, session: AsyncSession,
                    state: FSMContext) -> None:
    assert message.from_user is not None
    await state.clear()
    user, created = await UserRepo(session, ctx.owner_id).touch(
        message.from_user.id, message.from_user.username, message.from_user.full_name,
        is_admin=True,
    )
    if created:
        await session.commit()
        await ctx.ui.load(ctx.sessions, ctx.owner_id)
    if created:
        await message.answer(
            f"👋 Hi {html.escape(message.from_user.first_name)}, I'm <b>Jakov</b>.\n"
            "I publish posts, guard your groups and scan links. Let me check a few things first.",
            reply_markup=ReplyKeyboardRemove(),
        )
    cap = await CapabilityRepo(session, ctx.owner_id).get(CAP_PRIVATE)
    if cap is None:
        await message.answer(await run_private_emoji_probe(bot, ctx, session, message.chat.id))
    await message.answer(
        await main_menu_text(session, ctx, message.from_user.id), reply_markup=main_menu_kb()
    )
    if user.timezone is None:
        kb = InlineKeyboardBuilder()
        kb.button(text="⏰ Set my timezone", callback_data=SettingsCb(action="tz"))
        await message.answer(
            f"⏰ I'm using the default timezone <b>{html.escape(ctx.settings.timezone)}</b>. "
            "Share your location so schedules use your local time.",
            reply_markup=kb.as_markup(),
        )


@router.callback_query(MenuCb.filter(F.to == "main"))
async def cb_main(callback: CallbackQuery, ctx: AppContext, session: AsyncSession,
                  state: FSMContext) -> None:
    await state.clear()
    await show(callback, await main_menu_text(session, ctx, callback.from_user.id), main_menu_kb())
    await callback.answer()


@router.callback_query(CancelCb.filter())
async def cb_cancel(callback: CallbackQuery, ctx: AppContext, session: AsyncSession,
                    state: FSMContext) -> None:
    await state.clear()
    await show(callback, "✖️ Cancelled.\n\n" + await main_menu_text(
        session, ctx, callback.from_user.id), main_menu_kb())
    await callback.answer("Cancelled")


@router.message(F.text == CANCEL_TEXT)
async def msg_cancel(message: Message, ctx: AppContext, session: AsyncSession,
                     state: FSMContext) -> None:
    assert message.from_user is not None
    await state.clear()
    await message.answer("✖️ Cancelled.", reply_markup=ReplyKeyboardRemove())
    await message.answer(await main_menu_text(session, ctx, message.from_user.id),
                         reply_markup=main_menu_kb())
