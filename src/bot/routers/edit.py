from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.callbacks.data import AudienceChoice, FieldSelect, OpportunityAction
from src.bot.keyboards.edit import (
    audience_choice_keyboard,
    back_to_item_keyboard,
    field_select_keyboard,
)
from src.bot.states.forms import EditForm
from src.core.enums import Audience, Category
from src.db.repositories.opportunity import OpportunityRepository

router = Router(name="edit")

_FIELD_LABELS = {
    "title": "Title",
    "category": "Category",
    "audience": "Audience",
    "deadline": "Deadline",
    "eligibility": "Eligibility",
    "location": "Location",
    "cost": "Funding",
    "organizer": "Organizer",
    "duration": "Duration",
    "rewards": "Rewards",
    "apply_link": "Apply Link",
    "description": "Description",
}


@router.callback_query(OpportunityAction.filter(F.action == "edit"))
async def start_edit(
    call: CallbackQuery,
    callback_data: OpportunityAction,
    state: FSMContext,
) -> None:
    await state.set_state(EditForm.choose_field)
    await state.update_data(opp_id=callback_data.opp_id)
    await call.message.edit_text(
        "Choose a field to edit:",
        reply_markup=field_select_keyboard(callback_data.opp_id),
    )
    await call.answer()


@router.callback_query(FieldSelect.filter(), EditForm.choose_field)
async def choose_field(
    call: CallbackQuery,
    callback_data: FieldSelect,
    state: FSMContext,
) -> None:
    # Audience is a fixed 3-value enum — pick it from buttons, no free-text state.
    if callback_data.field == "audience":
        await call.message.edit_text(
            "Choose the target <b>Audience</b>:",
            parse_mode="HTML",
            reply_markup=audience_choice_keyboard(callback_data.opp_id),
        )
        await call.answer()
        return

    await state.set_state(EditForm.waiting_value)
    await state.update_data(opp_id=callback_data.opp_id, field=callback_data.field)
    label = _FIELD_LABELS.get(callback_data.field, callback_data.field)

    hints = ""
    if callback_data.field == "category":
        cats = ", ".join(c.value for c in Category)
        hints = f"\n\nValid values: {cats}"

    await call.message.edit_text(
        f"Enter new value for <b>{label}</b>:{hints}",
        parse_mode="HTML",
        reply_markup=back_to_item_keyboard(callback_data.opp_id),
    )
    await call.answer()


@router.message(EditForm.waiting_value)
async def receive_new_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    data = await state.get_data()
    opp_id: int = data["opp_id"]
    field: str = data["field"]
    new_value = message.text or ""

    repo = OpportunityRepository(session)
    opp = await repo.get(opp_id)
    if not opp:
        await state.clear()
        await message.answer("Opportunity not found.")
        return

    if field == "category":
        try:
            setattr(opp, field, Category(new_value))
        except ValueError:
            await message.answer(
                f"Invalid category. Valid values: {', '.join(c.value for c in Category)}"
            )
            return
    else:
        setattr(opp, field, new_value.strip())

    await session.commit()
    await state.clear()

    label = _FIELD_LABELS.get(field, field)
    await message.answer(
        f"✅ <b>{label}</b> updated successfully.",
        parse_mode="HTML",
        reply_markup=back_to_item_keyboard(opp_id),
    )


@router.callback_query(AudienceChoice.filter())
async def set_audience(
    call: CallbackQuery,
    callback_data: AudienceChoice,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    repo = OpportunityRepository(session)
    opp = await repo.get(callback_data.opp_id)
    if not opp:
        await state.clear()
        await call.answer("Not found.", show_alert=True)
        return

    # Every button value is a valid Audience member by construction (no 'none' button),
    # so there is no invalid-value case to guard against here.
    opp.audience = Audience(callback_data.value)
    await session.commit()
    await state.clear()
    await call.message.edit_text(
        "✅ <b>Audience</b> updated successfully.",
        parse_mode="HTML",
        reply_markup=back_to_item_keyboard(callback_data.opp_id),
    )
    await call.answer()
