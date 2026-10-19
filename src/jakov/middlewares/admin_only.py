"""Silently ignore anyone who isn't an admin in private chat and on our buttons."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message, TelegramObject

from jakov.logging_setup import get_logger

log = get_logger(__name__)


class AdminOnlyMiddleware(BaseMiddleware):
    """Outer middleware for private messages and callback queries.

    Non-admins get no response at all, as required. Group traffic is not filtered here
    because the Guard module must see every member's messages.
    """

    def __init__(self, admin_ids: set[int]) -> None:
        self.admin_ids = admin_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if (
            isinstance(event, Message)
            and event.chat.type == ChatType.PRIVATE
            and (event.from_user is None or event.from_user.id not in self.admin_ids)
        ):
            log.info("ignored_non_admin", user_id=getattr(event.from_user, "id", None))
            return None
        if isinstance(event, CallbackQuery) and event.from_user.id not in self.admin_ids:
            log.info("ignored_non_admin_callback", user_id=event.from_user.id)
            return None
        return await handler(event, data)
