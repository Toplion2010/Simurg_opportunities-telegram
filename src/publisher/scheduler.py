from datetime import datetime, timezone

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.config import Settings
from src.core.logging import get_logger
from src.db.repositories.opportunity import OpportunityRepository
from src.publisher.sender import OpportunitySender

logger = get_logger(__name__)


async def publish_scheduled(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
) -> None:
    sender = OpportunitySender(settings)
    now = datetime.now(tz=timezone.utc)

    async with session_factory() as session:
        repo = OpportunityRepository(session)
        due = await repo.get_due_for_publish(now)

        # Log the empty case too. Without it, "nobody approved anything" and
        # "every publish blew up" produce identical (silent) logs, which is what
        # made this failure invisible for days.
        logger.info("publishing_due_opportunities", count=len(due))
        if not due:
            return

        failures: list[str] = []
        for opp in due:
            try:
                result = await sender.publish(opp, bot)
                await session.commit()
                if result.failed:
                    logger.warning(
                        "scheduled_partial_publish",
                        opp_id=opp.id,
                        failed=[c for c, _ in result.failed],
                    )
            except Exception as e:
                logger.exception("scheduled_publish_error", opp_id=opp.id)
                await session.rollback()
                failures.append(f"#{opp.id} {opp.title or 'Untitled'}: {type(e).__name__}: {e}")

        # An approved post that never reaches the channel is the one failure the
        # admin must not have to read CI logs to discover.
        if failures:
            from src.core.notify import notify_admins

            await notify_admins(
                bot,
                settings.ADMIN_IDS,
                "⚠️ Failed to publish {} approved opportunit{}:\n{}".format(
                    len(failures),
                    "y" if len(failures) == 1 else "ies",
                    "\n".join(f"• {f}" for f in failures[:10]),
                ),
            )
