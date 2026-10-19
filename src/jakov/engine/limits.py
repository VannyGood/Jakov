"""Telegram length limits, measured the way Telegram does (UTF-16 units of visible text)."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024
# Conservative cap on custom emoji per message (Telegram limits entities per message).
MAX_CUSTOM_EMOJI = 100

_TAG_RE = re.compile(r"<[^>]+>")


def visible_text(html_text: str) -> str:
    return html.unescape(_TAG_RE.sub("", html_text))


def tg_length(html_text: str) -> int:
    return len(visible_text(html_text).encode("utf-16-le")) // 2


@dataclass(frozen=True, slots=True)
class LengthCheck:
    length: int
    limit: int

    @property
    def ok(self) -> bool:
        return 0 < self.length <= self.limit

    @property
    def over_by(self) -> int:
        return max(0, self.length - self.limit)


def check_length(html_text: str, has_media: bool) -> LengthCheck:
    return LengthCheck(tg_length(html_text), CAPTION_LIMIT if has_media else TEXT_LIMIT)
