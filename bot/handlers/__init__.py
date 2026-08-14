"""Пакет обработчиков (handlers)."""
from __future__ import annotations

from aiogram import Router

from bot.handlers import common, errors, fallback, google, input_handlers, photo


def build_main_router() -> Router:
    """Собирает дерево роутеров.

    Порядок критичен: state-хендлеры (input/photo/google) ДО fallback,
    иначе общий обработчик перехватывает ввод телефона/фото/видео.
    """
    main_router = Router()
    main_router.include_routers(
        common.router,
        input_handlers.router,
        photo.router,
        google.router,
        fallback.router,  # последний — только текст, только когда никто не подхватил
    )
    return main_router


def register(dp) -> None:
    dp.include_router(build_main_router())
    # Глобальный перехватчик ошибок: молчание на упавших хендлерах → сообщение
    dp.errors.register(errors.on_error)