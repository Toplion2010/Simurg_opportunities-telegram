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
import json
import sys
import time

from aiogram import Bot

from src.collector.web.filters import admits
from src.collector.web.fetcher import fetch_web_items
from src.collector.web.http import Fetcher
from src.collector.web.registry import WEB_SOURCES, get_source_class
from src.collector.web.to_dto import build_dto
from src.core.config import Settings
from src.core.enums import Audience, OpportunityStatus
from src.core.logging import get_logger, setup_logging
from src.core.notify import notify_admins
from src.db.base import create_engine
from src.db.models.opportunity import Opportunity
from src.db.repositories.opportunity import OpportunityRepository
from src.db.session import create_session_factory
from src.processor.deduplicator import Deduplicator
from src.processor.extractor import FieldExtractor
from src.processor.worker import build_pipeline, process_payloads
from src.publisher.formatter import format_opportunity

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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect the first 10 listings without writing to the database.",
    )
    return parser.parse_args(argv)


def _preview_opportunity(dto, source_url: str, similarity_hash: str) -> Opportunity:
    audience = Audience(dto.audience.value) if dto.audience else Audience.both
    return Opportunity(
        title=dto.title,
        category=dto.category,
        audience=audience,
        deadline=dto.deadline,
        eligibility=dto.eligibility,
        location=dto.location,
        cost=dto.cost,
        organizer=dto.organizer,
        duration=dto.duration,
        rewards=dto.rewards,
        apply_link=dto.apply_link,
        description=dto.description,
        rewritten_text=dto.rewritten_text,
        card_summary=dto.card_summary,
        card_eligibility=dto.card_eligibility,
        card_rewards=dto.card_rewards,
        additional_links=dto.additional_links,
        extra_notes=dto.extra_notes,
        source_excerpt=dto.source_excerpt,
        min_age=dto.min_age,
        relevance=dto.relevance,
        relevance_reason=dto.relevance_reason,
        source_url=source_url,
        similarity_hash=similarity_hash,
        hooks=[],
        status=OpportunityStatus.pending,
    )


async def _run_dry_preview(settings, session, source_key: str) -> int:
    """Read and render ten live items. The session is never flushed or committed."""
    config = WEB_SOURCES.get(source_key)
    if config is None:
        print(f"ERROR: unknown web source: {source_key}")
        return 2

    fetcher = Fetcher(
        user_agent=settings.WEB_USER_AGENT,
        timeout=settings.WEB_REQUEST_TIMEOUT_SECONDS,
        retries=settings.WEB_REQUEST_RETRIES,
        sleep_seconds=max(
            settings.WEB_FETCH_SLEEP_SECONDS,
            float(config.get("min_sleep_seconds", 0.0)),
        ),
    )
    try:
        source = get_source_class(config["module"])(fetcher)
        external_ids = source.discover()[:10]
        items = source.fetch(external_ids)
    finally:
        fetcher.close()

    deduplicator = Deduplicator(None, settings, FieldExtractor(settings))
    opp_repo = OpportunityRepository(session)
    print(
        f"DRY RUN: source={source_key} discovered={len(external_ids)} "
        f"parsed={len(items)} writes=0"
    )

    for index, item in enumerate(items, 1):
        dto = build_dto(item)
        similarity_hash = deduplicator.make_hash(dto)
        duplicate = await opp_repo.find_recent_by_hash(
            similarity_hash, settings.DEDUP_TTL_SECONDS
        )
        dedupe_method = "title + eligible link"
        if duplicate is None and not dto.apply_link and dto.title:
            duplicate = await opp_repo.find_recent_by_title(
                dto.title, settings.DEDUP_TTL_SECONDS
            )
            dedupe_method = "exact title (no eligible link)"

        admitted, admission_reason = admits(
            item, small_fee_usd=settings.WEB_SMALL_FEE_USD
        )
        preview = _preview_opportunity(dto, item.page_url, similarity_hash)
        dedupe_result = (
            {
                "status": "duplicate",
                "opportunity_id": duplicate.id,
                "title": duplicate.title,
                "method": dedupe_method,
            }
            if duplicate is not None
            else {"status": "new", "method": dedupe_method}
        )

        print(f"\n=== ITEM {index}/10: {item.external_id} ===")
        print("STRUCTURED DATA")
        print(json.dumps(dto.model_dump(mode="json"), ensure_ascii=False, indent=2))
        print("OPPORTUNITY TEXT")
        print(item.raw.get("opportunity_text") or "none")
        print("RETAINED LINK PROVENANCE")
        provenance = item.raw.get("link_provenance") or []
        print(
            json.dumps(provenance, ensure_ascii=False, indent=2)
            if provenance
            else "none"
        )
        print("DEDUPE")
        print(json.dumps(dedupe_result, ensure_ascii=False, indent=2))
        print("ADMISSION")
        print(json.dumps({"admitted": admitted, "reason": admission_reason}))
        print("RENDERED TELEGRAM POST")
        print(format_opportunity(preview))

    if len(items) != 10:
        print(f"ERROR: expected 10 parsed items, got {len(items)}")
        return 1
    return 0


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
        dry_run=args.dry_run,
    )

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    bot = None if args.dry_run else Bot(token=settings.BOT_TOKEN)

    try:
        if args.dry_run:
            if not args.source:
                print("ERROR: --dry-run requires --source")
                return 2
            async with session_factory() as session:
                return await _run_dry_preview(settings, session, args.source)

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
        if bot is not None:
            await notify_admins(
                bot,
                settings.ADMIN_IDS,
                f"❌ Web scan FAILED: {type(e).__name__}: {e}",
            )
        return 1
    finally:
        if bot is not None:
            await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
