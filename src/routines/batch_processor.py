"""One-shot batch run for a scheduled environment (GitHub Actions).

Does in a single short-lived process what the always-on deployment spreads across
a live Telethon listener plus two APScheduler jobs:

    1. fetch each source channel's history since the last run
    2. run it through the extraction pipeline
    3. drain admin button presses queued since the last run
    4. publish anything approved and due
    5. report the result to the admins

Run with:  python -m src.routines.batch_processor
"""
import asyncio
import time

from aiogram import Bot
from telethon import TelegramClient
from telethon.sessions import StringSession

from src.bot.bootstrap import build_dispatcher
from src.collector.fetcher import advance_cursors, compute_safe_cursors, fetch_new_messages
from src.core.config import Settings
from src.core.logging import get_logger, setup_logging
from src.core.notify import notify_admins
from src.db.base import create_engine
from src.db.session import create_session_factory
from src.processor.worker import build_pipeline, process_payloads
from src.publisher.scheduler import publish_scheduled

logger = get_logger(__name__)

# How long to listen for admin button presses. Telegram retains bot updates for
# ~24h, so approvals made while nothing was running arrive as soon as we poll.
APPROVAL_WINDOW_SECONDS = 90


async def run() -> int:
    settings = Settings()
    setup_logging(settings.ENVIRONMENT)
    started_at = time.monotonic()

    logger.info("routine_started", environment=settings.ENVIRONMENT)

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    bot = Bot(token=settings.BOT_TOKEN)

    processed = created = errors = 0
    fetched = 0
    payloads: list[dict] = []

    try:
        # --- 1 & 2: collect and process -------------------------------------
        client = _build_telethon_client(settings)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise RuntimeError(
                    "Telethon session is not authorized. Regenerate "
                    "TELETHON_SESSION_STRING with scripts/export_session_string.py"
                )
            payloads = await fetch_new_messages(client, session_factory)
            fetched = len(payloads)
        finally:
            await client.disconnect()

        if payloads:
            # Oldest first, so a capped run leaves the newest for next time and the
            # per-channel cursor stays contiguous.
            payloads.sort(key=lambda p: (p["channel_id"], p["telegram_msg_id"]))
            if len(payloads) > settings.MAX_MESSAGES_PER_RUN:
                logger.warning(
                    "batch_capped",
                    fetched=len(payloads),
                    cap=settings.MAX_MESSAGES_PER_RUN,
                )
                payloads = payloads[: settings.MAX_MESSAGES_PER_RUN]

            # No Redis: this run owns the messages it just fetched.
            factory = build_pipeline(settings, None, session_factory)
            processed, created, errors, failed = await process_payloads(
                factory, payloads, throttle_seconds=settings.LLM_THROTTLE_SECONDS
            )
            # Only skip messages that actually made it through; a rate-limited one
            # must come back on the next run rather than vanish.
            await advance_cursors(session_factory, compute_safe_cursors(payloads, failed))

        # --- 3: apply approvals made since the last run ----------------------
        await _drain_admin_updates(settings, session_factory, bot)

        # --- 4: publish whatever is approved and due -------------------------
        try:
            await publish_scheduled(settings, session_factory, bot)
        except Exception:
            logger.exception("publish_scheduled_failed")

        # --- 5: report -------------------------------------------------------
        duration = round(time.monotonic() - started_at, 2)
        logger.info(
            "routine_complete",
            fetched=fetched,
            processed=processed,
            created=created,
            errors=errors,
            duration_seconds=duration,
        )
        if created or errors:
            await notify_admins(
                bot,
                settings.ADMIN_IDS,
                f"\U0001f501 Batch run: {created} new opportunit"
                f"{'y' if created == 1 else 'ies'} ready for review\n"
                f"({fetched} messages fetched"
                + (f", {errors} errors" if errors else "")
                + f", {duration}s)",
            )
        return 0
    except Exception as e:
        logger.exception("routine_failed")
        # A failed scheduled run is invisible unless something says so.
        await notify_admins(
            bot,
            settings.ADMIN_IDS,
            f"❌ Batch run FAILED: {type(e).__name__}: {e}",
        )
        return 1
    finally:
        await bot.session.close()
        await engine.dispose()


def _build_telethon_client(settings: Settings) -> TelegramClient:
    if settings.TELETHON_SESSION_STRING:
        session = StringSession(settings.TELETHON_SESSION_STRING)
    else:
        session = f"telethon_session/{settings.TELETHON_SESSION}"
    return TelegramClient(
        session, settings.TELETHON_API_ID, settings.TELETHON_API_HASH
    )


async def _drain_admin_updates(settings, session_factory, bot: Bot) -> None:
    """Poll briefly so approve/reject presses made between runs take effect."""
    dp = build_dispatcher(settings, session_factory, bot)
    polling = asyncio.create_task(
        dp.start_polling(
            bot,
            handle_signals=False,
            allowed_updates=dp.resolve_used_update_types(),
        )
    )
    try:
        await asyncio.wait_for(asyncio.shield(polling), timeout=APPROVAL_WINDOW_SECONDS)
    except asyncio.TimeoutError:
        logger.info("approval_window_elapsed", seconds=APPROVAL_WINDOW_SECONDS)
    except Exception:
        logger.exception("approval_polling_failed")
    finally:
        polling.cancel()
        try:
            await polling
        except (asyncio.CancelledError, Exception):
            pass


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
