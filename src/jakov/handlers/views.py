"""Text for the main screens, shared by commands and buttons."""

from __future__ import annotations

import html

from sqlalchemy.ext.asyncio import AsyncSession

from jakov.context import AppContext
from jakov.db.base import utcnow
from jakov.db.models import BotCapability, Chat, ChatKind
from jakov.db.repositories.chats import ChatRepo
from jakov.db.repositories.posts import PublishedRepo
from jakov.db.repositories.schedules import ScheduleRepo
from jakov.db.repositories.users import UserRepo
from jakov.keyboards.channels import KIND_ICON
from jakov.services.rights import RIGHT_LABELS, publisher_problems, rights_of
from jakov.services.timezones import effective_zone
from jakov.utils.time import format_local

_SHORT_RIGHTS = {
    "can_post": "Post", "can_edit": "Edit", "can_delete": "Delete",
    "can_pin": "Pin", "can_restrict": "Ban", "can_invite": "Invite",
}
assert _SHORT_RIGHTS.keys() == RIGHT_LABELS.keys()


async def zone_for(session: AsyncSession, ctx: AppContext, user_id: int) -> tuple[str, bool]:
    """Returns (zone name, is_personal)."""
    user = await UserRepo(session, ctx.owner_id).get(user_id)
    if user and user.timezone:
        return user.timezone, True
    return ctx.settings.timezone, False


def emoji_status(cap: BotCapability | None) -> str:
    if cap is None:
        return "❔ not tested yet"
    return "✅ animated emoji work" if cap.supported else "❗ normal emoji only (auto fallback)"


async def main_menu_text(session: AsyncSession, ctx: AppContext, user_id: int) -> str:
    """A short dashboard: what's linked, what's next, what's done."""
    chats = [c for c in await ChatRepo(session, ctx.owner_id).list() if c.is_active]
    if not chats:
        return ("👋 <b>Welcome to Jakov</b>\n\n"
                "First step: add me as an admin to your channel, then open "
                "<b>📣 Channels</b> and tap <b>➕ Add</b>.")
    zone_name, _ = await zone_for(session, ctx, user_id)
    zone = effective_zone(zone_name, ctx.settings.timezone)
    schedules = await ScheduleRepo(session, ctx.owner_id).all()
    upcoming = sorted((s for s in schedules if s.status == "active" and s.next_run_at),
                      key=lambda s: s.next_run_at or utcnow())
    names = {c.id: c.name for c in chats}
    lines = ["🤖 <b>Jakov</b>", "", f"📣 Channels: <b>{len(chats)}</b>"]
    if upcoming:
        nxt = upcoming[0]
        assert nxt.next_run_at is not None
        lines.append(f"⏰ Next post: <b>{format_local(nxt.next_run_at, zone)}</b> · "
                     f"{html.escape(names.get(nxt.chat_id, 'chat'))}")
        lines.append(f"📆 Active schedules: <b>{len(upcoming)}</b>")
    else:
        lines.append("⏰ Nothing scheduled yet")
    published = await PublishedRepo(session, ctx.owner_id).count()
    lines.append(f"📰 Published: <b>{published}</b>")
    return "\n".join(lines)


def chat_card(chat: Chat, zone_name: str) -> str:
    zone = effective_zone(None, zone_name)
    lines = [f"{KIND_ICON[chat.kind]} <b>{html.escape(chat.name)}</b>"]
    if chat.display_name and chat.title and chat.display_name != chat.title:
        lines.append(f"Title: {html.escape(chat.title)}")
    ident = f"@{chat.username} · " if chat.username else ""
    lines.append(f"{ident}ID <code>{chat.tg_chat_id}</code> · {chat.kind.value}")

    if not chat.is_active:
        lines.append("Status: ❌ not a member")
    elif chat.bot_status in ("administrator", "creator"):
        lines.append("Status: ✅ admin")
    else:
        lines.append(f"Status: ❗ {chat.bot_status}, not admin")
    rights = rights_of(chat).flags()
    lines.append("Rights: " + "  ".join(
        f"{'✅' if rights[k] else '❌'} {label}" for k, label in _SHORT_RIGHTS.items()
    ))
    if chat.kind is ChatKind.CHANNEL:
        lines.append(
            f"Discussion group: <code>{chat.linked_chat_id}</code>"
            if chat.linked_chat_id else "Discussion group: none"
        )
    emoji = {None: "❔ not tested", True: "✅ works here", False: "❗ falls back to normal emoji"}
    lines.append(f"Custom emoji: {emoji[chat.custom_emoji_ok]}")
    if chat.rights_checked_at:
        lines.append(f"Checked: {format_local(chat.rights_checked_at, zone)}")
    problems = publisher_problems(chat.kind, rights_of(chat))
    if problems:
        lines.append("")
        lines.extend(f"❗ {html.escape(p)}" for p in problems)
    return "\n".join(lines)
