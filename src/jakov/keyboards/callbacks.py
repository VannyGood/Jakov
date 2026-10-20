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
    action: str  # tz | tz_list | tz_pick | tz_type | tz_loc | emoji_test | ui_toggle | ui_premium
    value: int = 0


class PostCb(CallbackData, prefix="p"):
    # type | skip | choice | tone | nomedia | nobuttons | use | rotate | regen | emojis | style
    # | editpick | back | ready | opt_pin | opt_silent | opt_preview | send | sendto | sendgo
    # | close
    action: str
    post: int = 0
    value: int = 0


class PubCb(CallbackData, prefix="pub"):
    action: str  # list | open | edit | delete | delete_go
    pk: int = 0
    page: int = 0


class EmojiCb(CallbackData, prefix="e"):
    # menu | packs | pack | pack_toggle | pack_delete | pack_delete_go | moods | mood | item
    # | tag_add | tag_rm | item_delete | import | addown | starter
    action: str
    pk: int = 0
    page: int = 0
    value: int = 0


class SchCb(CallbackData, prefix="s"):
    # Wizard: new | chat | when | once | once_type | kind | daily | daily_type | every
    #   | every_type | first | ends | end_count | end_type | opt_rotate | opt_approval
    #   | summary | confirm
    # Manage: list | open | pause | resume | sendnow | edit | delete | delete_go | history
    action: str
    pk: int = 0
    value: int = 0


class ApCb(CallbackData, prefix="ap"):
    action: str  # approve | skip | edit
    pk: int = 0
