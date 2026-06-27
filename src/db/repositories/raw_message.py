from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.raw_message import RawMessage
from src.db.repositories.base import BaseRepository


class RawMessageRepository(BaseRepository[RawMessage]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, RawMessage)

    async def create(
        self,
        source_channel_id: int | None,
        telegram_msg_id: int,
        text: str | None,
        received_at: datetime,
    ) -> RawMessage:
        msg = RawMessage(
            source_channel_id=source_channel_id,
            telegram_msg_id=telegram_msg_id,
            text=text,
            received_at=received_at,
            processed=False,
        )
        return await self.save(msg)
