"""Render posts and send them: previews to the admin, real posts to channels."""

from __future__ import annotations

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
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
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
from jakov.engine.compose import RenderInput, needed_pools, render, resolve_spintax
from jakov.engine.emoji_render import EmojiPicker, merge_moods, strip_custom_emoji
from jakov.engine.limits import check_length
from jakov.engine.variables import builtin_values
from jakov.logging_setup import get_logger
from jakov.services.emoji_capability import has_custom_emoji
from jakov.services.emoji_library import EmojiLibrary
from jakov.services.pools import pool_values
from jakov.services.send_queue import SendQueue
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
    html = render(variation.resolved, RenderInput(values, fields), picker,
                  capitalize=not variation.is_custom)
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
    bot: Bot, queue: SendQueue, chat_id: int, html: str, *, media_kind: str | None,
    media_file_id: str | None, buttons: list[dict[str, str]], silent: bool = False,
    link_preview: bool = True, extra_rows: list[list[InlineKeyboardButton]] | None = None,
) -> Message:
    """Send a rendered post through the queue (rate limits + retries).

    Raises TelegramAPIError subclasses that aren't worth retrying (Forbidden, BadRequest).
    """
    markup = url_keyboard(buttons, extra_rows)

    async def attempt() -> Message:
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

    return await queue.run(chat_id, attempt)


def pick_variation(post: Post, *, rotate: bool | None = None,
                   last_index: int | None = None) -> PostVariation:
    """The chosen variation, or the next one in rotation after `last_index`."""
    rotate = post.rotate if rotate is None else rotate
    last_index = post.last_variation_index if last_index is None else last_index
    variations = list(post.variations) if rotate else post.active_variations()
    if not variations:
        raise PublishError("This post has no text yet.")
    if not rotate:
        return variations[0]
    by_idx = sorted(variations, key=lambda v: v.idx)
    following = [v for v in by_idx if v.idx > last_index]
    return following[0] if following else by_idx[0]


def fresh_spin(variation: PostVariation) -> PostVariation:
    """A detached copy re-spun from its template with new emoji picks (scheduled sends)."""
    rng = random.Random()
    return PostVariation(owner_id=variation.owner_id, idx=variation.idx,
                         template=variation.template,
                         resolved=resolve_spintax(variation.template, rng),
                         is_custom=variation.is_custom, emoji_seed=rng.randrange(1, 2**62))


def ensure_can_post(chat: Chat) -> None:
    if not chat.is_active or not chat.can_post:
        raise PublishError(f"I can't post in {chat.name}: check my admin rights there.",
                           lost_access=True)


async def render_for_chat(
    session: AsyncSession, owner_id: int, post: Post, chat: Chat, variation: PostVariation,
    catalog: Catalog, library: EmojiLibrary, *, consume_pools: bool = True,
) -> Rendered:
    use_custom = chat.custom_emoji_ok is not False
    rendered = await render_variation(session, owner_id, post, variation, catalog, library,
                                      custom_emoji=use_custom, chat_title=chat.title,
                                      consume_pools=consume_pools)
    length = check_length(rendered.html, post.has_media)
    if not length.ok:
        raise PublishError(f"The text is {length.length} characters; the limit here is "
                           f"{length.limit}. Shorten it first.")
    return rendered


async def publish(
    bot: Bot, session: AsyncSession, owner_id: int, post: Post, chat: Chat, catalog: Catalog,
    library: EmojiLibrary, queue: SendQueue, variation: PostVariation | None = None,
) -> tuple[PublishedPost, list[str]]:
    """Render and send `post` to `chat`. Returns the record and human-readable notes."""
    ensure_can_post(chat)
    variation = variation or pick_variation(post)
    rendered = await render_for_chat(session, owner_id, post, chat, variation, catalog, library)
    return await deliver(bot, session, owner_id, post, chat, rendered, variation.idx, queue)


async def deliver(
    bot: Bot, session: AsyncSession, owner_id: int, post: Post, chat: Chat,
    rendered: Rendered, variation_idx: int | None, queue: SendQueue,
) -> tuple[PublishedPost, list[str]]:
    """Send already-rendered HTML (e.g. an approved run) and record it."""
    ensure_can_post(chat)
    length = check_length(rendered.html, post.has_media)
    if not length.ok:
        raise PublishError(f"The text is {length.length} characters; the limit here is "
                           f"{length.limit}. Shorten it first.")
    notes: list[str] = []
    try:
        message = await send_rendered(
            bot, queue, chat.tg_chat_id, rendered.html, media_kind=post.media_kind,
            media_file_id=post.media_file_id, buttons=post.buttons, silent=post.silent,
            link_preview=post.link_preview)
    except TelegramForbiddenError as exc:
        raise PublishError(f"Telegram refused: I'm not allowed to post in {chat.name}.",
                           lost_access=True) from exc
    except TelegramBadRequest as exc:
        lost = "not enough rights" in exc.message or "chat not found" in exc.message
        raise PublishError(f"Telegram rejected the post: {exc.message}", lost_access=lost) from exc
    except (TelegramRetryAfter, TelegramNetworkError, TelegramServerError) as exc:
        raise PublishError(f"Telegram kept failing after several retries: {exc}") from exc

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
            await queue.run(chat.tg_chat_id, lambda: bot.pin_chat_message(
                chat.tg_chat_id, message.message_id, disable_notification=post.silent))
            pinned = True
        except TelegramAPIError as exc:
            notes.append(f"Couldn't pin: {getattr(exc, 'message', str(exc))}")

    record = PublishedPost(
        owner_id=owner_id, post_id=post.id, chat_id=chat.id, tg_chat_id=chat.tg_chat_id,
        message_id=message.message_id, variation_idx=variation_idx, media_kind=post.media_kind,
        html=rendered.html, buttons=list(post.buttons),
        custom_emoji_used=rendered.has_custom_emoji and has_custom_emoji(message),
        pinned=pinned, sent_at=datetime.now(UTC),
    )
    session.add(record)
    if variation_idx is not None:
        post.last_variation_index = variation_idx
    await session.flush()
    log.info("published", post_id=post.id, chat_id=chat.tg_chat_id,
             message_id=message.message_id, variation=variation_idx)
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
