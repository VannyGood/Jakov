"""Helpers for replying to buttons and messages consistently."""

from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message


async def show(
    target: Message | CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    """Edit the menu message when answering a button, otherwise send a new message."""
    if isinstance(target, CallbackQuery):
        message = target.message
        if isinstance(message, Message):
            try:
                edited = await message.edit_text(text, reply_markup=reply_markup)
            except TelegramBadRequest as exc:
                if "message is not modified" in exc.message:
                    return message
                # Message too old or has media: fall back to a fresh message.
                return await message.answer(text, reply_markup=reply_markup)
            return edited if isinstance(edited, Message) else message
        if target.from_user and target.bot:
            return await target.bot.send_message(
                target.from_user.id, text, reply_markup=reply_markup
            )
        return None
    return await target.answer(text, reply_markup=reply_markup)
