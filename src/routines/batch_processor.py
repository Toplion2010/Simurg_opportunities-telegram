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
import os
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

# Upper bound on the drain, not a fixed duration: the drain normally returns as
# soon as Telegram reports an empty queue, which is typically within a second or
# two. This only stops a pathological backlog from running the job forever.
APPROVAL_WINDOW_SECONDS = int(os.environ.get("SIMURG_APPROVAL_WINDOW_SECONDS") or 120)
# Long-poll seconds per getUpdates call. Keep it short: with the deterministic
# drain there is nothing to gain from holding the connection open, and a short
# timeout makes the "queue is empty, stop now" decision quick.
_GET_UPDATES_TIMEOUT = 3
# Telegram's per-call maximum.
_GET_UPDATES_LIMIT = 100


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
        # Skipped in the scheduled workflow: the dedicated drain job runs every
        # 10 minutes and is the sole getUpdates consumer. Two pollers would race
        # for the same updates and get 409 Conflict from Telegram.
        if os.environ.get("SIMURG_SKIP_DRAIN", "").lower() in ("1", "true", "yes"):
            logger.info("drain_skipped", reason="SIMURG_SKIP_DRAIN")
        else:
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
    """Apply every admin button press waiting in Telegram's update queue.

    Deliberately does NOT use ``dp.start_polling()``. That advances the Telegram
    ``offset`` as soon as updates are *fetched* while running each handler as a
    detached ``asyncio`` task, so closing the window killed handlers whose updates
    Telegram already considered delivered — the tap was gone for good, and it
    logged nothing because the handlers only log after their commit. That is the
    bug that made approvals silently vanish for days.

    Here the offset is only advanced past an update once its handler has actually
    finished, and the advanced offset isn't sent to Telegram until the next
    ``getUpdates`` call — so an interrupted run leaves the tap queued for the next
    one instead of destroying it. Returns as soon as the queue is empty.
    """
    from aiogram.methods import GetUpdates, GetWebhookInfo

    # A webhook and getUpdates are mutually exclusive: with a webhook set, every
    # getUpdates call 409s. When the Koyeb bot is deployed it owns delivery, and
    # this job's only remaining duty is publishing. Detecting that here (rather
    # than hard-wiring drain.yml to publish-only) means the switch happens
    # automatically in BOTH directions -- dropping the webhook restores polling
    # with no workflow edit, so a stale webhook can never silently swallow taps.
    # getWebhookInfo is a genuine read: unlike getUpdates it confirms nothing.
    try:
        info = await bot(GetWebhookInfo())
    except Exception:
        logger.warning("webhook_info_failed", hint="assuming polling mode")
    else:
        if info.url:
            logger.info(
                "drain_skipped_webhook_active",
                url_host=info.url.split("/")[2] if "//" in info.url else "?",
                pending=info.pending_update_count,
                hint="the webhook bot applies taps in real time; this job only publishes",
            )
            return

    dp = build_dispatcher(settings, session_factory, bot)
    allowed = dp.resolve_used_update_types()
    deadline = time.monotonic() + APPROVAL_WINDOW_SECONDS

    offset: int | None = None
    handled = 0

    while True:
        if time.monotonic() >= deadline:
            logger.warning("drain_deadline_reached", handled=handled)
            break
        try:
            updates = await bot(
                GetUpdates(
                    offset=offset,
                    limit=_GET_UPDATES_LIMIT,
                    timeout=_GET_UPDATES_TIMEOUT,
                    allowed_updates=allowed,
                )
            )
        except Exception:
            logger.exception("get_updates_failed", handled=handled)
            break

        if not updates:
            break

        for update in updates:
            try:
                await dp.feed_update(bot, update)
            except Exception:
                # Skip past a poison update rather than letting it wedge the
                # queue forever — every later tap sits behind this offset.
                logger.exception("admin_update_handler_failed", update_id=update.update_id)
            offset = update.update_id + 1
            handled += 1

    if handled:
        # Flush the final offset so the taps just applied aren't replayed next run.
        try:
            await bot(GetUpdates(offset=offset, limit=1, timeout=0, allowed_updates=allowed))
        except Exception:
            logger.warning("final_offset_flush_failed", offset=offset)

    logger.info("admin_updates_drained", handled=handled)


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
