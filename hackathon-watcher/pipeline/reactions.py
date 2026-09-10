"""Best-effort emoji reactions on freshly posted messages: one from the bot,
plus one from each configured personal account (the same userbot session(s)
Simurg's main pipeline uses to scrape source channels, reused here so no
separate login is needed). Never raises -- posting has already succeeded by
the time this runs, and a reaction failure must not turn that into a
reported failure."""

from __future__ import annotations

import logging
import os
import random

import requests

import config

logger = logging.getLogger(__name__)

EMOJI_POOL = ["\U0001F525", "❤"]  # fire, heart

# Env var pairs for each personal account this bot may react as. A second
# account is entirely optional -- unset TELETHON_SESSION_STRING_2 and it's
# simply skipped.
_SESSION_STRING_ENV_VARS = ["TELETHON_SESSION_STRING", "TELETHON_SESSION_STRING_2"]


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


def _react_as_user(chat_id: str, message_id: int, emoji: str, api_id: str, api_hash: str, session_string: str) -> None:
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


def _configured_accounts() -> list[str]:
    """Session strings for every personal account configured via the
    TELETHON_* env vars -- empty if TELETHON_API_ID/HASH aren't set."""
    api_id = os.environ.get("TELETHON_API_ID")
    api_hash = os.environ.get("TELETHON_API_HASH")
    if not api_id or not api_hash:
        return []
    return [os.environ[k] for k in _SESSION_STRING_ENV_VARS if os.environ.get(k)]


def react(token: str, chat_id: str, message_id: int) -> None:
    """Add a bot reaction and one reaction per configured personal account,
    each an independently random pick from the pool -- landing on the same
    emoji twice is fine."""
    _react_as_bot(token, chat_id, message_id, random.choice(EMOJI_POOL))

    api_id = os.environ.get("TELETHON_API_ID")
    api_hash = os.environ.get("TELETHON_API_HASH")
    for session_string in _configured_accounts():
        _react_as_user(chat_id, message_id, random.choice(EMOJI_POOL), api_id, api_hash, session_string)
