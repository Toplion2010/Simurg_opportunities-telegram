from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.logging import get_logger
from src.db.repositories.source_channel import SourceChannelRepository

logger = get_logger(__name__)


async def load_active_channel_ids(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[int]:
    async with session_factory() as session:
        repo = SourceChannelRepository(session)
        ids = await repo.get_active_channel_ids()

    logger.info("loaded_active_channels", count=len(ids), channel_ids=ids)
    return ids
