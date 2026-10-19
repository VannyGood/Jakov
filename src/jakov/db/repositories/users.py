from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.db.base import utcnow
from jakov.db.models import User


class UserRepo:
    def __init__(self, session: AsyncSession, owner_id: int) -> None:
        self.session = session
        self.owner_id = owner_id

    async def get(self, tg_user_id: int) -> User | None:
        return await self.session.scalar(
            select(User).where(User.tg_user_id == tg_user_id, User.owner_id == self.owner_id)
        )

    async def touch(
        self, tg_user_id: int, username: str | None, full_name: str, is_admin: bool
    ) -> tuple[User, bool]:
        """Create or refresh a user. Returns (user, created)."""
        user = await self.get(tg_user_id)
        created = user is None
        if user is None:
            user = User(owner_id=self.owner_id, tg_user_id=tg_user_id)
            self.session.add(user)
        user.username = username
        user.full_name = full_name
        user.is_admin = is_admin
        user.last_seen_at = utcnow()
        await self.session.flush()
        return user, created

    async def set_timezone(self, tg_user_id: int, zone: str) -> None:
        user = await self.get(tg_user_id)
        if user is not None:
            user.timezone = zone
            await self.session.flush()

    async def admins(self) -> list[User]:
        result = await self.session.scalars(
            select(User).where(User.owner_id == self.owner_id, User.is_admin.is_(True))
        )
        return list(result)
