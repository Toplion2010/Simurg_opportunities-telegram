"""Read-only report: every approved/rejected/published opportunity, with a
best-effort flag for whether the "approved" was a real human decision or
just the daily digest auto-approving because the old regex score crossed
AUTO_APPROVE_SCORE (src/routines/daily_digest.py sets digested_at and
scheduled_at to the exact same timestamp only in that auto-approve branch;
a human approval via the queue never sets scheduled_at at all unless later
scheduled separately, so scheduled_at == digested_at is the tell). Rejected
rows are always a real human decision -- there is no auto-reject path.

Manual diagnostic only -- SELECTs, never writes.

Usage:
    python -m scripts.list_decisions
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from sqlalchemy import select

from src.core.config import Settings
from src.core.enums import OpportunityStatus
from src.db.base import create_engine
from src.db.models.opportunity import Opportunity
from src.db.session import create_session_factory


async def run() -> int:
    settings = Settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    try:
        async with session_factory() as session:
            stmt = (
                select(Opportunity)
                .where(
                    Opportunity.status.in_(
                        [
                            OpportunityStatus.approved,
                            OpportunityStatus.rejected,
                            OpportunityStatus.published,
                        ]
                    )
                )
                .order_by(Opportunity.id)
            )
            opps = (await session.execute(stmt)).scalars().all()

            counts = {"approved": 0, "rejected": 0, "published": 0, "auto_approved": 0, "human_approved": 0}
            print("id\tstatus\tsource\trelevance\trelevance_reason\ttitle")
            for opp in opps:
                status = opp.status.value
                counts[status] = counts.get(status, 0) + 1

                is_auto = (
                    status in ("approved", "published")
                    and opp.digested_at is not None
                    and opp.scheduled_at == opp.digested_at
                )
                if status in ("approved", "published"):
                    if is_auto:
                        counts["auto_approved"] += 1
                    else:
                        counts["human_approved"] += 1
                source = "auto(digest-score)" if is_auto else "human"

                title = (opp.title or "")[:70]
                reason = (opp.relevance_reason or "")[:60]
                print(f"{opp.id}\t{status}\t{source}\t{opp.relevance}\t{reason}\t{title}")

            print(f"\n{len(opps)} decided opportunities total.")
            print(
                f"  approved={counts['approved']} published={counts['published']} "
                f"rejected={counts['rejected']}"
            )
            print(
                f"  of the approved/published: auto(digest-score)={counts['auto_approved']} "
                f"human={counts['human_approved']}"
            )
            print(f"  human-labeled total (human-approved + rejected) = "
                  f"{counts['human_approved'] + counts['rejected']}")
            return 0
    finally:
        await engine.dispose()


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
