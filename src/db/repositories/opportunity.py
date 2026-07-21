from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.enums import OpportunityStatus
from src.db.models.opportunity import Opportunity
from src.db.repositories.base import BaseRepository


class OpportunityRepository(BaseRepository[Opportunity]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Opportunity)

    async def get_with_raw_message(self, id: int) -> Opportunity | None:
        """Fetch an opportunity with ``raw_message`` eagerly loaded.

        Needed before publishing: ``live_background.py`` reads
        ``opp.raw_message.text`` (the original source-channel wording) for
        prompt context, and a lazy load there would raise ``MissingGreenlet``
        in async SQLAlchemy.
        """
        stmt = (
            select(Opportunity)
            .options(selectinload(Opportunity.raw_message))
            .where(Opportunity.id == id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_pending(self, page: int = 0, page_size: int = 5) -> list[Opportunity]:
        stmt = (
            select(Opportunity)
            .where(Opportunity.status == OpportunityStatus.pending)
            .order_by(Opportunity.created_at.asc())
            .offset(page * page_size)
            .limit(page_size)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_pending(self) -> int:
        from sqlalchemy import func
        stmt = select(func.count()).select_from(Opportunity).where(
            Opportunity.status == OpportunityStatus.pending
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def get_due_for_publish(self, now: datetime | None = None) -> list[Opportunity]:
        now = (now or datetime.now(tz=timezone.utc)).replace(tzinfo=None)
        stmt = (
            select(Opportunity)
            .options(selectinload(Opportunity.raw_message))
            .where(
                Opportunity.status == OpportunityStatus.approved,
                (Opportunity.scheduled_at.is_(None)) | (Opportunity.scheduled_at <= now),
            )
            .order_by(Opportunity.scheduled_at.asc().nullsfirst(), Opportunity.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def search(self, query: str, limit: int = 20) -> list[Opportunity]:
        stmt = (
            select(Opportunity)
            .where(Opportunity.title.ilike(f"%{query}%"))
            .order_by(Opportunity.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
