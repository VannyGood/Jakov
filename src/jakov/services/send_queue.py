"""The single outgoing gateway for posts: rate limits, per-chat ordering and retries.

- waits for a rate-limiter slot before every attempt
- one message at a time per chat, so a slow chat never blocks the others
- TelegramRetryAfter: waits exactly as long as Telegram asks, then retries
- network / 5xx errors: exponential backoff (1 s, 2 s, 4 s)
- Forbidden / BadRequest are not retried: the caller decides (e.g. pause the schedule)
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramServerError

from jakov.engine.rate_limiter import RateLimiter
from jakov.logging_setup import get_logger

log = get_logger(__name__)
T = TypeVar("T")


class SendQueue:
    def __init__(self, limiter: RateLimiter | None = None, *, max_retries: int = 3,
                 max_concurrency: int = 8,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.limiter = limiter or RateLimiter()
        self.max_retries = max_retries
        self._sleep = sleep
        self._locks: dict[int, asyncio.Lock] = {}
        self._concurrency = asyncio.Semaphore(max_concurrency)
        self._in_flight = 0
        self._idle = asyncio.Event()
        self._idle.set()

    def _lock(self, chat_id: int) -> asyncio.Lock:
        return self._locks.setdefault(chat_id, asyncio.Lock())

    async def run(self, chat_id: int, call: Callable[[], Awaitable[T]]) -> T:
        self._in_flight += 1
        self._idle.clear()
        try:
            async with self._lock(chat_id):
                return await self._attempts(chat_id, call)
        finally:
            self._in_flight -= 1
            if not self._in_flight:
                self._idle.set()

    async def _attempts(self, chat_id: int, call: Callable[[], Awaitable[T]]) -> T:
        for attempt in range(self.max_retries + 1):
            delay = self.limiter.reserve(chat_id)
            if delay:
                await self._sleep(delay)
            try:
                async with self._concurrency:
                    return await call()
            except TelegramRetryAfter as exc:
                if attempt == self.max_retries:
                    raise
                log.warning("send_retry_after", chat_id=chat_id, seconds=exc.retry_after)
                self.limiter.block(chat_id, exc.retry_after)
            except (TelegramNetworkError, TelegramServerError) as exc:
                if attempt == self.max_retries:
                    raise
                backoff = 2.0 ** attempt
                log.warning("send_network_retry", chat_id=chat_id, error=type(exc).__name__,
                            backoff=backoff)
                await self._sleep(backoff)
        raise AssertionError("unreachable")

    async def drain(self) -> None:
        """Wait until no send is in flight (wrap in asyncio.timeout on shutdown)."""
        await self._idle.wait()
