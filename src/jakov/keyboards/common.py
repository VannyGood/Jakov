from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from jakov.keyboards.callbacks import CancelCb, MenuCb
from jakov.keyboards.ui import btn, kb


def cancel_button() -> InlineKeyboardButton:
    return btn("✖️ Cancel", CancelCb(), "danger")


def cancel_kb() -> InlineKeyboardMarkup:
    return kb(cancel_button())


def back_button(to: str = "main", text: str = "👈 Back") -> InlineKeyboardButton:
    return btn(text, MenuCb(to=to))


def main_menu_kb() -> InlineKeyboardMarkup:
    return kb(
        btn("✍️ Create a post", MenuCb(to="newpost"), "primary"),
        [btn("📆 Schedules", MenuCb(to="schedules")), btn("📰 Posts", MenuCb(to="published"))],
        [btn("📣 Channels", MenuCb(to="channels")), btn("🧰 Settings", MenuCb(to="settings"))],
    )
