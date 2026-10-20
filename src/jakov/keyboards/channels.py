from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from jakov.db.models import Chat, ChatKind
from jakov.keyboards.callbacks import ChannelCb, MenuCb

KIND_ICON = {ChatKind.CHANNEL: "📣", ChatKind.GROUP: "👥", ChatKind.SUPERGROUP: "👥"}


def chat_status_icon(chat: Chat) -> str:
    if not chat.is_active:
        return "❌"
    return "✅" if chat.can_post else "❗"


def channels_list_kb(chats: list[Chat]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for chat in chats:
        kb.button(
            text=f"{chat_status_icon(chat)} {KIND_ICON[chat.kind]} {chat.name}"[:60],
            callback_data=ChannelCb(action="open", pk=chat.id),
        )
    kb.button(text="➕ Add channel or group", callback_data=ChannelCb(action="add"),
              style="primary")
    kb.button(text="🏠 Menu", callback_data=MenuCb(to="main"))
    kb.adjust(1)
    return kb.as_markup()


def channel_detail_kb(chat: Chat) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Rename", callback_data=ChannelCb(action="rename", pk=chat.id))
    kb.button(text="🔄 Re-check rights", callback_data=ChannelCb(action="recheck", pk=chat.id))
    if chat.is_active and chat.can_post:
        kb.button(text="🧪 Test custom emoji", callback_data=ChannelCb(action="emoji", pk=chat.id))
    kb.button(text="❌ Remove", callback_data=ChannelCb(action="remove", pk=chat.id),
              style="danger")
    kb.button(text="👈 Back", callback_data=MenuCb(to="channels"))
    kb.adjust(2, 1)
    return kb.as_markup()


def confirm_emoji_test_kb(chat: Chat) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Run test", callback_data=ChannelCb(action="emoji_go", pk=chat.id),
              style="success")
    kb.button(text="👈 Back", callback_data=ChannelCb(action="open", pk=chat.id))
    kb.adjust(1)
    return kb.as_markup()


def confirm_remove_kb(chat: Chat) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Remove from Jakov", callback_data=ChannelCb(action="remove_go", pk=chat.id),
              style="danger")
    if chat.is_active:
        kb.button(text="👋 Remove and leave chat",
                  callback_data=ChannelCb(action="leave_go", pk=chat.id), style="danger")
    kb.button(text="👈 Back", callback_data=ChannelCb(action="open", pk=chat.id))
    kb.adjust(1)
    return kb.as_markup()
