from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from jakov.keyboards.callbacks import EmojiCb, MenuCb, SettingsCb
from jakov.keyboards.common import cancel_button
from jakov.services.timezones import COMMON_ZONES

ZONES_PER_PAGE = 10
SHARE_LOCATION_TEXT = "📍 Send my location"
CANCEL_TEXT = "✖️ Cancel"


def settings_kb(ui_animated: bool = True) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🕒 Timezone", callback_data=SettingsCb(action="tz"))
    kb.button(text=f"🎨 Animated menus: {'On' if ui_animated else 'Off'}",
              callback_data=SettingsCb(action="ui_toggle"))
    kb.button(text="📦 Menu emoji pack", callback_data=EmojiCb(action="packs"))
    kb.button(text="🧪 Custom emoji test", callback_data=SettingsCb(action="emoji_test"))
    kb.button(text="⬅️ Back", callback_data=MenuCb(to="main"))
    kb.adjust(1)
    return kb.as_markup()


def timezone_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📍 Use my location", callback_data=SettingsCb(action="tz_loc"))
    kb.button(text="🌍 Pick from list", callback_data=SettingsCb(action="tz_list", value=0))
    kb.button(text="⌨️ Type a timezone", callback_data=SettingsCb(action="tz_type"))
    kb.button(text="⬅️ Back", callback_data=MenuCb(to="settings"))
    kb.adjust(1)
    return kb.as_markup()


def zone_list_kb(page: int) -> InlineKeyboardMarkup:
    pages = (len(COMMON_ZONES) + ZONES_PER_PAGE - 1) // ZONES_PER_PAGE
    page = max(0, min(page, pages - 1))
    start = page * ZONES_PER_PAGE
    buttons = [
        InlineKeyboardButton(
            text=zone.replace("_", " "),
            callback_data=SettingsCb(action="tz_pick", value=index).pack(),
        )
        for index, zone in enumerate(COMMON_ZONES[start:start + ZONES_PER_PAGE], start=start)
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="◀️", callback_data=SettingsCb(action="tz_list", value=page - 1).pack()))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(
            text="▶️", callback_data=SettingsCb(action="tz_list", value=page + 1).pack()))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(
        text="⬅️ Back", callback_data=SettingsCb(action="tz").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def location_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=SHARE_LOCATION_TEXT, request_location=True)],
            [KeyboardButton(text=CANCEL_TEXT)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def type_zone_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[cancel_button()]])
