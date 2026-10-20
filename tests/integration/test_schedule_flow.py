"""⏰ Schedule wizard and /schedules through the real dispatcher."""

import random

from aiogram import Bot, Dispatcher
from sqlalchemy import select

from jakov.context import AppContext
from jakov.db.models import Chat, ChatKind, Post, Schedule
from jakov.db.repositories.posts import PostRepo
from jakov.engine.text_generator import TemplateGenerator
from jakov.keyboards.callbacks import SchCb
from jakov.services.drafts import generate_variations
from jakov.services.scheduler import Scheduler
from tests.conftest import ADMIN, OWNER, FakeSession
from tests.integration.conftest import button_update, sent_texts, text_update


async def ready_post(ctx: AppContext) -> tuple[int, int]:
    async with ctx.sessions() as s:
        chat = Chat(owner_id=OWNER, tg_chat_id=-1003, kind=ChatKind.CHANNEL, title="Daily",
                    can_post=True, is_active=True, bot_status="administrator", settings={})
        s.add(chat)
        post = await PostRepo(s, OWNER).add(Post(
            created_by=ADMIN, post_type="custom", tone="chill",
            answers={"topic": "Morning tip", "message": "Drink water."}, moments={},
            buttons=[], timezone="Europe/Belgrade"))
        await generate_variations(s, OWNER, post, TemplateGenerator(ctx.catalog, random.Random(2)),
                                  ctx.catalog, ctx.library)
        post.status, post.chosen_index = "ready", 0
        await s.commit()
        return post.id, chat.id


async def schedule(ctx: AppContext) -> Schedule | None:
    async with ctx.sessions() as s:
        return await s.scalar(select(Schedule))


async def test_daily_schedule_wizard_and_management(dp: Dispatcher, bot: Bot,
                                                    fake_session: FakeSession,
                                                    ctx: AppContext) -> None:
    ctx.scheduler = Scheduler(bot, ctx)
    post_id, _ = await ready_post(ctx)
    feed = dp.feed_update
    await feed(bot, button_update(SchCb(action="new", pk=post_id).pack()))
    # One channel only: the chat picker is skipped.
    assert "When should it go out" in sent_texts(fake_session)[-1]
    await feed(bot, button_update(SchCb(action="kind", pk=post_id, value=1).pack()))  # daily
    await feed(bot, button_update(SchCb(action="daily_type", pk=post_id).pack()))
    await feed(bot, text_update("25:99"))
    assert "Use a time like" in sent_texts(fake_session)[-1]
    await feed(bot, text_update("7:45"))
    summary = sent_texts(fake_session)[-1]
    assert "Check and confirm" in summary and "Every day at 07:45" in summary
    assert summary.count("   • ") == 3

    # Tap-to-change options on the summary card.
    await feed(bot, button_update(SchCb(action="ends", pk=post_id).pack()))
    await feed(bot, button_update(SchCb(action="end_type", pk=post_id, value=1).pack()))
    await feed(bot, text_update("five"))
    assert "Send a number" in sent_texts(fake_session)[-1]
    await feed(bot, text_update("5"))
    assert "5 times" in sent_texts(fake_session)[-1]
    await feed(bot, button_update(SchCb(action="opt_approval", pk=post_id).pack()))
    markup = str(fake_session.called("EditMessageText")[-1].reply_markup)
    assert "Approval: on" in markup and "after 5 posts" in markup
    await feed(bot, button_update(SchCb(action="confirm", pk=post_id).pack()))
    assert "Scheduled!" in sent_texts(fake_session)[-1]

    sch = await schedule(ctx)
    assert sch is not None and sch.time_of_day == "07:45" and sch.require_approval
    assert sch.limit_count == 5 and sch.timezone == "UTC" and sch.next_run_at is not None

    await feed(bot, button_update(SchCb(action="list").pack()))
    assert "1 active" in sent_texts(fake_session)[-1]
    await feed(bot, button_update(SchCb(action="pause", pk=sch.id).pack()))
    assert "Paused" in sent_texts(fake_session)[-1]
    await feed(bot, button_update(SchCb(action="resume", pk=sch.id).pack()))
    assert "Active" in sent_texts(fake_session)[-1]
    await feed(bot, button_update(SchCb(action="edit", pk=sch.id).pack()))
    assert "Check and confirm" in sent_texts(fake_session)[-1]  # edit opens the summary
    await feed(bot, button_update(SchCb(action="end_count", pk=post_id, value=10).pack()))
    await feed(bot, button_update(SchCb(action="confirm", pk=post_id).pack()))
    assert "Schedule updated" in sent_texts(fake_session)[-1]
    sch = await schedule(ctx)
    assert sch is not None and sch.limit_count == 10
    await feed(bot, button_update(SchCb(action="history", pk=sch.id).pack()))
    assert "No runs yet" in sent_texts(fake_session)[-1]
    await feed(bot, button_update(SchCb(action="delete_go", pk=sch.id).pack()))
    assert "Schedule deleted" in sent_texts(fake_session)[-1]
    assert await schedule(ctx) is None


async def test_quick_once_and_interval(dp: Dispatcher, bot: Bot, fake_session: FakeSession,
                                       ctx: AppContext) -> None:
    post_id, _ = await ready_post(ctx)
    feed = dp.feed_update
    await feed(bot, button_update(SchCb(action="new", pk=post_id).pack()))
    await feed(bot, button_update(SchCb(action="kind", pk=post_id, value=2).pack()))
    await feed(bot, button_update(SchCb(action="every_type", pk=post_id).pack()))
    await feed(bot, text_update("2m"))  # below the 5 minute minimum
    assert "between 5 minutes" in sent_texts(fake_session)[-1]
    await feed(bot, text_update("2h30m"))
    summary = sent_texts(fake_session)[-1]
    assert "Every 2 h 30 min" in summary
    await feed(bot, button_update(SchCb(action="first", pk=post_id).pack()))
    assert "after one interval" in str(fake_session.called("EditMessageText")[-1].reply_markup)
    await feed(bot, button_update(SchCb(action="confirm", pk=post_id).pack()))
    sch = await schedule(ctx)
    assert sch is not None and sch.interval_minutes == 150 and sch.limit_kind == "forever"

    # Change time to a one-off via the shortcut.
    await feed(bot, button_update(SchCb(action="edit", pk=sch.id).pack()))
    await feed(bot, button_update(SchCb(action="when", pk=post_id).pack()))
    await feed(bot, button_update(SchCb(action="once", pk=post_id, value=1).pack()))
    assert "Once" in sent_texts(fake_session)[-1]
    await feed(bot, button_update(SchCb(action="confirm", pk=post_id).pack()))
    sch = await schedule(ctx)
    assert sch is not None and sch.kind == "once" and sch.run_at is not None


async def test_schedule_needs_a_chosen_variation(dp: Dispatcher, bot: Bot,
                                                 fake_session: FakeSession,
                                                 ctx: AppContext) -> None:
    post_id, _ = await ready_post(ctx)
    async with ctx.sessions() as s:
        post = await s.get(Post, post_id)
        assert post is not None
        post.status = "draft"
        await s.commit()
    await dp.feed_update(bot, button_update(SchCb(action="new", pk=post_id).pack()))
    assert fake_session.called("AnswerCallbackQuery")[-1].show_alert
