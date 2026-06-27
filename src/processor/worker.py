from datetime import datetime, timezone

import redis.asyncio as aioredis
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

    def make_pipeline(self, session: AsyncSession) -> ProcessingPipeline:
        return ProcessingPipeline(
            cleaner=self._cleaner,
            extractor=self._extractor,
            classifier=self._classifier,
            deduplicator=self._deduplicator,
            opp_repo=OpportunityRepository(session),
            raw_repo=RawMessageRepository(session),
        )


async def process_batch(
    factory: PipelineFactory,
    batch_size: int = 10,
) -> None:
    payloads = await dequeue_batch(factory._redis, batch_size)
    if not payloads:
        return

    logger.info("processing_batch", count=len(payloads))

    async with factory._session_factory() as session:
        raw_repo = RawMessageRepository(session)
        pipeline = factory.make_pipeline(session)

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
                await pipeline.run(raw, media_path=payload.get("media_path"))
                await session.commit()
            except Exception:
                logger.exception("batch_item_error", payload=payload)
                await session.rollback()


async def _resolve_channel_id(session: AsyncSession, telegram_id: int) -> int | None:
    repo = SourceChannelRepository(session)
    channels = await repo.list(telegram_id=telegram_id)
    return channels[0].id if channels else None
