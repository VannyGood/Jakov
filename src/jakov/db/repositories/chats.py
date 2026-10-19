from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.db.models import Chat


class ChatRepo:
    def __init__(self, session: AsyncSession, owner_id: int) -> None:
        self.session = session
        self.owner_id = owner_id

    async def get(self, chat_pk: int) -> Chat | None:
        return await self.session.scalar(
            select(Chat).where(Chat.id == chat_pk, Chat.owner_id == self.owner_id)
        )

    async def by_tg_id(self, tg_chat_id: int) -> Chat | None:
        return await self.session.scalar(
            select(Chat).where(Chat.tg_chat_id == tg_chat_id, Chat.owner_id == self.owner_id)
        )

    async def list(self, include_inactive: bool = True) -> list[Chat]:
        query = select(Chat).where(Chat.owner_id == self.owner_id)
        if not include_inactive:
            query = query.where(Chat.is_active.is_(True))
        result = await self.session.scalars(query.order_by(Chat.created_at))
        return list(result)

    async def add(self, chat: Chat) -> Chat:
        chat.owner_id = self.owner_id
        self.session.add(chat)
        await self.session.flush()
        return chat

    async def delete(self, chat: Chat) -> None:
        await self.session.delete(chat)
        await self.session.flush()
