import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import TelegramClient, events

from src.collector.channel_manager import load_active_channel_ids
from src.collector.handlers import make_message_handler
from src.core.config import Settings
from src.core.logging import get_logger

logger = get_logger(__name__)


async def start_userbot(
    settings: Settings,
    redis: aioredis.Redis,
    session_factory: async_sessionmaker[AsyncSession],
) -> TelegramClient:
    session_path = f"telethon_session/{settings.TELETHON_SESSION}"
    client = TelegramClient(
        session_path,
        settings.TELETHON_API_ID,
        settings.TELETHON_API_HASH,
    )

    await client.start()
    logger.info("telethon_connected")

    channel_ids = await load_active_channel_ids(session_factory)

    if channel_ids:
        handler = make_message_handler(redis)
        client.add_event_handler(
            handler,
            events.NewMessage(chats=channel_ids),
        )
        logger.info("monitoring_channels", count=len(channel_ids))
    else:
        logger.warning("no_active_channels_configured")

    return client
