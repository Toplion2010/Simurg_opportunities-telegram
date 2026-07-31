from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.core.config import Settings


class Base(DeclarativeBase):
    pass


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.DATABASE_URL,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=20,
        echo=settings.ENVIRONMENT != "production",
        # Neon (and most serverless Postgres) drop idle connections well within a
        # long-running process's lifetime. Without this, a stale pooled connection
        # gets reused as-is and fails with "connection is closed" instead of being
        # transparently replaced.
        pool_pre_ping=True,
    )
