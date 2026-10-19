from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from jakov.db.models import EmojiLibraryItem
from jakov.db.repositories.emoji import PackInfo
from jakov.keyboards.callbacks import EmojiCb, MenuCb

PACKS_PER_PAGE = 8
MOODS_PER_PAGE = 15
ITEMS_PER_PAGE = 12


def _b(text: str, action: str, pk: int = 0, page: int = 0, value: int = 0,
       icon: str | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text, icon_custom_emoji_id=icon,
        callback_data=EmojiCb(action=action, pk=pk, page=page, value=value).pack())


def _nav(action: str, page: int, has_more: bool, pk: int = 0, value: int = 0
         ) -> list[InlineKeyboardButton]:
    row = []
    if page > 0:
        row.append(_b("◀️", action, pk, page - 1, value))
    if has_more:
        row.append(_b("▶️", action, pk, page + 1, value))
    return row


def emoji_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("📦 Packs", "packs"), _b("🏷 Moods", "moods")],
        [_b("➕ Import a pack", "import")],
        [_b("📥 Re-import starter packs", "starter")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data=MenuCb(to="main").pack())],
    ])


def packs_kb(packs: list[PackInfo], page: int, icons: dict[int, str]) -> InlineKeyboardMarkup:
    start = page * PACKS_PER_PAGE
    rows = [[_b(f"{'' if p.active else '⏸ '}{p.title} ({p.count})"[:60], "pack", p.first_id,
                icon=icons.get(p.first_id))]
            for p in packs[start:start + PACKS_PER_PAGE]]
    if nav := _nav("packs", page, start + PACKS_PER_PAGE < len(packs)):
        rows.append(nav)
    rows.append([_b("⬅️ Emoji library", "menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pack_kb(pack: PackInfo, is_menu_pack: bool) -> InlineKeyboardMarkup:
    rows = [[_b("⏸ Disable" if pack.active else "▶️ Enable", "pack_toggle", pack.first_id)]]
    if pack.name and not is_menu_pack:
        rows.append([_b("🎨 Use for my menus", "pack_ui", pack.first_id)])
    rows.append([_b("🗑 Delete pack", "pack_delete", pack.first_id)])
    rows.append([_b("⬅️ Packs", "packs")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_pack_delete_kb(pack: PackInfo) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b(f"🗑 Delete {pack.count} emoji", "pack_delete_go", pack.first_id)],
        [_b("⬅️ Back", "pack", pack.first_id)],
    ])


def moods_kb(moods: list[tuple[str, int]], page: int, icons: dict[str, str]
             ) -> InlineKeyboardMarkup:
    start = page * MOODS_PER_PAGE
    chunk = moods[start:start + MOODS_PER_PAGE]
    buttons = [_b(f"{name} ({n})", "mood", page=0, value=start + i, icon=icons.get(name))
               for i, (name, n) in enumerate(chunk)]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    if nav := _nav("moods", page, start + MOODS_PER_PAGE < len(moods)):
        rows.append(nav)
    rows.append([_b("⬅️ Emoji library", "menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def mood_items_kb(items: list[EmojiLibraryItem], mood_index: int, page: int,
                  icons_ok: bool) -> InlineKeyboardMarkup:
    start = page * ITEMS_PER_PAGE
    buttons = [_b(item.fallback if not icons_ok else f"#{item.id}", "item", item.id,
                  icon=item.custom_emoji_id if icons_ok else None)
               for item in items[start:start + ITEMS_PER_PAGE]]
    rows = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
    if nav := _nav("mood", page, start + ITEMS_PER_PAGE < len(items), value=mood_index):
        rows.append(nav)
    rows.append([_b("⬅️ Moods", "moods")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def item_kb(item: EmojiLibraryItem) -> InlineKeyboardMarkup:
    rows = [[_b("🏷 Add tag", "tag_add", item.id)]]
    tag_buttons = [_b(f"❌ {tag}", "tag_rm", item.id, value=i) for i, tag in enumerate(item.tags)]
    rows += [tag_buttons[i:i + 3] for i in range(0, len(tag_buttons), 3)]
    rows.append([_b("🗑 Delete emoji", "item_delete", item.id)])
    rows.append([_b("⬅️ Moods", "moods"), _b("📦 Its pack", "pack", item.id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
