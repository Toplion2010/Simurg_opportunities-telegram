from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.callbacks.data import OpportunityAction, QueuePage


def opportunity_actions_keyboard(opp_id: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Approve",
                    callback_data=OpportunityAction(opp_id=opp_id, action="approve").pack(),
                ),
                InlineKeyboardButton(
                    text="❌ Reject",
                    callback_data=OpportunityAction(opp_id=opp_id, action="reject").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Edit",
                    callback_data=OpportunityAction(opp_id=opp_id, action="edit").pack(),
                ),
                InlineKeyboardButton(
                    text="🕐 Schedule",
                    callback_data=OpportunityAction(opp_id=opp_id, action="schedule").pack(),
                ),
                InlineKeyboardButton(
                    text="🏷 Hooks",
                    callback_data=OpportunityAction(opp_id=opp_id, action="hooks").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👁 Preview",
                    callback_data=OpportunityAction(opp_id=opp_id, action="preview").pack(),
                ),
            ],
        ]
    )


def pagination_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    buttons = []
    if page > 0:
        buttons.append(
            InlineKeyboardButton(
                text="⬅️ Prev",
                callback_data=QueuePage(page=page - 1).pack(),
            )
        )
    buttons.append(
        InlineKeyboardButton(
            text=f"📄 {page + 1}/{total_pages}",
            callback_data=QueuePage(page=page).pack(),
        )
    )
    if page < total_pages - 1:
        buttons.append(
            InlineKeyboardButton(
                text="➡️ Next",
                callback_data=QueuePage(page=page + 1).pack(),
            )
        )
    return InlineKeyboardMarkup(inline_keyboard=[buttons])
