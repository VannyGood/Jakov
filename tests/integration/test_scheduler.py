"""Scheduler end-to-end with a real database and a fake Telegram."""

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import select

from jakov.context import AppContext
from jakov.db.models import ApprovalRequest, Chat, ChatKind, Post, Schedule, SendLog
from jakov.db.repositories.posts import PostRepo
from jakov.engine.text_generator import TemplateGenerator
from jakov.services import scheduler as scheduler_module
from jakov.services.drafts import generate_variations
from jakov.services.scheduler import Scheduler
from jakov.services.scheduling import ScheduleSpec, apply_spec
from tests.conftest import ADMIN, OWNER, FakeSession

T0 = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)


@pytest.fixture
def frozen(monkeypatch: pytest.MonkeyPatch) -> list[datetime]:
    """Controls utcnow() inside the scheduler module."""
    now = [T0]
    monkeypatch.setattr(scheduler_module, "utcnow", lambda: now[0])
    return now


async def setup(ctx: AppContext, *, rotate: bool = False, **spec_kw: Any) -> tuple[int, int]:
    async with ctx.sessions() as s:
        chat = Chat(owner_id=OWNER, tg_chat_id=-1007, kind=ChatKind.CHANNEL, title="News",
                    can_post=True, can_edit=True, is_active=True, bot_status="administrator",
                    settings={})
        s.add(chat)
        post = await PostRepo(s, OWNER).add(Post(
            created_by=ADMIN, post_type="announcement", tone="serious",
            answers={"topic": "Server maintenance"}, moments={}, buttons=[], timezone="UTC"))
        await generate_variations(s, OWNER, post, TemplateGenerator(ctx.catalog, random.Random(5)),
                                  ctx.catalog, ctx.library)
        post.status, post.chosen_index = "ready", 0
        await s.flush()
        defaults: dict[str, Any] = dict(kind="interval", interval_minutes=60,
                                        anchor_at=T0.isoformat(), timezone="UTC")
        defaults.update(spec_kw)
        spec = ScheduleSpec(chat_pk=chat.id, rotate=rotate, **defaults)
        sch = Schedule(owner_id=OWNER, post_id=post.id, created_by=ADMIN, chat_id=chat.id,
                       timezone="UTC", kind=spec.kind, sent_count=0, skipped_count=0,
                       last_variation_index=-1)
        apply_spec(sch, spec, T0 - timedelta(minutes=1))
        s.add(sch)
        await s.commit()
        return sch.id, chat.id


async def get_schedule(ctx: AppContext, pk: int) -> Schedule:
    async with ctx.sessions() as s:
        sch = await s.get(Schedule, pk)
        assert sch is not None
        return sch


async def logs(ctx: AppContext) -> list[SendLog]:
    async with ctx.sessions() as s:
        return list(await s.scalars(select(SendLog).order_by(SendLog.id)))


def channel_posts(fake: FakeSession) -> list[Any]:
    return [c for c in fake.called("SendMessage") if c.chat_id == -1007]


async def test_runs_on_time_and_moves_on(ctx: AppContext, bot: Bot, fake_session: FakeSession,
                                         frozen: list[datetime]) -> None:
    sch_id, _ = await setup(ctx)
    sched = Scheduler(bot, ctx)
    assert await sched.tick(T0 - timedelta(seconds=1)) == 0
    await sched.tick(T0)
    assert len(channel_posts(fake_session)) == 1
    sch = await get_schedule(ctx, sch_id)
    assert sch.sent_count == 1 and sch.next_run_at == T0 + timedelta(hours=1)
    assert [r.status for r in await logs(ctx)] == ["sent"]
    await sched.tick(T0 + timedelta(minutes=30))  # nothing due
    assert len(channel_posts(fake_session)) == 1


async def test_reserved_run_is_never_sent_twice(ctx: AppContext, bot: Bot,
                                                fake_session: FakeSession,
                                                frozen: list[datetime]) -> None:
    sch_id, _ = await setup(ctx)
    async with ctx.sessions() as s:  # a previous process already reserved this run
        s.add(SendLog(owner_id=OWNER, schedule_id=sch_id, tg_chat_id=-1007, scheduled_for=T0,
                      status="sent"))
        await s.commit()
    await Scheduler(bot, ctx).tick(T0)
    assert channel_posts(fake_session) == []


async def test_outage_skips_old_runs_and_sends_latest(ctx: AppContext, bot: Bot,
                                                      fake_session: FakeSession,
                                                      frozen: list[datetime]) -> None:
    sch_id, _ = await setup(ctx)
    now = T0 + timedelta(hours=3, minutes=5)
    frozen[0] = now
    await Scheduler(bot, ctx).tick(now)
    assert len(channel_posts(fake_session)) == 1
    rows = await logs(ctx)
    assert [r.status for r in rows] == ["skipped", "sent"]
    assert "Missed 3 run(s)" in (rows[0].reason or "")
    assert rows[1].scheduled_for == T0 + timedelta(hours=3)
    sch = await get_schedule(ctx, sch_id)
    assert sch.skipped_count == 3 and sch.next_run_at == T0 + timedelta(hours=4)


async def test_count_limit_finishes(ctx: AppContext, bot: Bot, fake_session: FakeSession,
                                    frozen: list[datetime]) -> None:
    sch_id, _ = await setup(ctx, limit_kind="count", limit_count=2)
    sched = Scheduler(bot, ctx)
    for hour in range(4):
        frozen[0] = T0 + timedelta(hours=hour)
        await sched.tick(frozen[0])
    assert len(channel_posts(fake_session)) == 2
    sch = await get_schedule(ctx, sch_id)
    assert sch.status == "finished" and sch.next_run_at is None
    assert any("complete" in (c.text or "") for c in fake_session.called("SendMessage")
               if c.chat_id == ADMIN)


async def test_until_limit(ctx: AppContext, bot: Bot, fake_session: FakeSession,
                           frozen: list[datetime]) -> None:
    sch_id, _ = await setup(ctx, limit_kind="until",
                            until_at=(T0 + timedelta(hours=1, minutes=30)).isoformat())
    sched = Scheduler(bot, ctx)
    for hour in range(3):
        frozen[0] = T0 + timedelta(hours=hour)
        await sched.tick(frozen[0])
    assert len(channel_posts(fake_session)) == 2
    assert (await get_schedule(ctx, sch_id)).status == "finished"


async def test_lost_rights_pause_and_notify(ctx: AppContext, bot: Bot, fake_session: FakeSession,
                                            frozen: list[datetime]) -> None:
    sch_id, _ = await setup(ctx)
    fake_session.on("SendMessage", lambda m: TelegramForbiddenError(m, "bot was kicked")
                    if m.chat_id == -1007 else _ok(m))
    await Scheduler(bot, ctx).tick(T0)
    sch = await get_schedule(ctx, sch_id)
    assert sch.status == "paused" and "not allowed" in (sch.paused_reason or "")
    alert = [c for c in fake_session.called("SendMessage") if c.chat_id == ADMIN][-1]
    assert "paused" in alert.text and "Resume" in str(alert.reply_markup)
    assert [r.status for r in await logs(ctx)] == ["failed"]


def _ok(m: Any) -> Any:
    from aiogram.types import Chat as TgChat
    from aiogram.types import Message

    return Message(message_id=1, date=datetime.now(UTC), chat=TgChat(id=m.chat_id, type="private"),
                   text=m.text)


async def test_restart_marks_in_flight_uncertain(ctx: AppContext, bot: Bot,
                                                 fake_session: FakeSession) -> None:
    sch_id, _ = await setup(ctx)
    async with ctx.sessions() as s:
        s.add(SendLog(owner_id=OWNER, schedule_id=sch_id, tg_chat_id=-1007, scheduled_for=T0,
                      status="in_flight"))
        await s.commit()
    assert await Scheduler(bot, ctx).recover() == 1
    assert [r.status for r in await logs(ctx)] == ["uncertain"]
    assert channel_posts(fake_session) == []  # not re-sent
    assert any("interrupted" in c.text for c in fake_session.called("SendMessage"))


async def test_rotation_cycles_variations(ctx: AppContext, bot: Bot, fake_session: FakeSession,
                                          frozen: list[datetime]) -> None:
    await setup(ctx, rotate=True)
    sched = Scheduler(bot, ctx)
    for hour in range(4):
        frozen[0] = T0 + timedelta(hours=hour)
        await sched.tick(frozen[0])
    assert [r.variation_idx for r in await logs(ctx)] == [0, 1, 2, 0]


async def test_approval_flow_approve(ctx: AppContext, bot: Bot, fake_session: FakeSession,
                                     frozen: list[datetime]) -> None:
    await setup(ctx, require_approval=True)
    sched = Scheduler(bot, ctx)
    await sched.tick(T0)
    assert channel_posts(fake_session) == []
    dms = [c for c in fake_session.called("SendMessage") if c.chat_id == ADMIN]
    assert "Approve this post" in dms[-1].text
    async with ctx.sessions() as s:
        req = await s.scalar(select(ApprovalRequest))
        assert req is not None and req.status == "pending"
    ok, _ = await sched.approve(req.id)
    assert ok and len(channel_posts(fake_session)) == 1
    assert channel_posts(fake_session)[0].text == req.html  # exactly what was approved
    assert [r.status for r in await logs(ctx)] == ["sent"]
    ok_again, msg = await sched.approve(req.id)
    assert not ok_again and "approved" in msg


async def test_approval_skip_and_expiry(ctx: AppContext, bot: Bot, fake_session: FakeSession,
                                        frozen: list[datetime]) -> None:
    sch_id, _ = await setup(ctx, require_approval=True)
    sched = Scheduler(bot, ctx)
    await sched.tick(T0)
    async with ctx.sessions() as s:
        first = await s.scalar(select(ApprovalRequest))
    assert first is not None and await sched.skip(first.id)

    frozen[0] = T0 + timedelta(hours=1)
    await sched.tick(frozen[0])
    late = frozen[0] + timedelta(minutes=ctx.settings.approval_timeout_minutes + 1)
    frozen[0] = late
    await sched.expire_approvals(late)
    async with ctx.sessions() as s:
        reqs = list(await s.scalars(select(ApprovalRequest).order_by(ApprovalRequest.id)))
    assert [r.status for r in reqs] == ["skipped", "expired"]
    assert [r.status for r in await logs(ctx)] == ["skipped", "expired"]
    assert fake_session.called("EditMessageText")  # "Expired" shown on the DM
    ok, _msg = await sched.approve(reqs[1].id)
    assert not ok
    sch = await get_schedule(ctx, sch_id)
    assert sch.skipped_count == 2 and sch.status == "active" and channel_posts(fake_session) == []


async def test_once_schedule_finishes(ctx: AppContext, bot: Bot, fake_session: FakeSession,
                                      frozen: list[datetime]) -> None:
    sch_id, _ = await setup(ctx, kind="once", run_at=T0.isoformat())
    await Scheduler(bot, ctx).tick(T0 + timedelta(minutes=2))
    sch = await get_schedule(ctx, sch_id)
    assert len(channel_posts(fake_session)) == 1 and sch.status == "finished"


async def test_send_now_counts(ctx: AppContext, bot: Bot, fake_session: FakeSession,
                               frozen: list[datetime]) -> None:
    sch_id, _ = await setup(ctx)
    ok, _ = await Scheduler(bot, ctx).send_now(sch_id)
    assert ok and (await get_schedule(ctx, sch_id)).sent_count == 1
