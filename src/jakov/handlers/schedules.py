"""🗓 /schedules: list, inspect, pause/resume, send now, edit, history, delete."""

from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.context import AppContext
from jakov.db.base import utcnow
from jakov.db.models import Schedule
from jakov.db.repositories.chats import ChatRepo
from jakov.db.repositories.schedules import ScheduleRepo
from jakov.handlers.schedule_views import list_label, render_schedule
from jakov.handlers.schedule_wizard import start_retime
from jakov.handlers.views import zone_for
from jakov.keyboards.callbacks import MenuCb, SchCb
from jakov.keyboards.schedules import back_to_schedule_kb, confirm_delete_kb, schedules_list_kb
from jakov.logging_setup import get_logger
from jakov.services.scheduling import recurrence_of, within_limits
from jakov.services.timezones import effective_zone
from jakov.utils.telegram import show
from jakov.utils.time import format_local

log = get_logger(__name__)
router = Router(name="schedules")
router.message.filter(F.chat.type == ChatType.PRIVATE)
STATUS_TEXT = {"sent": "✅ sent", "skipped": "⏭ skipped", "expired": "⌛ expired",
               "failed": "❌ failed", "uncertain": "❔ uncertain", "in_flight": "📤 sending",
               "awaiting_approval": "🛂 waiting for approval"}


async def _list(target: Message | CallbackQuery, ctx: AppContext, session: AsyncSession,
                user_id: int, prefix: str = "") -> None:
    schedules = await ScheduleRepo(session, ctx.owner_id).all()
    chats = {c.id: c for c in await ChatRepo(session, ctx.owner_id).list()}
    zone_name, _ = await zone_for(session, ctx, user_id)
    zone = effective_zone(zone_name, ctx.settings.timezone)
    items = []
    for sch in schedules:
        chat = chats.get(sch.chat_id)
        when = (format_local(sch.next_run_at, zone) if sch.next_run_at
                else sch.status)
        items.append((sch, list_label(sch, chat.name if chat else "removed chat", when)))
    active = sum(1 for s in schedules if s.status == "active")
    text = (f"{prefix}🗓 <b>Schedules</b>: {active} active of {len(schedules)}\n"
            "🟢 active · ⏸ paused · 🏁 finished")
    if not schedules:
        text = (f"{prefix}🗓 <b>Schedules</b>\n\nNothing scheduled yet. Write a post with "
                "✍️ New post and tap ⏰ Schedule.")
    await show(target, text, schedules_list_kb(items))


@router.message(Command("schedules"))
async def cmd_schedules(message: Message, ctx: AppContext, session: AsyncSession,
                        state: FSMContext) -> None:
    assert message.from_user is not None
    await state.clear()
    await _list(message, ctx, session, message.from_user.id)


@router.callback_query(MenuCb.filter(F.to == "schedules"))
@router.callback_query(SchCb.filter(F.action == "list"))
async def cb_list(callback: CallbackQuery, ctx: AppContext, session: AsyncSession,
                  state: FSMContext) -> None:
    await state.clear()
    await _list(callback, ctx, session, callback.from_user.id)
    await callback.answer()


async def _load(callback: CallbackQuery, ctx: AppContext, session: AsyncSession,
                pk: int) -> Schedule | None:
    sch = await ScheduleRepo(session, ctx.owner_id).get(pk)
    if sch is None:
        await callback.answer("That schedule no longer exists.", show_alert=True)
    return sch


@router.callback_query(SchCb.filter(F.action == "open"))
async def cb_open(callback: CallbackQuery, callback_data: SchCb, ctx: AppContext,
                  session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    sch = await _load(callback, ctx, session, callback_data.pk)
    if sch:
        await render_schedule(callback, sch, ctx, session, callback.from_user.id)
        await callback.answer()


@router.callback_query(SchCb.filter(F.action.in_({"pause", "resume"})))
async def cb_pause_resume(callback: CallbackQuery, callback_data: SchCb, ctx: AppContext,
                          session: AsyncSession) -> None:
    sch = await _load(callback, ctx, session, callback_data.pk)
    if sch is None:
        return
    if callback_data.action == "pause":
        sch.status, sch.paused_reason = "paused", "Paused by you."
        note = "Paused ⏸"
    else:
        chat = await ChatRepo(session, ctx.owner_id).get(sch.chat_id)
        if chat is None or not chat.is_active or not chat.can_post:
            await callback.answer("I still can't post in that chat. Fix my rights in "
                                  "📡 Channels → 🔄 Re-check rights first.", show_alert=True)
            return
        now = utcnow()
        rec = recurrence_of(sch)
        # Resume from now on: runs missed while paused are not sent.
        nxt = rec.first_run(now) if sch.kind == "once" else rec.next_after(now)
        pending = await ScheduleRepo(session, ctx.owner_id).pending_runs(sch.id)
        sch.next_run_at = within_limits(sch, nxt, pending)
        if sch.next_run_at is None:
            await callback.answer("Nothing left to run: this schedule is complete or its time "
                                  "has passed. Edit the timing instead.", show_alert=True)
            return
        sch.status, sch.paused_reason, sch.last_error = "active", None, None
        note = "Resumed ▶️"
    await session.commit()
    log.info("schedule_status", schedule_id=sch.id, status=sch.status)
    await render_schedule(callback, sch, ctx, session, callback.from_user.id)
    await callback.answer(note)


@router.callback_query(SchCb.filter(F.action == "sendnow"))
async def cb_send_now(callback: CallbackQuery, callback_data: SchCb, ctx: AppContext,
                      session: AsyncSession) -> None:
    sch = await _load(callback, ctx, session, callback_data.pk)
    if sch is None or ctx.scheduler is None:
        return
    await callback.answer("Sending…")
    await session.commit()
    ok, reason = await ctx.scheduler.send_now(sch.id)
    await session.refresh(sch)
    prefix = "✅ Sent now.\n\n" if ok else f"⚠️ Not sent: {html.escape(reason)}\n\n"
    await render_schedule(callback, sch, ctx, session, callback.from_user.id, prefix)


@router.callback_query(SchCb.filter(F.action == "edit"))
async def cb_edit(callback: CallbackQuery, callback_data: SchCb, ctx: AppContext,
                  session: AsyncSession, state: FSMContext) -> None:
    sch = await _load(callback, ctx, session, callback_data.pk)
    if sch is None:
        return
    zone, _ = await zone_for(session, ctx, callback.from_user.id)
    await start_retime(callback, sch, state, zone)
    await callback.answer()


@router.callback_query(SchCb.filter(F.action == "history"))
async def cb_history(callback: CallbackQuery, callback_data: SchCb, ctx: AppContext,
                     session: AsyncSession) -> None:
    sch = await _load(callback, ctx, session, callback_data.pk)
    if sch is None:
        return
    zone_name, _ = await zone_for(session, ctx, callback.from_user.id)
    zone = effective_zone(zone_name, ctx.settings.timezone)
    rows = await ScheduleRepo(session, ctx.owner_id).history(sch.id)
    lines = ["📜 <b>Last runs</b>"]
    for row in rows:
        when = format_local(row.scheduled_for, zone)
        line = f"{STATUS_TEXT.get(row.status, row.status)} · {when}"
        if row.reason and row.status != "sent":
            line += f"\n   <i>{html.escape(row.reason[:160])}</i>"
        lines.append(line)
    if not rows:
        lines.append("No runs yet.")
    await show(callback, "\n".join(lines), back_to_schedule_kb(sch.id))
    await callback.answer()


@router.callback_query(SchCb.filter(F.action == "delete"))
async def cb_delete(callback: CallbackQuery, callback_data: SchCb, ctx: AppContext,
                    session: AsyncSession) -> None:
    sch = await _load(callback, ctx, session, callback_data.pk)
    if sch:
        await show(callback, "🗑 Delete this schedule? Posts already published stay in the chat.",
                   confirm_delete_kb(sch))
        await callback.answer()


@router.callback_query(SchCb.filter(F.action == "delete_go"))
async def cb_delete_go(callback: CallbackQuery, callback_data: SchCb, ctx: AppContext,
                       session: AsyncSession) -> None:
    repo = ScheduleRepo(session, ctx.owner_id)
    sch = await _load(callback, ctx, session, callback_data.pk)
    if sch is None:
        return
    await repo.delete(sch)
    await session.commit()
    log.info("schedule_deleted", schedule_id=callback_data.pk)
    await _list(callback, ctx, session, callback.from_user.id, "🗑 Schedule deleted.\n\n")
    await callback.answer()
