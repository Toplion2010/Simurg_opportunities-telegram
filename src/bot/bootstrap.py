from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.middlewares.auth import AdminAuthMiddleware
from src.bot.middlewares.db_session import DbSessionMiddleware
from src.bot.routers import edit, hooks, queue, schedule, search, setup, start, stats
from src.core.config import Settings


def build_dispatcher(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
) -> Dispatcher:
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    dp.update.middleware(AdminAuthMiddleware(settings.ADMIN_IDS))
    dp.update.middleware(DbSessionMiddleware(session_factory))

    dp["settings"] = settings
    dp["bot"] = bot

    dp.include_router(setup.router)
    dp.include_router(start.router)
    dp.include_router(queue.router)
    dp.include_router(edit.router)
    dp.include_router(schedule.router)
    dp.include_router(hooks.router)
    dp.include_router(search.router)
    dp.include_router(stats.router)

    return dp
