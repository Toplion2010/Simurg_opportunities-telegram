from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.source_channel import SourceChannel
from src.db.repositories.base import BaseRepository


class SourceChannelRepository(BaseRepository[SourceChannel]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SourceChannel)

    async def get_active_channel_ids(self) -> list[int]:
        stmt = select(SourceChannel.telegram_id).where(SourceChannel.active.is_(True))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_active(self) -> list[SourceChannel]:
        return await self.list(active=True)
