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
from src.db.base import create_engine
from src.db.models.opportunity import Opportunity
from src.db.session import create_session_factory


async def run():
    settings = Settings()
    print(f"DEST_CHANNEL_ID_HACKATHON = {settings.DEST_CHANNEL_ID_HACKATHON!r}")
    engine = create_engine(settings)
    sf = create_session_factory(engine)
    async with sf() as session:
        stmt = select(Opportunity).where(Opportunity.title.ilike("%VentureHack%"))
        opps = (await session.execute(stmt)).scalars().all()
        for o in opps:
            print(
                f"id={o.id} status={o.status} category={o.category} location={o.location!r} "
                f"organizer={o.organizer!r} audience={o.audience} "
                f"scheduled_at={o.scheduled_at} published_at={o.published_at} "
                f"created_at={o.created_at} similarity_hash={o.similarity_hash}"
            )
    await engine.dispose()


asyncio.run(run())
