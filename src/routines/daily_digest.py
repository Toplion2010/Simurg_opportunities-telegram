"""Once-a-day curation pass over the pending queue (GitHub Actions).

Picks the best still-undigested pending opportunities (src/core/scoring.py's
0-100 score), and routes each by how strong the score is:

    >= AUTO_APPROVE_SCORE  auto-approved, no human review — the next
                            drain.yml run publishes it through the existing
                            OpportunitySender, unchanged.
    >= DIGEST_MIN_SCORE    pushed straight to the admins as a reviewable
                            card, reusing the exact card/keyboard the manual
                            "View Queue" flow already uses.

Deliberately separate from batch_processor.py (5x/day ingestion) and
drain_and_publish.py (~10-25 min approval drain + publish): this runs once a
day, and DAILY_DIGEST_SIZE bounds how many NEW candidates it ever touches, so
there's no reason to run it more often. Manual "View Queue" browsing is
untouched — this is additive.

Run with:  python -m src.routines.daily_digest
"""
import asyncio
from datetime import datetime, timezone

from aiogram import Bot

from src.bot.keyboards.queue import opportunity_actions_keyboard
from src.bot.routers.queue import _card_text
from src.core.config import Settings
from src.core.enums import OpportunityStatus
from src.core.logging import get_logger, setup_logging
from src.core.notify import notify_admins
from src.db.base import create_engine
from src.db.repositories.opportunity import OpportunityRepository
from src.db.session import create_session_factory

logger = get_logger(__name__)


async def run() -> int:
    settings = Settings()
    setup_logging(settings.ENVIRONMENT)

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    bot = Bot(token=settings.BOT_TOKEN)

    try:
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)

        async with session_factory() as session:
            repo = OpportunityRepository(session)
            candidates = await repo.get_digest_candidates(
                min_score=settings.DIGEST_MIN_SCORE, limit=settings.DAILY_DIGEST_SIZE
            )
            logger.info("digest_candidates_selected", count=len(candidates))

            if not candidates:
                return 0

            # Stamped for every selected row up front, before any routing —
            # a candidate counts as "surfaced" the moment it's picked, even
            # if the admin push below fails partway through.
            for_review = []
            auto_approved = []
            for opp in candidates:
                opp.digested_at = now
                if opp.relevance is not None and opp.relevance >= settings.AUTO_APPROVE_SCORE:
                    opp.status = OpportunityStatus.approved
                    opp.scheduled_at = now
                    auto_approved.append((opp.id, opp.title or "Untitled", opp.relevance))
                else:
                    for_review.append(opp)

            await session.commit()

            # Push the review batch AFTER commit, so a Telegram failure here
            # never rolls back the digested_at/approved state already saved.
            # expire_on_commit=False (src/db/session.py) — `opp` is still
            # fully readable post-commit, no re-fetch needed.
            for opp in for_review:
                text = "🗓 <b>Today's pick</b> — please review:\n\n" + _card_text(opp)
                kb = opportunity_actions_keyboard(opp.id, page=0)
                for admin_id in settings.ADMIN_IDS:
                    try:
                        await bot.send_message(
                            admin_id, text, parse_mode="HTML", reply_markup=kb
                        )
                    except Exception:
                        logger.exception(
                            "digest_push_failed", opp_id=opp.id, admin_id=admin_id
                        )

        logger.info(
            "digest_complete",
            surfaced=len(candidates),
            auto_approved=len(auto_approved),
            for_review=len(for_review),
        )

        lines = [
            f"🗓 Daily digest: {len(candidates)} surfaced "
            f"({len(auto_approved)} auto-approved, {len(for_review)} for your review)"
        ]
        for opp_id, title, relevance in auto_approved:
            lines.append(f"  ✅ #{opp_id} {title} ({relevance}/100) — publishing shortly")
        await notify_admins(bot, settings.ADMIN_IDS, "\n".join(lines))

        return 0
    except Exception as e:
        logger.exception("digest_failed")
        await notify_admins(
            bot, settings.ADMIN_IDS, f"❌ Daily digest FAILED: {type(e).__name__}: {e}"
        )
        return 1
    finally:
        await bot.session.close()
        await engine.dispose()


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
