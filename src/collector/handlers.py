import os
from datetime import datetime, timezone
from typing import Callable, Coroutine, Any

import redis.asyncio as aioredis
from telethon import events

from src.core.logging import get_logger
from src.core.redis_client import enqueue_message

logger = get_logger(__name__)

MEDIA_DIR = "/tmp/simurg_media"
os.makedirs(MEDIA_DIR, exist_ok=True)


def make_message_handler(
    redis: aioredis.Redis,
) -> Callable[[events.NewMessage.Event], Coroutine[Any, Any, None]]:
    async def handler(event: events.NewMessage.Event) -> None:
        try:
            text = event.message.text or event.message.message or ""
            if not text.strip():
                return

            media_path: str | None = None
            if event.message.photo:
                try:
                    path = os.path.join(MEDIA_DIR, f"{event.chat_id}_{event.message.id}.jpg")
                    await event.message.download_media(file=path)
                    media_path = path
                except Exception:
                    logger.warning("media_download_failed", msg_id=event.message.id)

            payload = {
                "telegram_msg_id": event.message.id,
                "channel_id": event.chat_id,
                "text": text,
                "received_at": datetime.now(tz=timezone.utc).isoformat(),
                "media_path": media_path,
            }
            await enqueue_message(redis, payload)
            logger.debug(
                "message_enqueued",
                channel_id=event.chat_id,
                msg_id=event.message.id,
                has_media=media_path is not None,
            )
        except Exception:
            logger.exception(
                "handler_error",
                channel_id=getattr(event, "chat_id", None),
            )

    return handler
