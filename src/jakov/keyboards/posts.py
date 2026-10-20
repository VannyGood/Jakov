from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from jakov.db.models import Chat, Post, PublishedPost
from jakov.engine.catalog import Catalog, Question
from jakov.keyboards.callbacks import MenuCb, PostCb, PubCb, SchCb
from jakov.keyboards.common import cancel_button
from jakov.keyboards.ui import Style, btn, grid, kb, url_btn


def _b(text: str, action: str, post: int = 0, value: int = 0, style: Style = None
       ) -> InlineKeyboardButton:
    return btn(text, PostCb(action=action, post=post, value=value), style)


def type_picker_kb(catalog: Catalog) -> InlineKeyboardMarkup:
    buttons = [_b(catalog.types[key].title, "type", value=i)
               for i, key in enumerate(catalog.type_order)]
    return InlineKeyboardMarkup(inline_keyboard=[*grid(buttons, 2), [cancel_button()]])


def question_kb(post: Post, question: Question) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if question.kind == "choice":
        rows += grid([_b(o.label, "choice", post.id, i)
                      for i, o in enumerate(question.options)], 2)
    if not question.required:
        rows.append([_b("👉 Skip", "skip", post.id)])
    rows.append([cancel_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tone_kb(post: Post, catalog: Catalog) -> InlineKeyboardMarkup:
    buttons = [_b(t.title, "tone", post.id, i) for i, t in enumerate(catalog.tones.values())]
    return InlineKeyboardMarkup(inline_keyboard=[*grid(buttons, 2), [cancel_button()]])


def extras_kb(post: Post) -> InlineKeyboardMarkup:
    rows = [[_b("✨ Create my post", "create", post.id, style="success")]]
    removals = []
    if post.has_media:
        removals.append(_b("❌ Remove media", "nomedia", post.id))
    if post.buttons:
        removals.append(_b("❌ Remove buttons", "nobuttons", post.id))
    if removals:
        rows.append(removals)
    rows.append([cancel_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def preview_extra_rows(post: Post, idx: int) -> list[list[InlineKeyboardButton]]:
    """Picker row attached under each preview (below the post's own URL buttons)."""
    return [[_b(f"✅ Use this · #{idx + 1}", "use", post.id, idx, "success"),
             _b("✏️ Edit", "editpick", post.id, idx)]]


def review_kb(post: Post, style_label: str) -> InlineKeyboardMarkup:
    return kb(
        _b(f"🔄 Use all {len(post.variations)} (rotate)", "rotate", post.id, style="success"),
        [_b("🔄 New texts", "regen", post.id), _b("🎭 New emojis", "emojis", post.id)],
        _b(f"🎨 Emoji style: {style_label}", "style", post.id),
        cancel_button(),
    )


def ready_kb(post: Post) -> InlineKeyboardMarkup:
    def flag(on: bool) -> str:
        return "on" if on else "off"

    options = [_b(f"⭐ Pin {flag(post.pin)}", "opt_pin", post.id),
               _b(f"🔕 Silent {flag(post.silent)}", "opt_silent", post.id)]
    if not post.has_media:
        options.append(_b(f"🔗 Preview {flag(post.link_preview)}", "opt_preview", post.id))
    return kb(
        [_b("🚀 Post now", "send", post.id, style="success"),
         btn("⏰ Schedule", SchCb(action="new", pk=post.id), "primary")],
        options,
        [_b("👈 Other variation", "back", post.id), _b("Done", "close", post.id)],
    )


def chat_picker_kb(post: Post, chats: list[Chat]) -> InlineKeyboardMarkup:
    rows = [[_b(f"📣 {c.name}"[:60], "sendto", post.id, c.id)] for c in chats]
    rows.append([_b("👈 Back", "ready", post.id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_send_kb(post: Post, chat: Chat) -> InlineKeyboardMarkup:
    return kb(_b("🚀 Post it now", "sendgo", post.id, chat.id, "success"),
              _b("👈 Back", "ready", post.id))


def published_kb(record: PublishedPost, link: str, *, back_to_list: bool = True
                 ) -> InlineKeyboardMarkup:
    rows = [[url_btn("🔗 Open post", link)]]
    if record.deleted_at is None:
        rows.append([btn("✏️ Edit text", PubCb(action="edit", pk=record.id)),
                     btn("❌ Delete", PubCb(action="delete", pk=record.id), "danger")])
    rows.append([btn("👈 Posts", PubCb(action="list")) if back_to_list
                 else btn("🏠 Menu", MenuCb(to="main"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def published_list_kb(records: list[tuple[PublishedPost, str]], page: int, has_more: bool
                      ) -> InlineKeyboardMarkup:
    rows = [[btn(label[:60], PubCb(action="open", pk=record.id))] for record, label in records]
    nav = []
    if page > 0:
        nav.append(btn("◀️", PubCb(action="list", page=page - 1)))
    if has_more:
        nav.append(btn("▶️", PubCb(action="list", page=page + 1)))
    if nav:
        rows.append(nav)
    rows.append([btn("🏠 Menu", MenuCb(to="main"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_delete_kb(record: PublishedPost) -> InlineKeyboardMarkup:
    return kb(btn("❌ Yes, delete it from the chat", PubCb(action="delete_go", pk=record.id),
                  "danger"),
              btn("👈 Back", PubCb(action="open", pk=record.id)))
