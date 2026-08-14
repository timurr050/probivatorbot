"""Глобальный обработчик исключений диспетчера.

Без него aiogram молча логирует упавший хендлер в консоль и ничего не
отправляет пользователю — бот выглядит «молчащим» на номера/фото. Теперь
любая ошибка превращается в видимое сообщение.
"""
from __future__ import annotations

import logging

from aiogram.types import ErrorEvent

from bot.texts import error_text

logger = logging.getLogger("probivbot")


async def on_error(event: ErrorEvent) -> None:
    exc = event.exception
    logger.exception("Unhandled error in update %s: %s", event.update, exc)

    msg = event.update.message
    if msg is None and event.update.callback_query is not None:
        msg = event.update.callback_query.message
    if msg is None:
        return

    text = error_text(f"{type(exc).__name__}: {exc}")
    try:
        await msg.answer(text)
    except Exception:  # noqa: BLE001 — самим ответить не смогли, что-то с сетью
        logger.exception("Failed to send error notification")
