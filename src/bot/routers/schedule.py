from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.callbacks.data import OpportunityAction
from src.bot.keyboards.edit import back_to_item_keyboard
from src.bot.states.forms import ScheduleForm
from src.core.enums import OpportunityStatus
from src.db.repositories.opportunity import OpportunityRepository

router = Router(name="schedule")

_DT_FORMAT = "%Y-%m-%d %H:%M"


@router.callback_query(OpportunityAction.filter(F.action == "schedule"))
async def start_schedule(
    call: CallbackQuery,
    callback_data: OpportunityAction,
    state: FSMContext,
) -> None:
    await state.set_state(ScheduleForm.waiting_datetime)
    await state.update_data(opp_id=callback_data.opp_id)
    await call.message.edit_text(
        "Enter scheduled publication time (UTC):\n\n"
        "Format: <code>YYYY-MM-DD HH:MM</code>\n"
        "Example: <code>2025-06-15 09:00</code>",
        parse_mode="HTML",
        reply_markup=back_to_item_keyboard(callback_data.opp_id),
    )
    await call.answer()


@router.message(ScheduleForm.waiting_datetime)
async def receive_datetime(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    data = await state.get_data()
    opp_id: int = data["opp_id"]
    text = (message.text or "").strip()

    try:
        dt = datetime.strptime(text, _DT_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        await message.answer(
            f"❌ Invalid format. Please use: <code>{_DT_FORMAT}</code>",
            parse_mode="HTML",
        )
        return

    if dt <= datetime.now(tz=timezone.utc):
        await message.answer("❌ Scheduled time must be in the future.")
        return

    repo = OpportunityRepository(session)
    opp = await repo.get(opp_id)
    if not opp:
        await state.clear()
        await message.answer("Opportunity not found.")
        return

    opp.scheduled_at = dt
    opp.status = OpportunityStatus.approved
    await session.commit()
    await state.clear()

    await message.answer(
        f"✅ Scheduled for <b>{dt.strftime(_DT_FORMAT)} UTC</b>",
        parse_mode="HTML",
        reply_markup=back_to_item_keyboard(opp_id),
    )
