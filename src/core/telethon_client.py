from telethon import TelegramClient
from telethon.sessions import StringSession

from src.core.config import Settings
from src.core.logging import get_logger

logger = get_logger(__name__)


def build_telethon_client(
    settings: Settings,
    session_string: str = "",
    session_name: str = "",
) -> TelegramClient:
    """Same session-selection rule used everywhere the userbot connects
    (src/collector/userbot.py, src/routines/batch_processor.py): a string
    session (CI) takes priority over the on-disk file session (local dev).
    `session_string`/`session_name` default to the primary account's
    settings, so this also builds the optional second (reaction-only)
    account's client when passed its TELETHON_SESSION_STRING_2/SESSION_2."""
    session_string = session_string or settings.TELETHON_SESSION_STRING
    session_name = session_name or settings.TELETHON_SESSION
    session = StringSession(session_string) if session_string else f"telethon_session/{session_name}"
    return TelegramClient(session, settings.TELETHON_API_ID, settings.TELETHON_API_HASH)


async def _connect_reaction_client(
    settings: Settings, session_string: str, session_name: str, label: str
) -> TelegramClient | None:
    client = build_telethon_client(settings, session_string, session_name)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.warning("telethon_not_authorized", account=label, hint="skipping its reactions")
            await client.disconnect()
            return None
        return client
    except Exception:
        logger.warning("telethon_connect_failed", account=label, hint="skipping its reactions")
        return None


async def connect_second_reaction_client(settings: Settings) -> TelegramClient | None:
    """Connects the optional second personal account, used only to react to
    published posts. None if it isn't configured or fails to connect --
    never blocks publishing."""
    if not settings.TELETHON_SESSION_STRING_2:
        return None
    return await _connect_reaction_client(
        settings, settings.TELETHON_SESSION_STRING_2, settings.TELETHON_SESSION_2, "second"
    )


async def connect_all_reaction_clients(settings: Settings) -> list[TelegramClient]:
    """Connects every configured personal account used only to react to
    published posts: the primary userbot account plus the optional second
    one. For a context that already has the primary account connected for
    another purpose (e.g. batch_processor.py's fetch client), reuse that
    one directly and call connect_second_reaction_client() instead of this."""
    if not settings.TELETHON_API_ID:
        return []

    clients = []
    primary = await _connect_reaction_client(
        settings, settings.TELETHON_SESSION_STRING, settings.TELETHON_SESSION, "primary"
    )
    if primary is not None:
        clients.append(primary)

    second = await connect_second_reaction_client(settings)
    if second is not None:
        clients.append(second)

    return clients


async def disconnect_all(clients: list[TelegramClient]) -> None:
    for client in clients:
        try:
            await client.disconnect()
        except Exception:
            logger.debug("telethon_disconnect_failed")
