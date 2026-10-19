"""Declarative base and shared column mixins."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from jakov.db.types import UTCDateTime

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class OwnedMixin:
    """Every table carries the workspace owner so the bot can become multi-tenant."""

    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, server_default=func.now()
    )
