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

        # Read identity for everything up front: commit()/rollback() expire
        # EVERY object in the session, not just the one just processed, so
        # touching opp.id/opp.title on a later iteration triggers a lazy
        # reload. AsyncSession refuses that implicit IO and raises
        # MissingGreenlet, which would abort the loop and skip every
        # remaining opportunity, not just the one that failed.
        identities = {opp.id: (opp.id, opp.title or "Untitled") for opp in due}

        failures: list[str] = []
        for opp in due:
            opp_id, title = identities[opp.id]
            try:
                result = await sender.publish(opp, bot)
                await session.commit()
                if result.failed:
                    logger.warning(
                        "scheduled_partial_publish",
                        opp_id=opp_id,
                        failed=[c for c, _ in result.failed],
                    )
            except Exception as e:
                logger.exception("scheduled_publish_error", opp_id=opp_id)
                await session.rollback()
                failures.append(f"#{opp_id} {title}: {type(e).__name__}: {e}")

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
