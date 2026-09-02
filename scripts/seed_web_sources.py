"""
Seed source_channels rows for the scraped web catalogs.

Usage:
    python -m scripts.seed_web_sources

Idempotent: re-running reactivates and relabels existing rows, never duplicates
them. Needs no Telethon and no API keys — only DATABASE_URL.

A registry entry alone does NOT make a source run; src/collector/web/fetcher.py
requires a matching active row here. That is deliberate: it lets a source be
switched off in the database, without a deploy.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from sqlalchemy.ext.asyncio import async_sessionmaker

from src.collector.web.registry import WEB_SOURCES
from src.core.config import Settings
from src.db.base import create_engine
from src.db.models.source_channel import KIND_WEB, SourceChannel
from src.db.repositories.source_channel import SourceChannelRepository
from src.db.session import create_session_factory

# Human-readable labels for the admin queue and logs. Keys must exist in
# WEB_SOURCES; a key here that the registry does not know is a typo and is
# reported rather than silently seeded.
LABELS: dict[str, str] = {
    "extracurricularhub": "ExtracurricularHub (extracurricularhub.com)",
    "sirel": "SIREL (sirel.org)",
}


async def seed(settings: Settings, session_factory: async_sessionmaker) -> int:
    unknown = set(LABELS) - set(WEB_SOURCES)
    if unknown:
        print(f"ERROR: not in WEB_SOURCES registry: {sorted(unknown)}")
        return 1

    async with session_factory() as session:
        repo = SourceChannelRepository(session)

        for key in WEB_SOURCES:
            label = LABELS.get(key, key)
            existing = await repo.list(kind=KIND_WEB, identifier=key)
            if existing:
                row = existing[0]
                row.name = label
                row.active = True
                print(f"  OK    {key} (id={row.id}) -- already seeded, reactivated")
                continue

            row = SourceChannel(
                kind=KIND_WEB,
                identifier=key,
                name=label,
                telegram_id=None,
                active=True,
            )
            await repo.save(row)
            print(f"  ADD   {key} (id={row.id}) -- {label}")

        await session.commit()

    print("\nDone. Run the collector with: python -m src.routines.web_collector")
    return 0


async def main() -> int:
    settings = Settings()
    engine = create_engine(settings)
    try:
        return await seed(settings, create_session_factory(engine))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
