"""
Run this ONCE to authorize your Telegram account for the userbot.
It will ask for your phone number and the OTP code Telegram sends you.

Usage:
    .venv/bin/python auth_telethon.py
"""
import asyncio
from telethon import TelegramClient

API_ID = 27232743
API_HASH = "cea02c328e3756bad9aceabc182fd94f"
SESSION = "telethon_session/simurg"


async def main():
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    print(f"\n✅ Authorized as: {me.first_name} (@{me.username})")
    print("Session saved. You can now run the bot.\n")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
