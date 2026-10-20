from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from jakov.db.models import Chat, Schedule
from jakov.keyboards.callbacks import MenuCb, PostCb, SchCb
from jakov.keyboards.common import cancel_button
from jakov.keyboards.ui import Style, btn, grid, kb

DAILY_TIMES = [8 * 60, 9 * 60, 12 * 60, 15 * 60, 18 * 60, 20 * 60, 21 * 60, 22 * 60]
INTERVALS = [15, 30, 60, 120, 180, 360, 720, 1440]
END_COUNTS = [5, 10, 30]
STATUS_ICON = {"active": "✅", "paused": "💤", "finished": "🏁"}


def _b(text: str, action: str, pk: int = 0, value: int = 0, style: Style = None
       ) -> InlineKeyboardButton:
    return btn(text, SchCb(action=action, pk=pk, value=value), style)


def chat_kb(post_id: int, chats: list[Chat]) -> InlineKeyboardMarkup:
    rows = [[_b(f"📣 {c.name}"[:60], "chat", post_id, c.id)] for c in chats]
    rows.append([cancel_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def when_kb(post_id: int) -> InlineKeyboardMarkup:
    return kb(
        [_b("⏳ In 1 hour", "once", post_id, 1), _b("🌞 Tomorrow 09:00", "once", post_id, 2)],
        [_b("🌛 Tomorrow 18:00", "once", post_id, 3), _b("⏰ Pick date & time", "once_type",
                                                          post_id)],
        [_b("📆 Every day at…", "kind", post_id, 1, "primary"),
         _b("🔄 Every few hours…", "kind", post_id, 2, "primary")],
        cancel_button(),
    )


def daily_kb(post_id: int) -> InlineKeyboardMarkup:
    buttons = [_b(f"{m // 60:02d}:{m % 60:02d}", "daily", post_id, m) for m in DAILY_TIMES]
    return InlineKeyboardMarkup(inline_keyboard=[
        *grid(buttons, 4), [_b("⌨️ Another time", "daily_type", post_id)],
        [_b("👈 Back", "when", post_id), cancel_button()]])


def every_kb(post_id: int, minimum: int, labels: dict[int, str]) -> InlineKeyboardMarkup:
    buttons = [_b(labels[m], "every", post_id, m) for m in INTERVALS if m >= minimum]
    return InlineKeyboardMarkup(inline_keyboard=[
        *grid(buttons, 4), [_b("⌨️ Another interval", "every_type", post_id)],
        [_b("👈 Back", "when", post_id), cancel_button()]])


def summary_kb(post_id: int, *, recurring: bool, interval: bool, ends: str, rotate: bool,
               approval: bool, can_rotate: bool, starts_now: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if recurring:
        rows.append([_b(f"🏁 Ends: {ends}", "ends", post_id)])
    if interval:
        rows.append([_b("▶️ First post: right away" if starts_now
                        else "▶️ First post: after one interval", "first", post_id)])
    toggles = [_b(f"🛂 Approval: {'on' if approval else 'off'}", "opt_approval", post_id)]
    if can_rotate:
        toggles.insert(0, _b(f"🔄 Rotate: {'on' if rotate else 'off'}", "opt_rotate", post_id))
    rows.append(toggles)
    rows.append([_b("✏️ Change time", "when", post_id)])
    rows.append([_b("✅ Confirm", "confirm", post_id, style="success"), cancel_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ends_kb(post_id: int) -> InlineKeyboardMarkup:
    counts = [_b(f"After {n} posts", "end_count", post_id, n) for n in END_COUNTS]
    return kb(
        _b("Never", "end_count", post_id, 0),
        counts,
        [_b("🔟 Other number", "end_type", post_id, 1), _b("📆 On a date", "end_type", post_id, 2)],
        _b("👈 Back", "summary", post_id),
    )


def schedules_list_kb(items: list[tuple[Schedule, str]]) -> InlineKeyboardMarkup:
    rows = [[_b(label[:60], "open", sch.id)] for sch, label in items]
    rows.append([btn("✍️ Create a post", MenuCb(to="newpost"), "primary")])
    rows.append([btn("🏠 Menu", MenuCb(to="main"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def schedule_kb(sch: Schedule) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if sch.status == "active":
        rows.append([_b("🚀 Send now", "sendnow", sch.id, style="primary"),
                     _b("💤 Pause", "pause", sch.id)])
    elif sch.status == "paused":
        rows.append([_b("▶️ Resume", "resume", sch.id, style="success"),
                     _b("🚀 Send now", "sendnow", sch.id, style="primary")])
    rows.append([_b("✏️ Edit timing", "edit", sch.id),
                 btn("📝 Edit post", PostCb(action="back", post=sch.post_id))])
    rows.append([_b("📖 History", "history", sch.id),
                 _b("❌ Delete", "delete", sch.id, style="danger")])
    rows.append([_b("👈 Schedules", "list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_delete_kb(sch: Schedule) -> InlineKeyboardMarkup:
    return kb(_b("❌ Yes, delete the schedule", "delete_go", sch.id, style="danger"),
              _b("👈 Back", "open", sch.id))


def back_to_schedule_kb(sch_id: int) -> InlineKeyboardMarkup:
    return kb(_b("👈 Back", "open", sch_id))
