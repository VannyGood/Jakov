"""Parse what an admin typed to identify a chat: @username, t.me link or numeric ID."""

from __future__ import annotations

import re

_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
_LINK_RE = re.compile(r"^(?:https?://)?(?:t\.me|telegram\.me|telegram\.dog)/(?:s/)?([A-Za-z0-9_]+)/?(?:\d+)?/?$")


class ChatRefError(ValueError):
    pass


def parse_chat_ref(text: str) -> int | str:
    """Return a numeric chat ID or an '@username' suitable for getChat.

    Private invite links (t.me/+abc, t.me/joinchat/abc) cannot be resolved by bots,
    so they raise ChatRefError with a hint to forward a message instead.
    """
    value = text.strip()
    if not value:
        raise ChatRefError("Send @username, a t.me link or a numeric chat ID.")
    if re.fullmatch(r"-?\d{5,20}", value):
        return int(value)
    if "/+" in value or "/joinchat/" in value:
        raise ChatRefError(
            "Private invite links can't be resolved by bots. "
            "Forward any message from the chat instead."
        )
    link = _LINK_RE.match(value)
    if link:
        value = link.group(1)
    value = value.removeprefix("@")
    if not _USERNAME_RE.fullmatch(value):
        raise ChatRefError(f"'{text.strip()}' doesn't look like a username, link or chat ID.")
    return f"@{value}"
