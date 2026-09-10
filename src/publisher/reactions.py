import random

from aiogram import Bot
from aiogram.types import ReactionTypeEmoji
from telethon import TelegramClient
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji

from src.core.logging import get_logger

logger = get_logger(__name__)

EMOJI_POOL = ["\U0001F525", "❤"]  # fire, heart


async def add_reactions(
    bot: Bot,
    chat_id: int,
    message_id: int,
    telethon_client: TelegramClient | None,
) -> None:
    """Best-effort engagement boost on a just-published post: one reaction
    from the bot, one from the userbot's personal account (if connected),
    each an independently random pick from EMOJI_POOL -- landing on the same
    emoji twice is fine. Never raises -- publishing has already succeeded by
    the time this runs, so a reaction failure (bot lacks the permission, the
    account isn't a member of the channel, a transient API error) must not
    turn a successful publish into a reported failure."""
    bot_emoji = random.choice(EMOJI_POOL)
    try:
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=bot_emoji)],
        )
    except Exception as e:
        logger.warning(
            "bot_reaction_failed", chat_id=chat_id, message_id=message_id, error=str(e)
        )

    if telethon_client is None or not telethon_client.is_connected():
        return

    user_emoji = random.choice(EMOJI_POOL)
    try:
        entity = await telethon_client.get_entity(chat_id)
        await telethon_client(
            SendReactionRequest(
                peer=entity, msg_id=message_id, reaction=[ReactionEmoji(emoticon=user_emoji)]
            )
        )
    except Exception as e:
        logger.warning(
            "user_reaction_failed", chat_id=chat_id, message_id=message_id, error=str(e)
        )
