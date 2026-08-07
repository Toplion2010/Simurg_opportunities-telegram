"""Render cards for real opportunities without publishing them.

Exercises the exact publish-time rendering path — Gemini background generation,
model-rotation fallback, grammar engine, HTML/CSS, Chromium screenshot — and
writes the JPEGs to disk instead of sending them to a channel. Lets the card's
appearance be checked (and the Gemini fallback chain verified) without touching
the review queue or posting anything.

Usage:
    python -m scripts.render_preview [count] [out_dir]
"""
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

from src.core.logging import get_logger, setup_logging
from src.db.base import create_engine
from src.db.models.opportunity import Opportunity
from src.db.session import create_session_factory
from src.core.config import Settings

logger = get_logger(__name__)


async def run(count: int, out_dir: Path) -> None:
    settings = Settings()
    setup_logging(settings.ENVIRONMENT)
    out_dir.mkdir(parents=True, exist_ok=True)

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    try:
        async with session_factory() as session:
            # Newest first: the most recently collected posts are the ones whose
            # rendering the admin is actually about to look at.
            stmt = (
                select(Opportunity)
                .where(Opportunity.title.is_not(None))
                .order_by(Opportunity.created_at.desc())
                .limit(count)
            )
            opps = list((await session.execute(stmt)).scalars().all())

        if not opps:
            logger.warning("no_opportunities_to_render")
            return

        from src.publisher.image_gen import generate_card

        ok = failed = 0
        for opp in opps:
            try:
                img = await generate_card(opp)
                path = out_dir / f"card_{opp.id}.jpg"
                path.write_bytes(img)
                ok += 1
                logger.info("preview_rendered", opp_id=opp.id, title=opp.title, bytes=len(img))
            except Exception as e:  # noqa: BLE001
                failed += 1
                logger.exception("preview_render_failed", opp_id=opp.id, error=str(e))

        logger.info("preview_complete", rendered=ok, failed=failed, out_dir=str(out_dir))
    finally:
        await engine.dispose()


def main() -> None:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("previews")
    asyncio.run(run(count, out_dir))


if __name__ == "__main__":
    main()
