"""/settings: personal timezone (by location, list or typed) and the custom emoji test."""

from __future__ import annotations

import html

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.context import AppContext
from jakov.db.base import utcnow
from jakov.db.repositories.capabilities import CapabilityRepo
from jakov.db.repositories.users import UserRepo
from jakov.handlers.start import run_private_emoji_probe
from jakov.handlers.states import SettingsStates
from jakov.handlers.views import emoji_status, zone_for
from jakov.keyboards.callbacks import MenuCb, SettingsCb
from jakov.keyboards.settings import (
    location_request_kb,
    settings_kb,
    timezone_kb,
    type_zone_kb,
    zone_list_kb,
)
from jakov.logging_setup import get_logger
from jakov.services.emoji_capability import CAP_PRIVATE
from jakov.services.timezones import (
    COMMON_ZONES,
    effective_zone,
    normalize_zone,
    zone_from_location,
)
from jakov.utils.telegram import show
from jakov.utils.time import format_local

log = get_logger(__name__)
router = Router(name="settings")
router.message.filter(F.chat.type == ChatType.PRIVATE)


async def _settings_text(session: AsyncSession, ctx: AppContext, user_id: int) -> str:
    zone, personal = await zone_for(session, ctx, user_id)
    cap = await CapabilityRepo(session, ctx.owner_id).get(CAP_PRIVATE)
    user = await UserRepo(session, ctx.owner_id).get(user_id)
    now_local = format_local(utcnow(), effective_zone(zone, ctx.settings.timezone))
    source = "your setting" if personal else "default from config"
    menu_pack = (user.ui_emoji_pack if user else None) or ctx.library.default_ui_pack or "any"
    animated = user.ui_animated if user else True
    return (
        "⚙️ <b>Settings</b>\n\n"
        f"🕒 Timezone: <b>{html.escape(zone)}</b> ({source})\n"
        f"    Local time now: {now_local}\n"
        f"✨ Custom emoji in DMs: {emoji_status(cap)}\n"
        f"🎨 Animated menus: <b>{'on' if animated else 'off'}</b> · pack "
        f"<b>{html.escape(menu_pack)}</b>"
    )


async def _show_settings(target: Message | CallbackQuery, session: AsyncSession,
                         ctx: AppContext, user_id: int, prefix: str = "") -> None:
    user = await UserRepo(session, ctx.owner_id).get(user_id)
    await show(target, prefix + await _settings_text(session, ctx, user_id),
               settings_kb(user.ui_animated if user else True))


async def _save_zone(session: AsyncSession, ctx: AppContext, user_id: int, zone: str) -> None:
    await UserRepo(session, ctx.owner_id).set_timezone(user_id, zone)
    log.info("timezone_set", user_id=user_id, zone=zone)


@router.message(Command("settings"))
async def cmd_settings(message: Message, ctx: AppContext, session: AsyncSession,
                       state: FSMContext) -> None:
    assert message.from_user is not None
    await state.clear()
    await _show_settings(message, session, ctx, message.from_user.id)


@router.callback_query(MenuCb.filter(F.to == "settings"))
async def cb_settings(callback: CallbackQuery, ctx: AppContext, session: AsyncSession,
                      state: FSMContext) -> None:
    await state.clear()
    await _show_settings(callback, session, ctx, callback.from_user.id)
    await callback.answer()


@router.callback_query(SettingsCb.filter(F.action == "tz"))
async def cb_tz(callback: CallbackQuery, ctx: AppContext, session: AsyncSession,
                state: FSMContext) -> None:
    await state.clear()
    zone, _ = await zone_for(session, ctx, callback.from_user.id)
    await show(
        callback,
        f"🕒 <b>Timezone</b>: {html.escape(zone)}\n\n"
        "All times are stored in UTC and shown in this timezone. Telegram doesn't tell bots "
        "where you are, so pick how to set it:",
        timezone_kb(),
    )
    await callback.answer()


@router.callback_query(SettingsCb.filter(F.action == "tz_list"))
async def cb_tz_list(callback: CallbackQuery, callback_data: SettingsCb) -> None:
    await show(callback, "🌍 Pick your timezone:", zone_list_kb(callback_data.value))
    await callback.answer()


@router.callback_query(SettingsCb.filter(F.action == "tz_pick"))
async def cb_tz_pick(callback: CallbackQuery, callback_data: SettingsCb, ctx: AppContext,
                     session: AsyncSession) -> None:
    if not 0 <= callback_data.value < len(COMMON_ZONES):
        await callback.answer("Unknown timezone", show_alert=True)
        return
    await _save_zone(session, ctx, callback.from_user.id, COMMON_ZONES[callback_data.value])
    await _show_settings(callback, session, ctx, callback.from_user.id, "✅ Timezone saved.\n\n")
    await callback.answer()


@router.callback_query(SettingsCb.filter(F.action == "tz_type"))
async def cb_tz_type(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.waiting_zone)
    await show(callback, "⌨️ Send a timezone name, e.g. <code>Europe/Belgrade</code>, "
               "<code>America/New_York</code> or just <code>Tokyo</code>.", type_zone_kb())
    await callback.answer()


@router.message(SettingsStates.waiting_zone, F.text)
async def msg_tz_typed(message: Message, ctx: AppContext, session: AsyncSession,
                       state: FSMContext) -> None:
    assert message.from_user is not None and message.text is not None
    zone = normalize_zone(message.text)
    if zone is None:
        await message.answer("⚠️ I don't know that timezone. Try a name like "
                             "<code>Europe/Berlin</code>.", reply_markup=type_zone_kb())
        return
    await state.clear()
    await _save_zone(session, ctx, message.from_user.id, zone)
    await _show_settings(message, session, ctx, message.from_user.id, "✅ Timezone saved.\n\n")


@router.callback_query(SettingsCb.filter(F.action == "tz_loc"))
async def cb_tz_location(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.set_state(SettingsStates.waiting_location)
    await callback.answer()
    # Location requests only work on reply keyboards, so this needs a new message.
    await bot.send_message(
        callback.from_user.id,
        "📍 Tap the button below to share your location. I only use it once, offline, to find "
        "your timezone. The coordinates are not stored.\n"
        "(Location sharing works in the Telegram mobile apps.)",
        reply_markup=location_request_kb(),
    )


@router.message(SettingsStates.waiting_location, F.location)
async def msg_location(message: Message, ctx: AppContext, session: AsyncSession,
                       state: FSMContext) -> None:
    assert message.from_user is not None and message.location is not None
    zone = await zone_from_location(message.location.latitude, message.location.longitude)
    await state.clear()
    if zone is None:
        await message.answer("⚠️ I couldn't find a timezone for that spot (open sea?). "
                             "Pick one from the list instead.", reply_markup=ReplyKeyboardRemove())
        await message.answer("🌍 Pick your timezone:", reply_markup=zone_list_kb(0))
        return
    await _save_zone(session, ctx, message.from_user.id, zone)
    await message.answer(f"✅ Timezone set to <b>{html.escape(zone)}</b>.",
                         reply_markup=ReplyKeyboardRemove())
    await _show_settings(message, session, ctx, message.from_user.id)


@router.message(SettingsStates.waiting_location)
async def msg_location_other(message: Message) -> None:
    await message.answer("Tap “📍 Send my location” below, or “✖️ Cancel”.",
                         reply_markup=location_request_kb())


@router.callback_query(SettingsCb.filter(F.action == "ui_toggle"))
async def cb_ui_toggle(callback: CallbackQuery, ctx: AppContext, session: AsyncSession) -> None:
    user = await UserRepo(session, ctx.owner_id).get(callback.from_user.id)
    if user is None:
        await callback.answer("Send /start first.", show_alert=True)
        return
    user.ui_animated = not user.ui_animated
    await session.commit()
    await ctx.ui.load(ctx.sessions, ctx.owner_id)
    await _show_settings(callback, session, ctx, callback.from_user.id)
    await callback.answer("Animated menus " + ("on ✨" if user.ui_animated else "off"))


@router.callback_query(SettingsCb.filter(F.action == "emoji_test"))
async def cb_emoji_test(callback: CallbackQuery, bot: Bot, ctx: AppContext,
                        session: AsyncSession) -> None:
    await callback.answer("Testing…")
    verdict = await run_private_emoji_probe(bot, ctx, session, callback.from_user.id)
    sent = await bot.send_message(callback.from_user.id, verdict)
    # A Message target makes _show_settings send a fresh settings card below the verdict.
    await _show_settings(sent, session, ctx, callback.from_user.id)
