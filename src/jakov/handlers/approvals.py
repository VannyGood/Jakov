"""🛂 Approve / Skip / Edit buttons on scheduled runs that need the admin's OK."""

from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from jakov.context import AppContext
from jakov.keyboards.callbacks import ApCb
from jakov.keyboards.common import cancel_kb
from jakov.utils.telegram import show

router = Router(name="approvals")
router.message.filter(F.chat.type == ChatType.PRIVATE)


class ApprovalStates(StatesGroup):
    editing = State()


@router.callback_query(ApCb.filter(F.action == "approve"))
async def cb_approve(callback: CallbackQuery, callback_data: ApCb, ctx: AppContext) -> None:
    assert ctx.scheduler is not None
    await callback.answer("Posting…")
    ok, message = await ctx.scheduler.approve(callback_data.pk)
    await show(callback, f"{'✅' if ok else '❗'} {html.escape(message)}")


@router.callback_query(ApCb.filter(F.action == "skip"))
async def cb_skip(callback: CallbackQuery, callback_data: ApCb, ctx: AppContext) -> None:
    assert ctx.scheduler is not None
    skipped = await ctx.scheduler.skip(callback_data.pk)
    await show(callback, "👉 Skipped. The schedule continues with the next run." if skipped
               else "This request was already handled.")
    await callback.answer()


@router.callback_query(ApCb.filter(F.action == "edit"))
async def cb_edit(callback: CallbackQuery, callback_data: ApCb, state: FSMContext) -> None:
    await state.set_state(ApprovalStates.editing)
    await state.update_data(request=callback_data.pk)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "✏️ Send the corrected text for this run. Formatting and animated emoji are kept. "
            "You'll get a new preview to approve.", reply_markup=cancel_kb())


@router.message(ApprovalStates.editing, F.text | F.caption)
async def msg_edit(message: Message, ctx: AppContext, state: FSMContext) -> None:
    assert ctx.scheduler is not None
    request_id = int((await state.get_data()).get("request", 0))
    error = await ctx.scheduler.update_approval_text(request_id, message.html_text)
    if error:
        await message.answer(f"❗ {html.escape(error)}", reply_markup=cancel_kb())
        return
    await state.clear()
