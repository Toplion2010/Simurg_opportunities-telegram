"""Pull channel history since the last run.

The live ``events.NewMessage`` handler in handlers.py only sees posts that arrive
while a process is connected, which forces a 24/7 process. Telegram keeps channel
history, so a scheduled run can instead ask each channel for everything posted
after the last message id it recorded — same result, no always-on requirement.
"""
import os
import re
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

# Some channels split one post into two Telegram messages: a photo with a short
# (or truncated) caption, immediately followed by the full text as its own
# message — a workaround for Telegram's 1024-char photo caption limit. Treated
# as separate messages, this reaches the extractor as one broken opportunity
# (missing fields) plus one duplicate. A gap this small between a photo message
# and the text that completes it is treated as one post instead of two.
SPLIT_POST_WINDOW_SECONDS = 300


def _looks_like_continuation(shorter: str, longer: str) -> bool:
    """True if `longer` reads as `shorter` published in full a moment later."""
    a = re.sub(r"\s+", " ", shorter).strip()
    b = re.sub(r"\s+", " ", longer).strip()
    return bool(a) and b.startswith(a)


def _merge_split_posts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse a photo+caption message and the full-text message that follows it.

    Expects ``items`` sorted oldest-first per channel, each with text/media_path/date.
    """
    merged: list[dict[str, Any]] = []
    i = 0
    while i < len(items):
        current = items[i]
        if i + 1 < len(items):
            nxt = items[i + 1]
            gap = (nxt["date"] - current["date"]).total_seconds()
            if (
                current["media_path"]
                and not nxt["media_path"]
                and 0 <= gap <= SPLIT_POST_WINDOW_SECONDS
                and _looks_like_continuation(current["text"], nxt["text"])
            ):
                merged.append(
                    {
                        "telegram_msg_id": nxt["telegram_msg_id"],
                        "text": nxt["text"],
                        "media_path": current["media_path"],
                        "date": current["date"],
                    }
                )
                i += 2
                continue
        merged.append(current)
        i += 1
    return merged


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

    # Only read the channel list from the DB, then close the session before the
    # Telegram loop below. That loop can run for many minutes (flood waits, a slow
    # or flaky network path to Telegram), and a hosted Postgres (Neon's free tier
    # in particular) will drop an idle connection well before that — holding the
    # session open for the whole loop turned a slow run into a crashed one.
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

    items: list[dict[str, Any]] = []
    for message in messages:
        text = message.text or message.message or ""

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

        items.append(
            {
                "telegram_msg_id": message.id,
                "text": text,
                "media_path": media_path,
                "date": message.date or datetime.now(tz=timezone.utc),
            }
        )

    items = _merge_split_posts(items)

    out: list[dict[str, Any]] = []
    for item in items:
        if not item["text"].strip():
            continue
        out.append(
            {
                "telegram_msg_id": item["telegram_msg_id"],
                "channel_id": channel.telegram_id,
                "text": item["text"],
                "received_at": item["date"].isoformat(),
                "media_path": item["media_path"],
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
