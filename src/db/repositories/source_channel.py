from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.source_channel import KIND_TELEGRAM, SourceChannel
from src.db.repositories.base import BaseRepository


class SourceChannelRepository(BaseRepository[SourceChannel]):
    """source_channels holds both kinds of source. Both accessors below are
    used exclusively by the Telegram collector, so both filter to
    kind='telegram' — without that, web rows (telegram_id NULL) would be handed
    to Telethon as channels to fetch history for.

    Web sources are read with `list(kind=KIND_WEB, active=True)` instead; see
    src/collector/web/fetcher.py.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SourceChannel)

    async def get_active_channel_ids(self) -> list[int]:
        stmt = select(SourceChannel.telegram_id).where(
            SourceChannel.active.is_(True),
            SourceChannel.kind == KIND_TELEGRAM,
            SourceChannel.telegram_id.is_not(None),
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_active(self) -> list[SourceChannel]:
        return await self.list(active=True, kind=KIND_TELEGRAM)
