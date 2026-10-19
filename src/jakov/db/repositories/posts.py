from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.db.models import Chat, Post, PublishedPost


class PostRepo:
    def __init__(self, session: AsyncSession, owner_id: int) -> None:
        self.session = session
        self.owner_id = owner_id

    async def get(self, pk: int) -> Post | None:
        return await self.session.scalar(
            select(Post).where(Post.id == pk, Post.owner_id == self.owner_id))

    async def add(self, post: Post) -> Post:
        post.owner_id = self.owner_id
        self.session.add(post)
        await self.session.flush()
        # Load unset columns and the (empty) variations now: async sessions can't lazy-load.
        await self.session.refresh(post)
        return post


class PublishedRepo:
    def __init__(self, session: AsyncSession, owner_id: int) -> None:
        self.session = session
        self.owner_id = owner_id

    async def get(self, pk: int) -> PublishedPost | None:
        return await self.session.scalar(select(PublishedPost).where(
            PublishedPost.id == pk, PublishedPost.owner_id == self.owner_id))

    async def recent(self, offset: int, limit: int) -> list[tuple[PublishedPost, Chat | None]]:
        rows = await self.session.execute(
            select(PublishedPost, Chat)
            .outerjoin(Chat, Chat.id == PublishedPost.chat_id)
            .where(PublishedPost.owner_id == self.owner_id, PublishedPost.deleted_at.is_(None))
            .order_by(PublishedPost.sent_at.desc(), PublishedPost.id.desc())
            .offset(offset).limit(limit)
        )
        return [(p, c) for p, c in rows.all()]
