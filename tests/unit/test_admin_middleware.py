from datetime import UTC, datetime
from typing import Any

from aiogram.types import CallbackQuery, Chat, Message

from jakov.middlewares.admin_only import AdminOnlyMiddleware
from tests.conftest import ADMIN, tg_user


def msg(user_id: int, chat_type: str = "private") -> Message:
    return Message(message_id=1, date=datetime.now(UTC), text="/start",
                   chat=Chat(id=user_id if chat_type == "private" else -5, type=chat_type),
                   from_user=tg_user(user_id))


async def _run(event: Any) -> bool:
    called = False

    async def handler(e: Any, d: dict[str, Any]) -> None:
        nonlocal called
        called = True

    await AdminOnlyMiddleware({ADMIN})(handler, event, {})
    return called


async def test_admin_passes() -> None:
    assert await _run(msg(ADMIN))


async def test_stranger_in_private_is_ignored() -> None:
    assert not await _run(msg(42))


async def test_group_messages_pass_for_guard() -> None:
    assert await _run(msg(42, "supergroup"))


async def test_stranger_buttons_are_ignored() -> None:
    cb = CallbackQuery(id="1", from_user=tg_user(42), chat_instance="c", data="m:main")
    assert not await _run(cb)
    cb_admin = CallbackQuery(id="2", from_user=tg_user(ADMIN), chat_instance="c", data="m:main")
    assert await _run(cb_admin)
