from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.context import AppContext
from jakov.db.models import Post
from jakov.db.repositories.posts import PostRepo

router = Router(name="post_wizard")
router.message.filter(F.chat.type == ChatType.PRIVATE)

MAX_BUTTONS = 6


class PostWizard(StatesGroup):
    answering = State()
    waiting_media = State()
    waiting_buttons = State()
    reviewing = State()
    editing_text = State()


async def load_post(callback: CallbackQuery, session: AsyncSession, ctx: AppContext,
                    post_id: int) -> Post | None:
    post = await PostRepo(session, ctx.owner_id).get(post_id)
    if post is None:
        await callback.answer("This draft no longer exists. Start a new post.", show_alert=True)
    return post


def summary_line(post: Post, ctx: AppContext) -> str:
    post_type = ctx.catalog.types[post.post_type]
    tone = ctx.catalog.tones.get(post.tone or "")
    parts = [post_type.title]
    if tone:
        parts.append(tone.title)
    parts.append(f"🎨 {html.escape(style_label(post))}")
    return " · ".join(parts)


def style_label(post: Post) -> str:
    return post.emoji_style or "Mixed"
