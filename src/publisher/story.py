"""Posts a Telegram Story to all three Simurg channels for published
opportunities an admin starred ("📸 Story" button, src/bot/routers/queue.py).

Looks like Telegram's own "Share post to Story": the live channel post drawn
as a card (story_card.py) using the post's REAL photo, downloaded from the
message -- not a fresh generate_card() render, whose background is
non-deterministic and would differ from what's live. Tapping the card opens
the original post (InputMediaAreaChannelPost).

Stories are MTProto-only, so this goes through the Telethon userbot, not the
aiogram Bot. Requires that account to be an admin with the "Post Stories"
right on all three destination channels -- a one-time Telegram-side setup.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import TelegramClient
from telethon.tl.functions.stories import SendStoryRequest
from telethon.tl.types import (
    InputMediaAreaChannelPost,
    InputMediaUploadedPhoto,
    InputPrivacyValueAllowAll,
    MediaAreaCoordinates,
)
from telethon.utils import get_input_channel

from src.core.config import Settings
from src.core.exceptions import PublishError
from src.core.logging import get_logger
from src.core.notify import notify_admins
from src.db.models.opportunity import Opportunity
from src.db.repositories.opportunity import OpportunityRepository
from src.publisher import story_card

logger = get_logger(__name__)

# The only duration a non-Premium account may pass.
_STORY_PERIOD_SECONDS = 24 * 60 * 60
_CAPTION_LIMIT = 200


@dataclass
class StoryResult:
    succeeded: list[int] = field(default_factory=list)
    failed: list[tuple[int, str]] = field(default_factory=list)


def story_caption(opp: Opportunity, post_link: str | None = None) -> str:
    caption = f"✨ {(opp.title or 'Opportunity').strip()}"
    if opp.deadline:
        caption += f"\n⏳ {opp.deadline}"
    if not post_link:
        return caption[:_CAPTION_LIMIT]
    # Trim the text, never the link -- a cut-off link is a broken link.
    room = _CAPTION_LIMIT - len(post_link) - 1
    return f"{caption[:room]}\n{post_link}"


def post_link(channel, msg_id: int) -> str | None:
    # Only public channels have a t.me link; for a private one the tappable
    # card area still opens the post for subscribers.
    username = getattr(channel, "username", None)
    return f"https://t.me/{username}/{msg_id}" if username else None


def story_targets(settings: Settings) -> list[int]:
    # All three channels regardless of the opportunity's own audience/category
    # routing -- a starred story is meant to be seen everywhere. 0 = unset.
    targets = [
        settings.DEST_CHANNEL_ID_SCHOOL,
        settings.DEST_CHANNEL_ID_UNIVERSITY,
        settings.DEST_CHANNEL_ID_HACKATHON,
    ]
    return list(dict.fromkeys(c for c in targets if c))


async def post_story(settings: Settings, client: TelegramClient, opp: Opportunity) -> StoryResult:
    """Raises PublishError only when the photo can't be fetched or EVERY channel
    failed -- a partial success still counts as done (mirrors sender.py's
    publish()), so a channel missing the "Post Stories" right can't retry forever."""
    message = await client.get_messages(opp.published_chat_id, ids=opp.published_message_id)
    if message is None or message.photo is None:
        raise PublishError(
            f"Published message {opp.published_chat_id}/{opp.published_message_id} "
            f"for opportunity {opp.id} is gone or has no photo"
        )
    photo_bytes = await client.download_media(message, file=bytes)
    source = await client.get_entity(opp.published_chat_id)

    # Rendered and uploaded once, reused for every channel.
    img_bytes, box = await story_card.render_story_card(
        photo_bytes, getattr(source, "title", "") or "", opp
    )
    uploaded = await client.upload_file(img_bytes, file_name="story.jpg")
    media = InputMediaUploadedPhoto(file=uploaded)
    open_post_area = InputMediaAreaChannelPost(
        coordinates=MediaAreaCoordinates(x=box.x, y=box.y, w=box.w, h=box.h, rotation=0),
        channel=get_input_channel(source),
        msg_id=opp.published_message_id,
    )
    caption = story_caption(opp, post_link(source, opp.published_message_id))

    result = StoryResult()
    for chat_id in story_targets(settings):
        try:
            entity = await client.get_entity(chat_id)
            await client(
                SendStoryRequest(
                    peer=entity,
                    media=media,
                    media_areas=[open_post_area],
                    privacy_rules=[InputPrivacyValueAllowAll()],
                    caption=caption,
                    period=_STORY_PERIOD_SECONDS,
                )
            )
            result.succeeded.append(chat_id)
        except Exception as e:
            logger.exception("story_post_failed_channel", opp_id=opp.id, chat_id=chat_id, error=str(e))
            result.failed.append((chat_id, str(e)))

    if not result.succeeded:
        raise PublishError(f"Failed to post story for opportunity {opp.id} to any channel")
    return result


async def publish_stories(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
    client: TelegramClient | None,
) -> None:
    """Post every starred, not-yet-posted story. `client` must be the primary
    userbot (the channel admin), already connected."""
    async with session_factory() as session:
        repo = OpportunityRepository(session)
        starred = await repo.get_story_pending()
        # Starred while still only approved: stays queued until its post is
        # live (usually earlier in this same run, via publish_scheduled).
        pending = [o for o in starred if o.published_message_id is not None]

        logger.info(
            "publishing_due_stories",
            count=len(pending),
            waiting_for_publish=len(starred) - len(pending),
        )
        if not pending:
            return
        if client is None or not client.is_connected():
            logger.warning("story_publish_skipped_no_client", count=len(pending))
            return
        # A fresh StringSession has an empty entity cache and can't resolve a
        # bare -100... channel id until it has seen the dialog list.
        await client.get_dialogs(limit=None)

        failures: list[str] = []
        partials: list[str] = []

        # No session.rollback() anywhere in this loop: nothing is dirty when
        # post_story() raises, and a rollback would expire every other loaded
        # row -- the next iteration's attribute reads would then lazy-load and
        # raise MissingGreenlet, aborting the rest of the batch.
        for opp in pending:
            opp_id, title = opp.id, opp.title or "Untitled"
            try:
                result = await post_story(settings, client, opp)
            except Exception as e:
                logger.exception("story_publish_error", opp_id=opp_id)
                # Un-queue rather than retry every run: the usual causes (no
                # "Post Stories" right, message deleted) are permanent, and a
                # retry loop would re-alert the admins on every run.
                opp.story_requested_at = None
                await session.commit()
                failures.append(f"#{opp_id} {title}: {type(e).__name__}: {e}")
                continue

            opp.story_posted_at = datetime.now(tz=timezone.utc).replace(tzinfo=None)
            await session.commit()
            failed_ids = [c for c, _ in result.failed]
            logger.info("story_posted", opp_id=opp_id, succeeded=result.succeeded, failed=failed_ids)
            if failed_ids:
                partials.append(
                    f"#{opp_id} {title}: story sent to {result.succeeded}, FAILED {failed_ids}"
                )

        if failures or partials:
            lines: list[str] = []
            if failures:
                lines.append(
                    "⚠️ Failed to post {} starred stor{} (tap 📸 Story again to retry):".format(
                        len(failures), "y" if len(failures) == 1 else "ies"
                    )
                )
                lines += [f"• {f}" for f in failures[:10]]
            if partials:
                lines.append(
                    "⚠️ Story posted to only SOME channels ({}, not retried):".format(len(partials))
                )
                lines += [f"• {p}" for p in partials[:10]]
            await notify_admins(bot, settings.ADMIN_IDS, "\n".join(lines))
