"""Resolve `{emoji}` / `{emoji:mood}` tokens to custom (animated) emoji or plain fallbacks."""

from __future__ import annotations

import html
import random
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from jakov.engine.limits import MAX_CUSTOM_EMOJI

TOKEN_RE = re.compile(r"\{emoji(?::([a-z_]+))?\}")
_VS16 = "️"


def normalize_emoji(char: str) -> str:
    """Compare emoji without the variation selector ('❤️' == '❤')."""
    return char.replace(_VS16, "")


def tg_emoji(custom_emoji_id: str, fallback: str) -> str:
    return (f'<tg-emoji emoji-id="{html.escape(custom_emoji_id)}">'
            f"{html.escape(fallback, quote=False)}</tg-emoji>")


@dataclass(frozen=True, slots=True)
class LibEmoji:
    custom_emoji_id: str
    fallback: str
    pack: str | None = None
    tags: frozenset[str] = frozenset()
    animated: bool = True


@dataclass(slots=True)
class EmojiPalette:
    """All usable emoji, indexed by mood. Built from the DB library + the moods file."""

    moods: Mapping[str, Sequence[str]]
    emojis: Sequence[LibEmoji] = ()
    # Packs used in posts only when nothing more expressive exists for a mood.
    base_packs: frozenset[str] = frozenset()
    _by_mood: dict[str, list[LibEmoji]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        for emoji in self.emojis:
            for tag in emoji.tags:
                self._by_mood.setdefault(tag, []).append(emoji)

    def auto_tags(self, fallback: str) -> set[str]:
        norm = normalize_emoji(fallback)
        return {mood for mood, chars in self.moods.items()
                if norm in {normalize_emoji(c) for c in chars}}

    def candidates(self, mood: str, style: str | None = None) -> list[LibEmoji]:
        found = self._by_mood.get(mood, [])
        if style:
            styled = [e for e in found if e.pack == style]
            if styled:
                return styled
        expressive = [e for e in found if e.pack not in self.base_packs]
        return expressive or list(found)

    def plain(self, mood: str) -> list[str]:
        return list(self.moods.get(mood, ())) or ["✨"]

    def known_moods(self) -> set[str]:
        return set(self.moods) | set(self._by_mood)

    def mood_counts(self) -> list[tuple[str, int]]:
        """Moods that have library emoji, most populated first."""
        return sorted(((m, len(e)) for m, e in self._by_mood.items()),
                      key=lambda pair: (-pair[1], pair[0]))


@dataclass(slots=True)
class EmojiPicker:
    """Picks emoji for one message, avoiding repeats where possible."""

    palette: EmojiPalette
    rng: random.Random
    custom: bool
    style: str | None = None
    generic_moods: Sequence[str] = ("star", "sparkles")
    max_custom: int = MAX_CUSTOM_EMOJI
    _used: set[str] = field(default_factory=set, init=False)
    _custom_count: int = field(default=0, init=False)

    def pick(self, mood: str | None) -> str:
        mood = mood or self.rng.choice(list(self.generic_moods))
        options = self.palette.candidates(mood, self.style)
        fresh = [e for e in options if e.custom_emoji_id not in self._used] or options
        if fresh:
            chosen = self.rng.choice(fresh)
            self._used.add(chosen.custom_emoji_id)
            if self.custom and self._custom_count < self.max_custom:
                self._custom_count += 1
                return tg_emoji(chosen.custom_emoji_id, chosen.fallback)
            return html.escape(chosen.fallback, quote=False)
        return self.rng.choice(self.palette.plain(mood))


def render_emoji_tokens(text: str, picker: EmojiPicker) -> str:
    return TOKEN_RE.sub(lambda m: picker.pick(m.group(1)), text)


def strip_custom_emoji(html_text: str) -> str:
    """Replace every <tg-emoji> with its plain fallback (for chats where custom emoji fail)."""
    return re.sub(r"<tg-emoji[^>]*>(.*?)</tg-emoji>", r"\1", html_text, flags=re.DOTALL)


def merge_moods(*groups: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for group in groups:
        for mood in group:
            seen.setdefault(mood, None)
    return list(seen)
