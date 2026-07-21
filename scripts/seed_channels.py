"""
Seed source channels from Telegram usernames.

Usage:
    python -m scripts.seed_channels

Resolves each username to its real Telegram channel ID via Telethon,
then inserts (or skips existing) rows into source_channels.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from telethon import TelegramClient
from telethon.tl.functions.channels import GetFullChannelRequest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.config import Settings
from src.db.base import create_engine
from src.db.session import create_session_factory
from src.db.models.source_channel import SourceChannel
from src.db.repositories.source_channel import SourceChannelRepository

SOURCE_CHANNELS = [
    {"username": "logic_aktau_bil",        "name": "Logic Aktau BIL (test)"},
    {"username": "bilopportunities",       "name": "Bil Opportunities"},
    {"username": "uppertunity",            "name": "Uppertunity"},
    {"username": "astana_hub",             "name": "Astana Hub"},
    {"username": "startup_course_com",     "name": "Startup Course"},
    {"username": "mentoria_organization",  "name": "Mentoria Organization"},
    {"username": "myextrakz",              "name": "MyExtra KZ"},
    {"username": "edu_strategies",         "name": "Edu Strategies"},
    {"username": "IvyLeaguesStudent",      "name": "Ivy League Student"},
    {"username": "jasa_project",           "name": "JASA Project"},
    {"username": "youthfinance",           "name": "Youth Finance"},
    {"username": "Saubolopps",             "name": "Saubol Opportunities"},
    {"username": "Portfolio_Lab",          "name": "Portfolio Lab"},
]


async def seed(settings: Settings, session_factory: async_sessionmaker) -> None:
    session_path = f"telethon_session/{settings.TELETHON_SESSION}"
    client = TelegramClient(session_path, settings.TELETHON_API_ID, settings.TELETHON_API_HASH)
    await client.start()
    print("Telethon connected.\n")

    async with session_factory() as session:
        repo = SourceChannelRepository(session)

        for ch in SOURCE_CHANNELS:
            username = ch["username"]
            try:
                entity = await client.get_entity(username)
                telegram_id = entity.id

                # Telegram channel IDs from get_entity are bare; broadcast channels
                # are stored as negative in Bot API: -(1000000000000 + id)
                # Telethon returns the bare positive peer id for channels.
                # Store the bare id; collector uses Telethon which also gives bare ids.
                existing = await repo.list(telegram_id=telegram_id)
                if existing:
                    print(f"  SKIP  @{username} (id={telegram_id}) — already in DB")
                    continue

                channel = SourceChannel(
                    telegram_id=telegram_id,
                    name=ch["name"],
                    username=username,
                    active=True,
                )
                await repo.save(channel)
                print(f"  ADD   @{username} → id={telegram_id}  ({ch['name']})")

            except Exception as e:
                print(f"  ERROR @{username}: {e}")

        await session.commit()

    await client.disconnect()
    print("\nDone.")


async def main() -> None:
    settings = Settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        await seed(settings, session_factory)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
