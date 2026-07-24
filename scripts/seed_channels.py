"""
Seed source channels from Telegram usernames.

Usage:
    python -m scripts.seed_channels

Resolves each username to its real Telegram channel ID via Telethon,
then inserts (or skips existing) rows into source_channels.
"""

import asyncio
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Channel titles include Cyrillic/emoji; force UTF-8 so printing them on a
# Windows console (cp1252) doesn't raise UnicodeEncodeError.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from telethon import TelegramClient
from telethon.tl.functions.channels import GetFullChannelRequest, JoinChannelRequest
from telethon.tl.functions.messages import (
    CheckChatInviteRequest,
    ImportChatInviteRequest,
)
from telethon.errors import (
    FloodWaitError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    UserAlreadyParticipantError,
)
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.config import Settings
from src.db.base import create_engine
from src.db.session import create_session_factory
from src.db.models.source_channel import SourceChannel
from src.db.repositories.source_channel import SourceChannelRepository

SOURCE_CHANNELS = [
    {"username": "logic_aktau_bil",        "name": "Logic Aktau BIL (test)"},
    {"username": "bilopportunities",       "name": "Bil Opportunities"},
    {"username": "uppertunity",            "name": "Uppertunity"},
    {"username": "astana_hub",             "name": "Astana Hub"},
    {"username": "startup_course_com",     "name": "Startup Course"},
    {"username": "mentoria_organization",  "name": "Mentoria Organization"},
    {"username": "myextrakz",              "name": "MyExtra KZ"},
    {"username": "edu_strategies",         "name": "Edu Strategies"},
    {"username": "IvyLeaguesStudent",      "name": "Ivy League Student"},
    {"username": "jasa_project",           "name": "JASA Project"},
    {"username": "youthfinance",           "name": "Youth Finance"},
    {"username": "Saubolopps",             "name": "Saubol Opportunities"},
    {"username": "Portfolio_Lab",          "name": "Portfolio Lab"},

    # --- Added 2026-07-24: second batch of source channels ---
    # (jasa_project, myextrakz, startup_course_com, mentoria_organization,
    #  Saubolopps, bilopportunities from the same batch are already listed above.)
    {"username": "studygrants",            "name": "StudyGrants"},
    {"username": "opportunitiesalarm",     "name": "Возможности для школьников"},
    {"username": "grants_scholarships",    "name": "grants.kz"},
    {"username": "launchzonehub",          "name": "LaunchZone"},
    {"username": "cabcchub",               "name": "CABCC"},
    {"username": "econ_for_teens",         "name": "ECON for TEENS"},
    {"username": "grantscholar",           "name": "Гранты/Стипендии"},
    {"username": "Ushqynkz",               "name": "Ushqyn"},
    {"username": "opportunities_zula",     "name": "Opportunities with Zula"},
    {"username": "nextstepuni",            "name": "Next Step Uni"},
    {"username": "airiseproject",          "name": "AIRISE Project"},
    {"username": "AI_Startify_Kazakhstan", "name": "AI Startify Incubator (KZ)"},
    {"username": "founderstackk",          "name": "Founders Stack"},
    {"username": "thedecentrathon",        "name": "Decentrathon"},
    {"username": "self_construction1",     "name": "Профориентация/стажировки/курсы"},
    {"username": "jasimpact",              "name": "JasImpact Hackathon"},
    {"username": "oppo4you",               "name": "Opportunity for you (FutureToday.KZ)"},
    {"username": "NISolympiads19",         "name": "Олимпиады и КНП в НИШ"},
    {"username": "localimpacthackaton",    "name": "Local Impact Hub"},
    {"username": "caassevents",            "name": "CAASS Events"},
    {"username": "feeledu",                "name": "FeelEdu"},
    {"username": "UniJol",                 "name": "UniJol"},
    {"username": "nucleus_borziyon",       "name": "NUcleus"},
    {"username": "ShineYourCV",            "name": "Shine Your CV"},
    {"username": "steppeforward",          "name": "Steppe Forward"},
    # Private invite links — no username; joined via ImportChatInviteRequest.
    # name is filled in from the resolved channel title.
    {"invite_link": "https://t.me/+NfgWEYGdCDVhMTYy"},
    {"invite_link": "https://t.me/+vvWaZe23A7xjZWZi"},
]

# Private invite links look like t.me/+HASH or t.me/joinchat/HASH — get_entity()
# can't resolve those, so they need ImportChatInviteRequest instead.
_INVITE_RE = re.compile(r"t\.me/(?:\+|joinchat/)([\w-]+)")


async def _resolve_invite(client: TelegramClient, invite_hash: str):
    """Join (or, if already a member, inspect) a private invite link and return
    the channel entity. Joining is required so messages flow to this account."""
    try:
        updates = await client(ImportChatInviteRequest(invite_hash))
        return updates.chats[0]
    except UserAlreadyParticipantError:
        result = await client(CheckChatInviteRequest(invite_hash))
        return result.chat


async def seed(settings: Settings, session_factory: async_sessionmaker) -> None:
    session_path = f"telethon_session/{settings.TELETHON_SESSION}"
    client = TelegramClient(session_path, settings.TELETHON_API_ID, settings.TELETHON_API_HASH)
    await client.start()
    print("Telethon connected.\n")

    async with session_factory() as session:
        repo = SourceChannelRepository(session)

        for ch in SOURCE_CHANNELS:
            username = ch.get("username")
            invite_link = ch.get("invite_link")
            label = f"@{username}" if username else (invite_link or ch.get("name", "?"))
            try:
                if invite_link:
                    match = _INVITE_RE.search(invite_link)
                    if not match:
                        print(f"  ERROR {label}: not a valid invite link")
                        continue
                    try:
                        entity = await _resolve_invite(client, match.group(1))
                    except (InviteHashExpiredError, InviteHashInvalidError) as e:
                        print(f"  ERROR {label}: invite link unusable ({type(e).__name__})")
                        continue
                else:
                    entity = await client.get_entity(username)

                telegram_id = entity.id
                name = ch.get("name") or getattr(entity, "title", None) or label

                # Telegram channel IDs from get_entity are bare; broadcast channels
                # are stored as negative in Bot API: -(1000000000000 + id)
                # Telethon returns the bare positive peer id for channels.
                # Store the bare id; collector uses Telethon which also gives bare ids.
                existing = await repo.list(telegram_id=telegram_id)
                if existing:
                    print(f"  SKIP  {label} (id={telegram_id}) -- already in DB")
                    continue

                # The userbot only receives NewMessage events for channels its
                # account is subscribed to, so join public channels here (invite
                # links were already joined during resolution above).
                if username:
                    try:
                        await client(JoinChannelRequest(username))
                    except FloodWaitError as e:
                        wait = int(getattr(e, "seconds", 0) or 0)
                        if 0 < wait <= 300:
                            print(f"  WAIT  {label}: flood wait {wait}s, sleeping then retrying join")
                            await asyncio.sleep(wait + 1)
                            await client(JoinChannelRequest(username))
                        else:
                            print(f"  WARN  {label}: flood wait {wait}s too long — recorded but NOT joined")

                channel = SourceChannel(
                    telegram_id=telegram_id,
                    name=name,
                    username=username,
                    active=True,
                )
                await repo.save(channel)
                print(f"  ADD   {label} -> id={telegram_id}  ({name})")
                await asyncio.sleep(1.5)  # pace joins to avoid Telegram flood limits

            except FloodWaitError as e:
                print(f"  WARN  {label}: flood wait {int(getattr(e, 'seconds', 0) or 0)}s — skipped")
            except Exception as e:
                print(f"  ERROR {label}: {e}")

        await session.commit()

    await client.disconnect()
    print("\nDone.")


async def main() -> None:
    settings = Settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        await seed(settings, session_factory)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
