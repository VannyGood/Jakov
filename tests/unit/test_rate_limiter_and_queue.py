import asyncio
from typing import Any

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import SendMessage

from jakov.engine.rate_limiter import RateLimiter
from jakov.services.send_queue import SendQueue


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_private_chat_one_per_second() -> None:
    clock = Clock()
    rl = RateLimiter(clock=clock)
    assert [rl.reserve(5) for _ in range(3)] == [0.0, 1.0, 2.0]


def test_groups_and_channels_twenty_per_minute() -> None:
    clock = Clock()
    rl = RateLimiter(clock=clock)
    delays = [rl.reserve(-100) for _ in range(21)]
    assert delays[1] == pytest.approx(3.0)
    assert delays[20] >= 60.0  # the 21st message falls outside the first minute


def test_global_thirty_per_second_across_chats() -> None:
    clock = Clock()
    rl = RateLimiter(clock=clock)
    delays = [rl.reserve(chat) for chat in range(1, 61)]
    assert delays[0] == 0.0
    assert delays[29] < 1.0 <= delays[30] + 1e-9 or delays[30] >= 29 / 30
    assert max(delays) == pytest.approx(59 / 30)


def test_waiting_chat_doesnt_block_others() -> None:
    clock = Clock()
    rl = RateLimiter(clock=clock)
    rl.reserve(1)
    assert rl.reserve(1) == pytest.approx(1.0)
    assert rl.reserve(2) < 0.1


def test_block_after_retry_after() -> None:
    clock = Clock()
    rl = RateLimiter(clock=clock)
    rl.block(7, 12)
    assert rl.reserve(7) == pytest.approx(12.0)


def test_time_passing_frees_slots() -> None:
    clock = Clock()
    rl = RateLimiter(clock=clock)
    rl.reserve(3)
    clock.now += 5
    assert rl.reserve(3) == 0.0


class Sleeps:
    """Fake sleep that moves the fake clock forward, like real time would."""

    def __init__(self, clock: Clock | None = None) -> None:
        self.calls: list[float] = []
        self.clock = clock

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        if self.clock is not None:
            self.clock.now += seconds


def method() -> Any:
    return SendMessage(chat_id=1, text="x")


async def test_queue_honours_retry_after_then_succeeds() -> None:
    sleeps = Sleeps()
    q = SendQueue(RateLimiter(clock=Clock()), sleep=sleeps)
    attempts = 0

    async def call() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TelegramRetryAfter(method(), "Flood control", retry_after=7)
        return "ok"

    assert await q.run(1, call) == "ok"
    assert attempts == 2 and pytest.approx(7.0) in sleeps.calls


async def test_queue_backs_off_on_network_errors_then_gives_up() -> None:
    clock = Clock()
    sleeps = Sleeps(clock)
    q = SendQueue(RateLimiter(clock=clock), max_retries=2, sleep=sleeps)

    async def call() -> None:
        raise TelegramNetworkError(method(), "boom")

    with pytest.raises(TelegramNetworkError):
        await q.run(1, call)
    assert sleeps.calls == [1.0, 2.0]  # backoff only: the clock moved past rate limits


async def test_queue_does_not_retry_forbidden() -> None:
    q = SendQueue(RateLimiter(clock=Clock()), sleep=Sleeps())
    attempts = 0

    async def call() -> None:
        nonlocal attempts
        attempts += 1
        raise TelegramForbiddenError(method(), "bot was kicked")

    with pytest.raises(TelegramForbiddenError):
        await q.run(1, call)
    assert attempts == 1


async def test_same_chat_is_serialized_and_drain_waits() -> None:
    q = SendQueue(RateLimiter(clock=Clock()), sleep=Sleeps())
    active = 0
    peak = 0

    async def call() -> None:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1

    tasks = [asyncio.create_task(q.run(9, call)) for _ in range(4)]
    await asyncio.sleep(0)
    await q.drain()
    await asyncio.gather(*tasks)
    assert peak == 1
