import pytest

from jakov.utils.chat_refs import ChatRefError, parse_chat_ref


@pytest.mark.parametrize(("text", "expected"), [
    ("@mychannel", "@mychannel"),
    ("mychannel", "@mychannel"),
    ("https://t.me/mychannel", "@mychannel"),
    ("t.me/mychannel/123", "@mychannel"),
    ("https://t.me/s/my_channel", "@my_channel"),
    ("-1001234567890", -1001234567890),
    ("  123456789 ", 123456789),
])
def test_valid_refs(text: str, expected: int | str) -> None:
    assert parse_chat_ref(text) == expected


@pytest.mark.parametrize(
    "text", ["", "a b", "@ab", "https://t.me/+AbCdEf", "t.me/joinchat/x", "1@#"]
)
def test_invalid_refs(text: str) -> None:
    with pytest.raises(ChatRefError):
        parse_chat_ref(text)


def test_invite_link_hint() -> None:
    with pytest.raises(ChatRefError, match="Forward"):
        parse_chat_ref("https://t.me/+secret")
