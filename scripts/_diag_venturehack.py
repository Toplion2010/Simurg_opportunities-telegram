import asyncio, os, sys
from datetime import datetime, timezone
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

async def run():
    settings = Settings()
    engine = create_engine(settings)
    sf = create_session_factory(engine)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    async with sf() as session:
        stmt = select(Opportunity).where(Opportunity.status == OpportunityStatus.approved)
        approved = (await session.execute(stmt)).scalars().all()
        print(f"now(utc)={now} start_of_day={start_of_day}")
        print(f"currently APPROVED (awaiting publish), count={len(approved)}:")
        for o in approved:
            print(f"  id={o.id} title={o.title!r} scheduled_at={o.scheduled_at} created_at={o.created_at}")
        stmt2 = select(Opportunity).where(
            Opportunity.status == OpportunityStatus.published,
            Opportunity.published_at >= start_of_day,
        )
        pub_today = (await session.execute(stmt2)).scalars().all()
        print(f"\npublished TODAY so far: {len(pub_today)} (cap={settings.DAILY_PUBLISH_CAP})")
        for o in pub_today:
            print(f"  id={o.id} title={o.title!r} published_at={o.published_at}")
    await engine.dispose()

asyncio.run(run())
