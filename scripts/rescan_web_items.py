"""
Repair pending opportunities scored or classified under an earlier rubric.

Usage:
    python -m scripts.rescan_web_items [--apply]

Runs read-only by default and prints exactly what it would change. Pass
--apply to commit.

Three separate problems, three different remedies -- and neither deletes
anything a human has acted on:

  1. RELEVANCE, for EVERY pending row, both sources. The 1-10 rubric
     (src/core/scoring.py) replaced two older, incompatible schemes at once:
     Telegram rows carried a 1-5 LLM judgement that is simply a different
     scale now, and web rows carried a 1-5 keyword score with no reachability
     signal in it at all. Neither means what the new number means, so every
     pending row is rescored, not just the ones that happen to be NULL.

     Recomputed from the row's own stored TEXT (location, cost, eligibility)
     -- an Opportunity does not retain the source's structured is_online /
     cost_amount fields the way a fresh WebItem does, so this is intentionally
     the same lower-fidelity derivation the Telegram pipeline itself uses
     (src/core/scoring.infer_is_online / infer_cost_amount), even for rows
     that originally came from a web source with better data available. A
     freshly-scraped item is still scored at full fidelity in to_dto.py; this
     script only ever touches what a repair CAN reach.

  2. CATEGORY, web-sourced rows only. Rows created with category=None
     (rendered "Unknown") or an actively wrong one (the pre-fix classifier
     matched "intern" inside "International") are re-classified in place from
     stored title/description via the web catalogs' own taxonomy rules
     (src/collector/web/classify.py). NOT applied to Telegram rows: that
     module's title-shape rules are built for catalog LISTING titles
     ("...Academy", "...Challenge") and are explicitly documented as too
     loose for free-text Telegram posts. A pre-fix Telegram row with a wrong
     category is a real, separate gap this script does not close.

  3. Listings rejected as unaffordable before the funding second look
     existed. Those left a raw_messages row and no Opportunity, and that row
     is what stops them being fetched again. Deleting those childless rows
     lets the next scan re-examine them against the official site.

Scope guards, deliberately narrow:
  * only opportunities still status='pending' -- anything approved, published
    or rejected by an admin is never touched
  * category repair (2) only touches rows from a source_channel.kind='web'
  * the childless-row deletion (3) only touches raw_messages from web sources
    with NO opportunities attached
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

from src.collector.web.classify import category_from_parts
from src.core.config import Settings
from src.core.enums import OpportunityStatus
from src.core.scoring import infer_cost_amount, infer_is_online
from src.core.scoring import score as reachability_score
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
            web_ids = set(
                (
                    await session.execute(
                        select(SourceChannel.id).where(SourceChannel.kind == KIND_WEB)
                    )
                )
                .scalars()
                .all()
            )

            # --- 1 & 2: repair every pending row in place -----------------
            stmt = (
                select(Opportunity)
                .join(RawMessage, Opportunity.raw_message_id == RawMessage.id)
                .where(Opportunity.status == OpportunityStatus.pending)
                .options(selectinload(Opportunity.raw_message))
            )
            opps = (await session.execute(stmt)).scalars().all()

            rescored = recategorized = 0
            for opp in opps:
                source_channel_id = (
                    opp.raw_message.source_channel_id if opp.raw_message else None
                )
                is_web = source_channel_id in web_ids

                if is_web:
                    # Overwrite, not just fill -- pre-fix rows carry actively
                    # WRONG categories (see docstring, problem 2), and the
                    # scope here (pending, unreviewed, web-only) makes that
                    # safe. Old value printed alongside the new one.
                    category = category_from_parts(opp.title, opp.description)
                    if category is not None and category != opp.category:
                        was = opp.category.value if opp.category else "None"
                        print(f"  CATEGORY   #{opp.id:<5} {was} -> {category.value}")
                        opp.category = category
                        recategorized += 1

                # Always recomputed, for both sources -- see docstring,
                # problem 1. The old value (whatever scale it happened to be
                # on) is printed so a surprising jump is auditable.
                old_relevance = opp.relevance
                is_online = infer_is_online(opp.location)
                cost_amount = infer_cost_amount(opp.cost)
                score_text = " ".join(
                    filter(None, [opp.title, opp.description, opp.eligibility, opp.organizer])
                )
                opp.relevance, opp.relevance_reason = reachability_score(
                    is_online, cost_amount, opp.location, score_text
                )
                if opp.relevance != old_relevance:
                    rescored += 1
                    old_label = str(old_relevance) if old_relevance is not None else "None"
                    print(
                        f"  RELEVANCE  #{opp.id:<5} {old_label} -> {opp.relevance}/10  "
                        f"({opp.relevance_reason})  {(opp.title or '')[:40]}"
                    )

            print(
                f"\n  {rescored} of {len(opps)} pending opportunities rescored, "
                f"{recategorized} web-sourced rows re-categorized."
            )

            # --- 3: free the pre-fix rejects for a second look ------------
            orphans: list[int] = []
            if web_ids:
                child_count = (
                    select(func.count(Opportunity.id))
                    .where(Opportunity.raw_message_id == RawMessage.id)
                    .scalar_subquery()
                )
                orphan_stmt = select(RawMessage.id).where(
                    RawMessage.source_channel_id.in_(web_ids), child_count == 0
                )
                orphans = list((await session.execute(orphan_stmt)).scalars().all())
            print(
                f"  {len(orphans)} rejected listings will be re-fetched "
                "(no opportunity was ever created from them)."
            )

            if not apply:
                print("\nDRY RUN — nothing written. Re-run with --apply to commit.")
                await session.rollback()
                return 0

            if orphans:
                await session.execute(delete(RawMessage).where(RawMessage.id.in_(orphans)))
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
