"""Pull channel history since the last run.

The live ``events.NewMessage`` handler in handlers.py only sees posts that arrive
while a process is connected, which forces a 24/7 process. Telegram keeps channel
history, so a scheduled run can instead ask each channel for everything posted
after the last message id it recorded — same result, no always-on requirement.
"""
import os
from datetime import datetime, timezone
from typing import Any

from telethon import TelegramClient

from src.core.logging import get_logger
from src.db.repositories.source_channel import SourceChannelRepository

logger = get_logger(__name__)

MEDIA_DIR = os.environ.get("SIMURG_MEDIA_DIR", "/tmp/simurg_media")

# Ceiling per channel per run. A channel that has been quiet for a long time (or a
# first run, where there is no last_seen_msg_id) would otherwise pull its entire
# backlog and spend the whole run on LLM calls for stale posts.
MAX_MESSAGES_PER_CHANNEL = 30


async def fetch_new_messages(
    client: TelegramClient,
    session_factory,
    download_media: bool = True,
) -> list[dict[str, Any]]:
    """Fetch messages posted since the last run and advance each channel's cursor.

    Returns payloads in the same shape the live handler used to enqueue, so the
    downstream pipeline is unchanged.
    """
    os.makedirs(MEDIA_DIR, exist_ok=True)
    payloads: list[dict[str, Any]] = []

    # A StringSession carries the auth key but NOT the entity cache that the
    # .session file keeps, so get_entity(channel_id) cannot resolve a bare id and
    # even mis-guesses it as a PeerUser. Loading the dialog list repopulates that
    # cache for this connection; without it every channel fetch fails.
    await client.get_dialogs(limit=None)

    async with session_factory() as session:
        repo = SourceChannelRepository(session)
        channels = await repo.get_active()

        if not channels:
            logger.warning("no_active_channels_configured")
            return []

        for channel in channels:
            try:
                fetched = await _fetch_channel(
                    client, channel, download_media=download_media
                )
            except Exception:
                # One unreachable channel (left, banned, deleted) must not abort
                # collection for the other 39.
                logger.exception(
                    "channel_fetch_failed", telegram_id=channel.telegram_id
                )
                continue

            if not fetched:
                continue

            payloads.extend(fetched)

    # Cursors are deliberately NOT advanced here. A message whose extraction later
    # fails (LLM rate limit, transient API error) must stay re-fetchable, so the
    # caller advances each cursor only past messages it actually processed —
    # see advance_cursors().
    logger.info("history_fetch_complete", messages=len(payloads))
    return payloads


async def advance_cursors(session_factory, safe_ids: dict[int, int]) -> None:
    """Record how far each channel was successfully processed.

    ``safe_ids`` maps telegram channel id -> highest message id that completed.
    Anything above it is left for the next run to retry.
    """
    if not safe_ids:
        return

    async with session_factory() as session:
        repo = SourceChannelRepository(session)
        for channel in await repo.get_active():
            new_id = safe_ids.get(channel.telegram_id)
            if new_id is None:
                continue
            if channel.last_seen_msg_id is None or new_id > channel.last_seen_msg_id:
                channel.last_seen_msg_id = new_id
        await session.commit()

    logger.info("cursors_advanced", channels=len(safe_ids))


def compute_safe_cursors(
    payloads: list[dict[str, Any]], failed: set[tuple[int, int]]
) -> dict[int, int]:
    """Highest message id per channel that is safe to skip next time.

    Stops at the first failure in each channel so a rate-limited message is
    retried on the next run instead of being silently dropped. Messages after it
    get re-fetched too; the deduplicator absorbs the ones that did succeed.
    """
    by_channel: dict[int, list[int]] = {}
    for p in payloads:
        by_channel.setdefault(p["channel_id"], []).append(p["telegram_msg_id"])

    safe: dict[int, int] = {}
    for channel_id, msg_ids in by_channel.items():
        highest: int | None = None
        for msg_id in sorted(msg_ids):
            if (channel_id, msg_id) in failed:
                break
            highest = msg_id
        if highest is not None:
            safe[channel_id] = highest
    return safe


async def _fetch_channel(
    client: TelegramClient, channel, download_media: bool
) -> list[dict[str, Any]]:
    entity = await client.get_entity(channel.telegram_id)

    if channel.last_seen_msg_id is None:
        # First ever run for this channel: take only the most recent few rather
        # than the entire history.
        messages = await client.get_messages(entity, limit=5)
        messages = list(reversed(messages))
    else:
        messages = [
            m
            async for m in client.iter_messages(
                entity,
                min_id=channel.last_seen_msg_id,
                limit=MAX_MESSAGES_PER_CHANNEL,
                reverse=True,
            )
        ]

    out: list[dict[str, Any]] = []
    for message in messages:
        text = message.text or message.message or ""
        if not text.strip():
            continue

        media_path: str | None = None
        if download_media and message.photo:
            try:
                path = os.path.join(
                    MEDIA_DIR, f"{channel.telegram_id}_{message.id}.jpg"
                )
                await message.download_media(file=path)
                media_path = path
            except Exception:
                logger.warning("media_download_failed", msg_id=message.id)

        out.append(
            {
                "telegram_msg_id": message.id,
                "channel_id": channel.telegram_id,
                "text": text,
                "received_at": (message.date or datetime.now(tz=timezone.utc)).isoformat(),
                "media_path": media_path,
            }
        )

    if out:
        logger.info(
            "channel_fetched",
            telegram_id=channel.telegram_id,
            name=channel.name,
            count=len(out),
        )
    return out
