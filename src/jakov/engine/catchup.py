"""Catch-up policy: what to do with runs that became due while the bot was offline.

Default: a run that is less than `grace` late is sent now; anything older is skipped and
logged once as a summary. Multiple missed runs never turn into a burst of posts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from jakov.engine.recurrence import Recurrence

_MAX_STEPS = 100_000


@dataclass(frozen=True, slots=True)
class CatchUpPlan:
    run_now: datetime | None        # scheduled time of the run to execute now, if any
    next_run: datetime | None       # the following run after this tick
    missed: int = 0
    first_missed: datetime | None = None
    last_missed: datetime | None = None


def plan(rec: Recurrence, due: datetime, now: datetime, grace: timedelta) -> CatchUpPlan:
    """`due` is the stored next_run_at (<= now)."""
    missed = 0
    first: datetime | None = None
    last: datetime | None = None
    cursor: datetime | None = due
    while cursor is not None and now - cursor > grace and missed < _MAX_STEPS:
        missed += 1
        first = first or cursor
        last = cursor
        cursor = rec.next_after(cursor)
    if cursor is not None and cursor <= now:
        # Several runs may still be inside the grace window; only the latest is sent.
        while (following := rec.next_after(cursor)) is not None and following <= now:
            missed += 1
            first = first or cursor
            last = cursor
            cursor = following
        return CatchUpPlan(cursor, rec.next_after(cursor), missed, first, last)
    return CatchUpPlan(None, cursor, missed, first, last)
