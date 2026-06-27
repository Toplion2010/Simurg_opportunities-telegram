from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from src.bot.keyboards.main_menu import main_menu_keyboard

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 Welcome to Simurg Opportunities Admin Panel.\n\n"
        "Use the menu below to manage opportunities.",
        reply_markup=main_menu_keyboard(),
    )
