"""Per-admin timezone: from a shared location, a picked list, or a typed IANA name."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo, available_timezones

COMMON_ZONES: tuple[str, ...] = (
    "Europe/London", "Europe/Berlin", "Europe/Paris", "Europe/Madrid", "Europe/Rome",
    "Europe/Belgrade", "Europe/Athens", "Europe/Istanbul", "Europe/Kyiv", "Europe/Moscow",
    "Asia/Dubai", "Asia/Tehran", "Asia/Karachi", "Asia/Kolkata", "Asia/Tashkent",
    "Asia/Bangkok", "Asia/Shanghai", "Asia/Singapore", "Asia/Tokyo", "Australia/Sydney",
    "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
    "America/Sao_Paulo", "America/Mexico_City", "Africa/Cairo", "Africa/Lagos", "UTC",
)


@lru_cache(maxsize=1)
def _finder() -> Any:
    from timezonefinder import TimezoneFinder

    return TimezoneFinder()


def zone_at(latitude: float, longitude: float) -> str | None:
    zone: str | None = _finder().timezone_at(lat=latitude, lng=longitude)
    return zone


async def zone_from_location(latitude: float, longitude: float) -> str | None:
    """Offline lookup (no external API); runs in a thread because the first call loads data."""
    return await asyncio.to_thread(zone_at, latitude, longitude)


@lru_cache(maxsize=1)
def _zones_by_lower() -> dict[str, str]:
    return {z.lower(): z for z in available_timezones()}


def normalize_zone(text: str) -> str | None:
    """Accept 'europe/berlin', 'Europe/Berlin', 'new york' etc. Returns the IANA name or None."""
    cleaned = text.strip().replace(" ", "_")
    if not cleaned:
        return None
    zones = _zones_by_lower()
    if cleaned.lower() in zones:
        return zones[cleaned.lower()]
    matches = [z for low, z in zones.items() if low.endswith("/" + cleaned.lower())]
    return matches[0] if len(matches) == 1 else None


def effective_zone(user_zone: str | None, default: str) -> ZoneInfo:
    return ZoneInfo(user_zone or default)
