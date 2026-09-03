import math

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.callbacks.data import OpportunityAction, QueuePage
from src.bot.keyboards.queue import opportunity_actions_keyboard, pagination_keyboard
from src.core.enums import Audience, OpportunityStatus
from src.core.logging import get_logger
from src.db.models.opportunity import Opportunity
from src.db.repositories.opportunity import OpportunityRepository
from src.publisher.formatter import format_opportunity

logger = get_logger(__name__)

router = Router(name="queue")

PAGE_SIZE = 5

_AUDIENCE_LABELS = {
    Audience.school: "🏫 School",
    Audience.university: "🎓 University",
    Audience.both: "🏫 School + 🎓 University",
}


def _routing_line(opp: Opportunity) -> str:
    return f"📍 {_AUDIENCE_LABELS[opp.audience]}"


def _stars_line(opp: Opportunity) -> str | None:
    # Omitted (not "0 stars") when unrated — NULL relevance is a missing rating,
    # not a low one.
    if opp.relevance is None:
        return None
    # relevance is 0-100 (src/core/scoring.py, coolness + fit); the glyph
    # count stays a readable 5 stars, compressed from the 100-point score,
    # but the number shown is always the honest /100 — only the star GLYPH
    # is compressed. ceil, not round(): round()'s banker's rounding collapses
    # boundary values to the same glyph count; ceil pairs cleanly, 1-20 -> 1.
    filled = min(5, math.ceil(opp.relevance / 20))
    stars = "⭐" * filled + "☆" * (5 - filled)
    reason = f" · {opp.relevance_reason}" if opp.relevance_reason else ""
    return f"{stars} {opp.relevance}/100{reason}"


def _tags_line(opp: Opportunity) -> str:
    cat = opp.category.value if opp.category else "Unknown"
    line = f"🏷 {cat}"
    if opp.min_age is not None and opp.min_age >= 18:
        line += " · 🔞 18+"
    return line


def _source_line(opp: Opportunity) -> str | None:
    if not opp.source_url:
        return None
    return f'🔗 <a href="{opp.source_url}">Original post</a>'


def _meta_lines(opp: Opportunity) -> str:
    """Stars, tags/age, routing and source link — everything but the title."""
    lines = [_stars_line(opp), _tags_line(opp), _routing_line(opp), _source_line(opp)]
    return "\n".join(line for line in lines if line)


def _card_text(opp: Opportunity) -> str:
    title = opp.title or "Untitled"
    lines = [_stars_line(opp), f"📌 <b>{title}</b>", _tags_line(opp), _routing_line(opp)]
    lines.append(f"📅 {opp.deadline or 'Unknown'}")
    lines.append(_source_line(opp))
    return "\n".join(line for line in lines if line)


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
    text = f"[{status_label}] {preview_short}\n\n{_meta_lines(opp)}"
    kb = opportunity_actions_keyboard(opp.id, page)

    if edit:
        await message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=kb)


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
        card = _card_text(opp)
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
    await call.message.answer(text[:4096], parse_mode="HTML")
    await call.answer()


@router.callback_query(OpportunityAction.filter(F.action == "approve"))
async def approve_opportunity(
    call: CallbackQuery,
    callback_data: OpportunityAction,
    session: AsyncSession,
) -> None:
    # Only flip the status here — do NOT call OpportunitySender.publish() (image
    # generation + Playwright render + upload) directly in this handler. This
    # runs inside the scheduled routine's short, cancellable admin-polling
    # window (see batch_processor._drain_admin_updates); a slow publish that's
    # still in flight when that window closes gets forcibly cancelled mid-send
    # with no error surfaced. publish_scheduled() already runs right after that
    # window closes, with no such time limit, and already picks up anything
    # approved — same as the "Schedule" flow in schedule.py.
    repo = OpportunityRepository(session)
    opp = await repo.get(callback_data.opp_id)
    if not opp:
        await call.answer("Not found.", show_alert=True)
        return

    opp.status = OpportunityStatus.approved
    await session.commit()
    logger.info("approval_recorded", opp_id=opp.id, title=opp.title)

    # Everything past this point is cosmetic. A tap made while the batch job was
    # offline arrives hours later, by which time Telegram rejects both calls
    # ("query is too old"); letting that bubble would make a committed approval
    # look like a failure and hide the real state in the logs.
    try:
        await call.answer("✅ Approved — publishing shortly")
        await call.message.edit_text(
            f"✅ Approved: {opp.title or 'Untitled'} — publishing shortly"
        )
    except TelegramBadRequest as e:
        logger.info("stale_callback_ack_skipped", opp_id=opp.id, error=str(e))


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
    logger.info("rejection_recorded", opp_id=opp.id, title=opp.title)

    try:
        await call.answer("❌ Rejected.")
        await call.message.edit_text(f"❌ Rejected: {opp.title or 'Untitled'}")
    except TelegramBadRequest as e:
        logger.info("stale_callback_ack_skipped", opp_id=opp.id, error=str(e))
