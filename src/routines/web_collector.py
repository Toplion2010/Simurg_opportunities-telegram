"""One-shot scrape of the registered web catalogs (GitHub Actions).

    1. discover candidate items per source
    2. skip what this source already ingested
    3. fetch a capped batch of the rest
    4. apply the admission filter
    5. run them through the extraction pipeline as status=pending

It deliberately does NOT publish. Scraped items land in the admin queue like
everything else, and drain.yml publishes whatever gets approved.

No LLM key is needed on the default path: web sources build their DTOs from
structured fields (see src/collector/web/to_dto.py), so Groq's budget stays
with the Telegram pipeline.

Run with:  python -m src.routines.web_collector [--source NAME] [--limit N]
"""
import argparse
import asyncio
import sys
import time

from aiogram import Bot

from src.collector.web.fetcher import fetch_web_items
from src.core.config import Settings
from src.core.logging import get_logger, setup_logging
from src.core.notify import notify_admins
from src.db.base import create_engine
from src.db.session import create_session_factory
from src.processor.worker import build_pipeline, process_payloads

logger = get_logger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="web_collector")
    parser.add_argument(
        "--source",
        default=None,
        help="Only run this registry key (e.g. extracurricularhub).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Override WEB_MAX_ITEMS_PER_RUN, per source. Use for a backfill.",
    )
    return parser.parse_args(argv)


async def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = Settings()
    setup_logging(settings.ENVIRONMENT)
    started_at = time.monotonic()

    logger.info(
        "web_routine_started",
        environment=settings.ENVIRONMENT,
        source=args.source,
        limit=args.limit,
    )

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    bot = Bot(token=settings.BOT_TOKEN)

    try:
        async with session_factory() as session:
            payloads = await fetch_web_items(
                settings, session, only_source=args.source, limit=args.limit
            )

        if not payloads:
            logger.info("web_routine_complete", fetched=0, created=0)
            return 0

        factory = build_pipeline(settings, None, session_factory)
        # No throttle: this path makes no LLM calls, so the Telegram pipeline's
        # LLM_THROTTLE_SECONDS would only make the job slower for nothing. If
        # WEB_INGEST_USE_LLM is ever turned on, a throttle has to come with it.
        processed, created, errors, failed = await process_payloads(factory, payloads)

        duration = round(time.monotonic() - started_at, 2)
        logger.info(
            "web_routine_complete",
            fetched=len(payloads),
            processed=processed,
            created=created,
            errors=errors,
            failed=len(failed),
            duration_seconds=duration,
        )

        if created or errors:
            await notify_admins(
                bot,
                settings.ADMIN_IDS,
                f"\U0001f310 Web scan: {created} new opportunit"
                f"{'y' if created == 1 else 'ies'} ready for review\n"
                f"({len(payloads)} items fetched"
                + (f", {errors} errors" if errors else "")
                + f", {duration}s)",
            )
        return 0
    except Exception as e:
        logger.exception("web_routine_failed")
        await notify_admins(
            bot,
            settings.ADMIN_IDS,
            f"❌ Web scan FAILED: {type(e).__name__}: {e}",
        )
        return 1
    finally:
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
