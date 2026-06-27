from datetime import datetime, timezone

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.config import Settings
from src.core.logging import get_logger
from src.db.repositories.opportunity import OpportunityRepository
from src.publisher.sender import OpportunitySender

logger = get_logger(__name__)


async def publish_scheduled(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
) -> None:
    sender = OpportunitySender(settings)
    now = datetime.now(tz=timezone.utc)

    async with session_factory() as session:
        repo = OpportunityRepository(session)
        due = await repo.get_due_for_publish(now)

        if not due:
            return

        logger.info("publishing_due_opportunities", count=len(due))
        for opp in due:
            try:
                await sender.publish(opp, bot)
                await session.commit()
            except Exception:
                logger.exception("scheduled_publish_error", opp_id=opp.id)
                await session.rollback()
