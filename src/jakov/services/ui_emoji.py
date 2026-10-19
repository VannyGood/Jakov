"""Animated emoji in the bot's own UI (menus, replies, button icons) for admins.

Implemented as a Bot API request middleware so every handler benefits automatically.
Post previews and real posts opt out via `raw_output()` so they show exactly what
the channel will get.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from aiogram import Bot
from aiogram.client.default import Default
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.enums import ParseMode
from aiogram.methods import (
    EditMessageCaption,
    EditMessageReplyMarkup,
    EditMessageText,
    Response,
    SendMessage,
    SendPhoto,
    SendVideo,
    TelegramMethod,
)
from aiogram.methods.base import TelegramType
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jakov.db.models import User
from jakov.db.repositories.capabilities import CapabilityRepo
from jakov.engine.html_emojify import Emojifier
from jakov.services.emoji_capability import CAP_PRIVATE
from jakov.services.emoji_library import EmojiLibrary

_raw: ContextVar[bool] = ContextVar("jakov_raw_output", default=False)


@contextmanager
def raw_output() -> Iterator[None]:
    """Send messages exactly as given (no UI emoji rewriting) inside this block."""
    token = _raw.set(True)
    try:
        yield
    finally:
        _raw.reset(token)


@dataclass(slots=True)
class UiPrefs:
    animated: bool = True
    pack: str | None = None


class UiEmojiService:
    def __init__(self, library: EmojiLibrary, admin_ids: set[int]) -> None:
        self.library = library
        self.admin_ids = admin_ids
        self.dm_supported = False
        self.prefs: dict[int, UiPrefs] = {}
        self._emojifiers: dict[str | None, Emojifier] = {}

    def invalidate(self) -> None:
        self._emojifiers.clear()

    async def load(self, sessions: async_sessionmaker[AsyncSession], owner_id: int) -> None:
        async with sessions() as session:
            cap = await CapabilityRepo(session, owner_id).get(CAP_PRIVATE)
            users = await session.scalars(select(User).where(User.owner_id == owner_id))
            self.prefs = {u.tg_user_id: UiPrefs(u.ui_animated, u.ui_emoji_pack) for u in users}
        self.dm_supported = bool(cap and cap.supported)
        self.invalidate()

    def emojifier_for(self, chat_id: object) -> Emojifier | None:
        if _raw.get() or not self.dm_supported or chat_id not in self.admin_ids:
            return None
        prefs = self.prefs.get(chat_id, UiPrefs()) if isinstance(chat_id, int) else UiPrefs()
        if not prefs.animated:
            return None
        if prefs.pack not in self._emojifiers:
            self._emojifiers[prefs.pack] = Emojifier(self.library.ui_map(prefs.pack))
        return self._emojifiers[prefs.pack]


def _is_html(parse_mode: Any) -> bool:
    # Our bot's default parse mode is HTML, so an unset (Default) value means HTML.
    return isinstance(parse_mode, Default) or parse_mode == ParseMode.HTML


def decorate_markup(markup: Any, emojifier: Emojifier) -> Any:
    if not isinstance(markup, InlineKeyboardMarkup):
        return markup
    rows: list[list[InlineKeyboardButton]] = []
    changed = False
    for row in markup.inline_keyboard:
        new_row = []
        for button in row:
            if button.icon_custom_emoji_id is None:
                icon, text = emojifier.leading(button.text)
                if icon:
                    button = button.model_copy(update={"icon_custom_emoji_id": icon, "text": text})
                    changed = True
            new_row.append(button)
        rows.append(new_row)
    return InlineKeyboardMarkup(inline_keyboard=rows) if changed else markup


def decorate(method: TelegramMethod[Any], emojifier: Emojifier) -> None:
    if isinstance(method, (SendMessage, EditMessageText)) and method.text \
            and _is_html(method.parse_mode):
        method.text = emojifier.html(method.text)
    elif isinstance(method, (SendPhoto, SendVideo, EditMessageCaption)) and method.caption \
            and _is_html(method.parse_mode):
        method.caption = emojifier.html(method.caption)
    if isinstance(method, (SendMessage, EditMessageText, SendPhoto, SendVideo,
                           EditMessageCaption, EditMessageReplyMarkup)):
        method.reply_markup = decorate_markup(method.reply_markup, emojifier)


class AnimatedUiMiddleware(BaseRequestMiddleware):
    def __init__(self, service: UiEmojiService) -> None:
        self.service = service

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        emojifier = self.service.emojifier_for(getattr(method, "chat_id", None))
        if emojifier is not None:
            decorate(method, emojifier)
        return await make_request(bot, method)
