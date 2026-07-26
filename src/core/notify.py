from aiogram import Bot

from src.core.logging import get_logger

logger = get_logger(__name__)


async def notify_admins(bot: Bot, admin_ids: list[int], text: str) -> None:
    """Best-effort broadcast to admins. Never raises — a blocked or deleted admin
    chat must not take down the caller (batch run, userbot supervisor, ...)."""
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            logger.exception("admin_notify_failed", admin_id=admin_id)
