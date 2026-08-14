"""Фильтры для aiogram."""
from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import Message, TelegramObject, User

from bot.loader import SETTINGS


class IsAdmin(BaseFilter):
    """Пропускает только пользователей из ADMIN_IDS (или всех, если RESTRICT_TO_ADMINS=false)."""

    async def __call__(self, obj: TelegramObject) -> bool:
        if not SETTINGS.restrict_to_admins:
            return True
        user: User | None = getattr(obj, "from_user", None)
        return user is not None and user.id in SETTINGS.admin_ids