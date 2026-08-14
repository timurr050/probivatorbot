"""Fallback-обработчик: обычный текст вне FSM-состояний.

Подключается ПОСЛЕДНИМ (см. bot/handlers/__init__.py), чтобы никогда не
перехватывать события, адресованные state-хендлерам (телефон/ник/email/фото).
Ограничен фильтром F.text: документы/фото/видео он не трогает.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from bot.filters import IsAdmin
from bot.keyboards import main_menu

router = Router(name="fallback")


@router.message(IsAdmin(), F.text)
async def on_unexpected_text(message: Message) -> None:
    await message.answer(
        "ℹ️ Используйте меню. Нажми <b>«📐 Форматы ввода»</b> для подсказки.",
        reply_markup=main_menu(),
    )