"""Render posts and send them: previews to the admin, real posts to channels."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.db.base import utcnow
from jakov.db.models import Chat, Post, PostVariation, PublishedPost
from jakov.engine.catalog import Catalog
from jakov.engine.compose import RenderInput, needed_pools, render
from jakov.engine.emoji_render import EmojiPicker, merge_moods, strip_custom_emoji
from jakov.engine.limits import check_length
from jakov.engine.variables import builtin_values
from jakov.logging_setup import get_logger
from jakov.services.emoji_capability import has_custom_emoji
from jakov.services.emoji_library import EmojiLibrary
from jakov.services.pools import pool_values
from jakov.services.ui_emoji import raw_output

log = get_logger(__name__)


class PublishError(Exception):
    """User-facing reason a post couldn't be sent."""

    def __init__(self, message: str, *, lost_access: bool = False) -> None:
        super().__init__(message)
        self.lost_access = lost_access


@dataclass(frozen=True, slots=True)
class Rendered:
    html: str
    has_custom_emoji: bool


def post_moods(post: Post, catalog: Catalog) -> list[str]:
    post_type = catalog.types[post.post_type]
    tone = catalog.tones.get(post.tone or "")
    choice_palettes: list[str] = []
    for question in post_type.questions:
        if question.kind == "choice":
            chosen = post.answers.get(question.key)
            for option in question.options:
                if option.value == chosen:
                    choice_palettes.extend(option.palette)
    return merge_moods(choice_palettes, tone.palette if tone else (), post_type.palette)


def answer_values(post: Post, catalog: Catalog) -> dict[str, str]:
    """Wizard answers as template values; choice answers show their label text."""
    post_type = catalog.types[post.post_type]
    values = dict(post.answers)
    for question in post_type.questions:
        if question.kind == "choice" and question.key in values:
            label = next((o.label for o in question.options if o.value == values[question.key]),
                         values[question.key])
            values[question.key] = label.split(" ", 1)[-1]
    return values


async def render_variation(
    session: AsyncSession, owner_id: int, post: Post, variation: PostVariation,
    catalog: Catalog, library: EmojiLibrary, *, custom_emoji: bool, chat_title: str = "",
    consume_pools: bool = False, now: datetime | None = None,
) -> Rendered:
    now_local = (now or utcnow()).astimezone(ZoneInfo(post.timezone))
    moments = {k: datetime.fromisoformat(v) for k, v in post.moments.items()}
    values = {**answer_values(post, catalog), **builtin_values(now_local, moments),
              "channel": chat_title}
    # Datetime answers are displayed from the stored moment, not the raw text typed.
    pools = needed_pools(variation.resolved, catalog.pools)
    values.update(await pool_values(session, owner_id, catalog.pools, pools,
                                    random.Random(variation.emoji_seed), consume=consume_pools))
    fields = frozenset(catalog.types[post.post_type].field_names)
    picker = EmojiPicker(library.palette, random.Random(variation.emoji_seed),
                         custom=custom_emoji, style=post.emoji_style,
                         generic_moods=post_moods(post, catalog))
    html = render(variation.resolved, RenderInput(values, fields), picker)
    if not custom_emoji:
        html = strip_custom_emoji(html)
    return Rendered(html, "<tg-emoji" in html)


def url_keyboard(
    buttons: list[dict[str, str]],
    extra_rows: list[list[InlineKeyboardButton]] | None = None,
) -> InlineKeyboardMarkup | None:
    rows = [[InlineKeyboardButton(text=b["text"], url=b["url"])] for b in buttons]
    rows += extra_rows or []
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def send_rendered(
    bot: Bot, chat_id: int, html: str, *, media_kind: str | None, media_file_id: str | None,
    buttons: list[dict[str, str]], silent: bool = False, link_preview: bool = True,
    extra_rows: list[list[InlineKeyboardButton]] | None = None,
) -> Message:
    """Low-level send with one RetryAfter retry. Raises TelegramAPIError subclasses."""
    markup = url_keyboard(buttons, extra_rows)
    for attempt in range(2):
        try:
            with raw_output():
                if media_kind == "photo" and media_file_id:
                    return await bot.send_photo(chat_id, media_file_id, caption=html,
                                                parse_mode=ParseMode.HTML, reply_markup=markup,
                                                disable_notification=silent)
                if media_kind == "video" and media_file_id:
                    return await bot.send_video(chat_id, media_file_id, caption=html,
                                                parse_mode=ParseMode.HTML, reply_markup=markup,
                                                disable_notification=silent)
                return await bot.send_message(
                    chat_id, html, parse_mode=ParseMode.HTML, reply_markup=markup,
                    disable_notification=silent,
                    link_preview_options=LinkPreviewOptions(is_disabled=not link_preview),
                )
        except TelegramRetryAfter as exc:
            if attempt:
                raise
            log.warning("retry_after", chat_id=chat_id, seconds=exc.retry_after)
            await asyncio.sleep(min(exc.retry_after, 60))
    raise AssertionError("unreachable")


def pick_variation(post: Post) -> PostVariation:
    variations = post.active_variations()
    if not variations:
        raise PublishError("This post has no text yet.")
    if not post.rotate:
        return variations[0]
    by_idx = sorted(variations, key=lambda v: v.idx)
    following = [v for v in by_idx if v.idx > post.last_variation_index]
    return following[0] if following else by_idx[0]


async def publish(
    bot: Bot, session: AsyncSession, owner_id: int, post: Post, chat: Chat, catalog: Catalog,
    library: EmojiLibrary, variation: PostVariation | None = None,
) -> tuple[PublishedPost, list[str]]:
    """Send `post` to `chat`. Returns the record and human-readable notes."""
    if not chat.is_active or not chat.can_post:
        raise PublishError(f"I can't post in {chat.name}: check my admin rights there.",
                           lost_access=True)
    variation = variation or pick_variation(post)
    use_custom = chat.custom_emoji_ok is not False
    rendered = await render_variation(session, owner_id, post, variation, catalog, library,
                                      custom_emoji=use_custom, chat_title=chat.title,
                                      consume_pools=True)
    length = check_length(rendered.html, post.has_media)
    if not length.ok:
        raise PublishError(f"The text is {length.length} characters; the limit here is "
                           f"{length.limit}. Shorten it first.")
    notes: list[str] = []
    try:
        message = await send_rendered(
            bot, chat.tg_chat_id, rendered.html, media_kind=post.media_kind,
            media_file_id=post.media_file_id, buttons=post.buttons, silent=post.silent,
            link_preview=post.link_preview)
    except TelegramForbiddenError as exc:
        raise PublishError(f"Telegram refused: I'm not allowed to post in {chat.name}.",
                           lost_access=True) from exc
    except TelegramBadRequest as exc:
        lost = "not enough rights" in exc.message or "chat not found" in exc.message
        raise PublishError(f"Telegram rejected the post: {exc.message}", lost_access=lost) from exc

    if rendered.has_custom_emoji:
        kept = has_custom_emoji(message)
        if chat.custom_emoji_ok is None or chat.custom_emoji_ok != kept:
            chat.custom_emoji_ok = kept
        if not kept:
            notes.append("Telegram replaced the animated emoji with normal ones in this chat; "
                         "future posts there will use normal emoji automatically.")

    pinned = False
    if post.pin:
        try:
            await bot.pin_chat_message(chat.tg_chat_id, message.message_id,
                                       disable_notification=post.silent)
            pinned = True
        except TelegramAPIError as exc:
            notes.append(f"Couldn't pin: {getattr(exc, 'message', str(exc))}")

    record = PublishedPost(
        owner_id=owner_id, post_id=post.id, chat_id=chat.id, tg_chat_id=chat.tg_chat_id,
        message_id=message.message_id, variation_idx=variation.idx, media_kind=post.media_kind,
        html=rendered.html, buttons=list(post.buttons),
        custom_emoji_used=rendered.has_custom_emoji and has_custom_emoji(message),
        pinned=pinned, sent_at=datetime.now(UTC),
    )
    session.add(record)
    post.last_variation_index = variation.idx
    await session.flush()
    log.info("published", post_id=post.id, chat_id=chat.tg_chat_id,
             message_id=message.message_id, variation=variation.idx)
    return record, notes


def message_link(chat: Chat | None, tg_chat_id: int, message_id: int) -> str:
    if chat is not None and chat.username:
        return f"https://t.me/{chat.username}/{message_id}"
    internal = str(tg_chat_id).removeprefix("-100").lstrip("-")
    return f"https://t.me/c/{internal}/{message_id}"


async def edit_published(bot: Bot, record: PublishedPost, new_html: str) -> None:
    length = check_length(new_html, bool(record.media_kind))
    if not length.ok:
        raise PublishError(f"That text is {length.length} characters; the limit is "
                           f"{length.limit}.")
    markup = url_keyboard(record.buttons)
    try:
        with raw_output():
            if record.media_kind:
                await bot.edit_message_caption(chat_id=record.tg_chat_id,
                                               message_id=record.message_id, caption=new_html,
                                               parse_mode=ParseMode.HTML, reply_markup=markup)
            else:
                await bot.edit_message_text(new_html, chat_id=record.tg_chat_id,
                                            message_id=record.message_id,
                                            parse_mode=ParseMode.HTML, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "message is not modified" in exc.message:
            return
        raise PublishError(f"Telegram couldn't edit it: {exc.message}") from exc
    except TelegramForbiddenError as exc:
        raise PublishError("I no longer have access to that chat.") from exc
    record.html = new_html
    record.edited_at = utcnow()


async def delete_published(bot: Bot, record: PublishedPost) -> None:
    try:
        await bot.delete_message(record.tg_chat_id, record.message_id)
    except TelegramBadRequest as exc:
        if "message to delete not found" not in exc.message:
            raise PublishError(f"Telegram couldn't delete it: {exc.message}") from exc
    except TelegramForbiddenError as exc:
        raise PublishError("I no longer have access to that chat.") from exc
    record.deleted_at = utcnow()
