from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 View Queue"), KeyboardButton(text="🔍 Search")],
        ],
        resize_keyboard=True,
        persistent=True,
    )
