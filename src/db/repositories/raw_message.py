from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.raw_message import RawMessage
from src.db.repositories.base import BaseRepository


class RawMessageRepository(BaseRepository[RawMessage]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, RawMessage)

    async def create(
        self,
        source_channel_id: int | None,
        text: str | None,
        received_at: datetime,
        telegram_msg_id: int | None = None,
        external_id: str | None = None,
    ) -> RawMessage:
        """Create a raw item. Exactly one of telegram_msg_id / external_id is
        set, depending on whether the source is a Telegram channel or a
        scraped web catalog."""
        msg = RawMessage(
            source_channel_id=source_channel_id,
            telegram_msg_id=telegram_msg_id,
            external_id=external_id,
            text=text,
            received_at=received_at,
            processed=False,
        )
        return await self.save(msg)

    async def existing_external_ids(
        self, source_channel_id: int, external_ids: list[str]
    ) -> set[str]:
        """Which of these ids this source has already ingested.

        This is why a web source's cursor stays small: "what have I seen" is
        answered from the rows that actually exist rather than from a duplicate
        set carried in source_channels.cursor, so the two can never disagree.
        Backed by ix_raw_messages_source_external.
        """
        if not external_ids:
            return set()
        stmt = select(RawMessage.external_id).where(
            RawMessage.source_channel_id == source_channel_id,
            RawMessage.external_id.in_(external_ids),
        )
        result = await self._session.execute(stmt)
        return {row for row in result.scalars().all() if row is not None}
