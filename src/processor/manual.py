"""Turn the admin's queued own posts into published opportunities.

The bot side (src/bot/routers/manual_post.py) only stores the post. This runs
inside the scheduled job, which has the time budget for an LLM call and the
Chromium that publishing needs. Called right before publish_scheduled, so a
queued post goes out in the same run.
"""

import tempfile
from pathlib import Path

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.routers.manual_post import QUEUED_PREFIX
from src.core.enums import OpportunityStatus
from src.core.logging import get_logger
from src.db.models.raw_message import RawMessage
from src.processor.worker import build_pipeline

logger = get_logger(__name__)


def parse_external_id(external_id: str) -> tuple[int, int, str | None]:
    """'manual:<chat>:<message>[:<file_id>]' -> (chat_id, message_id, file_id)."""
    chat, message, *rest = external_id[len(QUEUED_PREFIX):].split(":", 2)
    return int(chat), int(message), (rest[0] if rest else None)


async def process_manual_posts(
    settings,
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
) -> int:
    """Returns how many opportunities were created and approved."""
    factory = build_pipeline(settings, None, session_factory)
    created_total = 0

    async with session_factory() as session:
        result = await session.execute(
            select(RawMessage)
            .where(
                RawMessage.processed.is_(False),
                RawMessage.external_id.like(f"{QUEUED_PREFIX}%"),
            )
            .order_by(RawMessage.id)
        )
        raws = list(result.scalars().all())
        logger.info("manual_posts_due", count=len(raws))
        pipeline = factory.make_pipeline(session)

        for raw in raws:
            # Captured up front: rollback() expires every ORM object.
            raw_id = raw.id
            chat_id, message_id, file_id = parse_external_id(raw.external_id)
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    media_path = None
                    if file_id:
                        media_path = str(Path(tmp) / "poster.jpg")
                        await bot.download(file_id, destination=media_path)
                    created = await pipeline.run(raw, media_path=media_path, manual=True)
                # The admin already chose to publish it -- no second review.
                for opp in created:
                    opp.status = OpportunityStatus.approved
                    opp.media_path = None  # the temp file is gone
                summary = [
                    f"{o.title or 'Untitled'} ({o.category.value if o.category else '?'}, "
                    f"{o.audience.value})"
                    for o in created
                ]
                raw.processed = True
                await session.commit()
            except Exception as e:
                logger.exception("manual_post_failed", raw_id=raw_id)
                await session.rollback()
                # Mark it done anyway: a post that crashes the extractor would
                # otherwise retry (and fail) on every run. The admin can resend.
                failed = await session.get(RawMessage, raw_id)
                if failed is not None:
                    failed.processed = True
                    await session.commit()
                await _reply(bot, chat_id, message_id, f"❌ AI failed on this post: {type(e).__name__}: {e}\nSend it again to retry.")
                continue

            created_total += len(created)
            logger.info("manual_post_processed", raw_id=raw_id, created=len(created))
            if summary:
                text = "✅ AI made the card, publishing now:\n" + "\n".join(f"• {s}" for s in summary)
            else:
                text = "⚠️ AI could not extract anything to publish from this post. Add more details and send it again."
            await _reply(bot, chat_id, message_id, text)

    return created_total


async def _reply(bot: Bot, chat_id: int, message_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text, reply_to_message_id=message_id)
    except Exception:
        logger.exception("manual_post_reply_failed", chat_id=chat_id)
