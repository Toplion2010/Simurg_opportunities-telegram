"""Read-only report: checks the 6-axis relevance rubric (src/core/scoring.py)
against the 741 real approve/reject decisions instead of training anything.

A working rubric should show a clear score separation between historically
approved/published and historically rejected opportunities. This also
directly checks the claim that motivated splitting attendance-ability out as
its own axis: that Sirel/ExtracurricularHub-sourced (aggregator) opportunities
look prestigious but are historically over-approved relative to how
attendable they actually are, while Kazakhstan-local opportunities are
under-approved despite being genuinely easier to attend -- reported here with
real numbers, not assumed.

Manual diagnostic only -- SELECTs, never writes.

Usage:
    python -m scripts.validate_scoring_rubric
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
from sqlalchemy.orm import selectinload

from src.core.config import Settings
from src.core.decisions import is_auto_approval
from src.core.enums import OpportunityStatus
from src.core.geo import is_kazakhstan
from src.core.scoring import infer_cost_amount, infer_is_online, score
from src.db.base import create_engine
from src.db.models.opportunity import Opportunity
from src.db.models.raw_message import RawMessage
from src.db.models.source_channel import SourceChannel
from src.db.session import create_session_factory

_AGGREGATOR_IDENTIFIERS = {"sirel", "extracurricularhub"}


def _score_text(opp: Opportunity) -> str:
    return " ".join(
        filter(None, [opp.title, opp.description, opp.eligibility, opp.organizer])
    )


def _source_label(opp: Opportunity) -> str:
    channel: SourceChannel | None = opp.raw_message.source_channel if opp.raw_message else None
    if channel is None:
        return "unknown"
    if channel.identifier in _AGGREGATOR_IDENTIFIERS:
        return channel.identifier
    if channel.kind == "telegram":
        return "telegram"
    return channel.identifier or channel.kind


def _avg(values: list[int]) -> float:
    return sum(values) / len(values) if values else 0.0


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
                .options(
                    selectinload(Opportunity.raw_message).selectinload(RawMessage.source_channel)
                )
                .order_by(Opportunity.id)
            )
            opps = (await session.execute(stmt)).scalars().all()

            rows = []
            for opp in opps:
                if is_auto_approval(opp):
                    continue
                approved = opp.status in (OpportunityStatus.approved, OpportunityStatus.published)
                text = _score_text(opp)
                is_online = infer_is_online(opp.location)
                cost_amount = infer_cost_amount(opp.cost)
                value, reason = score(is_online, cost_amount, opp.location, text)
                is_local = is_kazakhstan(opp.location) or is_kazakhstan(opp.organizer)
                source = _source_label(opp)
                rows.append(
                    {
                        "id": opp.id,
                        "approved": approved,
                        "score": value,
                        "reason": reason,
                        "is_local": is_local,
                        "source": source,
                        "is_aggregator": source in _AGGREGATOR_IDENTIFIERS,
                    }
                )

            print(f"{len(rows)} human-decided rows scored (excluding digest auto-approvals).\n")

            approved_scores = [r["score"] for r in rows if r["approved"]]
            rejected_scores = [r["score"] for r in rows if not r["approved"]]
            print("-- separation: approved/published vs rejected --")
            print(f"  approved/published: n={len(approved_scores)}  avg score={_avg(approved_scores):.1f}")
            print(f"  rejected:           n={len(rejected_scores)}  avg score={_avg(rejected_scores):.1f}")

            print("\n-- score-bucket breakdown (does a higher score mean more likely approved?) --")
            buckets = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]
            for lo, hi in buckets:
                bucket_rows = [r for r in rows if lo <= r["score"] < hi]
                if not bucket_rows:
                    continue
                approved_in_bucket = sum(1 for r in bucket_rows if r["approved"])
                pct = 100 * approved_in_bucket / len(bucket_rows)
                print(f"  [{lo:>3}-{hi - 1:<3}]  n={len(bucket_rows):<4} approved={pct:5.1f}%")

            print("\n-- local (Kazakhstan) vs not --")
            for is_local in (True, False):
                group = [r for r in rows if r["is_local"] == is_local]
                if not group:
                    continue
                approved_pct = 100 * sum(1 for r in group if r["approved"]) / len(group)
                print(
                    f"  is_local={is_local!s:<5} n={len(group):<4} "
                    f"historical approval rate={approved_pct:5.1f}%  avg new score={_avg([r['score'] for r in group]):.1f}"
                )

            print("\n-- by source (aggregator vs Telegram-origin vs other) --")
            sources = sorted({r["source"] for r in rows})
            for src in sources:
                group = [r for r in rows if r["source"] == src]
                approved_pct = 100 * sum(1 for r in group if r["approved"]) / len(group)
                print(
                    f"  {src:<20} n={len(group):<4} "
                    f"historical approval rate={approved_pct:5.1f}%  avg new score={_avg([r['score'] for r in group]):.1f}"
                )

            return 0
    finally:
        await engine.dispose()


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
