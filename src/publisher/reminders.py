"""A second post, "N days left to apply!", for strong published opportunities
nearing their deadline: same channels and text as the original, with a newly
generated image (OpportunitySender.publish_reminder).

Runs right after publish_scheduled() in the batch and drain jobs. Each
opportunity gets at most one reminder (reminder_sent_at), and at most
DAILY_REMINDER_CAP go out per day, since every reminder is a billed image.
"""
from datetime import date, datetime, timezone

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import TelegramClient

from src.core.config import Settings
from src.core.logging import get_logger
from src.core.notify import notify_admins
from src.db.models.opportunity import Opportunity
from src.db.repositories.opportunity import OpportunityRepository
from src.publisher.deadlines import parse_deadline
from src.publisher.sender import OpportunitySender

logger = get_logger(__name__)

# A post published only days ago doesn't need a reminder yet -- the channel
# just saw it. Covers programs first posted inside the reminder window.
_MIN_DAYS_SINCE_POST = 7


def due_reminders(
    candidates: list[Opportunity], today: date, days_before: int
) -> list[tuple[Opportunity, int]]:
    """(opportunity, days_left) for every candidate whose deadline is 1 to
    `days_before` days away, soonest deadline first. An unparseable deadline
    ("Rolling", prose) never gets a reminder."""
    due = []
    for opp in candidates:
        deadline = parse_deadline(opp.deadline, today)
        if deadline is None:
            continue
        days_left = (deadline - today).days
        if not 1 <= days_left <= days_before:
            continue
        if opp.published_at and (today - opp.published_at.date()).days < _MIN_DAYS_SINCE_POST:
            continue
        due.append((opp, days_left))
    due.sort(key=lambda pair: pair[1])
    return due


async def publish_reminders(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
    telethon_clients: list[TelegramClient] | None = None,
) -> None:
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    sender = OpportunitySender(settings, telethon_clients=telethon_clients)

    async with session_factory() as session:
        repo = OpportunityRepository(session)
        candidates = await repo.get_reminder_candidates(settings.REMINDER_MIN_SCORE)
        due = due_reminders(candidates, now.date(), settings.REMINDER_DAYS_BEFORE)

        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        remaining = max(0, settings.DAILY_REMINDER_CAP - await repo.count_reminders_since(start_of_day))
        logger.info("publishing_due_reminders", due=len(due), remaining_today=remaining)
        due = due[:remaining]

        failures: list[str] = []
        partials: list[str] = []
        for opp, days_left in due:
            opp_id, title = opp.id, opp.title or "Untitled"
            try:
                result = await sender.publish_reminder(opp, bot, days_left)
            except Exception as e:
                logger.exception("reminder_publish_error", opp_id=opp_id)
                failures.append(f"#{opp_id} {title}: {type(e).__name__}: {e}")
                result = None
            # Stamped even on failure: a missed reminder is cheap, while a
            # retry every run would re-alert the admins (and re-bill an image)
            # each time. No session.rollback() here -- it would expire the
            # other loaded rows (MissingGreenlet on the next iteration).
            opp.reminder_sent_at = now
            await session.commit()
            if result and result.failed:
                partials.append(
                    f"#{opp_id} {title}: reminder sent to {result.succeeded}, "
                    f"FAILED {[c for c, _ in result.failed]}"
                )

        if failures or partials:
            lines = []
            if failures:
                lines.append(f"⚠️ Failed to post {len(failures)} deadline reminder(s) (not retried):")
                lines += [f"• {f}" for f in failures[:10]]
            if partials:
                lines.append(f"⚠️ Reminder posted to only SOME channels ({len(partials)}):")
                lines += [f"• {p}" for p in partials[:10]]
            await notify_admins(bot, settings.ADMIN_IDS, "\n".join(lines))
