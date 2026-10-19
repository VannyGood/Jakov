"""Wire everything together and run in polling or webhook mode."""

from __future__ import annotations

import asyncio
import contextlib
from time import monotonic

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from jakov.config import Settings
from jakov.context import AppContext
from jakov.db.fsm_storage import SQLAlchemyStorage
from jakov.db.session import create_engine, create_session_factory
from jakov.handlers import all_routers
from jakov.logging_setup import get_logger
from jakov.middlewares.admin_only import AdminOnlyMiddleware
from jakov.middlewares.db_session import DbSessionMiddleware, UpdateCounterMiddleware
from jakov.services.emoji_capability import EmojiProbe

log = get_logger(__name__)

ADMIN_COMMANDS = [
    BotCommand(command="start", description="Main menu"),
    BotCommand(command="channels", description="Linked channels and groups"),
    BotCommand(command="settings", description="Timezone and checks"),
]


def build_dispatcher(ctx: AppContext) -> Dispatcher:
    dp = Dispatcher(
        storage=SQLAlchemyStorage(ctx.sessions, ctx.owner_id),
        ctx=ctx,
    )
    admin_only = AdminOnlyMiddleware(ctx.admin_ids)
    dp.message.outer_middleware(admin_only)
    dp.callback_query.outer_middleware(admin_only)
    dp.update.outer_middleware(UpdateCounterMiddleware(ctx))
    dp.update.middleware(DbSessionMiddleware(ctx.sessions))
    dp.include_routers(*all_routers())
    return dp


async def _set_commands(bot: Bot, admin_ids: list[int]) -> None:
    # Non-admins see no command list at all.
    await bot.delete_my_commands(scope=BotCommandScopeDefault())
    for admin_id in admin_ids:
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
        except TelegramAPIError as exc:
            log.warning("set_commands_failed", admin_id=admin_id, error=type(exc).__name__)


async def _health_loop(ctx: AppContext, interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        log.info("health", uptime_s=int(monotonic() - ctx.started_at),
                 updates=ctx.updates_handled)


async def run(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    ctx = AppContext(
        settings=settings,
        sessions=create_session_factory(engine),
        emoji_probe=EmojiProbe(settings.emoji_test_pack),
    )
    bot = Bot(
        settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    dp = build_dispatcher(ctx)

    me = await bot.get_me()
    log.info("starting", bot=me.username, mode=settings.run_mode, admins=len(settings.admin_ids))
    await _set_commands(bot, settings.admin_ids)
    health = asyncio.create_task(_health_loop(ctx, settings.health_log_interval_s))
    try:
        if settings.run_mode == "webhook":
            await _run_webhook(bot, dp, settings)
        else:
            await bot.delete_webhook(drop_pending_updates=False)
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        health.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await health
        await bot.session.close()
        await engine.dispose()
        log.info("stopped")


async def _run_webhook(bot: Bot, dp: Dispatcher, settings: Settings) -> None:
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
    from aiohttp import web

    assert settings.webhook_base_url is not None
    secret = settings.webhook_secret.get_secret_value() if settings.webhook_secret else None
    await bot.set_webhook(
        settings.webhook_base_url.rstrip("/") + settings.webhook_path,
        secret_token=secret,
        allowed_updates=dp.resolve_used_update_types(),
    )
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret).register(
        app, path=settings.webhook_path
    )
    setup_application(app, dp, bot=bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.webhook_host, settings.webhook_port)
    await site.start()
    log.info("webhook_listening", host=settings.webhook_host, port=settings.webhook_port)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    import signal

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        await runner.cleanup()
