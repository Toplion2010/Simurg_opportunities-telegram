"""Drive the registered web sources and emit pipeline payloads.

Mirrors src/collector/fetcher.py (the Telegram one) in shape and in its safety
property: a source's items are only ever considered "seen" once their rows
exist, so a mid-run failure re-fetches rather than silently skipping.

There is no cursor arithmetic here. "What have I already ingested" is answered
by RawMessageRepository.existing_external_ids against the rows themselves,
which cannot drift out of sync with reality the way a separately-stored seen
set can.

The scrapers are synchronous (httpx.Client). That is deliberate: this runs as a
short-lived batch job with nothing else on the loop, and a sync client keeps
the per-request pacing in http.Fetcher trivially correct.
"""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.collector.web.filters import admits
from src.collector.web.http import Fetcher
from src.collector.web.registry import enabled_sources, get_source_class
from src.collector.web.to_dto import build_dto
from src.core.logging import get_logger
from src.db.models.source_channel import KIND_WEB, SourceChannel
from src.db.repositories.raw_message import RawMessageRepository
from src.db.repositories.source_channel import SourceChannelRepository

logger = get_logger(__name__)


async def fetch_web_items(
    settings,
    session: AsyncSession,
    only_source: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return payloads ready for processor.worker.process_payloads.

    ``only_source`` and ``limit`` back the workflow's manual-dispatch inputs,
    for testing one scraper without waiting for the daily run.
    """
    per_source_cap = limit or settings.WEB_MAX_ITEMS_PER_RUN

    source_repo = SourceChannelRepository(session)
    raw_repo = RawMessageRepository(session)
    rows = {
        row.identifier: row
        for row in await source_repo.list(kind=KIND_WEB, active=True)
        if row.identifier
    }

    payloads: list[dict[str, Any]] = []
    for key, config in enabled_sources().items():
        if only_source and key != only_source:
            continue

        row = rows.get(key)
        if row is None:
            # Not seeded, or deactivated by an admin. Not an error — it is how
            # a source is turned off without a deploy.
            logger.info("web_source_not_active", source=key)
            continue

        payloads.extend(
            await _collect_one(settings, raw_repo, row, key, config, per_source_cap)
        )

    return payloads


async def _collect_one(
    settings,
    raw_repo: RawMessageRepository,
    row: SourceChannel,
    key: str,
    config: dict,
    cap: int,
) -> list[dict[str, Any]]:
    fetcher = Fetcher(
        user_agent=settings.WEB_USER_AGENT,
        timeout=settings.WEB_REQUEST_TIMEOUT_SECONDS,
        retries=settings.WEB_REQUEST_RETRIES,
        sleep_seconds=settings.WEB_FETCH_SLEEP_SECONDS,
    )
    try:
        source_cls = get_source_class(config["module"])
        source = source_cls(fetcher)

        candidates = source.discover()
        if not candidates:
            logger.warning("web_discover_empty", source=key)
            return []

        known = await raw_repo.existing_external_ids(row.id, candidates)
        fresh = [item_id for item_id in candidates if item_id not in known][:cap]
        logger.info(
            "web_candidates",
            source=key,
            discovered=len(candidates),
            already_seen=len(known),
            fetching=len(fresh),
        )
        if not fresh:
            return []

        items = source.fetch(fresh)
    except Exception:
        # A source that breaks entirely must not cost the rest of the run.
        logger.exception("web_source_failed", source=key)
        return []
    finally:
        fetcher.close()

    payloads: list[dict[str, Any]] = []
    rejected = 0
    now = datetime.now(tz=timezone.utc).isoformat()
    for item in items:
        admitted, reason = admits(item, small_fee_usd=settings.WEB_SMALL_FEE_USD)
        dto = build_dto(item)

        if not admitted:
            rejected += 1
            logger.info(
                "web_item_rejected",
                source=key,
                external_id=item.external_id,
                title=item.title,
                reason=reason,
                is_online=item.is_online,
                cost=item.cost_amount,
            )
            # Still emitted, with is_opportunity=False. The pipeline creates the
            # raw_messages row (recording external_id) and no Opportunity — so a
            # rejected listing is remembered as seen instead of being re-fetched
            # every run and permanently eating the per-run cap. The real reason
            # is in web_item_rejected above; the pipeline's own
            # not_an_opportunity_skipped line is just the mechanism.
            dto.is_opportunity = False

        payloads.append(
            {
                "source_identifier": key,
                "external_id": item.external_id,
                "text": None,
                "received_at": now,
                "dto": dto,
                "page_url": item.page_url,
            }
        )

    # before -> after, the same shape the hackathon watcher's filters log, so
    # the yield of a source is readable straight off the run.
    logger.info(
        "web_filtered",
        source=key,
        before=len(items),
        after=len(payloads) - rejected,
        rejected=rejected,
    )
    return payloads
