"""Best-effort emoji reactions on freshly posted messages: one from the bot,
one from the personal Telegram account (the same userbot session Simurg's
main pipeline uses to scrape source channels, reused here so no separate
login is needed). Never raises -- posting has already succeeded by the time
this runs, and a reaction failure must not turn that into a reported
failure."""

from __future__ import annotations

import logging
import os
import random

import requests

import config

logger = logging.getLogger(__name__)

EMOJI_POOL = ["\U0001F525", "❤"]  # fire, heart


def _react_as_bot(token: str, chat_id: str, message_id: int, emoji: str) -> None:
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/setMessageReaction",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "reaction": [{"type": "emoji", "emoji": emoji}],
            },
            timeout=config.REQUEST_TIMEOUT_SECONDS,
        )
        if not response.ok:
            logger.warning(
                "telegram: setMessageReaction failed (%s): %s",
                response.status_code, response.text,
            )
    except requests.RequestException:
        logger.warning("telegram: setMessageReaction request failed", exc_info=True)


def _resolve_peer(chat_id: str) -> int | str:
    try:
        return int(chat_id)
    except ValueError:
        return chat_id


def _react_as_user(chat_id: str, message_id: int, emoji: str) -> None:
    """Reacts using the personal account, if the TELETHON_* secrets are
    present in the environment. Silently a no-op otherwise -- this bonus
    reaction is optional and must not block the bot's own reaction."""
    api_id = os.environ.get("TELETHON_API_ID")
    api_hash = os.environ.get("TELETHON_API_HASH")
    session_string = os.environ.get("TELETHON_SESSION_STRING")
    if not api_id or not api_hash or not session_string:
        return

    try:
        from telethon.sessions import StringSession
        from telethon.sync import TelegramClient
        from telethon.tl.functions.messages import SendReactionRequest
        from telethon.tl.types import ReactionEmoji

        with TelegramClient(StringSession(session_string), int(api_id), api_hash) as client:
            entity = client.get_entity(_resolve_peer(chat_id))
            client(
                SendReactionRequest(
                    peer=entity, msg_id=message_id, reaction=[ReactionEmoji(emoticon=emoji)]
                )
            )
    except Exception:
        logger.warning("telethon: user reaction failed", exc_info=True)


def react(token: str, chat_id: str, message_id: int) -> None:
    """Add a bot reaction and (if configured) a userbot reaction, picking
    two different emoji from the pool so the post doesn't look like a bot
    talking to itself."""
    bot_emoji = random.choice(EMOJI_POOL)
    _react_as_bot(token, chat_id, message_id, bot_emoji)

    user_emoji = next((e for e in EMOJI_POOL if e != bot_emoji), bot_emoji)
    _react_as_user(chat_id, message_id, user_emoji)
