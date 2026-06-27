from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.base import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    def __init__(self, session: AsyncSession, model: type[T]) -> None:
        self._session = session
        self._model = model

    async def get(self, id: int) -> T | None:
        return await self._session.get(self._model, id)

    async def list(self, **filters: Any) -> list[T]:
        stmt = select(self._model)
        for attr, value in filters.items():
            stmt = stmt.where(getattr(self._model, attr) == value)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def save(self, obj: T) -> T:
        self._session.add(obj)
        await self._session.flush()
        await self._session.refresh(obj)
        return obj

    async def delete(self, id: int) -> None:
        obj = await self.get(id)
        if obj is not None:
            await self._session.delete(obj)
