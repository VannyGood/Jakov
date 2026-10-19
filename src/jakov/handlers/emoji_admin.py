"""😀 Emoji library: browse packs and moods, tag, delete, import (/emojipack, /addemoji)."""

from __future__ import annotations

import html

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.context import AppContext
from jakov.db.models import EmojiLibraryItem
from jakov.db.repositories.emoji import EmojiRepo, PackInfo
from jakov.db.repositories.users import UserRepo
from jakov.engine.emoji_render import tg_emoji
from jakov.keyboards.callbacks import EmojiCb, MenuCb
from jakov.keyboards.common import cancel_kb
from jakov.keyboards.emoji import (
    confirm_pack_delete_kb,
    emoji_menu_kb,
    item_kb,
    mood_items_kb,
    moods_kb,
    pack_kb,
    packs_kb,
)
from jakov.services.emoji_library import (
    MAX_TAGS,
    EmojiImportError,
    add_from_message,
    import_pack,
    normalize_tag,
)
from jakov.services.starter import import_starter_packs
from jakov.utils.telegram import show

router = Router(name="emoji_admin")
router.message.filter(F.chat.type == ChatType.PRIVATE)
SAMPLE = 40


class EmojiStates(StatesGroup):
    waiting_pack = State()
    waiting_custom = State()
    waiting_tag = State()


def _sample_line(items: list[EmojiLibraryItem], animated: bool) -> str:
    return "".join(tg_emoji(i.custom_emoji_id, i.fallback) if animated
                   else html.escape(i.fallback) for i in items[:SAMPLE])


async def _commit_reload(session: AsyncSession, ctx: AppContext) -> None:
    await session.commit()
    await ctx.reload_emoji()


# --- menu --------------------------------------------------------------------

async def _menu_text(session: AsyncSession, ctx: AppContext) -> str:
    repo = EmojiRepo(session, ctx.owner_id)
    packs = await repo.packs()
    moods = ctx.library.palette.mood_counts()
    top = ", ".join(f"{m} {n}" for m, n in moods[:8]) or "none yet"
    return (
        "😀 <b>Emoji library</b>\n\n"
        f"Active emoji: <b>{ctx.library.size}</b> in {sum(p.active for p in packs)} packs\n"
        f"Top moods: {html.escape(top)}\n\n"
        "Posts pick emoji by mood (<code>{emoji:fire}</code>, <code>{emoji:money}</code>…).\n"
        "Add more with <code>/emojipack https://t.me/addemoji/Name</code> or "
        "<code>/addemoji mood</code>."
    )


@router.message(Command("emoji"))
async def cmd_emoji(message: Message, ctx: AppContext, session: AsyncSession,
                    state: FSMContext) -> None:
    await state.clear()
    await message.answer(await _menu_text(session, ctx), reply_markup=emoji_menu_kb())


@router.callback_query(MenuCb.filter(F.to == "emoji"))
@router.callback_query(EmojiCb.filter(F.action == "menu"))
async def cb_menu(callback: CallbackQuery, ctx: AppContext, session: AsyncSession,
                  state: FSMContext) -> None:
    await state.clear()
    await show(callback, await _menu_text(session, ctx), emoji_menu_kb())
    await callback.answer()


# --- packs -------------------------------------------------------------------

@router.callback_query(EmojiCb.filter(F.action == "packs"))
async def cb_packs(callback: CallbackQuery, callback_data: EmojiCb, ctx: AppContext,
                   session: AsyncSession) -> None:
    await _render_packs(callback, ctx, session, callback_data.page)
    await callback.answer()


async def _render_packs(callback: CallbackQuery, ctx: AppContext, session: AsyncSession,
                        page: int, prefix: str = "") -> None:
    repo = EmojiRepo(session, ctx.owner_id)
    packs = await repo.packs()
    icons: dict[int, str] = {}
    if ctx.ui.dm_supported:
        for pack in packs:
            first = await repo.get(pack.first_id)
            if first and first.kind != "static":
                icons[pack.first_id] = first.custom_emoji_id
    await show(callback, f"{prefix}📦 <b>Packs</b> ({len(packs)})", packs_kb(packs, page, icons))


async def _pack_of(repo: EmojiRepo, item_pk: int) -> PackInfo | None:
    item = await repo.get(item_pk)
    if item is None:
        return None
    name = item.pack_name or ""
    return next((p for p in await repo.packs() if p.name == name), None)


@router.callback_query(EmojiCb.filter(F.action == "pack"))
async def cb_pack(callback: CallbackQuery, callback_data: EmojiCb, ctx: AppContext,
                  session: AsyncSession) -> None:
    if await _render_pack(callback, ctx, session, callback_data.pk):
        await callback.answer()
    else:
        await callback.answer("Pack not found.", show_alert=True)


async def _render_pack(callback: CallbackQuery, ctx: AppContext, session: AsyncSession,
                       item_pk: int) -> bool:
    repo = EmojiRepo(session, ctx.owner_id)
    pack = await _pack_of(repo, item_pk)
    if pack is None:
        return False
    items = await repo.in_pack(pack.name)
    user = await UserRepo(session, ctx.owner_id).get(callback.from_user.id)
    menu_pack = (user.ui_emoji_pack if user else None) or ctx.library.default_ui_pack
    link = (f'\n<a href="https://t.me/addemoji/{html.escape(pack.name)}">Open in Telegram</a>'
            if pack.name else "")
    text = (f"📦 <b>{html.escape(pack.title)}</b>{link}\n"
            f"{pack.count} emoji · {'active' if pack.active else '⏸ disabled'}"
            f"{' · 🎨 used for your menus' if pack.name and pack.name == menu_pack else ''}\n\n"
            f"{_sample_line(items, ctx.ui.dm_supported)}")
    await show(callback, text, pack_kb(pack, pack.name == menu_pack))
    return True


@router.callback_query(EmojiCb.filter(F.action.in_({"pack_toggle", "pack_ui"})))
async def cb_pack_change(callback: CallbackQuery, callback_data: EmojiCb, ctx: AppContext,
                         session: AsyncSession) -> None:
    repo = EmojiRepo(session, ctx.owner_id)
    pack = await _pack_of(repo, callback_data.pk)
    if pack is None:
        await callback.answer("Pack not found.", show_alert=True)
        return
    if callback_data.action == "pack_toggle":
        await repo.set_pack_active(pack.name, not pack.active)
        note = "Disabled" if pack.active else "Enabled"
    else:
        user = await UserRepo(session, ctx.owner_id).get(callback.from_user.id)
        if user is not None:
            user.ui_emoji_pack = pack.name
        note = "Your menus now use this pack 🎨"
    await _commit_reload(session, ctx)
    await _render_pack(callback, ctx, session, callback_data.pk)
    await callback.answer(note)


@router.callback_query(EmojiCb.filter(F.action == "pack_delete"))
async def cb_pack_delete(callback: CallbackQuery, callback_data: EmojiCb, ctx: AppContext,
                         session: AsyncSession) -> None:
    pack = await _pack_of(EmojiRepo(session, ctx.owner_id), callback_data.pk)
    if pack is None:
        await callback.answer("Pack not found.", show_alert=True)
        return
    await show(callback, f"🗑 Remove <b>{html.escape(pack.title)}</b> ({pack.count} emoji) "
               "from your library? You can import it again later.", confirm_pack_delete_kb(pack))
    await callback.answer()


@router.callback_query(EmojiCb.filter(F.action == "pack_delete_go"))
async def cb_pack_delete_go(callback: CallbackQuery, callback_data: EmojiCb, ctx: AppContext,
                            session: AsyncSession) -> None:
    repo = EmojiRepo(session, ctx.owner_id)
    pack = await _pack_of(repo, callback_data.pk)
    if pack is None:
        await callback.answer("Pack not found.", show_alert=True)
        return
    removed = await repo.delete_pack(pack.name)
    await _commit_reload(session, ctx)
    await _render_packs(callback, ctx, session, 0, f"🗑 Removed {removed} emoji.\n\n")
    await callback.answer()


# --- moods and single emoji ----------------------------------------------------

@router.callback_query(EmojiCb.filter(F.action == "moods"))
async def cb_moods(callback: CallbackQuery, callback_data: EmojiCb, ctx: AppContext,
                   state: FSMContext) -> None:
    await state.clear()
    moods = ctx.library.palette.mood_counts()
    icons: dict[str, str] = {}
    if ctx.ui.dm_supported:
        for mood, _ in moods:
            found = ctx.library.palette.candidates(mood)
            if found:
                icons[mood] = found[0].custom_emoji_id
    await show(callback, f"🏷 <b>Moods</b> ({len(moods)})\nTap one to see its emoji.",
               moods_kb(moods, callback_data.page, icons))
    await callback.answer()


@router.callback_query(EmojiCb.filter(F.action == "mood"))
async def cb_mood(callback: CallbackQuery, callback_data: EmojiCb, ctx: AppContext,
                  session: AsyncSession) -> None:
    moods = ctx.library.palette.mood_counts()
    if not 0 <= callback_data.value < len(moods):
        await callback.answer("Mood list changed; open it again.", show_alert=True)
        return
    mood, _ = moods[callback_data.value]
    ids = [e.custom_emoji_id for e in ctx.library.palette.candidates(mood)]
    found = await EmojiRepo(session, ctx.owner_id).by_custom_ids(ids)
    items = [found[i] for i in ids if i in found]
    text = (f"🏷 <b>{html.escape(mood)}</b>: {len(items)} emoji\n"
            f"Use it in posts as <code>{{emoji:{html.escape(mood)}}}</code>\n\n"
            f"{_sample_line(items, ctx.ui.dm_supported)}")
    await show(callback, text, mood_items_kb(items, callback_data.value, callback_data.page,
                                             ctx.ui.dm_supported))
    await callback.answer()


async def _item_card(target: Message | CallbackQuery, item: EmojiLibraryItem,
                     ctx: AppContext, prefix: str = "") -> None:
    auto = sorted(ctx.library.palette.auto_tags(item.fallback) - set(item.tags))
    shown = (tg_emoji(item.custom_emoji_id, item.fallback) if ctx.ui.dm_supported
             else html.escape(item.fallback))
    text = (f"{prefix}{shown}  <b>#{item.id}</b>\n"
            f"Pack: {html.escape(item.pack_title or item.pack_name or 'added by hand')}\n"
            f"Kind: {item.kind}{'' if item.is_active else ' · ⏸ disabled'}\n"
            f"Your tags: {html.escape(', '.join(item.tags) or 'none')}\n"
            f"Automatic moods: {html.escape(', '.join(auto) or 'none')}")
    await show(target, text, item_kb(item))


@router.callback_query(EmojiCb.filter(F.action == "item"))
async def cb_item(callback: CallbackQuery, callback_data: EmojiCb, ctx: AppContext,
                  session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    item = await EmojiRepo(session, ctx.owner_id).get(callback_data.pk)
    if item is None:
        await callback.answer("That emoji was removed.", show_alert=True)
        return
    await _item_card(callback, item, ctx)
    await callback.answer()


@router.callback_query(EmojiCb.filter(F.action == "tag_add"))
async def cb_tag_add(callback: CallbackQuery, callback_data: EmojiCb, state: FSMContext) -> None:
    await state.set_state(EmojiStates.waiting_tag)
    await state.update_data(item=callback_data.pk)
    await show(callback, "🏷 Send a tag (mood or topic), e.g. <code>fire</code>, "
               "<code>money</code>, <code>snoop</code>.", cancel_kb())
    await callback.answer()


@router.message(EmojiStates.waiting_tag, F.text)
async def msg_tag(message: Message, ctx: AppContext, session: AsyncSession,
                  state: FSMContext) -> None:
    assert message.text is not None
    tag = normalize_tag(message.text)
    data = await state.get_data()
    item = await EmojiRepo(session, ctx.owner_id).get(int(data.get("item", 0)))
    if item is None:
        await state.clear()
        return
    if not tag:
        await message.answer("Use letters, numbers or _ only.", reply_markup=cancel_kb())
        return
    if len(item.tags) >= MAX_TAGS:
        await message.answer(f"An emoji can have at most {MAX_TAGS} tags.")
        return
    item.tags = sorted({*item.tags, tag})
    await state.clear()
    await _commit_reload(session, ctx)
    await _item_card(message, item, ctx, f"✅ Tagged <b>{html.escape(tag)}</b>\n\n")


@router.callback_query(EmojiCb.filter(F.action.in_({"tag_rm", "item_delete"})))
async def cb_item_change(callback: CallbackQuery, callback_data: EmojiCb, ctx: AppContext,
                         session: AsyncSession) -> None:
    repo = EmojiRepo(session, ctx.owner_id)
    item = await repo.get(callback_data.pk)
    if item is None:
        await callback.answer("That emoji was removed.", show_alert=True)
        return
    if callback_data.action == "item_delete":
        await repo.delete(item)
        await _commit_reload(session, ctx)
        await callback.answer("Deleted")
        await show(callback, "🗑 Emoji removed from the library.\n\n" +
                   await _menu_text(session, ctx), emoji_menu_kb())
        return
    if 0 <= callback_data.value < len(item.tags):
        item.tags = [t for i, t in enumerate(item.tags) if i != callback_data.value]
        await _commit_reload(session, ctx)
    await _item_card(callback, item, ctx)
    await callback.answer()


# --- import ------------------------------------------------------------------

async def _do_import(message: Message, bot: Bot, ctx: AppContext, session: AsyncSession,
                     state: FSMContext, ref: str) -> None:
    try:
        result = await import_pack(bot, session, ctx.owner_id, ref)
    except EmojiImportError as exc:
        await state.set_state(EmojiStates.waiting_pack)
        await message.answer(f"⚠️ {html.escape(str(exc))}", reply_markup=cancel_kb())
        return
    await state.clear()
    await _commit_reload(session, ctx)
    static = (f"\n(Skipped {result.skipped_static} static emoji; only animated ones are kept.)"
              if result.skipped_static else "")
    await message.answer(
        f"✅ <b>{html.escape(result.pack_title)}</b>: {result.added} new, "
        f"{result.updated} updated.{static}", reply_markup=emoji_menu_kb())


@router.message(Command("emojipack"))
async def cmd_emojipack(message: Message, command: CommandObject, bot: Bot, ctx: AppContext,
                        session: AsyncSession, state: FSMContext) -> None:
    if command.args:
        await _do_import(message, bot, ctx, session, state, command.args)
        return
    await state.set_state(EmojiStates.waiting_pack)
    await message.answer("📦 Send an emoji pack link, e.g. "
                         "<code>https://t.me/addemoji/DogsEmoji</code>", reply_markup=cancel_kb())


@router.callback_query(EmojiCb.filter(F.action == "import"))
async def cb_import(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EmojiStates.waiting_pack)
    await show(callback, "📦 Send an emoji pack link, e.g. "
               "<code>https://t.me/addemoji/DogsEmoji</code>", cancel_kb())
    await callback.answer()


@router.message(EmojiStates.waiting_pack, F.text)
async def msg_pack(message: Message, bot: Bot, ctx: AppContext, session: AsyncSession,
                   state: FSMContext) -> None:
    assert message.text is not None
    await _do_import(message, bot, ctx, session, state, message.text)


@router.callback_query(EmojiCb.filter(F.action == "starter"))
async def cb_starter(callback: CallbackQuery, bot: Bot, ctx: AppContext) -> None:
    await callback.answer("Importing… this takes a few seconds")
    total, failed = await import_starter_packs(bot, ctx)
    note = f"\n⚠️ Couldn't load: {html.escape(', '.join(failed))}" if failed else ""
    await show(callback, f"📥 Starter packs refreshed: {total} emoji.{note}", emoji_menu_kb())


@router.message(Command("addemoji"))
async def cmd_addemoji(message: Message, command: CommandObject, state: FSMContext) -> None:
    mood = normalize_tag(command.args or "")
    if not mood:
        await message.answer("Usage: <code>/addemoji mood</code>, e.g. <code>/addemoji fire</code>"
                             ", then send a message with your animated emoji.")
        return
    await state.set_state(EmojiStates.waiting_custom)
    await state.update_data(mood=mood)
    await message.answer(f"Now send a message with the custom emoji to tag as "
                         f"<b>{html.escape(mood)}</b>.", reply_markup=cancel_kb())


@router.message(EmojiStates.waiting_custom)
async def msg_custom(message: Message, bot: Bot, ctx: AppContext, session: AsyncSession,
                     state: FSMContext) -> None:
    mood = str((await state.get_data()).get("mood", "")) or None
    try:
        new, tagged = await add_from_message(bot, session, ctx.owner_id, message, mood)
    except EmojiImportError as exc:
        await message.answer(f"⚠️ {html.escape(str(exc))}", reply_markup=cancel_kb())
        return
    await state.clear()
    await _commit_reload(session, ctx)
    await message.answer(f"✅ {tagged} emoji tagged <b>{html.escape(mood or '')}</b> "
                         f"({new} new in the library).", reply_markup=emoji_menu_kb())
