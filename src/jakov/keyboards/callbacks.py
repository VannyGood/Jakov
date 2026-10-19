"""Typed callback data for every inline button (each must stay under 64 bytes)."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class MenuCb(CallbackData, prefix="m"):
    to: str  # main | channels | settings


class CancelCb(CallbackData, prefix="x"):
    pass


class ChannelCb(CallbackData, prefix="ch"):
    action: str  # open | add | rename | recheck | emoji | emoji_go | remove | remove_go | leave_go
    pk: int = 0


class SettingsCb(CallbackData, prefix="st"):
    action: str  # tz | tz_list | tz_pick | tz_type | tz_loc | emoji_test
    value: int = 0
