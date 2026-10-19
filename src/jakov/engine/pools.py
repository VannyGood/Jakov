"""Pick pool items without repeating until every item has been used."""

from __future__ import annotations

import random


def next_pick(size: int, used: list[int], rng: random.Random) -> tuple[int, list[int]]:
    """Return (index, updated used list). A new cycle never starts with the last item."""
    if size <= 0:
        raise ValueError("empty pool")
    used = [i for i in used if 0 <= i < size]
    remaining = [i for i in range(size) if i not in set(used)]
    if not remaining:
        last = used[-1] if used else None
        remaining = [i for i in range(size) if i != last] or [0]
        used = []
    index = rng.choice(remaining)
    return index, [*used, index]
