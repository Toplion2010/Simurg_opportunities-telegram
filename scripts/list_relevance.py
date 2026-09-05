"""Read-only report: every pending opportunity's relevance score and title,
most-relevant first. Manual diagnostic only -- SELECTs, never writes.

Usage:
    python -m scripts.list_relevance
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
                .where(Opportunity.status == OpportunityStatus.pending)
                .order_by(Opportunity.relevance.desc().nullslast())
            )
            opps = (await session.execute(stmt)).scalars().all()

            for opp in opps:
                title = (opp.title or "")[:70]
                print(f"{opp.id}\t{opp.relevance}\t{title}")

            print(f"\n{len(opps)} pending opportunities total.")
            return 0
    finally:
        await engine.dispose()


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
