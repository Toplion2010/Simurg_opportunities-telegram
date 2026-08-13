"""Build a t.me permalink back to the original source post.

Denormalized onto Opportunity.source_url at insert time (see pipeline.py) —
a join would require eager-loading raw_message -> source_channel on every
queue query, and a missed selectinload surfaces as MissingGreenlet at runtime.
"""
from src.db.models.source_channel import SourceChannel


def build_source_url(channel: SourceChannel | None, telegram_msg_id: int) -> str | None:
    if channel is None:
        return None
    if channel.username:
        return f"https://t.me/{channel.username}/{telegram_msg_id}"
    return f"https://t.me/c/{channel.telegram_id}/{telegram_msg_id}"
