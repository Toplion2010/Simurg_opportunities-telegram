from telethon import TelegramClient
from telethon.sessions import StringSession

from src.core.config import Settings


def build_telethon_client(settings: Settings) -> TelegramClient:
    """Same session-selection rule used everywhere else the userbot connects
    (src/collector/userbot.py, src/routines/batch_processor.py): a string
    session (CI) takes priority over the on-disk file session (local dev)."""
    if settings.TELETHON_SESSION_STRING:
        session = StringSession(settings.TELETHON_SESSION_STRING)
    else:
        session = f"telethon_session/{settings.TELETHON_SESSION}"
    return TelegramClient(session, settings.TELETHON_API_ID, settings.TELETHON_API_HASH)
