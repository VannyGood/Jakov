from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from jakov.db.models import Chat, Schedule
from jakov.keyboards.callbacks import MenuCb, PostCb, SchCb
from jakov.keyboards.common import cancel_button

DAILY_TIMES = [8 * 60, 9 * 60, 12 * 60, 15 * 60, 18 * 60, 20 * 60, 21 * 60, 22 * 60]
INTERVALS = [15, 30, 60, 120, 180, 360, 720, 1440]
STATUS_ICON = {"active": "🟢", "paused": "⏸", "finished": "🏁"}


def _b(text: str, action: str, pk: int = 0, value: int = 0) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text,
                                callback_data=SchCb(action=action, pk=pk, value=value).pack())


def _rows(buttons: list[InlineKeyboardButton], per_row: int) -> list[list[InlineKeyboardButton]]:
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def chat_kb(post_id: int, chats: list[Chat]) -> InlineKeyboardMarkup:
    rows = [[_b(f"📢 {c.name}"[:60], "chat", post_id, c.id)] for c in chats]
    rows.append([cancel_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kind_kb(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("🕐 Once", "kind", post_id, 0)],
        [_b("📅 Every day at…", "kind", post_id, 1)],
        [_b("🔁 Every N hours / minutes", "kind", post_id, 2)],
        [cancel_button()],
    ])


def once_kb(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("⏩ In 1 hour", "once", post_id, 1), _b("🌅 Tomorrow 09:00", "once", post_id, 2)],
        [_b("🌆 Tomorrow 18:00", "once", post_id, 3)],
        [cancel_button()],
    ])


def daily_kb(post_id: int) -> InlineKeyboardMarkup:
    buttons = [_b(f"{m // 60:02d}:{m % 60:02d}", "daily", post_id, m) for m in DAILY_TIMES]
    rows = _rows(buttons, 4)
    rows.append([_b("⌨️ Another time", "daily_type", post_id)])
    rows.append([cancel_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def every_kb(post_id: int, minimum: int, labels: dict[int, str]) -> InlineKeyboardMarkup:
    buttons = [_b(labels[m], "every", post_id, m) for m in INTERVALS if m >= minimum]
    rows = _rows(buttons, 4)
    rows.append([_b("⌨️ Another interval", "every_type", post_id)])
    rows.append([cancel_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def first_kb(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("▶️ Right away", "first", post_id, 0)],
        [_b("⏭ After one interval", "first", post_id, 1)],
        [_b("🕐 At a time I choose", "first", post_id, 2)],
        [cancel_button()],
    ])


def limit_kb(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("♾ Forever", "limit", post_id, 0)],
        [_b("🔢 N times, then stop", "limit", post_id, 1)],
        [_b("📅 Until a date", "limit", post_id, 2)],
        [cancel_button()],
    ])


def options_kb(post_id: int, rotate: bool, approval: bool, can_rotate: bool
               ) -> InlineKeyboardMarkup:
    rows = []
    if can_rotate:
        rows.append([_b(f"🔁 Rotate variations: {'On' if rotate else 'Off'}", "opt_rotate",
                        post_id)])
    rows.append([_b(f"🛂 Ask my approval first: {'On' if approval else 'Off'}", "opt_approval",
                    post_id)])
    rows.append([_b("✅ Continue", "summary", post_id)])
    rows.append([cancel_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def summary_kb(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("✅ Confirm schedule", "confirm", post_id)],
        [_b("✏️ Change timing", "retime", post_id)],
        [cancel_button()],
    ])


def schedules_list_kb(items: list[tuple[Schedule, str]]) -> InlineKeyboardMarkup:
    rows = [[_b(label[:60], "open", sch.id)] for sch, label in items]
    rows.append([InlineKeyboardButton(text="✍️ New post", callback_data=MenuCb(
        to="newpost").pack())])
    rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data=MenuCb(to="main").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def schedule_kb(sch: Schedule) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if sch.status == "active":
        rows.append([_b("⏸ Pause", "pause", sch.id), _b("📨 Send now", "sendnow", sch.id)])
    elif sch.status == "paused":
        rows.append([_b("▶️ Resume", "resume", sch.id), _b("📨 Send now", "sendnow", sch.id)])
    rows.append([_b("✏️ Edit timing", "edit", sch.id),
                 InlineKeyboardButton(text="📝 Edit post", callback_data=PostCb(
                     action="back", post=sch.post_id).pack())])
    rows.append([_b("📜 History", "history", sch.id), _b("🗑 Delete", "delete", sch.id)])
    rows.append([_b("⬅️ Schedules", "list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_delete_kb(sch: Schedule) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("🗑 Yes, delete schedule", "delete_go", sch.id)],
        [_b("⬅️ Back", "open", sch.id)],
    ])


def back_to_schedule_kb(sch_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_b("⬅️ Back", "open", sch_id)]])
