"""Emoji library: import packs, add emoji from messages, and serve an in-memory palette."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.enums import MessageEntityType, StickerType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, Sticker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jakov.db.models import EmojiLibraryItem
from jakov.db.repositories.emoji import EmojiRepo
from jakov.engine.emoji_render import EmojiPalette, LibEmoji, normalize_emoji
from jakov.engine.html_emojify import Emojifier
from jakov.engine.lottie_motion import ALIVE_THRESHOLD
from jakov.logging_setup import get_logger

log = get_logger(__name__)

_PACK_LINK_RE = re.compile(
    r"^(?:https?://)?(?:t\.me|telegram\.me)/(?:addemoji|addstickers)/([A-Za-z0-9_]+)/?$")
_PACK_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
MAX_TAGS = 12
# Kept in sync with data/starter_packs.yaml "retired" (checked by a test).
RETIRED_LOWER = frozenset({"adaptivepremium", "topicicons", "adaptivelines"})


class EmojiImportError(ValueError):
    """Shown to the admin as-is."""


def parse_pack_ref(text: str) -> str:
    value = text.strip()
    if m := _PACK_LINK_RE.match(value):
        return m.group(1)
    if _PACK_NAME_RE.match(value):
        return value
    raise EmojiImportError("Send a pack link like https://t.me/addemoji/DogsEmoji or its name.")


def normalize_tag(text: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", text.strip().lower().replace(" ", "_").replace("-", "_"))[:32]


def sticker_kind(sticker: Sticker) -> str:
    if sticker.is_animated:
        return "animated"
    if sticker.is_video:
        return "video"
    return "static"


@dataclass(slots=True)
class ImportResult:
    pack_name: str
    pack_title: str
    added: int = 0
    updated: int = 0
    skipped_static: int = 0

    @property
    def total(self) -> int:
        return self.added + self.updated


async def import_pack(bot: Bot, session: AsyncSession, owner_id: int, ref: str,
                      *, include_static: bool = False) -> ImportResult:
    name = parse_pack_ref(ref)
    if name.lower() in RETIRED_LOWER:
        raise EmojiImportError(f"“{name}” is blocked: its icons don't animate.")
    try:
        sticker_set = await bot.get_sticker_set(name)
    except TelegramBadRequest as exc:
        raise EmojiImportError(f"Telegram can't find a pack called “{name}”.") from exc
    if sticker_set.sticker_type != StickerType.CUSTOM_EMOJI:
        raise EmojiImportError(f"“{sticker_set.title}” is a sticker pack, not an emoji pack. "
                               "Look for t.me/addemoji/… links.")
    repo = EmojiRepo(session, owner_id)
    result = ImportResult(sticker_set.name, sticker_set.title)
    stickers = [s for s in sticker_set.stickers if s.custom_emoji_id]
    existing = await repo.by_custom_ids([s.custom_emoji_id for s in stickers if s.custom_emoji_id])
    for sticker in stickers:
        assert sticker.custom_emoji_id is not None
        kind = sticker_kind(sticker)
        if kind == "static" and not include_static:
            result.skipped_static += 1
            continue
        item = existing.get(sticker.custom_emoji_id)
        if item is None:
            item = EmojiLibraryItem(custom_emoji_id=sticker.custom_emoji_id, tags=[])
            repo.add(item)
            result.added += 1
        else:
            result.updated += 1
        item.fallback = (sticker.emoji or "⭐")[:16]
        item.pack_name = sticker_set.name
        item.pack_title = sticker_set.title[:128]
        item.kind = kind
        item.is_active = True
    await session.flush()
    log.info("emoji_pack_imported", pack=name, added=result.added, updated=result.updated,
             skipped_static=result.skipped_static)
    return result


@dataclass(frozen=True, slots=True)
class FoundEmoji:
    custom_emoji_id: str
    fallback: str


def custom_emoji_in(message: Message) -> list[FoundEmoji]:
    """Custom emoji in a message's text or caption, in order, without duplicates."""
    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []
    found: dict[str, FoundEmoji] = {}
    for entity in entities:
        if entity.type == MessageEntityType.CUSTOM_EMOJI and entity.custom_emoji_id:
            fallback = entity.extract_from(text) or "⭐"
            found.setdefault(entity.custom_emoji_id, FoundEmoji(entity.custom_emoji_id, fallback))
    return list(found.values())


async def add_from_message(bot: Bot, session: AsyncSession, owner_id: int, message: Message,
                           mood: str | None) -> tuple[int, int]:
    """Add the message's custom emoji to the library, tagged with `mood`. Returns (new, tagged)."""
    found = custom_emoji_in(message)
    if not found:
        raise EmojiImportError("That message has no custom emoji. Send emoji from a premium "
                               "pack (they look animated in your emoji keyboard).")
    stickers: dict[str, Sticker] = {}
    try:
        for chunk in range(0, len(found), 200):
            batch = found[chunk:chunk + 200]
            for st in await bot.get_custom_emoji_stickers([f.custom_emoji_id for f in batch]):
                if st.custom_emoji_id:
                    stickers[st.custom_emoji_id] = st
    except TelegramBadRequest as exc:
        log.warning("custom_emoji_lookup_failed", error=exc.message)
    repo = EmojiRepo(session, owner_id)
    existing = await repo.by_custom_ids([f.custom_emoji_id for f in found])
    new = 0
    for emoji in found:
        item = existing.get(emoji.custom_emoji_id)
        sticker = stickers.get(emoji.custom_emoji_id)
        if item is None:
            item = EmojiLibraryItem(custom_emoji_id=emoji.custom_emoji_id, tags=[])
            repo.add(item)
            new += 1
        item.fallback = ((sticker.emoji if sticker else None) or emoji.fallback)[:16]
        item.pack_name = sticker.set_name if sticker else item.pack_name
        item.kind = sticker_kind(sticker) if sticker else (item.kind or "animated")
        item.is_active = True
        if mood:
            item.tags = sorted({*item.tags, mood})[:MAX_TAGS]
    await session.flush()
    return new, len(found)


@dataclass(slots=True)
class EmojiLibrary:
    """In-memory view of the library for fast rendering; reload after every change."""

    moods: Mapping[str, Sequence[str]]
    default_ui_pack: str | None = None
    # Curated menu icons (data/ui_icons.yaml): used first in the default "Premium" style.
    ui_icons: Mapping[str, str] = field(default_factory=dict)
    base_packs: frozenset[str] = frozenset()
    palette: EmojiPalette = field(init=False)
    _ui_maps: dict[str | None, dict[str, str]] = field(default_factory=dict, init=False)
    _post_emojifiers: dict[str | None, Emojifier] = field(default_factory=dict, init=False)
    _items: list[LibEmoji] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.palette = EmojiPalette(self.moods)

    def load(self, items: Sequence[EmojiLibraryItem]) -> None:
        base = EmojiPalette(self.moods)
        lib = [
            LibEmoji(i.custom_emoji_id, i.fallback, i.pack_name,
                     frozenset({*i.tags, *base.auto_tags(i.fallback)}), i.kind != "static",
                     alive=i.kind != "static" and (i.motion is None
                                                   or i.motion >= ALIVE_THRESHOLD),
                     motion=i.motion)
            for i in items if i.is_active
        ]
        self._items = lib
        self.palette = EmojiPalette(self.moods, lib, self.base_packs)
        self._ui_maps.clear()
        self._post_emojifiers.clear()

    async def reload(self, sessions: async_sessionmaker[AsyncSession], owner_id: int) -> None:
        async with sessions() as session:
            self.load(await EmojiRepo(session, owner_id).all(active_only=True))

    @property
    def size(self) -> int:
        return len(self._items)

    def packs(self) -> list[str]:
        return sorted({e.pack for e in self._items if e.pack})

    def ui_map(self, pack: str | None) -> dict[str, str]:
        """Plain emoji -> custom id for menus.

        pack=None is the default "Premium" style: curated icons, then the default pack,
        then any animated emoji. A chosen pack goes first, curated icons fill its gaps.
        """
        if pack in self._ui_maps:
            return self._ui_maps[pack]
        mapping: dict[str, str] = {}
        # Hand-picked icons count only once measured as moving (and not from a retired pack).
        alive_ids = {e.custom_emoji_id for e in self._items
                     if e.motion is not None and e.motion >= ALIVE_THRESHOLD}
        curated = {normalize_emoji(k): v for k, v in self.ui_icons.items() if v in alive_ids}
        if pack is None:
            mapping.update(curated)
        # Menus only use emoji measured as clearly moving; livelier ones win.
        lively = sorted((e for e in self._items if e.motion is not None
                         and e.motion >= ALIVE_THRESHOLD),
                        key=lambda e: -(e.motion or 0.0))
        for preferred in [p for p in (pack, self.default_ui_pack) if p]:
            for e in lively:
                if e.pack == preferred:
                    mapping.setdefault(normalize_emoji(e.fallback), e.custom_emoji_id)
            if preferred == pack:
                for key, value in curated.items():
                    mapping.setdefault(key, value)
        for e in lively:
            mapping.setdefault(normalize_emoji(e.fallback), e.custom_emoji_id)
        self._ui_maps[pack] = mapping
        return mapping

    def post_emojifier(self, style: str | None) -> Emojifier:
        """Turns plain emoji in post text (e.g. written by the AI) into living animated ones:
        the chosen style pack first, then expressive packs, base packs last; livelier wins."""
        if style in self._post_emojifiers:
            return self._post_emojifiers[style]

        def rank(e: LibEmoji) -> tuple[int, int, float]:
            return (0 if style and e.pack == style else 1,
                    1 if e.pack in self.base_packs else 0, -(e.motion or 0.0))

        mapping: dict[str, str] = {}
        for e in sorted((e for e in self._items if e.alive), key=rank):
            mapping.setdefault(normalize_emoji(e.fallback), e.custom_emoji_id)
        self._post_emojifiers[style] = Emojifier(mapping)
        return self._post_emojifiers[style]

    def sample(self, fallback: str, pack: str | None = None) -> str | None:
        return self.ui_map(pack).get(normalize_emoji(fallback))
