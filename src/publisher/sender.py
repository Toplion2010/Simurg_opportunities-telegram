import os
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.types import BufferedInputFile, FSInputFile

from src.core.config import Settings
from src.core.enums import OpportunityStatus
from src.core.exceptions import PublishError
from src.core.logging import get_logger
from src.db.models.opportunity import Opportunity
from src.publisher.formatter import format_opportunity

logger = get_logger(__name__)


class OpportunitySender:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def publish(self, opp: Opportunity, bot: Bot) -> None:
        caption = format_opportunity(opp)
        chat_id = self._settings.DEST_CHANNEL_ID

        try:
            from src.publisher.image_gen import generate_card
            img_bytes = await generate_card(opp)
            photo = BufferedInputFile(img_bytes, filename="card.jpg")
            await bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                parse_mode="HTML",
            )

            opp.status = OpportunityStatus.published
            opp.published_at = datetime.now(tz=timezone.utc).replace(tzinfo=None)
            logger.info("opportunity_published", opp_id=opp.id, title=opp.title)

        except Exception as e:
            logger.exception("publish_failed", opp_id=opp.id, error=str(e))
            raise PublishError(f"Failed to publish opportunity {opp.id}: {e}") from e
