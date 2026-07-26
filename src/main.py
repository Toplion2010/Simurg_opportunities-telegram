import asyncio
import functools

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.bot.bootstrap import build_dispatcher
from src.core.config import Settings
from src.core.logging import get_logger, setup_logging
from src.core.notify import notify_admins
from src.core.redis_client import init_redis
from src.db.base import create_engine
from src.db.session import create_session_factory
from src.processor.worker import PipelineFactory, build_pipeline, process_batch
from src.publisher.scheduler import publish_scheduled

logger = get_logger(__name__)


async def run_async() -> None:
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
        functools.partial(process_batch, factory, bot=bot, admin_ids=settings.ADMIN_IDS),
        trigger=CronTrigger(hour=settings.PROCESSOR_CRON_HOURS, minute=0),
        id="process_batch",
        max_instances=1,
        # Wide grace window: unlike the old 30s interval (where a missed tick was
        # free), missing one of only 5 daily fires means a ~4h delay unless a
        # restart/redeploy near the scheduled minute can still catch up.
        misfire_grace_time=1800,
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

    # Telethon userbot — optional, skipped if no API id configured. Runs as its own
    # supervised task, independent of dp.start_polling() below, so a dead user session
    # never takes down the admin bot or scheduled publishing with it.
    userbot_task: asyncio.Task | None = None
    if settings.TELETHON_API_ID:
        userbot_task = asyncio.create_task(
            _run_userbot_supervised(settings, redis, session_factory, bot)
        )
    else:
        logger.info("userbot_disabled", hint="Set TELETHON_API_ID to enable message collection")

    logger.info("all_services_started")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception:
        logger.exception("fatal_error")
        raise
    finally:
        if userbot_task is not None:
            userbot_task.cancel()
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await engine.dispose()
        logger.info("shutdown_complete")


# Reconnect backoff for the collector. A transient network blip (wifi drop, laptop
# sleep) used to kill collection permanently — the process stayed alive polling
# Telegram for admin commands, so nothing external noticed the userbot was gone.
_USERBOT_MIN_BACKOFF = 10
_USERBOT_MAX_BACKOFF = 300
_USERBOT_ALERT_AFTER = 3


async def _run_userbot_supervised(
    settings, redis, session_factory, bot: Bot
) -> None:
    """Keep the collector connected, reconnecting with backoff, and tell the admins
    when collection is actually down rather than failing silently."""
    from src.collector.userbot import start_userbot

    backoff = _USERBOT_MIN_BACKOFF
    failures = 0
    outage_alerted = False

    while True:
        client = None
        try:
            client = await start_userbot(settings, redis, session_factory)
            logger.info("userbot_started")

            if outage_alerted:
                await notify_admins(
                    bot,
                    settings.ADMIN_IDS,
                    "✅ Message collection recovered — the userbot is connected again.",
                )
                outage_alerted = False
            failures = 0
            backoff = _USERBOT_MIN_BACKOFF

            await client.run_until_disconnected()
            failures += 1
            logger.warning("userbot_disconnected", hint="reconnecting")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            failures += 1
            logger.error(
                "userbot_connection_failed",
                error=str(e),
                consecutive_failures=failures,
            )
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    logger.debug("userbot_disconnect_failed")

        if failures >= _USERBOT_ALERT_AFTER and not outage_alerted:
            await notify_admins(
                bot,
                settings.ADMIN_IDS,
                f"⚠️ Message collection is DOWN — {failures} failed reconnect "
                f"attempts. New posts are not being collected.\n\n"
                f"Still retrying every {_USERBOT_MAX_BACKOFF // 60} min. If this persists, "
                f"the Telegram session may need re-authorizing (`python auth_telethon.py`).",
            )
            outage_alerted = True

        logger.info("userbot_reconnect_scheduled", seconds=backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, _USERBOT_MAX_BACKOFF)


def main() -> None:
    asyncio.run(run_async())


if __name__ == "__main__":
    main()
