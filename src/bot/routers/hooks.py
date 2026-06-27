from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.callbacks.data import HookToggle, OpportunityAction
from src.bot.keyboards.hooks import hooks_keyboard
from src.core.enums import HookLabel
from src.db.repositories.opportunity import OpportunityRepository

router = Router(name="hooks")


@router.callback_query(OpportunityAction.filter(F.action == "hooks"))
async def show_hooks(
    call: CallbackQuery,
    callback_data: OpportunityAction,
    session: AsyncSession,
) -> None:
    repo = OpportunityRepository(session)
    opp = await repo.get(callback_data.opp_id)
    if not opp:
        await call.answer("Not found.", show_alert=True)
        return

    await call.message.edit_text(
        f"Select hooks for: <b>{opp.title or 'Untitled'}</b>",
        parse_mode="HTML",
        reply_markup=hooks_keyboard(opp.id, opp.hooks or []),
    )
    await call.answer()


@router.callback_query(HookToggle.filter())
async def toggle_hook(
    call: CallbackQuery,
    callback_data: HookToggle,
    session: AsyncSession,
) -> None:
    repo = OpportunityRepository(session)
    opp = await repo.get(callback_data.opp_id)
    if not opp:
        await call.answer("Not found.", show_alert=True)
        return

    try:
        hook = HookLabel[callback_data.hook_key]
    except KeyError:
        await call.answer("Invalid hook.", show_alert=True)
        return

    hooks: list[str] = list(opp.hooks or [])
    if hook.value in hooks:
        hooks.remove(hook.value)
    else:
        hooks.append(hook.value)

    opp.hooks = hooks
    await session.commit()

    await call.message.edit_reply_markup(
        reply_markup=hooks_keyboard(opp.id, hooks)
    )
    await call.answer()
