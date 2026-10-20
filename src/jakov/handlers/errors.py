"""Last-resort error handler: log it, tell the admins, never crash the bot."""

from __future__ import annotations

import html

from aiogram import Bot, Router
from aiogram.types import ErrorEvent

from jakov.context import AppContext
from jakov.logging_setup import SecretRedactor, get_logger
from jakov.services.notifier import notify_admins

log = get_logger(__name__)
router = Router(name="errors")


@router.errors()
async def on_error(event: ErrorEvent, bot: Bot, ctx: AppContext) -> bool:
    exc = event.exception
    log.exception("update_failed", update_id=event.update.update_id, exc_info=exc)
    redactor = SecretRedactor(ctx.settings.secret_values())
    detail = redactor.redact(f"{type(exc).__name__}: {exc}")[:500]
    await notify_admins(
        bot, ctx.admin_ids,
        f"❗ Something went wrong while handling an update.\n<code>{html.escape(detail)}</code>\n"
        "The bot keeps running; details are in the log.",
    )
    return True
