"""Turn plain emoji in bot-authored HTML into animated <tg-emoji>, safely.

Only text between tags is touched; nothing inside <code>, <pre>, <a>, <tg-emoji> or
<blockquote expandable> attributes changes. Used for the bot's own menus and replies.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from functools import lru_cache

from jakov.engine.emoji_render import normalize_emoji, tg_emoji
from jakov.engine.limits import MAX_CUSTOM_EMOJI

_TAG_SPLIT = re.compile(r"(<[^>]+>)")
_SKIP_TAGS = {"code", "pre", "a", "tg-emoji"}
_VS16 = "️?"


@lru_cache(maxsize=8)
def _compile(keys: tuple[str, ...]) -> re.Pattern[str] | None:
    if not keys:
        return None
    parts = [_VS16.join(re.escape(ch) for ch in key) + _VS16
             for key in sorted(keys, key=len, reverse=True)]
    return re.compile("|".join(parts))


class Emojifier:
    def __init__(self, mapping: Mapping[str, str]) -> None:
        """`mapping`: plain emoji -> custom_emoji_id."""
        self.mapping = {normalize_emoji(k): v for k, v in mapping.items() if k}
        self._pattern = _compile(tuple(sorted(self.mapping)))

    def html(self, text: str, budget: int = MAX_CUSTOM_EMOJI) -> str:
        if self._pattern is None or not text:
            return text
        budget -= text.count("<tg-emoji")
        out: list[str] = []
        skip_depth = 0
        for piece in _TAG_SPLIT.split(text):
            if piece.startswith("<") and piece.endswith(">"):
                name = re.match(r"</?\s*([a-zA-Z-]+)", piece)
                tag = name.group(1).lower() if name else ""
                if tag in _SKIP_TAGS:
                    skip_depth += -1 if piece.startswith("</") else 1
                out.append(piece)
                continue
            if skip_depth > 0 or budget <= 0:
                out.append(piece)
                continue

            def swap(match: re.Match[str]) -> str:
                nonlocal budget
                if budget <= 0:
                    return match.group(0)
                emoji_id = self.mapping.get(normalize_emoji(match.group(0)))
                if emoji_id is None:
                    return match.group(0)
                budget -= 1
                return tg_emoji(emoji_id, match.group(0))

            out.append(self._pattern.sub(swap, piece))
        return "".join(out)

    def leading(self, text: str) -> tuple[str | None, str]:
        """For buttons: '🔥 Hot' -> (custom id, 'Hot'). Unknown emoji -> (None, text)."""
        if self._pattern is None:
            return None, text
        match = self._pattern.match(text)
        if not match:
            return None, text
        rest = text[match.end():].lstrip()
        emoji_id = self.mapping.get(normalize_emoji(match.group(0)))
        if emoji_id is None or not rest:
            return None, text
        return emoji_id, rest
