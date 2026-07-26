import time
from datetime import datetime, timezone

import redis.asyncio as aioredis
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.logging import get_logger
from src.core.redis_client import dequeue_batch
from src.db.repositories.opportunity import OpportunityRepository
from src.db.repositories.raw_message import RawMessageRepository
from src.db.repositories.source_channel import SourceChannelRepository
from src.processor.classifier import CategoryClassifier
from src.processor.cleaner import TextCleaner
from src.processor.deduplicator import Deduplicator
from src.processor.extractor import FieldExtractor
from src.processor.pipeline import ProcessingPipeline
from src.processor.vision import ImageReader

logger = get_logger(__name__)


def build_pipeline(
    settings,
    redis: aioredis.Redis,
    session_factory: async_sessionmaker[AsyncSession],
) -> "PipelineFactory":
    return PipelineFactory(settings, redis, session_factory)


class PipelineFactory:
    def __init__(self, settings, redis: aioredis.Redis, session_factory) -> None:
        self._settings = settings
        self._redis = redis
        self._session_factory = session_factory
        self._cleaner = TextCleaner()
        self._extractor = FieldExtractor(settings)
        self._classifier = CategoryClassifier()
        self._deduplicator = Deduplicator(redis, settings, self._extractor)
        self._image_reader = ImageReader(settings)

    def make_pipeline(self, session: AsyncSession) -> ProcessingPipeline:
        return ProcessingPipeline(
            cleaner=self._cleaner,
            extractor=self._extractor,
            classifier=self._classifier,
            deduplicator=self._deduplicator,
            opp_repo=OpportunityRepository(session),
            raw_repo=RawMessageRepository(session),
            image_reader=self._image_reader,
        )


async def process_batch(
    factory: PipelineFactory,
    batch_size: int = 20,
    bot: Bot | None = None,
    admin_ids: list[int] | None = None,
) -> None:
    started_at = time.monotonic()
    drained_count = 0
    created_count = 0
    error_count = 0

    async with factory._session_factory() as session:
        raw_repo = RawMessageRepository(session)
        pipeline = factory.make_pipeline(session)

        while True:
            payloads = await dequeue_batch(factory._redis, batch_size)
            if not payloads:
                break

            logger.info("processing_chunk", count=len(payloads))

            for payload in payloads:
                try:
                    received_at = datetime.fromisoformat(payload["received_at"]).replace(tzinfo=None)
                    source_channel_id = await _resolve_channel_id(
                        session, payload["channel_id"]
                    )
                    raw = await raw_repo.create(
                        source_channel_id=source_channel_id,
                        telegram_msg_id=payload["telegram_msg_id"],
                        text=payload.get("text"),
                        received_at=received_at,
                    )
                    created = await pipeline.run(raw, media_path=payload.get("media_path"))
                    await session.commit()
                    drained_count += 1
                    created_count += len(created)
                except Exception:
                    logger.exception("batch_item_error", payload=payload)
                    await session.rollback()
                    error_count += 1

    duration_seconds = round(time.monotonic() - started_at, 2)
    logger.info(
        "batch_drained",
        drained_count=drained_count,
        created_count=created_count,
        error_count=error_count,
        duration_seconds=duration_seconds,
    )

    if bot is not None and admin_ids:
        await _notify_admins(bot, admin_ids, drained_count, created_count, error_count, duration_seconds)


async def _notify_admins(
    bot: Bot,
    admin_ids: list[int],
    drained_count: int,
    created_count: int,
    error_count: int,
    duration_seconds: float,
) -> None:
    text = (
        f"\U0001f501 Batch run complete: {created_count} new opportunit"
        f"{'y' if created_count == 1 else 'ies'} ready for review\n"
        f"({drained_count} messages processed"
        + (f", {error_count} errors" if error_count else "")
        + f", {duration_seconds}s)"
    )
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            logger.exception("admin_notify_failed", admin_id=admin_id)


async def _resolve_channel_id(session: AsyncSession, telegram_id: int) -> int | None:
    repo = SourceChannelRepository(session)
    channels = await repo.list(telegram_id=telegram_id)
    return channels[0].id if channels else None
