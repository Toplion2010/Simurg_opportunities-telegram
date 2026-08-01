from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 View Queue"), KeyboardButton(text="🔍 Search")],
            [KeyboardButton(text="📊 Stats")],
        ],
        resize_keyboard=True,
        persistent=True,
    )
