"""Content pools (tips, quotes, facts) that rotate without repeats, persisted per owner."""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.db.models import PoolState
from jakov.engine.pools import next_pick


async def pool_values(
    session: AsyncSession, owner_id: int, pools: Mapping[str, Sequence[str]],
    names: Iterable[str], rng: random.Random, *, consume: bool,
) -> dict[str, str]:
    """`consume=False` (previews) peeks a random item without advancing the rotation."""
    values: dict[str, str] = {}
    for name in names:
        items = pools.get(name)
        if not items:
            continue
        if not consume:
            values[name] = rng.choice(list(items))
            continue
        state = await session.scalar(
            select(PoolState).where(PoolState.owner_id == owner_id, PoolState.pool == name))
        if state is None:
            state = PoolState(owner_id=owner_id, pool=name, used=[])
            session.add(state)
        index, state.used = next_pick(len(items), list(state.used or []), rng)
        values[name] = items[index]
    await session.flush()
    return values
