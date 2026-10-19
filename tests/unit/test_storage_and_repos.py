from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jakov.db.fsm_storage import SQLAlchemyStorage
from jakov.db.models import Chat, ChatKind, FsmState
from jakov.db.repositories.capabilities import CapabilityRepo
from jakov.db.repositories.chats import ChatRepo
from jakov.db.repositories.users import UserRepo
from tests.conftest import OWNER


class S(StatesGroup):
    step = State()


KEY = StorageKey(bot_id=1, chat_id=2, user_id=3)


async def test_fsm_state_and_data_roundtrip(sessions: async_sessionmaker[AsyncSession]) -> None:
    storage = SQLAlchemyStorage(sessions, OWNER)
    assert await storage.get_state(KEY) is None
    await storage.set_state(KEY, S.step)
    await storage.update_data(KEY, {"a": 1})
    await storage.update_data(KEY, {"b": [1, 2]})
    assert await storage.get_state(KEY) == "S:step"
    assert await storage.get_data(KEY) == {"a": 1, "b": [1, 2]}

    # A fresh storage instance (= bot restart) still sees it.
    again = SQLAlchemyStorage(sessions, OWNER)
    assert await again.get_state(KEY) == "S:step"


async def test_fsm_clear_removes_row(sessions: async_sessionmaker[AsyncSession]) -> None:
    storage = SQLAlchemyStorage(sessions, OWNER)
    await storage.set_state(KEY, S.step)
    await storage.set_data(KEY, {"x": 1})
    await storage.set_state(KEY, None)
    await storage.set_data(KEY, {})
    async with sessions() as s:
        assert (await s.scalars(select(FsmState))).all() == []


async def test_fsm_clear_on_empty_key_is_noop(sessions: async_sessionmaker[AsyncSession]) -> None:
    await SQLAlchemyStorage(sessions, OWNER).set_state(KEY, None)
    async with sessions() as s:
        assert (await s.scalars(select(FsmState))).all() == []


async def test_repos_are_scoped_by_owner(session: AsyncSession) -> None:
    mine, theirs = ChatRepo(session, OWNER), ChatRepo(session, 999)
    chat = await mine.add(Chat(tg_chat_id=-1, kind=ChatKind.CHANNEL, title="A", settings={}))
    await theirs.add(Chat(tg_chat_id=-1, kind=ChatKind.CHANNEL, title="B", settings={}))
    assert [c.title for c in await mine.list()] == ["A"]
    assert await theirs.get(chat.id) is None


async def test_user_touch_and_timezone(session: AsyncSession) -> None:
    users = UserRepo(session, OWNER)
    user, created = await users.touch(5, "nick", "Nick", is_admin=True)
    assert created and user.owner_id == OWNER
    _, created_again = await users.touch(5, "nick2", "Nick", is_admin=True)
    assert not created_again
    await users.set_timezone(5, "Europe/Berlin")
    fetched = await users.get(5)
    assert fetched is not None and fetched.timezone == "Europe/Berlin"
    assert fetched.last_seen_at is not None and fetched.last_seen_at.tzinfo is not None


async def test_capability_upsert(session: AsyncSession) -> None:
    caps = CapabilityRepo(session, OWNER)
    await caps.set("k", True, "ok")
    await caps.set("k", False, "nope")
    cap = await caps.get("k")
    assert cap is not None and cap.supported is False and cap.detail == "nope"
