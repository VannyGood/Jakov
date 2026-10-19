from typing import Any

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import GetChat, GetChatMember
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.db.models import ChatKind
from jakov.db.repositories.chats import ChatRepo
from jakov.services.channels import LinkError, link_chat, refresh_chat
from tests.conftest import ADMIN, OWNER, FakeSession, tg_user
from tests.factories import BOT_ID, admin_member, full_chat, owner_member, plain_member


def wire(fake: FakeSession, *, bot_member: Any, user_member: Any, chat: Any = None) -> None:
    fake.on("GetMe", lambda m: tg_user(BOT_ID, "Jakov").model_copy(update={"is_bot": True}))
    fake.on("GetChat", lambda m: chat or full_chat(linked=-2002))
    fake.on("GetChatMember",
            lambda m: bot_member if m.user_id == BOT_ID else user_member)


async def test_link_channel_stores_rights_and_discussion_group(
    bot: Bot, fake_session: FakeSession, session: AsyncSession
) -> None:
    wire(fake_session, bot_member=admin_member(), user_member=owner_member(tg_user()))
    repo = ChatRepo(session, OWNER)
    result = await link_chat(bot, repo, "@mychan", ADMIN)
    assert result.created and result.problems == []
    chat = result.chat
    assert chat.kind is ChatKind.CHANNEL and chat.owner_id == OWNER
    assert chat.linked_chat_id == -2002 and chat.username == "mychan"
    assert chat.can_post and chat.can_edit and chat.bot_status == "administrator"
    # Linking again updates instead of duplicating.
    again = await link_chat(bot, repo, -1001, ADMIN)
    assert not again.created and len(await repo.list()) == 1


async def test_link_requires_requester_to_be_chat_admin(
    bot: Bot, fake_session: FakeSession, session: AsyncSession
) -> None:
    wire(fake_session, bot_member=admin_member(), user_member=plain_member(tg_user()))
    with pytest.raises(LinkError, match="must be an admin"):
        await link_chat(bot, ChatRepo(session, OWNER), "@mychan", ADMIN)


async def test_link_unknown_chat_has_friendly_error(
    bot: Bot, fake_session: FakeSession, session: AsyncSession
) -> None:
    fake_session.on("GetChat", lambda m: TelegramBadRequest(GetChat(chat_id=1), "chat not found"))
    with pytest.raises(LinkError, match="Add me as an admin"):
        await link_chat(bot, ChatRepo(session, OWNER), "@ghost", ADMIN)


async def test_link_reports_missing_post_right(
    bot: Bot, fake_session: FakeSession, session: AsyncSession
) -> None:
    wire(fake_session, bot_member=admin_member(can_post_messages=False),
         user_member=owner_member(tg_user()))
    result = await link_chat(bot, ChatRepo(session, OWNER), "@mychan", ADMIN)
    assert result.problems == ["Missing right: post messages."]


async def test_refresh_marks_chat_inactive_when_bot_was_removed(
    bot: Bot, fake_session: FakeSession, session: AsyncSession
) -> None:
    wire(fake_session, bot_member=admin_member(), user_member=owner_member(tg_user()))
    chat = (await link_chat(bot, ChatRepo(session, OWNER), "@mychan", ADMIN)).chat
    fake_session.on("GetChatMember",
                    lambda m: TelegramBadRequest(GetChatMember(chat_id=1, user_id=1), "forbidden"))
    problems = await refresh_chat(bot, chat)
    assert problems and not chat.is_active and chat.bot_status == "left"
