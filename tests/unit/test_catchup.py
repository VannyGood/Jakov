from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from jakov.engine.catchup import plan
from jakov.engine.recurrence import Recurrence

Z = ZoneInfo("UTC")
GRACE = timedelta(minutes=15)


def u(h: int, m: int = 0, d: int = 20) -> datetime:
    return datetime(2026, 10, d, h, m, tzinfo=UTC)


HOURLY = Recurrence("interval", Z, interval=timedelta(hours=1), anchor=u(0))


def test_on_time_runs() -> None:
    p = plan(HOURLY, u(10), u(10, 0), GRACE)
    assert p.run_now == u(10) and p.next_run == u(11) and p.missed == 0


def test_slightly_late_still_runs() -> None:
    p = plan(HOURLY, u(10), u(10, 14), GRACE)
    assert p.run_now == u(10) and p.missed == 0


def test_too_late_is_skipped_and_next_is_future() -> None:
    p = plan(HOURLY, u(10), u(10, 20), GRACE)
    assert p.run_now is None and p.next_run == u(11)
    assert p.missed == 1 and p.first_missed == u(10)


def test_long_outage_skips_many_and_sends_at_most_one() -> None:
    p = plan(HOURLY, u(2), u(9, 5), GRACE)  # offline from 02:00 to 09:05
    assert p.run_now == u(9) and p.next_run == u(10)
    assert p.missed == 7 and p.first_missed == u(2) and p.last_missed == u(8)


def test_several_runs_in_grace_send_only_latest() -> None:
    every5 = Recurrence("interval", Z, interval=timedelta(minutes=5), anchor=u(0))
    p = plan(every5, u(10, 0), u(10, 12), GRACE)
    assert p.run_now == u(10, 10) and p.missed == 2 and p.next_run == u(10, 15)


def test_missed_one_off_is_dropped() -> None:
    once = Recurrence("once", Z, run_at=u(10))
    p = plan(once, u(10), u(12), GRACE)
    assert p.run_now is None and p.next_run is None and p.missed == 1


def test_zero_grace_skips_any_lateness() -> None:
    p = plan(HOURLY, u(10), u(10, 0, 20) + timedelta(seconds=1), timedelta(0))
    assert p.run_now is None and p.missed == 1
