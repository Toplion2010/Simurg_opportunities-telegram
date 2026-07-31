"""
Run this ONCE to authorize your Telegram account for the userbot.
It will ask for your phone number and the OTP code Telegram sends you.

Reads TELETHON_API_ID / TELETHON_API_HASH / TELETHON_SESSION from .env (via
Settings) instead of hardcoding them, so credentials never live in source.

Usage:
    .venv/bin/python auth_telethon.py
"""
import asyncio
from telethon import TelegramClient

from src.core.config import Settings


async def main():
    settings = Settings()
    session = f"telethon_session/{settings.TELETHON_SESSION}"
    client = TelegramClient(session, settings.TELETHON_API_ID, settings.TELETHON_API_HASH)
    await client.start()
    me = await client.get_me()
    print(f"\n✅ Authorized as: {me.first_name} (@{me.username})")
    print("Session saved. You can now run the bot.\n")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
