"""Live test: does Telegram keep our custom emoji, or strip them to plain emoji?

Since Bot API 9.4, bots may send custom emoji when the bot owner has Telegram Premium,
in private chats, groups and supergroups. Channels and future rule changes are not
guaranteed, so we never assume: we send a real message and inspect its entities.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from aiogram import Bot
from aiogram.enums import MessageEntityType, ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from jakov.logging_setup import get_logger

log = get_logger(__name__)

CAP_PRIVATE = "custom_emoji.private"
_PREFERRED = ("🔥", "🚀", "✨")


@dataclass(frozen=True, slots=True)
class SampleEmoji:
    custom_emoji_id: str
    fallback: str


@dataclass(frozen=True, slots=True)
class ProbeResult:
    supported: bool
    detail: str
    message: Message | None = None


def has_custom_emoji(message: Message) -> bool:
    entities = (message.entities or []) + (message.caption_entities or [])
    return any(e.type == MessageEntityType.CUSTOM_EMOJI for e in entities)


def tg_emoji(custom_emoji_id: str, fallback: str) -> str:
    return f'<tg-emoji emoji-id="{html.escape(custom_emoji_id)}">{html.escape(fallback)}</tg-emoji>'


class EmojiProbe:
    def __init__(self, pack_name: str) -> None:
        self.pack_name = pack_name
        self._sample: SampleEmoji | None = None

    async def sample(self, bot: Bot) -> SampleEmoji:
        if self._sample is None:
            sticker_set = await bot.get_sticker_set(self.pack_name)
            stickers = [s for s in sticker_set.stickers if s.custom_emoji_id]
            if not stickers:
                raise ValueError(f"Pack {self.pack_name!r} has no custom emoji")
            chosen = next(
                (s for want in _PREFERRED for s in stickers if s.emoji == want), stickers[0]
            )
            assert chosen.custom_emoji_id is not None
            self._sample = SampleEmoji(chosen.custom_emoji_id, chosen.emoji or "⭐")
        return self._sample

    async def probe(
        self, bot: Bot, chat_id: int, intro: str, *, silent: bool = False
    ) -> ProbeResult:
        """Send a test message. Raises TelegramForbiddenError if we can't write there."""
        try:
            sample = await self.sample(bot)
        except (TelegramBadRequest, ValueError) as exc:
            log.warning("emoji_sample_unavailable", pack=self.pack_name, error=str(exc))
            return ProbeResult(False, f"Test pack {self.pack_name!r} is unavailable.")
        text = f"{intro} {tg_emoji(sample.custom_emoji_id, sample.fallback)}"
        try:
            message = await bot.send_message(
                chat_id, text, parse_mode=ParseMode.HTML, disable_notification=silent
            )
        except TelegramBadRequest as exc:
            return ProbeResult(False, f"Telegram rejected the custom emoji: {exc.message}")
        if has_custom_emoji(message):
            return ProbeResult(True, "Custom emoji delivered.", message)
        return ProbeResult(
            False, "Telegram replaced the custom emoji with a normal one.", message
        )
