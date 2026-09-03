from datetime import datetime, timezone

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.config import Settings
from src.core.logging import get_logger
from src.db.repositories.opportunity import OpportunityRepository
from src.publisher.sender import OpportunitySender

logger = get_logger(__name__)


def remaining_publish_cap(daily_cap: int, already_published: int) -> int:
    """How many more opportunities may publish today, given how many already
    have. Never negative -- a cap lowered mid-day, or a burst of manual
    approvals, must not turn into a negative slice."""
    return max(0, daily_cap - already_published)


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

        # DAILY_PUBLISH_CAP bounds actual channel posts per day regardless of
        # WHEN a row was approved -- daily_digest.py's auto-approvals and a
        # human tap from days ago both flow through this same due-for-publish
        # list, so the cap has to live here, not in the digest step, to be a
        # true ceiling. Order is already scheduled_at/created_at ascending
        # (get_due_for_publish), so older approvals go out first; anything
        # trimmed simply stays 'approved' for a later run to pick up.
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        already_published = await repo.count_published_since(start_of_day)
        remaining_cap = remaining_publish_cap(settings.DAILY_PUBLISH_CAP, already_published)
        if len(due) > remaining_cap:
            logger.info(
                "daily_publish_cap_trimmed",
                due=len(due),
                already_published=already_published,
                cap=settings.DAILY_PUBLISH_CAP,
                kept=remaining_cap,
            )
            due = due[:remaining_cap]
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
        partials: list[str] = []
        for opp in due:
            opp_id, title = identities[opp.id]
            try:
                result = await sender.publish(opp, bot)
                await session.commit()
                if result.failed:
                    failed_ids = [c for c, _ in result.failed]
                    logger.warning(
                        "scheduled_partial_publish",
                        opp_id=opp_id,
                        failed=failed_ids,
                    )
                    # The row is already marked published, so this leg is never
                    # retried. Naming the channel that dropped it is the only
                    # way the admin learns without reading CI logs — and with
                    # category routing layered on audience routing, a silently
                    # missing third post is easy to never notice.
                    partials.append(
                        f"#{opp_id} {title}: sent to {result.succeeded}, FAILED {failed_ids}"
                    )
            except Exception as e:
                logger.exception("scheduled_publish_error", opp_id=opp_id)
                await session.rollback()
                failures.append(f"#{opp_id} {title}: {type(e).__name__}: {e}")

        # An approved post that never reaches the channel is the one failure the
        # admin must not have to read CI logs to discover. A post that reached
        # only some of its channels counts: it is marked published and will
        # never be retried.
        if failures or partials:
            from src.core.notify import notify_admins

            lines: list[str] = []
            if failures:
                lines.append(
                    "⚠️ Failed to publish {} approved opportunit{}:".format(
                        len(failures), "y" if len(failures) == 1 else "ies"
                    )
                )
                lines += [f"• {f}" for f in failures[:10]]
            if partials:
                lines.append(
                    "⚠️ Published to only SOME channels ({}, not retried):".format(len(partials))
                )
                lines += [f"• {p}" for p in partials[:10]]

            await notify_admins(bot, settings.ADMIN_IDS, "\n".join(lines))
