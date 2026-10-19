from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from jakov.keyboards.callbacks import CancelCb, MenuCb


def cancel_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="✖️ Cancel", callback_data=CancelCb().pack())


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[cancel_button()]])


def back_button(to: str = "main", text: str = "⬅️ Back") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=MenuCb(to=to).pack())


def main_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✍️ New post", callback_data=MenuCb(to="newpost"))
    kb.button(text="📰 Published", callback_data=MenuCb(to="published"))
    kb.button(text="😀 Emoji library", callback_data=MenuCb(to="emoji"))
    kb.button(text="📡 Channels", callback_data=MenuCb(to="channels"))
    kb.button(text="⚙️ Settings", callback_data=MenuCb(to="settings"))
    kb.adjust(1, 2, 2)
    return kb.as_markup()
