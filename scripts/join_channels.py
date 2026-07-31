"""
Join every already-seeded source channel with whichever Telethon session is
currently authorized (telethon_session/<TELETHON_SESSION>.session, or
TELETHON_SESSION_STRING if set).

seed_channels.py only joins a channel the first time it's inserted into the
DB — if you switch the userbot to a new Telegram account, the channels are
already in the DB, so seed_channels.py silently skips joining them under the
new account, and collection then fails for everything. This script re-joins
by username without touching the DB, so it's safe to re-run any time.

Channels added via a private invite link (no username stored) can't be
rejoined this way — the original invite link is required. Their names are
printed for you to rejoin manually with the new account.

Usage:
    python -m scripts.join_channels
"""
import asyncio

from telethon import TelegramClient
from telethon.errors import FloodWaitError, UserAlreadyParticipantError
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest

from src.core.config import Settings
from src.db.base import create_engine
from src.db.repositories.source_channel import SourceChannelRepository
from src.db.session import create_session_factory


def _build_client(settings: Settings) -> TelegramClient:
    if settings.TELETHON_SESSION_STRING:
        session = StringSession(settings.TELETHON_SESSION_STRING)
    else:
        session = f"telethon_session/{settings.TELETHON_SESSION}"
    return TelegramClient(session, settings.TELETHON_API_ID, settings.TELETHON_API_HASH)


async def main() -> None:
    settings = Settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    client = _build_client(settings)
    await client.connect()
    if not await client.is_user_authorized():
        print("Session not authorized. Run auth_telethon.py first.")
        await client.disconnect()
        await engine.dispose()
        return

    me = await client.get_me()
    print(f"Joining channels as: {me.first_name} (@{me.username})\n")

    no_username: list[str] = []
    joined = skipped = failed = 0

    try:
        async with session_factory() as session:
            repo = SourceChannelRepository(session)
            channels = await repo.get_active()

            for ch in channels:
                if not ch.username:
                    no_username.append(ch.name or str(ch.telegram_id))
                    continue
                try:
                    await client(JoinChannelRequest(ch.username))
                    print(f"  JOINED  @{ch.username}")
                    joined += 1
                    await asyncio.sleep(1.5)  # pace joins to avoid flood limits
                except UserAlreadyParticipantError:
                    print(f"  SKIP    @{ch.username} (already a member)")
                    skipped += 1
                except FloodWaitError as e:
                    wait = int(getattr(e, "seconds", 0) or 0)
                    print(f"  WARN    @{ch.username}: flood wait {wait}s — skipped")
                    failed += 1
                except Exception as e:
                    print(f"  ERROR   @{ch.username}: {e}")
                    failed += 1
    finally:
        await client.disconnect()
        await engine.dispose()

    print(f"\nDone. joined={joined} already_member={skipped} failed={failed}")
    if no_username:
        print(
            f"\n{len(no_username)} channel(s) were added via private invite link and "
            "have no username, so they can't be auto-rejoined. Rejoin these manually "
            "with the new account using their original invite links:"
        )
        for name in no_username:
            print(f"  - {name}")


if __name__ == "__main__":
    asyncio.run(main())
