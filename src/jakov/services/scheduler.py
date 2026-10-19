"""The DB-driven scheduler: due runs, catch-up, approvals, sending and bookkeeping.

Duplicate-safety: before anything is sent, a run is reserved by inserting a SendLog row
(unique per schedule + scheduled time) and moving next_run_at forward, in one committed
transaction. A crash after that point leaves an "in_flight" row, which recover() marks
"uncertain" on restart and reports. It is never re-sent automatically.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.context import AppContext
from jakov.db.base import utcnow
from jakov.db.models import ApprovalRequest, Chat, Post, Schedule, SendLog
from jakov.db.repositories.chats import ChatRepo
from jakov.db.repositories.posts import PostRepo
from jakov.db.repositories.schedules import ScheduleRepo
from jakov.engine import catchup
from jakov.engine.limits import check_length
from jakov.keyboards.callbacks import ApCb, SchCb
from jakov.logging_setup import get_logger
from jakov.services.notifier import notify_admins
from jakov.services.publisher import (
    PublishError,
    Rendered,
    deliver,
    fresh_spin,
    message_link,
    pick_variation,
    render_for_chat,
    send_rendered,
)
from jakov.services.scheduling import recurrence_of, within_limits
from jakov.services.ui_emoji import raw_output
from jakov.utils.time import format_local

log = get_logger(__name__)


def open_schedule_kb(schedule_id: int, *, resume: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🗓 Open schedule",
                                  callback_data=SchCb(action="open", pk=schedule_id).pack())]]
    if resume:
        rows.insert(0, [InlineKeyboardButton(
            text="▶️ Resume", callback_data=SchCb(action="resume", pk=schedule_id).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def approval_kb(request_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Approve", callback_data=ApCb(action="approve",
                                                                  pk=request_id).pack()),
         InlineKeyboardButton(text="⏭ Skip", callback_data=ApCb(action="skip",
                                                               pk=request_id).pack())],
        [InlineKeyboardButton(text="✏️ Edit text", callback_data=ApCb(action="edit",
                                                                     pk=request_id).pack())],
    ])


class Scheduler:
    def __init__(self, bot: Bot, ctx: AppContext) -> None:
        self.bot = bot
        self.ctx = ctx
        self.settings = ctx.settings

    # --- lifecycle -----------------------------------------------------------------

    async def run(self, stop: asyncio.Event) -> None:
        await self.recover()
        log.info("scheduler_started", tick_s=self.settings.scheduler_tick_seconds)
        while not stop.is_set():
            try:
                await self.tick()
            except Exception:
                log.exception("scheduler_tick_failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), self.settings.scheduler_tick_seconds)
        log.info("scheduler_stopped")

    async def recover(self) -> int:
        """Runs interrupted mid-send by a crash: mark uncertain, never re-send."""
        async with self.ctx.sessions() as session:
            stuck = list(await session.scalars(select(SendLog).where(
                SendLog.owner_id == self.ctx.owner_id, SendLog.status == "in_flight")))
            for row in stuck:
                row.status = "uncertain"
                row.reason = ("The bot stopped while this run was being sent. It may or may "
                              "not have been posted; it was not retried to avoid a duplicate.")
            await session.commit()
        for row in stuck:
            await notify_admins(
                self.bot, self.ctx.admin_ids,
                f"⚠️ A scheduled run ({format_local(row.scheduled_for, self.settings.default_zone)})"
                " was interrupted by a restart. Check the channel: it was <b>not</b> retried, "
                "so there is no duplicate.",
                open_schedule_kb(row.schedule_id) if row.schedule_id else None)
        if stuck:
            log.warning("recovered_in_flight", count=len(stuck))
        return len(stuck)

    async def tick(self, now: datetime | None = None) -> int:
        now = now or utcnow()
        async with self.ctx.sessions() as session:
            due = await ScheduleRepo(session, self.ctx.owner_id).due(now)
        for schedule_id in due:
            try:
                await self.process(schedule_id, now)
            except Exception:
                log.exception("schedule_failed", schedule_id=schedule_id)
        await self.expire_approvals(now)
        return len(due)

    # --- one due schedule ------------------------------------------------------------

    async def process(self, schedule_id: int, now: datetime) -> None:
        grace = timedelta(minutes=self.settings.catchup_grace_minutes)
        async with self.ctx.sessions() as session:
            repo = ScheduleRepo(session, self.ctx.owner_id)
            sch = await repo.get(schedule_id)
            if sch is None or sch.status != "active" or sch.next_run_at is None \
                    or sch.next_run_at > now:
                return
            chat = await ChatRepo(session, self.ctx.owner_id).get(sch.chat_id)
            tg_chat_id = chat.tg_chat_id if chat else 0
            plan = catchup.plan(recurrence_of(sch), sch.next_run_at, now, grace)
            if plan.missed:
                assert plan.first_missed is not None and plan.last_missed is not None
                session.add(SendLog(
                    owner_id=self.ctx.owner_id, schedule_id=sch.id, post_id=sch.post_id,
                    tg_chat_id=tg_chat_id, scheduled_for=plan.first_missed, status="skipped",
                    reason=(f"Missed {plan.missed} run(s) between "
                            f"{plan.first_missed:%Y-%m-%d %H:%M} and "
                            f"{plan.last_missed:%Y-%m-%d %H:%M} UTC "
                            f"(more than {self.settings.catchup_grace_minutes} min late)")))
                sch.skipped_count += plan.missed
                log.info("runs_missed", schedule_id=sch.id, count=plan.missed)
            pending = await repo.pending_runs(sch.id)
            run_at = within_limits(sch, plan.run_now, pending)
            run_log: SendLog | None = None
            if run_at is not None:
                run_log = SendLog(
                    owner_id=self.ctx.owner_id, schedule_id=sch.id, post_id=sch.post_id,
                    tg_chat_id=tg_chat_id, scheduled_for=run_at,
                    status="awaiting_approval" if sch.require_approval else "in_flight")
                session.add(run_log)
                sch.last_run_at = now
                pending += 1
            sch.next_run_at = within_limits(sch, plan.next_run, pending)
            if sch.next_run_at is None and not pending:
                sch.status = "finished"
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                log.warning("duplicate_run_prevented", schedule_id=schedule_id)
                return
            needs_approval = sch.require_approval
        if run_log is None:
            return
        if needs_approval:
            await self.request_approval(run_log.id)
        else:
            await self.execute(run_log.id)

    # --- sending -----------------------------------------------------------------

    async def _load(self, session: AsyncSession, run: SendLog
                    ) -> tuple[Schedule | None, Post | None, Chat | None]:
        owner = self.ctx.owner_id
        sch = await ScheduleRepo(session, owner).get(run.schedule_id) if run.schedule_id else None
        post = await PostRepo(session, owner).get(run.post_id) if run.post_id else None
        chat = await ChatRepo(session, owner).get(sch.chat_id) if sch else None
        return sch, post, chat

    async def _render(self, session: AsyncSession, sch: Schedule, post: Post, chat: Chat
                      ) -> tuple[Rendered, int]:
        variation = fresh_spin(pick_variation(post, rotate=sch.rotate,
                                              last_index=sch.last_variation_index))
        rendered = await render_for_chat(session, self.ctx.owner_id, post, chat, variation,
                                         self.ctx.catalog, self.ctx.library)
        return rendered, variation.idx

    async def execute(self, log_id: int, rendered: Rendered | None = None,
                      variation_idx: int | None = None) -> bool:
        """Send one reserved run. Returns True when it was posted."""
        async with self.ctx.sessions() as session:
            run = await session.get(SendLog, log_id)
            if run is None or run.status != "in_flight":
                return False
            sch, post, chat = await self._load(session, run)
            if sch is None or post is None or chat is None:
                run.status, run.reason = "failed", "The schedule, post or chat no longer exists."
                await session.commit()
                return False
            try:
                if rendered is None:
                    rendered, variation_idx = await self._render(session, sch, post, chat)
                # Release the DB write lock before the network call (pool rotation is saved).
                await session.commit()
                record, notes = await deliver(self.bot, session, self.ctx.owner_id, post, chat,
                                              rendered, variation_idx, self.ctx.queue)
            except PublishError as exc:
                await self._failed(session, sch, run, chat, exc)
                return False
            run.status, run.reason = "sent", None
            run.message_id, run.published_post_id = record.message_id, record.id
            run.variation_idx = variation_idx
            sch.sent_count += 1
            sch.last_error = None
            if variation_idx is not None:
                sch.last_variation_index = variation_idx
            finished = await self._settle(session, sch, utcnow())
            await session.commit()
            link = message_link(chat, record.tg_chat_id, record.message_id)
            schedule_id, chat_name = sch.id, chat.name
        log.info("scheduled_post_sent", schedule_id=schedule_id, message_id=record.message_id)
        for note in notes:
            await notify_admins(self.bot, self.ctx.admin_ids, f"ℹ️ {html.escape(note)}")
        if finished:
            await notify_admins(
                self.bot, self.ctx.admin_ids,
                f"🏁 Schedule for <b>{html.escape(chat_name)}</b> is complete. "
                f'<a href="{link}">Last post</a>.', open_schedule_kb(schedule_id))
        return True

    async def _failed(self, session: AsyncSession, sch: Schedule, run: SendLog, chat: Chat,
                      exc: PublishError) -> None:
        run.status, run.reason = "failed", str(exc)
        sch.last_error = str(exc)
        if exc.lost_access:
            sch.status = "paused"
            sch.paused_reason = str(exc)
        else:
            await self._settle(session, sch, utcnow())
        await session.commit()
        log.warning("scheduled_post_failed", schedule_id=sch.id, error=str(exc),
                    paused=exc.lost_access)
        prefix = "⏸ Schedule paused" if exc.lost_access else "⚠️ A scheduled post failed"
        await notify_admins(
            self.bot, self.ctx.admin_ids,
            f"{prefix} for <b>{html.escape(chat.name)}</b>.\n{html.escape(str(exc))}",
            open_schedule_kb(sch.id, resume=exc.lost_access))

    async def _settle(self, session: AsyncSession, sch: Schedule, now: datetime) -> bool:
        """After a run ends (sent, skipped, expired, failed): fix next_run / finish.

        Returns True when the schedule just finished.
        """
        if sch.status != "active":
            return False
        pending = await ScheduleRepo(session, self.ctx.owner_id).pending_runs(sch.id)
        if sch.next_run_at is not None:
            sch.next_run_at = within_limits(sch, sch.next_run_at, pending)
        elif sch.kind != "once":
            # A run that didn't count (skipped/expired) may free up room under a count limit.
            sch.next_run_at = within_limits(sch, recurrence_of(sch).next_after(now), pending)
        if sch.next_run_at is None and not pending:
            sch.status = "finished"
            return True
        return False

    async def send_now(self, schedule_id: int) -> tuple[bool, str]:
        """Manual 'Send now' from /schedules. Counts as a run."""
        async with self.ctx.sessions() as session:
            sch = await ScheduleRepo(session, self.ctx.owner_id).get(schedule_id)
            if sch is None:
                return False, "Schedule not found."
            chat = await ChatRepo(session, self.ctx.owner_id).get(sch.chat_id)
            run = SendLog(owner_id=self.ctx.owner_id, schedule_id=sch.id, post_id=sch.post_id,
                          tg_chat_id=chat.tg_chat_id if chat else 0, scheduled_for=utcnow(),
                          status="in_flight", reason="sent manually")
            session.add(run)
            await session.commit()
            run_id = run.id
        ok = await self.execute(run_id)
        async with self.ctx.sessions() as session:
            row = await session.get(SendLog, run_id)
            return ok, (row.reason or "") if row else ""

    # --- approvals ---------------------------------------------------------------

    async def request_approval(self, log_id: int) -> None:
        timeout = timedelta(minutes=self.settings.approval_timeout_minutes)
        async with self.ctx.sessions() as session:
            run = await session.get(SendLog, log_id)
            if run is None or run.status != "awaiting_approval":
                return
            sch, post, chat = await self._load(session, run)
            if sch is None or post is None or chat is None:
                run.status, run.reason = "failed", "The schedule, post or chat no longer exists."
                await session.commit()
                return
            try:
                rendered, variation_idx = await self._render(session, sch, post, chat)
            except PublishError as exc:
                run.status = "in_flight"
                await self._failed(session, sch, run, chat, exc)
                return
            request = ApprovalRequest(
                owner_id=self.ctx.owner_id, schedule_id=sch.id, send_log_id=run.id,
                admin_id=sch.created_by, expires_at=utcnow() + timeout, html=rendered.html,
                variation_idx=variation_idx)
            session.add(request)
            await session.commit()
            await self._send_approval_messages(session, request, post, chat, sch)

    async def _send_approval_messages(self, session: AsyncSession, request: ApprovalRequest,
                                      post: Post, chat: Chat, sch: Schedule) -> None:
        zone_text = format_local(request.expires_at, recurrence_of(sch).zone)
        try:
            preview = await send_rendered(
                self.bot, self.ctx.queue, request.admin_id, request.html,
                media_kind=post.media_kind, media_file_id=post.media_file_id,
                buttons=post.buttons, link_preview=post.link_preview)
            control = await self.bot.send_message(
                request.admin_id,
                f"🛂 <b>Approve this post?</b>\nFor <b>{html.escape(chat.name)}</b>, "
                f"scheduled run. If you don't answer by {zone_text}, it is skipped.",
                reply_markup=approval_kb(request.id))
        except TelegramAPIError as exc:
            log.warning("approval_dm_failed", request_id=request.id, error=str(exc))
            return
        request.preview_message_id = preview.message_id
        request.control_message_id = control.message_id
        await session.commit()

    async def approve(self, request_id: int) -> tuple[bool, str]:
        async with self.ctx.sessions() as session:
            req = await session.get(ApprovalRequest, request_id)
            if req is None or req.owner_id != self.ctx.owner_id:
                return False, "Not found."
            if req.status != "pending":
                return False, f"Already {req.status}."
            if req.expires_at <= utcnow():
                return False, "This request expired; the run was skipped."
            run = await session.get(SendLog, req.send_log_id)
            sch, post, _ = await self._load(session, run) if run else (None, None, None)
            if run is None or sch is None or post is None:
                req.status = "skipped"
                await session.commit()
                return False, "The schedule or post no longer exists."
            if sch.limit_kind == "count" and sch.limit_count is not None \
                    and sch.sent_count >= sch.limit_count:
                req.status, run.status, run.reason = "skipped", "skipped", "limit already reached"
                await self._settle(session, sch, utcnow())
                await session.commit()
                return False, "The schedule already reached its limit."
            req.status, run.status = "approved", "in_flight"
            html_text, variation_idx, log_id = req.html, req.variation_idx, run.id
            await session.commit()
        ok = await self.execute(log_id, Rendered(html_text, "<tg-emoji" in html_text),
                                variation_idx)
        return ok, "Posted ✅" if ok else "Sending failed; see the message above."

    async def skip(self, request_id: int, reason: str = "skipped by admin",
                   status: str = "skipped") -> bool:
        async with self.ctx.sessions() as session:
            req = await session.get(ApprovalRequest, request_id)
            if req is None or req.status != "pending":
                return False
            req.status = status
            run = await session.get(SendLog, req.send_log_id)
            if run is not None:
                run.status, run.reason = ("expired" if status == "expired" else "skipped"), reason
                sch, _, _ = await self._load(session, run)
                if sch is not None:
                    sch.skipped_count += 1
                    await self._settle(session, sch, utcnow())
            await session.commit()
            return True

    async def update_approval_text(self, request_id: int, new_html: str) -> str | None:
        """Admin edited the text. Returns an error message, or None when updated."""
        async with self.ctx.sessions() as session:
            req = await session.get(ApprovalRequest, request_id)
            if req is None or req.status != "pending":
                return "This request is no longer pending."
            run = await session.get(SendLog, req.send_log_id)
            sch, post, chat = await self._load(session, run) if run else (None, None, None)
            if sch is None or post is None or chat is None:
                return "The schedule or post no longer exists."
            length = check_length(new_html, post.has_media)
            if not length.ok:
                return f"That text is {length.length} characters; the limit is {length.limit}."
            req.html = new_html
            await session.commit()
            await self._send_approval_messages(session, req, post, chat, sch)
            return None

    async def expire_approvals(self, now: datetime) -> int:
        async with self.ctx.sessions() as session:
            expired = list(await session.scalars(select(ApprovalRequest).where(
                ApprovalRequest.owner_id == self.ctx.owner_id,
                ApprovalRequest.status == "pending", ApprovalRequest.expires_at <= now)))
        for req in expired:
            minutes = self.settings.approval_timeout_minutes
            await self.skip(req.id, f"no approval within {minutes} min", status="expired")
            log.info("approval_expired", request_id=req.id)
            if req.control_message_id:
                with contextlib.suppress(TelegramAPIError), raw_output():
                    await self.bot.edit_message_text(
                        "⌛ <b>Expired.</b> No answer in time, so this run was skipped.",
                        chat_id=req.admin_id, message_id=req.control_message_id)
        return len(expired)

    # --- chat access changes -------------------------------------------------------

    async def pause_for_chat(self, session: AsyncSession, chat_pk: int, reason: str) -> int:
        result = await session.execute(
            update(Schedule).where(Schedule.owner_id == self.ctx.owner_id,
                                   Schedule.chat_id == chat_pk, Schedule.status == "active")
            .values(status="paused", paused_reason=reason))
        return int(getattr(result, "rowcount", 0) or 0)
