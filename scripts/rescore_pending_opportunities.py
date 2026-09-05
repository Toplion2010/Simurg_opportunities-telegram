"""Rescore every pending opportunity with the current 6-axis rubric
(src/core/scoring.py) -- the same scorer both collector pipelines call live,
just applied here to the existing backlog after a rubric change.

Pure regex/arithmetic, no external calls, no rate limits -- unlike the old
Groq-based scripts/ai_rescore_opportunities.py, a full backlog rescore
finishes in well under a second regardless of size, so every dispatch just
rescores everything pending unconditionally (no resumability marker, no
pacing, no retry, no batching needed).

Usage:
    python -m scripts.rescore_pending_opportunities [--apply] [--limit N] [--count-only]

Runs read-only by default and prints exactly what it would change. Pass
--apply to write relevance/relevance_reason for every pending row.
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from sqlalchemy import select, update

from src.core.config import Settings
from src.core.enums import OpportunityStatus
from src.core.scoring import infer_cost_amount, infer_is_online, score
from src.db.base import create_engine
from src.db.models.opportunity import Opportunity
from src.db.session import create_session_factory


def _score_text(opp: Opportunity) -> str:
    return " ".join(
        filter(None, [opp.title, opp.description, opp.eligibility, opp.organizer])
    )


async def run(apply: bool, limit: int | None, count_only: bool) -> int:
    settings = Settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    try:
        async with session_factory() as session:
            stmt = (
                select(Opportunity)
                .where(Opportunity.status == OpportunityStatus.pending)
                .order_by(Opportunity.id)
            )
            if limit:
                stmt = stmt.limit(limit)
            opps = (await session.execute(stmt)).scalars().all()

            if count_only:
                print(f"{len(opps)} pending opportunities.")
                return 0

            changed = 0
            updates: list[tuple[int, int, str]] = []
            for opp in opps:
                text = _score_text(opp)
                is_online = infer_is_online(opp.location)
                cost_amount = infer_cost_amount(opp.cost)
                value, reason = score(is_online, cost_amount, opp.location, text)

                old = opp.relevance
                print(f"  #{opp.id:<5} {old} -> {value}/100  ({reason})  {(opp.title or '')[:40]}")
                if value != old:
                    changed += 1
                updates.append((opp.id, value, reason))

            print(f"\n{changed} of {len(opps)} pending opportunities would change score.")

            if not apply:
                print("\nDRY RUN — nothing written. Re-run with --apply to commit.")
                return 0

            async with session_factory() as write_session:
                for opp_id, relevance, reason in updates:
                    await write_session.execute(
                        update(Opportunity)
                        .where(Opportunity.id == opp_id)
                        .values(relevance=relevance, relevance_reason=reason)
                    )
                await write_session.commit()
            print("\nApplied.")
            return 0
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(prog="rescore_pending_opportunities")
    parser.add_argument(
        "--apply", action="store_true", help="Commit the changes (default: dry run)."
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Only rescore this many pending rows."
    )
    parser.add_argument(
        "--count-only", action="store_true", help="Print the pending row count and exit."
    )
    args = parser.parse_args()
    return asyncio.run(run(args.apply, args.limit, args.count_only))


if __name__ == "__main__":
    sys.exit(main())
