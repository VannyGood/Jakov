"""⏰ Schedule wizard: (chat) → when → summary with tap-to-change options → confirm.

Also used to change an existing schedule (FSM data "edit" = schedule id).
"""

from __future__ import annotations

import html
from datetime import datetime, time, timedelta

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.context import AppContext
from jakov.db.base import utcnow
from jakov.db.models import Post, Schedule
from jakov.db.repositories.chats import ChatRepo
from jakov.db.repositories.posts import PostRepo
from jakov.db.repositories.schedules import ScheduleRepo
from jakov.engine.recurrence import parse_interval, parse_time_of_day
from jakov.handlers.schedule_views import render_schedule
from jakov.handlers.views import zone_for
from jakov.keyboards.callbacks import SchCb
from jakov.keyboards.common import cancel_kb
from jakov.keyboards.schedules import (
    INTERVALS,
    chat_kb,
    daily_kb,
    ends_kb,
    every_kb,
    summary_kb,
    when_kb,
)
from jakov.logging_setup import get_logger
from jakov.services.scheduling import (
    ScheduleError,
    ScheduleSpec,
    apply_spec,
    interval_label,
    limit_text,
    spec_of,
    timing_text,
)
from jakov.services.timezones import effective_zone
from jakov.utils.dates import DateParseError, localize, parse_when
from jakov.utils.telegram import show
from jakov.utils.time import format_local

log = get_logger(__name__)
router = Router(name="schedule_wizard")
router.message.filter(F.chat.type == ChatType.PRIVATE)
MAX_COUNT = 10_000
START_DELAY = timedelta(seconds=30)


class ScheduleWizard(StatesGroup):
    once_time = State()
    daily_time = State()
    every_value = State()
    limit_count = State()
    limit_until = State()


async def _spec(state: FSMContext) -> ScheduleSpec:
    return ScheduleSpec.from_dict((await state.get_data()).get("spec"))


async def _save(state: FSMContext, spec: ScheduleSpec) -> None:
    await state.update_data(spec=spec.to_dict())


async def _post_id(state: FSMContext) -> int:
    return int((await state.get_data()).get("post", 0))


def _now_local(spec: ScheduleSpec) -> datetime:
    return utcnow().astimezone(effective_zone(spec.timezone, "UTC"))


# --- start ---------------------------------------------------------------------

@router.callback_query(SchCb.filter(F.action == "new"))
async def cb_new(callback: CallbackQuery, callback_data: SchCb, ctx: AppContext,
                 session: AsyncSession, state: FSMContext) -> None:
    post = await PostRepo(session, ctx.owner_id).get(callback_data.pk)
    if post is None or post.status != "ready":
        await callback.answer("Pick a variation first.", show_alert=True)
        return
    chats = [c for c in await ChatRepo(session, ctx.owner_id).list(include_inactive=False)
             if c.can_post]
    if not chats:
        await callback.answer("No chats where I can post. Link one in 📣 Channels.",
                              show_alert=True)
        return
    zone, _ = await zone_for(session, ctx, callback.from_user.id)
    spec = ScheduleSpec(timezone=zone, rotate=post.rotate and len(post.variations) > 1)
    await state.set_state(None)
    await state.set_data({"post": post.id, "spec": spec.to_dict(), "edit": 0, "starts_now": True})
    await callback.answer()
    if len(chats) == 1:  # nothing to choose
        spec.chat_pk = chats[0].id
        await _save(state, spec)
        await _show_when(callback, post.id, f"📣 {html.escape(chats[0].name)}\n\n")
        return
    await show(callback, "⏰ <b>Schedule</b>\n\nWhere should it be posted?",
               chat_kb(post.id, chats))


async def start_retime(callback: CallbackQuery, sch: Schedule, state: FSMContext,
                       ctx: AppContext, session: AsyncSession, zone: str) -> None:
    """Entry point from /schedules → ✏️ Edit timing: opens the summary of that schedule."""
    spec = spec_of(sch)
    spec.timezone = zone
    await state.set_state(None)
    await state.set_data({"post": sch.post_id, "spec": spec.to_dict(), "edit": sch.id,
                          "starts_now": True})
    await _show_summary(callback, ctx, session, state)


@router.callback_query(SchCb.filter(F.action == "chat"))
async def cb_chat(callback: CallbackQuery, callback_data: SchCb, ctx: AppContext,
                  session: AsyncSession, state: FSMContext) -> None:
    chat = await ChatRepo(session, ctx.owner_id).get(callback_data.value)
    if chat is None:
        await callback.answer("That chat is no longer linked.", show_alert=True)
        return
    spec = await _spec(state)
    spec.chat_pk = chat.id
    await _save(state, spec)
    await callback.answer()
    await _show_when(callback, callback_data.pk, f"📣 {html.escape(chat.name)}\n\n")


async def _show_when(target: Message | CallbackQuery, post_id: int, prefix: str = "") -> None:
    await show(target, f"{prefix}⏰ <b>When should it go out?</b>", when_kb(post_id))


@router.callback_query(SchCb.filter(F.action == "when"))
async def cb_when(callback: CallbackQuery, callback_data: SchCb, state: FSMContext) -> None:
    await state.set_state(None)
    await callback.answer()
    await _show_when(callback, callback_data.pk)


# --- once ------------------------------------------------------------------------

@router.callback_query(SchCb.filter(F.action == "once"))
async def cb_once(callback: CallbackQuery, callback_data: SchCb, ctx: AppContext,
                  session: AsyncSession, state: FSMContext) -> None:
    spec = await _spec(state)
    if callback_data.value == 1:
        moment = utcnow() + timedelta(hours=1)
    else:
        clock = time(9, 0) if callback_data.value == 2 else time(18, 0)
        moment = localize(datetime.combine(_now_local(spec).date() + timedelta(days=1), clock),
                          effective_zone(spec.timezone, "UTC"))
    spec.kind, spec.run_at = "once", moment.replace(microsecond=0).isoformat()
    await _save(state, spec)
    await callback.answer()
    await _show_summary(callback, ctx, session, state)


@router.callback_query(SchCb.filter(F.action == "once_type"))
async def cb_once_type(callback: CallbackQuery, state: FSMContext) -> None:
    spec = await _spec(state)
    await state.set_state(ScheduleWizard.once_time)
    await callback.answer()
    await show(callback, f"⏰ Type a date and time ({html.escape(spec.timezone)}), e.g. "
               "<code>friday 18:00</code>, <code>25.12 09:30</code>, <code>in 3 hours</code>.",
               cancel_kb())


@router.message(ScheduleWizard.once_time, F.text)
async def msg_once(message: Message, ctx: AppContext, session: AsyncSession,
                   state: FSMContext) -> None:
    assert message.text is not None
    spec = await _spec(state)
    try:
        moment = parse_when(message.text, _now_local(spec))
    except DateParseError as exc:
        await message.answer(f"❗ {html.escape(str(exc))}", reply_markup=cancel_kb())
        return
    spec.kind, spec.run_at = "once", moment.isoformat()
    await _save(state, spec)
    await _show_summary(message, ctx, session, state)


# --- daily / interval ------------------------------------------------------------------

@router.callback_query(SchCb.filter(F.action == "kind"))
async def cb_kind(callback: CallbackQuery, callback_data: SchCb, ctx: AppContext,
                  state: FSMContext) -> None:
    spec = await _spec(state)
    await callback.answer()
    if callback_data.value == 1:
        await show(callback, f"📆 <b>Every day at what time?</b> ({html.escape(spec.timezone)})",
                   daily_kb(callback_data.pk))
        return
    minimum = ctx.settings.min_interval_minutes
    await show(callback, "🔄 <b>How often?</b>",
               every_kb(callback_data.pk, minimum, {m: interval_label(m) for m in INTERVALS}))


@router.callback_query(SchCb.filter(F.action.in_({"daily", "daily_type"})))
async def cb_daily(callback: CallbackQuery, callback_data: SchCb, ctx: AppContext,
                   session: AsyncSession, state: FSMContext) -> None:
    await callback.answer()
    if callback_data.action == "daily_type":
        await state.set_state(ScheduleWizard.daily_time)
        await show(callback, "⌨️ Type the time, e.g. <code>07:45</code> or <code>9pm</code>.",
                   cancel_kb())
        return
    spec = await _spec(state)
    spec.kind = "daily"
    spec.time_of_day = f"{callback_data.value // 60:02d}:{callback_data.value % 60:02d}"
    await _save(state, spec)
    await _show_summary(callback, ctx, session, state)


@router.message(ScheduleWizard.daily_time, F.text)
async def msg_daily(message: Message, ctx: AppContext, session: AsyncSession,
                    state: FSMContext) -> None:
    assert message.text is not None
    clock = parse_time_of_day(message.text)
    if clock is None:
        await message.answer("❗ Use a time like <code>09:30</code> or <code>9pm</code>.",
                             reply_markup=cancel_kb())
        return
    spec = await _spec(state)
    spec.kind, spec.time_of_day = "daily", clock.strftime("%H:%M")
    await _save(state, spec)
    await _show_summary(message, ctx, session, state)


async def _set_interval(target: Message | CallbackQuery, ctx: AppContext,
                        session: AsyncSession, state: FSMContext, minutes: int) -> None:
    minimum = ctx.settings.min_interval_minutes
    if minutes < minimum or minutes > 31 * 24 * 60:
        await show(target, f"❗ Choose between {minimum} minutes and 31 days.", cancel_kb())
        return
    spec = await _spec(state)
    spec.kind, spec.interval_minutes = "interval", minutes
    starts_now = bool((await state.get_data()).get("starts_now", True))
    spec.anchor_at = _anchor(minutes, starts_now)
    await _save(state, spec)
    await state.set_state(None)
    await _show_summary(target, ctx, session, state)


def _anchor(minutes: int, starts_now: bool) -> str:
    offset = START_DELAY if starts_now else timedelta(minutes=minutes)
    return (utcnow() + offset).replace(microsecond=0).isoformat()


@router.callback_query(SchCb.filter(F.action.in_({"every", "every_type"})))
async def cb_every(callback: CallbackQuery, callback_data: SchCb, ctx: AppContext,
                   session: AsyncSession, state: FSMContext) -> None:
    await callback.answer()
    if callback_data.action == "every_type":
        await state.set_state(ScheduleWizard.every_value)
        await show(callback, "⌨️ Type the interval, e.g. <code>45m</code>, <code>90m</code>, "
                   "<code>4h</code>, <code>2h30m</code>.", cancel_kb())
        return
    await _set_interval(callback, ctx, session, state, callback_data.value)


@router.message(ScheduleWizard.every_value, F.text)
async def msg_every(message: Message, ctx: AppContext, session: AsyncSession,
                    state: FSMContext) -> None:
    assert message.text is not None
    interval = parse_interval(message.text)
    if interval is None:
        await message.answer("❗ Use something like <code>90m</code>, <code>4h</code> or "
                             "<code>2h30m</code>.", reply_markup=cancel_kb())
        return
    await _set_interval(message, ctx, session, state, int(interval.total_seconds() // 60))


@router.callback_query(SchCb.filter(F.action == "first"))
async def cb_first(callback: CallbackQuery, ctx: AppContext, session: AsyncSession,
                   state: FSMContext) -> None:
    starts_now = not bool((await state.get_data()).get("starts_now", True))
    spec = await _spec(state)
    spec.anchor_at = _anchor(spec.interval_minutes or 0, starts_now)
    await state.update_data(starts_now=starts_now)
    await _save(state, spec)
    await callback.answer()
    await _show_summary(callback, ctx, session, state)


# --- ends ------------------------------------------------------------------------

@router.callback_query(SchCb.filter(F.action == "ends"))
async def cb_ends(callback: CallbackQuery, callback_data: SchCb) -> None:
    await callback.answer()
    await show(callback, "🏁 <b>When should it stop?</b>", ends_kb(callback_data.pk))


@router.callback_query(SchCb.filter(F.action == "end_count"))
async def cb_end_count(callback: CallbackQuery, callback_data: SchCb, ctx: AppContext,
                       session: AsyncSession, state: FSMContext) -> None:
    spec = await _spec(state)
    if callback_data.value:
        spec.limit_kind, spec.limit_count, spec.until_at = "count", callback_data.value, None
    else:
        spec.limit_kind, spec.limit_count, spec.until_at = "forever", None, None
    await _save(state, spec)
    await callback.answer()
    await _show_summary(callback, ctx, session, state)


@router.callback_query(SchCb.filter(F.action == "end_type"))
async def cb_end_type(callback: CallbackQuery, callback_data: SchCb, state: FSMContext) -> None:
    await callback.answer()
    if callback_data.value == 1:
        await state.set_state(ScheduleWizard.limit_count)
        await show(callback, "🔟 How many posts in total? e.g. <code>12</code>", cancel_kb())
    else:
        await state.set_state(ScheduleWizard.limit_until)
        await show(callback, "📆 Until when? e.g. <code>31.12</code>, <code>in 2 weeks</code>, "
                   "<code>sunday 23:00</code>.", cancel_kb())


@router.message(ScheduleWizard.limit_count, F.text)
async def msg_limit_count(message: Message, ctx: AppContext, session: AsyncSession,
                          state: FSMContext) -> None:
    assert message.text is not None
    text = message.text.strip()
    if not text.isdigit() or not 1 <= int(text) <= MAX_COUNT:
        await message.answer(f"❗ Send a number from 1 to {MAX_COUNT}.", reply_markup=cancel_kb())
        return
    spec = await _spec(state)
    spec.limit_kind, spec.limit_count, spec.until_at = "count", int(text), None
    await _save(state, spec)
    await _show_summary(message, ctx, session, state)


@router.message(ScheduleWizard.limit_until, F.text)
async def msg_limit_until(message: Message, ctx: AppContext, session: AsyncSession,
                          state: FSMContext) -> None:
    assert message.text is not None
    spec = await _spec(state)
    try:
        moment = parse_when(message.text, _now_local(spec))
    except DateParseError as exc:
        await message.answer(f"❗ {html.escape(str(exc))}", reply_markup=cancel_kb())
        return
    spec.limit_kind, spec.until_at, spec.limit_count = "until", moment.isoformat(), None
    await _save(state, spec)
    await _show_summary(message, ctx, session, state)


# --- summary -----------------------------------------------------------------------

@router.callback_query(SchCb.filter(F.action.in_({"opt_rotate", "opt_approval", "summary"})))
async def cb_option(callback: CallbackQuery, callback_data: SchCb, ctx: AppContext,
                    session: AsyncSession, state: FSMContext) -> None:
    spec = await _spec(state)
    if callback_data.action == "opt_rotate":
        spec.rotate = not spec.rotate
    elif callback_data.action == "opt_approval":
        spec.require_approval = not spec.require_approval
    await _save(state, spec)
    await callback.answer()
    await _show_summary(callback, ctx, session, state)


async def _show_summary(target: Message | CallbackQuery, ctx: AppContext,
                       session: AsyncSession, state: FSMContext) -> None:
    await state.set_state(None)
    data = await state.get_data()
    spec = await _spec(state)
    post = await PostRepo(session, ctx.owner_id).get(int(data.get("post", 0)))
    chat = await ChatRepo(session, ctx.owner_id).get(spec.chat_pk)
    if post is None or chat is None:
        await state.clear()
        await show(target, "❗ The post or chat no longer exists. Start again from the menu.")
        return
    zone = effective_zone(spec.timezone, "UTC")
    try:
        rec = spec.recurrence()
    except ScheduleError:
        await _show_when(target, post.id)
        return
    upcoming = rec.upcoming(utcnow(), 3)
    if (until := spec.until()) is not None:
        upcoming = [u for u in upcoming if u <= until]
    if spec.limit_kind == "count" and spec.limit_count:
        upcoming = upcoming[:spec.limit_count]
    runs = "\n".join(f"   • {format_local(u, zone)}" for u in upcoming) or "   • none"
    which = (f"🔄 rotating {len(post.variations)} variations" if spec.rotate
             else f"✅ variation #{(post.chosen_index or 0) + 1}")
    text = (
        "📝 <b>Check and confirm</b>\n\n"
        f"📣 <b>{html.escape(chat.name)}</b>\n"
        f"⏰ {html.escape(timing_text(spec, zone))}\n"
        f"🏁 {html.escape(limit_text(spec, zone))}\n"
        f"📝 {ctx.catalog.types[post.post_type].title} · {which}\n"
        f"🛂 Approval: {'I ask you before each post' if spec.require_approval else 'off'}\n\n"
        f"<b>Next posts</b> ({html.escape(spec.timezone)}):\n{runs}"
    )
    until_at = spec.until()
    if spec.limit_kind == "count":
        ends = f"after {spec.limit_count} posts"
    elif until_at is not None:
        ends = f"on {format_local(until_at, zone)}"
    else:
        ends = "never"
    await show(target, text, summary_kb(
        post.id, recurring=spec.kind != "once", interval=spec.kind == "interval",
        ends=ends, rotate=spec.rotate, approval=spec.require_approval,
        can_rotate=len(post.variations) > 1, starts_now=bool(data.get("starts_now", True))))


@router.callback_query(SchCb.filter(F.action == "confirm"))
async def cb_confirm(callback: CallbackQuery, ctx: AppContext, session: AsyncSession,
                     state: FSMContext) -> None:
    data = await state.get_data()
    spec = await _spec(state)
    post: Post | None = await PostRepo(session, ctx.owner_id).get(int(data.get("post", 0)))
    if post is None:
        await callback.answer("This draft no longer exists.", show_alert=True)
        return
    repo = ScheduleRepo(session, ctx.owner_id)
    editing = int(data.get("edit", 0))
    sch = await repo.get(editing) if editing else Schedule(
        post_id=post.id, created_by=callback.from_user.id, chat_id=spec.chat_pk,
        timezone=spec.timezone, kind=spec.kind, sent_count=0, skipped_count=0,
        last_variation_index=-1)
    if sch is None:
        await callback.answer("That schedule was deleted.", show_alert=True)
        return
    try:
        apply_spec(sch, spec, utcnow())
    except ScheduleError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    if not editing:
        await repo.add(sch)
    await session.commit()
    await state.clear()
    log.info("schedule_saved", schedule_id=sch.id, kind=sch.kind, edited=bool(editing))
    prefix = "✅ Schedule updated.\n\n" if editing else "✅ <b>Scheduled!</b>\n\n"
    await render_schedule(callback, sch, ctx, session, callback.from_user.id, prefix)
    await callback.answer("Scheduled ✅")
