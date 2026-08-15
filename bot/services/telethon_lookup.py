"""
Telethon: перебор всех Telegram-сессий по очереди.

В .env можно указать сколько угодно аккаунтов (TG_ACCOUNTS — JSON-словарь
phone:session_file). Бот пробует сессии по порядку: первая авторизованная,
которая смогла найти цель, возвращает результат; если сессия не авторизована
или выдала ошибку — берётся следующая.
"""
from __future__ import annotations

from bot.config import SETTINGS
from bot.exceptions import ToolNotConfigured
from bot.services.base import session_path


def require_telethon() -> None:
    """Проверяет, что Telethon настроен и есть хотя бы одна сессия."""
    if not SETTINGS.is_telethon_ready:
        raise ToolNotConfigured(
            "Telethon не настроен.\nДобавьте в .env:\n"
            "<code>TG_API_ID</code> и <code>TG_API_HASH</code> "
            "(https://my.telegram.org/apps)\n"
            "и пары <code>phone</code>:<code>session_file</code> в "
            "<code>TG_ACCOUNTS</code>.\n"
            "Чем больше сессий — тем надёжнее поиск (бот перебирает их по очереди)."
        )
    if not SETTINGS.tg_accounts:
        raise ToolNotConfigured(
            "Не заданы Telegram-аккаунты (<code>TG_ACCOUNTS</code> в .env).\n"
            'Пример: {"+375291234567": "sess_1", "+79001234567": "sess_2"}\n'
            "Создать сессию: <code>python session_maker.py</code>"
        )


async def for_each_session(handler):
    """Перебирает сессии по очереди.

    handler(client, phone) → dict (непустой словарь = результат, стоп) | None.
    Возвращает (результат, [заметки по сессиям]).
    """
    require_telethon()

    from telethon import TelegramClient

    hints: list[str] = []
    for phone, session_name in SETTINGS.tg_accounts.items():
        client = TelegramClient(
            session_path(session_name),
            api_id=SETTINGS.tg_api_id,
            api_hash=SETTINGS.tg_api_hash,
        )
        try:
            await client.connect()
            if not await client.is_user_authorized():
                hints.append(f"{phone}: не авторизована")
                continue
            result = await handler(client, phone)
            if result:
                return result, hints
            hints.append(f"{phone}: пустой результат")
        except Exception as exc:  # noqa: BLE001 — одна сессия не должна ломать все
            hints.append(f"{phone}: {type(exc).__name__}")
        finally:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
    return None, hints
