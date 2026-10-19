"""Send messages to the bot admins without ever crashing the caller."""

from __future__ import annotations

from collections.abc import Iterable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup

from jakov.logging_setup import get_logger

log = get_logger(__name__)


async def notify_admins(
    bot: Bot,
    admin_ids: Iterable[int],
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> int:
    """Returns how many admins were reached."""
    delivered = 0
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=reply_markup)
            delivered += 1
        except TelegramAPIError as exc:
            # Typical cause: the admin never pressed /start, so Telegram refuses the DM.
            log.warning("admin_notify_failed", admin_id=admin_id, error=type(exc).__name__)
    return delivered
