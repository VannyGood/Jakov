"""Telegram send limits as slot reservations on a clock (pure, testable with a fake clock).

- at most ~30 messages/second overall: global slots are >= 1/30 s apart
- at most 1 message/second to the same private chat
- at most 20 messages/minute to the same group or channel: >= 3 s apart

Reservations may lie in the future (a chat waiting for its next slot); other chats can
still use the free global slots before it.
"""

from __future__ import annotations

import bisect
import time
from collections.abc import Callable


class RateLimiter:
    def __init__(self, *, global_per_second: int = 30, private_interval: float = 1.0,
                 group_per_minute: int = 20, clock: Callable[[], float] = time.monotonic
                 ) -> None:
        self.clock = clock
        self._global_gap = 1.0 / global_per_second
        self._private_interval = private_interval
        self._group_interval = max(private_interval, 60.0 / group_per_minute)
        self._slots: list[float] = []
        self._chat_next: dict[int, float] = {}

    def interval_for(self, chat_id: int) -> float:
        # Negative IDs are groups, supergroups and channels.
        return self._group_interval if chat_id < 0 else self._private_interval

    def _free_global_slot(self, t: float) -> float:
        gap = self._global_gap
        start = bisect.bisect_left(self._slots, t - gap)
        candidate = t
        for slot in self._slots[start:]:
            if slot + gap <= candidate:
                continue
            if candidate + gap <= slot:
                break
            candidate = slot + gap
        return candidate

    def reserve(self, chat_id: int) -> float:
        """Reserve the next allowed slot for `chat_id`; returns seconds to wait (>= 0)."""
        now = self.clock()
        t = max(now, self._chat_next.get(chat_id, now))
        t = self._free_global_slot(t)
        bisect.insort(self._slots, t)
        self._chat_next[chat_id] = t + self.interval_for(chat_id)
        cutoff = bisect.bisect_left(self._slots, now - 1.0)
        del self._slots[:cutoff]
        return max(0.0, t - now)

    def block(self, chat_id: int, seconds: float) -> None:
        """Telegram said RetryAfter: nothing more to this chat for `seconds`."""
        self._chat_next[chat_id] = max(self._chat_next.get(chat_id, 0.0),
                                       self.clock() + seconds)
