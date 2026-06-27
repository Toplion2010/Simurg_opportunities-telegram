from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.callbacks.data import FieldSelect, OpportunityAction

EDITABLE_FIELDS: list[tuple[str, str]] = [
    ("title", "Title"),
    ("category", "Category"),
    ("deadline", "Deadline"),
    ("eligibility", "Eligibility"),
    ("location", "Location"),
    ("cost", "Funding"),
    ("organizer", "Organizer"),
    ("duration", "Duration"),
    ("rewards", "Rewards"),
    ("apply_link", "Apply Link"),
    ("description", "Description"),
]


def field_select_keyboard(opp_id: int) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for i, (field_key, label) in enumerate(EDITABLE_FIELDS):
        row.append(
            InlineKeyboardButton(
                text=label,
                callback_data=FieldSelect(opp_id=opp_id, field=field_key).pack(),
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([
        InlineKeyboardButton(
            text="🔙 Back",
            callback_data=OpportunityAction(opp_id=opp_id, action="view").pack(),
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_item_keyboard(opp_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="🔙 Back to item",
                callback_data=OpportunityAction(opp_id=opp_id, action="view").pack(),
            )
        ]]
    )
