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
    telethon_clients: list[TelegramClient] | None = None,
) -> None:
    """Best-effort engagement boost on a just-published post: one reaction
    from the bot, plus one from each connected personal account (the primary
    userbot and, if configured, a second one) -- each an independently
    random pick from EMOJI_POOL, landing on the same emoji twice is fine.
    Never raises -- publishing has already succeeded by the time this runs,
    so a reaction failure (bot lacks the permission, an account isn't a
    member of the channel, a transient API error) must not turn a successful
    publish into a reported failure."""
    try:
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=random.choice(EMOJI_POOL))],
        )
    except Exception as e:
        logger.warning(
            "bot_reaction_failed", chat_id=chat_id, message_id=message_id, error=str(e)
        )

    for client in telethon_clients or []:
        if not client.is_connected():
            continue
        try:
            entity = await client.get_entity(chat_id)
            await client(
                SendReactionRequest(
                    peer=entity,
                    msg_id=message_id,
                    reaction=[ReactionEmoji(emoticon=random.choice(EMOJI_POOL))],
                )
            )
        except Exception as e:
            logger.warning(
                "user_reaction_failed", chat_id=chat_id, message_id=message_id, error=str(e)
            )
