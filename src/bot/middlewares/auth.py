from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from src.core.logging import get_logger

logger = get_logger(__name__)


class AdminAuthMiddleware(BaseMiddleware):
    def __init__(self, admin_ids: list[int]) -> None:
        self._admin_ids = set(admin_ids)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.id not in self._admin_ids:
            if user:
                logger.warning("unauthorized_access", user_id=user.id, username=user.username)
            return None
        return await handler(event, data)
