from sqlalchemy.ext.asyncio import AsyncSession

from jakov.db.models import Chat, ChatKind
from jakov.db.repositories.chats import ChatRepo
from jakov.services.channels import handle_membership
from tests.conftest import ADMIN, OWNER, tg_user
from tests.factories import admin_member, left_member, plain_member, tg_chat

ADMINS = {ADMIN}


async def test_added_as_admin_by_owner_links_chat(session: AsyncSession) -> None:
    repo = ChatRepo(session, OWNER)
    change = await handle_membership(
        _upd(left_member(), admin_member()), repo, ADMINS)
    assert change.chat is not None and change.chat.kind is ChatKind.CHANNEL
    assert change.message and "linked" in change.message and not change.leave
    assert (await repo.by_tg_id(-1001)) is not None


async def test_added_by_stranger_leaves(session: AsyncSession) -> None:
    repo = ChatRepo(session, OWNER)
    change = await handle_membership(
        _upd(left_member(), admin_member(), actor=tg_user(555, "<Eve>")), repo, ADMINS)
    assert change.leave and change.chat is None
    assert change.message and "&lt;Eve&gt;" in change.message  # HTML-escaped
    assert await repo.list() == []


async def test_removed_marks_inactive_and_notifies(session: AsyncSession) -> None:
    repo = ChatRepo(session, OWNER)
    await handle_membership(_upd(left_member(), admin_member()), repo, ADMINS)
    change = await handle_membership(_upd(admin_member(), left_member()), repo, ADMINS)
    assert change.chat is not None and not change.chat.is_active
    assert change.message and "removed" in change.message


async def test_lost_rights_are_listed(session: AsyncSession) -> None:
    repo = ChatRepo(session, OWNER)
    await handle_membership(_upd(left_member(), admin_member()), repo, ADMINS)
    change = await handle_membership(
        _upd(admin_member(), admin_member(can_post_messages=False)), repo, ADMINS)
    assert change.message and "post messages" in change.message


async def test_demoted_to_member(session: AsyncSession) -> None:
    repo = ChatRepo(session, OWNER)
    await handle_membership(_upd(left_member(), admin_member(), kind="supergroup"), repo, ADMINS)
    change = await handle_membership(
        _upd(admin_member(), plain_member(), kind="supergroup"), repo, ADMINS)
    assert change.message and "no longer an admin" in change.message


async def test_unrelated_update_for_unknown_left_chat_is_ignored(session: AsyncSession) -> None:
    change = await handle_membership(
        _upd(admin_member(), left_member()), ChatRepo(session, OWNER), ADMINS)
    assert change.chat is None and change.message is None


async def test_no_change_no_message(session: AsyncSession) -> None:
    repo = ChatRepo(session, OWNER)
    await handle_membership(_upd(left_member(), admin_member()), repo, ADMINS)
    change = await handle_membership(_upd(admin_member(), admin_member()), repo, ADMINS)
    assert change.message is None


def _upd(old, new, actor=None, kind: str = "channel"):  # type: ignore[no-untyped-def]
    from tests.factories import member_update

    return member_update(tg_chat(kind=kind), actor or tg_user(), old, new)


def test_chat_name_prefers_display_name() -> None:
    chat = Chat(tg_chat_id=1, kind=ChatKind.CHANNEL, title="T", display_name=None)
    assert chat.name == "T"
    chat.display_name = "Mine"
    assert chat.name == "Mine"
