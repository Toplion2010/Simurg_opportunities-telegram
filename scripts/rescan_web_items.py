"""
Repair web-sourced rows ingested before the classify + funding fixes.

Usage:
    python -m scripts.rescan_web_items [--apply]

Runs read-only by default and prints exactly what it would change. Pass
--apply to commit.

Two separate problems, two different remedies -- and neither deletes anything a
human has acted on:

  1. Opportunities created with category=None / relevance=None. They render as
     "Unknown" with no star line, and NULL relevance sorts LAST in
     get_pending, so they sit behind every Telegram item forever. These are
     re-classified IN PLACE from their stored title and description. No delete,
     no re-fetch, no duplicate.

  2. Listings rejected as unaffordable before the funding second look existed.
     Those left a raw_messages row and no Opportunity, and that row is what
     stops them being fetched again. Deleting those childless rows lets the
     next scan re-examine them against the official site.

Scope guards, deliberately narrow:
  * only rows whose source_channel.kind = 'web'
  * only opportunities still status='pending' -- anything approved, published
    or rejected by an admin is never touched
  * only raw_messages with NO opportunities attached
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

from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from src.collector.web.classify import category_from_parts, relevance_from_parts
from src.core.config import Settings
from src.core.enums import OpportunityStatus
from src.db.base import create_engine
from src.db.models.opportunity import Opportunity
from src.db.models.raw_message import RawMessage
from src.db.models.source_channel import KIND_WEB, SourceChannel
from src.db.session import create_session_factory


async def run(apply: bool) -> int:
    settings = Settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    try:
        async with session_factory() as session:
            web_ids = (
                await session.execute(
                    select(SourceChannel.id).where(SourceChannel.kind == KIND_WEB)
                )
            ).scalars().all()
            if not web_ids:
                print("No web sources seeded — nothing to do.")
                return 0

            # --- 1: re-classify pending rows in place --------------------
            stmt = (
                select(Opportunity)
                .join(RawMessage, Opportunity.raw_message_id == RawMessage.id)
                .where(
                    RawMessage.source_channel_id.in_(web_ids),
                    Opportunity.status == OpportunityStatus.pending,
                )
                .options(selectinload(Opportunity.raw_message))
            )
            opps = (await session.execute(stmt)).scalars().all()

            fixed = 0
            for opp in opps:
                changed = False
                # Overwrite, not just fill. Rows created before the
                # classifier's word-boundary fix carry actively WRONG values --
                # anything containing "International" was filed as an
                # Internship. Safe here because the scope is pending,
                # unreviewed, web-sourced rows only, and the old value is
                # printed alongside the new one so the change is auditable.
                category = category_from_parts(opp.title, opp.description)
                if category is not None and category != opp.category:
                    was = opp.category.value if opp.category else "None"
                    print(f"  CATEGORY  #{opp.id:<5} {was} -> {category.value}")
                    opp.category = category
                    changed = True
                if opp.relevance is None:
                    opp.relevance, opp.relevance_reason = relevance_from_parts(
                        opp.title, opp.description
                    )
                    changed = True
                if changed:
                    fixed += 1
                    cat = opp.category.value if opp.category else "Unknown"
                    print(
                        f"  RECLASSIFY #{opp.id:<5} {cat:<14} "
                        f"{opp.relevance}/5  {(opp.title or '')[:44]}"
                    )

            print(f"\n  {fixed} of {len(opps)} pending web opportunities re-classified.")

            # --- 2: free the rejects for a second look -------------------
            child_count = (
                select(func.count(Opportunity.id))
                .where(Opportunity.raw_message_id == RawMessage.id)
                .scalar_subquery()
            )
            orphan_stmt = select(RawMessage.id).where(
                RawMessage.source_channel_id.in_(web_ids), child_count == 0
            )
            orphans = (await session.execute(orphan_stmt)).scalars().all()
            print(
                f"  {len(orphans)} rejected listings will be re-fetched "
                "(no opportunity was ever created from them)."
            )

            if not apply:
                print("\nDRY RUN — nothing written. Re-run with --apply to commit.")
                await session.rollback()
                return 0

            if orphans:
                await session.execute(
                    delete(RawMessage).where(RawMessage.id.in_(orphans))
                )
            await session.commit()
            print("\nApplied. The next webscan run will re-fetch the freed listings.")
            return 0
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(prog="rescan_web_items")
    parser.add_argument(
        "--apply", action="store_true", help="Commit the changes (default: dry run)."
    )
    return asyncio.run(run(parser.parse_args().apply))


if __name__ == "__main__":
    sys.exit(main())
