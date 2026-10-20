"""Button helpers with Telegram's colored button styles (Bot API 9.4).

Colour language used everywhere:
- primary (blue): the main next step
- success (green): confirm / send / approve
- danger (red): cancel / delete
- default (grey): everything else
"""

from __future__ import annotations

from typing import Literal

from aiogram.enums import ButtonStyle
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

Style = Literal["primary", "success", "danger"] | None
_STYLES = {"primary": ButtonStyle.PRIMARY, "success": ButtonStyle.SUCCESS,
           "danger": ButtonStyle.DANGER}


def btn(text: str, data: CallbackData | str, style: Style = None,
        icon: str | None = None) -> InlineKeyboardButton:
    packed = data.pack() if isinstance(data, CallbackData) else data
    return InlineKeyboardButton(text=text, callback_data=packed,
                                style=_STYLES[style] if style else None,
                                icon_custom_emoji_id=icon)


def url_btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def kb(*rows: list[InlineKeyboardButton] | InlineKeyboardButton) -> InlineKeyboardMarkup:
    """kb([a, b], c) -> two rows: [a, b] and [c]."""
    return InlineKeyboardMarkup(inline_keyboard=[r if isinstance(r, list) else [r]
                                                 for r in rows])


def grid(buttons: list[InlineKeyboardButton], per_row: int) -> list[list[InlineKeyboardButton]]:
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]
