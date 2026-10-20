"""Schedule cards shared by /schedules and the schedule wizard."""

from __future__ import annotations

import html

from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.context import AppContext
from jakov.db.models import Schedule
from jakov.db.repositories.chats import ChatRepo
from jakov.db.repositories.posts import PostRepo
from jakov.handlers.views import zone_for
from jakov.keyboards.schedules import STATUS_ICON, schedule_kb
from jakov.services.scheduling import limit_text, timing_text
from jakov.services.timezones import effective_zone
from jakov.utils.telegram import show
from jakov.utils.time import format_local


async def schedule_card(sch: Schedule, ctx: AppContext, session: AsyncSession,
                        user_id: int) -> str:
    zone_name, _ = await zone_for(session, ctx, user_id)
    zone = effective_zone(zone_name, ctx.settings.timezone)
    chat = await ChatRepo(session, ctx.owner_id).get(sch.chat_id)
    post = await PostRepo(session, ctx.owner_id).get(sch.post_id)
    title = ctx.catalog.types[post.post_type].title if post else "Post"
    status = {"active": "✅ Active", "paused": "💤 Paused", "finished": "🏁 Finished"}
    lines = [
        f"📆 <b>{title}</b> → <b>{html.escape(chat.name if chat else 'removed chat')}</b>",
        f"Status: {status.get(sch.status, sch.status)}",
    ]
    if sch.paused_reason and sch.status == "paused":
        lines.append(f"   <i>{html.escape(sch.paused_reason)}</i>")
    lines += [
        f"⏰ {html.escape(timing_text(sch, zone))}",
        f"🏁 {html.escape(limit_text(sch, zone))}",
        f"🔄 Rotate: {'on' if sch.rotate else 'off'} · 🛂 Approval: "
        f"{'on' if sch.require_approval else 'off'}",
        f"👉 Next run: <b>{format_local(sch.next_run_at, zone) if sch.next_run_at else '—'}</b>",
    ]
    if sch.last_run_at:
        lines.append(f"⏰ Last run: {format_local(sch.last_run_at, zone)}")
    lines.append(f"🚀 Sent: <b>{sch.sent_count}</b> · Skipped: {sch.skipped_count}")
    if sch.last_error:
        lines.append(f"❗ Last error: {html.escape(sch.last_error[:200])}")
    return "\n".join(lines)


async def render_schedule(target: Message | CallbackQuery, sch: Schedule, ctx: AppContext,
                          session: AsyncSession, user_id: int, prefix: str = "") -> None:
    await show(target, prefix + await schedule_card(sch, ctx, session, user_id),
               schedule_kb(sch))


def list_label(sch: Schedule, chat_name: str, next_local: str) -> str:
    return f"{STATUS_ICON.get(sch.status, '•')} {chat_name} · {next_local}"
