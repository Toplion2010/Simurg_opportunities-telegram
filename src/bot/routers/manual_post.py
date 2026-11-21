"""Admin's own posts: send any text/photo to the bot and it goes to the channel.

Flow:
  1. The admin sends (or forwards) a post to the bot. It is saved as a
     ``manual-draft:`` raw message -- inert, nothing processes it yet -- and the
     bot asks "🤖 Publish via AI / ✖ Discard".
  2. "Publish" flips it to ``manual:`` and unprocessed. That is all the handler
     does, so it stays far inside Vercel's 10 s budget.
  3. The next scheduled run (src/processor/manual.py) has the AI extract the
     card fields, auto-approves the result and publishes it like any other post.

Why a confirm tap instead of queueing straight away: FSM state lives in
MemoryStorage, which does not survive between Vercel invocations, so an answer
meant for "✏️ Edit" or "🔍 Search" can arrive here with no state. As a draft it
is harmless -- the admin just ignores the prompt.

This router must be included LAST: it catches every stateless private message
the other routers did not claim.
"""

from datetime import datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.callbacks.data import ManualPostAction
from src.core.logging import get_logger
from src.db.models.raw_message import RawMessage
from src.db.repositories.raw_message import RawMessageRepository

logger = get_logger(__name__)

router = Router(name="manual_post")

DRAFT_PREFIX = "manual-draft:"
QUEUED_PREFIX = "manual:"

# Shorter than this with no photo is almost certainly a stray reply (an edit
# value whose FSM state was lost), not a post.
_MIN_TEXT_CHARS = 20


def _keyboard(raw_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🤖 Publish via AI",
                    callback_data=ManualPostAction(raw_id=raw_id, action="publish").pack(),
                ),
                InlineKeyboardButton(
                    text="✖ Discard",
                    callback_data=ManualPostAction(raw_id=raw_id, action="discard").pack(),
                ),
            ]
        ]
    )


@router.message(StateFilter(None), F.chat.type == "private", F.text | F.caption)
async def receive_post(message: Message, session: AsyncSession) -> None:
    text = (message.text or message.caption or "").strip()
    if text.startswith("/"):
        return
    photo_id = message.photo[-1].file_id if message.photo else None
    if photo_id is None and len(text) < _MIN_TEXT_CHARS:
        return

    # external_id carries everything the processing step needs to report back
    # and to fetch the poster: "<prefix><chat>:<message>[:<file_id>]".
    external_id = f"{DRAFT_PREFIX}{message.chat.id}:{message.message_id}"
    if photo_id:
        external_id += f":{photo_id}"

    raw = await RawMessageRepository(session).create(
        source_channel_id=None,
        text=text,
        received_at=datetime.utcnow(),
        external_id=external_id[:200],
    )
    # Drafts are marked processed so no run touches them until confirmed.
    raw.processed = True
    await session.commit()
    logger.info("manual_post_drafted", raw_id=raw.id, chars=len(text), photo=bool(photo_id))

    await message.reply(
        "📝 Got your post. AI will turn it into a branded card and post it to the "
        "channel(s) on the next run.",
        reply_markup=_keyboard(raw.id),
    )


@router.callback_query(ManualPostAction.filter())
async def confirm_post(
    call: CallbackQuery,
    callback_data: ManualPostAction,
    session: AsyncSession,
) -> None:
    raw = await session.get(RawMessage, callback_data.raw_id)
    if raw is None or not (raw.external_id or "").startswith(DRAFT_PREFIX):
        await call.answer("Already handled.", show_alert=True)
        return

    if callback_data.action == "publish":
        raw.external_id = QUEUED_PREFIX + raw.external_id[len(DRAFT_PREFIX):]
        raw.processed = False
        reply = "⏳ Queued — AI will make the card and publish it on the next run."
        logger.info("manual_post_queued", raw_id=raw.id)
    else:
        raw.external_id = "manual-discarded:" + raw.external_id[len(DRAFT_PREFIX):]
        reply = "✖ Discarded."
        logger.info("manual_post_discarded", raw_id=raw.id)
    await session.commit()

    try:
        await call.answer()
        await call.message.edit_text(reply)
    except TelegramBadRequest as e:
        logger.info("stale_callback_ack_skipped", raw_id=callback_data.raw_id, error=str(e))
