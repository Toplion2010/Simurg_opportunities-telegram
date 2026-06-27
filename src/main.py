import asyncio
import functools

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.bot.bootstrap import build_dispatcher
from src.core.config import Settings
from src.core.logging import get_logger, setup_logging
from src.core.redis_client import init_redis
from src.db.base import create_engine
from src.db.session import create_session_factory
from src.processor.worker import PipelineFactory, build_pipeline, process_batch
from src.publisher.scheduler import publish_scheduled

logger = get_logger(__name__)


async def main() -> None:
    settings = Settings()
    setup_logging(settings.ENVIRONMENT)

    logger.info("starting_simurg", environment=settings.ENVIRONMENT)

    redis = await init_redis(settings)
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    factory: PipelineFactory = build_pipeline(settings, redis, session_factory)

    bot = Bot(token=settings.BOT_TOKEN)
    dp = build_dispatcher(settings, session_factory, bot)

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        functools.partial(process_batch, factory),
        trigger="interval",
        seconds=settings.PROCESSOR_INTERVAL_SECONDS,
        id="process_batch",
        max_instances=1,
        misfire_grace_time=30,
    )
    scheduler.add_job(
        functools.partial(publish_scheduled, settings, session_factory, bot),
        trigger="interval",
        seconds=settings.PUBLISHER_POLL_SECONDS,
        id="publish_scheduled",
        max_instances=1,
        misfire_grace_time=30,
    )
    scheduler.start()
    logger.info("scheduler_started")

    coroutines = [
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
    ]

    # Telethon userbot — optional, skipped if session file not yet created
    userbot = None
    try:
        from src.collector.userbot import start_userbot
        userbot = await start_userbot(settings, redis, session_factory)
        coroutines.append(userbot.run_until_disconnected())
        logger.info("userbot_started")
    except Exception as e:
        logger.warning(
            "userbot_skipped",
            reason=str(e),
            hint="Run auth_telethon.py to authorize Telethon session",
        )

    logger.info("all_services_started")
    try:
        await asyncio.gather(*coroutines)
    except Exception:
        logger.exception("fatal_error")
        raise
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await engine.dispose()
        logger.info("shutdown_complete")


if __name__ == "__main__":
    asyncio.run(main())
