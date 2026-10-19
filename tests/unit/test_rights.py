from aiogram.types import ChatMemberRestricted

from jakov.db.models import ChatKind
from jakov.services.rights import (
    Rights,
    lost_rights,
    publisher_problems,
    rights_from_member,
    status_value,
)
from tests.factories import BOT_USER, admin_member, left_member, owner_member, plain_member


def test_status_is_plain_string() -> None:
    assert rights_from_member(admin_member(), ChatKind.CHANNEL).status == "administrator"
    assert status_value("member") == "member"


def test_channel_admin_with_post_and_edit_is_ready() -> None:
    r = rights_from_member(admin_member(), ChatKind.CHANNEL)
    assert r.is_admin and r.can_post and r.can_edit and r.can_pin
    assert publisher_problems(ChatKind.CHANNEL, r) == []


def test_channel_admin_without_post_right() -> None:
    r = rights_from_member(admin_member(can_post_messages=False), ChatKind.CHANNEL)
    assert publisher_problems(ChatKind.CHANNEL, r) == ["Missing right: post messages."]


def test_channel_pin_follows_edit_right() -> None:
    r = rights_from_member(admin_member(can_edit_messages=False, can_pin_messages=True),
                           ChatKind.CHANNEL)
    assert not r.can_pin and not r.can_edit


def test_group_admin_can_always_post() -> None:
    r = rights_from_member(admin_member(can_post_messages=None, can_restrict_members=False),
                           ChatKind.SUPERGROUP)
    assert r.can_post and not r.can_restrict
    assert publisher_problems(ChatKind.SUPERGROUP, r) == []


def test_group_member_not_admin() -> None:
    r = rights_from_member(plain_member(), ChatKind.SUPERGROUP)
    assert r.can_post and not r.is_admin
    assert "not an admin" in publisher_problems(ChatKind.SUPERGROUP, r)[0]


def test_owner_has_everything() -> None:
    r = rights_from_member(owner_member(BOT_USER), ChatKind.CHANNEL)
    assert all(r.flags().values())


def test_left_is_not_present() -> None:
    r = rights_from_member(left_member(), ChatKind.CHANNEL)
    assert not r.is_present
    assert publisher_problems(ChatKind.CHANNEL, r) == ["I'm not a member of this chat."]


def test_restricted_member_cannot_post() -> None:
    m = ChatMemberRestricted(
        user=BOT_USER, is_member=True, can_send_messages=False, can_send_audios=False,
        can_send_documents=False, can_send_photos=False, can_send_videos=False,
        can_send_video_notes=False, can_send_voice_notes=False, can_send_polls=False,
        can_send_other_messages=False, can_add_web_page_previews=False, can_change_info=False,
        can_invite_users=False, can_pin_messages=False, can_manage_topics=False, can_edit_tag=False,
        can_react_to_messages=False,
        until_date=0,
    )
    assert not rights_from_member(m, ChatKind.SUPERGROUP).can_post


def test_lost_rights_lists_only_removed() -> None:
    before = Rights("administrator", can_post=True, can_delete=True, can_pin=True)
    after = Rights("administrator", can_post=True, can_delete=False, can_pin=False)
    assert lost_rights(before, after) == ["delete messages", "pin messages"]
