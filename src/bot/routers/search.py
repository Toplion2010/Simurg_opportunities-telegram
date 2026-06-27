from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.keyboards.queue import opportunity_actions_keyboard
from src.bot.states.forms import SearchForm
from src.core.enums import OpportunityStatus
from src.db.repositories.opportunity import OpportunityRepository

router = Router(name="search")


@router.message(F.text == "🔍 Search")
async def start_search(message: Message, state: FSMContext) -> None:
    await state.set_state(SearchForm.waiting_query)
    await message.answer("Enter search query (searches by title):")


@router.message(SearchForm.waiting_query)
async def perform_search(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    query = (message.text or "").strip()
    if not query:
        await message.answer("Please enter a search term.")
        return

    await state.clear()
    repo = OpportunityRepository(session)
    results = await repo.search(query, limit=10)

    if not results:
        await message.answer(f"No results found for: <b>{query}</b>", parse_mode="HTML")
        return

    await message.answer(
        f"Found <b>{len(results)}</b> results for: <b>{query}</b>",
        parse_mode="HTML",
    )
    for opp in results:
        cat = opp.category.value if opp.category else "Unknown"
        status = opp.status.value
        text = (
            f"📌 <b>{opp.title or 'Untitled'}</b>\n"
            f"🏷 {cat} | 📊 {status}\n"
            f"📅 {opp.deadline or 'Unknown'}"
        )
        kb = opportunity_actions_keyboard(opp.id, 0)
        await message.answer(text, parse_mode="HTML", reply_markup=kb)
