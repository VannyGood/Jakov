"""Wizard steps up to the previews: type, questions, tone, media and URL buttons."""

from __future__ import annotations

import html

from aiogram import Bot, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from jakov.context import AppContext
from jakov.db.base import utcnow
from jakov.db.models import Post
from jakov.db.repositories.posts import PostRepo
from jakov.handlers.post_wizard.common import MAX_BUTTONS, PostWizard, load_post, router
from jakov.handlers.post_wizard.preview import show_previews
from jakov.handlers.views import zone_for
from jakov.keyboards.callbacks import MenuCb, PostCb
from jakov.keyboards.posts import buttons_kb, media_kb, question_kb, tone_kb, type_picker_kb
from jakov.services.drafts import store_moment
from jakov.services.timezones import effective_zone
from jakov.utils.buttons import parse_buttons
from jakov.utils.dates import DateParseError, parse_when
from jakov.utils.telegram import show

TYPE_PROMPT = "✍️ <b>New post</b>\n\nWhat kind of post?"


@router.message(Command("newpost"))
async def cmd_newpost(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.clear()
    await message.answer(TYPE_PROMPT, reply_markup=type_picker_kb(ctx.catalog))


@router.callback_query(MenuCb.filter(F.to == "newpost"))
async def cb_newpost(callback: CallbackQuery, ctx: AppContext, state: FSMContext) -> None:
    await state.clear()
    await show(callback, TYPE_PROMPT, type_picker_kb(ctx.catalog))
    await callback.answer()


@router.callback_query(PostCb.filter(F.action == "type"))
async def cb_type(callback: CallbackQuery, callback_data: PostCb, ctx: AppContext,
                  session: AsyncSession, state: FSMContext) -> None:
    order = ctx.catalog.type_order
    if not 0 <= callback_data.value < len(order):
        await callback.answer("Unknown type", show_alert=True)
        return
    zone, _ = await zone_for(session, ctx, callback.from_user.id)
    post = await PostRepo(session, ctx.owner_id).add(Post(
        created_by=callback.from_user.id, post_type=order[callback_data.value], timezone=zone,
        answers={}, moments={}, buttons=[]))
    await state.set_state(PostWizard.answering)
    await state.set_data({"post": post.id, "q": 0})
    await callback.answer()
    await _ask(callback, post, ctx, 0)


async def _ask(target: Message | CallbackQuery, post: Post, ctx: AppContext, index: int) -> None:
    post_type = ctx.catalog.types[post.post_type]
    question = post_type.questions[index]
    step = f"<i>Step {index + 1} of {len(post_type.questions)}</i>"
    hint = "" if question.required else "\n<i>Optional: tap Skip if it doesn't apply.</i>"
    await show(target, f"{post_type.title}\n{step}\n\n{question.prompt}{hint}",
               question_kb(post, question))


async def _advance(target: Message | CallbackQuery, post: Post, ctx: AppContext,
                   state: FSMContext, index: int) -> None:
    questions = ctx.catalog.types[post.post_type].questions
    if index + 1 < len(questions):
        await state.update_data(q=index + 1)
        await _ask(target, post, ctx, index + 1)
        return
    await state.set_state(None)
    await show(target, f"{ctx.catalog.types[post.post_type].title}\n\n🎭 Pick a tone:",
               tone_kb(post, ctx.catalog))


@router.message(PostWizard.answering, F.text)
async def msg_answer(message: Message, ctx: AppContext, session: AsyncSession,
                     state: FSMContext) -> None:
    assert message.text is not None
    data = await state.get_data()
    post = await PostRepo(session, ctx.owner_id).get(int(data.get("post", 0)))
    if post is None:
        await state.clear()
        await message.answer("This draft no longer exists. Start again with /newpost.")
        return
    index = int(data.get("q", 0))
    question = ctx.catalog.types[post.post_type].questions[index]
    text = message.text.strip()
    if question.kind == "choice":
        await message.answer("Please tap one of the buttons.",
                             reply_markup=question_kb(post, question))
        return
    if len(text) > question.max_len:
        await message.answer(f"⚠️ Please keep it under {question.max_len} characters "
                             f"(yours is {len(text)}).", reply_markup=question_kb(post, question))
        return
    if question.kind == "datetime":
        now_local = utcnow().astimezone(effective_zone(post.timezone, ctx.settings.timezone))
        try:
            moment = parse_when(text, now_local)
        except DateParseError as exc:
            await message.answer(f"⚠️ {html.escape(str(exc))}",
                                 reply_markup=question_kb(post, question))
            return
        store_moment(post, question.key, moment)
    post.answers = {**post.answers, question.key: text}
    await session.flush()
    await _advance(message, post, ctx, state, index)


@router.callback_query(PostCb.filter(F.action.in_({"skip", "choice"})))
async def cb_skip_or_choice(callback: CallbackQuery, callback_data: PostCb, ctx: AppContext,
                            session: AsyncSession, state: FSMContext) -> None:
    post = await load_post(callback, session, ctx, callback_data.post)
    if post is None:
        return
    data = await state.get_data()
    if data.get("post") != post.id:
        await callback.answer("That step is from an older draft.", show_alert=True)
        return
    index = int(data.get("q", 0))
    question = ctx.catalog.types[post.post_type].questions[index]
    if callback_data.action == "skip":
        if question.required:
            await callback.answer("This one is required.", show_alert=True)
            return
        post.answers = {k: v for k, v in post.answers.items() if k != question.key}
        post.moments = {k: v for k, v in post.moments.items() if k != question.key}
    else:
        if question.kind != "choice" or not 0 <= callback_data.value < len(question.options):
            await callback.answer("Not available here.", show_alert=True)
            return
        post.answers = {**post.answers, question.key: question.options[callback_data.value].value}
    await session.flush()
    await callback.answer()
    await _advance(callback, post, ctx, state, index)


@router.callback_query(PostCb.filter(F.action == "tone"))
async def cb_tone(callback: CallbackQuery, callback_data: PostCb, ctx: AppContext,
                  session: AsyncSession, state: FSMContext) -> None:
    post = await load_post(callback, session, ctx, callback_data.post)
    if post is None:
        return
    tones = list(ctx.catalog.tones)
    if not 0 <= callback_data.value < len(tones):
        await callback.answer("Unknown tone", show_alert=True)
        return
    post.tone = tones[callback_data.value]
    await session.flush()
    await state.set_state(PostWizard.waiting_media)
    await state.update_data(post=post.id)
    await callback.answer()
    await show(callback, "📎 <b>Media</b>\n\nSend <b>one photo or video</b> to attach, "
               "or continue with text only.\n<i>With media, the text limit is 1024 characters.</i>",
               media_kb(post))


@router.message(PostWizard.waiting_media)
async def msg_media(message: Message, ctx: AppContext, session: AsyncSession,
                    state: FSMContext) -> None:
    data = await state.get_data()
    post = await PostRepo(session, ctx.owner_id).get(int(data.get("post", 0)))
    if post is None:
        await state.clear()
        return
    if message.photo:
        post.media_kind, post.media_file_id = "photo", message.photo[-1].file_id
    elif message.video:
        post.media_kind, post.media_file_id = "video", message.video.file_id
    else:
        await message.answer("Send a photo or a video, or tap “Text only”.",
                             reply_markup=media_kb(post))
        return
    await session.flush()
    await _ask_buttons(message, post, state)


@router.callback_query(PostCb.filter(F.action == "nomedia"))
async def cb_nomedia(callback: CallbackQuery, callback_data: PostCb, ctx: AppContext,
                     session: AsyncSession, state: FSMContext) -> None:
    post = await load_post(callback, session, ctx, callback_data.post)
    if post is None:
        return
    post.media_kind = post.media_file_id = None
    await session.flush()
    await callback.answer()
    await _ask_buttons(callback, post, state)


async def _ask_buttons(target: Message | CallbackQuery, post: Post, state: FSMContext) -> None:
    await state.set_state(PostWizard.waiting_buttons)
    await state.update_data(post=post.id)
    await show(target,
               "🔗 <b>Link buttons</b> (optional)\n\nSend one button per line, up to "
               f"{MAX_BUTTONS}:\n<code>Join the game - https://t.me/yourgroup</code>\n"
               "<code>Buy now - https://shop.example.com</code>",
               buttons_kb(post))


@router.message(PostWizard.waiting_buttons, F.text)
async def msg_buttons(message: Message, bot: Bot, ctx: AppContext, session: AsyncSession,
                      state: FSMContext) -> None:
    assert message.text is not None
    data = await state.get_data()
    post = await PostRepo(session, ctx.owner_id).get(int(data.get("post", 0)))
    if post is None:
        await state.clear()
        return
    buttons, errors = parse_buttons(message.text, MAX_BUTTONS)
    if errors and not buttons:
        await message.answer("⚠️ " + "\n⚠️ ".join(html.escape(e) for e in errors),
                             reply_markup=buttons_kb(post))
        return
    post.buttons = buttons
    await session.flush()
    if errors:
        await message.answer("ℹ️ " + "\n".join(html.escape(e) for e in errors))
    await show_previews(message, bot, post, ctx, session, state, fresh=True)


@router.callback_query(PostCb.filter(F.action == "nobuttons"))
async def cb_nobuttons(callback: CallbackQuery, callback_data: PostCb, bot: Bot,
                       ctx: AppContext, session: AsyncSession, state: FSMContext) -> None:
    post = await load_post(callback, session, ctx, callback_data.post)
    if post is None:
        return
    post.buttons = []
    await session.flush()
    await callback.answer("Generating…")
    await show_previews(callback, bot, post, ctx, session, state, fresh=True)
