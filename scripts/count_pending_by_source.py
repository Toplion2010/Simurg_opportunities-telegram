"""Read-only smoke test for the Telegram/Online queue split
(src/db/repositories/opportunity.py's get_pending/count_pending
source_kind filter, used by the bot's two "📱 Telegram Queue" /
"🌐 Online Queue" buttons) -- confirms telegram-count + web-count adds up
to the unfiltered total, against the real database.

Usage:
    python -m scripts.count_pending_by_source
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from src.core.config import Settings
from src.db.base import create_engine
from src.db.repositories.opportunity import OpportunityRepository
from src.db.session import create_session_factory


async def run() -> int:
    settings = Settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    try:
        async with session_factory() as session:
            repo = OpportunityRepository(session)
            total = await repo.count_pending()
            telegram = await repo.count_pending(source_kind="telegram")
            web = await repo.count_pending(source_kind="web")

            print(f"all:      {total}")
            print(f"telegram: {telegram}")
            print(f"web:      {web}")
            print(f"telegram + web == all: {telegram + web == total}")
            return 0
    finally:
        await engine.dispose()


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
