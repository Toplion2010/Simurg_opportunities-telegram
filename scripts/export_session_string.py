"""Export the local telethon_session/*.session file as a portable session string.

Hosts with an ephemeral filesystem (Railway, Fly, Heroku) lose the .session file on
every redeploy, so the session travels as an env var instead.

Usage:
    python -m scripts.export_session_string

Copy the printed value into TELETHON_SESSION_STRING on the host. Treat it like a
password: it grants full access to the Telegram account.
"""
import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession

from src.core.config import Settings


async def main() -> None:
    settings = Settings()
    session_path = f"telethon_session/{settings.TELETHON_SESSION}"

    client = TelegramClient(
        session_path,
        settings.TELETHON_API_ID,
        settings.TELETHON_API_HASH,
    )
    await client.connect()

    if not await client.is_user_authorized():
        print("Local session is not authorized. Run auth_telethon.py first.")
        await client.disconnect()
        return

    me = await client.get_me()
    session_string = StringSession.save(client.session)
    await client.disconnect()

    print(f"\nAuthorized as: {me.first_name} (@{me.username})")
    print("\nTELETHON_SESSION_STRING=" + session_string)
    print("\nSet this on your host. Anyone holding it can act as this Telegram account.\n")


if __name__ == "__main__":
    asyncio.run(main())
