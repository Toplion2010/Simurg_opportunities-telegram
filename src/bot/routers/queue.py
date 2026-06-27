import math

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.callbacks.data import OpportunityAction, QueuePage
from src.bot.keyboards.queue import opportunity_actions_keyboard, pagination_keyboard
from src.core.config import Settings
from src.core.enums import OpportunityStatus
from src.db.repositories.opportunity import OpportunityRepository
from src.publisher.formatter import format_opportunity
from src.publisher.sender import OpportunitySender

router = Router(name="queue")

PAGE_SIZE = 5


async def _send_opportunity_card(
    message: Message,
    opp_id: int,
    session: AsyncSession,
    page: int = 0,
    edit: bool = False,
) -> None:
    repo = OpportunityRepository(session)
    opp = await repo.get(opp_id)
    if not opp:
        await message.answer("Opportunity not found.")
        return

    preview = format_opportunity(opp)
    preview_short = preview[:1000] + ("..." if len(preview) > 1000 else "")
    status_label = opp.status.value.upper()
    text = f"[{status_label}] {preview_short}"
    kb = opportunity_actions_keyboard(opp.id, page)

    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


@router.message(F.text == "📋 View Queue")
async def view_queue(message: Message, session: AsyncSession) -> None:
    await _show_queue_page(message, session, page=0, edit=False)


@router.callback_query(QueuePage.filter())
async def queue_page(
    call: CallbackQuery,
    callback_data: QueuePage,
    session: AsyncSession,
) -> None:
    await _show_queue_page(call.message, session, page=callback_data.page, edit=True)
    await call.answer()


async def _show_queue_page(
    message: Message,
    session: AsyncSession,
    page: int,
    edit: bool,
) -> None:
    repo = OpportunityRepository(session)
    total = await repo.count_pending()

    if total == 0:
        text = "✅ No opportunities in queue."
        if edit:
            await message.edit_text(text)
        else:
            await message.answer(text)
        return

    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    items = await repo.get_pending(page=page, page_size=PAGE_SIZE)

    for opp in items:
        title = opp.title or "Untitled"
        cat = opp.category.value if opp.category else "Unknown"
        card = f"📌 <b>{title}</b>\n🏷 {cat}\n📅 {opp.deadline or 'Unknown'}"
        kb = opportunity_actions_keyboard(opp.id, page)
        if edit and opp == items[0]:
            await message.edit_text(card, parse_mode="HTML", reply_markup=kb)
        else:
            await message.answer(card, parse_mode="HTML", reply_markup=kb)

    nav_kb = pagination_keyboard(page, total_pages)
    await message.answer(f"Page {page + 1} of {total_pages} ({total} in queue)", reply_markup=nav_kb)


@router.callback_query(OpportunityAction.filter(F.action == "view"))
async def view_opportunity(
    call: CallbackQuery,
    callback_data: OpportunityAction,
    session: AsyncSession,
) -> None:
    await _send_opportunity_card(call.message, callback_data.opp_id, session, edit=True)
    await call.answer()


@router.callback_query(OpportunityAction.filter(F.action == "preview"))
async def preview_opportunity(
    call: CallbackQuery,
    callback_data: OpportunityAction,
    session: AsyncSession,
) -> None:
    repo = OpportunityRepository(session)
    opp = await repo.get(callback_data.opp_id)
    if not opp:
        await call.answer("Not found.", show_alert=True)
        return
    text = format_opportunity(opp)
    await call.message.answer(text[:4096])
    await call.answer()


@router.callback_query(OpportunityAction.filter(F.action == "approve"))
async def approve_opportunity(
    call: CallbackQuery,
    callback_data: OpportunityAction,
    session: AsyncSession,
    bot: Bot,
    settings: Settings,
) -> None:
    repo = OpportunityRepository(session)
    opp = await repo.get(callback_data.opp_id)
    if not opp:
        await call.answer("Not found.", show_alert=True)
        return

    sender = OpportunitySender(settings)
    try:
        await sender.publish(opp, bot)
        await session.commit()
        await call.answer("✅ Published successfully!")
        await call.message.edit_text(f"✅ Published: {opp.title}")
    except Exception as e:
        await call.answer(f"❌ Failed: {e}", show_alert=True)


@router.callback_query(OpportunityAction.filter(F.action == "reject"))
async def reject_opportunity(
    call: CallbackQuery,
    callback_data: OpportunityAction,
    session: AsyncSession,
) -> None:
    repo = OpportunityRepository(session)
    opp = await repo.get(callback_data.opp_id)
    if not opp:
        await call.answer("Not found.", show_alert=True)
        return

    opp.status = OpportunityStatus.rejected
    await session.commit()
    await call.answer("❌ Rejected.")
    await call.message.edit_text(f"❌ Rejected: {opp.title or 'Untitled'}")
