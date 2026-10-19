from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.db.models import EmojiLibraryItem


@dataclass(frozen=True, slots=True)
class PackInfo:
    name: str
    title: str
    count: int
    active: bool
    first_id: int


class EmojiRepo:
    def __init__(self, session: AsyncSession, owner_id: int) -> None:
        self.session = session
        self.owner_id = owner_id

    def _q(self) -> Select[EmojiLibraryItem]:
        return select(EmojiLibraryItem).where(EmojiLibraryItem.owner_id == self.owner_id)

    async def get(self, pk: int) -> EmojiLibraryItem | None:
        return await self.session.scalar(self._q().where(EmojiLibraryItem.id == pk))

    async def by_custom_ids(self, ids: Sequence[str]) -> dict[str, EmojiLibraryItem]:
        if not ids:
            return {}
        rows = await self.session.scalars(
            self._q().where(EmojiLibraryItem.custom_emoji_id.in_(list(ids))))
        return {r.custom_emoji_id: r for r in rows}

    async def all(self, active_only: bool = False) -> list[EmojiLibraryItem]:
        query = self._q()
        if active_only:
            query = query.where(EmojiLibraryItem.is_active.is_(True))
        return list(await self.session.scalars(query.order_by(EmojiLibraryItem.id)))

    async def count(self) -> int:
        return int(await self.session.scalar(
            select(func.count()).select_from(EmojiLibraryItem)
            .where(EmojiLibraryItem.owner_id == self.owner_id)) or 0)

    async def packs(self) -> list[PackInfo]:
        """Every pack ('' = emoji added by hand), in import order."""
        rows = await self.session.execute(
            select(
                func.coalesce(EmojiLibraryItem.pack_name, ""),
                func.max(EmojiLibraryItem.pack_title),
                func.count(),
                func.max(EmojiLibraryItem.is_active),
                func.min(EmojiLibraryItem.id),
            )
            .where(EmojiLibraryItem.owner_id == self.owner_id)
            .group_by(func.coalesce(EmojiLibraryItem.pack_name, ""))
            .order_by(func.min(EmojiLibraryItem.id))
        )
        return [PackInfo(name, title or name or "Added by hand", int(n), bool(active), int(first))
                for name, title, n, active, first in rows.all()]

    async def in_pack(self, pack: str) -> list[EmojiLibraryItem]:
        cond = (EmojiLibraryItem.pack_name.is_(None) if pack == ""
                else EmojiLibraryItem.pack_name == pack)
        return list(await self.session.scalars(self._q().where(cond).order_by(EmojiLibraryItem.id)))

    async def set_pack_active(self, pack: str, active: bool) -> None:
        cond = (EmojiLibraryItem.pack_name.is_(None) if pack == ""
                else EmojiLibraryItem.pack_name == pack)
        await self.session.execute(
            update(EmojiLibraryItem)
            .where(EmojiLibraryItem.owner_id == self.owner_id, cond)
            .values(is_active=active))

    async def delete_pack(self, pack: str) -> int:
        cond = (EmojiLibraryItem.pack_name.is_(None) if pack == ""
                else EmojiLibraryItem.pack_name == pack)
        result = await self.session.execute(
            delete(EmojiLibraryItem).where(EmojiLibraryItem.owner_id == self.owner_id, cond))
        return int(getattr(result, "rowcount", 0) or 0)

    async def delete(self, item: EmojiLibraryItem) -> None:
        await self.session.delete(item)
        await self.session.flush()

    def add(self, item: EmojiLibraryItem) -> None:
        item.owner_id = self.owner_id
        self.session.add(item)
