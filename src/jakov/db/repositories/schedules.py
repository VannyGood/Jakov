from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.db.models import ApprovalRequest, Schedule, SendLog


class ScheduleRepo:
    def __init__(self, session: AsyncSession, owner_id: int) -> None:
        self.session = session
        self.owner_id = owner_id

    async def get(self, pk: int) -> Schedule | None:
        return await self.session.scalar(
            select(Schedule).where(Schedule.id == pk, Schedule.owner_id == self.owner_id))

    async def add(self, schedule: Schedule) -> Schedule:
        schedule.owner_id = self.owner_id
        self.session.add(schedule)
        await self.session.flush()
        await self.session.refresh(schedule)
        return schedule

    async def all(self) -> list[Schedule]:
        result = await self.session.scalars(
            select(Schedule).where(Schedule.owner_id == self.owner_id)
            .order_by(Schedule.status, Schedule.next_run_at.is_(None), Schedule.next_run_at))
        return list(result)

    async def due(self, now: datetime, limit: int = 20) -> list[int]:
        result = await self.session.scalars(
            select(Schedule.id).where(Schedule.owner_id == self.owner_id,
                                      Schedule.status == "active",
                                      Schedule.next_run_at.is_not(None),
                                      Schedule.next_run_at <= now)
            .order_by(Schedule.next_run_at).limit(limit))
        return list(result)

    async def for_chat(self, chat_pk: int, status: str = "active") -> list[Schedule]:
        result = await self.session.scalars(select(Schedule).where(
            Schedule.owner_id == self.owner_id, Schedule.chat_id == chat_pk,
            Schedule.status == status))
        return list(result)

    async def pending_runs(self, schedule_id: int) -> int:
        return int(await self.session.scalar(
            select(func.count()).select_from(SendLog).where(
                SendLog.schedule_id == schedule_id,
                SendLog.status.in_(("in_flight", "awaiting_approval")))) or 0)

    async def history(self, schedule_id: int, limit: int = 10) -> list[SendLog]:
        result = await self.session.scalars(
            select(SendLog).where(SendLog.schedule_id == schedule_id)
            .order_by(SendLog.scheduled_for.desc(), SendLog.id.desc()).limit(limit))
        return list(result)

    async def delete(self, schedule: Schedule) -> None:
        await self.session.execute(
            update(ApprovalRequest).where(ApprovalRequest.schedule_id == schedule.id,
                                          ApprovalRequest.status == "pending")
            .values(status="skipped"))
        await self.session.delete(schedule)
        await self.session.flush()
