from dataclasses import dataclass, field
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.types import BufferedInputFile

from src.core.config import Settings
from src.core.enums import Audience, OpportunityStatus
from src.core.exceptions import PublishError
from src.core.logging import get_logger
from src.db.models.opportunity import Opportunity
from src.publisher.formatter import format_opportunity

logger = get_logger(__name__)

# Telegram's hard limit for a photo caption. Truncating the formatted HTML to
# fit risks cutting inside a tag (e.g. an unclosed <a>), which trades this
# error for a "can't parse entities" one. Sending the photo with a short
# caption and the full text as a follow-up message loses nothing instead.
_CAPTION_LIMIT = 1024


@dataclass
class PublishResult:
    """Outcome of publishing to one or more channels.

    A non-empty ``succeeded`` with a non-empty ``failed`` is a *partial* publish:
    the opportunity is still marked published (it's live somewhere) so the
    scheduler never resends it, and the admin is warned about the failed leg.
    """

    succeeded: list[int] = field(default_factory=list)
    failed: list[tuple[int, str]] = field(default_factory=list)  # (chat_id, error)


class OpportunitySender:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _resolve_targets(self, audience: Audience) -> list[int]:
        school = self._settings.DEST_CHANNEL_ID_SCHOOL
        university = self._settings.DEST_CHANNEL_ID_UNIVERSITY
        # Total over the 3 Audience members — 'none' structurally can't exist here.
        if audience == Audience.school:
            return [school]
        if audience == Audience.university:
            return [university]
        return [school, university]  # both

    async def publish(self, opp: Opportunity, bot: Bot) -> PublishResult:
        # format_opportunity trims the About section to fit _CAPTION_LIMIT when
        # possible, so the common case (an overlong description) stays a single
        # message. `caption` keeps the untrimmed text for the rare case where
        # even eligibility/prize/notes alone don't fit — the last-resort
        # follow-up message below.
        caption = format_opportunity(opp)
        photo_caption = format_opportunity(opp, max_length=_CAPTION_LIMIT)
        targets = self._resolve_targets(opp.audience)

        # Generate the card ONCE — Gemini + Playwright render is expensive and
        # non-deterministic per call, so a "both" post must reuse one image.
        try:
            from src.publisher.image_gen import generate_card
            img_bytes = await generate_card(opp)
        except Exception as e:
            logger.exception("publish_failed", opp_id=opp.id, error=str(e))
            raise PublishError(f"Failed to render card for opportunity {opp.id}: {e}") from e

        overlong = len(photo_caption) > _CAPTION_LIMIT
        if overlong:
            photo_caption = f"<b>✨ {opp.title or 'Opportunity'}</b>"

        result = PublishResult()
        for chat_id in targets:
            try:
                photo = BufferedInputFile(img_bytes, filename="card.jpg")
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=photo_caption,
                    parse_mode="HTML",
                )
                if overlong:
                    await bot.send_message(chat_id=chat_id, text=caption, parse_mode="HTML")
                result.succeeded.append(chat_id)
            except Exception as e:
                logger.exception(
                    "publish_failed_channel", opp_id=opp.id, chat_id=chat_id, error=str(e)
                )
                result.failed.append((chat_id, str(e)))

        # Total failure (nothing sent) → raise so nothing commits and it's retried.
        if not result.succeeded:
            raise PublishError(f"Failed to publish opportunity {opp.id} to any channel")

        # Any success (full OR partial) → mark published so the scheduler won't resend
        # to the channel(s) that already received it.
        opp.status = OpportunityStatus.published
        opp.published_at = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        logger.info(
            "opportunity_published",
            opp_id=opp.id,
            title=opp.title,
            audience=opp.audience.value,
            succeeded=result.succeeded,
            failed=[c for c, _ in result.failed],
        )
        return result
