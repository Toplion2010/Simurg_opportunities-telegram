"""
Local-testing helper: run just the "apply approvals + publish" half of
batch_processor.py, skipping the Telethon fetch entirely.

Useful when you want to tap Approve/Reject in Telegram and see it take
effect without waiting for a full collection run (which, on a network with
poor Telegram connectivity, can take a very long time).

Usage:
    python -m scripts.drain_and_publish
"""
import asyncio

from aiogram import Bot

from src.core.config import Settings
from src.core.logging import get_logger, setup_logging
from src.db.base import create_engine
from src.db.session import create_session_factory
from src.publisher.scheduler import publish_scheduled
from src.routines.batch_processor import _drain_admin_updates

logger = get_logger(__name__)


async def run() -> None:
    settings = Settings()
    setup_logging(settings.ENVIRONMENT)

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    bot = Bot(token=settings.BOT_TOKEN)

    try:
        logger.info("draining_admin_updates")
        await _drain_admin_updates(settings, session_factory, bot)

        logger.info("publishing_due")
        await publish_scheduled(settings, session_factory, bot)
    finally:
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
