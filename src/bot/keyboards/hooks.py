from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.callbacks.data import HookToggle, OpportunityAction
from src.core.enums import HookLabel


def hooks_keyboard(opp_id: int, active_hooks: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for hook in HookLabel:
        is_active = hook.value in active_hooks
        prefix = "✅ " if is_active else "☐ "
        rows.append([
            InlineKeyboardButton(
                text=f"{prefix}{hook.value}",
                callback_data=HookToggle(opp_id=opp_id, hook_key=hook.name).pack(),
            )
        ])

    rows.append([
        InlineKeyboardButton(
            text="🔙 Back",
            callback_data=OpportunityAction(opp_id=opp_id, action="view").pack(),
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
