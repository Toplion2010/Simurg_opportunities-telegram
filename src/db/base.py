from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.core.config import Settings


class Base(DeclarativeBase):
    pass


def create_serverless_engine(settings: Settings) -> AsyncEngine:
    """Engine sized for a serverless function rather than a long-lived process.

    A Vercel function handles one request at a time and may be frozen between
    them, so the 10-connection pool ``create_engine`` opens is pure waste --
    Neon would see idle connections from every warm instance. One connection,
    reused while the instance stays warm, is what this workload actually needs.

    ``pool_pre_ping`` matters more here than anywhere else: an instance can be
    frozen for minutes and resume holding a connection Neon has long since
    dropped.

    Use Neon's DIRECT endpoint for this, not ``-pooler``. Through PgBouncer's
    transaction mode asyncpg's prepared statements break, which would need
    ``statement_cache_size=0``; going direct avoids the whole class of problem.
    """
    return create_async_engine(
        settings.DATABASE_URL,
        pool_size=1,
        max_overflow=0,
        pool_recycle=300,
        pool_pre_ping=True,
        echo=False,
    )


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
