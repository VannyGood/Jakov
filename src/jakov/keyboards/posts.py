from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from jakov.db.models import Chat, Post, PublishedPost
from jakov.engine.catalog import Catalog, Question
from jakov.keyboards.callbacks import MenuCb, PostCb, PubCb
from jakov.keyboards.common import cancel_button


def _btn(text: str, action: str, post: int = 0, value: int = 0) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text,
                                callback_data=PostCb(action=action, post=post, value=value).pack())


def type_picker_kb(catalog: Catalog) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for index, key in enumerate(catalog.type_order):
        kb.button(text=catalog.types[key].title, callback_data=PostCb(action="type", value=index))
    kb.adjust(2)
    kb.row(cancel_button())
    return kb.as_markup()


def question_kb(post: Post, question: Question) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if question.kind == "choice":
        buttons = [_btn(o.label, "choice", post.id, i) for i, o in enumerate(question.options)]
        rows += [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    if not question.required:
        rows.append([_btn("⏭ Skip", "skip", post.id)])
    rows.append([cancel_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tone_kb(post: Post, catalog: Catalog) -> InlineKeyboardMarkup:
    buttons = [_btn(t.title, "tone", post.id, i) for i, t in enumerate(catalog.tones.values())]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([cancel_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def media_kb(post: Post) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("⏭ Text only", "nomedia", post.id)], [cancel_button()]])


def buttons_kb(post: Post) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("⏭ No buttons", "nobuttons", post.id)], [cancel_button()]])


def preview_extra_rows(post: Post, idx: int) -> list[list[InlineKeyboardButton]]:
    """Picker row attached under each preview (below the post's own URL buttons)."""
    return [[_btn(f"✅ Use this (#{idx + 1})", "use", post.id, idx),
             _btn(f"✏️ Edit #{idx + 1}", "editpick", post.id, idx)]]


def review_kb(post: Post, style_label: str) -> InlineKeyboardMarkup:
    count = len(post.variations)
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(f"🔁 Rotate all {count}", "rotate", post.id)],
        [_btn("🔄 Regenerate", "regen", post.id), _btn("🎭 Change emojis", "emojis", post.id)],
        [_btn(f"🎨 Style: {style_label}", "style", post.id)],
        [cancel_button()],
    ])


def ready_kb(post: Post) -> InlineKeyboardMarkup:
    def flag(on: bool) -> str:
        return "On" if on else "Off"

    rows = [[_btn(f"📌 Pin: {flag(post.pin)}", "opt_pin", post.id),
             _btn(f"🔕 Silent: {flag(post.silent)}", "opt_silent", post.id)]]
    if not post.has_media:
        rows.append([_btn(f"🔗 Link preview: {flag(post.link_preview)}", "opt_preview", post.id)])
    rows.append([_btn("📨 Send now", "send", post.id)])
    rows.append([_btn("⬅️ Back to variations", "back", post.id),
                 _btn("✖️ Close", "close", post.id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def chat_picker_kb(post: Post, chats: list[Chat]) -> InlineKeyboardMarkup:
    rows = [[_btn(f"📢 {c.name}"[:60], "sendto", post.id, c.id)] for c in chats]
    rows.append([_btn("⬅️ Back", "ready", post.id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_send_kb(post: Post, chat: Chat) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✅ Send it", "sendgo", post.id, chat.id)],
        [_btn("⬅️ Back", "send", post.id)],
    ])


def published_kb(record: PublishedPost, link: str, *, back_to_list: bool = True
                 ) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🔗 Open post", url=link)]]
    if record.deleted_at is None:
        rows.append([
            InlineKeyboardButton(text="✏️ Edit text",
                                 callback_data=PubCb(action="edit", pk=record.id).pack()),
            InlineKeyboardButton(text="🗑 Delete",
                                 callback_data=PubCb(action="delete", pk=record.id).pack()),
        ])
    rows.append([InlineKeyboardButton(
        text="⬅️ Published posts" if back_to_list else "⬅️ Menu",
        callback_data=PubCb(action="list").pack() if back_to_list
        else MenuCb(to="main").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def published_list_kb(records: list[tuple[PublishedPost, str]], page: int, has_more: bool
                      ) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for record, label in records:
        kb.row(InlineKeyboardButton(text=label[:60],
                                    callback_data=PubCb(action="open", pk=record.id).pack()))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=PubCb(
            action="list", page=page - 1).pack()))
    if has_more:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=PubCb(
            action="list", page=page + 1).pack()))
    if nav:
        kb.row(*nav)
    kb.row(InlineKeyboardButton(text="⬅️ Back", callback_data=MenuCb(to="main").pack()))
    return kb.as_markup()


def confirm_delete_kb(record: PublishedPost) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Yes, delete from the chat",
                              callback_data=PubCb(action="delete_go", pk=record.id).pack())],
        [InlineKeyboardButton(text="⬅️ Back",
                              callback_data=PubCb(action="open", pk=record.id).pack())],
    ])
